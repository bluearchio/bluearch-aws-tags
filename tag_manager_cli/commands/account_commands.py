"""
AWS Account Management Commands for Cross-Account Operations

This module provides CLI commands for managing cross-account infrastructure,
including setup, testing, and account group management.
"""

import json
from typing import List, Optional
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table
from rich.prompt import Prompt, Confirm
from rich.progress import Progress, SpinnerColumn, TextColumn
from botocore.exceptions import ClientError

from ..utils.aws_auth import aws_auth
from ..utils.account_iterator import account_iterator
from ..utils.error_handlers import handle_aws_errors
from ..services.organizations_service import OrganizationsService
from ..utils.setup_guardrails import setup_guardrails
from ..services.dynamodb_state import DynamoDBStateService
from ..licensing.gate import requires_tier
from ..utils.parallel_role_manager import ParallelRoleManager, AccountInfo

app = typer.Typer(
    help="Manage cross-account infrastructure and enable/disable accounts",
    no_args_is_help=False
)
console = Console()


def _enable_stacksets_trusted_access() -> bool:
    """
    Enable CloudFormation StackSets trusted access for AWS Organizations.

    Returns:
        True if successful, False otherwise
    """
    try:
        console.print("[blue]Enabling CloudFormation StackSets trusted access...[/blue]")

        cf_client = aws_auth.get_client('cloudformation')
        org_client = aws_auth.get_client('organizations')

        # First enable trusted access at the Organizations level
        # Use the correct service principal for StackSets with Organizations
        try:
            org_client.enable_aws_service_access(
                ServicePrincipal='member.org.stacksets.cloudformation.amazonaws.com'
            )
            console.print("[green]✓ Enabled Organizations trusted access for CloudFormation StackSets[/green]")
        except ClientError as e:
            if e.response['Error']['Code'] == 'ConcurrentModificationException':
                console.print("[blue]Trusted access is being enabled concurrently, waiting...[/blue]")
                import time
                time.sleep(2)
            elif 'AlreadyEnabled' in str(e) or 'already enabled' in str(e).lower():
                console.print("[blue]Organizations trusted access already enabled[/blue]")
            else:
                raise

        # Then activate Organizations access in CloudFormation
        try:
            cf_client.activate_organizations_access()
            console.print("[green]✓ Activated CloudFormation Organizations access[/green]")
        except ClientError as e:
            if e.response['Error']['Code'] == 'InvalidOperationException':
                # May already be activated
                error_msg = str(e)
                if 'already activated' in error_msg.lower():
                    console.print("[blue]CloudFormation Organizations access already activated[/blue]")
                else:
                    raise
            else:
                raise

        return True

    except ClientError as e:
        error_code = e.response.get('Error', {}).get('Code', '')
        error_message = e.response.get('Error', {}).get('Message', str(e))

        console.print(f"[red]Failed to enable trusted access:[/red]")
        console.print(f"[red]  Error Code: {error_code}[/red]")
        console.print(f"[red]  Message: {error_message}[/red]")

        if error_code == 'AccessDeniedException':
            console.print("\n[yellow]Required permissions:[/yellow]")
            console.print("  - organizations:EnableAWSServiceAccess")
            console.print("  - cloudformation:ActivateOrganizationsAccess")

        return False
    except Exception as e:
        console.print(f"[red]Unexpected error: {str(e)}[/red]")
        return False


