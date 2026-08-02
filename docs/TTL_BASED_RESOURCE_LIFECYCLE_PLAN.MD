# TTL-Based Resource Lifecycle Management - Implementation Plan

## Overview

Implement a full lifecycle flow for AWS resource management:
**Tag Policies → Discover Resources → Apply TTL Tags → Monitor Expiration → Notify via Slack → User Decision → Action**

## Current State (Updated: 2026-01-12)

| Component | Status | Location |
|-----------|--------|----------|
| Tag Policies | **Complete** | `commands/policy_commands.py`, `services/policy_builder_service.py` |
| Resource Discovery | **Complete** | `modules/discovery.py`, `commands/discovery_commands.py` |
| Resource Tracking | **Complete** | `database/models.py` (Resource model) |
| TTL Fields | **Complete** | `expires_at`, `lifecycle_state`, `delete_after`, `protected`, `warned_at`, `warning_count` |
| Resource TTL Source Fields | **Complete** | `ttl_source`, `ttl_tag_key`, `owner_email`, `grace_period_ends_at` |
| ResourceLifecyclePolicy Model | **Complete** | `database/models.py` - full policy configuration |
| LifecycleAuditLog Model | **Complete** | `database/models.py` - tracks lifecycle operations |
| LifecycleNotification Table | **Complete** | `database/models.py` - tracks sent notifications |
| LifecycleDecision Table | **Complete** | `database/models.py` - tracks user decisions |
| TTL Parser Service | **Complete** | `services/ttl_parser_service.py` - parses duration, ISO, timestamp formats |
| Slack Notification Service | **Complete** | `services/slack_notification_service.py` - webhook-based notifications |
| Lifecycle Commands App | **Complete** | `commands/lifecycle_commands.py` - standalone Typer app |
| `lifecycle scan` | **Complete** | Shows expired, expiring soon, active resources with TTL |
| `lifecycle set-ttl` | **Complete** | Set TTL on resources (by ARN, service, or policy) |
| `lifecycle delete` | **Complete** | Delete expired resources with warning period logic |
| `lifecycle policies` | **Complete** | List and manage lifecycle policies |
| `lifecycle extend` | **Complete** | Extend TTL for resources by ARN or service filter |
| `lifecycle protect` | **Complete** | Protect/unprotect resources from automated deletion |
| `lifecycle review` | **Complete** | Interactive TUI to review and act on expiring resources |
| `lifecycle notify-setup` | **Complete** | Configure Slack webhook for notifications |
| `lifecycle notify` | **Complete** | Send Slack notifications for expiring resources |
| Database Migration | **Complete** | `migrations/versions/007_add_lifecycle_notifications.py` |

---

## Implementation Plan

### Phase 1: TTL Tag Parser Service

**New file:** `tag_manager_cli/services/ttl_parser_service.py`

```
Supported tag names:
- tag-manager:TTL, tag-manager:ExpireAfter, tag-manager:DeleteAfter
- TTL, ExpirationDate, DeleteAfter (compatibility)

Supported formats:
- Duration: "30d", "6m", "1y", "2w"
- ISO date: "2025-03-15", "2025-03-15T14:30:00Z"
- Unix timestamp: "1742054400"

Functions:
- parse_ttl_value(value: str) -> Optional[datetime]
- extract_ttl_from_tags(tags: Dict) -> Optional[datetime]
- validate_ttl_tag(key: str, value: str) -> Tuple[bool, str]
```

---

### Phase 2: Slack Notification Service

**New file:** `tag_manager_cli/services/slack_notification_service.py`

Uses **Slack Incoming Webhooks** (simplest, no Docker):
- User creates webhook URL in Slack workspace settings
- CLI stores webhook URL in `~/.tag-manager/config.json`
- Simple HTTP POST with formatted message blocks

```python
class SlackNotificationService:
    def send_expiration_warning(resources: List[Resource], days: int) -> bool
    def send_batch_summary(summary: Dict) -> bool
    def test_webhook(webhook_url: str) -> bool
```

