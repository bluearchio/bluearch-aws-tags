"""AWS Organizations Tag Policy commands for Tag Manager CLI."""

import typer
import json
from typing import Optional
from rich.console import Console
from rich.panel import Panel
from rich.syntax import Syntax
from rich.prompt import Confirm, Prompt

from ..services.organizations_service import OrganizationsService
from ..utils.aws_auth import aws_auth

# Create Typer app for policy commands
app = typer.Typer(
    name="policy",
    help="AWS Organizations Tag Policy management - view, enable, and manage tag policies",
    no_args_is_help=False
)

console = Console()


def show_policy_help():
    """Show formatted help for policy command."""
    console.print("\n[bold cyan]AWS Organizations Tag Policy Management[/bold cyan] - Centralized tag governance\n")

    console.print("[bold green]DISCOVERY & ACCESS[/bold green] (start here):")
    console.print("- [cyan]check-access[/cyan]   - Check AWS Organizations access and permissions")
    console.print("- [cyan]view[/cyan]           - List all tag policies with full details")
    console.print("- [cyan]effective[/cyan]      - Show effective policy for current account\n")

    console.print("[bold yellow]POLICY MANAGEMENT[/bold yellow] (management account only):")
    console.print("- [cyan]enable[/cyan]         - Enable tag policies for the organization")
    console.print("- [cyan]disable[/cyan]        - Disable tag policies for the organization\n")

    console.print("[bold red]COMPLIANCE CHECKING[/bold red] (AWS API-based):")
    console.print("- [cyan]check-compliance[/cyan] - Check resource compliance against tag policies")
    console.print("  Options: --details, --account, --service, --region, --resource\n")

    console.print("[bold green]POLICY MANAGEMENT[/bold green] (Interactive & Direct):")
    console.print("- [cyan]wizard[/cyan]         - Unified wizard with interactive menu for all operations")
    console.print("- [cyan]create[/cyan]         - Create new policy using interactive builder")
    console.print("- [cyan]update[/cyan]         - Update existing policy (content and/or metadata)")
    console.print("- [cyan]delete[/cyan]         - Delete policy with safety confirmations")
    console.print("- [cyan]attach[/cyan]         - Attach policy to Root/OU/Account targets")
    console.print("- [cyan]detach[/cyan]         - Detach policy from targets\n")

    console.print("[bold magenta]COMING SOON[/bold magenta] (Phase 3):")
    console.print("- [dim]events[/dim]          - Configure EventBridge automation for policies\n")

    console.print("[bold green]QUICK START WORKFLOW[/bold green]:")
    console.print("1. [dim]policy check-access[/dim]                  # Verify AWS Organizations access")
    console.print("2. [dim]policy view[/dim]                         # Discover existing policies")
    console.print("3. [dim]policy create[/dim]                       # Create new policy (or use 'wizard')")
    console.print("4. [dim]policy attach --policy-id <id>[/dim]      # Attach policy to targets")
    console.print("5. [dim]policy effective[/dim]                    # Check what applies to you")
    console.print("6. [dim]policy check-compliance[/dim]             # Check compliance status\n")

    console.print("For detailed help on any command: [cyan]policy [COMMAND] --help[/cyan]")


@app.callback(invoke_without_command=True)
def policy_main(
    ctx: typer.Context,
    help: bool = typer.Option(False, "--help", "-h", help="Show this message and exit.")
):
    """
    AWS Organizations Tag Policy management - view, enable, and manage tag policies.

    This command provides comprehensive integration with AWS Organizations Tag Policies,
    enabling discovery, management, and governance of tag policies across multi-account
    AWS environments.
    """
    if help or ctx.invoked_subcommand is None:
        show_policy_help()
        if help:
            raise typer.Exit()


# === ACCESS & DISCOVERY COMMANDS ===

@app.command("check-access")
def check_access(
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Show additional details")
):
    """
    Check AWS Organizations access and tag policy status.

    This command verifies:
    - Access to AWS Organizations
    - Current account vs management account
    - Tag policies enabled/disabled status
    - Available policy types
    """
    try:
        # Initialize the service with AWS session
        session = aws_auth.initialize_session()
        service = OrganizationsService(session)

        console.print("[cyan]Checking AWS Organizations access...[/cyan]")
        result = service.check_access()

        if result['has_access']:
            console.print("[green]OK AWS Organizations access verified![/green]\n")

            # Display access information
            info = [
                f"Organization ID:      {result.get('org_id', 'N/A')}",
                f"Master Account:       {result.get('master_account', 'N/A')}",
                f"Current Account:      {result.get('current_account', 'N/A')}",
                f"Tag Policies Enabled: {'Yes' if result.get('tag_policies_enabled') else 'No'}",
                f"Active Policies:      {result.get('policies_count', 0)}",
                f"Feature Set:          {result.get('feature_set', 'N/A')}",
            ]

            panel = Panel(
                "\n".join(info),
                title="AWS Organizations Status",
                border_style="green"
            )
            console.print(panel)

            if verbose and result.get('available_policy_types'):
                console.print("\n[dim]Available policy types:[/dim]")
                for policy_type in result['available_policy_types']:
                    console.print(f"  - {policy_type}")

            if not result.get('tag_policies_enabled'):
                console.print("\n[yellow]Note: Tag policies are not enabled in your organization.[/yellow]")

                # Check if current account is the master account
                is_master = result.get('current_account') == result.get('master_account')

                if is_master:
                    console.print("\n[bold cyan]You are currently signed in as the master account.[/bold cyan]")
                    console.print("Tag policies allow you to:")
                    console.print("  • Define standardized tags across your organization")
                    console.print("  • Enforce tag compliance on resources")
                    console.print("  • Improve cost allocation and resource management")
                    console.print("  • Maintain consistent tagging strategies")

                    console.print("\n[dim]To enable tag policies, run:[/dim] [cyan]policy enable[/cyan]")
                else:
                    console.print("\n[yellow]You are not signed in as the master account.[/yellow]")
                    console.print(f"Current account: [cyan]{result.get('current_account')}[/cyan]")
                    console.print(f"Master account:  [cyan]{result.get('master_account')}[/cyan]")
                    console.print("\nTo enable tag policies:")
                    console.print("  1. Sign in as the master account ({})".format(result.get('master_account')))
                    console.print("  2. Run [cyan]policy enable[/cyan]")

        else:
            console.print(f"[red]ERROR AWS Organizations not accessible[/red]\n")
            console.print(f"Error: {result.get('error', 'Unknown error')}")

            if result.get('current_account'):
                console.print(f"\nCurrent account: {result['current_account']}")

            if result.get('required_permissions'):
                console.print("\nRequired IAM permissions:")
                for perm in result['required_permissions']:
                    console.print(f"  - {perm}")

            console.print("\nSolutions:")
            console.print("  1. Ensure your AWS account is part of an AWS Organization")
            console.print("  2. Request the required permissions from your administrator")
            console.print("  3. Use --profile to switch to a profile with appropriate permissions")

    except Exception as e:
        console.print(f"[red]Unexpected error: {str(e)}[/red]")
        raise typer.Exit(1)


