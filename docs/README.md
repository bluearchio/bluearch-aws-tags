
# AWS Tag Manager CLI

A comprehensive command-line interface for managing AWS tags and related functionality, built with Python, Typer, and Boto3.

## Features

- **Cost Allocation & Financial Tracking**: Track costs by tags, generate reports, budget monitoring
- **Resource Organization**: Organize and categorize AWS resources using tags
- **Automation & Operations**: Automate tagging policies and operational tasks
- **Access Control (IAM Conditions)**: Manage access control using tag-based IAM policies
- **Monitoring & Alerting**: Set up monitoring and alerts based on tags
- **Security & Compliance**: Ensure security compliance through proper tagging
- **Governance & Policy Enforcement**: Enforce organizational policies via tags

## Installation

### From Source

```bash
git clone <repository-url>
cd bluearch-aws-tags
pip install -r requirements.txt
pip install -e .
```

### Using pip (when published)

```bash
pip install -e .
```

## Prerequisites

### AWS Configuration

1. **AWS CLI configured with SSO**: The CLI uses AWS SSO profiles for authentication
   ```bash
   aws configure sso
   ```

2. **Set AWS_PROFILE environment variable**:
   ```bash
   export AWS_PROFILE=your-sso-profile-name
   ```

3. **Active SSO session**:
   ```bash
   aws sso login
   ```

### Optional: Redis for Caching

To enable caching for improved performance:

```bash
# Install Redis
# Ubuntu/Debian
sudo apt-get install redis-server

# macOS
brew install redis

# Start Redis
redis-server
```

Set Redis configuration (optional):
```bash
export REDIS_HOST=localhost
export REDIS_PORT=6379
export REDIS_DB=0
```

### Optional: DynamoDB for Configuration

The CLI will automatically create a DynamoDB table for configuration storage. Ensure your AWS credentials have the necessary DynamoDB permissions.

## Usage

### Interactive Mode (Default)

```bash
# Start interactive mode
bluearch-aws-tags

# Or explicitly
bluearch-aws-tags interactive
```

### Direct Commands

```bash
# Analyze costs by tag (CUR-powered)
bluearch-aws-tags cost report --tag-key Environment --start 2024-01-01 --end 2024-01-31

# Find untagged resource costs
bluearch-aws-tags cost gaps --required-tags Environment,Team,CostCenter

# Detect cost anomalies
bluearch-aws-tags cost anomalies detect --tag-key Team --percent-threshold 30

# Show version
bluearch-aws-tags --version

# Use specific AWS profile
bluearch-aws-tags --profile my-sso-profile interactive
```

## Project Structure

```
tag_manager_cli/
├── main.py                 # Entry point and main CLI logic
├── plugin.py              # Plugin integration system
├── modules/                # Feature modules
│   ├── finops/             # FinOps cost analysis (CUR-powered)
│   │   ├── cur_client.py   # Athena query layer
│   │   ├── cur_setup.py    # CUR detection + setup
│   │   ├── chargeback.py   # Tag-based reports
│   │   ├── visibility_gaps.py  # Untagged costs
│   │   ├── anomaly_detector.py # Cost anomalies
│   │   └── cost_trends.py  # Historical trends
│   ├── resource_organization.py
│   ├── automation_operations.py
│   ├── access_control.py
│   ├── monitoring_alerting.py
│   ├── security_compliance.py
│   └── governance_enforcement.py
├── utils/                  # Utility modules
│   ├── aws_auth.py        # AWS authentication
│   ├── cache.py           # Diskcache caching
│   └── config.py          # Configuration
└── __init__.py
```

## Plugin Integration

The Tag Manager CLI can be integrated as a plugin into other CLI applications:

```python
import typer
from tag_manager_cli.plugin import register_with_parent_cli

# Create your main CLI app
main_app = typer.Typer()

# Register Tag Manager as a subcommand
register_with_parent_cli(main_app, "tags")

if __name__ == "__main__":
    main_app()
```