def show_accounts_help():
    """Show custom formatted help for accounts command."""
    console.print("\n[bold cyan]AWS Cross-Account Management[/bold cyan] - Configure multi-account operations\n")

    console.print("[bold green]✨ ONE-COMMAND SETUP[/bold green] (Recommended):")
    console.print("  [cyan]accounts setup --complete[/cyan]\n")
    console.print("  This single command will:")
    console.print("    1. Deploy BlueArchRole to all accounts")
    console.print("    2. Test access to verify deployment")
    console.print("    3. List all Organization accounts")
    console.print("    4. Enable all accounts for scanning\n")
    console.print("  After this, you're ready for all multi-account operations!\n")

    console.print("[bold yellow]MANUAL SETUP[/bold yellow] (If you prefer step-by-step control):")
    console.print("[dim]Step 1: Infrastructure[/dim]")
    console.print("- [cyan]accounts setup[/cyan]           - Deploy BlueArchRole to all accounts")
    console.print("- [cyan]accounts test-access[/cyan]     - Verify role deployment worked")
    console.print("- [cyan]accounts list[/cyan]            - List all Organization accounts")
    console.print("[dim]Step 2: Enable Accounts[/dim]")
    console.print("- [cyan]accounts enable --all[/cyan]    - Enable all accounts")
    console.print("- [cyan]accounts enable --accounts ID1,ID2[/cyan] - Specific accounts")
    console.print("- [cyan]accounts enable --ou ou-xxx[/cyan]        - All accounts in OU\n")

    console.print("[bold magenta]AFTER SETUP[/bold magenta]:")
    console.print("- [green]discover --multi-account[/green]      - Discover resources across accounts")
    console.print("- [green]cost report --tag-key Team[/green]    - Analyze costs by tag")
    console.print("- [green]tags apply --multi-account[/green]    - Apply tags across accounts\n")

    console.print("[bold cyan]MAINTENANCE[/bold cyan]:")
    console.print("- [cyan]accounts show-enabled[/cyan]    - View which accounts are enabled")
    console.print("- [cyan]accounts disable[/cyan]         - Disable accounts from scanning")
    console.print("- [cyan]accounts diagnose ID[/cyan]     - Debug specific account issues")
    console.print("- [cyan]accounts rollback[/cyan]        - Remove cross-account infrastructure\n")

    console.print("[bold blue]ARCHITECTURE[/bold blue]:")
    console.print("- Uses CloudFormation StackSets for role deployment")
    console.print("- Parallel role assumption for performance")
    console.print("- Hybrid state: DynamoDB (centralized) + SQLite (local)")
    console.print("- Automatic fallback to local storage when offline\n")

    console.print("For detailed command help: [cyan]accounts [COMMAND] --help[/cyan]")


@app.callback(invoke_without_command=True)
def accounts_callback(
    ctx: typer.Context,
    help: bool = typer.Option(False, "--help", "-h", help="Show this message and exit")
):
    """
    AWS Account Management for Cross-Account Operations.

    This command group manages cross-account infrastructure and controls which
    accounts are enabled for multi-account discovery and tagging operations.
    """
    # Show custom help if no subcommand or --help
    if ctx.invoked_subcommand is None or help:
        show_accounts_help()
        raise typer.Exit()


@app.command()
@requires_tier("cross_account")
def setup(
    validate_only: bool = typer.Option(False, "--validate-only", help="Only validate prerequisites without deploying"),
    accounts: Optional[str] = typer.Option(None, "--accounts", help="Comma-separated list of account IDs"),
    organizational_units: Optional[str] = typer.Option(None, "--ous", help="Comma-separated list of OU IDs"),
    regions: Optional[str] = typer.Option(None, "--regions", help="Comma-separated list of regions"),
    force: bool = typer.Option(False, "--force", "-f", help="Skip confirmation prompts"),
    clean: bool = typer.Option(False, "--clean", help="Delete existing StackSet and recreate from scratch"),
    update: bool = typer.Option(False, "--update", help="Update existing StackSet to latest template version"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Simulate deployment without making changes"),
    complete: bool = typer.Option(False, "--complete", help="Complete setup: deploy, test, list, and enable all accounts")
):
    """
    Deploy cross-account infrastructure using CloudFormation StackSets.

    Use --complete for one-command full setup (deploy, test, list, enable all).
    """
    console.print("\n[bold cyan]Cross-Account Infrastructure Setup[/bold cyan]\n")
    if dry_run:
        payload = {
            "accounts": [item.strip() for item in accounts.split(",") if item.strip()] if accounts else None,
            "organizational_units": [item.strip() for item in organizational_units.split(",") if item.strip()]
            if organizational_units
            else None,
            "regions": [item.strip() for item in regions.split(",") if item.strip()] if regions else None,
            "force_recreate": clean,
            "update": update,
        }
        console.print("[yellow]DRY RUN - no bluearch-core setup job submitted[/yellow]")
        console.print(json.dumps(payload, indent=2))
        return

    from .setup_commands import multi_account_setup

    multi_account_setup(
        validate_only=validate_only,
        accounts=accounts,
        organizational_units=organizational_units,
        regions=regions,
        force=force,
        clean=clean,
        update=update,
        complete=complete,
        remove=False,
    )
    return


@app.command()
@requires_tier("cross_account")
def list(
    show_access: bool = typer.Option(True, "--show-access/--no-access", help="Test and show role access status"),
    include_suspended: bool = typer.Option(False, "--include-suspended", help="Include suspended accounts"),
    output_format: str = typer.Option("table", "--format", help="Output format: table, json"),
    role_name: str = typer.Option("BlueArchRole", "--role-name", help="Role name to test")
):
    """List all AWS Organization accounts with their status"""

    console.print("\n[bold cyan]AWS Organization Accounts[/bold cyan]\n")

    try:
        # Get accounts
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=console,
            transient=True
        ) as progress:
            task = progress.add_task("Loading accounts...", total=None)

            accounts = account_iterator.list_accounts(
                include_suspended=include_suspended,
                validate_access=show_access,
                role_name=role_name
            )

            progress.remove_task(task)

        if output_format == "json":
            # JSON output
            output = []
            for account in accounts:
                output.append({
                    "account_id": account.account_id,
                    "account_name": account.account_name,
                    "email": account.email,
                    "status": account.status.value,
                    "role_configured": account.role_configured
                })
            console.print_json(data=output)
        else:
            # Table output
            account_iterator.display_accounts_table(accounts, show_access_status=show_access)

        # Provide actionable next steps
        if show_access:
            failed_access = [a for a in accounts if a.status.value == 'ACTIVE' and not a.role_configured]
            if failed_access:
                console.print(f"\n[yellow]Found {len(failed_access)} accounts without role access.[/yellow]")
                console.print("Run 'tag-manager accounts setup' to deploy the role to these accounts.")

    except Exception as e:
        console.print(f"[red]Failed to list accounts: {str(e)}[/red]")
        raise typer.Exit(1)