@app.command("view")
def view_policies(
    policy_id: Optional[str] = typer.Option(None, "--policy-id", help="View specific policy by ID"),
    format: str = typer.Option("table", "--format", "-f", help="Output format: table, json, or yaml"),
    raw: bool = typer.Option(False, "--raw", help="Show raw JSON output"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Show additional details")
):
    """
    View tag policies in the organization.

    Without --policy-id: Lists all tag policies with details
    With --policy-id: Shows specific policy with full content
    """
    try:
        # Initialize the service with AWS session
        session = aws_auth.initialize_session()
        service = OrganizationsService(session)

        if policy_id:
            # View specific policy
            console.print(f"[cyan]Getting policy details for {policy_id}...[/cyan]")
            policy = service.get_policy_details(policy_id)

            if 'error' in policy:
                console.print(f"[red]Error: {policy['error']}[/red]")
                return

            # Display policy details
            console.print(f"\n[bold]Policy: {policy.get('name', 'N/A')}[/bold]")
            console.print(f"ID: {policy.get('id', 'N/A')}")
            console.print(f"Type: {policy.get('type', 'N/A')}")
            console.print(f"AWS Managed: {'Yes' if policy.get('aws_managed') else 'No'}")

            if policy.get('description'):
                console.print(f"Description: {policy['description']}")

            if policy.get('targets'):
                console.print(f"\n[bold]Targets ({len(policy['targets'])})[/bold]")
                for target in policy['targets'][:10]:  # Show first 10 targets
                    target_type = target.get('Type', 'UNKNOWN')
                    target_id = target.get('TargetId', 'N/A')
                    target_name = target.get('Name', '')
                    console.print(f"  - {target_type}: {target_id} {f'({target_name})' if target_name else ''}")
                if len(policy['targets']) > 10:
                    console.print(f"  ... and {len(policy['targets']) - 10} more")

            # Always show policy content if available
            if policy.get('content'):
                console.print(f"\n[bold]Policy Content:[/bold]")
                if raw or format == 'json':
                    console.print(json.dumps(policy['content'], indent=2))
                else:
                    formatted = service.format_policy_content(policy['content'])
                    syntax = Syntax(formatted, "yaml", theme="monokai", line_numbers=False)
                    console.print(syntax)

            if verbose:
                if policy.get('arn'):
                    console.print(f"\n[dim]ARN: {policy['arn']}[/dim]")
                if policy.get('create_date'):
                    console.print(f"[dim]Created: {policy['create_date']}[/dim]")
                if policy.get('update_date'):
                    console.print(f"[dim]Updated: {policy['update_date']}[/dim]")

        else:
            # List all policies
            console.print("[cyan]Discovering tag policies in the organization...[/cyan]")
            # Always get detailed information for policies
            policies = service.list_policies(detailed=True)

            if not policies:
                console.print("[yellow]No tag policies found in the organization[/yellow]")
                console.print("\nThis could mean:")
                console.print("  1. Tag policies are not enabled")
                console.print("  2. No policies have been created yet")
                console.print("  3. You don't have permission to list policies")
                console.print("\nRun [cyan]policy check-access[/cyan] to verify your permissions")
                return

            if raw or format == 'json':
                console.print(json.dumps(policies, indent=2, default=str))
            elif format == 'yaml':
                # Simple YAML-like output
                for policy in policies:
                    console.print(f"- id: {policy.get('id', 'N/A')}")
                    console.print(f"  name: {policy.get('name', 'N/A')}")
                    console.print(f"  type: {policy.get('type', 'TAG_POLICY')}")
                    console.print(f"  aws_managed: {policy.get('aws_managed', False)}")
                    if policy.get('description'):
                        console.print(f"  description: {policy['description']}")
                    if 'target_count' in policy:
                        console.print(f"  target_count: {policy['target_count']}")
                    console.print()
            else:
                # Table output (default)
                service.display_policies_table(policies)

                if verbose:
                    # Show summary statistics
                    aws_managed_count = sum(1 for p in policies if p.get('aws_managed'))
                    custom_count = len(policies) - aws_managed_count
                    console.print(f"\n[dim]AWS Managed: {aws_managed_count}, Custom: {custom_count}[/dim]")

    except Exception as e:
        console.print(f"[red]Unexpected error: {str(e)}[/red]")
        raise typer.Exit(1)


@app.command("effective")
def show_effective_policy(
    target_id: Optional[str] = typer.Option(None, "--target-id", help="Target account/OU ID (default: current account)"),
    format: str = typer.Option("table", "--format", "-f", help="Output format: table or json"),
    raw: bool = typer.Option(False, "--raw", help="Show raw JSON output"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Show additional details")
):
    """
    Show effective tag policy for an account.

    The effective policy is the merged result of all tag policies
    that apply to the account through the organization hierarchy.
    """
    try:
        # Initialize the service with AWS session
        session = aws_auth.initialize_session()
        service = OrganizationsService(session)

        console.print("[cyan]Getting effective tag policy...[/cyan]")
        result = service.get_effective_policy(target_id)

        if 'error' in result:
            console.print(f"[red]Error: {result['error']}[/red]")
            return

        console.print(f"\n[bold]Effective Policy for Account: {result.get('target_id', 'N/A')}[/bold]")

        if raw or format == 'json':
            console.print(json.dumps(result['content'], indent=2))
        else:
            formatted = service.format_policy_content(result.get('content', {}))
            syntax = Syntax(formatted, "yaml", theme="monokai", line_numbers=False)
            console.print(syntax)

        if verbose:
            console.print(f"\n[dim]Last updated: {result.get('last_updated', 'N/A')}[/dim]")

    except Exception as e:
        console.print(f"[red]Unexpected error: {str(e)}[/red]")
        raise typer.Exit(1)


# === MANAGEMENT COMMANDS ===

@app.command("enable")
def enable_tag_policies():
    """
    Enable tag policies for the organization (management account only).

    This command:
    - Enables tag policy feature for the entire organization
    - Requires management account privileges
    - Affects all member accounts
    """
    try:
        # Initialize the service with AWS session
        session = aws_auth.initialize_session()
        service = OrganizationsService(session)

        console.print("\n[bold]Enable Tag Policies[/bold]")
        console.print("[cyan]Checking organization status...[/cyan]")

        # Check if we're running from master account
        org_info = service.check_access()

        if not org_info["has_access"]:
            console.print("[red]ERROR AWS Organizations access is not available[/red]")
            return

        # Check if already enabled BEFORE showing any warnings
        if org_info.get("tag_policies_enabled", False):
            console.print("\n[yellow]Tag policies are already enabled for this organization[/yellow]")
            console.print("\nCurrent status:")
            console.print(f"  Organization ID: {org_info.get('org_id', 'Unknown')}")
            console.print(f"  Active policies: {org_info.get('policies_count', 0)}")
            console.print("\nYou can:")
            console.print("  - View existing policies: [cyan]policy view[/cyan]")
            console.print("  - Check effective policies: [cyan]policy effective[/cyan]")
            return

        if org_info.get('current_account') != org_info.get('master_account'):
            console.print("[red]ERROR Tag policies can only be enabled from the management account[/red]")
            console.print(f"Current account: {org_info.get('current_account', 'Unknown')}")
            console.print(f"Management account: {org_info.get('master_account', 'Unknown')}")
            console.print("\n[yellow]AWS Requirement:[/yellow]")
            console.print("Tag policies can ONLY be enabled from:")
            console.print("  • The organization's management account (master), OR")
            console.print("  • A member account that is a delegated administrator")
            console.print("\nSwitch to the management account and try again.")
            return

        # Show warnings and get confirmation
        console.print("\n[yellow]WARNING You are about to enable tag policies for the entire organization[/yellow]")
        console.print("\nThis action will:")
        console.print("  - Enable tag policy enforcement across all member accounts")
        console.print("  - Allow creation and attachment of tag policies")
        console.print("  - May affect existing tagging workflows")
        console.print("\nThis is an organization-wide change that affects all member accounts.")

        confirm1 = Confirm.ask(
            "\n[bold]Do you want to proceed with enabling tag policies?[/bold]",
            default=False
        )
        if not confirm1:
            console.print("[yellow]Operation cancelled[/yellow]")
            return

        # Second confirmation
        confirm2 = Confirm.ask(
            "[bold]Are you ABSOLUTELY SURE you want to enable tag policies for the entire organization?[/bold]",
            default=False
        )
        if not confirm2:
            console.print("[yellow]Operation cancelled[/yellow]")
            return

        # Enable tag policies
        console.print("\n[cyan]Enabling tag policies for the organization...[/cyan]")
        result = service.enable_tag_policies()

        if result.get('already_enabled'):
            console.print(f"[yellow]{result['message']}[/yellow]")
            console.print("\nTag policies are already active. You can:")
            console.print("  - View existing policies: [cyan]policy view[/cyan]")
            console.print("  - Check effective policies: [cyan]policy effective[/cyan]")
        elif result["success"]:
            console.print("[green]OK Tag policies have been successfully enabled![/green]")
            console.print(f"Organization ID: {org_info.get('org_id', 'Unknown')}")

            if result.get('service_access_enabled'):
                console.print("[green]OK Tag policies service access also enabled for compliance checking[/green]")

            console.print("\nYou can now:")
            console.print("  - Create tag policies using AWS Console or CLI")
            console.print("  - View existing policies using: [cyan]policy view[/cyan]")
            console.print("  - Check effective policies using: [cyan]policy effective[/cyan]")
            console.print("  - Check compliance using: [cyan]policy check-compliance[/cyan]")
        else:
            console.print(f"[red]ERROR Failed to enable tag policies: {result.get('error', result.get('message', 'Unknown error'))}[/red]")

    except Exception as e:
        console.print(f"[red]Unexpected error: {str(e)}[/red]")
        raise typer.Exit(1)


@app.command("disable")
def disable_tag_policies():
    """
    Disable tag policies for the organization (management account only).

    WARNING: This is a destructive operation that will:
    - Disable all tag policy enforcement
    - Detach all existing tag policies
    - Delete all existing tag policies
    """
    try:
        # Initialize the service with AWS session
        session = aws_auth.initialize_session()
        service = OrganizationsService(session)

        console.print("\n[bold]Disable Tag Policies[/bold]")
        console.print("[cyan]Checking organization status...[/cyan]")

        # Check if we're running from master account
        org_info = service.check_access()

        if not org_info["has_access"]:
            console.print("[red]ERROR AWS Organizations access is not available[/red]")
            return

        # Check if already disabled BEFORE showing any warnings
        if not org_info.get("tag_policies_enabled", False):
            console.print("\n[yellow]Tag policies are already disabled for this organization[/yellow]")
            console.print("\nCurrent status:")
            console.print(f"  Organization ID: {org_info.get('org_id', 'Unknown')}")
            console.print("\nTag policies are not enabled. To enable them:")
            console.print("  - Run: [cyan]policy enable[/cyan]")
            return

        if org_info.get('current_account') != org_info.get('master_account'):
            console.print("[red]ERROR Tag policies can only be disabled from the management account[/red]")
            console.print(f"Current account: {org_info.get('current_account', 'Unknown')}")
            console.print(f"Management account: {org_info.get('master_account', 'Unknown')}")
            console.print("\n[yellow]AWS Requirement:[/yellow]")
            console.print("Tag policies can ONLY be disabled from:")
            console.print("  • The organization's management account (master), OR")
            console.print("  • A member account that is a delegated administrator")
            console.print("\nSwitch to the management account and try again.")
            return

        # Show warnings and get confirmation
        console.print("\n[red]WARNING You are about to DISABLE tag policies for the entire organization[/red]")
        console.print("\nThis action will:")
        console.print("  - [red]Disable all tag policy enforcement across all member accounts[/red]")
        console.print("  - [red]Detach all existing tag policies from OUs and accounts[/red]")
        console.print("  - [red]Delete all existing tag policies[/red]")
        console.print("  - [yellow]This is a DESTRUCTIVE operation that cannot be easily undone[/yellow]")
        console.print("\n[yellow]WARNING: This will remove ALL tag governance from your organization![/yellow]")

        # Use Rich's Confirm for consistency with other prompts
        confirm1 = Confirm.ask(
            "\n[bold]Do you want to proceed with DISABLING tag policies?[/bold]",
            default=False
        )

        if not confirm1:
            console.print("[yellow]Operation cancelled[/yellow]")
            return

        # Second confirmation with explicit typing
        console.print("\n[red]FINAL WARNING: This will DELETE all tag policies and remove all tag governance![/red]")
        console.print("Type 'DISABLE TAG POLICIES' to confirm (case-sensitive):")
        confirmation_text = Prompt.ask("Confirmation", default="")

        if confirmation_text != "DISABLE TAG POLICIES":
            console.print("[yellow]Operation cancelled - confirmation text did not match[/yellow]")
            return

        # Disable tag policies
        console.print("\n[cyan]Disabling tag policies for the organization...[/cyan]")
        result = service.disable_tag_policies()

        if result.get('already_disabled'):
            console.print(f"[yellow]{result['message']}[/yellow]")
        elif result["success"]:
            console.print("[green]OK Tag policies have been successfully disabled[/green]")
            console.print(f"Organization ID: {org_info.get('org_id', 'Unknown')}")
            console.print("\n[yellow]Note:[/yellow] All tag policies have been removed from the organization")
        else:
            console.print(f"[red]ERROR Failed to disable tag policies: {result.get('error', result.get('message', 'Unknown error'))}[/red]")

    except Exception as e:
        console.print(f"[red]Unexpected error: {str(e)}[/red]")
        raise typer.Exit(1)


# === COMPLIANCE CHECKING COMMANDS ===

@app.command("check-compliance")
def check_compliance(
    account: Optional[str] = typer.Option(None, "--account", help="Filter by specific account ID"),
    resource: Optional[str] = typer.Option(None, "--resource", help="Check specific resource ARN"),
    service: Optional[str] = typer.Option(None, "--service", help="Filter by service type (e.g., ec2, s3)"),
    region: Optional[str] = typer.Option(None, "--region", help="Filter by AWS region"),
    details: bool = typer.Option(False, "--details", help="Show detailed noncompliant resources"),
    limit: int = typer.Option(100, "--limit", help="Maximum number of resources to return"),
    format: str = typer.Option("table", "--format", "-f", help="Output format: table or json"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Show additional details")
):
    """
    Check tag policy compliance for resources in the organization.

    This command uses AWS's native GetComplianceSummary and GetResources APIs
    to check which resources are noncompliant with your tag policies.

    Note:
    - Must be called from management account in us-east-1 region
    - Compliance data is evaluated every 48 hours (not real-time)
    - Use --details to see specific noncompliant resources
    """
    try:
        # Initialize the service with AWS session
        session = aws_auth.initialize_session()
        org_service = OrganizationsService(session)

        # Check if checking specific resource
        if resource:
            console.print(f"[cyan]Checking compliance for resource: {resource}...[/cyan]")
            result = org_service.check_resource_compliance(resource)

            if not result.get('success'):
                console.print(f"[red]Error: {result.get('error')}[/red]")
                if result.get('suggestion'):
                    console.print(f"[yellow]{result['suggestion']}[/yellow]")
                return

            # Display resource compliance status
            console.print(f"\n[bold]Resource Compliance Check[/bold]")
            console.print(f"ARN: {result.get('arn', 'N/A')}")

            if result.get('is_compliant'):
                console.print("[green]Status: COMPLIANT[/green]")
                console.print("\nThis resource is compliant with all tag policies.")
            else:
                console.print("[red]Status: NONCOMPLIANT[/red]")

                if result.get('noncompliant_keys'):
                    console.print(f"\n[red]Missing required tags:[/red]")
                    for key in result['noncompliant_keys']:
                        console.print(f"  - {key}")

                if result.get('keys_with_noncompliant_values'):
                    console.print(f"\n[red]Tags with invalid values:[/red]")
                    for key in result['keys_with_noncompliant_values']:
                        console.print(f"  - {key}")

            if verbose and result.get('tags'):
                console.print(f"\n[dim]Current tags:[/dim]")
                for tag in result['tags']:
                    console.print(f"  {tag.get('Key', 'N/A')}: {tag.get('Value', 'N/A')}")

            return

        # Build filters
        target_ids = [account] if account else None
        region_filters = [region] if region else None

        # Convert service shorthand to resource type filter
        resource_type_filters = None
        if service:
            # Map common service names to resource type patterns
            service_map = {
                'ec2': ['ec2:instance', 'ec2:volume', 'ec2:snapshot'],
                's3': ['s3:bucket'],
                'rds': ['rds:db'],
                'lambda': ['lambda:function'],
                'dynamodb': ['dynamodb:table'],
            }
            resource_type_filters = service_map.get(service.lower(), [f'{service}:*'])

        if details:
            # Get detailed noncompliant resources
            console.print("[cyan]Fetching noncompliant resources...[/cyan]")
            console.print("[dim]Note: This may take a moment for large organizations[/dim]\n")

            result = org_service.get_noncompliant_resources(
                resource_type_filters=resource_type_filters,
                region_filters=region_filters,
                max_results=limit
            )

            if format == 'json':
                console.print(json.dumps(result, indent=2, default=str))
            else:
                org_service.display_noncompliant_resources(result)

        else:
            # Get compliance summary
            console.print("[cyan]Fetching compliance summary...[/cyan]")
            console.print("[dim]Note: Compliance data is evaluated every 48 hours[/dim]\n")

            result = org_service.get_compliance_summary(
                target_ids=target_ids,
                region_filters=region_filters,
                resource_type_filters=resource_type_filters
            )

            if format == 'json':
                console.print(json.dumps(result, indent=2, default=str))
            else:
                org_service.display_compliance_summary(result, verbose=verbose)

                if verbose and result.get('success'):
                    console.print("\n[dim]Tips:[/dim]")
                    console.print("  - Use --details to see specific noncompliant resources")
                    console.print("  - Use --service ec2 to filter by service type")
                    console.print("  - Use --region us-east-1 to filter by region")
                    console.print("  - Use --account 123456789012 to check specific account")

    except Exception as e:
        console.print(f"[red]Unexpected error: {str(e)}[/red]")
        raise typer.Exit(1)


# === POLICY CREATION COMMANDS ===

@app.command("wizard")
def policy_wizard(
    operation: Optional[str] = typer.Option(None, "--operation", "-op", help="Direct operation: create, update, delete, attach, detach"),
    policy_id: Optional[str] = typer.Option(None, "--policy-id", help="Policy ID (for update/delete/attach/detach operations)")
):
    """
    Interactive wizard for managing tag policies.

    This unified wizard provides menu-driven access to all policy operations:
    - Create new policies
    - Update existing policies
    - Delete policies
    - Attach/detach policies to targets

    Features:
    - Step-by-step guidance
    - All inheritance operators
    - Child control operators
    - Resource type suggestions
    - Real-time validation
    - Safety confirmations
    """
    from ..services.policy_builder_service import PolicyBuilder
    from rich.table import Table

    # Initialize AWS service with error handling
    try:
        session = aws_auth.initialize_session()
        org_service = OrganizationsService(session)
    except Exception as e:
        console.print(f"[red]ERROR Failed to authenticate with AWS[/red]")
        console.print(f"\n{str(e)}\n")

        # Check if it's an SSO token expiration
        if "Token has expired" in str(e) or "sso" in str(e).lower():
            console.print("[yellow]Your AWS SSO session has expired.[/yellow]")

            # Get the profile name for the error message
            import os
            profile = os.environ.get('AWS_PROFILE', 'default')

            console.print("\nTo fix this, run:")
            console.print(f"  [cyan]aws sso login --profile {profile}[/cyan]")
        else:
            console.print("[yellow]Please check your AWS credentials and try again.[/yellow]")

        raise typer.Exit(1)

    # Show main menu if no operation specified
    if operation is None:
        while True:
            console.print("\n[bold cyan]╭─────────────────────────────────────────────────╮[/bold cyan]")
            console.print("[bold cyan]│   AWS Organizations Tag Policy Wizard          │[/bold cyan]")
            console.print("[bold cyan]╰─────────────────────────────────────────────────╯[/bold cyan]\n")

            console.print("[bold green]What would you like to do?[/bold green]\n")
            console.print("[cyan][1][/cyan] Create new policy")
            console.print("    [dim]Build a new tag policy from scratch[/dim]")
            console.print("[cyan][2][/cyan] Update existing policy")
            console.print("    [dim]Modify an existing tag policy[/dim]")
            console.print("[cyan][3][/cyan] Delete policy")
            console.print("    [dim]Remove a tag policy from the organization[/dim]")
            console.print("[cyan][4][/cyan] Attach policy")
            console.print("    [dim]Attach policy to root/OU/account[/dim]")
            console.print("[cyan][5][/cyan] Detach policy")
            console.print("    [dim]Remove policy from target[/dim]")
            console.print("[cyan][Q][/cyan] Exit\n")

            choice = Prompt.ask("Choice", choices=["1", "2", "3", "4", "5", "q", "Q"], default="1")

            if choice.upper() == "Q":
                console.print("[yellow]Exiting wizard[/yellow]")
                return

            # Route to appropriate operation
            if choice == "1":
                _wizard_create_policy(org_service)
            elif choice == "2":
                _wizard_update_policy(org_service)
            elif choice == "3":
                _wizard_delete_policy(org_service)
            elif choice == "4":
                _wizard_attach_policy(org_service)
            elif choice == "5":
                _wizard_detach_policy(org_service)

            # Ask if user wants to do another operation
            if not Confirm.ask("\n[cyan]Perform another operation?[/cyan]", default=True):
                console.print("[green]Thank you for using the policy wizard![/green]")
                return

    # Direct operation mode
    elif operation == "create":
        _wizard_create_policy(org_service)
    elif operation == "update":
        _wizard_update_policy(org_service, policy_id)
    elif operation == "delete":
        _wizard_delete_policy(org_service, policy_id)
    elif operation == "attach":
        _wizard_attach_policy(org_service, policy_id)
    elif operation == "detach":
        _wizard_detach_policy(org_service, policy_id)
    else:
        console.print(f"[red]Unknown operation: {operation}[/red]")
        console.print("Valid operations: create, update, delete, attach, detach")
        raise typer.Exit(1)


@app.command("create")
def create_policy():
    """
    Create a new tag policy interactively.

    Opens the interactive policy builder to create a new tag policy
    with full support for all operators and child controls.
    """
    try:
        session = aws_auth.initialize_session()
        org_service = OrganizationsService(session)
    except Exception as e:
        console.print(f"[red]ERROR Failed to authenticate with AWS[/red]")
        console.print(f"\n{str(e)}\n")
        if "Token has expired" in str(e) or "sso" in str(e).lower():
            console.print("[yellow]Your AWS SSO session has expired.[/yellow]")
            import os
            profile = os.environ.get('AWS_PROFILE', 'default')
            console.print("\nTo fix this, run:")
            console.print(f"  [cyan]aws sso login --profile {profile}[/cyan]")
        raise typer.Exit(1)

    _wizard_create_policy(org_service)


@app.command("update")
def update_policy(
    policy_id: Optional[str] = typer.Option(None, "--policy-id", "-p", help="Policy ID to update")
):
    """
    Update an existing tag policy.

    Allows you to update policy content, name, description, or both.
    Policy content is loaded into the interactive builder for editing.
    """
    try:
        session = aws_auth.initialize_session()
        org_service = OrganizationsService(session)
    except Exception as e:
        console.print(f"[red]ERROR Failed to authenticate with AWS[/red]")
        console.print(f"\n{str(e)}\n")
        if "Token has expired" in str(e) or "sso" in str(e).lower():
            console.print("[yellow]Your AWS SSO session has expired.[/yellow]")
            import os
            profile = os.environ.get('AWS_PROFILE', 'default')
            console.print("\nTo fix this, run:")
            console.print(f"  [cyan]aws sso login --profile {profile}[/cyan]")
        raise typer.Exit(1)

    _wizard_update_policy(org_service, policy_id)


@app.command("delete")
def delete_policy(
    policy_id: Optional[str] = typer.Option(None, "--policy-id", "-p", help="Policy ID to delete")
):
    """
    Delete a tag policy.

    Deletes a tag policy with safety confirmations. Automatically detaches
    the policy from all targets before deletion.
    """
    try:
        session = aws_auth.initialize_session()
        org_service = OrganizationsService(session)
    except Exception as e:
        console.print(f"[red]ERROR Failed to authenticate with AWS[/red]")
        console.print(f"\n{str(e)}\n")
        if "Token has expired" in str(e) or "sso" in str(e).lower():
            console.print("[yellow]Your AWS SSO session has expired.[/yellow]")
            import os
            profile = os.environ.get('AWS_PROFILE', 'default')
            console.print("\nTo fix this, run:")
            console.print(f"  [cyan]aws sso login --profile {profile}[/cyan]")
        raise typer.Exit(1)

    _wizard_delete_policy(org_service, policy_id)


@app.command("attach")
def attach_policy(
    policy_id: Optional[str] = typer.Option(None, "--policy-id", "-p", help="Policy ID to attach")
):
    """
    Attach a tag policy to targets.

    Attach a tag policy to organizational units, accounts, or the root.
    Supports multi-select for attaching to multiple targets at once.
    """
    try:
        session = aws_auth.initialize_session()
        org_service = OrganizationsService(session)
    except Exception as e:
        console.print(f"[red]ERROR Failed to authenticate with AWS[/red]")
        console.print(f"\n{str(e)}\n")
        if "Token has expired" in str(e) or "sso" in str(e).lower():
            console.print("[yellow]Your AWS SSO session has expired.[/yellow]")
            import os
            profile = os.environ.get('AWS_PROFILE', 'default')
            console.print("\nTo fix this, run:")
            console.print(f"  [cyan]aws sso login --profile {profile}[/cyan]")
        raise typer.Exit(1)

    _wizard_attach_policy(org_service, policy_id)


@app.command("detach")
def detach_policy(
    policy_id: Optional[str] = typer.Option(None, "--policy-id", "-p", help="Policy ID to detach")
):
    """
    Detach a tag policy from targets.

    Detach a tag policy from specific targets or all targets at once.
    Shows all current attachments for easy selection.
    """
    try:
        session = aws_auth.initialize_session()
        org_service = OrganizationsService(session)
    except Exception as e:
        console.print(f"[red]ERROR Failed to authenticate with AWS[/red]")
        console.print(f"\n{str(e)}\n")
        if "Token has expired" in str(e) or "sso" in str(e).lower():
            console.print("[yellow]Your AWS SSO session has expired.[/yellow]")
            import os
            profile = os.environ.get('AWS_PROFILE', 'default')
            console.print("\nTo fix this, run:")
            console.print(f"  [cyan]aws sso login --profile {profile}[/cyan]")
        raise typer.Exit(1)

    _wizard_detach_policy(org_service, policy_id)


# === WIZARD OPERATION FUNCTIONS ===

def _wizard_create_policy(org_service: OrganizationsService):
    """Create a new policy flow."""
    from ..services.policy_builder_service import PolicyBuilder

    console.print("\n[bold yellow]═══ Create New Policy ═══[/bold yellow]\n")
    try:
        # Run the interactive builder
        builder = PolicyBuilder()
        policy_data = builder.run_interactive_loop()

        if not policy_data:
            # User quit without saving
            console.print("[yellow]Policy creation cancelled[/yellow]")
            return

        # Show final preview
        console.print("\n[bold green]Policy Created Successfully![/bold green]")
        console.print("=" * 50)

        policy_json = json.dumps(policy_data['content'], indent=2)
        syntax = Syntax(policy_json, "json", theme="monokai", line_numbers=True)

        console.print(f"\n[bold]Policy: {policy_data['name']}[/bold]")
        console.print(f"[dim]{policy_data['description']}[/dim]\n")
        console.print(syntax)

        # Save to file if requested
        if Confirm.ask("\n[cyan]Save policy to file?[/cyan]", default=False):
            output_file = Prompt.ask(
                "[cyan]File path[/cyan]",
                default=f"./{policy_data['name'].replace(' ', '_')}.json"
            )

            try:
                with open(output_file, 'w') as f:
                    f.write(policy_json)
                console.print(f"[green]OK Saved to {output_file}[/green]")
            except Exception as e:
                console.print(f"[red]Failed to save file: {e}[/red]")

        # Create in AWS
        if Confirm.ask("\n[cyan]Create policy in AWS Organizations?[/cyan]", default=True):
            console.print("\n[cyan]Creating policy in AWS...[/cyan]")

            result = org_service.create_policy(
                name=policy_data['name'],
                description=policy_data['description'],
                content=policy_data['content']
            )

            if result['success']:
                policy_id = result['policy_id']
                console.print(f"[green]OK Policy created successfully![/green]")
                console.print(f"[cyan]Policy ID:[/cyan] {policy_id}")

                # Attach to targets if requested
                if Confirm.ask("\n[cyan]Attach policy to targets?[/cyan]", default=False):
                    _attach_to_targets(org_service, policy_id)

                console.print(f"\n[green]OK Policy deployment complete![/green]")
            else:
                console.print(f"[red]Failed to create policy: {result.get('error', 'Unknown error')}[/red]")
                if result.get('suggestion'):
                    console.print(f"[yellow]{result['suggestion']}[/yellow]")
        else:
            console.print("\n[yellow]Skipped AWS creation[/yellow]")

    except KeyboardInterrupt:
        console.print("\n[yellow]Operation cancelled by user[/yellow]")
    except Exception as e:
        console.print(f"[red]Unexpected error: {str(e)}[/red]")


def _wizard_update_policy(org_service: OrganizationsService, policy_id: Optional[str] = None):
    """Update an existing policy flow."""
    console.print("\n[bold yellow]═══ Update Policy ═══[/bold yellow]\n")

    try:
        # List policies if no policy_id provided
        if not policy_id:
            policies = org_service.list_policies(detailed=False)

            if not policies:
                console.print("[yellow]No policies found to update[/yellow]")
                return

            # Display policies
            console.print("[cyan]Available policies:[/cyan]\n")
            for idx, policy in enumerate(policies, 1):
                console.print(f"[cyan][{idx}][/cyan] {policy.get('name', 'N/A')}")
                console.print(f"    [dim]ID: {policy.get('id', 'N/A')}[/dim]")
                if policy.get('description'):
                    console.print(f"    [dim]{policy['description']}[/dim]")
                console.print()

            console.print("[cyan][B][/cyan] Back to main menu\n")

            choice = Prompt.ask("Select policy", default="B")

            if choice.upper() == "B":
                return

            if choice.isdigit():
                idx = int(choice) - 1
                if 0 <= idx < len(policies):
                    policy_id = policies[idx]['id']
                else:
                    console.print("[red]Invalid selection[/red]")
                    return
            else:
                console.print("[red]Invalid selection[/red]")
                return

        # Get current policy details
        policy = org_service.get_policy_details(policy_id)

        if 'error' in policy:
            console.print(f"[red]Error: {policy['error']}[/red]")
            return

        # Show current policy
        console.print(f"\n[bold]Current Policy: {policy.get('name', 'N/A')}[/bold]")
        console.print(f"[dim]{policy.get('description', 'N/A')}[/dim]\n")

        current_content = policy.get('content', {})
        formatted = org_service.format_policy_content(current_content)
        syntax = Syntax(formatted, "yaml", theme="monokai", line_numbers=False)
        console.print(syntax)

        # Update options
        console.print("\n[bold green]What would you like to update?[/bold green]\n")
        console.print("[cyan][1][/cyan] Policy content (use interactive builder)")
        console.print("[cyan][2][/cyan] Policy name and description")
        console.print("[cyan][3][/cyan] Both content and metadata")
        console.print("[cyan][B][/cyan] Back\n")

        update_choice = Prompt.ask("Choice", choices=["1", "2", "3", "b", "B"], default="1")

        if update_choice.upper() == "B":
            return

        new_content = None
        new_name = None
        new_description = None

        # Update content
        if update_choice in ["1", "3"]:
            from ..services.policy_builder_service import PolicyBuilder

            console.print("\n[cyan]Opening policy builder...[/cyan]")
            tag_count = len(current_content.get('tags', {}))
            console.print(f"[dim]Loading current policy with {tag_count} tag(s) defined...[/dim]\n")

            # Create builder and load existing policy
            builder = PolicyBuilder()
            builder.policy_name = policy.get('name', 'Updated Policy')
            builder.policy_description = policy.get('description', 'Updated via wizard')
            builder.metadata_set = True  # Skip metadata collection in run_interactive_loop

            # Load existing tag rules from the current policy
            builder.load_from_policy(current_content)

            console.print(f"[green]OK[/green] Loaded {len(builder.tag_rules)} tag rule(s) from existing policy\n")

            policy_data = builder.run_interactive_loop()

            if policy_data:
                new_content = policy_data['content']

        # Update metadata
        if update_choice in ["2", "3"]:
            console.print("\n[cyan]Update policy metadata:[/cyan]\n")

            new_name = Prompt.ask(
                "New policy name (leave blank to keep current)",
                default=""
            )
            if not new_name:
                new_name = None

            new_description = Prompt.ask(
                "New description (leave blank to keep current)",
                default=""
            )
            if not new_description:
                new_description = None

        # Confirm update
        if new_content is None and new_name is None and new_description is None:
            console.print("[yellow]No changes to apply[/yellow]")
            return

        console.print("\n[bold yellow]Confirm Update[/bold yellow]")
        if new_name:
            console.print(f"  New name: {new_name}")
        if new_description:
            console.print(f"  New description: {new_description}")
        if new_content:
            console.print("  Content: [green]Will be updated[/green]")

        if not Confirm.ask("\n[cyan]Apply these changes?[/cyan]", default=True):
            console.print("[yellow]Update cancelled[/yellow]")
            return

        # Apply update
        console.print("\n[cyan]Updating policy...[/cyan]")
        result = org_service.update_policy(
            policy_id=policy_id,
            content=new_content,
            name=new_name,
            description=new_description
        )

        if result['success']:
            console.print(f"[green]OK Policy updated successfully![/green]")
        else:
            console.print(f"[red]Failed to update policy: {result.get('error', result.get('message', 'Unknown error'))}[/red]")
            if result.get('suggestion'):
                console.print(f"[yellow]{result['suggestion']}[/yellow]")

    except KeyboardInterrupt:
        console.print("\n[yellow]Operation cancelled by user[/yellow]")
    except Exception as e:
        console.print(f"[red]Unexpected error: {str(e)}[/red]")


def _wizard_delete_policy(org_service: OrganizationsService, policy_id: Optional[str] = None):
    """Delete a policy flow."""
    console.print("\n[bold yellow]═══ Delete Policy ═══[/bold yellow]\n")

    try:
        # List policies if no policy_id provided
        if not policy_id:
            policies = org_service.list_policies(detailed=False)

            if not policies:
                console.print("[yellow]No policies found to delete[/yellow]")
                return

            # Display policies
            console.print("[cyan]Available policies:[/cyan]\n")
            for idx, policy in enumerate(policies, 1):
                console.print(f"[cyan][{idx}][/cyan] {policy.get('name', 'N/A')}")
                console.print(f"    [dim]ID: {policy.get('id', 'N/A')}[/dim]")
                if policy.get('aws_managed'):
                    console.print(f"    [yellow]AWS Managed - Cannot delete[/yellow]")
                console.print()

            console.print("[cyan][B][/cyan] Back to main menu\n")

            choice = Prompt.ask("Select policy to delete", default="B")

            if choice.upper() == "B":
                return

            if choice.isdigit():
                idx = int(choice) - 1
                if 0 <= idx < len(policies):
                    policy_id = policies[idx]['id']

                    # Check if AWS managed
                    if policies[idx].get('aws_managed'):
                        console.print("[red]Cannot delete AWS managed policies[/red]")
                        return
                else:
                    console.print("[red]Invalid selection[/red]")
                    return
            else:
                console.print("[red]Invalid selection[/red]")
                return

        # Get policy details
        policy = org_service.get_policy_details(policy_id)

        if 'error' in policy:
            console.print(f"[red]Error: {policy['error']}[/red]")
            return

        # Check if AWS managed
        if policy.get('aws_managed'):
            console.print("[red]Cannot delete AWS managed policies[/red]")
            return

        # Show policy details
        console.print(f"\n[bold red]WARNING: You are about to delete this policy:[/bold red]")
        console.print(f"\nName: {policy.get('name', 'N/A')}")
        console.print(f"ID: {policy.get('id', 'N/A')}")
        console.print(f"Description: {policy.get('description', 'N/A')}")

        # Check attachments
        targets_result = org_service.list_targets_for_policy(policy_id)

        if targets_result['success'] and targets_result.get('targets'):
            targets = targets_result['targets']
            console.print(f"\n[yellow]This policy is attached to {len(targets)} target(s):[/yellow]")
            for target in targets[:5]:
                console.print(f"  - {target.get('type', 'N/A')}: {target.get('name', target.get('target_id', 'N/A'))}")
            if len(targets) > 5:
                console.print(f"  ... and {len(targets) - 5} more")

            console.print("\n[red]You must detach the policy from all targets before deleting it.[/red]")

            if Confirm.ask("\n[cyan]Detach from all targets now?[/cyan]", default=True):
                console.print("\n[cyan]Detaching from all targets...[/cyan]")

                for target in targets:
                    target_id = target.get('target_id')
                    target_name = target.get('name', target_id)

                    detach_result = org_service.detach_policy(policy_id, target_id)
                    if detach_result['success']:
                        console.print(f"[green]OK Detached from {target_name}[/green]")
                    else:
                        console.print(f"[red]Failed to detach from {target_name}: {detach_result.get('message')}[/red]")
            else:
                console.print("[yellow]Cannot delete policy while it is attached to targets[/yellow]")
                return

        # Final confirmation
        console.print("\n[bold red]FINAL CONFIRMATION[/bold red]")
        console.print("[red]This action CANNOT be undone![/red]")

        confirmation = Prompt.ask(
            f"\nType the policy name '{policy.get('name', '')}' to confirm deletion",
            default=""
        )

        if confirmation != policy.get('name', ''):
            console.print("[yellow]Deletion cancelled - name did not match[/yellow]")
            return

        # Delete policy
        console.print("\n[cyan]Deleting policy...[/cyan]")
        result = org_service.delete_policy(policy_id)

        if result['success']:
            console.print(f"[green]OK Policy deleted successfully![/green]")
        else:
            console.print(f"[red]Failed to delete policy: {result.get('error', result.get('message', 'Unknown error'))}[/red]")
            if result.get('suggestion'):
                console.print(f"[yellow]{result['suggestion']}[/yellow]")

    except KeyboardInterrupt:
        console.print("\n[yellow]Operation cancelled by user[/yellow]")
    except Exception as e:
        console.print(f"[red]Unexpected error: {str(e)}[/red]")


def _wizard_attach_policy(org_service: OrganizationsService, policy_id: Optional[str] = None):
    """Attach a policy to targets flow."""
    console.print("\n[bold yellow]═══ Attach Policy ═══[/bold yellow]\n")

    try:
        # Select policy if not provided
        if not policy_id:
            policies = org_service.list_policies(detailed=False)

            if not policies:
                console.print("[yellow]No policies found to attach[/yellow]")
                return

            # Display policies
            console.print("[cyan]Available policies:[/cyan]\n")
            for idx, policy in enumerate(policies, 1):
                console.print(f"[cyan][{idx}][/cyan] {policy.get('name', 'N/A')}")
                console.print(f"    [dim]ID: {policy.get('id', 'N/A')}[/dim]")
                console.print()

            console.print("[cyan][B][/cyan] Back to main menu\n")

            choice = Prompt.ask("Select policy to attach", default="B")

            if choice.upper() == "B":
                return

            if choice.isdigit():
                idx = int(choice) - 1
                if 0 <= idx < len(policies):
                    policy_id = policies[idx]['id']
                    policy_name = policies[idx].get('name', 'N/A')
                else:
                    console.print("[red]Invalid selection[/red]")
                    return
            else:
                console.print("[red]Invalid selection[/red]")
                return
        else:
            # Get policy name
            policy = org_service.get_policy_details(policy_id)
            if 'error' in policy:
                console.print(f"[red]Error: {policy['error']}[/red]")
                return
            policy_name = policy.get('name', 'N/A')

        console.print(f"\n[bold]Attaching policy:[/bold] {policy_name}")

        # Show current attachments
        targets_result = org_service.list_targets_for_policy(policy_id)
        if targets_result['success'] and targets_result.get('targets'):
            console.print(f"\n[dim]Currently attached to:[/dim]")
            for target in targets_result['targets'][:3]:
                console.print(f"  - {target.get('type', 'N/A')}: {target.get('name', target.get('target_id', 'N/A'))}")
            if len(targets_result['targets']) > 3:
                console.print(f"  ... and {len(targets_result['targets']) - 3} more")

        # Attach to new targets
        _attach_to_targets(org_service, policy_id)

    except KeyboardInterrupt:
        console.print("\n[yellow]Operation cancelled by user[/yellow]")
    except Exception as e:
        console.print(f"[red]Unexpected error: {str(e)}[/red]")


def _wizard_detach_policy(org_service: OrganizationsService, policy_id: Optional[str] = None):
    """Detach a policy from targets flow."""
    console.print("\n[bold yellow]═══ Detach Policy ═══[/bold yellow]\n")

    try:
        # Select policy if not provided
        if not policy_id:
            policies = org_service.list_policies(detailed=False)

            if not policies:
                console.print("[yellow]No policies found to detach[/yellow]")
                return

            # Display policies
            console.print("[cyan]Available policies:[/cyan]\n")
            for idx, policy in enumerate(policies, 1):
                console.print(f"[cyan][{idx}][/cyan] {policy.get('name', 'N/A')}")
                console.print(f"    [dim]ID: {policy.get('id', 'N/A')}[/dim]")
                console.print()

            console.print("[cyan][B][/cyan] Back to main menu\n")

            choice = Prompt.ask("Select policy to detach", default="B")

            if choice.upper() == "B":
                return

            if choice.isdigit():
                idx = int(choice) - 1
                if 0 <= idx < len(policies):
                    policy_id = policies[idx]['id']
                    policy_name = policies[idx].get('name', 'N/A')
                else:
                    console.print("[red]Invalid selection[/red]")
                    return
            else:
                console.print("[red]Invalid selection[/red]")
                return
        else:
            # Get policy name
            policy = org_service.get_policy_details(policy_id)
            if 'error' in policy:
                console.print(f"[red]Error: {policy['error']}[/red]")
                return
            policy_name = policy.get('name', 'N/A')

        console.print(f"\n[bold]Detaching policy:[/bold] {policy_name}")

        # Get current attachments
        targets_result = org_service.list_targets_for_policy(policy_id)

        if not targets_result['success']:
            console.print(f"[red]Error: {targets_result.get('message', 'Failed to list targets')}[/red]")
            return

        targets = targets_result.get('targets', [])

        if not targets:
            console.print("\n[yellow]This policy is not attached to any targets[/yellow]")
            return

        # Display current targets
        console.print(f"\n[cyan]Currently attached to:[/cyan]\n")
        for idx, target in enumerate(targets, 1):
            target_type = target.get('type', 'N/A')
            target_id = target.get('target_id', 'N/A')
            target_name = target.get('name', target_id)
            console.print(f"[cyan][{idx}][/cyan] {target_type}: {target_name}")
            console.print(f"    [dim]ID: {target_id}[/dim]")
            console.print()

        console.print("[cyan][A][/cyan] Detach from ALL targets")
        console.print("[cyan][B][/cyan] Back to main menu\n")

        choice = Prompt.ask("Select targets to detach (comma-separated) or A for all", default="B")

        if choice.upper() == "B":
            return

        selected_targets = []

        if choice.upper() == "A":
            # Detach from all
            selected_targets = targets
        else:
            # Parse selection
            for part in choice.split(","):
                part = part.strip()
                if part.isdigit():
                    idx = int(part) - 1
                    if 0 <= idx < len(targets):
                        selected_targets.append(targets[idx])

        if not selected_targets:
            console.print("[yellow]No targets selected[/yellow]")
            return

        # Confirm detachment
        console.print(f"\n[bold yellow]Confirm Detachment[/bold yellow]")
        console.print(f"Policy: {policy_name}")
        console.print(f"Targets to detach: {len(selected_targets)}")

        if not Confirm.ask("\n[cyan]Proceed with detachment?[/cyan]", default=True):
            console.print("[yellow]Detachment cancelled[/yellow]")
            return

        # Detach from selected targets
        console.print("\n[cyan]Detaching policy...[/cyan]")

        success_count = 0
        for target in selected_targets:
            target_id = target.get('target_id')
            target_name = target.get('name', target_id)

            result = org_service.detach_policy(policy_id, target_id)
            if result['success']:
                console.print(f"[green]OK Detached from {target_name}[/green]")
                success_count += 1
            else:
                console.print(f"[red]Failed to detach from {target_name}: {result.get('message')}[/red]")

        console.print(f"\n[green]OK Detached from {success_count} of {len(selected_targets)} targets[/green]")

    except KeyboardInterrupt:
        console.print("\n[yellow]Operation cancelled by user[/yellow]")
    except Exception as e:
        console.print(f"[red]Unexpected error: {str(e)}[/red]")


def _attach_to_targets(org_service: OrganizationsService, policy_id: str):
    """Helper function to attach a policy to targets."""
    console.print("\n[cyan]Fetching available targets...[/cyan]")

    # Get root
    root_id = org_service.get_root_id()

    # Get OUs
    ous_result = org_service.list_organizational_units(root_id)
    ous = ous_result.get('ous', []) if ous_result['success'] else []

    # Get accounts
    accounts_result = org_service.list_accounts_for_parent()
    accounts = accounts_result.get('accounts', []) if accounts_result['success'] else []

    # Build target list
    targets = []
    console.print("\n[cyan]Available targets:[/cyan]\n")

    if root_id:
        console.print(f"[cyan][1][/cyan] Root")
        console.print(f"    [dim]ID: {root_id}[/dim]")
        targets.append(('ROOT', root_id, 'Root'))
        console.print()

    for idx, ou in enumerate(ous, start=len(targets) + 1):
        ou_id = ou.get('id')
        ou_name = ou.get('name', 'N/A')
        console.print(f"[cyan][{idx}][/cyan] OU: {ou_name}")
        console.print(f"    [dim]ID: {ou_id}[/dim]")
        targets.append(('ORGANIZATIONAL_UNIT', ou_id, ou_name))
        console.print()

    # Show first 10 accounts
    for idx, account in enumerate(accounts[:10], start=len(targets) + 1):
        account_id = account.get('id')
        account_name = account.get('name', 'N/A')
        console.print(f"[cyan][{idx}][/cyan] Account: {account_name}")
        console.print(f"    [dim]ID: {account_id}[/dim]")
        targets.append(('ACCOUNT', account_id, account_name))
        console.print()

    if len(accounts) > 10:
        console.print(f"[dim]... and {len(accounts) - 10} more accounts (not shown)[/dim]\n")

    console.print("[cyan][B][/cyan] Back\n")

    # Select targets
    selection = Prompt.ask(
        "Select targets (comma-separated numbers)",
        default="B"
    )

    if selection.upper() == "B":
        return

    # Parse selection
    selected_targets = []
    for part in selection.split(","):
        part = part.strip()
        if part.isdigit():
            idx = int(part) - 1
            if 0 <= idx < len(targets):
                selected_targets.append(targets[idx])

    if not selected_targets:
        console.print("[yellow]No targets selected[/yellow]")
        return

    # Attach to selected targets
    console.print(f"\n[cyan]Attaching to {len(selected_targets)} target(s)...[/cyan]")

    success_count = 0
    for target_type, target_id, target_name in selected_targets:
        result = org_service.attach_policy(policy_id, target_id)
        if result['success']:
            console.print(f"[green]OK Attached to {target_name}[/green]")
            success_count += 1
        else:
            # Check if already attached
            if 'already attached' in result.get('message', '').lower():
                console.print(f"[yellow]Already attached to {target_name}[/yellow]")
            else:
                console.print(f"[red]Failed to attach to {target_name}: {result.get('message')}[/red]")

    console.print(f"\n[green]OK Attached to {success_count} new target(s)[/green]")