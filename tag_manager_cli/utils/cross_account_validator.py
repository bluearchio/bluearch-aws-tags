"""
Cross-Account Prerequisites Validator

This module validates all prerequisites for cross-account operations including:
- AWS Organizations access and role (management or delegated admin)
- CloudFormation StackSets configuration
- Required IAM permissions
- Account status validation
"""

import logging
from typing import Dict, List, Tuple, Optional
from dataclasses import dataclass
from enum import Enum

import boto3
from botocore.exceptions import ClientError
from rich.console import Console
from rich.table import Table
from rich.progress import Progress, SpinnerColumn, TextColumn

from ..utils.aws_auth import aws_auth
from ..utils.error_handlers import handle_aws_errors

logger = logging.getLogger(__name__)
console = Console()


class ValidationStatus(Enum):
    """Status of validation checks"""
    PASSED = "passed"
    FAILED = "failed"
    WARNING = "warning"
    SKIPPED = "skipped"


@dataclass
class ValidationResult:
    """Result of a validation check"""
    check_name: str
    status: ValidationStatus
    message: str
    solution: Optional[str] = None
    details: Optional[Dict] = None


class CrossAccountValidator:
    """Validates prerequisites for cross-account operations"""

    def __init__(self):
        self.validation_results: List[ValidationResult] = []
        self.is_management_account = False
        self.is_delegated_admin = False
        self.organization_id = None
        self.account_id = None

    def validate_all(self, verbose: bool = False) -> bool:
        """
        Run all validation checks

        Args:
            verbose: Show detailed output

        Returns:
            True if all critical checks pass, False otherwise
        """
        console.print("\n[bold]Running Cross-Account Prerequisites Check...[/bold]\n")

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=console,
            transient=not verbose
        ) as progress:

            # Run validation checks
            checks = [
                ("Checking AWS credentials...", self._check_aws_credentials),
                ("Checking Organizations access...", self._check_organizations_access),
                ("Checking account role...", self._check_account_role),
                ("Checking StackSets configuration...", self._check_stacksets_config),
                ("Checking required permissions...", self._check_permissions),
                ("Checking organization structure...", self._check_organization_structure),
            ]

            for description, check_func in checks:
                task = progress.add_task(description, total=None)
                try:
                    check_func()
                except Exception as e:
                    self.validation_results.append(
                        ValidationResult(
                            check_name=description.replace("Checking ", "").replace("...", ""),
                            status=ValidationStatus.FAILED,
                            message=f"Check failed with error: {str(e)}",
                            solution="Check AWS credentials and permissions"
                        )
                    )
                progress.remove_task(task)

        # Display results
        self._display_results(verbose)

        # Return True if all critical checks passed
        critical_passed = all(
            r.status != ValidationStatus.FAILED
            for r in self.validation_results
            if r.check_name not in ["organization structure"]  # Non-critical checks
        )

        return critical_passed

    def _check_aws_credentials(self):
        """Check AWS credentials are configured"""
        try:
            sts_client = aws_auth.get_client('sts')
            identity = sts_client.get_caller_identity()
            self.account_id = identity['Account']

            self.validation_results.append(
                ValidationResult(
                    check_name="AWS credentials",
                    status=ValidationStatus.PASSED,
                    message=f"Authenticated as account {self.account_id}",
                    details={"account_id": self.account_id, "arn": identity['Arn']}
                )
            )
        except ClientError as e:
            self.validation_results.append(
                ValidationResult(
                    check_name="AWS credentials",
                    status=ValidationStatus.FAILED,
                    message="AWS credentials not configured or expired",
                    solution="Run 'aws sso login' or configure AWS credentials"
                )
            )

    def _check_organizations_access(self):
        """Check AWS Organizations access"""
        try:
            org_client = aws_auth.get_client('organizations')
            org_info = org_client.describe_organization()
            self.organization_id = org_info['Organization']['Id']

            self.validation_results.append(
                ValidationResult(
                    check_name="Organizations access",
                    status=ValidationStatus.PASSED,
                    message=f"Organization {self.organization_id} accessible",
                    details={"org_id": self.organization_id}
                )
            )
        except ClientError as e:
            if e.response['Error']['Code'] == 'AWSOrganizationsNotInUseException':
                self.validation_results.append(
                    ValidationResult(
                        check_name="Organizations access",
                        status=ValidationStatus.FAILED,
                        message="AWS Organizations not enabled for this account",
                        solution="Enable AWS Organizations or run from an organization account"
                    )
                )
            elif e.response['Error']['Code'] == 'AccessDeniedException':
                self.validation_results.append(
                    ValidationResult(
                        check_name="Organizations access",
                        status=ValidationStatus.FAILED,
                        message="Access denied to AWS Organizations",
                        solution="Ensure you have organizations:DescribeOrganization permission"
                    )
                )
            else:
                raise

    def _check_account_role(self):
        """Check if account is management or delegated admin"""
        if not self.organization_id:
            self.validation_results.append(
                ValidationResult(
                    check_name="account role",
                    status=ValidationStatus.SKIPPED,
                    message="Skipped - Organizations not accessible"
                )
            )
            return

        try:
            org_client = aws_auth.get_client('organizations')

            # Check if management account
            org_info = org_client.describe_organization()
            if org_info['Organization']['MasterAccountId'] == self.account_id:
                self.is_management_account = True
                self.validation_results.append(
                    ValidationResult(
                        check_name="account role",
                        status=ValidationStatus.PASSED,
                        message="Running from Organizations management account",
                        details={"role": "management_account"}
                    )
                )
                return

            # Check if delegated admin for CloudFormation StackSets
            try:
                delegated_admins = org_client.list_delegated_administrators(
                    ServicePrincipal='member.org.stacksets.cloudformation.amazonaws.com'
                )

                if any(admin['AccountId'] == self.account_id for admin in delegated_admins['DelegatedAdministrators']):
                    self.is_delegated_admin = True
                    self.validation_results.append(
                        ValidationResult(
                            check_name="account role",
                            status=ValidationStatus.PASSED,
                            message="Account is delegated administrator for CloudFormation StackSets",
                            details={"role": "delegated_admin"}
                        )
                    )
                else:
                    self.validation_results.append(
                        ValidationResult(
                            check_name="account role",
                            status=ValidationStatus.FAILED,
                            message="Account is neither management account nor delegated admin",
                            solution="Run from management account or register as delegated admin for StackSets"
                        )
                    )
            except ClientError as e:
                if e.response['Error']['Code'] == 'AccessDeniedException':
                    # Might be running from member account
                    self.validation_results.append(
                        ValidationResult(
                            check_name="account role",
                            status=ValidationStatus.WARNING,
                            message="Cannot verify delegated admin status - may need additional permissions",
                            solution="Ensure organizations:ListDelegatedAdministrators permission"
                        )
                    )
                else:
                    raise

        except ClientError as e:
            self.validation_results.append(
                ValidationResult(
                    check_name="account role",
                    status=ValidationStatus.FAILED,
                    message=f"Failed to check account role: {str(e)}",
                    solution="Check Organizations permissions"
                )
            )

    def _check_stacksets_config(self):
        """Check CloudFormation StackSets configuration and trusted access"""
        if not (self.is_management_account or self.is_delegated_admin):
            self.validation_results.append(
                ValidationResult(
                    check_name="StackSets configuration",
                    status=ValidationStatus.SKIPPED,
                    message="Skipped - not management account or delegated admin"
                )
            )
            return

        try:
            cf_client = aws_auth.get_client('cloudformation')
            org_client = aws_auth.get_client('organizations')

            # Check if StackSets API is accessible (try to list stack sets)
            response = cf_client.list_stack_sets(Status='ACTIVE', MaxResults=1)

            # Check if trusted access is enabled for CloudFormation StackSets
            # Note: The service principal is 'member.org.stacksets.cloudformation.amazonaws.com'
            trusted_services = org_client.list_aws_service_access_for_organization()
            cf_enabled = any(
                service['ServicePrincipal'] == 'member.org.stacksets.cloudformation.amazonaws.com'
                for service in trusted_services.get('EnabledServicePrincipals', [])
            )

            if not cf_enabled:
                self.validation_results.append(
                    ValidationResult(
                        check_name="StackSets configuration",
                        status=ValidationStatus.FAILED,
                        message="CloudFormation StackSets trusted access not enabled",
                        solution="Enable trusted access using: aws organizations enable-aws-service-access --service-principal member.org.stacksets.cloudformation.amazonaws.com"
                    )
                )
                return

            self.validation_results.append(
                ValidationResult(
                    check_name="StackSets configuration",
                    status=ValidationStatus.PASSED,
                    message="CloudFormation StackSets is enabled with trusted access",
                    details={"existing_stacksets": len(response.get('Summaries', []))}
                )
            )

        except ClientError as e:
            if e.response['Error']['Code'] == 'AccessDeniedException':
                self.validation_results.append(
                    ValidationResult(
                        check_name="StackSets configuration",
                        status=ValidationStatus.FAILED,
                        message="Access denied to CloudFormation StackSets or Organizations",
                        solution="Grant cloudformation:ListStackSets and organizations:ListAWSServiceAccessForOrganization permissions"
                    )
                )
            elif 'StackSets' in str(e):
                self.validation_results.append(
                    ValidationResult(
                        check_name="StackSets configuration",
                        status=ValidationStatus.FAILED,
                        message="CloudFormation StackSets not enabled",
                        solution="Enable trusted access for CloudFormation StackSets in Organizations"
                    )
                )
            else:
                raise

    def _check_permissions(self):
        """Check required IAM permissions"""
        required_actions = [
            ('sts', 'AssumeRole', 'sts:AssumeRole'),
            ('dynamodb', 'ListTables', 'dynamodb:ListTables'),
            ('organizations', 'ListAccounts', 'organizations:ListAccounts'),
            ('cloudformation', 'CreateStackSet', 'cloudformation:CreateStackSet'),
        ]

        missing_permissions = []

        for service, action, permission_name in required_actions:
            try:
                client = aws_auth.get_client(service)

                # Try to perform a harmless action to check permission
                if service == 'sts':
                    # Can't test AssumeRole without a role, so skip
                    continue
                elif service == 'dynamodb':
                    client.list_tables(Limit=1)
                elif service == 'organizations':
                    client.list_accounts(MaxResults=1)
                elif service == 'cloudformation':
                    # Can't test CreateStackSet, check ListStackSets instead
                    client.list_stack_sets(Status='ACTIVE', MaxResults=1)

            except ClientError as e:
                if e.response['Error']['Code'] in ['AccessDeniedException', 'UnauthorizedOperation']:
                    missing_permissions.append(permission_name)

        if missing_permissions:
            self.validation_results.append(
                ValidationResult(
                    check_name="required permissions",
                    status=ValidationStatus.WARNING,
                    message=f"Some permissions may be missing: {', '.join(missing_permissions)}",
                    solution="Review and update IAM policy with required permissions",
                    details={"missing": missing_permissions}
                )
            )
        else:
            self.validation_results.append(
                ValidationResult(
                    check_name="required permissions",
                    status=ValidationStatus.PASSED,
                    message="All testable permissions verified"
                )
            )

    def _check_organization_structure(self):
        """Check organization structure and accounts"""
        if not self.organization_id:
            self.validation_results.append(
                ValidationResult(
                    check_name="organization structure",
                    status=ValidationStatus.SKIPPED,
                    message="Skipped - Organizations not accessible"
                )
            )
            return

        try:
            org_client = aws_auth.get_client('organizations')

            # List accounts
            paginator = org_client.get_paginator('list_accounts')
            accounts = []
            for page in paginator.paginate():
                accounts.extend(page['Accounts'])

            active_accounts = [acc for acc in accounts if acc['Status'] == 'ACTIVE']
            suspended_accounts = [acc for acc in accounts if acc['Status'] == 'SUSPENDED']

            self.validation_results.append(
                ValidationResult(
                    check_name="organization structure",
                    status=ValidationStatus.PASSED if active_accounts else ValidationStatus.WARNING,
                    message=f"Found {len(active_accounts)} active accounts, {len(suspended_accounts)} suspended",
                    details={
                        "total_accounts": len(accounts),
                        "active_accounts": len(active_accounts),
                        "suspended_accounts": len(suspended_accounts)
                    }
                )
            )

        except ClientError as e:
            self.validation_results.append(
                ValidationResult(
                    check_name="organization structure",
                    status=ValidationStatus.WARNING,
                    message=f"Could not check organization structure: {str(e)}",
                    solution="Ensure organizations:ListAccounts permission"
                )
            )

    def _display_results(self, verbose: bool = False):
        """Display validation results in a formatted table"""
        console.print("\n[bold]Validation Results:[/bold]\n")

        # Create results table
        table = Table(show_header=True, header_style="bold magenta")
        table.add_column("Check", style="cyan", no_wrap=True)
        table.add_column("Status", justify="center")
        table.add_column("Details")

        for result in self.validation_results:
            # Color code status
            if result.status == ValidationStatus.PASSED:
                status = "[green]✓ PASSED[/green]"
            elif result.status == ValidationStatus.FAILED:
                status = "[red]✗ FAILED[/red]"
            elif result.status == ValidationStatus.WARNING:
                status = "[yellow]⚠ WARNING[/yellow]"
            else:
                status = "[dim]- SKIPPED[/dim]"

            # Build details message
            details = result.message
            if result.solution:
                details += f"\n[yellow]→ {result.solution}[/yellow]"

            table.add_row(result.check_name.title(), status, details)

        console.print(table)

        # Summary
        failed_count = sum(1 for r in self.validation_results if r.status == ValidationStatus.FAILED)
        warning_count = sum(1 for r in self.validation_results if r.status == ValidationStatus.WARNING)

        console.print("\n[bold]Summary:[/bold]")
        if failed_count == 0:
            console.print("[green]✓ All critical checks passed![/green]")
            if self.is_management_account:
                console.print("[green]Ready to deploy cross-account infrastructure from management account.[/green]")
            elif self.is_delegated_admin:
                console.print("[green]Ready to deploy cross-account infrastructure as delegated administrator.[/green]")
        else:
            console.print(f"[red]✗ {failed_count} critical check(s) failed.[/red]")
            console.print("[yellow]Please resolve the issues above before proceeding.[/yellow]")

        if warning_count > 0:
            console.print(f"[yellow]⚠ {warning_count} warning(s) - review recommended but not blocking.[/yellow]")

        # Additional guidance
        if verbose and failed_count > 0:
            console.print("\n[bold]Next Steps:[/bold]")
            console.print("1. Review the failed checks above")
            console.print("2. Follow the suggested solutions")
            console.print("3. Run 'tag-manager cross-account setup --validate-only' to re-check")

    def get_validation_summary(self) -> Dict:
        """Get validation summary for programmatic use"""
        return {
            "passed": all(r.status != ValidationStatus.FAILED for r in self.validation_results),
            "is_management_account": self.is_management_account,
            "is_delegated_admin": self.is_delegated_admin,
            "account_id": self.account_id,
            "organization_id": self.organization_id,
            "failed_checks": [r.check_name for r in self.validation_results if r.status == ValidationStatus.FAILED],
            "warnings": [r.check_name for r in self.validation_results if r.status == ValidationStatus.WARNING],
            "results": self.validation_results
        }


# Singleton instance
cross_account_validator = CrossAccountValidator()