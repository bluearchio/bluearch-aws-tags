"""AWS tools for querying AWS resources using existing SSO authentication."""

import shlex
import shutil
import subprocess
import sys
from typing import Dict, Any, List, Optional
from datetime import datetime, timedelta
from botocore.exceptions import ClientError

from ..utils.aws_auth import aws_auth
from ..utils.core_storage import list_all_records
from ..utils.public_executables import (
    PUBLIC_TAGS_EXECUTABLE,
    resolve_public_tags_executable,
)


def _find_public_tags_executable() -> str | None:
    """Find a canonical packaged or PATH-installed public Tags executable."""
    for candidate in (sys.executable, shutil.which(PUBLIC_TAGS_EXECUTABLE)):
        resolved = resolve_public_tags_executable(candidate)
        if resolved:
            return resolved
    return None


class AWSTools:
    """AWS API operations exposed as tools for the AI assistant."""

    # Session-level account scope state for cross-account queries
    _account_scope: Optional[List[str]] = None
    _scope_mode: str = "current"  # "current", "specific", "all_enabled"

    @staticmethod
    def get_tools_schema() -> List[Dict[str, Any]]:
        """Get tool schemas for all available AWS operations."""
        return [
            {
                "name": "list_ec2_instances",
                "description": "List EC2 instances in specified regions with details like instance ID, type, state, name tag, and launch time. Supports cross-account queries when account_ids is provided.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "regions": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "AWS regions to query (default: current region)"
                        },
                        "state": {
                            "type": "string",
                            "enum": ["running", "stopped", "terminated", "all"],
                            "description": "Filter by instance state (default: running)"
                        },
                        "account_ids": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "AWS account IDs to query. If not provided, uses current session scope."
                        }
                    }
                }
            },
            {
                "name": "describe_s3_buckets",
                "description": "List all S3 buckets with regions, creation dates, and tags. Supports cross-account queries when account_ids is provided.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "include_tags": {
                            "type": "boolean",
                            "description": "Include bucket tags (default: true)"
                        },
                        "account_ids": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "AWS account IDs to query. If not provided, uses current session scope."
                        }
                    }
                }
            },
            {
                "name": "list_lambda_functions",
                "description": "List Lambda functions with runtime, memory, timeout, and modification date. Supports cross-account queries when account_ids is provided.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "regions": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "AWS regions to query"
                        },
                        "runtime": {
                            "type": "string",
                            "description": "Filter by runtime (e.g. python3.11)"
                        },
                        "account_ids": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "AWS account IDs to query. If not provided, uses current session scope."
                        }
                    }
                }
            },
            {
                "name": "query_cur_costs",
                "description": "PREFERRED: Query Cost and Usage Reports (CUR) using natural language. Translates questions to Athena SQL and returns detailed cost data. CUR contains data for ALL linked accounts in the organization. Use account_ids to filter to specific accounts, or query all by default. Supports: resource-level detail, usage types, regions, instance types, cost by account. Examples: 'What are my top services?', 'Show costs by account', 'Break down EC2 by instance type'.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "question": {
                            "type": "string",
                            "description": "Natural language cost question (e.g., 'What are my top 5 spending services?', 'Show EC2 costs by instance type', 'Show costs by account')"
                        },
                        "account_ids": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Filter to specific AWS account IDs. If not provided, queries all accounts in CUR data."
                        }
                    },
                    "required": ["question"]
                }
            },
            {
                "name": "get_cost_analysis",
                "description": "FALLBACK: Basic cost analysis using Cost Explorer API. Only use when CUR is not available or for simple high-level summaries. For detailed analysis, prefer query_cur_costs which provides resource-level detail.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "start_date": {
                            "type": "string",
                            "description": "Start date YYYY-MM-DD (default: 30 days ago)"
                        },
                        "end_date": {
                            "type": "string",
                            "description": "End date YYYY-MM-DD (default: today)"
                        },
                        "group_by": {
                            "type": "string",
                            "enum": ["SERVICE", "TAG", "LINKED_ACCOUNT"],
                            "description": "How to group costs (default: SERVICE)"
                        },
                        "tag_key": {
                            "type": "string",
                            "description": "Tag key for grouping (when group_by=TAG)"
                        }
                    }
                }
            },
            {
                "name": "find_untagged_resources",
                "description": "Find resources missing required tags from the Tag Manager database",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "resource_types": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Filter by types (e.g. AWS::EC2::Instance)"
                        },
                        "required_tags": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Required tag keys (default: Environment, Owner, Project)"
                        },
                        "limit": {
                            "type": "integer",
                            "description": "Max results (default: 50)"
                        }
                    }
                }
            },
            {
                "name": "list_iam_users",
                "description": "List IAM users with creation dates, password age, and access key information",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "include_access_keys": {
                            "type": "boolean",
                            "description": "Include access key details (default: true)"
                        }
                    }
                }
            },
            {
                "name": "describe_rds_instances",
                "description": "List RDS database instances with engine, size, status, and configuration. Supports cross-account queries when account_ids is provided.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "regions": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "AWS regions to query"
                        },
                        "engine": {
                            "type": "string",
                            "description": "Filter by engine (e.g. postgres, mysql)"
                        },
                        "account_ids": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "AWS account IDs to query. If not provided, uses current session scope."
                        }
                    }
                }
            },
            {
                "name": "list_vpc_resources",
                "description": "List VPCs with subnets, CIDR blocks, and configuration. Supports cross-account queries when account_ids is provided.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "regions": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "AWS regions to query"
                        },
                        "vpc_id": {
                            "type": "string",
                            "description": "Filter by VPC ID"
                        },
                        "account_ids": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "AWS account IDs to query. If not provided, uses current session scope."
                        }
                    }
                }
            },
            {
                "name": "get_account_summary",
                "description": "Get AWS account summary with account ID, regions, and resource counts",
                "input_schema": {
                    "type": "object",
                    "properties": {}
                }
            },
            {
                "name": "get_tag_compliance_summary",
                "description": "Get overall tag compliance summary with statistics. Returns total resources, compliance rate, breakdown by status (fully compliant, partially compliant, non-compliant), required tags from org policy or defaults, and compliance mode (AND/OR). Use this to answer questions like 'What is my tag compliance rate?' or 'How many resources are missing tags?'",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "services": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Filter by AWS services (e.g. ec2, s3, lambda)"
                        },
                        "regions": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Filter by AWS regions"
                        },
                        "account_ids": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Filter by AWS account IDs"
                        }
                    }
                }
            },
            {
                "name": "get_tag_compliance_by_service",
                "description": "Get tag compliance breakdown by AWS service. Shows which services have the most untagged resources, sorted by compliance rate (worst first). Useful for identifying which services need the most attention. Use this to answer questions like 'Which services have the most untagged resources?' or 'What is my EC2 tag compliance?'",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "services": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Filter to specific services"
                        },
                        "regions": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Filter by AWS regions"
                        },
                        "account_ids": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Filter by AWS account IDs"
                        }
                    }
                }
            },
            {
                "name": "get_high_risk_untagged_resources",
                "description": "Get non-compliant resources with risk analysis. Categorizes resources by risk level (high: >1 week old or expensive services like EC2/RDS, medium: >1 day old, low: recently created). Includes missing tags, age, and remediation recommendations. Use this for questions like 'Show high-risk untagged resources' or 'Which untagged resources need immediate attention?'",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "services": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Filter by services (e.g. ec2, rds)"
                        },
                        "regions": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Filter by regions"
                        },
                        "account_ids": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Filter by AWS account IDs"
                        },
                        "risk_level": {
                            "type": "string",
                            "enum": ["high", "medium", "low"],
                            "description": "Filter by risk level (default: all levels)"
                        },
                        "min_age_hours": {
                            "type": "integer",
                            "description": "Only include resources older than N hours"
                        },
                        "limit": {
                            "type": "integer",
                            "description": "Maximum resources to return (default: 50)"
                        }
                    }
                }
            },
            {
                "name": "execute_aws_cli",
                "description": "Execute read-only AWS CLI commands for services not covered by other tools. Provide exact AWS CLI command syntax. Covers: CloudWatch Logs, CloudFormation, ECS, EKS, SNS, SQS, DynamoDB, Secrets Manager, SSM, API Gateway, EventBridge, Step Functions, Glue, Athena, Backup, ECR, KMS, ACM, Route53, ElastiCache.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "command": {
                            "type": "string",
                            "description": "AWS CLI command to execute (without 'aws' prefix). Examples: 'cloudformation list-stacks', 'logs describe-log-groups', 'ecs list-clusters', 'dynamodb list-tables'."
                        },
                        "region": {
                            "type": "string",
                            "description": "AWS region (default: us-east-1)"
                        }
                    },
                    "required": ["command"]
                }
            },
            {
                "name": "suggest_cloudwatch_alarms",
                "description": "Suggest CloudWatch alarm templates for a specific resource. Returns available alarm types with recommended thresholds for the resource type. Use this to answer questions like 'What alarms should I create for this EC2 instance?' or 'Suggest monitoring for my RDS database'.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "resource_arn": {
                            "type": "string",
                            "description": "AWS ARN of the resource to get alarm suggestions for"
                        }
                    },
                    "required": ["resource_arn"]
                }
            },
            {
                "name": "list_managed_alarms",
                "description": "List CloudWatch alarms created and managed by BlueArch AWS Tags. Shows alarm state, target resource, owner, and configuration. Use this to answer questions like 'What alarms have I created?' or 'Show alarms in ALARM state'.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "service": {
                            "type": "string",
                            "description": "Filter by target service (ec2, rds, lambda)"
                        },
                        "state": {
                            "type": "string",
                            "enum": ["OK", "ALARM", "INSUFFICIENT_DATA"],
                            "description": "Filter by alarm state"
                        },
                        "resource_arn": {
                            "type": "string",
                            "description": "Filter by target resource ARN"
                        },
                        "limit": {
                            "type": "integer",
                            "description": "Maximum alarms to return (default: 50)"
                        }
                    }
                }
            },
            {
                "name": "get_alarm_templates",
                "description": "Get available CloudWatch alarm templates. Returns all built-in alarm templates organized by service with default thresholds and metrics. Use this to see what types of alarms are available.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "service": {
                            "type": "string",
                            "description": "Filter templates by service (ec2, rds, lambda, sqs, dynamodb, elb, s3)"
                        }
                    }
                }
            },
            {
                "name": "create_cloudwatch_alarm",
                "description": "Create a CloudWatch alarm for a resource. IMPORTANT: This is a WRITE operation that requires user confirmation. Always call this in preview mode first to show the user what will be created, then ask for confirmation before actually creating. Tags the alarm with CreatedBy=tag-manager-cli and sets up SNS notifications if owner_email is provided.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "resource_arn": {
                            "type": "string",
                            "description": "AWS ARN of the resource to monitor"
                        },
                        "alarm_type": {
                            "type": "string",
                            "description": "Type of alarm from templates (e.g., cpu_high, errors, free_storage_low)"
                        },
                        "threshold": {
                            "type": "number",
                            "description": "Custom threshold (uses template default if not specified)"
                        },
                        "owner_email": {
                            "type": "string",
                            "description": "Email address for alarm notifications. Creates SNS topic if needed."
                        },
                        "preview_only": {
                            "type": "boolean",
                            "description": "If true, only return preview without creating. ALWAYS call with preview_only=true first."
                        }
                    },
                    "required": ["resource_arn", "alarm_type"]
                }
            },
            # Cross-account tools
            {
                "name": "list_available_accounts",
                "description": "List AWS accounts in the organization with names and enabled status. Use this to identify account IDs when the user mentions account names (e.g., 'production', 'staging'). Returns current account, enabled accounts for cross-account queries, and all org accounts with friendly names.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "include_disabled": {
                            "type": "boolean",
                            "description": "Include accounts not enabled for bluearch-aws-tags cross-account access (default: false)"
                        }
                    }
                }
            },
            {
                "name": "set_account_scope",
                "description": "Set account scope for subsequent queries in this session. Use 'current' for current account only (default), 'all' for all enabled accounts, or 'specific' with account_ids for specific accounts. The scope persists for the session. IMPORTANT: Before running multi-account queries, ASK the user which scope they prefer unless they explicitly requested 'all accounts' or named a specific account.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "scope": {
                            "type": "string",
                            "enum": ["current", "all", "specific"],
                            "description": "Scope mode: 'current' (default), 'all' (all enabled accounts), 'specific' (use account_ids)"
                        },
                        "account_ids": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Account IDs when scope='specific'. Use list_available_accounts to find IDs."
                        }
                    },
                    "required": ["scope"]
                }
            },
            {
                "name": "get_current_account_scope",
                "description": "Get the current account scope setting for this session. Returns the scope mode (current/all/specific) and which accounts are included.",
                "input_schema": {
                    "type": "object",
                    "properties": {}
                }
            },
            # CLI Self-Awareness Tools
            {
                "name": "run_tag_manager_command",
                "description": "Run a bluearch-aws-tags CLI command and return the output. Use for resource discovery, tag scanning, cost analysis, and other read-only CLI operations. Only safe commands are allowed.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "command": {
                            "type": "string",
                            "description": "The bluearch-aws-tags command to run (e.g., 'discover all', 'lifecycle scan', 'cost summary', 'cost services')"
                        },
                        "args": {
                            "type": "string",
                            "description": "Optional arguments for the command (e.g., '--region us-east-1')"
                        }
                    },
                    "required": ["command"]
                }
            },
            {
                "name": "get_cli_help",
                "description": "Get help about bluearch-aws-tags CLI commands, including usage, examples, prerequisites, and troubleshooting. Use when users ask about CLI commands or need help with errors.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "topic": {
                            "type": "string",
                            "description": "Topic to get help for: 'commands' (overview), 'cost' (cost commands), 'tags' (tagging commands), 'discover' (resource discovery), 'accounts' (cross-account), 'setup' (configuration), 'troubleshooting' (common issues)"
                        }
                    }
                }
            }
        ]

    @classmethod
    def list_ec2_instances(
        cls,
        regions: Optional[List[str]] = None,
        state: str = "running",
        account_ids: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        """List EC2 instances with optional cross-account support."""
        from concurrent.futures import ThreadPoolExecutor, as_completed

        if not regions:
            from ..utils.env_config import settings
            regions = [settings.aws_region]

        # Get effective accounts to query
        accounts = cls.get_effective_accounts(account_ids)
        current_account = aws_auth.get_caller_identity()['Account']

        results = {
            "instances": [],
            "total_count": 0,
            "by_region": {},
            "by_account": {},
            "accounts_queried": accounts
        }

        def query_account_region(account_id: str, region: str):
            """Query a single account/region combination."""
            try:
                # Get client for the account
                if account_id == current_account:
                    ec2_client = aws_auth.get_client('ec2', region=region)
                else:
                    ec2_client = aws_auth.get_client_for_account(
                        account_id, 'ec2', region=region
                    )

                filters = []
                if state != "all":
                    filters.append({'Name': 'instance-state-name', 'Values': [state]})

                response = ec2_client.describe_instances(Filters=filters)

                instances = []
                for reservation in response.get('Reservations', []):
                    for instance in reservation.get('Instances', []):
                        name = 'N/A'
                        for tag in instance.get('Tags', []):
                            if tag['Key'] == 'Name':
                                name = tag['Value']
                                break

                        instances.append({
                            'instance_id': instance['InstanceId'],
                            'name': name,
                            'type': instance['InstanceType'],
                            'state': instance['State']['Name'],
                            'launch_time': instance.get('LaunchTime').isoformat() if instance.get('LaunchTime') else None,
                            'private_ip': instance.get('PrivateIpAddress'),
                            'public_ip': instance.get('PublicIpAddress'),
                            'region': region,
                            'account_id': account_id
                        })

                return {'account_id': account_id, 'region': region, 'instances': instances, 'error': None}

            except ClientError as e:
                return {'account_id': account_id, 'region': region, 'instances': [], 'error': str(e)}

        # Execute queries in parallel
        with ThreadPoolExecutor(max_workers=10) as executor:
            futures = []
            for account_id in accounts:
                for region in regions:
                    futures.append(executor.submit(query_account_region, account_id, region))

            for future in as_completed(futures):
                result = future.result()
                account_id = result['account_id']
                region = result['region']

                if result['error']:
                    key = f"{account_id}:{region}"
                    results['by_region'][key] = f"Error: {result['error']}"
                else:
                    results['instances'].extend(result['instances'])
                    # Track by region
                    if region not in results['by_region']:
                        results['by_region'][region] = 0
                    results['by_region'][region] += len(result['instances'])
                    # Track by account
                    if account_id not in results['by_account']:
                        results['by_account'][account_id] = 0
                    results['by_account'][account_id] += len(result['instances'])

        results['total_count'] = len(results['instances'])
        return results

    @classmethod
    def describe_s3_buckets(
        cls,
        include_tags: bool = True,
        account_ids: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        """List S3 buckets with optional cross-account support."""
        from concurrent.futures import ThreadPoolExecutor, as_completed

        # Get effective accounts to query
        accounts = cls.get_effective_accounts(account_ids)
        current_account = aws_auth.get_caller_identity()['Account']

        results = {
            "buckets": [],
            "total_count": 0,
            "by_account": {},
            "accounts_queried": accounts
        }

        def query_account(account_id: str):
            """Query S3 buckets for a single account."""
            try:
                # Get client for the account
                if account_id == current_account:
                    s3_client = aws_auth.get_client('s3')
                else:
                    s3_client = aws_auth.get_client_for_account(account_id, 's3')

                response = s3_client.list_buckets()

                buckets = []
                for bucket in response.get('Buckets', []):
                    bucket_info = {
                        'name': bucket['Name'],
                        'creation_date': bucket['CreationDate'].isoformat(),
                        'account_id': account_id
                    }

                    if include_tags:
                        try:
                            tags_response = s3_client.get_bucket_tagging(Bucket=bucket['Name'])
                            bucket_info['tags'] = {
                                tag['Key']: tag['Value']
                                for tag in tags_response.get('TagSet', [])
                            }
                        except ClientError:
                            bucket_info['tags'] = {}

                    try:
                        location = s3_client.get_bucket_location(Bucket=bucket['Name'])
                        bucket_info['region'] = location.get('LocationConstraint') or 'us-east-1'
                    except ClientError:
                        bucket_info['region'] = 'unknown'

                    buckets.append(bucket_info)

                return {'account_id': account_id, 'buckets': buckets, 'error': None}

            except ClientError as e:
                return {'account_id': account_id, 'buckets': [], 'error': str(e)}

        # Execute queries in parallel
        with ThreadPoolExecutor(max_workers=10) as executor:
            futures = [executor.submit(query_account, acc) for acc in accounts]

            for future in as_completed(futures):
                result = future.result()
                account_id = result['account_id']

                if result['error']:
                    results['by_account'][account_id] = f"Error: {result['error']}"
                else:
                    results['buckets'].extend(result['buckets'])
                    results['by_account'][account_id] = len(result['buckets'])

        results['total_count'] = len(results['buckets'])
        return results

    @classmethod
    def list_lambda_functions(
        cls,
        regions: Optional[List[str]] = None,
        runtime: Optional[str] = None,
        account_ids: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        """List Lambda functions with optional cross-account support."""
        from concurrent.futures import ThreadPoolExecutor, as_completed

        if not regions:
            from ..utils.env_config import settings
            regions = [settings.aws_region]

        # Get effective accounts to query
        accounts = cls.get_effective_accounts(account_ids)
        current_account = aws_auth.get_caller_identity()['Account']

        results = {
            "functions": [],
            "total_count": 0,
            "by_region": {},
            "by_account": {},
            "accounts_queried": accounts
        }

        def query_account_region(account_id: str, region: str):
            """Query Lambda functions for a single account/region."""
            try:
                # Get client for the account
                if account_id == current_account:
                    lambda_client = aws_auth.get_client('lambda', region=region)
                else:
                    lambda_client = aws_auth.get_client_for_account(
                        account_id, 'lambda', region=region
                    )

                response = lambda_client.list_functions()

                functions = []
                for func in response.get('Functions', []):
                    if runtime and func.get('Runtime') != runtime:
                        continue

                    functions.append({
                        'name': func['FunctionName'],
                        'runtime': func.get('Runtime'),
                        'memory': func.get('MemorySize'),
                        'timeout': func.get('Timeout'),
                        'last_modified': func.get('LastModified'),
                        'code_size': func.get('CodeSize'),
                        'region': region,
                        'account_id': account_id
                    })

                return {'account_id': account_id, 'region': region, 'functions': functions, 'error': None}

            except ClientError as e:
                return {'account_id': account_id, 'region': region, 'functions': [], 'error': str(e)}

        # Execute queries in parallel
        with ThreadPoolExecutor(max_workers=10) as executor:
            futures = []
            for account_id in accounts:
                for region in regions:
                    futures.append(executor.submit(query_account_region, account_id, region))

            for future in as_completed(futures):
                result = future.result()
                account_id = result['account_id']
                region = result['region']

                if result['error']:
                    key = f"{account_id}:{region}"
                    results['by_region'][key] = f"Error: {result['error']}"
                else:
                    results['functions'].extend(result['functions'])
                    # Track by region
                    if region not in results['by_region']:
                        results['by_region'][region] = 0
                    results['by_region'][region] += len(result['functions'])
                    # Track by account
                    if account_id not in results['by_account']:
                        results['by_account'][account_id] = 0
                    results['by_account'][account_id] += len(result['functions'])

        results['total_count'] = len(results['functions'])
        return results

    @staticmethod
    def query_cur_costs(question: str, account_ids: Optional[List[str]] = None) -> Dict[str, Any]:
        """Query CUR using natural language - translates to Athena SQL.

        This is the PREFERRED method for cost analysis as it provides:
        - Resource-level detail
        - Usage type breakdown
        - Region/AZ analysis
        - Instance type breakdown
        - Tag-based queries
        - Multi-account cost breakdown

        Args:
            question: Natural language cost question
            account_ids: Optional list of account IDs to filter results
        """
        try:
            from ..modules.finops.cur_setup import CURSetup
            from ..modules.finops.cur_client import CURClient
            from ..integrations.model_resolver import get_latest_haiku

            # Check for CUR configuration
            setup = CURSetup()
            cur_config = setup.detect_existing_cur()

            if not cur_config or cur_config.status != 'active':
                return {
                    'error': 'CUR not configured',
                    'suggestion': 'CUR (Cost and Usage Reports) is not available. Falling back to Cost Explorer API would provide less detail. Run "bluearch-aws-tags cost setup detect" to configure CUR.',
                    'cur_available': False
                }

            # Build account filter clause if account_ids provided
            account_filter_clause = ""
            account_filter_note = ""
            if account_ids:
                quoted_ids = "', '".join(account_ids)
                account_filter_clause = f"line_item_usage_account_id IN ('{quoted_ids}')"
                account_filter_note = f"\n\nACCOUNT FILTER: The query MUST include this filter in the WHERE clause:\n{account_filter_clause}"

            # CUR Query System Prompt
            cur_system_prompt = f"""You are an AWS Cost and Usage Report (CUR) analyst. Generate Athena SQL queries for cost questions.

RULES:
1. ONLY generate SELECT queries
2. Include LIMIT (default 100) unless aggregating totals
3. Use SUM(line_item_unblended_cost) as cost for aggregations
4. Filter out zero/negative costs: line_item_unblended_cost > 0
5. Use date_add('day', -30, current_date) for last 30 days{account_filter_note}

KEY CUR COLUMNS:
- line_item_unblended_cost: The cost amount
- line_item_usage_start_date: Usage timestamp
- line_item_product_code: AWS service (AmazonEC2, AmazonS3, AmazonRDS, etc.)
- line_item_usage_type: Specific usage (BoxUsage, DataTransfer-Out-Bytes, etc.)
- line_item_resource_id: Resource ARN
- line_item_usage_account_id: Account ID (use for multi-account breakdown)
- product_region: AWS region
- product_instance_type: EC2/RDS instance type
- product_instance_family: Instance family (t3, m5, etc.)
- product_database_engine: RDS engine
- pricing_term: OnDemand, Reserved, Spot
- resource_tags_user_*: User tags (e.g., resource_tags_user_environment)

COMMON QUERIES:

Top services:
SELECT line_item_product_code as service, SUM(line_item_unblended_cost) as cost
FROM {{table}} WHERE line_item_unblended_cost > 0
GROUP BY 1 ORDER BY cost DESC LIMIT 20

Costs by account:
SELECT line_item_usage_account_id as account_id, SUM(line_item_unblended_cost) as cost
FROM {{table}} WHERE line_item_unblended_cost > 0
GROUP BY 1 ORDER BY cost DESC

EC2 by instance type:
SELECT product_instance_type, SUM(line_item_unblended_cost) as cost
FROM {{table}} WHERE line_item_product_code = 'AmazonEC2'
  AND line_item_usage_type LIKE '%BoxUsage%' AND line_item_unblended_cost > 0
GROUP BY 1 ORDER BY cost DESC

Break down "Others" or detailed usage types:
SELECT line_item_product_code, line_item_usage_type, SUM(line_item_unblended_cost) as cost, COUNT(*) as line_count
FROM {{table}} WHERE line_item_unblended_cost > 0
GROUP BY 1, 2 ORDER BY cost DESC

Costs by region:
SELECT product_region, SUM(line_item_unblended_cost) as cost
FROM {{table}} WHERE line_item_unblended_cost > 0
GROUP BY 1 ORDER BY cost DESC

OUTPUT: Return ONLY the SQL query. No explanations. No markdown."""

            # Generate SQL using Bedrock
            bedrock_client = aws_auth.get_client('bedrock-runtime', region='us-east-1')
            model_id = get_latest_haiku("us-east-1")

            full_table = f'"{cur_config.athena_database}"."{cur_config.athena_table}"'
            user_prompt = f"""Generate an Athena SQL query for: {question}

Table: {full_table}

Return ONLY the SQL query."""

            response = bedrock_client.converse(
                modelId=model_id,
                messages=[{"role": "user", "content": [{"text": user_prompt}]}],
                system=[{"text": cur_system_prompt.replace("{table}", full_table)}],
                inferenceConfig={"maxTokens": 1000, "temperature": 0.1}
            )

            sql_query = response['output']['message']['content'][0]['text'].strip()

            # Clean up SQL
            if sql_query.startswith("```"):
                lines = sql_query.split('\n')
                sql_query = '\n'.join(lines[1:-1] if lines[-1] == '```' else lines[1:])
            sql_query = sql_query.replace("{table}", full_table)

            # Execute query
            cur_client = CURClient(cur_config)
            results = cur_client.execute_query(sql_query, cache_ttl=300)

            if not results:
                return {
                    'data': [],
                    'message': 'Query returned no results',
                    'sql_query': sql_query,
                    'cur_available': True,
                    'account_filter': account_ids if account_ids else 'all accounts'
                }

            # Calculate total if cost column exists
            total_cost = None
            if results:
                cost_cols = [k for k in results[0].keys() if 'cost' in k.lower()]
                if cost_cols:
                    total_cost = sum(float(r.get(cost_cols[0], 0) or 0) for r in results)

            return {
                'data': results[:100],  # Limit response size
                'total_rows': len(results),
                'total_cost': round(total_cost, 2) if total_cost else None,
                'sql_query': sql_query,
                'cur_available': True,
                'source': 'CUR (Cost and Usage Reports)',
                'database': cur_config.athena_database,
                'table': cur_config.athena_table,
                'account_filter': account_ids if account_ids else 'all accounts'
            }

        except Exception as e:
            return {
                'error': str(e),
                'cur_available': False,
                'suggestion': 'CUR query failed. You may fall back to get_cost_analysis for basic summaries.'
            }

    @staticmethod
    def get_cost_analysis(
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        group_by: str = "SERVICE",
        tag_key: Optional[str] = None
    ) -> Dict[str, Any]:
        """Get cost analysis using Cost Explorer API (FALLBACK - less detail than CUR)."""
        try:
            ce_client = aws_auth.get_client('ce', region='us-east-1')

            if not end_date:
                end_date = datetime.now().strftime('%Y-%m-%d')
            if not start_date:
                start_date = (datetime.now() - timedelta(days=30)).strftime('%Y-%m-%d')

            group_by_param = [{'Type': 'DIMENSION', 'Key': group_by}]
            if group_by == "TAG" and tag_key:
                group_by_param = [{'Type': 'TAG', 'Key': tag_key}]

            response = ce_client.get_cost_and_usage(
                TimePeriod={'Start': start_date, 'End': end_date},
                Granularity='MONTHLY',
                Metrics=['UnblendedCost'],
                GroupBy=group_by_param
            )

            costs = []
            total_cost = 0.0

            for result in response.get('ResultsByTime', []):
                period = result['TimePeriod']
                for group in result.get('Groups', []):
                    amount = float(group['Metrics']['UnblendedCost']['Amount'])
                    total_cost += amount
                    costs.append({
                        'period': f"{period['Start']} to {period['End']}",
                        'category': group['Keys'][0],
                        'amount': round(amount, 2),
                        'unit': group['Metrics']['UnblendedCost']['Unit']
                    })

            return {
                'costs': costs,
                'total_cost': round(total_cost, 2),
                'currency': 'USD',
                'period': f"{start_date} to {end_date}",
                'grouped_by': group_by
            }

        except ClientError as e:
            return {'error': str(e)}

    @staticmethod
    def find_untagged_resources(
        resource_types: Optional[List[str]] = None,
        required_tags: Optional[List[str]] = None,
        limit: int = 50
    ) -> Dict[str, Any]:
        """Find resources missing required tags using org policy compliance logic."""
        try:
            from ..services.org_policy_provider import org_policy_provider
            import json as json_module

            # Get required tags from org policy if not specified
            if not required_tags:
                required_tags, from_org_policy, _ = org_policy_provider.get_required_tags(
                    show_warnings=False
                )
            else:
                from_org_policy = False

            all_resources = list_all_records(
                "core",
                "resources",
                filters=[("lifecycle_state", "active")],
            )

            untagged = []
            for resource in all_resources:
                if len(untagged) >= limit:
                    break
                if resource_types and resource.get("resource_type") not in resource_types:
                    continue

                # Parse tags (handle string or dict)
                current_tags = resource.get("current_tags") or {}
                if isinstance(current_tags, str):
                    try:
                        current_tags = json_module.loads(current_tags) if current_tags else {}
                    except json_module.JSONDecodeError:
                        current_tags = {}

                # Use proper compliance check
                result = org_policy_provider.check_resource_compliance_detailed(
                    current_tags, required_tags, from_org_policy
                )

                if not result.is_compliant:
                    untagged.append({
                        'resource_arn': resource.get("resource_arn"),
                        'resource_type': resource.get("resource_type"),
                        'resource_id': resource.get("resource_id"),
                        'region': resource.get("region"),
                        'account_id': resource.get("account_id"),
                        'missing_tags': result.missing_tags,
                        'matched_tags': result.matched_tags,
                        'existing_tags': list(current_tags.keys())
                    })

                return {
                    'untagged_resources': untagged,
                    'count': len(untagged),
                    'required_tags': required_tags,
                    'policy_source': 'org_policy' if from_org_policy else 'default',
                    'compliance_mode': 'AND' if from_org_policy else 'OR'
                }

        except Exception as e:
            return {'error': str(e)}

    @staticmethod
    def list_iam_users(include_access_keys: bool = True) -> Dict[str, Any]:
        """List IAM users."""
        try:
            iam_client = aws_auth.get_client('iam')
            response = iam_client.list_users()

            users = []
            for user in response.get('Users', []):
                user_info = {
                    'username': user['UserName'],
                    'user_id': user['UserId'],
                    'arn': user['Arn'],
                    'create_date': user['CreateDate'].isoformat(),
                    'password_last_used': user.get('PasswordLastUsed').isoformat() if user.get('PasswordLastUsed') else None
                }

                if include_access_keys:
                    try:
                        keys_response = iam_client.list_access_keys(UserName=user['UserName'])
                        user_info['access_keys'] = [
                            {
                                'key_id': key['AccessKeyId'],
                                'status': key['Status'],
                                'create_date': key['CreateDate'].isoformat()
                            }
                            for key in keys_response.get('AccessKeyMetadata', [])
                        ]
                    except ClientError:
                        user_info['access_keys'] = []

                users.append(user_info)

            return {'users': users, 'total_count': len(users)}

        except ClientError as e:
            return {'error': str(e)}

    @classmethod
    def describe_rds_instances(
        cls,
        regions: Optional[List[str]] = None,
        engine: Optional[str] = None,
        account_ids: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        """List RDS instances with optional cross-account support."""
        from concurrent.futures import ThreadPoolExecutor, as_completed

        if not regions:
            from ..utils.env_config import settings
            regions = [settings.aws_region]

        # Get effective accounts to query
        accounts = cls.get_effective_accounts(account_ids)
        current_account = aws_auth.get_caller_identity()['Account']

        results = {
            "instances": [],
            "total_count": 0,
            "by_region": {},
            "by_account": {},
            "accounts_queried": accounts
        }

        def query_account_region(account_id: str, region: str):
            """Query RDS instances for a single account/region."""
            try:
                if account_id == current_account:
                    rds_client = aws_auth.get_client('rds', region=region)
                else:
                    rds_client = aws_auth.get_client_for_account(
                        account_id, 'rds', region=region
                    )

                response = rds_client.describe_db_instances()

                instances = []
                for db in response.get('DBInstances', []):
                    if engine and db.get('Engine') != engine:
                        continue

                    instances.append({
                        'identifier': db['DBInstanceIdentifier'],
                        'engine': db['Engine'],
                        'engine_version': db.get('EngineVersion'),
                        'instance_class': db['DBInstanceClass'],
                        'status': db['DBInstanceStatus'],
                        'allocated_storage': db.get('AllocatedStorage'),
                        'multi_az': db.get('MultiAZ', False),
                        'region': region,
                        'account_id': account_id
                    })

                return {'account_id': account_id, 'region': region, 'instances': instances, 'error': None}

            except ClientError as e:
                return {'account_id': account_id, 'region': region, 'instances': [], 'error': str(e)}

        # Execute queries in parallel
        with ThreadPoolExecutor(max_workers=10) as executor:
            futures = []
            for account_id in accounts:
                for region in regions:
                    futures.append(executor.submit(query_account_region, account_id, region))

            for future in as_completed(futures):
                result = future.result()
                account_id = result['account_id']
                region = result['region']

                if result['error']:
                    key = f"{account_id}:{region}"
                    results['by_region'][key] = f"Error: {result['error']}"
                else:
                    results['instances'].extend(result['instances'])
                    if region not in results['by_region']:
                        results['by_region'][region] = 0
                    results['by_region'][region] += len(result['instances'])
                    if account_id not in results['by_account']:
                        results['by_account'][account_id] = 0
                    results['by_account'][account_id] += len(result['instances'])

        results['total_count'] = len(results['instances'])
        return results

    @classmethod
    def list_vpc_resources(
        cls,
        regions: Optional[List[str]] = None,
        vpc_id: Optional[str] = None,
        account_ids: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        """List VPC resources with optional cross-account support."""
        from concurrent.futures import ThreadPoolExecutor, as_completed

        if not regions:
            from ..utils.env_config import settings
            regions = [settings.aws_region]

        # Get effective accounts to query
        accounts = cls.get_effective_accounts(account_ids)
        current_account = aws_auth.get_caller_identity()['Account']

        results = {
            "vpcs": [],
            "total_vpcs": 0,
            "by_region": {},
            "by_account": {},
            "accounts_queried": accounts
        }

        def query_account_region(account_id: str, region: str):
            """Query VPCs for a single account/region."""
            try:
                if account_id == current_account:
                    ec2_client = aws_auth.get_client('ec2', region=region)
                else:
                    ec2_client = aws_auth.get_client_for_account(
                        account_id, 'ec2', region=region
                    )

                filters = []
                if vpc_id:
                    filters.append({'Name': 'vpc-id', 'Values': [vpc_id]})

                vpcs_response = ec2_client.describe_vpcs(Filters=filters) if filters else ec2_client.describe_vpcs()

                vpcs = []
                for vpc in vpcs_response.get('Vpcs', []):
                    vpc_info = {
                        'vpc_id': vpc['VpcId'],
                        'cidr_block': vpc['CidrBlock'],
                        'state': vpc['State'],
                        'is_default': vpc.get('IsDefault', False),
                        'region': region,
                        'account_id': account_id
                    }

                    subnets_response = ec2_client.describe_subnets(
                        Filters=[{'Name': 'vpc-id', 'Values': [vpc['VpcId']]}]
                    )
                    vpc_info['subnet_count'] = len(subnets_response.get('Subnets', []))

                    vpcs.append(vpc_info)

                return {'account_id': account_id, 'region': region, 'vpcs': vpcs, 'error': None}

            except ClientError as e:
                return {'account_id': account_id, 'region': region, 'vpcs': [], 'error': str(e)}

        # Execute queries in parallel
        with ThreadPoolExecutor(max_workers=10) as executor:
            futures = []
            for account_id in accounts:
                for region in regions:
                    futures.append(executor.submit(query_account_region, account_id, region))

            for future in as_completed(futures):
                result = future.result()
                account_id = result['account_id']
                region = result['region']

                if result['error']:
                    key = f"{account_id}:{region}"
                    results['by_region'][key] = f"Error: {result['error']}"
                else:
                    results['vpcs'].extend(result['vpcs'])
                    if region not in results['by_region']:
                        results['by_region'][region] = 0
                    results['by_region'][region] += len(result['vpcs'])
                    if account_id not in results['by_account']:
                        results['by_account'][account_id] = 0
                    results['by_account'][account_id] += len(result['vpcs'])

        results['total_vpcs'] = len(results['vpcs'])
        return results

    @staticmethod
    def get_account_summary() -> Dict[str, Any]:
        """Get AWS account summary."""
        try:
            sts_client = aws_auth.get_client('sts')
            identity = sts_client.get_caller_identity()

            ec2_client = aws_auth.get_client('ec2')
            regions_response = ec2_client.describe_regions()
            enabled_regions = [r['RegionName'] for r in regions_response.get('Regions', [])]

            summary = {
                'account_id': identity['Account'],
                'user_arn': identity['Arn'],
                'enabled_regions': enabled_regions,
                'region_count': len(enabled_regions)
            }

            try:
                summary['discovered_resources'] = len(list_all_records("core", "resources"))
            except Exception:
                summary['discovered_resources'] = 'Core storage not available'

            return summary

        except ClientError as e:
            return {'error': str(e)}

    @staticmethod
    def get_tag_compliance_summary(
        services: Optional[List[str]] = None,
        regions: Optional[List[str]] = None,
        account_ids: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        """Get overall tag compliance summary."""
        try:
            from ..services.tag_compliance_service import tag_compliance_service
            summary = tag_compliance_service.get_compliance_summary(
                services=services,
                regions=regions,
                account_ids=account_ids
            )
            return summary.to_dict()
        except Exception as e:
            return {'error': str(e)}

    @staticmethod
    def get_tag_compliance_by_service(
        services: Optional[List[str]] = None,
        regions: Optional[List[str]] = None,
        account_ids: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        """Get tag compliance breakdown by service."""
        try:
            from ..services.tag_compliance_service import tag_compliance_service
            breakdown = tag_compliance_service.get_service_breakdown(
                services=services,
                regions=regions,
                account_ids=account_ids
            )
            return {
                'services': [s.to_dict() for s in breakdown],
                'count': len(breakdown),
                'worst_service': breakdown[0].to_dict() if breakdown else None
            }
        except Exception as e:
            return {'error': str(e)}

    @staticmethod
    def get_high_risk_untagged_resources(
        services: Optional[List[str]] = None,
        regions: Optional[List[str]] = None,
        account_ids: Optional[List[str]] = None,
        risk_level: Optional[str] = None,
        min_age_hours: int = 0,
        limit: int = 50
    ) -> Dict[str, Any]:
        """Get non-compliant resources with risk analysis."""
        try:
            from ..services.tag_compliance_service import tag_compliance_service
            return tag_compliance_service.get_non_compliant_resources(
                services=services,
                regions=regions,
                account_ids=account_ids,
                min_age_hours=min_age_hours,
                risk_level=risk_level,
                limit=limit
            )
        except Exception as e:
            return {'error': str(e)}

    @staticmethod
    def suggest_cloudwatch_alarms(resource_arn: str) -> Dict[str, Any]:
        """Suggest CloudWatch alarm templates for a resource."""
        try:
            from ..services.alarm_service import alarm_service
            suggestions = alarm_service.suggest_alarms_for_resource(resource_arn)
            return {
                'resource_arn': resource_arn,
                'suggestions': suggestions,
                'count': len(suggestions),
                'message': f"Found {len(suggestions)} alarm templates for this resource type"
            }
        except Exception as e:
            return {'error': str(e)}

    @staticmethod
    def list_managed_alarms(
        service: Optional[str] = None,
        state: Optional[str] = None,
        resource_arn: Optional[str] = None,
        limit: int = 50
    ) -> Dict[str, Any]:
        """List CloudWatch alarms managed by BlueArch AWS Tags."""
        try:
            from ..services.alarm_service import alarm_service
            alarms = alarm_service.list_alarms(
                service=service,
                resource_arn=resource_arn,
                state=state,
                managed_only=True,
                limit=limit
            )
            return {
                'alarms': alarms,
                'count': len(alarms),
                'filters': {
                    'service': service,
                    'state': state,
                    'resource_arn': resource_arn
                }
            }
        except Exception as e:
            return {'error': str(e)}

    @staticmethod
    def get_alarm_templates(service: Optional[str] = None) -> Dict[str, Any]:
        """Get available alarm templates."""
        try:
            from ..services.alarm_service import alarm_service
            templates = alarm_service.get_alarm_templates(service)
            return {
                'templates': templates,
                'count': len(templates),
                'service_filter': service
            }
        except Exception as e:
            return {'error': str(e)}

    @staticmethod
    def create_cloudwatch_alarm(
        resource_arn: str,
        alarm_type: str,
        threshold: Optional[float] = None,
        owner_email: Optional[str] = None,
        preview_only: bool = True
    ) -> Dict[str, Any]:
        """Create a CloudWatch alarm for a resource.

        This is a write operation. When preview_only=True, returns preview without creating.
        When preview_only=False, actually creates the alarm in AWS.
        """
        try:
            from ..services.alarm_service import alarm_service, AlarmConfig
            from ..templates.alarm_templates import (
                extract_service_from_arn,
                extract_resource_id_from_arn,
                get_template,
            )

            # Extract service and resource ID from ARN
            service = extract_service_from_arn(resource_arn)
            if not service:
                return {'error': f"Could not determine service from ARN: {resource_arn}"}

            resource_id = extract_resource_id_from_arn(resource_arn)
            if not resource_id:
                return {'error': f"Could not extract resource ID from ARN: {resource_arn}"}

            # Get template
            template_config = get_template(service, alarm_type)
            if not template_config:
                available = alarm_service.get_alarm_templates(service)
                return {
                    'error': f"Unknown alarm type '{alarm_type}' for service '{service}'",
                    'available_types': [t['template_name'] for t in available]
                }

            # Build alarm config
            config = AlarmConfig(
                resource_arn=resource_arn,
                resource_id=resource_id,
                service=service,
                template_name=alarm_type,
                metric_name=template_config["metric_name"],
                namespace=template_config["namespace"],
                statistic=template_config["statistic"],
                period=template_config["period"],
                evaluation_periods=template_config["evaluation_periods"],
                threshold=threshold if threshold is not None else template_config["threshold"],
                comparison_operator=template_config["comparison_operator"],
                treat_missing_data=template_config.get("treat_missing_data", "missing"),
                dimension_key=template_config.get("dimension_key", ""),
                dimension_value=resource_id,
                owner_email=owner_email,
            )

            # Create alarm (or preview)
            result = alarm_service.create_alarm(
                config=config,
                dry_run=preview_only,
                executed_by="ai_assistant",
                executed_via="ask_command",
            )

            if preview_only:
                return {
                    'preview': True,
                    'alarm_name': result.alarm_name,
                    'details': result.details,
                    'message': 'This is a preview. To create the alarm, ask the user for confirmation and call again with preview_only=false.',
                    'confirmation_required': True
                }
            else:
                return {
                    'success': result.success,
                    'alarm_name': result.alarm_name,
                    'alarm_arn': result.alarm_arn,
                    'message': result.message,
                    'error': result.error
                }

        except Exception as e:
            return {'error': str(e)}

    # ==================== Cross-Account Tools ====================

    @staticmethod
    def list_available_accounts(include_disabled: bool = False) -> Dict[str, Any]:
        """List available AWS accounts for cross-account operations."""
        try:
            from ..utils.account_iterator import account_iterator
            from ..services.dynamodb_state import dynamodb_state

            # Get current account
            current_identity = aws_auth.get_caller_identity()
            current_account = current_identity['Account']

            # Get enabled accounts from state service
            try:
                enabled_accounts = set(dynamodb_state.get_enabled_accounts())
            except Exception:
                enabled_accounts = set()

            # Try to get org accounts with names
            try:
                all_accounts = account_iterator.list_accounts(include_suspended=False)
                account_list = []
                for acc in all_accounts:
                    is_enabled = acc.account_id in enabled_accounts
                    if not include_disabled and not is_enabled and acc.account_id != current_account:
                        continue
                    account_list.append({
                        'account_id': acc.account_id,
                        'account_name': acc.account_name,
                        'is_current': acc.account_id == current_account,
                        'is_enabled': is_enabled or acc.account_id == current_account
                    })

                # Sort: current first, then enabled, then by name
                account_list.sort(key=lambda x: (
                    not x['is_current'],
                    not x['is_enabled'],
                    x['account_name']
                ))

                return {
                    'current_account_id': current_account,
                    'accounts': account_list,
                    'total_enabled': len(enabled_accounts) + 1,  # +1 for current
                    'total_in_org': len(all_accounts),
                    'cross_account_available': len(enabled_accounts) > 0
                }
            except Exception as e:
                # Fallback: just return current account
                return {
                    'current_account_id': current_account,
                    'accounts': [{
                        'account_id': current_account,
                        'account_name': 'Current Account',
                        'is_current': True,
                        'is_enabled': True
                    }],
                    'total_enabled': 1,
                    'cross_account_available': False,
                    'note': f"Could not list org accounts: {str(e)}. Only current account available."
                }

        except Exception as e:
            return {'error': str(e)}

    @classmethod
    def set_account_scope(cls, scope: str, account_ids: Optional[List[str]] = None) -> Dict[str, Any]:
        """Set session-wide account scope for queries."""
        try:
            from ..services.dynamodb_state import dynamodb_state

            if scope == "current":
                cls._account_scope = None
                cls._scope_mode = "current"
                current = aws_auth.get_caller_identity()['Account']
                return {
                    'scope': 'current',
                    'accounts': [current],
                    'message': f"Scope set to current account only ({current})"
                }

            elif scope == "all":
                try:
                    enabled = dynamodb_state.get_enabled_accounts()
                except Exception:
                    enabled = []

                if not enabled:
                    # Fallback to current account
                    cls._account_scope = None
                    cls._scope_mode = "current"
                    current = aws_auth.get_caller_identity()['Account']
                    return {
                        'scope': 'current',
                        'accounts': [current],
                        'warning': 'No accounts enabled for cross-account access. Using current account only.',
                        'suggestion': 'Run "account setup" to enable cross-account access.'
                    }

                # Add current account to the list if not already there
                current = aws_auth.get_caller_identity()['Account']
                if current not in enabled:
                    enabled = [current] + enabled

                cls._account_scope = enabled
                cls._scope_mode = "all_enabled"
                return {
                    'scope': 'all_enabled',
                    'accounts': enabled,
                    'count': len(enabled),
                    'message': f"Scope set to all {len(enabled)} enabled accounts"
                }

            elif scope == "specific":
                if not account_ids:
                    return {'error': 'account_ids required when scope is "specific"'}
                cls._account_scope = account_ids
                cls._scope_mode = "specific"
                return {
                    'scope': 'specific',
                    'accounts': account_ids,
                    'count': len(account_ids),
                    'message': f"Scope set to {len(account_ids)} specific account(s)"
                }

            return {'error': f'Invalid scope: {scope}. Use "current", "all", or "specific".'}

        except Exception as e:
            return {'error': str(e)}

    @classmethod
    def get_current_account_scope(cls) -> Dict[str, Any]:
        """Get current account scope setting."""
        try:
            current = aws_auth.get_caller_identity()['Account']

            if cls._scope_mode == "current" or cls._account_scope is None:
                return {
                    'scope': 'current',
                    'accounts': [current],
                    'count': 1,
                    'message': 'Queries will run against the current account only'
                }
            else:
                return {
                    'scope': cls._scope_mode,
                    'accounts': cls._account_scope,
                    'count': len(cls._account_scope),
                    'message': f'Queries will run against {len(cls._account_scope)} account(s)'
                }
        except Exception as e:
            return {'error': str(e)}

    @classmethod
    def get_effective_accounts(cls, override_account_ids: Optional[List[str]] = None) -> List[str]:
        """Get effective account list for a query.

        Args:
            override_account_ids: Optional override for this specific query

        Returns:
            List of account IDs to query
        """
        if override_account_ids:
            return override_account_ids
        if cls._scope_mode == "current" or cls._account_scope is None:
            return [aws_auth.get_caller_identity()['Account']]
        return cls._account_scope

    # =========================================================================
    # CLI Self-Awareness Tools
    # =========================================================================

    # Whitelist of safe commands (read-only operations)
    ALLOWED_CLI_COMMANDS = {
        'discover',
        'lifecycle scan',
        'cost summary', 'cost services', 'cost ec2', 'cost s3', 'cost rds', 'cost lambda',
        'cost daily', 'cost compare', 'cost forecast', 'cost accounts', 'cost regions',
        'cost resources', 'cost usage-types', 'cost gaps', 'cost anomalies',
        'cost setup detect', 'cost setup validate',
        'setup validate',
        '--version', '--help',
    }

    # CLI documentation content
    CLI_HELP_CONTENT = {
        'commands': """
# Tag Manager CLI Commands Overview

## Main Command Groups:
- `discover` - Discover AWS resources and their tags
- `lifecycle` - Scan and manage resource lifecycle tags
- `cost` - Cost analysis and FinOps (CUR-powered)
- `ask` - AI-powered assistant (you're using it now!)
- `policy` - AWS Organizations tag policies
- `setup` - Configuration, validation, and multi-account management
- `update` - Update to latest version

## Quick Start:
1. Configure AWS: `export AWS_PROFILE=your-profile`
2. Validate setup: `bluearch-aws-tags setup validate`
3. Discover resources: `bluearch-aws-tags discover all`
4. Scan lifecycle resources: `bluearch-aws-tags lifecycle scan`
""",
        'cost': """
# Cost Analysis Commands

## Prerequisites:
- CUR (Cost and Usage Report) configured in your AWS account
- Run `bluearch-aws-tags cost setup detect` to find existing CUR

## Commands:
- `cost summary` - Overall cost breakdown by charge type
- `cost services` - Cost by AWS service
- `cost ec2` - EC2 analysis (instance types, families)
- `cost s3` - S3 analysis (buckets, storage classes)
- `cost rds` - RDS analysis (engines, instance types)
- `cost lambda` - Lambda analysis (functions, memory tiers)
- `cost daily` - Daily cost trends
- `cost compare` - Period comparison (MoM, YoY)
- `cost forecast` - Cost projections
- `cost accounts` - Cost by AWS account
- `cost regions` - Cost by region
- `cost gaps` - Untagged resource costs
- `cost anomalies` - Detect cost anomalies

## Examples:
```
bluearch-aws-tags cost summary
bluearch-aws-tags cost ec2 instances
bluearch-aws-tags cost compare this-month last-month
```
""",
        'tags': """
# Lifecycle Tag Management Commands

## Commands:
- `lifecycle scan` - Find resources governed by lifecycle policies
- `lifecycle review` - Review expiring resources interactively
- `lifecycle set-ttl` - Apply TTL tags to selected resources

## Examples:
```
bluearch-aws-tags lifecycle scan
bluearch-aws-tags lifecycle review
bluearch-aws-tags lifecycle set-ttl
```

## Required Tags (typical):
- Environment (prod/dev/staging)
- CostCenter
- Owner
- Project
""",
        'discover': """
# Resource Discovery

## Command:
`bluearch-aws-tags discover all` - Scan AWS for resources and their tags

## What it finds:
- EC2 instances
- S3 buckets
- RDS databases
- Lambda functions
- VPCs and subnets
- IAM users

## Options:
- `--regions` - Specific regions to scan
- `--service` - Specific service to scan

## Example:
```
bluearch-aws-tags discover all
bluearch-aws-tags discover all --regions us-east-1,us-west-2
```
""",
        'accounts': """
# Cross-Account Management

## Setup:
`bluearch-aws-tags setup multi-account` - Deploy cross-account IAM roles

## How it works:
1. Deploys StackSet from management account
2. Creates TagManagerCrossAccountRole in each account
3. Uses secure ExternalId stored in Secrets Manager

## Commands:
- `setup multi-account` - Interactive deployment
- `setup multi-account --validate-only` - Validate prerequisites
- `setup multi-account --complete` - Deploy, test, and enable all accounts

## In Ask Chat:
Say "list my AWS accounts" or "show costs across all accounts"
""",
        'setup': """
# Configuration & Setup

## Commands:
- `setup validate` - Check AWS permissions and configuration
- `setup database` - Initialize/check database

## Validation checks:
- AWS credentials and connectivity
- Required IAM permissions
- Database schema
- CUR configuration

## Prerequisites:
1. AWS CLI configured with SSO or credentials
2. Required IAM permissions (see iam-policy.json)

## Example:
```
export AWS_PROFILE=your-sso-profile
aws sso login
bluearch-aws-tags setup validate
```
""",
        'troubleshooting': """
# Troubleshooting Guide

## Common Issues:

### "No CUR found"
- Run: `bluearch-aws-tags cost setup detect`
- Or create CUR: `bluearch-aws-tags cost setup create`

### "Permission denied" errors
- Run: `bluearch-aws-tags setup validate` to see missing permissions
- Check iam-policy.json for required permissions

### Cost commands return empty
- Ensure CUR is configured and has data (takes 24h for first data)
- Check region matches CUR location

### "Session expired" or SSO errors
- Re-authenticate: `aws sso login`
- Verify profile: `echo $AWS_PROFILE`

### Database errors
- Reinitialize: `bluearch-aws-tags setup database --force`
- Location: ~/.tag-manager/data/tag-manager.db

### Binary won't run (macOS)
- Allow in System Preferences > Security
- Or run: `xattr -d com.apple.quarantine /path/to/bluearch-aws-tags`

## Debug Mode:
```
export TAG_MANAGER_DEBUG=1
bluearch-aws-tags <command>
```
""",
        'ask': """
# AI Assistant (Ask Chat)

## Commands:
- `ask chat` - Interactive conversation mode
- `ask question "your question"` - Single question
- `ask models` - List available Bedrock models

## In Chat:
- `help` - Show example questions
- `stats` - View session usage
- `prompts` - Browse prompt library
- `1/2/3` - Run suggested prompts
- `suggestions on/off` - Toggle follow-ups
- `reset` - Clear conversation
- `exit` - End session

## Example Questions:
- "What are my top 5 most expensive services?"
- "Show me untagged EC2 instances"
- "Compare this month to last month"
- "Which Lambda functions cost the most?"
"""
    }

    @classmethod
    def run_tag_manager_command(cls, command: str, args: str = "") -> Dict[str, Any]:
        """Run a bluearch-aws-tags CLI command (safe commands only)."""
        # Normalize command
        full_command = f"{command} {args}".strip()
        try:
            command_argv = shlex.split(full_command)
        except ValueError as exc:
            return {
                'error': f"Invalid command arguments: {exc}",
                'message': 'Use normal CLI argv without shell syntax',
            }

        # Check if command is allowed
        allowed_prefixes = [tuple(shlex.split(allowed)) for allowed in cls.ALLOWED_CLI_COMMANDS]
        is_allowed = any(
            tuple(command_argv[:len(prefix)]) == prefix
            for prefix in allowed_prefixes
        )

        if not is_allowed:
            return {
                'error': f"Command not allowed: '{command}'",
                'message': 'Only read-only commands are permitted. Blocked commands include: tags apply, account setup, update',
                'allowed_commands': list(cls.ALLOWED_CLI_COMMANDS)
            }

        # Block dangerous flags
        if any(
            (part.startswith('-f') and not part.startswith('--'))
            or part == '--force'
            or part.startswith('--force=')
            for part in command_argv
        ):
            return {
                'error': 'The --force flag is not allowed for safety',
                'message': 'Remove --force and try again'
            }

        try:
            executable = _find_public_tags_executable()
            if executable is None:
                return {
                    'error': 'A safe bluearch-aws-tags executable was not found',
                    'command': f"bluearch-aws-tags {full_command}",
                }
            cmd_parts = [executable, *command_argv]

            # Execute with timeout
            result = subprocess.run(
                cmd_parts,
                capture_output=True,
                text=True,
                timeout=60,
            )

            output = result.stdout
            if result.stderr and not output:
                output = result.stderr

            # Truncate if too long
            if len(output) > 10000:
                output = output[:10000] + "\n\n[Output truncated - showing first 10KB]"

            return {
                'command': f"bluearch-aws-tags {full_command}",
                'exit_code': result.returncode,
                'output': output,
                'success': result.returncode == 0
            }

        except subprocess.TimeoutExpired:
            return {
                'error': 'Command timed out after 60 seconds',
                'command': f"bluearch-aws-tags {full_command}"
            }
        except Exception as e:
            return {
                'error': f'Failed to execute command: {str(e)}',
                'command': f"bluearch-aws-tags {full_command}"
            }

    @classmethod
    def get_cli_help(cls, topic: str = "commands") -> Dict[str, Any]:
        """Get CLI help and documentation."""
        topic = (topic or "commands").lower().strip()

        if topic in cls.CLI_HELP_CONTENT:
            return {
                'topic': topic,
                'content': cls.CLI_HELP_CONTENT[topic],
                'available_topics': list(cls.CLI_HELP_CONTENT.keys())
            }
        else:
            # Return overview if topic not found
            return {
                'topic': 'commands',
                'content': cls.CLI_HELP_CONTENT['commands'],
                'available_topics': list(cls.CLI_HELP_CONTENT.keys()),
                'note': f"Topic '{topic}' not found, showing commands overview"
            }


def execute_tool(tool_name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
    """Execute a tool by name with given arguments."""
    from .aws_cli_tool import AWSCLITool

    tools = AWSTools()

    tool_map = {
        'list_ec2_instances': tools.list_ec2_instances,
        'describe_s3_buckets': tools.describe_s3_buckets,
        'list_lambda_functions': tools.list_lambda_functions,
        'query_cur_costs': tools.query_cur_costs,
        'get_cost_analysis': tools.get_cost_analysis,
        'find_untagged_resources': tools.find_untagged_resources,
        'list_iam_users': tools.list_iam_users,
        'describe_rds_instances': tools.describe_rds_instances,
        'list_vpc_resources': tools.list_vpc_resources,
        'get_account_summary': tools.get_account_summary,
        'get_tag_compliance_summary': tools.get_tag_compliance_summary,
        'get_tag_compliance_by_service': tools.get_tag_compliance_by_service,
        'get_high_risk_untagged_resources': tools.get_high_risk_untagged_resources,
        'execute_aws_cli': lambda **args: AWSCLITool.execute_cli_command(**args),
        'suggest_cloudwatch_alarms': tools.suggest_cloudwatch_alarms,
        'list_managed_alarms': tools.list_managed_alarms,
        'get_alarm_templates': tools.get_alarm_templates,
        'create_cloudwatch_alarm': tools.create_cloudwatch_alarm,
        # Cross-account tools
        'list_available_accounts': tools.list_available_accounts,
        'set_account_scope': AWSTools.set_account_scope,
        'get_current_account_scope': AWSTools.get_current_account_scope,
        # CLI Self-Awareness tools
        'run_tag_manager_command': tools.run_tag_manager_command,
        'get_cli_help': tools.get_cli_help,
    }

    if tool_name not in tool_map:
        return {'error': f"Unknown tool: {tool_name}"}

    try:
        return tool_map[tool_name](**arguments)
    except Exception as e:
        return {'error': f"Tool execution failed: {str(e)}"}
