# AWS Tag Manager CLI - Overview

## What is it?

AWS Tag Manager CLI helps you **stop zombie AWS resources** from eating your budget. It ensures every resource has a TTL (time-to-live) and owner tag, then helps you manage resources that are about to expire.

## Core Problem We Solve

> "We're spending too much on AWS because no one knows which resources are still needed."

**Solution**: Every resource gets:
- A **TTL tag** (when should this resource expire?)
- An **owner tag** (who is responsible for this resource?)

Then we help you review, extend, or delete resources before they become zombies.

---

## CLI Structure (After Simplification)

```
tag-manager
    |
    +-- lifecycle      <-- MAIN FEATURE (90% of what you'll use)
    |       |
    |       +-- wizard         Start here! Guided setup for new users
    |       +-- scan           Find all your AWS resources
    |       +-- set-ttl        Apply TTL tags to resources
    |       +-- review         Interactive screen to manage expiring resources
    |       +-- extend         Give resources more time
    |       +-- protect        Mark resources as "don't delete"
    |       +-- delete         Remove expired resources
    |       +-- notify         Send Slack alerts about expiring resources
    |       +-- notify-setup   Configure Slack notifications
    |       +-- policies       Manage local lifecycle policies
    |
    +-- policy         <-- AWS ORG POLICIES (enterprise governance)
    |       |
    |       +-- check-access       Check if AWS Org access is available
    |       +-- view               List AWS Org tag policies
    |       +-- create             Create new AWS Org tag policy
    |       +-- check-compliance   Check resource compliance
    |
    +-- ask            <-- AI HELPER (ask questions, get help)
    |
    +-- setup          <-- ONE-TIME SETUP
    |       |
    |       +-- wizard         Complete guided setup
    |       +-- validate       Check if everything is working
    |       +-- multi-accounts Configure scanning across AWS accounts
    |
    +-- update         <-- UPDATE THE CLI
    |
    +-- uninstall      <-- REMOVE EVERYTHING
```

---

## How to Use (For New Users)

### Option 1: Guided Wizard (Recommended)

Just run this one command and follow the prompts:

```bash
tag-manager lifecycle wizard
```

The wizard will:
1. Check if multi-account is set up
2. Setup tagging policies
3. Help you discover your AWS resources which are catched by the tagging policies
4. Apply TTL tags  to resources which are catched by the tagging policies (you choose how long each resource should live)
5. Set up notifications so you know when resources are expiring
6. Show you how to review and manage expiring resources

### Option 2: Step-by-Step Commands

```bash
# 1. First time? Set up the CLI
tag-manager setup wizard

# 2. COnfigure tagging policies
tag-manager lifecycle policies create

# 3. Scan your AWS resources
tag-manager lifecycle scan

# 4. Apply TTL tags on resources catched by tagging policies(30 days for EC2 instances)
tag-manager lifecycle set-ttl --services ec2 --ttl-days 30

# 5. Review what's expiring
tag-manager lifecycle review

# 6. (Optional) Set up Slack notifications
tag-manager lifecycle notify-setup
```

---

## Hybrid Policy System

You can use **TWO types of policies** together (hybrid approach):

### 1. Local Lifecycle Policies (Default)
- Quick setup, no AWS Org access needed
- Stored locally in SQLite database
- Create with: `tag-manager lifecycle policies create`
- Best for: Individual accounts, quick start

### 2. AWS Organizations Tag Policies (Enterprise)
- Centralized governance across all accounts in your organization
- Requires AWS Organizations access
- Create with: `tag-manager policy create`
- Check compliance: `tag-manager lifecycle scan --check-compliance`
- Best for: Multi-account environments, enterprise compliance

### How They Work Together

When you run `lifecycle set-ttl`, resources are tagged with their policy source:

| Tag | Values |
|-----|--------|
| `bluearch:policy-source` | `aws_org`, `local`, or `manual` |
| `bluearch:policy` | Name of the policy that triggered the TTL |
| `bluearch:noncompliant-tags` | Missing tags (if from AWS Org policy) |

**Workflow Example**:
```bash
# Check which resources violate AWS Org Tag Policies
tag-manager lifecycle scan --check-compliance

# Show only noncompliant resources
tag-manager lifecycle scan --noncompliant

# Apply TTL to noncompliant resources only
tag-manager lifecycle set-ttl --noncompliant --ttl-days 14
```

---

## Command Reference

### lifecycle wizard
**What it does**: Complete guided walkthrough for new users

**When to use**: First time using the CLI, or when onboarding a new team member

**Example**:
```bash
tag-manager lifecycle wizard
```

---

### lifecycle scan
**What it does**: Shows all your AWS resources and their TTL status

**When to use**: To see what resources you have and which are expiring

**Examples**:
```bash
# Show everything
tag-manager lifecycle scan

# Show only resources without tags
tag-manager lifecycle scan --untagged

# Show resources expiring in 7 days
tag-manager lifecycle scan --expiring 7

# Show only EC2 and Lambda
tag-manager lifecycle scan --services ec2,lambda

# Check AWS Org Tag Policy compliance
tag-manager lifecycle scan --check-compliance

# Show only noncompliant resources (missing required tags)
tag-manager lifecycle scan --noncompliant
```

---

### lifecycle set-ttl
**What it does**: Applies TTL tags to resources

**When to use**: To set expiration dates on resources

