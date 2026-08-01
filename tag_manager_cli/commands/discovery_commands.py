"""Discovery Commands for AWS Tag Manager CLI.

Top-level commands for discovering AWS resources across services and regions.
"""

import typer
from typing import Optional
from rich.console import Console
from ..modules.collection.collectors import COLLECTORS
from ..utils.error_handlers import require_aws_credentials, handle_all_errors
from ..utils.aws_auth import aws_auth
from ..utils.console_safe import safe_print

console = Console()

# Create the discover app
discover_app = typer.Typer(
    name="discover",
    help="Discover AWS resources across services and regions",
    no_args_is_help=False
)


def show_discover_help():
    """Show custom formatted help for discover command."""
    console.print("\n[bold cyan]AWS Resource Discovery[/bold cyan] - Scan and inventory your AWS environment\n")

    console.print("[bold green]SERVICE OPTIONS[/bold green] (what to discover):")
    console.print("- [cyan]discover all[/cyan]     - Discover ALL services in all regions (default)")
    console.print("- [cyan]discover ec2[/cyan]     - EC2 instances only")
    console.print("- [cyan]discover s3[/cyan]      - S3 buckets only (global service)")
    console.print("- [cyan]discover lambda[/cyan]  - Lambda functions only\n")

    console.print("[bold yellow]MULTI-ACCOUNT OPTIONS[/bold yellow] (NEW default behavior):")
    console.print("- [cyan]Automatic:[/cyan] Scans all enabled accounts when configured")
    console.print("- [dim]--single-account[/dim]     # Force scan current account only")
    console.print("- [dim]--accounts 123,456[/dim]  # Scan specific account IDs\n")

    console.print("[bold yellow]REGION OPTIONS[/bold yellow] (where to scan):")
    console.print("- [dim]discover --regions us-east-1,eu-west-1[/dim]  # Specific regions\n")

    console.print("[bold magenta]OTHER OPTIONS[/bold magenta]:")
    console.print("- [dim]--force[/dim]             # Force fresh scan, ignore cache")
    console.print("- [dim]--services ec2,s3[/dim]   # Combine multiple services\n")

    console.print("[bold green]QUICK START EXAMPLES[/bold green]:")
    console.print("1. [dim]discover all[/dim]                       # Scan all enabled accounts")
    console.print("2. [dim]discover all --single-account[/dim]     # Current account only")
    console.print("3. [dim]discover ec2[/dim]                       # EC2 across all accounts")
    console.print("4. [dim]discover lambda --regions us-east-1[/dim] # Lambda in one region, all accounts")
    console.print("5. [dim]discover --regions all[/dim]             # Scan all enabled regions")
    console.print("6. [dim]discover --force[/dim]                   # Force fresh scan\n")

    console.print("[bold cyan]PERFORMANCE NOTES[/bold cyan]:")
    console.print("- Runs up to 10 discoveries concurrently")
    console.print("- Real-time tree display shows progress")
    console.print("- Default: US regions for faster scans")
    console.print("- Use [cyan]--regions all[/cyan] when you need full global coverage\n")

    console.print("[bold green]NEXT STEPS[/bold green] (after discovery):")
    console.print("- [cyan]bluearch-aws-tags lifecycle wizard[/cyan]  # Guided lifecycle and tagging workflow")
    console.print("- [cyan]bluearch-aws-tags policy --help[/cyan]     # AWS Organizations tag policy governance")
    console.print("- [cyan]bluearch-aws-core start --daemon[/cyan]   # Open local dashboards\n")

    console.print("For detailed command help: [cyan]bluearch-aws-tags discover [COMMAND] --help[/cyan]")


