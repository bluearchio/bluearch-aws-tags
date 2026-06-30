# AWS Tag Manager CLI - IAM Permissions Documentation

This document details all AWS IAM permissions required by the tag-manager-cli application, based on a comprehensive analysis of all boto3 API calls in the codebase.

## Table of Contents
- [Quick Start](#quick-start)
- [Policy File](#policy-file)
- [Permission Details](#permission-details)
- [Applying the Policy](#applying-the-policy)
- [Maintaining the Policy](#maintaining-the-policy)
- [Security Best Practices](#security-best-practices)

## Quick Start

The **`iam-policy.json`** file contains ALL AWS permissions required by the tag-manager-cli application. This single consolidated policy includes every AWS API action that the application may call.

## Policy File

### iam-policy.json
This comprehensive policy includes permissions for:
- **Resource Discovery**: EC2, S3, Lambda, RDS, and other AWS services
- **Tag Management**: Reading and applying tags across resources
- **Organizations**: Full tag policy management capabilities
- **Cost Analysis**: Cost Explorer access for reporting
- **AI Features**: Bedrock for Claude AI assistance
- **Integration Services**: DynamoDB and SSM for OAuth and configuration

## IMPORTANT: Policy Maintenance

⚠️ **When adding new boto3 API calls to the codebase, you MUST update `iam-policy.json`**

### Update Process:
1. **Identify the IAM action**: Check AWS documentation for the exact action name
2. **Update iam-policy.json**: Add the permission to the appropriate statement
3. **Test the permission**: Verify it works with the upcoming `setup validate` command
4. **Update this documentation**: Add details about the new permission below

### Example:
```python
# If you add this boto3 call:
ec2_client.describe_snapshots()

# Add to iam-policy.json:
{
  "Sid": "EC2Access",
  "Action": [
    "ec2:DescribeSnapshots"  # <- Add this
  ]
}
```

## Permission Details

### Core Services

#### STS (Security Token Service)
- **sts:GetCallerIdentity** - Required to identify the current AWS account and user/role ARN. Used throughout the application for authentication and logging.

#### EC2 (Elastic Compute Cloud)
- **ec2:DescribeInstances** - List and analyze EC2 instances for tagging
- **ec2:DescribeVolumes** - List and analyze EBS volumes
- **ec2:DescribeRegions** - Discover available AWS regions for multi-region operations
- **ec2:DescribeVpcs** - Analyze VPC resources and their tags
- **ec2:DescribeSubnets** - Analyze subnet resources within VPCs

#### S3 (Simple Storage Service)
- **s3:ListAllMyBuckets** - Discover all S3 buckets in the account
- **s3:GetBucketLocation** - Determine bucket regions for proper API routing
- **s3:GetBucketAcl** - Analyze bucket access controls (security compliance)
- **s3:GetBucketTagging** - Read existing bucket tags
- **s3:PutBucketTagging** - Apply tags to S3 buckets
- **s3:PutObjectTagging** - Apply tags to S3 objects

#### Lambda
- **lambda:ListFunctions** - Discover Lambda functions for tagging
- **lambda:ListTags** - Read existing function tags
- **lambda:TagResource** - Apply tags to Lambda functions
- **lambda:UntagResource** - Remove tags from Lambda functions

#### IAM
- **iam:ListUsers** - Analyze IAM users (for security/compliance reporting)
- **iam:ListAccessKeys** - Audit access key usage and age

#### RDS (Relational Database Service)
- **rds:DescribeDBInstances** - Discover and analyze RDS database instances

#### Cost Explorer
- **ce:GetCostAndUsage** - Generate cost analysis reports grouped by tags, essential for cost allocation and chargeback

### Tagging Services

#### Resource Groups Tagging API
- **tag:GetResources** - Primary API for discovering resources and their tags across all AWS services
- **tag:TagResources** - Bulk apply tags to multiple resources
- **tag:GetComplianceSummary** - Check tag policy compliance status

### AWS Organizations

#### Read Operations
- **organizations:DescribeOrganization** - Get organization structure and details
- **organizations:ListRoots** - Navigate organization hierarchy
- **organizations:ListPolicies** - View existing tag policies
- **organizations:DescribePolicy** - Get tag policy details and content
- **organizations:ListTargetsForPolicy** - See where policies are attached
- **organizations:ListOrganizationalUnitsForParent** - Navigate OU structure
- **organizations:ListAccounts** - List all accounts in organization
- **organizations:ListAccountsForParent** - List accounts under specific OUs
- **organizations:DescribeEffectivePolicy** - Calculate effective tag policies for accounts/OUs

#### Write Operations
- **organizations:CreatePolicy** - Create new tag policies
- **organizations:UpdatePolicy** - Modify existing tag policies
- **organizations:DeletePolicy** - Remove tag policies
- **organizations:AttachPolicy** - Attach policies to accounts/OUs
- **organizations:DetachPolicy** - Detach policies from accounts/OUs
- **organizations:EnablePolicyType** - Enable tag policies for the organization
- **organizations:DisablePolicyType** - Disable tag policies
- **organizations:EnableAWSServiceAccess** - Enable required AWS service integrations

### AI and Integration Services

#### Bedrock (AI/ML)
- **bedrock:ListFoundationModels** - List available Claude models
- **bedrock:ListFoundationModelAgreementOffers** - Check model licensing
- **bedrock:InvokeModel** - Call AI models for assistance (deprecated)
- **bedrock:InvokeModelWithResponseStream** - Streaming AI responses (deprecated)
- **bedrock:Converse** - New conversation API for Claude
- **bedrock:ConverseStream** - Streaming conversation API

#### DynamoDB
- **dynamodb:GetItem** - Retrieve Slack OAuth tokens for integration
- **dynamodb:DeleteItem** - Clean up expired tokens

#### Systems Manager (SSM)
- **ssm:GetParameter** - Retrieve configuration parameters (OAuth settings, SQS URLs)

## Validating Your Permissions

### Using setup validate Command

The `setup validate` command now includes comprehensive IAM permission checking:

```bash
# Run the validation
tag-manager setup validate

# Or with Python directly
python -m tag_manager_cli.main setup validate
```

**What it does:**
1. Loads required permissions from `tag_manager_cli/integrations/iam-policy.json`
2. Gets your current AWS principal identity (user/role)
3. Uses IAM Policy Simulator to check each required permission
4. Shows exactly which permissions are missing
5. Maps missing permissions to affected CLI commands

**Example Output - All Permissions Granted:**
```
5. Checking IAM permissions...
┏━━━━━━━━━━━━━━━━━━┳━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
┃ Component        ┃ Status ┃ Details                             ┃
┡━━━━━━━━━━━━━━━━━━╇━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┩
│ IAM Permissions  │ OK     │ All 45 required permissions granted │
└──────────────────┴────────┴─────────────────────────────────────┘
```

**Example Output - Missing Permissions:**
```
5. Checking IAM permissions...
┏━━━━━━━━━━━━━━━━━━┳━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
┃ Component        ┃ Status ┃ Details                                     ┃
┡━━━━━━━━━━━━━━━━━━╇━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┩
│ IAM Permissions  │ ERROR  │ Missing 5 permissions affecting: tags       │
│                  │        │ apply, ai assistant, policy create          │
└──────────────────┴────────┴─────────────────────────────────────────────┘

Missing IAM Permissions:
  ai assistant:
    - bedrock:Converse
    - bedrock:ConverseStream
  tags apply:
    - tag:TagResources
    - s3:PutBucketTagging
  policy create:
    - organizations:CreatePolicy

To fix: Update your IAM policy with permissions from tag_manager_cli/integrations/iam-policy.json
```

### Permission Requirements for Validation

The validation feature itself requires:
- **iam:SimulatePrincipalPolicy** - To check permissions without making actual API calls
- **iam:GetUser** - Optional, for enhanced user identity information
- **iam:GetRole** - Optional, for role-based checking

If you don't have `iam:SimulatePrincipalPolicy`, the validator will fall back to limited checking of critical permissions only.

## Applying the Policy

### Option 1: AWS Console

1. Navigate to IAM → Policies
2. Click "Create policy"
3. Select "JSON" tab
4. Paste the content from `iam-policy.json`
5. Name the policy (e.g., "TagManagerCLI")
6. Attach to users, groups, or roles as needed

### Option 2: AWS CLI

```bash
# Create the policy
aws iam create-policy \
  --policy-name TagManagerCLI \
  --policy-document file://iam-policy.json

# Attach to a role
aws iam attach-role-policy \
  --role-name YourRoleName \
  --policy-arn arn:aws:iam::YOUR_ACCOUNT_ID:policy/TagManagerCLI

# Or attach to a user
aws iam attach-user-policy \
  --user-name YourUserName \
  --policy-arn arn:aws:iam::YOUR_ACCOUNT_ID:policy/TagManagerCLI
```

### Option 3: Terraform

Use the provided `iam-role.tf` template (see Terraform template file).

## Maintaining the Policy

### When to Update

Update `iam-policy.json` when:
1. Adding new boto3 client calls in the codebase
2. Using new AWS service operations
3. Implementing new features that require additional permissions

### How to Find IAM Action Names

1. **From boto3 documentation**: The method name usually maps directly
   - `ec2.describe_instances()` → `ec2:DescribeInstances`
   - `s3.list_buckets()` → `s3:ListBuckets`

2. **From AWS documentation**: Check the service's API reference

3. **From error messages**: AWS 403 errors usually include the exact action name

### Testing New Permissions

After adding new permissions:
1. Update `iam-policy.json`
2. Apply the updated policy to a test role
3. Test the functionality with that role
4. Use the upcoming `setup validate` command to verify

## Security Best Practices

### 1. Principle of Least Privilege
- Only include permissions that are actually used
- Consider splitting read-only vs write operations for different use cases
- Remove permissions when features are deprecated

### 2. Resource Constraints
For production use, consider adding resource constraints where possible:

```json
{
  "Effect": "Allow",
  "Action": "s3:*",
  "Resource": [
    "arn:aws:s3:::my-bucket-prefix-*",
    "arn:aws:s3:::my-bucket-prefix-*/*"
  ]
}
```

### 3. Conditional Access
Add conditions for additional security:

```json
{
  "Effect": "Allow",
  "Action": "tag:TagResources",
  "Resource": "*",
  "Condition": {
    "StringEquals": {
      "aws:RequestTag/ManagedBy": "TagManagerCLI"
    }
  }
}
```

### 4. MFA Requirements
For sensitive operations, require MFA:

```json
{
  "Effect": "Allow",
  "Action": "organizations:*Policy",
  "Resource": "*",
  "Condition": {
    "Bool": {
      "aws:MultiFactorAuthPresent": "true"
    }
  }
}
```

### 5. Regular Audits
- Use AWS Access Analyzer to review policy usage
- Enable CloudTrail logging for all API calls
- Regularly review and remove unused permissions
- Use the `setup validate` command to check current permissions

## Troubleshooting

### Common 403 Errors and Solutions

1. **"Access Denied" for tag operations**
   - Verify the action is in `iam-policy.json`
   - Check if tag policies restrict certain tag keys

2. **"Not authorized to perform organizations:DescribeOrganization"**
   - Verify the account is part of an AWS Organization
   - Check if Organizations is enabled in your region

3. **"Access Denied" for Cost Explorer**
   - Cost Explorer must be enabled in the account
   - There may be a delay after enabling before access works

4. **Bedrock model access issues**
   - Ensure Bedrock is available in your region
   - Model access may need to be explicitly granted in Bedrock console

## Files Mapping

Here's where each permission is used in the codebase:

| Service | Permission | Primary Usage Files |
|---------|------------|-------------------|
| STS | GetCallerIdentity | aws_auth.py, organizations_service.py, event_hooks.py |
| EC2 | Describe* | discovery.py, aws_tools.py, onboarding.py |
| S3 | List/Get/Put | discovery.py, unified_tags.py |
| Lambda | List/Tag | discovery.py, unified_tags.py |
| Organizations | All operations | organizations_service.py, policy_commands.py |
| Cost Explorer | GetCostAndUsage/Forecast/Tags | finops/cur_client.py |
| Athena | Query/Results/Workgroups | finops/cur_client.py |
| Glue | Database/Table operations | finops/cur_setup.py |
| CUR | Report definitions | finops/cur_setup.py |
| Resource Groups | Tag operations | resource_organization.py, unified_tags.py |
| Bedrock | Converse | aws_assistant.py, ai_commands.py |
| DynamoDB | Get/Delete | oauth_token_manager.py |
| SSM | GetParameter | oauth_token_manager.py |

## Support

For issues or questions about IAM permissions:
1. Check CloudTrail logs for the exact API call that failed
2. Verify the permission is included in `iam-policy.json`
3. Check for any SCPs or permission boundaries that might override
4. Review the specific error message for additional context
5. Use the `setup validate` command to check your current permissions

## Version History

- v2.0.0 - Consolidated to single policy file, added maintenance instructions
- v1.0.0 - Initial comprehensive permission analysis based on codebase scan
- Generated from tag-manager-cli codebase analysis on 2025-11-12