@app.command()
@requires_tier("cross_account")
def test_access(
    account_ids: Optional[str] = typer.Option(None, "--accounts", help="Comma-separated account IDs to test"),
    role_name: str = typer.Option("BlueArchRole", "--role-name", help="Role name to test"),
    external_id: Optional[str] = typer.Option(None, "--external-id", help="External ID if required"),
    show_all: bool = typer.Option(False, "--all", help="Test all accounts")
):
    """Test role assumption access to accounts"""

    console.print("\n[bold cyan]Testing Cross-Account Access[/bold cyan]\n")

    # Check if database is ready (for tracking results)
    setup_guardrails.ensure_database_ready()

    try:
        # Determine which accounts to test
        if account_ids:
            test_accounts = [a.strip() for a in account_ids.split(",")]
        elif show_all:
            accounts = account_iterator.list_accounts(include_suspended=False, validate_access=False)
            test_accounts = [a.account_id for a in accounts]
        else:
            # Test first 5 accounts as sample
            accounts = account_iterator.list_accounts(include_suspended=False, validate_access=False)
            test_accounts = [a.account_id for a in accounts[:5]]
            if len(accounts) > 5:
                console.print(f"[dim]Testing first 5 accounts (use --all to test all {len(accounts)} accounts)[/dim]\n")

        # Get account information first
        account_map = {}
        try:
            org_accounts = aws_auth.get_organization_accounts()
            for acc in org_accounts:
                account_map[acc['Id']] = acc['Name']
        except Exception:
            pass

        # Use ParallelRoleManager for efficient parallel testing
        role_manager = ParallelRoleManager(
            aws_auth=aws_auth,
            max_workers=10,
            show_progress=True
        )

        # Build AccountInfo objects for all accounts to test
        accounts_to_test = []
        for acc_id in test_accounts:
            accounts_to_test.append(AccountInfo(
                account_id=acc_id,
                account_name=account_map.get(acc_id, "Unknown"),
                role_name=role_name,
                external_id=external_id
            ))

        # Test accounts in parallel with tree display
        console.print(f"[cyan]Testing access to {len(accounts_to_test)} accounts...[/cyan]\n")

        # Get external ID if not provided
        if not external_id:
            external_id = aws_auth.get_cross_account_external_id()
            for account in accounts_to_test:
                account.external_id = external_id

        results = role_manager.assume_roles_parallel(
            accounts=accounts_to_test,
            use_tree_display=True
        )

        # Calculate statistics
        success_count = sum(1 for r in results.values() if r.success)
        failed_count = sum(1 for r in results.values() if not r.success)

        # Show final table
        table = Table(title="Access Test Results")
        table.add_column("Account ID", style="cyan")
        table.add_column("Account Name", style="white")
        table.add_column("Status", justify="center")
        table.add_column("Details", style="dim")

        # Sort results for consistent display
        for acc_id in sorted(test_accounts):
            if acc_id in results:
                result = results[acc_id]
                if result.success:
                    table.add_row(
                        acc_id,
                        result.account_name or "Unknown",
                        "[green]✓ Success[/green]",
                        "Role assumption successful"
                    )
                else:
                    error_msg = result.error_message or "Unknown error"
                    if "Access denied" in error_msg:
                        details = "Access denied - check trust policy"
                    else:
                        details = error_msg[:50] + "..." if len(error_msg) > 50 else error_msg
                    table.add_row(
                        acc_id,
                        result.account_name or "Unknown",
                        "[red]✗ Failed[/red]",
                        details
                    )

        console.print(table)

        # Summary
        console.print(f"\n[bold]Summary:[/bold]")
        console.print(f"  [green]Successful:[/green] {success_count}")
        console.print(f"  [red]Failed:[/red] {failed_count}")

        if failed_count > 0:
            # Check if StackSet exists
            if not setup_guardrails.check_stackset_exists():
                console.print("\n[bold red]No CloudFormation StackSet Found![/bold red]")
                console.print("\nYou need to deploy the infrastructure first:")
                console.print("  [green]1.[/green] Run: [cyan]tag-manager accounts setup[/cyan]")
                console.print("     This will deploy the BlueArchRole to all accounts")
                console.print("  [green]2.[/green] Wait 2-5 minutes for deployment to complete")
                console.print("  [green]3.[/green] Run: [cyan]tag-manager accounts test-access[/cyan]")
                console.print("     To verify the roles are working\n")
            else:
                console.print("\n[yellow]For failed accounts:[/yellow]")
                console.print("  1. The StackSet exists but these accounts don't have access")
                console.print("  2. Check if these are new accounts added after initial setup")
                console.print("  3. Run 'tag-manager accounts setup' to update deployment")
                console.print("  4. Or run 'tag-manager accounts diagnose ACCOUNT_ID' for details")

    except Exception as e:
        console.print(f"[red]Failed to test access: {str(e)}[/red]")
        raise typer.Exit(1)