**Message format:**
```
[TAG-MANAGER] 5 Resources Expiring Soon

EXPIRING IN 3 DAYS:
- i-0abc123 (EC2 Instance) - us-east-1
- bucket-dev (S3 Bucket) - us-west-2

Actions: Run `bluearch-aws-tags lifecycle review` to manage these resources.
```

**Config storage:** `~/.tag-manager/config.json`
```json
{
  "slack_webhook_url": "https://hooks.slack.com/services/T.../B.../xxx",
  "notify_on_warning_days": [7, 3, 1],
  "notify_channel": "#aws-alerts"
}
```

---

### Phase 3: Database Schema Updates

**File:** `tag_manager_cli/database/models.py`

**New tables:**

1. `LifecycleNotification` - Track sent notifications
   - `id`, `batch_id`, `resource_arn`
   - `notification_type` (warning_7d, warning_3d, final)
   - `channel` (slack, cli)
   - `status` (pending, sent, failed)
   - `sent_at`, `created_at`

2. `LifecycleDecision` - Track user decisions
   - `id`, `resource_arn`
   - `decision_type` (extend, protect, terminate, skip)
   - `previous_expires_at`, `new_expires_at`
   - `decided_by`, `decided_at`

**Updates to Resource table:**
```python
ttl_source = Column(String(50))  # 'tag', 'policy', 'manual'
ttl_tag_key = Column(String(256))
owner_email = Column(String(256), index=True)
grace_period_ends_at = Column(DateTime)
```

**Updates to ResourceLifecyclePolicy table:**
```python
warning_schedule = Column(JSON)  # [7, 3, 1] days before
grace_period_days = Column(Integer, default=7)
auto_delete_enabled = Column(Boolean, default=False)
```

**Migration:** `migrations/versions/XXX_add_lifecycle_notifications.py`

---

### Phase 4: Interactive Review Mode

**File:** `tag_manager_cli/commands/unified_tags.py` (extend lifecycle subcommand)

**New commands:**

```bash
# Interactive review - TUI-like interface
bluearch-aws-tags lifecycle review

# Bulk operations
bluearch-aws-tags lifecycle extend --resource-arn <arn> --days 30
bluearch-aws-tags lifecycle extend --services ec2 --days 14
bluearch-aws-tags lifecycle protect --resource-arn <arn> --reason "Production"
bluearch-aws-tags lifecycle protect --resource-arn <arn> --unprotect

# Notification management
bluearch-aws-tags lifecycle notify-setup  # Configure Slack webhook
bluearch-aws-tags lifecycle notify --test # Test notification
bluearch-aws-tags lifecycle notify        # Send pending notifications

# View decisions
bluearch-aws-tags lifecycle review --include-active
```

**Interactive review UI:**
```
TTL Resource Review
===================

[1/12] i-0abc123def (EC2 Instance)
       Region: us-east-1 | Account: 123456789012
       Expires: 2025-01-20 (3 days)
       Tags: Environment=dev, Owner=team@example.com

Actions:
  [E] Extend 30 days    [P] Protect    [T] Terminate now
  [S] Skip              [D] Details    [Q] Quit review

Choice: _
```

---

### Phase 5: Full Flow Integration

**Public command group:** `bluearch-aws-tags lifecycle`

**Complete workflow:**

```bash
# 1. Setup (one-time)
bluearch-aws-tags lifecycle notify-setup
# Prompts for Slack webhook URL, warning days [7,3,1], etc.

# 2. Create lifecycle policy
bluearch-aws-tags lifecycle policy-create --name "dev-cleanup" --ttl-days 30 --warning-days 7,3,1

# 3. Discover resources and apply TTL
bluearch-aws-tags discover all
bluearch-aws-tags lifecycle apply-policies
# OR apply TTL manually:
bluearch-aws-tags lifecycle set-ttl --services ec2 --ttl-days 30

# 4. Scan for expiring resources
bluearch-aws-tags lifecycle scan
# Shows: 5 expiring in 7 days, 2 expiring in 3 days, 1 expired

# 5. Send notifications
bluearch-aws-tags lifecycle notify
# Sends Slack message for resources matching warning thresholds

# 6. User reviews and decides
bluearch-aws-tags lifecycle review
# Interactive mode to extend/protect/terminate each resource

# 7. Execute deletions
bluearch-aws-tags lifecycle delete-expired --dry-run
bluearch-aws-tags lifecycle delete-expired --confirm
```