@discover_app.callback(invoke_without_command=True)
def discover_callback(
    ctx: typer.Context,
    services: Optional[str] = typer.Option("all", "--services", "-s", help="Services to discover (ec2,s3,lambda,all)"),
    regions: Optional[str] = typer.Option(None, "--regions", "-r", help="Regions to scan (default: US regions; use 'all' for all enabled regions)"),
    force: bool = typer.Option(False, "--force", "-f", help="Force fresh discovery, ignore cache"),
    multi_account: bool = typer.Option(False, "--multi-account", help="Discover resources across all enabled accounts"),
    single_account: bool = typer.Option(False, "--single-account", help="Force single account mode (scan only current account)"),
    accounts: Optional[str] = typer.Option(None, "--accounts", help="Specific account IDs to discover (comma-separated)"),
    help: bool = typer.Option(False, "--help", "-h", help="Show this message and exit")
):
    """
    Discover AWS resources across the default US regions concurrently.

    This is the foundational step for tag management. Run this command to scan your
    AWS environment and build a local inventory. By DEFAULT, scans US regions
    for faster feedback. Use --regions all when you need full global coverage.

    MULTI-ACCOUNT BEHAVIOR:
    - Automatically scans all enabled accounts when accounts are configured
    - Use --single-account to force scanning only the current account
    - Use --accounts to specify specific account IDs

    Examples:
        discover                           # Scan enabled accounts in US regions
        discover --single-account          # Force scan current account only
        discover ec2                       # Only EC2 in all enabled accounts
        discover lambda --regions us-east-1,eu-west-1  # Specific service and regions
        discover --accounts 123456789012,234567890123  # Specific accounts only
        discover --regions all             # Scan all enabled regions
        discover --force                   # Force fresh scan, ignore cache

    Service Options:
        all      - Discover all supported services (EC2, S3, Lambda)
        ec2      - EC2 instances only
        s3       - S3 buckets only
        lambda   - Lambda functions only

    You can also combine services:
        discover ec2,s3                    # Just EC2 and S3

    Display Format (tree-like structure):
        ec2/
        ├─ us-east-1/ OK (5 resources)
        ├─ us-west-2/ OK (2 resources)
        └─ eu-west-1/ OK (0 resources)
        s3/
        └─ global/ OK (10 buckets)

    Performance:
        - Runs up to 10 discoveries concurrently
        - Real-time tree updates as regions complete
        - Default scan: 4 US regions × selected services for faster feedback
        - Regions complete in any order, tree updates live
    """
    # Bare `discover` is help-only and deliberately succeeds without a scan.
    if not ctx.invoked_subcommand and services == "all" and regions is None and not force and not multi_account and not single_account and not accounts:
        typer.echo(ctx.get_help())
        typer.echo("Run bluearch-aws-tags discover all to scan your AWS resources.")
        return
    if help:
        show_discover_help()
        raise typer.Exit()

    # If a subcommand is invoked, don't run default
    if ctx.invoked_subcommand is not None:
        return

    # Default behavior: discover with options
    discover_resources_internal(services, regions, force, multi_account, single_account, accounts)


@discover_app.command("all")
@require_aws_credentials
@handle_all_errors
def discover_all(
    regions: Optional[str] = typer.Option(None, "--regions", "-r", help="Regions to scan (default: all)"),
    force: bool = typer.Option(False, "--force", "-f", help="Force fresh discovery"),
    multi_account: bool = typer.Option(False, "--multi-account", help="Discover across all enabled accounts"),
    single_account: bool = typer.Option(False, "--single-account", help="Force single account mode"),
    accounts: Optional[str] = typer.Option(None, "--accounts", help="Specific account IDs (comma-separated)")
):
    """Discover ALL services in all regions (EC2, S3, Lambda)."""
    discover_resources_internal("all", regions, force, multi_account, single_account, accounts)


@discover_app.command("ec2")
@require_aws_credentials
@handle_all_errors
def discover_ec2(
    regions: Optional[str] = typer.Option(None, "--regions", "-r", help="Regions to scan (default: all)"),
    force: bool = typer.Option(False, "--force", "-f", help="Force fresh discovery"),
    multi_account: bool = typer.Option(False, "--multi-account", help="Discover across all enabled accounts"),
    single_account: bool = typer.Option(False, "--single-account", help="Force single account mode"),
    accounts: Optional[str] = typer.Option(None, "--accounts", help="Specific account IDs (comma-separated)")
):
    """Discover EC2 instances across regions."""
    discover_resources_internal("ec2", regions, force, multi_account, single_account, accounts)


@discover_app.command("s3")
@require_aws_credentials
@handle_all_errors
def discover_s3(
    force: bool = typer.Option(False, "--force", "-f", help="Force fresh discovery"),
    multi_account: bool = typer.Option(False, "--multi-account", help="Discover across all enabled accounts"),
    single_account: bool = typer.Option(False, "--single-account", help="Force single account mode"),
    accounts: Optional[str] = typer.Option(None, "--accounts", help="Specific account IDs (comma-separated)")
):
    """Discover S3 buckets (global service)."""
    discover_resources_internal("s3", None, force, multi_account, single_account, accounts)


@discover_app.command("lambda")
@require_aws_credentials
@handle_all_errors
def discover_lambda(
    regions: Optional[str] = typer.Option(None, "--regions", "-r", help="Regions to scan (default: all)"),
    force: bool = typer.Option(False, "--force", "-f", help="Force fresh discovery"),
    multi_account: bool = typer.Option(False, "--multi-account", help="Discover across all enabled accounts"),
    single_account: bool = typer.Option(False, "--single-account", help="Force single account mode"),
    accounts: Optional[str] = typer.Option(None, "--accounts", help="Specific account IDs (comma-separated)")
):
    """Discover Lambda functions across regions."""
    discover_resources_internal("lambda", regions, force, multi_account, single_account, accounts)