@app.command("remove-stacks")
@requires_tier("cross_account")
def remove_stacks(
    force: bool = typer.Option(False, "--force", "-f", help="Skip confirmation prompts"),
    keep_management_stack: bool = typer.Option(False, "--keep-management", help="Keep the management account stack")
):
    """
    Remove all cross-account infrastructure (StackSet and stacks).

    This command performs a clean removal of:
    - CloudFormation StackSet instances in member accounts
    - The StackSet itself
    - Optionally, the management account stack

    Shows live progress during deletion similar to setup --clean.
    """
    console.print("\n[bold cyan]Cross-Account Infrastructure Removal[/bold cyan]\n")
    if keep_management_stack:
        console.print(
            "[red]--keep-management is no longer supported here because bluearch-core owns shared setup removal.[/red]"
        )
        raise typer.Exit(1)

    if not force and not Confirm.ask("[bold red]Remove ALL cross-account infrastructure?[/bold red]", default=False):
        console.print("[yellow]Removal cancelled.[/yellow]")
        raise typer.Exit(0)

    try:
        from .setup_commands import _submit_core_setup_job

        result = _submit_core_setup_job(
            "/api/v1/accounts/remove",
            action="Cross-account removal",
            timeout_seconds=1800,
        )
    except Exception as exc:
        console.print(f"[red]Removal failed through bluearch-core: {exc}[/red]")
        raise typer.Exit(1)

    console.print(f"[green]{result.get('message') or 'Cross-account infrastructure removed'}[/green]")
    return


