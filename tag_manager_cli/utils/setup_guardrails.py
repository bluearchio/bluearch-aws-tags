"""
Setup guardrails to ensure proper initialization of cross-account features.

This module provides validation and automatic setup for cross-account operations,
ensuring the database schema is up-to-date and infrastructure is deployed.
"""

from typing import Tuple, Optional
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Confirm
import sys
import typer

from ..utils.aws_auth import aws_auth
from ..utils.core_client import request_core
from ..utils.parallel_role_manager import ParallelRoleManager, AccountInfo
from botocore.exceptions import ClientError

console = Console()


class SetupGuardrails:
    """Provides guardrails and automatic setup for cross-account features."""

    @staticmethod
    def ensure_database_ready() -> bool:
        """
        Ensure bluearch-core storage has the account-status collection.

        Returns:
            bool: True if database is ready, False otherwise
        """
        try:
            request_core("GET", "/api/v1/core/db/status", timeout=10.0)
            request_core(
                "GET",
                "/api/v1/storage/core/account-status",
                service_token=True,
                params=[("limit", 1)],
                timeout=10.0,
            )
            return True

        except Exception as e:
            console.print(f"[red]Failed to check bluearch-core storage: {str(e)}[/red]")
            return False

    @staticmethod
    def check_stackset_exists(stackset_name: str = "BlueArchCLI-CrossAccount-Infrastructure") -> bool:
        """
        Check if the CloudFormation StackSet exists.

        Args:
            stackset_name: Name of the StackSet to check

        Returns:
            bool: True if StackSet exists, False otherwise
        """
        try:
            cf_client = aws_auth.get_client('cloudformation')
            cf_client.describe_stack_set(StackSetName=stackset_name)
            return True
        except ClientError as e:
            if e.response['Error']['Code'] == 'StackSetNotFoundException':
                return False
            # Other errors - assume setup might be needed
            return False
        except Exception:
            return False

    @staticmethod
    def check_any_role_access(role_name: str = "BlueArchRole") -> Tuple[bool, int, int]:
        """
        Check if any accounts have the cross-account role deployed.

        Args:
            role_name: Name of the role to check

        Returns:
            Tuple of (has_any_access, success_count, total_count)
        """
        try:
            # Get organization accounts
            org_accounts = aws_auth.get_organization_accounts()
            active_accounts = [acc for acc in org_accounts if acc['Status'] == 'ACTIVE']

            if not active_accounts:
                return False, 0, 0

            # Test first 5 accounts as a sample
            test_accounts = active_accounts[:5]

            # Use ParallelRoleManager for efficient parallel validation
            role_manager = ParallelRoleManager(
                aws_auth=aws_auth,
                max_workers=5,
                show_progress=False  # Silent validation
            )

            # Build AccountInfo objects
            accounts_to_test = [
                AccountInfo(
                    account_id=account['Id'],
                    account_name=account.get('Name', 'Unknown'),
                    role_name=role_name
                )
                for account in test_accounts
            ]

            # Test accounts in parallel (silently)
            results = role_manager.assume_roles_parallel(
                accounts=accounts_to_test,
                use_tree_display=False
            )

            # Count successful role assumptions
            success_count = sum(1 for r in results.values() if r.success)

            return success_count > 0, success_count, len(test_accounts)

        except Exception:
            return False, 0, 0

    @staticmethod
    def validate_setup_complete() -> Tuple[bool, Optional[str]]:
        """
        Validate that cross-account setup is complete.

        Returns:
            Tuple of (is_complete, error_message)
        """
        # Check database
        if not SetupGuardrails.ensure_database_ready():
            return False, "Database schema not ready. Run database migrations."

        # Check StackSet
        if not SetupGuardrails.check_stackset_exists():
            return False, "CloudFormation StackSet not found. Run 'bluearch-aws-tags accounts setup' first."

        # Check if any accounts have role access
        has_access, success_count, total_tested = SetupGuardrails.check_any_role_access()
        if not has_access:
            return False, f"No accounts have role access (tested {total_tested}). Run 'bluearch-aws-tags accounts setup'."

        return True, None

    @staticmethod
    def show_setup_required_message():
        """Display a helpful message about running setup first."""
        panel = Panel(
            "[bold yellow]Cross-Account Setup Required[/bold yellow]\n\n"
            "Before you can enable/disable accounts, you need to:\n\n"
            "1. [cyan]Deploy infrastructure:[/cyan]\n"
            "   [dim]bluearch-aws-tags accounts setup[/dim]\n"
            "   This deploys the BlueArchRole to your accounts\n\n"
            "2. [cyan]Verify access:[/cyan]\n"
            "   [dim]bluearch-aws-tags accounts test-access[/dim]\n"
            "   This confirms the roles are working\n\n"
            "3. [cyan]Enable accounts:[/cyan]\n"
            "   [dim]bluearch-aws-tags accounts enable --all[/dim]\n"
            "   This marks accounts for scanning\n\n"
            "[bold]Quick Start:[/bold]\n"
            "[green]bluearch-aws-tags accounts setup --all[/green]",
            border_style="yellow",
            padding=(1, 2)
        )
        console.print(panel)

    @staticmethod
    def ensure_setup_or_exit() -> bool:
        """
        Ensure setup is complete or exit with helpful message.

        Returns:
            bool: True if setup is complete
        """
        # First ensure database is ready
        if not SetupGuardrails.ensure_database_ready():
            console.print("\n[red]Cannot proceed without database schema[/red]")
            sys.exit(1)

        # Then check infrastructure
        is_complete, error_msg = SetupGuardrails.validate_setup_complete()

        if not is_complete:
            console.print(f"\n[red]Setup incomplete: {error_msg}[/red]")
            SetupGuardrails.show_setup_required_message()

            # Offer to run setup
            if Confirm.ask("\nWould you like to run setup now?", default=True):
                console.print("\n[green]Starting setup...[/green]\n")

                # Try to run setup directly by importing and calling it
                # This works in both development and packaged binaries
                try:
                    from ..commands import account_commands

                    # Call setup with default parameters
                    console.print("[blue]Deploying cross-account infrastructure...[/blue]")
                    console.print("[dim]This will deploy BlueArchRole to all accounts[/dim]\n")

                    # Run setup (this will handle all the validation and deployment)
                    # We need to catch typer.Exit exceptions since typer uses them for control flow
                    try:
                        account_commands.setup(
                            validate_only=False,
                            accounts=None,  # Deploy to all accounts
                            organizational_units=None,
                            regions=None,
                            force=False,  # Will prompt for confirmation
                            dry_run=False
                        )
                        # If we get here, setup was successful
                        console.print("\n[green]Setup completed! You can now enable accounts.[/green]")
                        return True

                    except typer.Exit as e:
                        # Typer uses Exit for normal termination
                        if e.exit_code == 0:
                            console.print("\n[green]Setup completed! You can now enable accounts.[/green]")
                            return True
                        else:
                            console.print("\n[yellow]Setup was cancelled or failed[/yellow]")
                            sys.exit(e.exit_code)

                except SystemExit as e:
                    # Setup command exited (either success or user cancelled)
                    if e.code == 0:
                        # Success - user can now proceed
                        console.print("\n[green]Setup completed! You can now enable accounts.[/green]")
                        return True
                    else:
                        # User cancelled or error occurred
                        sys.exit(e.code)
                except Exception as e:
                    console.print(f"\n[red]Failed to run setup: {e}[/red]")
                    console.print("\n[yellow]Run manually:[/yellow] bluearch-aws-tags accounts setup")
                    sys.exit(1)
            else:
                sys.exit(1)

        return True


# Singleton instance
setup_guardrails = SetupGuardrails()
