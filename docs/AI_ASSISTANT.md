# AI-Powered AWS Assistant

An intelligent assistant built into the Tag Manager CLI that answers questions about your AWS account using AWS Bedrock and Claude models.

## Overview

The AI Assistant leverages:
- **AWS Bedrock** - Uses Claude models hosted in your AWS account
- **Your SSO Authentication** - No API keys needed!
- **MCP-style Tools** - Executes real AWS API calls to answer questions
- **Natural Language** - Ask questions in plain English

## Recent Improvements (2025-01)

### Streaming Responses
- **Real-time token delivery** using `converse_stream` API
- Shows tool calls as they happen
- Immediate feedback for better UX
- Aligns with Evil Martians CLI UX principles

### Prompt Caching
- **90% cost reduction** on repeated context
- System prompts automatically cached
- Tool definitions cached (all 9 tools)
- Significant savings in multi-turn conversations

### Performance Optimization
- **Latency-optimized inference** for faster responses
- Automatic retry with exponential backoff
- Enhanced error handling with specific exception types

### Dynamic Model Detection
- **Automatic latest version detection** from AWS Bedrock API
- No manual updates needed when AWS releases new models
- Support for shortcuts: `haiku`, `sonnet`, `opus`

**Current Auto-Detected Versions:**
- haiku: `us.anthropic.claude-haiku-4-5-20251001-v1:0`
- sonnet: `us.anthropic.claude-sonnet-4-5-20250929-v1:0`
- opus: `us.anthropic.claude-opus-4-1-20250805-v1:0`

## Features

### Available Tools

The assistant can:
1. **List EC2 Instances** - Get running/stopped instances with details
2. **Describe S3 Buckets** - List buckets with regions and tags
3. **List Lambda Functions** - View functions with runtime and configuration
4. **Cost Analysis** - Analyze costs by service, tag, or time period
5. **Find Untagged Resources** - Identify compliance issues
6. **List IAM Users** - View users with access key ages
7. **Describe RDS Instances** - Get database information
8. **List VPC Resources** - View network configuration
9. **Account Summary** - Get overview of your AWS account

### Available Models

| Model ID | Name | Cost | Best For |
|----------|------|------|----------|
| `anthropic.claude-3-5-sonnet-20241022-v2:0` | Claude 3.5 Sonnet v2 | $$ | **Recommended** - Best balance |
| `anthropic.claude-3-5-sonnet-20240620-v1:0` | Claude 3.5 Sonnet v1 | $$ | Older version |
| `anthropic.claude-haiku-4-5-20251001-v1:0` | Claude 3 Haiku | $ | Cheaper, faster queries |

## Usage

**Good News:** The assistant can automatically enable Bedrock access for you! Just try using it, and if access isn't enabled, it will:
1. Detect the issue automatically
2. Ask if you want automatic setup
3. Enable model access in ~5 seconds if you confirm
4. Ready to use immediately!

No manual console work needed!

### Interactive Chat Mode

Start a conversational session:

```bash
bluearch-aws-tags ask chat
```

With specific model:

```bash
bluearch-aws-tags ask chat --model anthropic.claude-haiku-4-5-20251001-v1:0
```

### Single Question Mode

Ask one question and exit:

```bash
bluearch-aws-tags ask question "What EC2 instances are running?"
bluearch-aws-tags ask question "Show me my costs last month"
bluearch-aws-tags ask question "Which resources are missing tags?"
```

### List Available Models

```bash
bluearch-aws-tags ask models
```

### Enable Model Access (Manual)

If you want to enable access without asking a question first:

```bash
bluearch-aws-tags ask enable-access

# Or for a specific model
bluearch-aws-tags ask enable-access --model us.anthropic.claude-haiku-4-5-20251001-v1:0
```

This automatically:
1. Accepts the model license agreement (if needed)
2. Submits your use case details to Anthropic
3. Enables model access instantly

## Example Questions

### Resource Discovery
```
- What EC2 instances are running?
- List all S3 buckets in my account
- Show me Lambda functions in us-east-1
- What RDS databases do I have?
- List all VPCs
```

### Cost Analysis
```
- What were my costs last month?
- Show me costs by service for the last 30 days
- How much am I spending on EC2?
- Break down my costs by the Environment tag
```

### Compliance & Tagging
```
- Find resources without required tags
- Which EC2 instances are missing the Environment tag?
- Show me untagged S3 buckets
```

### Security & IAM
```
- List all IAM users
- Which users have old access keys?
- Show me users who haven't used their password recently
```