@app.command("cleanup-orphans")
@requires_tier("cross_account")
def cleanup_orphans(
    force: bool = typer.Option(False, "--force", "-f", help="Skip confirmation prompts"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Show what would be deleted without actually deleting")
):
    """
    Clean up orphaned CloudFormation stacks from previous deployments.

    This command finds and deletes orphaned stacks in member accounts that were
    created by a previous StackSet deployment but were not properly cleaned up
    when the StackSet was deleted.

    The orphaned stacks contain BlueArchRole and related IAM resources that
    block new deployments.

    This command requires the current StackSet to be created first (run 'accounts setup').
    It will:
    1. Find orphaned stacks matching 'StackSet-BlueArchCLI-CrossAccount-Infrastructure-*'
    2. Import them into the current StackSet
    3. Delete them properly through the StackSet

    If there is no current StackSet, you'll need to manually delete the orphaned
    stacks from each affected account.
    """
    console.print("\n[bold cyan]Orphaned Stack Cleanup[/bold cyan]\n")
    console.print(
        "[red]Orphan StackSet cleanup is no longer executed from Tag Manager. "
        "Use bluearch-core setup removal/deployment flows or clean up orphaned stacks in CloudFormation.[/red]"
    )
    raise typer.Exit(1)


@app.command()
@requires_tier("cross_account")
def diagnose(
    account_id: str = typer.Argument(..., help="Account ID to diagnose"),
    role_name: str = typer.Option("BlueArchRole", "--role-name", help="Role name to test"),
    external_id: Optional[str] = typer.Option(None, "--external-id", help="External ID if required")
):
    """Diagnose access issues for a specific account"""

    console.print(f"\n[bold cyan]Diagnosing Account {account_id}[/bold cyan]\n")

    diagnostics = []

    try:
        # 1. Check if account exists in organization
        console.print("[bold]1. Checking account existence...[/bold]")
        accounts = aws_auth.get_organization_accounts()
        account = next((a for a in accounts if a['Id'] == account_id), None)

        if account:
            diagnostics.append(("[green]✓[/green]", f"Account found: {account['Name']}"))
            diagnostics.append(("  ", f"Email: {account['Email']}"))
            diagnostics.append(("  ", f"Status: {account['Status']}"))

            if account['Status'] != 'ACTIVE':
                diagnostics.append(("[yellow]⚠[/yellow]", f"Account is {account['Status']} - may not be accessible"))
        else:
            diagnostics.append(("[red]✗[/red]", "Account not found in organization"))

        # 2. Check current identity
        console.print("\n[bold]2. Checking current identity...[/bold]")
        identity = aws_auth.get_caller_identity()
        diagnostics.append(("[green]✓[/green]", f"Current account: {identity['Account']}"))
        diagnostics.append(("  ", f"ARN: {identity['Arn']}"))

        # 3. Check if management account
        console.print("\n[bold]3. Checking account role...[/bold]")
        org_client = aws_auth.get_client('organizations')
        org_info = org_client.describe_organization()
        is_management = org_info['Organization']['MasterAccountId'] == identity['Account']

        if is_management:
            diagnostics.append(("[green]✓[/green]", "Running from management account"))
        else:
            diagnostics.append(("[yellow]⚠[/yellow]", "Not running from management account"))

        # 4. Test role assumption
        console.print("\n[bold]4. Testing role assumption...[/bold]")
        role_arn = f"arn:aws:iam::{account_id}:role/{role_name}"

        try:
            if aws_auth.validate_cross_account_access(account_id, role_name, external_id):
                diagnostics.append(("[green]✓[/green]", f"Successfully assumed role {role_name}"))
            else:
                diagnostics.append(("[red]✗[/red]", f"Failed to assume role {role_name}"))
        except ValueError as e:
            diagnostics.append(("[red]✗[/red]", str(e)))

        # 5. Check StackSet status
        console.print("\n[bold]5. Checking StackSet deployment...[/bold]")
        try:
            cf_client = aws_auth.get_client('cloudformation')
            instances = cf_client.list_stack_instances(
                StackSetName="BlueArchCLI-CrossAccount-Infrastructure",
                StackInstanceAccount=account_id
            )

            if instances['Summaries']:
                instance = instances['Summaries'][0]
                status = instance['Status']
                if status == 'CURRENT':
                    diagnostics.append(("[green]✓[/green]", "StackSet instance is current"))
                else:
                    diagnostics.append(("[yellow]⚠[/yellow]", f"StackSet instance status: {status}"))
                    if instance.get('StatusReason'):
                        diagnostics.append(("  ", f"Reason: {instance['StatusReason']}"))
            else:
                diagnostics.append(("[yellow]⚠[/yellow]", "No StackSet instance found for this account"))
                diagnostics.append(("  ", "Run 'tag-manager accounts setup' to deploy"))
        except ClientError as e:
            if e.response['Error']['Code'] == 'StackSetNotFoundException':
                diagnostics.append(("[red]✗[/red]", "StackSet not found - run 'tag-manager accounts setup'"))
            else:
                diagnostics.append(("[yellow]⚠[/yellow]", f"Could not check StackSet: {str(e)}"))

    except Exception as e:
        diagnostics.append(("[red]✗[/red]", f"Diagnostic failed: {str(e)}"))

    # Display diagnostics
    console.print("\n[bold]Diagnostic Results:[/bold]\n")
    for status, message in diagnostics:
        console.print(f"{status} {message}")

    # Provide recommendations
    console.print("\n[bold]Recommendations:[/bold]")
    if account and account.get('Status') == 'SUSPENDED':
        console.print("  • Account is suspended - contact AWS Support")
    elif not any("[green]✓[/green]" in d[0] and "assumed role" in d[1] for d in diagnostics):
        console.print("  • Run 'tag-manager accounts setup' to deploy the role")
        console.print("  • Check Service Control Policies (SCPs) that might block deployment")
        console.print("  • Verify you have required permissions in your account")


@app.command()
@requires_tier("cross_account")
def rollback(
    accounts: Optional[str] = typer.Option(None, "--accounts", help="Comma-separated list of account IDs"),
    force: bool = typer.Option(False, "--force", "-f", help="Skip confirmation prompt"),
    keep_dynamodb: bool = typer.Option(False, "--keep-dynamodb", help="Keep DynamoDB table")
):
    """Remove cross-account infrastructure"""

    console.print("\n[bold red]Cross-Account Infrastructure Rollback[/bold red]\n")
    if accounts or keep_dynamodb:
        console.print(
            "[red]Partial rollback and DynamoDB-specific cleanup are legacy product-local setup options. "
            "Use the core-owned full removal flow instead.[/red]"
        )
        raise typer.Exit(1)

    # Warning
    console.print("[yellow]WARNING: This will remove:[/yellow]")
    console.print("  • Cross-account IAM roles from specified accounts")
    console.print("  • CloudFormation StackSet")
    if not keep_dynamodb:
        console.print("  • DynamoDB state table (if exists)")
    console.print("\n[yellow]This action cannot be undone![/yellow]")

    if not force:
        if not Confirm.ask("\n[red]Are you sure you want to proceed?[/red]"):
            console.print("[green]Rollback cancelled[/green]")
            raise typer.Exit(0)

    try:
        from .setup_commands import _submit_core_setup_job

        result = _submit_core_setup_job(
            "/api/v1/accounts/remove",
            action="Cross-account removal",
            timeout_seconds=1800,
        )
    except Exception as exc:
        console.print(f"[red]Rollback failed through bluearch-core: {exc}[/red]")
        raise typer.Exit(1)

    aws_auth.clear_assumed_sessions_cache()
    console.print(f"[green]{result.get('message') or 'Rollback completed'}[/green]")
    return


@app.command()
@requires_tier("cross_account")
def enable(
    accounts: Optional[str] = typer.Option(None, "--accounts", help="Comma-separated account IDs to enable"),
    ou: Optional[str] = typer.Option(None, "--ou", help="Organizational Unit ID to enable all accounts within"),
    all_accounts: bool = typer.Option(False, "--all", help="Enable all accounts in the organization"),
    force: bool = typer.Option(False, "--force", "-f", help="Skip confirmation")
):
    """Enable accounts for cross-account scanning"""

    console.print("\n[bold cyan]Enabling Accounts for Scanning[/bold cyan]\n")

    # Check if setup is complete
    if not setup_guardrails.ensure_setup_or_exit():
        return

    try:
        # Determine which accounts to enable
        target_accounts = []

        if accounts:
            # Specific accounts provided
            target_accounts = [a.strip() for a in accounts.split(",")]
            console.print(f"Enabling specific accounts: {target_accounts}")

        elif ou:
            # Enable all accounts in an OU
            console.print(f"[bold]Enabling all accounts in OU: {ou}[/bold]")
            org_client = aws_auth.get_client('organizations')

            # Get accounts in the OU
            paginator = org_client.get_paginator('list_accounts_for_parent')
            ou_accounts = []
            for page in paginator.paginate(ParentId=ou):
                for account in page['Accounts']:
                    if account['Status'] == 'ACTIVE':
                        ou_accounts.append(account['Id'])

            target_accounts = ou_accounts
            console.print(f"Found {len(ou_accounts)} active accounts in OU {ou}")

        elif all_accounts:
            # Enable all organization accounts
            console.print("[bold]Enabling all organization accounts[/bold]")
            org_accounts = aws_auth.get_organization_accounts()
            target_accounts = [a['Id'] for a in org_accounts if a['Status'] == 'ACTIVE']
            console.print(f"Found {len(target_accounts)} active accounts")

        else:
            console.print("[red]Please specify --accounts, --ou, or --all[/red]")
            raise typer.Exit(1)

        if not target_accounts:
            console.print("[yellow]No accounts to enable[/yellow]")
            return

        # Confirmation
        if not force:
            if not Confirm.ask(f"Enable {len(target_accounts)} accounts for scanning?"):
                console.print("[yellow]Operation cancelled[/yellow]")
                return

        # Use DynamoDB state service to enable accounts
        dynamodb_state = DynamoDBStateService()

        # Check if DynamoDB is available
        if dynamodb_state.check_table_exists():
            console.print("[dim]Using DynamoDB for centralized state management[/dim]")
        else:
            console.print("[yellow]DynamoDB table 'tag-manager-cross-account' not found. Using local storage only.[/yellow]")

        # Enable accounts
        result = dynamodb_state.enable_accounts(target_accounts)

        if result['success'] or result['enabled_count'] > 0:
            console.print(f"[green]Successfully enabled {result['enabled_count']} accounts[/green]")

            # Show any failures
            if result['failed_accounts']:
                console.print(f"[yellow]Failed to enable {len(result['failed_accounts'])} accounts:[/yellow]")
                for acc in result['failed_accounts'][:5]:
                    console.print(f"  - {acc}")
                if len(result['failed_accounts']) > 5:
                    console.print(f"  ... and {len(result['failed_accounts']) - 5} more")

            # Get total enabled count
            all_enabled = dynamodb_state.get_enabled_accounts()
            console.print(f"Total enabled accounts: {len(all_enabled)}")
        else:
            console.print(f"[red]Failed to enable accounts: {result.get('errors', ['Unknown error'])[0]}[/red]")
            raise typer.Exit(1)

    except ClientError as e:
        console.print(f"[red]Failed to enable accounts: {str(e)}[/red]")
        raise typer.Exit(1)


@app.command()
@requires_tier("cross_account")
def disable(
    accounts: Optional[str] = typer.Option(None, "--accounts", help="Comma-separated account IDs to disable"),
    ou: Optional[str] = typer.Option(None, "--ou", help="Organizational Unit ID to disable all accounts within"),
    all_accounts: bool = typer.Option(False, "--all", help="Disable all accounts"),
    force: bool = typer.Option(False, "--force", "-f", help="Skip confirmation")
):
    """Disable accounts from cross-account scanning"""

    console.print("\n[bold cyan]Disabling Accounts from Scanning[/bold cyan]\n")

    # Check if setup is complete
    if not setup_guardrails.ensure_setup_or_exit():
        return

    try:
        # Determine which accounts to disable
        target_accounts = []

        if accounts:
            # Specific accounts provided
            target_accounts = [a.strip() for a in accounts.split(",")]
            console.print(f"Disabling specific accounts: {target_accounts}")

        elif ou:
            # Disable all accounts in an OU
            console.print(f"[bold]Disabling all accounts in OU: {ou}[/bold]")
            org_client = aws_auth.get_client('organizations')

            # Get accounts in the OU
            paginator = org_client.get_paginator('list_accounts_for_parent')
            ou_accounts = []
            for page in paginator.paginate(ParentId=ou):
                for account in page['Accounts']:
                    ou_accounts.append(account['Id'])

            target_accounts = ou_accounts
            console.print(f"Found {len(ou_accounts)} accounts in OU {ou}")

        elif all_accounts:
            # Disable all accounts
            console.print("[bold]Disabling all accounts[/bold]")
            enabled_file = Path.home() / ".tag-manager" / "data" / "enabled_accounts.json"
            if enabled_file.exists():
                with open(enabled_file, 'r') as f:
                    target_accounts = json.load(f)
            console.print(f"Found {len(target_accounts)} enabled accounts")

        else:
            console.print("[red]Please specify --accounts, --ou, or --all[/red]")
            raise typer.Exit(1)

        if not target_accounts:
            console.print("[yellow]No accounts to disable[/yellow]")
            return

        # Confirmation
        if not force:
            if not Confirm.ask(f"Disable {len(target_accounts)} accounts from scanning?"):
                console.print("[yellow]Operation cancelled[/yellow]")
                return

        # Use DynamoDB state service to disable accounts
        dynamodb_state = DynamoDBStateService()

        # Check if DynamoDB is available
        if dynamodb_state.check_table_exists():
            console.print("[dim]Using DynamoDB for centralized state management[/dim]")
        else:
            console.print("[yellow]DynamoDB table 'tag-manager-cross-account' not found. Using local storage only.[/yellow]")

        # Disable accounts
        result = dynamodb_state.disable_accounts(target_accounts)

        if result['success'] or result['disabled_count'] > 0:
            console.print(f"[green]Successfully disabled {result['disabled_count']} accounts[/green]")

            # Show any failures
            if result['failed_accounts']:
                console.print(f"[yellow]Failed to disable {len(result['failed_accounts'])} accounts:[/yellow]")
                for acc in result['failed_accounts'][:5]:
                    console.print(f"  - {acc}")
                if len(result['failed_accounts']) > 5:
                    console.print(f"  ... and {len(result['failed_accounts']) - 5} more")

            # Get remaining enabled count
            all_enabled = dynamodb_state.get_enabled_accounts()
            console.print(f"Remaining enabled accounts: {len(all_enabled)}")
        else:
            console.print(f"[red]Failed to disable accounts: {result.get('errors', ['Unknown error'])[0]}[/red]")
            raise typer.Exit(1)

    except ClientError as e:
        console.print(f"[red]Failed to disable accounts: {str(e)}[/red]")
        raise typer.Exit(1)


@app.command()
@requires_tier("cross_account")
def show_enabled():
    """Show which accounts are enabled for scanning"""

    console.print("\n[bold cyan]Enabled Accounts[/bold cyan]\n")

    # Check if setup is complete (but don't exit if not)
    setup_guardrails.ensure_database_ready()

    # Use DynamoDB state service
    dynamodb_state = DynamoDBStateService()

    # Get sync status
    sync_status = dynamodb_state.get_sync_status()
    if sync_status.get('dynamodb_available'):
        console.print("[dim]Source: DynamoDB (centralized)[/dim]")
    elif sync_status.get('dynamodb_available') is False:
        console.print("[dim]Source: Local cache (DynamoDB not available)[/dim]")
    else:
        console.print("[dim]Source: Local cache[/dim]")

    # Get enabled accounts
    enabled_accounts = dynamodb_state.get_enabled_accounts()

    if not enabled_accounts:
        console.print("[yellow]No accounts are currently enabled for scanning[/yellow]")
        console.print("\nEnable accounts with:")
        console.print("  • 'tag-manager accounts enable --accounts 123456789012'")
        console.print("  • 'tag-manager accounts enable --ou ou-xxxx-xxxxxxxx'")
        console.print("  • 'tag-manager accounts enable --all'")
        return

    # Get account details
    try:
        org_accounts = aws_auth.get_organization_accounts()

        table = Table(title="Enabled Accounts for Scanning")
        table.add_column("Account ID", style="cyan")
        table.add_column("Account Name", style="white")
        table.add_column("Status")
        table.add_column("OU", style="dim")

        # Get OU information for each account
        org_client = aws_auth.get_client('organizations')

        for account_id in enabled_accounts:
            account = next((a for a in org_accounts if a['Id'] == account_id), None)

            if account:
                # Get parent OU
                try:
                    parents = org_client.list_parents(ChildId=account_id)
                    parent_ou = parents['Parents'][0]['Id'] if parents['Parents'] else "Root"
                except:
                    parent_ou = "Unknown"

                status = "[green]ACTIVE[/green]" if account['Status'] == 'ACTIVE' else f"[yellow]{account['Status']}[/yellow]"
                table.add_row(account_id, account['Name'], status, parent_ou)
            else:
                table.add_row(account_id, "Unknown", "[red]NOT FOUND[/red]", "Unknown")

        console.print(table)
        console.print(f"\n[bold]Total:[/bold] {len(enabled_accounts)} accounts enabled")

    except Exception as e:
        # Fall back to simple list
        console.print("[yellow]Could not retrieve account details[/yellow]")
        console.print("\nEnabled account IDs:")
        for account_id in enabled_accounts:
            console.print(f"  • {account_id}")


if __name__ == "__main__":
    app()