---

### Phase 6: Lifecycle State Machine

```
                    [active]
                       |
               [TTL tag applied]
                       |
                       v
                 [ttl_active] ----[extend]----> [ttl_active]
                       |
              [warning threshold]
                       |
                       v
                  [warning] ----[extend]----> [ttl_active]
                       |
                 [TTL expires]
                       |
                       v
                  [expired] ----[extend]----> [ttl_active]
                       |
              [grace period ends]
                       |
                       v
              [marked_for_deletion]
                       |
                 [user confirms]
                       |
                       v
                  [deleted]

[Any state] --[protect]--> [protected] --[unprotect]--> [original state]
```

---

## Files to Create/Modify

| File | Action | Status | Purpose |
|------|--------|--------|---------|
| `commands/lifecycle_commands.py` | Create | **Done** | Standalone lifecycle Typer app with all commands |
| `database/models.py` | Modify | **Done** | LifecycleNotification, LifecycleDecision tables + Resource/Policy fields |
| `services/ttl_parser_service.py` | Create | **Done** | TTL tag parsing (duration, ISO, timestamp) |
| `services/slack_notification_service.py` | Create | **Done** | Slack webhook notifications |
| `migrations/versions/007_add_lifecycle_notifications.py` | Create | **Done** | Database migration for new tables/columns |
| `integrations/iam-policy.json` | No change | N/A | No new AWS permissions needed for Slack |

---

## Testing Checklist

### All Features Implemented
- [x] Grace period logic works correctly (7-day warning before deletion)
- [x] Audit logging captures lifecycle operations (LifecycleAuditLog)
- [x] Dry-run mode works for deletions (`lifecycle delete --dry-run`)
- [x] Scan command groups resources by state correctly
- [x] Set-ttl command applies TTL to resources
- [x] TTL parser handles all formats (duration, ISO, epoch)
- [x] Slack webhook sends correctly formatted messages
- [x] Interactive review mode handles all actions (extend, protect, delete, skip)
- [x] Extend command updates database correctly
- [x] Protect/unprotect updates database correctly
- [x] Notifications track sent status in LifecycleNotification table
- [x] LifecycleDecision records all user decisions

### Integration Testing (Recommended)
- [ ] Test complete flow: discover -> set-ttl -> scan -> notify -> review -> delete
- [ ] Test Slack notification delivery with real webhook
- [ ] Test edge cases (already expired, protected resources)
- [ ] Verify audit logging captures all operations

---

## User Experience Flow

```
User runs: bluearch-aws-tags lifecycle review

+--------------------------------------------------+
| TTL Resource Review                              |
| ================================================ |
|                                                  |
| [1/5] i-0abc123def (EC2 Instance)               |
|       Region: us-east-1                          |
|       Expires: 2025-01-20 (3 days)              |
|       Cost: ~$45/month                           |
|                                                  |
| [E] Extend  [P] Protect  [T] Terminate  [S] Skip |
+--------------------------------------------------+

User presses 'E':

+--------------------------------------------------+
| Extend TTL                                       |
| ------------------------------------------------ |
| Current expiration: 2025-01-20                   |
|                                                  |
| Extend by:                                       |
| [1] 7 days   [2] 14 days   [3] 30 days          |
| [4] 60 days  [5] 90 days   [C] Custom           |
+--------------------------------------------------+

User presses '3':

[OK] Extended i-0abc123def by 30 days (new expiration: 2025-02-19)

Moving to next resource...
```

---

## Trello Board: TTL Resource Lifecycle

### List: Done

---

**Card: Core Database Schema**
Labels: `backend` `database`