Now you can use:
```bash
your-cli tags interactive
your-cli cost report --tag-key Environment --start 2024-01-01 --end 2024-01-31
```

## Configuration

### Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `AWS_PROFILE` | AWS SSO profile name | Required |
| `REDIS_HOST` | Redis server host | localhost |
| `REDIS_PORT` | Redis server port | 6379 |
| `REDIS_DB` | Redis database number | 0 |

### DynamoDB Configuration

The CLI uses DynamoDB table `tag-manager-config` to store configuration. The table will be created automatically with the following structure:

- **Primary Key**: `config_key` (String)
- **Attributes**: `config_value` (String, JSON), `updated_at` (String)

## AWS Permissions

Your AWS profile needs the following permissions:

### Cost Explorer
```json
{
    "Version": "2012-10-17",
    "Statement": [
        {
            "Effect": "Allow",
            "Action": [
                "ce:GetCostAndUsage",
                "ce:GetUsageReport",
                "ce:ListCostCategoryDefinitions",
                "ce:GetCostCategories"
            ],
            "Resource": "*"
        }
    ]
}
```

### Resource Groups Tagging API
```json
{
    "Version": "2012-10-17",
    "Statement": [
        {
            "Effect": "Allow",
            "Action": [
                "tag:GetResources",
                "tag:TagResources",
                "tag:UntagResources",
                "tag:GetTagKeys",
                "tag:GetTagValues"
            ],
            "Resource": "*"
        }
    ]
}
```

### DynamoDB (for configuration storage)
```json
{
    "Version": "2012-10-17",
    "Statement": [
        {
            "Effect": "Allow",
            "Action": [
                "dynamodb:CreateTable",
                "dynamodb:PutItem",
                "dynamodb:GetItem",
                "dynamodb:UpdateItem",
                "dynamodb:DeleteItem",
                "dynamodb:Scan",
                "dynamodb:DescribeTable"
            ],
            "Resource": "arn:aws:dynamodb:*:*:table/tag-manager-config"
        }
    ]
}
```

## Examples

### Cost Analysis by Tag

```bash
# Interactive mode
bluearch-aws-tags
# Select option 1: FinOps Cost Analysis
# Select option 1: Generate chargeback report

# Direct command
bluearch-aws-tags cost report \
  --tag-key Environment \
  --start 2024-01-01 \
  --end 2024-01-31 \
  --format csv --output costs.csv
```

### Find Untagged Resources

```bash
# Interactive mode
bluearch-aws-tags
# Select option 2: Resource Organization
# Select option 2: List untagged resources
```

## Development

### Setup Development Environment

```bash
git clone <repository-url>
cd bluearch-aws-tags
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
pip install -r requirements.txt
pip install -e .
```

### Running Tests

```bash
pytest
```

### Code Formatting

```bash
black tag_manager_cli/
flake8 tag_manager_cli/
mypy tag_manager_cli/
```

## Contributing

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Commit your changes (`git commit -m 'Add some amazing feature'`)
4. Push to the branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

## License

This project is licensed under the MIT License - see the LICENSE file for details.

## Support

For issues and questions:
1. Check the troubleshooting section below
2. Search existing issues
3. Create a new issue with detailed information

## Troubleshooting

### Common Issues

1. **"AWS_PROFILE environment variable not set"**
   - Set your AWS profile: `export AWS_PROFILE=your-sso-profile`

2. **"No valid AWS credentials found"**
   - Run `aws sso login` to refresh your session

3. **"Redis cache not available"**
   - Install and start Redis, or the CLI will work without caching

4. **"Failed to create DynamoDB table"**
   - Check your AWS permissions for DynamoDB operations

### Debug Mode

Enable verbose logging:
```bash
export TAG_MANAGER_DEBUG=1
bluearch-aws-tags interactive
```