**Examples**:
```bash
# Set all EC2 instances to expire in 30 days
tag-manager lifecycle set-ttl --services ec2 --ttl-days 30

# Set a specific resource to expire in 60 days
tag-manager lifecycle set-ttl --resource-arn arn:aws:ec2:... --ttl-days 60

# Preview changes without applying them
tag-manager lifecycle set-ttl --services ec2 --ttl-days 30 --dry-run

# Apply TTL to noncompliant resources only (from AWS Org policy check)
tag-manager lifecycle set-ttl --noncompliant --ttl-days 14
```

---

### lifecycle review
**What it does**: Interactive screen to review and manage expiring resources

**When to use**: Daily/weekly review of what's about to expire

**What you can do**:
- **[E] Extend** - Give the resource more time (7, 14, 30, 60, 90 days)
- **[P] Protect** - Mark as "don't auto-delete" (with a reason)
- **[D] Delete** - Delete the resource now
- **[S] Skip** - Move to next resource
- **[Q] Quit** - Exit review

**Example**:
```bash
tag-manager lifecycle review
```

Screen looks like:
```
TTL Resource Review
===================

[1/5] i-0abc123def (EC2 Instance)
      Region: us-east-1
      Expires: 2026-01-20 (3 days)
      Owner: team@example.com

[E] Extend  [P] Protect  [D] Delete  [S] Skip  [Q] Quit
```

---

### lifecycle extend
**What it does**: Extends the TTL of resources

**When to use**: To quickly extend resources without interactive review

**Examples**:
```bash
# Extend a specific resource by 30 days
tag-manager lifecycle extend --resource-arn arn:aws:ec2:... --days 30

# Extend all EC2 instances by 14 days
tag-manager lifecycle extend --services ec2 --days 14
```

---

### lifecycle protect
**What it does**: Marks resources as protected from automatic deletion

**When to use**: For production resources that should never be auto-deleted

**Examples**:
```bash
# Protect a resource
tag-manager lifecycle protect --resource-arn arn:aws:ec2:... --reason "Production server"

# Remove protection
tag-manager lifecycle protect --resource-arn arn:aws:ec2:... --unprotect

# List all protected resources
tag-manager lifecycle protect --list
```

---

### lifecycle delete
**What it does**: Deletes expired resources

**When to use**: After reviewing expired resources

**Examples**:
```bash
# Preview what would be deleted
tag-manager lifecycle delete --dry-run

# Delete expired resources (with confirmation)
tag-manager lifecycle delete --confirm
```

---

### lifecycle notify
**What it does**: Sends Slack notifications about expiring resources

**When to use**: Set up as a daily cron job, or run manually before team meetings

**Examples**:
```bash
# Send notifications
tag-manager lifecycle notify

# Preview what would be sent
tag-manager lifecycle notify --dry-run

# Send a test message
tag-manager lifecycle notify --test

# Send daily summary
tag-manager lifecycle notify --summary
```

---

### lifecycle notify-setup
**What it does**: Configure Slack webhook for notifications

**When to use**: One-time setup, or to change notification settings

**Examples**:
```bash
# Interactive setup
tag-manager lifecycle notify-setup

# Set webhook URL directly
tag-manager lifecycle notify-setup --webhook-url "https://hooks.slack.com/..."

# Show current config
tag-manager lifecycle notify-setup --show

# Disable notifications
tag-manager lifecycle notify-setup --disable
```

---

### ask
**What it does**: AI helper that can answer questions and run commands

**When to use**: When you're not sure what command to use, or need help

**Examples**:
```bash
# Ask a question
tag-manager ask "what resources are expiring soon?"

# Get help with a task
tag-manager ask "how do I protect a resource?"

# Start interactive chat
tag-manager ask chat
```

---

## Before/After Comparison

### Before (Complex)
```
tag-manager
    |-- discover (...)
    |-- tags (...)
    |-- lifecycle (...)
    |-- ask (...)
    |-- accounts (...)
    |-- cost (...)
    |-- policy (...)
    |-- alarms (...)
    |-- setup (...)
    |-- update (...)
    |-- uninstall (...)
```
12+ command groups, overwhelming for new users

### After (Simple)
```
tag-manager
    |-- lifecycle   <-- Main feature
    |-- policy      <-- AWS Org policies (enterprise)
    |-- ask         <-- AI helper
    |-- setup       <-- One-time setup
    |-- update
    |-- uninstall
```
6 command groups, clear purpose for each

---

## Daily Workflow

### Morning Routine (5 minutes)

```bash
# 1. Scan for resources expiring this week
tag-manager lifecycle scan --expiring 7

# 2. Review and take action
tag-manager lifecycle review
```

### Weekly Routine (10 minutes)

```bash
# 1. Send notifications to team
tag-manager lifecycle notify

# 2. Review all expiring resources
tag-manager lifecycle review

# 3. Clean up expired resources
tag-manager lifecycle delete --dry-run
tag-manager lifecycle delete --confirm
```

### Automation (Cron)

```bash
# Daily at 9am: Send Slack notifications
0 9 * * * tag-manager lifecycle notify

# Weekly on Monday: Send summary
0 9 * * 1 tag-manager lifecycle notify --summary
```

---

## FAQ

**Q: What happens when a resource expires?**
A: Nothing automatic! The CLI warns you via Slack and in `lifecycle scan`. You decide what to do in `lifecycle review`.

**Q: Can I auto-delete resources?**
A: Not by default. You can enable auto-delete in lifecycle policies, but it's opt-in with safeguards.

**Q: What if I protect a resource?**
A: It won't appear in expiring lists or be eligible for deletion. You can unprotect it later.

**Q: Can I undo a deletion?**
A: No. Deletions are permanent. Always use `--dry-run` first!

**Q: How do I scan multiple AWS accounts?**
A: Run `tag-manager setup multi-accounts` first, then `lifecycle scan` will include all configured accounts.
