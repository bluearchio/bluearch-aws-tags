"""AWS CLI tool wrapper for expanded functionality with security validation."""

import subprocess
import json
import re
from typing import Dict, Any, List, Optional
import shlex


class AWSCLITool:
    """
    Wrapper for AWS CLI commands with security validation.

    This provides a safe, validated interface for executing AWS CLI commands
    with read-only operation filtering and service-level security checks.
    """

    # Commands that are always denied for security
    DENIED_COMMANDS = {
        'deploy',  # install, uninstall operations
        'emr',     # ssh, sock, get, put operations
    }

    # Read-only operations that are safe to execute
    READ_ONLY_OPERATIONS = {
        'describe', 'get', 'list', 'show', 'view', 'explain',
        'describe-', 'get-', 'list-', 'show-', 'view-',
    }

    @staticmethod
    def is_read_only_command(command: str) -> bool:
        """Check if a command is read-only (safe to execute)."""
        parts = command.lower().split()
        if len(parts) < 2:
            return False

        # Parse command structure: 'aws service operation ...' or 'service operation ...'
        if parts[0] == 'aws':
            # Command starts with 'aws': aws cloudformation list-stacks
            if len(parts) < 3:
                return False
            service = parts[1]
            operation = parts[2]
        else:
            # Command without 'aws' prefix: cloudformation list-stacks
            if len(parts) < 2:
                return False
            service = parts[0]
            operation = parts[1]

        # Denied services
        if service in AWSCLITool.DENIED_COMMANDS:
            return False

        # Check if operation starts with read-only prefix
        for prefix in AWSCLITool.READ_ONLY_OPERATIONS:
            if operation.startswith(prefix):
                return True

        return False

    @staticmethod
    def execute_cli_command(command: str = None, query: str = None, region: str = 'us-east-1', **kwargs) -> Dict[str, Any]:
        """
        Execute an AWS CLI command safely.

        Expects exact AWS CLI command syntax (not natural language).

        Args:
            command: AWS CLI command to execute (e.g., "cloudformation list-stacks")
            query: Backward compatibility alias for 'command'
            region: AWS region to execute in
            **kwargs: Additional parameters (ignored, for compatibility)

        Returns:
            Dict with result or error
        """
        # Support both 'command' and 'query' parameters for backward compatibility
        cli_command = command or query
        if not cli_command:
            return {
                'error': 'No command provided',
                'message': 'Please provide an AWS CLI command',
                'example': 'cloudformation list-stacks'
            }

        # Normalize command - add 'aws' prefix if missing
        if not cli_command.strip().startswith('aws '):
            cli_command = f'aws {cli_command}'

        # Security validation
        if not AWSCLITool.is_read_only_command(cli_command):
            return {
                'error': 'Command not allowed',
                'message': f'Only read-only operations are permitted. Command: {cli_command}',
                'allowed_prefixes': list(AWSCLITool.READ_ONLY_OPERATIONS)
            }

        # Check for denied services
        for denied in AWSCLITool.DENIED_COMMANDS:
            if denied in cli_command.lower():
                return {
                    'error': 'Service denied',
                    'message': f'Service {denied} is not allowed for security reasons',
                    'command': cli_command
                }

        # Add region if not specified
        if '--region' not in cli_command and '-r' not in cli_command:
            cli_command = f'{cli_command} --region {region}'

        # Add JSON output if not specified
        if '--output' not in cli_command:
            cli_command = f'{cli_command} --output json'

        # Show command preview for transparency
        from rich.console import Console
        console = Console()
        console.print(f"[dim]→ Executing: {cli_command}[/dim]")

        try:
            # Execute command safely using shlex for proper argument parsing
            cmd_parts = shlex.split(cli_command)

            result = subprocess.run(
                cmd_parts,
                capture_output=True,
                text=True,
                timeout=60,  # 60 second timeout
                check=False
            )

            if result.returncode == 0:
                # Try to parse JSON output
                try:
                    output = json.loads(result.stdout) if result.stdout.strip() else {}
                    return {
                        'success': True,
                        'output': output,
                        'command': cli_command
                    }
                except json.JSONDecodeError:
                    # Return raw output if not JSON
                    return {
                        'success': True,
                        'output': result.stdout,
                        'command': cli_command,
                        'format': 'text'
                    }
            else:
                return {
                    'error': 'Command failed',
                    'message': result.stderr,
                    'command': cli_command,
                    'exit_code': result.returncode
                }

        except subprocess.TimeoutExpired:
            return {
                'error': 'Timeout',
                'message': 'Command execution exceeded 60 second timeout',
                'command': cli_command
            }

        except Exception as e:
            return {
                'error': 'Execution error',
                'message': str(e),
                'command': cli_command
            }

    @staticmethod
    def translate_natural_language(query: str, region: str = 'us-east-1') -> Optional[str]:
        """
        Translate natural language query to AWS CLI command.

        This helps the AI by providing common translation patterns.

        Args:
            query: Natural language query
            region: AWS region

        Returns:
            Suggested AWS CLI command or None
        """
        query_lower = query.lower().strip()

        # CloudFormation patterns
        if re.search(r'(list|show|get).*(stack|cloudformation|cfn)', query_lower):
            if 'drift' in query_lower:
                # Note: Drift detection is complex and requires multiple API calls
                # First list stacks, then check drift for each
                return 'cloudformation list-stacks'
            if 'failed' in query_lower or 'error' in query_lower:
                return 'cloudformation list-stacks --stack-status-filter CREATE_FAILED UPDATE_FAILED ROLLBACK_FAILED'
            return 'cloudformation list-stacks'

        if re.search(r'drift', query_lower) and re.search(r'stack', query_lower):
            # Drift detection - return stacks and mention drift requires separate detection
            return 'cloudformation list-stacks'

        if re.search(r'describe.*(stack)', query_lower):
            # Extract stack name if present
            match = re.search(r'stack\s+(?:named\s+)?["\']?([a-zA-Z0-9-]+)["\']?', query_lower)
            if match:
                stack_name = match.group(1)
                return f'cloudformation describe-stacks --stack-name {stack_name}'
            return 'cloudformation describe-stacks'

        # CloudWatch Logs patterns
        if re.search(r'(list|show|get).*(log\s+group|cloudwatch.*log)', query_lower):
            # Extract prefix if present
            match = re.search(r'(?:prefix|starting\s+with|named)\s+["\']?([a-zA-Z0-9/_-]+)["\']?', query_lower)
            if match:
                prefix = match.group(1)
                return f'logs describe-log-groups --log-group-name-prefix {prefix}'
            return 'logs describe-log-groups'

        if re.search(r'(list|show|get).*(log\s+stream)', query_lower):
            # Extract log group name
            match = re.search(r'(?:for|in|from)\s+["\']?([a-zA-Z0-9/_-]+)["\']?', query_lower)
            if match:
                log_group = match.group(1)
                return f'logs describe-log-streams --log-group-name {log_group}'
            return None  # Needs log group name

        # ECS patterns
        if re.search(r'(list|show|get).*(ecs\s+cluster|container.*cluster)', query_lower):
            return 'ecs list-clusters'

        if re.search(r'(list|show|get).*(ecs\s+service|container.*service)', query_lower):
            match = re.search(r'(?:in|from)\s+cluster\s+["\']?([a-zA-Z0-9-]+)["\']?', query_lower)
            if match:
                cluster = match.group(1)
                return f'ecs list-services --cluster {cluster}'
            return 'ecs list-services'

        if re.search(r'(list|show|get).*(ecs\s+task|container.*task)', query_lower):
            match = re.search(r'(?:in|from)\s+cluster\s+["\']?([a-zA-Z0-9-]+)["\']?', query_lower)
            if match:
                cluster = match.group(1)
                return f'ecs list-tasks --cluster {cluster}'
            return 'ecs list-tasks'

        # EKS patterns
        if re.search(r'(list|show|get).*(eks\s+cluster|kubernetes.*cluster)', query_lower):
            return 'eks list-clusters'

        if re.search(r'describe.*(eks\s+cluster|kubernetes.*cluster)', query_lower):
            match = re.search(r'cluster\s+(?:named\s+)?["\']?([a-zA-Z0-9-]+)["\']?', query_lower)
            if match:
                cluster = match.group(1)
                return f'eks describe-cluster --name {cluster}'
            return None  # Needs cluster name

        # SNS patterns
        if re.search(r'(list|show|get).*(sns\s+topic|notification.*topic)', query_lower):
            return 'sns list-topics'

        if re.search(r'(list|show|get).*(sns\s+subscription)', query_lower):
            match = re.search(r'(?:for|to)\s+topic\s+["\']?([a-zA-Z0-9:_-]+)["\']?', query_lower)
            if match:
                topic_arn = match.group(1)
                return f'sns list-subscriptions-by-topic --topic-arn {topic_arn}'
            return 'sns list-subscriptions'

        # SQS patterns
        if re.search(r'(list|show|get).*(sqs\s+queue|message.*queue)', query_lower):
            match = re.search(r'(?:prefix|starting\s+with|named)\s+["\']?([a-zA-Z0-9-]+)["\']?', query_lower)
            if match:
                prefix = match.group(1)
                return f'sqs list-queues --queue-name-prefix {prefix}'
            return 'sqs list-queues'

        if re.search(r'get.*queue.*attribute', query_lower):
            match = re.search(r'queue\s+["\']?([a-zA-Z0-9-]+)["\']?', query_lower)
            if match:
                queue_name = match.group(1)
                return f'sqs get-queue-attributes --queue-url https://sqs.{region}.amazonaws.com/ACCOUNT/{queue_name} --attribute-names All'
            return None  # Needs queue name

        # DynamoDB patterns
        if re.search(r'(list|show|get).*(dynamo.*table)', query_lower):
            return 'dynamodb list-tables'

        if re.search(r'describe.*(dynamo.*table)', query_lower):
            match = re.search(r'table\s+(?:named\s+)?["\']?([a-zA-Z0-9-_]+)["\']?', query_lower)
            if match:
                table = match.group(1)
                return f'dynamodb describe-table --table-name {table}'
            return None  # Needs table name

        # Secrets Manager patterns
        if re.search(r'(list|show|get).*(secret)', query_lower):
            return 'secretsmanager list-secrets'

        if re.search(r'(get|retrieve|show).*(secret\s+value)', query_lower):
            match = re.search(r'(?:named|called|for)\s+["\']?([a-zA-Z0-9/_-]+)["\']?', query_lower)
            if match:
                secret_name = match.group(1)
                return f'secretsmanager get-secret-value --secret-id {secret_name}'
            return None  # Needs secret name

        # Systems Manager Parameter Store patterns
        if re.search(r'(list|show|get).*(parameter|ssm)', query_lower):
            return 'ssm describe-parameters'

        if re.search(r'(get|retrieve).*(parameter\s+value)', query_lower):
            match = re.search(r'(?:named|called)\s+["\']?([a-zA-Z0-9/_-]+)["\']?', query_lower)
            if match:
                param_name = match.group(1)
                return f'ssm get-parameter --name {param_name}'
            return None  # Needs parameter name

        # API Gateway patterns
        if re.search(r'(list|show|get).*(api\s+gateway|rest\s+api)', query_lower):
            return 'apigateway get-rest-apis'

        # EventBridge patterns
        if re.search(r'(list|show|get).*(event.*rule|eventbridge)', query_lower):
            return 'events list-rules'

        # Step Functions patterns
        if re.search(r'(list|show|get).*(state\s+machine|step\s+function)', query_lower):
            return 'stepfunctions list-state-machines'

        # Glue patterns
        if re.search(r'(list|show|get).*(glue\s+job|etl\s+job)', query_lower):
            return 'glue get-jobs'

        if re.search(r'(list|show|get).*(glue.*crawler)', query_lower):
            return 'glue get-crawlers'

        # Athena patterns
        if re.search(r'(list|show|get).*(athena\s+database|data\s+catalog)', query_lower):
            return 'athena list-databases --catalog-name AwsDataCatalog'

        # Backup patterns
        if re.search(r'(list|show|get).*(backup\s+plan)', query_lower):
            return 'backup list-backup-plans'

        if re.search(r'(list|show|get).*(backup\s+vault)', query_lower):
            return 'backup list-backup-vaults'

        # ECR patterns
        if re.search(r'(list|show|get).*(ecr\s+repo|container\s+repo)', query_lower):
            return 'ecr describe-repositories'

        # KMS patterns
        if re.search(r'(list|show|get).*(kms\s+key|encryption\s+key)', query_lower):
            return 'kms list-keys'

        # ACM patterns
        if re.search(r'(list|show|get).*(certificate|acm)', query_lower):
            return 'acm list-certificates'

        # Route53 patterns
        if re.search(r'(list|show|get).*(hosted\s+zone|dns\s+zone)', query_lower):
            return 'route53 list-hosted-zones'

        # ElastiCache patterns
        if re.search(r'(list|show|get).*(elasticache|redis|memcached)', query_lower):
            if 'redis' in query_lower:
                return 'elasticache describe-cache-clusters --cache-cluster-id'
            return 'elasticache describe-cache-clusters'

        # No pattern matched
        return None

    @staticmethod
    def suggest_commands(query: str) -> List[Dict[str, Any]]:
        """
        Suggest AWS CLI commands based on a natural language query.

        This provides natural language to AWS CLI command translation.

        Args:
            query: Natural language description of what to do

        Returns:
            List of suggested commands with descriptions
        """
        # Common query patterns mapped to AWS CLI commands
        suggestions = []
        query_lower = query.lower()

        # CloudWatch Logs
        if any(word in query_lower for word in ['log', 'cloudwatch', 'logs']):
            suggestions.append({
                'command': 'logs describe-log-groups',
                'description': 'List CloudWatch log groups',
                'parameters': ['--log-group-name-prefix', '--limit']
            })
            suggestions.append({
                'command': 'logs describe-log-streams',
                'description': 'List log streams in a log group',
                'parameters': ['--log-group-name', '--limit']
            })

        # CloudFormation
        if any(word in query_lower for word in ['stack', 'cloudformation', 'cfn']):
            suggestions.append({
                'command': 'cloudformation list-stacks',
                'description': 'List CloudFormation stacks',
                'parameters': ['--stack-status-filter']
            })
            suggestions.append({
                'command': 'cloudformation describe-stacks',
                'description': 'Describe CloudFormation stack details',
                'parameters': ['--stack-name']
            })

        # ECS/EKS
        if 'ecs' in query_lower or 'container' in query_lower:
            suggestions.append({
                'command': 'ecs list-clusters',
                'description': 'List ECS clusters',
                'parameters': []
            })
            suggestions.append({
                'command': 'ecs list-services',
                'description': 'List ECS services in a cluster',
                'parameters': ['--cluster']
            })

        if 'eks' in query_lower or 'kubernetes' in query_lower:
            suggestions.append({
                'command': 'eks list-clusters',
                'description': 'List EKS clusters',
                'parameters': []
            })
            suggestions.append({
                'command': 'eks describe-cluster',
                'description': 'Describe EKS cluster details',
                'parameters': ['--name']
            })

        # SNS/SQS
        if 'sns' in query_lower or 'topic' in query_lower or 'notification' in query_lower:
            suggestions.append({
                'command': 'sns list-topics',
                'description': 'List SNS topics',
                'parameters': []
            })

        if 'sqs' in query_lower or 'queue' in query_lower:
            suggestions.append({
                'command': 'sqs list-queues',
                'description': 'List SQS queues',
                'parameters': ['--queue-name-prefix']
            })

        # DynamoDB
        if 'dynamo' in query_lower or 'table' in query_lower:
            suggestions.append({
                'command': 'dynamodb list-tables',
                'description': 'List DynamoDB tables',
                'parameters': []
            })

        # Secrets Manager
        if 'secret' in query_lower:
            suggestions.append({
                'command': 'secretsmanager list-secrets',
                'description': 'List secrets in Secrets Manager',
                'parameters': []
            })

        # Systems Manager Parameter Store
        if 'parameter' in query_lower or 'ssm' in query_lower:
            suggestions.append({
                'command': 'ssm describe-parameters',
                'description': 'List SSM parameters',
                'parameters': ['--filters']
            })

        return suggestions[:5]  # Return top 5 suggestions
