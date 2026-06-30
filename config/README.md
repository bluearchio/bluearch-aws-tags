# Tag Manager Configuration Files

This directory contains various tagging rule configurations for the AWS Tag Manager CLI.

## Rule Sets

### 1. safe_default_rules.json (DEFAULT for Setup)
**Purpose:** Safe, non-destructive tags for initial setup and untagged resources
- Sets `Environment=unknown` and `Owner=unknown` on resources
- Adds `NeedsReview=true` flag for easy identification
- Marks resources with `ManagedBy=tag-manager-setup`
- **Won't break anything** - just marks resources for review
- **This is the default choice during setup wizard**

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

### During Setup (Automatic)
The setup wizard (`tag-manager setup`) will offer these rule sets:
1. Safe Defaults (default) - Uses `safe_default_rules.json`
2. Standard Rules - Uses `production_tagging_rules.json`
3. Advanced Rules - Uses `advanced_tagging_rules.json`

### Manual Loading
```bash
# Load specific rule set
tag-manager tags rules load config/safe_default_rules.json

# Load with replacement
tag-manager tags rules load config/production_tagging_rules.json --replace
```

## Safety Notes

- **safe_default_rules.json** is designed to be completely safe - it only adds informational tags that won't affect resource behavior
- All "unknown" values are intentionally non-operational to ensure resources continue functioning normally
- The `NeedsReview=true` tag makes it easy to find resources that need proper classification later

## Best Practices

1. **Start with safe defaults** during initial setup
2. **Review and update** the "unknown" tags with proper values
3. **Graduate to production rules** once comfortable with the system
4. **Customize rules** based on your organization's needs