Checklist:
- [x] `Resource` model with TTL fields (`expires_at`, `lifecycle_state`, `delete_after`, `protected`)
- [x] `Resource` model with warning tracking (`warned_at`, `warning_count`, `lifecycle_policy_id`)
- [x] `ResourceLifecyclePolicy` model with full configuration
- [x] `LifecycleAuditLog` model for tracking operations
- [x] Indexes for lifecycle queries

---

**Card: Database Schema Updates (Extended)**
Labels: `backend` `database`

Checklist:
- [x] Add `LifecycleNotification` table to models.py
- [x] Add `LifecycleDecision` table to models.py
- [x] Add `ttl_source`, `ttl_tag_key`, `owner_email`, `grace_period_ends_at` to Resource
- [x] Add `warning_schedule`, `grace_period_days`, `auto_delete_enabled` to ResourceLifecyclePolicy
- [x] Create Alembic migration file (`007_add_lifecycle_notifications.py`)

---

**Card: TTL Tag Parser Service**
Labels: `backend` `core`

Checklist:
- [x] Create `tag_manager_cli/services/ttl_parser_service.py`
- [x] Implement `parse_ttl_value()` - duration format (30d, 6m, 1y)
- [x] Implement `parse_ttl_value()` - ISO date format (2025-03-15)
- [x] Implement `parse_ttl_value()` - Unix timestamp format
- [x] Implement `extract_ttl_from_tags()` - check all supported tag names
- [x] Implement `validate_ttl_tag()` - return validation errors
- [x] Handle edge cases (invalid formats, past dates)

---

**Card: Slack Notification Service**
Labels: `backend` `notifications`

Checklist:
- [x] Create `tag_manager_cli/services/slack_notification_service.py`
- [x] Implement `test_webhook()` - verify webhook URL works
- [x] Implement `send_expiration_warning()` - batch notifications
- [x] Implement `send_batch_summary()` - daily summary
- [x] Add config storage in `~/.tag-manager/config.json`
- [x] Handle HTTP errors

---

**Card: Lifecycle Commands - Core**
Labels: `cli` `core`

Checklist:
- [x] Create `tag_manager_cli/commands/lifecycle_commands.py` with Typer app
- [x] `lifecycle scan` - Show expired, expiring soon, active resources
- [x] `lifecycle set-ttl` - Set TTL by ARN, service, or policy
- [x] `lifecycle delete` - Delete expired resources with warning period
- [x] `lifecycle policies` - List lifecycle policies
- [x] Warning period logic (7-day grace period before deletion)
- [x] Audit logging for lifecycle operations

---

**Card: Bulk Lifecycle Commands**
Labels: `cli`

Checklist:
- [x] Implement `lifecycle extend` command with `--days`, `--resource-arn`, `--services` options
- [x] Implement `lifecycle protect` command with `--reason` option
- [x] Implement `lifecycle protect --unprotect` to remove protection
- [x] Implement `lifecycle protect --list` to view protected resources
- [x] Add confirmation prompts for bulk operations
- [x] Add `--dry-run` flag for preview
- [x] Update database and audit log

---

**Card: Interactive Review Mode**
Labels: `cli` `ux`

Checklist:
- [x] Implement `lifecycle review` command
- [x] Query database for expiring/expired resources
- [x] Display resource details (ARN, type, region, tags, expiry)
- [x] Implement [E] Extend action with day selection
- [x] Implement [P] Protect action with reason prompt
- [x] Implement [D] Delete (mark for deletion) action with confirmation
- [x] Implement [S] Skip action
- [x] Implement [Q] Quit action
- [x] Show progress counter (e.g., [3/12])
- [x] Log all decisions to LifecycleDecision table
- [x] Handle empty results gracefully

---

**Card: Slack Setup Command**
Labels: `cli` `notifications`

Checklist:
- [x] Implement `lifecycle notify-setup` command
- [x] Prompt for Slack webhook URL (interactive or `--webhook-url`)
- [x] Configure warning days schedule (`--warning-days`)
- [x] Validate webhook URL with test message
- [x] Save config to `~/.tag-manager/config.json`
- [x] Implement `--show` to view current config
- [x] Implement `--disable` to turn off notifications
- [x] Show success/failure feedback

---

