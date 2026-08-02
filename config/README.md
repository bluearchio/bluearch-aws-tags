# Tag Manager Configuration Files

This directory contains various tagging rule configurations for the AWS Tag Manager CLI.

## Rule Sets

### 1. safe_default_rules.json (Legacy Example)
**Purpose:** Reference data for the retired tagging-rule loader
- Sets `Environment=unknown` and `Owner=unknown` on resources
- Adds `NeedsReview=true` flag for easy identification
- Marks resources with `ManagedBy=tag-manager-setup`
- **Won't break anything** - just marks resources for review

### 2. production_tagging_rules.json
**Purpose:** Production-ready governance and cost tracking rules
- Enforces core governance tags (Environment, Owner, Project, CostCenter)
- Adds cost tracking tags (Team, Department, BudgetCode)
- Includes lifecycle management tags
- Compliance and security classification

### 3. sample_tagging_rules.json
**Purpose:** Example rules showing various tagging patterns
- Environment classification based on naming
- Creator attribution from CloudTrail
- Cost center assignment
- Time-based lifecycle tagging

### 4. advanced_tagging_rules.json
**Purpose:** Comprehensive tagging with advanced patterns
- Lifecycle automation
- Cost optimization tagging
- Compliance and security enforcement
- Operational metadata
- Resource relationship tracking

## Usage

### Supported Public Workflow

These JSON files are retained as examples of the legacy tagging-rule format.
The public CLI does not expose a command that loads them. Create and apply a
supported lifecycle policy instead:

```bash
bluearch-aws-tags lifecycle policies create
bluearch-aws-tags lifecycle scan
bluearch-aws-tags lifecycle set-ttl --dry-run
```

## Safety Notes

- **safe_default_rules.json** is designed to be completely safe - it only adds informational tags that won't affect resource behavior
- All "unknown" values are intentionally non-operational to ensure resources continue functioning normally
- The `NeedsReview=true` tag makes it easy to find resources that need proper classification later

## Best Practices

1. **Treat these files as reference data**, not commands accepted by the public CLI
2. **Create lifecycle policies** with `bluearch-aws-tags lifecycle policies create`
3. **Preview changes** with `bluearch-aws-tags lifecycle set-ttl --dry-run`
4. **Review policy compliance** with `bluearch-aws-tags policy check-compliance`