### Multi-Step Queries
```
- What are my top 3 most expensive services and how many resources do I have in each?
- Find all running EC2 instances in us-east-1 and tell me which ones are missing tags
- Compare my costs from last month to this month
```

## How It Works

```
┌─────────────────────────────────────────────────┐
│  User: "What EC2 instances are running?"       │
└────────────────┬────────────────────────────────┘
                 │
┌────────────────▼────────────────────────────────┐
│  Bedrock Claude (via AWS SSO auth)             │
│  - Understands the question                     │
│  - Decides which tools to use                   │
│  - Calls: list_ec2_instances(state='running')  │
└────────────────┬────────────────────────────────┘
                 │
┌────────────────▼────────────────────────────────┐
│  MCP Tools (AWS API Calls)                     │
│  - Uses your SSO credentials                    │
│  - Calls: ec2_client.describe_instances()      │
│  - Returns: Instance data                       │
└────────────────┬────────────────────────────────┘
                 │
┌────────────────▼────────────────────────────────┐
│  Bedrock Claude                                 │
│  - Formats the data                             │
│  - Returns human-readable answer                │
└────────────────┬────────────────────────────────┘
                 │
┌────────────────▼────────────────────────────────┐
│  You get a formatted answer!                    │
└─────────────────────────────────────────────────┘
```

## Prerequisites

### 1. AWS Bedrock Access

**Fully Automated!** The assistant handles Bedrock setup for you:

```bash
# Just try using it - automatic setup if needed!
bluearch-aws-tags ask question "What EC2 instances do I have?"

# The assistant will:
# 1. Detect if access is needed
# 2. Ask for confirmation (Y/n)
# 3. Enable access automatically (~5 seconds)
# 4. Answer your question!
```

**Manual Commands** (optional):

```bash
# Manually enable access first
bluearch-aws-tags ask enable-access

# Check current access status
bluearch-aws-tags ask check-access

# View manual setup instructions
bluearch-aws-tags ask setup-bedrock
```

### 2. IAM Permissions

**For using the assistant** (required):
```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "bedrock:InvokeModel",
        "bedrock:InvokeModelWithResponseStream"
      ],
      "Resource": [
        "arn:aws:bedrock:*::foundation-model/anthropic.claude-*"
      ]
    }
  ]
}
```

**For automatic setup** (optional, only needed once):
```json
{
  "Effect": "Allow",
  "Action": [
    "bedrock:ListFoundationModels",
    "bedrock:ListFoundationModelAgreementOffers",
    "bedrock:CreateFoundationModelAgreement",
    "bedrock:PutUseCaseForModelAccess",
    "bedrock:GetUseCaseForModelAccess"
  ],
  "Resource": "*"
}
```

Plus your existing Tag Manager permissions for:
- EC2, S3, Lambda, RDS (read access)
- Cost Explorer (for cost analysis)
- IAM (for user listing)

### 3. Bedrock Region

Bedrock must be available in your region. Common regions:
- **us-east-1** (recommended)
- **us-west-2**
- **eu-west-1**

Specify region:

```bash
bluearch-aws-tags ask chat --region us-east-1
```

## Pricing

### Bedrock Costs

Pricing varies by model (as of 2025):

**Claude 3.5 Sonnet:**
- Input: ~$3 per 1M tokens
- Output: ~$15 per 1M tokens

**Claude 3 Haiku (cheaper):**
- Input: ~$0.25 per 1M tokens
- Output: ~$1.25 per 1M tokens

**Example Cost:**
- Asking "What EC2 instances are running?" typically uses ~500 input + ~1000 output tokens
- With Sonnet: ~$0.015 per question
- With Haiku: ~$0.0015 per question (10x cheaper!)

**Tip:** Use Haiku for simple queries, Sonnet for complex analysis.

## Advanced Usage

### Python API

Use the assistant programmatically:

```python
from tag_manager_cli.integrations.aws_assistant import BedrockAWSAssistant

# Create assistant
assistant = BedrockAWSAssistant(
    model_id="anthropic.claude-3-5-sonnet-20241022-v2:0",
    region="us-east-1"
)

# Ask a question
answer = assistant.ask("What EC2 instances are running?")
print(answer)

# Interactive mode
assistant.interactive_mode()
```

### Custom Tools

Add your own tools by extending `AWSMCPTools`:

```python
# tag_manager_cli/integrations/mcp_tools.py

@staticmethod
def my_custom_tool(param1: str) -> Dict[str, Any]:
    """My custom AWS operation."""
    # Your implementation
    return {"result": "data"}
```

Then register it in `get_tools_schema()` and `execute_tool()`.

## Troubleshooting

### "Model not found" Error

**Problem:** Bedrock model access not enabled

**What happens:** The assistant will automatically detect this and show you setup instructions!

**Manual check (optional):**
```bash
bluearch-aws-tags ask check-access
```

**Solution:**
1. Go to AWS Console > Bedrock > Model access
2. Enable Claude 3.5 Sonnet and/or Haiku
3. Wait ~2 minutes for activation
4. Try again

### "Access Denied" Error

**Problem:** Missing IAM permissions

**What happens:** The assistant will automatically detect this and show you exactly which permissions are needed!

**Solution:** Add these permissions to your SSO role:
- `bedrock:InvokeModel`
- `bedrock:InvokeModelWithResponseStream`

### "Bedrock not available in region"

**Problem:** Bedrock not supported in your region

**Solution:** Use `--region us-east-1` or another supported region

### Slow Responses

**Problem:** Large responses or complex queries

**Solution:**
- Use Haiku model (faster)
- Ask more specific questions
- Limit regions/resources in queries

## Examples

### Example 1: Quick Resource Check

```bash
$ bluearch-aws-tags ask question "How many EC2 instances are running?"

Answer:
You currently have 5 EC2 instances running across your account:
- us-east-1: 3 instances
- us-west-2: 2 instances

All instances are healthy and operational.
```

### Example 2: Cost Analysis

```bash
$ bluearch-aws-tags ask question "What were my top 3 costs last month?"

Answer:
Here are your top 3 costs from March 2025:

1. Amazon EC2: $1,234.56
   - Primary driver: t3.large instances in production
2. Amazon RDS: $456.78
   - Mostly from PostgreSQL db.r5.xlarge
3. Amazon S3: $123.45
   - Storage: 2.3 TB, requests: 450M

Total: $1,814.79
```

### Example 3: Compliance Check

```bash
$ bluearch-aws-tags ask question "Find EC2 instances missing required tags"

Answer:
Found 3 EC2 instances missing required tags:

1. i-abc123 (t3.medium, us-east-1)
   Missing: Environment, Owner

2. i-def456 (t3.large, us-east-1)
   Missing: Project

3. i-ghi789 (t3.small, us-west-2)
   Missing: Environment, Owner, Project

Would you like me to help create a tagging plan?
```

## Integration with Tag Manager

The AI assistant integrates seamlessly:

```bash
# Use AI to find issues
bluearch-aws-tags ask question "Find untagged resources"

# Then fix with Tag Manager
bluearch-aws-tags tags apply --interactive

# Verify
bluearch-aws-tags ask question "Are there still untagged resources?"
```

## Security & Privacy

- **All data stays in your AWS account**
- Uses your existing SSO authentication
- No data sent to external APIs
- Bedrock logs can be reviewed in CloudWatch
- Models don't retain conversation history

## Limitations

1. **Database Dependency:** Some queries require Tag Manager's resource database
   - Run `bluearch-aws-tags tags discover` first
2. **Permissions:** Answers limited by your AWS SSO role permissions
3. **Regions:** Some questions may require multi-region access
4. **Cost Explorer:** Cost queries require Cost Explorer API access

## Tips

1. **Be Specific:** "Show running EC2 instances in us-east-1" vs "Show me stuff"
2. **Use Haiku for Speed:** Simple queries don't need Sonnet
3. **Chain Questions:** The assistant remembers context in chat mode
4. **Check Permissions:** Ensure your role has necessary read permissions
5. **Run Discovery:** Keep your resource database updated for best results

## Future Enhancements

Planned features:
- [ ] Multi-account support (AWS Organizations)
- [ ] Automated remediation (tag application via AI)
- [ ] Custom tool plugins
- [ ] Voice input (via Alexa integration)
- [ ] Scheduled reports

## Contributing

To add new tools:

1. Add schema to `AWSMCPTools.get_tools_schema()`
2. Implement the tool method
3. Register in `execute_tool()` dispatcher
4. Test with example questions
5. Update documentation

## See Also

- [AWS Bedrock Documentation](https://docs.aws.amazon.com/bedrock/)
- [Claude API Documentation](https://docs.anthropic.com/)
- [MCP Protocol](https://modelcontextprotocol.io/)
- [Tag Manager CLI Docs](../README.md)