**Card: Lifecycle Notify Command**
Labels: `cli` `notifications`

Checklist:
- [x] Implement `lifecycle notify` command
- [x] Query resources matching warning schedule (7, 3, 1 days)
- [x] Group resources by warning tier
- [x] Send Slack notifications via SlackNotificationService
- [x] Record sent notifications in database
- [x] Show summary of sent notifications
- [x] Add `--dry-run` flag to preview without sending
- [x] Add `--test` flag to send test notification
- [x] Add `--summary` flag to send batch summary

---

### List: Backlog (Future Enhancements)

---

**Card: Lifecycle Scan Command - Enhancements**
Labels: `cli`

Checklist:
- [ ] Filter by region
- [ ] Filter by days until expiry
- [ ] Output formats: json, csv
- [ ] Add `--output` flag for format selection

---

**Card: Full Flow Integration Testing**
Labels: `integration` `testing`

Checklist:
- [ ] Test complete flow: discover -> set-ttl -> scan -> notify -> review -> delete
- [ ] Test edge cases (already expired, protected resources)
- [ ] Test Slack notification delivery
- [ ] Verify audit logging captures all operations
- [ ] Add integration tests

---

**Card: Documentation**
Labels: `docs`

Checklist:
- [ ] Add lifecycle section to README
- [ ] Document Slack webhook setup steps
- [ ] Document complete workflow with examples
- [ ] Document TTL tag formats
- [ ] Update CLAUDE.md with new commands

---

## CLI Simplification Plan (2026-01-13)

### Vision
Make lifecycle the **flagship feature** of the CLI. Target audience: non-experienced AWS users who need to stop zombie resources from being created to keep a ceiling on costs.

### Business Case
User needs to stop zombie resources from being created. Solution: TTL and owner tags on all NEW and EXISTING resources, then provide services to update and delete resources that need attention.

### New CLI Structure

```
bluearch-aws-tags
├── lifecycle (FLAGSHIP)
│   ├── wizard        # End-to-end guided workflow for new users
│   ├── scan          # Scan for resources (auto multi-account if configured)
│   ├── set-ttl       # Apply TTL tags
│   ├── review        # Interactive TUI to review expiring resources
│   ├── extend        # Extend TTL for resources
│   ├── protect       # Protect resources from deletion
│   ├── delete        # Delete expired resources
│   ├── notify        # Send Slack notifications
│   ├── notify-setup  # Configure Slack webhook
│   └── policies      # Lifecycle policies
├── ask               # AI helper (top-level, can execute commands)
├── setup             # First-time setup wizard
│   ├── wizard        # Complete guided setup
│   ├── validate      # Check system health
│   └── multi-accounts  # Configure cross-account scanning
├── update            # Update CLI version
└── uninstall         # Remove CLI and resources
```

### Commands to Remove (from top-level)
| Command | Status |
|---------|--------|
| `discover` | **REMOVED** - Merged into `lifecycle scan` |
| `tags` | **REMOVED** - Merged into lifecycle |
| `cost` | **REMOVED** - Too complex for core flow |
| `policy` | **RE-ENABLED** - Part of hybrid policy system |
| `alarms` | **REMOVED** - Tangential feature |
| `accounts` | **REMOVED** - Merged into `setup multi-accounts` |

### Implementation Tasks

| Task | Status |
|------|--------|
| Add `lifecycle wizard` command | **COMPLETE** |
| Merge discovery into `lifecycle scan` | **COMPLETE** |
| Merge accounts into `setup multi-accounts` | **COMPLETE** |
| Remove tangential commands from main.py | **COMPLETE** |
| Update main help text | **COMPLETE** |
| Update onboarding flow | **COMPLETE** |
| Re-enable `policy` command (hybrid system) | **COMPLETE** |
| Add `--check-compliance` to scan | **COMPLETE** |
| Add `--noncompliant` to scan/set-ttl | **COMPLETE** |

