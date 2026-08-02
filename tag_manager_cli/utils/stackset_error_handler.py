"""
Enhanced error handling for CloudFormation StackSet operations.

This module provides comprehensive error detection and user-friendly messages
for common StackSet deployment failures.
"""

from typing import Dict, Optional, Tuple
from botocore.exceptions import ClientError
from rich.console import Console
from rich.panel import Panel

console = Console()


class StackSetErrorHandler:
    """Handle and diagnose StackSet deployment errors"""

    # Common error codes and their explanations
    ERROR_PATTERNS = {
        'AccessDeniedException': {
            'pattern': 'is not authorized to perform',
            'category': 'permissions',
            'solutions': [
                'Ensure you have CloudFormation StackSets permissions',
                'Check if StackSets is enabled for your organization',
                'Verify IAM permissions include cloudformation:*'
            ]
        },
        'InvalidOperationException': {
            'pattern': 'Account is not a delegated administrator',
            'category': 'delegated_admin',
            'solutions': [
                'Register as delegated admin: aws organizations register-delegated-administrator --account-id YOUR_ACCOUNT --service-principal member.org.stacksets.cloudformation.amazonaws.com',
                'Or run from the Organizations management account',
                'Check with: aws organizations list-delegated-administrators --service-principal member.org.stacksets.cloudformation.amazonaws.com'
            ]
        },
        'ValidationError': {
            'pattern': 'StackSets operations are not enabled',
            'category': 'stacksets_not_enabled',
            'solutions': [
                'Enable trusted access: aws organizations enable-aws-service-access --service-principal member.org.stacksets.cloudformation.amazonaws.com',
                'Then activate Organizations access: aws cloudformation activate-organizations-access',
                'Verify with: aws organizations list-aws-service-access-for-organization'
            ]
        },
        'OrganizationNotInAllFeaturesMode': {
            'pattern': 'Organization is not in all features mode',
            'category': 'org_features',
            'solutions': [
                'Enable all features in Organizations: aws organizations enable-all-features',
                'This requires approval from all member accounts',
                'Check status: aws organizations describe-organization'
            ]
        },
        'AccountNotRegistered': {
            'pattern': 'Account is not registered with AWS Organizations',
            'category': 'not_in_org',
            'solutions': [
                'This account must be part of an AWS Organization',
                'Create an organization or accept an invitation to join one',
                'Check: aws organizations describe-organization'
            ]
        },
        'OperationInProgressException': {
            'pattern': 'Another operation is already in progress',
            'category': 'concurrent_operation',
            'solutions': [
                'Wait for the current operation to complete',
                'Check status: aws cloudformation list-stack-set-operations --stack-set-name STACKSET_NAME',
                'Stop if needed: aws cloudformation stop-stack-set-operation --operation-id OPERATION_ID'
            ]
        },
        'StackSetNotFoundException': {
            'pattern': 'Stack set .* does not exist',
            'category': 'not_found',
            'solutions': [
                'The StackSet does not exist yet',
                'Run: bluearch-aws-tags setup multi-account',
                'Or check the StackSet name is correct'
            ]
        },
        'InsufficientCapabilitiesException': {
            'pattern': 'Requires capabilities',
            'category': 'capabilities',
            'solutions': [
                'The template requires additional capabilities',
                'Add CAPABILITY_IAM and CAPABILITY_NAMED_IAM',
                'This is a bug - please report it'
            ]
        }
    }

    @classmethod
    def analyze_error(cls, error: ClientError) -> Tuple[str, str, list]:
        """
        Analyze a ClientError and return category, message, and solutions.

        Returns:
            Tuple of (category, error_message, solutions_list)
        """
        error_code = error.response.get('Error', {}).get('Code', 'Unknown')
        error_message = error.response.get('Error', {}).get('Message', str(error))

        # Check for known patterns
        for code, details in cls.ERROR_PATTERNS.items():
            if code in error_code or details['pattern'] in error_message:
                return details['category'], error_message, details['solutions']

        # Check for specific error messages
        if 'not the management account' in error_message.lower():
            return 'wrong_account', error_message, [
                f'You must run this from the management account',
                f'Current account may be a member account',
                f'Switch to management account and retry'
            ]

        if 'trusted access is not enabled' in error_message.lower():
            return 'trusted_access', error_message, [
                'Enable trusted access for CloudFormation StackSets',
                'Run: aws organizations enable-aws-service-access --service-principal member.org.stacksets.cloudformation.amazonaws.com',
                'Then activate: aws cloudformation activate-organizations-access'
            ]

        if 'permission' in error_message.lower() or 'denied' in error_message.lower():
            return 'permissions', error_message, [
                'Check IAM permissions for CloudFormation and Organizations',
                'Ensure you have administrator access or required policies',
                'Verify: aws sts get-caller-identity'
            ]

        # Default case
        return 'unknown', error_message, [
            'Check AWS CloudFormation documentation',
            'Verify your AWS credentials and permissions',
            'Try running from the Organizations management account'
        ]

    @classmethod
    def display_error(cls, error: ClientError, operation: str = "StackSet operation"):
        """Display a user-friendly error message with solutions"""
        category, message, solutions = cls.analyze_error(error)

        # Determine error title based on category
        titles = {
            'permissions': '🔒 Permission Denied',
            'delegated_admin': '👤 Not a Delegated Administrator',
            'stacksets_not_enabled': '⚙️ StackSets Not Enabled',
            'org_features': '🏢 Organization Configuration Issue',
            'not_in_org': '🔗 Not in an AWS Organization',
            'concurrent_operation': '⏳ Operation in Progress',
            'not_found': '❌ StackSet Not Found',
            'capabilities': '🔧 Missing Capabilities',
            'wrong_account': '🏦 Wrong Account',
            'trusted_access': '🤝 Trusted Access Not Enabled',
            'unknown': '❓ Unexpected Error'
        }

        title = titles.get(category, '❌ Error')

        # Create error panel
        error_content = f"[bold red]{title}[/bold red]\n\n"
        error_content += f"[yellow]Operation:[/yellow] {operation}\n"
        error_content += f"[yellow]Error:[/yellow] {message[:200]}{'...' if len(message) > 200 else ''}\n\n"
        error_content += "[bold cyan]Solutions:[/bold cyan]\n"

        for i, solution in enumerate(solutions, 1):
            error_content += f"  {i}. {solution}\n"

        panel = Panel(
            error_content,
            title="[bold red]StackSet Deployment Failed[/bold red]",
            border_style="red",
            padding=(1, 2)
        )
        console.print(panel)

    @classmethod
    def check_prerequisites(cls) -> Tuple[bool, Optional[str]]:
        """
        Check common prerequisites before attempting StackSet operations.

        Returns:
            Tuple of (success, error_message)
        """
        from ..utils.aws_auth import aws_auth

        try:
            # Check Organizations access
            org_client = aws_auth.get_client('organizations')
            org_info = org_client.describe_organization()

            # Check if all features enabled
            if org_info['Organization']['FeatureSet'] != 'ALL':
                return False, "Organization must have 'all features' enabled"

            # Check trusted access for CloudFormation StackSets
            # Note: The service principal is 'member.org.stacksets.cloudformation.amazonaws.com'
            trusted_services = org_client.list_aws_service_access_for_organization()
            cf_enabled = any(
                service['ServicePrincipal'] == 'member.org.stacksets.cloudformation.amazonaws.com'
                for service in trusted_services.get('EnabledServicePrincipals', [])
            )

            if not cf_enabled:
                return False, "CloudFormation StackSets trusted access not enabled"

            # Check if we're management account or delegated admin
            sts_client = aws_auth.get_client('sts')
            current_account = sts_client.get_caller_identity()['Account']
            mgmt_account = org_info['Organization']['MasterAccountId']

            if current_account != mgmt_account:
                # Check if delegated admin for CloudFormation StackSets
                delegated_admins = org_client.list_delegated_administrators(
                    ServicePrincipal='member.org.stacksets.cloudformation.amazonaws.com'
                )
                is_delegated = any(
                    admin['AccountId'] == current_account
                    for admin in delegated_admins.get('DelegatedAdministrators', [])
                )

                if not is_delegated:
                    return False, f"Account {current_account} is neither management account nor delegated admin"

            return True, None

        except ClientError as e:
            error_code = e.response.get('Error', {}).get('Code', '')
            if error_code == 'AWSOrganizationsNotInUseException':
                return False, "This account is not part of an AWS Organization"
            elif error_code == 'AccessDeniedException':
                return False, "Insufficient permissions to check Organizations settings"
            else:
                return False, f"Failed to check prerequisites: {str(e)}"

        except Exception as e:
            return False, f"Unexpected error checking prerequisites: {str(e)}"


# Convenience function for displaying errors
def handle_stackset_error(error: Exception, operation: str = "StackSet operation"):
    """Handle and display StackSet errors in a user-friendly way"""
    if isinstance(error, ClientError):
        StackSetErrorHandler.display_error(error, operation)
    else:
        console.print(f"[red]Error during {operation}: {str(error)}[/red]")