@require_aws_credentials
@handle_all_errors
def discover_resources_internal(services: str, regions: Optional[str], force: bool, multi_account: bool = False, single_account: bool = False, accounts: Optional[str] = None):
    """Internal function to perform resource discovery."""

    # Check if we should do multi-account discovery by default
    from ..modules.multi_account_discovery import multi_account_discovery

    # Check if there are enabled accounts (unless explicitly doing single account)
    should_do_multi_account = multi_account or accounts is not None

    # If single_account is explicitly set, override multi-account behavior
    if single_account:
        should_do_multi_account = False
        console.print("[cyan]Running in single-account mode (current account only).[/cyan]\n")
    elif not should_do_multi_account:
        # Check if any accounts are enabled - if so, default to multi-account
        enabled_accounts = multi_account_discovery.get_enabled_accounts()
        if enabled_accounts:
            console.print("[cyan]Found enabled accounts. Performing multi-account discovery.[/cyan]")
            console.print("[dim]Use --single-account flag to scan only current account.[/dim]\n")
            should_do_multi_account = True

    # Handle multi-account discovery
    if should_do_multi_account:
        # Check if StackSet is deployed for cross-account access through core.
        try:
            from ..utils.core_client import request_core
            from rich.prompt import Confirm

            stackset_status = request_core("GET", "/api/v1/accounts/status", timeout=10.0)
            exists = bool(stackset_status.get("exists"))
            status = stackset_status.get("status")
            status_reason = stackset_status.get("status_reason")

            if not exists:
                console.print("[yellow]Cross-account StackSet not found.[/yellow]")
                console.print("[dim]Cross-account infrastructure is required for multi-account discovery.[/dim]\n")
                console.print("To deploy the StackSet, run:")
                console.print("  [cyan]bluearch-aws-tags setup multi-account[/cyan]\n")

                if not Confirm.ask("Continue with single-account discovery instead?", default=True):
                    console.print("[yellow]Discovery cancelled.[/yellow]")
                    raise typer.Exit(0)  # Exit cleanly - stops calling command too

                # Fall through to single-account discovery
                should_do_multi_account = False
                console.print("[cyan]Running in single-account mode.[/cyan]\n")

            elif status == 'FAILED':
                console.print(f"[yellow]Cross-account StackSet has issues: {status_reason}[/yellow]")
                console.print("Some accounts may fail. To fix, run:")
                console.print("  [cyan]bluearch-aws-tags setup multi-account --update[/cyan]\n")

        except typer.Exit:
            # User cancelled - propagate exit
            raise
        except Exception as e:
            # If we can't check StackSet status, continue anyway
            pass  # StackSet check is optional, don't block on errors

    if should_do_multi_account:
        # Parse account IDs if provided
        account_list = None
        if accounts:
            account_list = [a.strip() for a in accounts.split(",")]

        # Parse services and filter by implemented collectors.
        allowed = dict(COLLECTORS)

        if services == 'all':
            service_list = ['ec2', 's3', 'lambda', 'rds', 'dynamodb', 'ecs', 'elb']
        else:
            service_list = [s.strip().lower() for s in services.split(',')]
        service_list = [s for s in service_list if s in allowed]

        # Parse regions
        if regions and regions.lower() == 'all':
            # User explicitly wants all enabled regions
            region_list = None
        elif regions and regions.lower() != 'all':
            # User specified specific regions
            region_list = [r.strip() for r in regions.split(',')]
        else:
            # Default: US regions for faster discovery
            region_list = ['us-east-1', 'us-east-2', 'us-west-1', 'us-west-2']

        # Run multi-account discovery
        result = multi_account_discovery.discover_all_accounts(
            account_ids=account_list,
            services=service_list,
            regions=region_list,
            show_progress=True,
            save_to_database=True
        )

        # Show task tracking
        from ..utils.task_tracker import task_tracker
        task_tracker.record_task_execution("resource_discovery", success=True)

        return

    # Original single-account discovery
    from ..modules.discovery import discover_all_resources_v2
    allowed = dict(COLLECTORS)

    # Parse services and filter by implemented collectors.
    if services == "all":
        service_list = ['ec2', 's3', 'lambda', 'rds', 'dynamodb', 'ecs', 'elb']
    else:
        service_list = [s.strip() for s in services.split(',') if s.strip()]
    service_list = [s for s in service_list if s in allowed]

    # Parse regions - default to US AWS regions for speed
    if regions and regions.lower() == 'all':
        # User explicitly wants all enabled regions
        try:
            ec2_client = aws_auth.get_client('ec2', region='us-east-1')
            response = ec2_client.describe_regions(
                Filters=[{"Name": "opt-in-status", "Values": ["opt-in-not-required", "opted-in"]}]
            )
            region_list = [r['RegionName'] for r in response['Regions']]
            console.print(f"[dim]Scanning all {len(region_list)} enabled AWS regions[/dim]")
        except Exception as e:
            console.print(f"[yellow]Could not fetch all regions, using US regions: {e}[/yellow]")
            region_list = ['us-east-1', 'us-east-2', 'us-west-1', 'us-west-2']
    elif regions and regions.lower() != 'all':
        # User specified specific regions
        region_list = [r.strip() for r in regions.split(',') if r.strip()]
    else:
        region_list = ['us-east-1', 'us-east-2', 'us-west-1', 'us-west-2']

    # Clear cache if force flag is set
    if force:
        from ..utils.cache import cache
        for service in service_list:
            cache.invalidate_service_cache(service)
        console.print("[yellow]Cache cleared, forcing fresh discovery...[/yellow]\n")

    summary = discover_all_resources_v2(service_list, region_list, console)

    # Show summary
    console.print()
    if summary['total_resources_discovered'] > 0:
        safe_print(f"OK Discovered {summary['total_resources_discovered']} resources!", "green")
    else:
        safe_print("WARN No resources discovered", "yellow")

    console.print(f"Services scanned: {summary['services_scanned']}")
    console.print(f"Regions scanned: {summary['regions_scanned']}")
    console.print(f"Duration: {summary['duration_seconds']:.1f} seconds")

    # Show errors if any
    if summary['errors']:
        console.print(f"\n[yellow]Errors encountered ({len(summary['errors'])}):[/yellow]")
        for error in summary['errors'][:5]:  # Show first 5 errors
            console.print(f"  - {error}")
        if len(summary['errors']) > 5:
            console.print(f"  ... and {len(summary['errors']) - 5} more errors")

    # Check for permission errors and suggest setup validate
    permission_errors = summary.get('permission_errors', 0)
    if permission_errors > 0:
        skipped_types = summary.get('permission_error_resource_types') or []
        permission_details = summary.get('permission_error_details') or []
        console.print("\n" + "="*60)
        console.print("[bold yellow]ATTENTION Permission Issues Detected[/bold yellow]")
        console.print(f"\n[yellow]{permission_errors} permission error(s) were encountered during discovery.[/yellow]")
        console.print("Some AWS resources may not have been discovered due to missing IAM permissions.")
        if skipped_types:
            console.print("\n[yellow]Resource types not collected due to permissions:[/yellow]")
            for resource_type in skipped_types:
                console.print(f"  - {resource_type}")
        if permission_details:
            console.print("\n[yellow]Permission error details:[/yellow]")
            for detail in permission_details[:12]:
                account = detail.get('account_id') or 'unknown'
                region = detail.get('region') or 'global'
                service = detail.get('service') or 'unknown'
                code = detail.get('code') or 'AccessDenied'
                resource_types = ', '.join(detail.get('resource_types') or []) or 'unknown resource types'
                resource_name = detail.get('resource_name')
                suffix = f"; resource {resource_name}" if resource_name else ""
                console.print(f"  - {account} {service}/{region}: {code}; skipped {resource_types}{suffix}")
            remaining = len(permission_details) - 12
            if remaining > 0:
                console.print(f"  ... and {remaining} more permission error(s)")
        console.print("\n[bold cyan]Recommended Action:[/bold cyan]")
        console.print("Run the following command to check all required IAM permissions:")
        console.print("  [bold cyan]bluearch-aws-tags setup validate[/bold cyan]")
        console.print("\nThis will:")
        console.print("  - Show exactly which IAM permissions are missing")
        console.print("  - Provide a JSON policy to fix the permission issues")
        console.print("  - Tell you which commands won't work without these permissions")
        console.print("="*60)

    # Next steps
    console.print("\n[bold green]Next steps:[/bold green]")
    if permission_errors > 0:
        console.print("  [cyan]bluearch-aws-tags setup validate[/cyan] - Check and fix IAM permission issues")
    console.print("  [cyan]bluearch-aws-tags lifecycle wizard[/cyan] - Guided lifecycle and tagging workflow")
    console.print("  [cyan]bluearch-aws-core start --daemon[/cyan] - Open local dashboards")

    # Record task execution for tracking
    from ..utils.task_tracker import task_tracker
    task_tracker.record_task_execution("resource_discovery", success=True)