### Decisions Made
1. **No backwards compatibility** - Remove `discover`, `tags` completely once merged
2. **Multi-account scanning** - Default when `setup multi-accounts` is configured
3. **AI capabilities** - Full command execution (not read-only)
4. **Slack notifications in wizard** - Keep optional
5. **Hybrid policy system** - Both AWS Org Tag Policies and Local Lifecycle Policies

---

## Hybrid Policy System (Implemented 2026-01)

Re-enabled the `policy` command to create a hybrid approach: users can use either AWS Organizations Tag Policies (enterprise governance) or Local Lifecycle Policies (quick setup), or both together.

### Updated CLI Structure

```
bluearch-aws-tags
├── lifecycle (FLAGSHIP)
│   ├── wizard        # End-to-end guided workflow for new users
│   ├── scan          # Scan for resources (--check-compliance, --noncompliant)
│   ├── set-ttl       # Apply TTL tags (--noncompliant)
│   ├── review        # Interactive TUI to review expiring resources
│   ├── extend        # Extend TTL for resources
│   ├── protect       # Protect resources from deletion
│   ├── delete        # Delete expired resources
│   ├── notify        # Send Slack notifications
│   ├── notify-setup  # Configure Slack webhook
│   └── policies      # Local lifecycle policies
├── policy (RE-ENABLED)  # AWS Org Tag Policies (enterprise)
│   ├── check-access     # Check if AWS Org access is available
│   ├── view             # List AWS Org tag policies
│   ├── create           # Create new AWS Org tag policy
│   └── check-compliance # Check resource compliance
├── ask               # AI helper (top-level, can execute commands)
├── setup             # First-time setup wizard
│   ├── wizard        # Complete guided setup
│   ├── validate      # Check system health
│   └── multi-accounts  # Configure cross-account scanning
├── update            # Update CLI version
└── uninstall         # Remove CLI and resources
```

### AWS Tags Applied by set-ttl

| Tag | Description |
|-----|-------------|
| `bluearch:ttl` | Expiration date (YYYY-MM-DD format) |
| `bluearch:policy` | Policy name that triggered the TTL |
| `bluearch:policy-source` | `aws_org`, `local`, or `manual` |
| `bluearch:owner` | Owner email (if specified in policy or manual) |
| `bluearch:noncompliant-tags` | Missing/invalid tags (if from AWS Org policy) |

### New Database Fields (Resource Model)

| Field | Type | Description |
|-------|------|-------------|
| `policy_source` | String(50) | `aws_org`, `local`, or `manual` |
| `org_policy_id` | String(100) | AWS Org policy ID (if applicable) |
| `org_policy_name` | String(255) | AWS Org policy name (if applicable) |
| `compliance_status` | String(50) | `compliant`, `noncompliant`, `unknown` |
| `missing_tags` | JSON | List of missing required tags |
| `invalid_tags` | JSON | Tags with invalid values |
| `last_compliance_check` | DateTime | When compliance was last checked |

### New Scan Flags

```bash
# Check AWS Org Tag Policy compliance for all resources
bluearch-aws-tags lifecycle scan --check-compliance

# Show only noncompliant resources (missing required tags)
bluearch-aws-tags lifecycle scan --noncompliant
```

### New set-ttl Flag

```bash
# Apply TTL only to noncompliant resources (from AWS Org policy check)
bluearch-aws-tags lifecycle set-ttl --noncompliant --ttl-days 14
```

### Workflow: Using Both Policy Types Together

```bash
# 1. Check if you have AWS Org access
bluearch-aws-tags policy check-access

# 2a. If yes: View/create AWS Org Tag Policies
bluearch-aws-tags policy view
bluearch-aws-tags policy create

# 2b. Also create local policies for quick TTL rules
bluearch-aws-tags lifecycle policies create

# 3. Scan and check compliance
bluearch-aws-tags lifecycle scan --check-compliance

# 4. Apply TTL to noncompliant resources
bluearch-aws-tags lifecycle set-ttl --noncompliant --ttl-days 14

# 5. Review expiring resources
bluearch-aws-tags lifecycle review
```

### Database Migration

Migration `008_add_policy_source_tracking.py` adds the policy source tracking fields to the `resources` table, enabling the hybrid policy system.
