# AWS Tag Manager CLI - Complete Slack Integration Setup Guide

## Overview
This guide walks through setting up the complete Slack integration for AWS Tag Manager CLI, enabling your team to manage AWS tags directly from Slack using slash commands with real data from your AWS environment.

## Architecture
```
Slack → API Gateway → Lambda → SQS Queue → Local CLI Worker → AWS Resources
                                     ↓
                              Response to Slack
```

## Prerequisites

1. **AWS Account** with appropriate permissions
2. **Slack Workspace** with admin access to create apps
3. **AWS SAM CLI** installed ([Installation Guide](https://docs.aws.amazon.com/serverless-application-model/latest/developerguide/serverless-sam-cli-install.html))
4. **AWS CLI** configured with credentials
5. **Tag Manager CLI** installed and configured

## Step 1: Create Slack App

1. Go to https://api.slack.com/apps
2. Click "Create New App" → "From scratch"
3. Enter app name: "AWS Tag Manager"
4. Select your workspace
5. Note down the following from "Basic Information":
   - **Client ID**
   - **Client Secret** 
   - **Signing Secret**

## Step 2: Configure Slack App Permissions

1. Go to "OAuth & Permissions"
2. Add the following Bot Token Scopes:
   ```
   chat:write
   chat:write.public
   channels:read
   groups:read
   commands
   app_mentions:read
   users:read
   team:read
   files:write
   channels:history
   groups:history
   im:history
   im:read
   im:write
   reactions:write
   ```

## Step 3: Deploy AWS Infrastructure

1. Navigate to the AWS OAuth service directory:
   ```bash
   cd aws-oauth-service
   ```

2. Run the deployment script:
   ```bash
   ./deploy.sh
   ```

3. Select environment (dev/staging/prod)
4. Enter your AWS region
5. Provide Slack credentials when prompted
6. Wait for deployment to complete (5-10 minutes)

The script will output:
- OAuth Callback URL
- SQS Queue URL for the worker
- Slack Command Base URL
- Saved configuration to `.env.aws-oauth-{environment}`

## Step 4: Configure Slack OAuth Redirect

1. Go back to your Slack app settings
2. Navigate to "OAuth & Permissions" → "Redirect URLs"
3. Add the OAuth Callback URL from the deployment output
4. Click "Save URLs"

## Step 5: Configure Slack Slash Commands

In your Slack app settings, go to "Slash Commands" and create these commands:

| Command | Request URL | Description |
|---------|------------|-------------|
| `/tag-status` | `{SLACK_COMMAND_BASE_URL}/tag-status` | View tagging system status |
| `/tag-scan` | `{SLACK_COMMAND_BASE_URL}/tag-scan` | Scan for untagged resources |
| `/tag-apply` | `{SLACK_COMMAND_BASE_URL}/tag-apply` | Apply tags to resources |
| `/tag-history` | `{SLACK_COMMAND_BASE_URL}/tag-history` | View operation history |
| `/tag-rollback` | `{SLACK_COMMAND_BASE_URL}/tag-rollback` | Rollback tag operations |
| `/tag-cost` | `{SLACK_COMMAND_BASE_URL}/tag-cost` | Analyze costs by tags |
| `/tag-report` | `{SLACK_COMMAND_BASE_URL}/tag-report` | Generate tag reports |
| `/tag-validate` | `{SLACK_COMMAND_BASE_URL}/tag-validate` | Validate tag compliance |
| `/tag-rules` | `{SLACK_COMMAND_BASE_URL}/tag-rules` | Manage tagging rules |
| `/tag-bulk` | `{SLACK_COMMAND_BASE_URL}/tag-bulk` | Bulk tag operations |

Replace `{SLACK_COMMAND_BASE_URL}` with the URL from your deployment output.

## Step 6: Install Bot in Slack Workspace

1. Load the environment configuration:
   ```bash
   source .env.aws-oauth-{environment}
   ```

2. Run the Slack setup:
   ```bash
   tag-manager slack setup
   ```

3. The browser will open with the OAuth flow
4. Authorize the app in your Slack workspace
5. The bot token will be stored automatically

## Step 7: Start the Local CLI Worker

The worker polls the SQS queue for commands from Slack and executes them locally:

1. In a new terminal, load the environment:
   ```bash
   source .env.aws-oauth-{environment}
   ```

2. Start the worker:
   ```bash
   tag-manager slack worker
   ```

The worker will:
- Poll the SQS queue for commands
- Execute CLI commands locally
- Send responses back to Slack
- Show real data from your AWS environment

Keep this running to process Slack commands.

## Step 8: Test the Integration

1. In Slack, type:
   ```
   /tag-status
   ```

2. You should see:
   - Command acknowledged in Slack
   - Worker processing the command in terminal
   - Real AWS tagging status returned to Slack

3. Try other commands:
   ```
   /tag-history --limit 5
   /tag-scan --service ec2
   /tag-cost --help
   ```

## How It Works

1. **User types slash command** in Slack
2. **Slack sends request** to API Gateway
3. **Lambda function**:
   - Validates the request signature
   - Sends command to SQS queue
   - Returns immediate acknowledgment to Slack
4. **Local CLI worker**:
   - Polls SQS queue
   - Executes actual CLI command
   - Captures output
   - Sends formatted response back to Slack
5. **User sees real results** in Slack

## Command Examples

### Check System Status
```
/tag-status
```
Shows comprehensive dashboard with compliance metrics, risk analysis, and recommendations.

### Scan for Untagged Resources
```
/tag-scan --service ec2
```
Scans EC2 resources for missing tags.

### View Operation History
```
/tag-history --limit 10
```
Shows last 10 tag operations.

### Analyze Costs by Tags
```
/tag-cost --tag-key Environment --tag-value Production --start 2025-08-01 --end 2025-08-31
```
Analyzes costs for Production environment.

### Generate Compliance Report
```
/tag-report compliance
```
Generates detailed compliance report.

## Monitoring

### Lambda Logs
```bash
# OAuth handler logs
aws logs tail /aws/lambda/tag-manager-slack-oauth-{environment} --follow

# Command handler logs  
aws logs tail /aws/lambda/tag-manager-slack-commands-{environment} --follow
```

### SQS Queue Status
```bash
aws sqs get-queue-attributes --queue-url {SQS_QUEUE_URL} --attribute-names All
```

### CloudWatch Dashboard
View metrics at: https://console.aws.amazon.com/cloudwatch/

## Troubleshooting

### Worker Not Receiving Commands
1. Check SQS queue has messages
2. Verify worker is using correct queue URL
3. Check Lambda logs for errors

### Commands Not Working
1. Verify Slack app signing secret
2. Check Lambda has SQS permissions
3. Ensure worker is running

### No Response in Slack
1. Check worker output for errors
2. Verify Slack bot token is valid
3. Check bot has channel permissions

### Authentication Issues
1. Ensure AWS credentials are configured
2. Verify IAM permissions for Lambda
3. Check Secrets Manager access

## Security Best Practices

1. **Use environment-specific deployments** (dev/staging/prod)
2. **Rotate Slack tokens** regularly
3. **Monitor CloudWatch alarms** for errors
4. **Use IAM roles** with least privilege
5. **Enable SQS encryption** for sensitive data
6. **Review CloudWatch logs** for suspicious activity

## Cost Optimization

- SQS uses long polling (20s) to reduce API calls
- Lambda functions have appropriate memory allocation
- DynamoDB uses on-demand billing
- CloudWatch logs have 14-day retention

## Support

For issues or questions:
1. Check CloudWatch logs for errors
2. Review this documentation
3. Open an issue on GitHub
4. Contact your AWS administrator

## Next Steps

1. **Add more commands** by updating the Lambda handler
2. **Customize response formatting** in the worker
3. **Implement approval workflows** for sensitive operations
4. **Set up CloudWatch alarms** for monitoring
5. **Configure auto-scaling** for high usage