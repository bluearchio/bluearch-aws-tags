# -*- coding: utf-8 -*-
"""Lifecycle management commands for AWS resources."""

import typer
from typing import Optional, List
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.prompt import Prompt, Confirm
from datetime import datetime, timezone, timedelta

from ..licensing.gate import requires_tier

console = Console()

# Create the lifecycle app
lifecycle_app = typer.Typer(
    name="lifecycle",
    help="""Resource Lifecycle Management - Stop zombie resources from eating your budget.

POLICY-FIRST WORKFLOW:
1. lifecycle policies create    # Define which resources to manage
2. lifecycle scan               # Find resources matching policies
3. lifecycle set-ttl            # Apply TTL to matched resources
4. lifecycle review             # Review and manage expiring resources

COMMANDS:
- wizard        - End-to-end guided workflow for new users
- policies      - Manage lifecycle policies (create/edit/delete)
- scan          - Find resources matching policies
- set-ttl       - Apply TTL tags to resources
- extend        - Extend TTL for expiring resources
- protect       - Protect resources from deletion
- review        - Interactive TUI to manage resources
- delete        - Delete expired resources
- notify-setup  - Configure Slack notifications
- notify        - Send expiration alerts

QUICK START:
  lifecycle wizard              # Guided end-to-end workflow

MANUAL WORKFLOW:
  lifecycle policies create     # Step 1: Define rules
  lifecycle scan                # Step 2: Find matching resources
  lifecycle set-ttl             # Step 3: Apply TTL
  lifecycle review              # Step 4: Manage expiring
""",
    no_args_is_help=True,
    rich_markup_mode="rich"
)


def _get_db_session():
    """Get database session with lazy import."""
    from tag_manager_cli.database.connection import get_db_session
    return get_db_session()


def _check_resources_exist() -> bool:
    """Check if resources exist in the database."""
    from tag_manager_cli.database.models import Resource

    with _get_db_session() as session:
        count = session.query(Resource).count()
        if count == 0:
            console.print("[yellow]No resources found in database.[/yellow]")
            console.print("Run [cyan]tag-manager lifecycle scan[/cyan] first to scan AWS resources.")
            return False
        return True


def _check_aws_org_access() -> tuple:
    """Check if AWS Organizations access is available.

    Returns:
        Tuple of (has_access: bool, org_service: Optional[OrganizationsService], message: str)
    """
    try:
        from tag_manager_cli.utils.aws_auth import aws_auth
        from tag_manager_cli.services.organizations_service import OrganizationsService

        session = aws_auth.initialize_session()
        org_service = OrganizationsService(session)

        # Check access
        access_result = org_service.check_organizations_access()
        if access_result.get('has_access'):
            return True, org_service, "AWS Organizations access available"
        else:
            return False, None, access_result.get('message', 'No Organizations access')
    except Exception as e:
        return False, None, f"Could not check Organizations access: {e}"


def _update_resource_compliance(session, resources, org_service):
    """Update resource compliance status from AWS Organizations.

    Args:
        session: Database session
        resources: List of Resource objects to update
        org_service: OrganizationsService instance

    Returns:
        Dict with compliance summary
    """
    from tag_manager_cli.database.models import Resource
    from datetime import datetime, timezone

    summary = {
        'checked': 0,
        'compliant': 0,
        'noncompliant': 0,
        'errors': 0,
        'org_policy_name': None
    }

    if not resources:
        return summary

    # Get the list of AWS Org tag policies to find required tags
    try:
        policies = org_service.list_tag_policies()
        if policies.get('success') and policies.get('policies'):
            summary['org_policy_name'] = policies['policies'][0].get('Name', 'Unknown')
    except Exception:
        pass

    # Get compliance data for resources (batch check)
    # Note: AWS API limits batch checking, so we use get_noncompliant_resources
    try:
        # Get noncompliant resources from AWS
        noncompliant_result = org_service.get_noncompliant_resources(max_results=500)
        if noncompliant_result.get('success'):
            noncompliant_arns = {}
            for r in noncompliant_result.get('resources', []):
                arn = r.get('ResourceARN', '')
                noncompliant_arns[arn] = {
                    'missing_tags': r.get('ComplianceDetails', {}).get('NoncompliantKeys', []),
                    'invalid_tags': r.get('ComplianceDetails', {}).get('KeysWithNoncompliantValues', [])
                }

            # Update resources in database
            now = datetime.now(timezone.utc)
            for resource in resources:
                summary['checked'] += 1

                if resource.resource_arn in noncompliant_arns:
                    # Resource is noncompliant
                    compliance_data = noncompliant_arns[resource.resource_arn]
                    resource.compliance_status = 'noncompliant'
                    resource.missing_tags = compliance_data['missing_tags']
                    resource.invalid_tags = compliance_data['invalid_tags']
                    resource.policy_source = 'aws_org'
                    resource.org_policy_name = summary['org_policy_name']
                    summary['noncompliant'] += 1
                else:
                    # Resource is compliant (or not in the noncompliant list)
                    resource.compliance_status = 'compliant'
                    resource.missing_tags = None
                    resource.invalid_tags = None
                    summary['compliant'] += 1

                resource.last_compliance_check = now

            session.commit()

    except Exception as e:
        console.print(f"[dim]Warning: Could not fetch AWS Org compliance: {e}[/dim]")
        summary['errors'] = 1

    return summary


@lifecycle_app.command("wizard")
def wizard_command():
    """
    End-to-end guided workflow for managing resource lifecycle.

    The wizard walks you through:
    1. Check multi-account setup
    2. Create lifecycle policy (define which resources to manage)
    3. Discover resources from AWS
    4. Apply TTL tags to matched resources
    5. (Optional) Set up Slack notifications
    6. Show next steps

    This is the recommended way to get started with tag-manager lifecycle management.

    Example:
        tag-manager lifecycle wizard
    """
    from tag_manager_cli.database.models import Resource, ResourceLifecyclePolicy
    from rich.progress import Progress, SpinnerColumn, TextColumn

    console.print("\n" + "=" * 60)
    console.print("[bold blue]  AWS Tag Manager - Lifecycle Wizard[/bold blue]")
    console.print("=" * 60)
    console.print("\nThis wizard will help you set up resource lifecycle management.")
    console.print("You'll define which resources to manage and set their TTL.\n")

    # =========================================================================
    # STEP 1: Check multi-account setup
    # =========================================================================
    console.print("[bold]Step 1/6: Multi-Account Setup Check[/bold]")
    console.print("-" * 40)

    # Check if multi-account is configured
    multi_account_configured = False
    try:
        from tag_manager_cli.integrations.aws_tools import AWSTools
        accounts = AWSTools.list_available_accounts()
        if accounts and len(accounts) > 1:
            multi_account_configured = True
            console.print(f"[green][OK][/green] Multi-account configured ({len(accounts)} accounts)")
        else:
            console.print("[dim]Single account mode (multi-account not configured)[/dim]")
    except Exception as e:
        console.print(f"[dim]Single account mode (could not check: {e})[/dim]")

    if not multi_account_configured:
        setup_multi = Confirm.ask(
            "\nWould you like to set up multi-account scanning?",
            default=False
        )
        if setup_multi:
            console.print("\nRun: [cyan]tag-manager setup multi-accounts[/cyan]")
            console.print("Then restart this wizard.\n")
            return

    console.print()

    # =========================================================================
    # STEP 2: Create lifecycle policy
    # =========================================================================
    console.print("[bold]Step 2/6: Create Lifecycle Policy[/bold]")
    console.print("-" * 40)
    console.print("Policies define WHICH resources to manage and their TTL rules.\n")

    with _get_db_session() as session:
        existing_policies = session.query(ResourceLifecyclePolicy).filter(
            ResourceLifecyclePolicy.enabled == True
        ).all()

        if existing_policies:
            console.print(f"[green][OK][/green] Found {len(existing_policies)} existing policy(ies):")
            for p in existing_policies:
                console.print(f"    - {p.name} (TTL: {p.ttl_days}d)")

            create_new = Confirm.ask("\nCreate a new policy?", default=False)
        else:
            console.print("[yellow]No policies found.[/yellow]")
            create_new = Confirm.ask("\nCreate your first lifecycle policy?", default=True)

    if create_new:
        console.print("\n[bold blue]Policy Creation Wizard[/bold blue]\n")

        # Policy name
        policy_name = Prompt.ask(
            "[bold]Policy name[/bold]",
            default="dev-cleanup"
        )

        # Validate unique name
        with _get_db_session() as session:
            existing = session.query(ResourceLifecyclePolicy).filter(
                ResourceLifecyclePolicy.name == policy_name
            ).first()
            if existing:
                console.print(f"[yellow]Policy '{policy_name}' already exists. Using existing policy.[/yellow]")
                selected_policy_name = existing.name
            else:
                # Description
                description = Prompt.ask(
                    "[bold]Description[/bold] (optional)",
                    default=f"Manage {policy_name} resources"
                )

                # Resource types
                console.print("\n[bold]Select resource types to manage:[/bold]")
                console.print("[dim]Common: ec2_instance, lambda_function, s3_bucket, rds_instance[/dim]")
                resource_types_input = Prompt.ask(
                    "Resource types (comma-separated, or 'all')",
                    default="ec2_instance,lambda_function"
                )

                if resource_types_input.lower() == "all":
                    resource_types = RESOURCE_TYPES.copy()
                else:
                    resource_types = [t.strip().lower() for t in resource_types_input.split(",")]

                # Tag conditions
                console.print("\n[bold]Define tag conditions (which resources to match):[/bold]")
                console.print("[dim]Example: Environment=dev matches resources with that tag[/dim]")

                conditions = {"tags": []}
                add_condition = Confirm.ask("Add a tag condition?", default=True)

                while add_condition:
                    tag_key = Prompt.ask("Tag key", default="Environment")
                    tag_value = Prompt.ask("Tag value", default="dev")
                    conditions["tags"].append({
                        "field": f"tags.{tag_key}",
                        "operator": "equals",
                        "value": tag_value,
                    })
                    console.print(f"[green][OK][/green] Added: {tag_key}={tag_value}")
                    add_condition = Confirm.ask("Add another condition?", default=False)

                # TTL settings
                console.print("\n[bold]TTL Settings:[/bold]")
                ttl_days = int(Prompt.ask("TTL (days until expiration)", default="30"))
                warning_schedule = [7, 3, 1]
                grace_period_days = 7

                # Create policy
                policy = ResourceLifecyclePolicy(
                    name=policy_name,
                    description=description,
                    resource_types=resource_types,
                    conditions=conditions,
                    ttl_days=ttl_days,
                    actions=[
                        {"action": "warn", "trigger": "warning_threshold"},
                        {"action": "delete", "trigger": "grace_period_end", "require_confirmation": True},
                    ],
                    warning_days_before=warning_schedule[0],
                    warning_schedule=warning_schedule,
                    grace_period_days=grace_period_days,
                    auto_apply=True,
                    enabled=True,
                    require_confirmation=True,
                    auto_delete_enabled=False,
                )
                session.add(policy)
                session.commit()

                console.print(f"\n[green][OK][/green] Policy '{policy_name}' created!")
                selected_policy_name = policy_name
    else:
        # Use first existing policy
        with _get_db_session() as session:
            first_policy = session.query(ResourceLifecyclePolicy).filter(
                ResourceLifecyclePolicy.enabled == True
            ).first()
            selected_policy_name = first_policy.name if first_policy else None

    console.print()

    # =========================================================================
    # STEP 3: Discover resources
    # =========================================================================
    console.print("[bold]Step 3/6: Discover AWS Resources[/bold]")
    console.print("-" * 40)

    with _get_db_session() as session:
        existing_count = session.query(Resource).count()

    if existing_count > 0:
        console.print(f"Found {existing_count} resources in local database.")
        refresh = Confirm.ask("Refresh resources from AWS?", default=True)
    else:
        console.print("[yellow]No resources in database yet.[/yellow]")
        refresh = True

    if refresh:
        console.print("\n[bold blue]Discovering resources from AWS...[/bold blue]")
        try:
            from tag_manager_cli.commands.discovery_commands import discover_resources_internal
            discover_resources_internal("all", None, True, False, False, None)
            console.print("[green][OK][/green] Discovery complete!")
        except Exception as e:
            console.print(f"[red]Error:[/red] Discovery failed: {e}")
            console.print("You can run manually: [cyan]tag-manager lifecycle scan[/cyan]")

    console.print()

    # =========================================================================
    # STEP 4: Apply TTL to matched resources
    # =========================================================================
    console.print("[bold]Step 4/6: Apply TTL to Resources[/bold]")
    console.print("-" * 40)

    now = datetime.now(timezone.utc)

    with _get_db_session() as session:
        # Get the policy we just created or selected (by name to avoid detached session issues)
        if selected_policy_name:
            policy = session.query(ResourceLifecyclePolicy).filter(
                ResourceLifecyclePolicy.name == selected_policy_name
            ).first()
        else:
            policy = session.query(ResourceLifecyclePolicy).filter(
                ResourceLifecyclePolicy.enabled == True
            ).first()

        if not policy:
            console.print("[yellow]No policy available. Skipping TTL application.[/yellow]")
        else:
            # Find resources matching the policy without TTL
            resources = session.query(Resource).filter(
                Resource.expires_at.is_(None)
            ).all()

            matched_resources = [r for r in resources if policy.is_applicable_to_resource(r)]

            if not matched_resources:
                console.print(f"[yellow]No untagged resources match policy '{policy.name}'.[/yellow]")
                console.print("This could mean all matching resources already have TTL set.")
            else:
                console.print(f"Found {len(matched_resources)} resource(s) matching policy '{policy.name}'")

                # Show preview
                table = Table(title="Resources to Tag", show_header=True)
                table.add_column("Service", style="cyan", width=12)
                table.add_column("Resource ID", width=35)
                table.add_column("Region", width=12)

                for r in matched_resources[:10]:
                    table.add_row(
                        r.service_name.upper(),
                        r.resource_id[:33] + "..." if len(r.resource_id) > 35 else r.resource_id,
                        r.region,
                    )

                if len(matched_resources) > 10:
                    table.add_row("...", f"and {len(matched_resources) - 10} more", "")

                console.print(table)

                apply_ttl = Confirm.ask(
                    f"\nApply TTL ({policy.ttl_days} days) to {len(matched_resources)} resources?",
                    default=True
                )

                if apply_ttl:
                    count = 0
                    new_expires = now + timedelta(days=policy.ttl_days)

                    for r in matched_resources:
                        r.expires_at = new_expires
                        r.lifecycle_state = 'active'
                        r.ttl_source = 'policy'
                        r.lifecycle_policy_id = policy.id
                        count += 1

                    session.commit()
                    console.print(f"\n[green][OK][/green] Applied TTL to {count} resource(s)")
                    console.print(f"    Expiration date: {new_expires.strftime('%Y-%m-%d')}")

    console.print()

    # =========================================================================
    # STEP 5: Optional Slack notifications
    # =========================================================================
    console.print("[bold]Step 5/6: Slack Notifications (Optional)[/bold]")
    console.print("-" * 40)

    from tag_manager_cli.services.slack_notification_service import slack_notification_service

    if slack_notification_service.is_configured():
        console.print("[green][OK][/green] Slack notifications already configured")
    else:
        console.print("Slack notifications will alert you when resources are expiring.")
        setup_slack = Confirm.ask("\nSet up Slack notifications now?", default=False)

        if setup_slack:
            console.print("\n[bold]To set up Slack notifications:[/bold]")
            console.print("1. Go to https://api.slack.com/apps")
            console.print("2. Create an app with Incoming Webhooks")
            console.print("3. Copy the webhook URL\n")

            webhook_url = Prompt.ask("Paste your Slack webhook URL (or press Enter to skip)", default="")

            if webhook_url:
                success, msg = slack_notification_service.configure(
                    webhook_url=webhook_url,
                    channel="#aws-alerts",
                    warning_days=[7, 3, 1],
                    enabled=True,
                )

                if success:
                    console.print(f"[green][OK][/green] Slack configured!")
                    # Test it
                    if Confirm.ask("Send a test notification?", default=True):
                        result = slack_notification_service.test_webhook(webhook_url)
                        if result.success:
                            console.print("[green][OK][/green] Test notification sent!")
                        else:
                            console.print(f"[red]Error:[/red] {result.message}")
                else:
                    console.print(f"[red]Error:[/red] {msg}")
        else:
            console.print("[dim]Skipped. You can set up later with:[/dim]")
            console.print("  [cyan]tag-manager lifecycle notify-setup[/cyan]")

    console.print()

    # =========================================================================
    # STEP 6: Summary and next steps
    # =========================================================================
    console.print("[bold]Step 6/6: Summary & Next Steps[/bold]")
    console.print("-" * 40)

    # Get final counts
    with _get_db_session() as session:
        total_resources = session.query(Resource).count()
        resources_with_ttl = session.query(Resource).filter(
            Resource.expires_at.isnot(None)
        ).count()
        policies_count = session.query(ResourceLifecyclePolicy).filter(
            ResourceLifecyclePolicy.enabled == True
        ).count()

    console.print("\n[bold]Configuration Summary:[/bold]")
    console.print(f"  Lifecycle policies: {policies_count}")
    console.print(f"  Total resources: {total_resources}")
    console.print(f"  Resources with TTL: {resources_with_ttl}")
    console.print(f"  Slack notifications: {'Configured' if slack_notification_service.is_configured() else 'Not configured'}")

    console.print("\n[bold]Daily Workflow:[/bold]")
    console.print("  [cyan]tag-manager lifecycle scan[/cyan]       # See resource status")
    console.print("  [cyan]tag-manager lifecycle review[/cyan]     # Review expiring resources")

    console.print("\n[bold]Useful Commands:[/bold]")
    console.print("  [cyan]tag-manager lifecycle scan --expiring 7[/cyan]   # Resources expiring in 7 days")
    console.print("  [cyan]tag-manager lifecycle extend --days 30[/cyan]    # Extend TTL")
    console.print("  [cyan]tag-manager lifecycle protect --list[/cyan]      # View protected resources")
    console.print("  [cyan]tag-manager lifecycle policies[/cyan]            # Manage policies")

    console.print("\n" + "=" * 60)
    console.print("[bold green]  Wizard Complete![/bold green]")
    console.print("=" * 60 + "\n")


@lifecycle_app.command("scan")
def scan_command(
    services: Optional[str] = typer.Option(None, "--services", "-s", help="Filter by services (comma-separated)"),
    regions: Optional[str] = typer.Option(None, "--regions", "-r", help="Filter by regions (comma-separated, for discovery)"),
    policy_filter: Optional[str] = typer.Option(None, "--policy", "-p", help="Filter by policy name"),
    untagged: bool = typer.Option(False, "--untagged", "-u", help="Show resources without TTL (candidates for policies)"),
    expiring: Optional[int] = typer.Option(None, "--expiring", "-e", help="Show resources expiring within N days"),
    discover: bool = typer.Option(False, "--discover", "-d", help="Run fresh AWS discovery before scanning"),
    multi_account: bool = typer.Option(False, "--multi-account", "-m", help="Include all enabled accounts in discovery"),
    show_all: bool = typer.Option(False, "--all", "-a", help="Show all resources, not just those with TTL"),
    check_compliance: bool = typer.Option(False, "--check-compliance", "-c", help="Check AWS Org Tag Policy compliance"),
    noncompliant: bool = typer.Option(False, "--noncompliant", "-n", help="Show only noncompliant resources (requires AWS Org access)"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip prompts, use defaults (cached data, single account)"),
):
    """
    Scan resources and check lifecycle status.

    By default, uses cached resources from the database. If no cached resources
    exist or --discover is set, prompts to run AWS discovery.

    Examples:
        lifecycle scan                      # Interactive: asks about discovery
        lifecycle scan --discover           # Force fresh AWS discovery
        lifecycle scan --discover -m        # Discover across all accounts
        lifecycle scan --services lambda    # Filter by Lambda only
        lifecycle scan --policy dev-cleanup # Filter by specific policy
        lifecycle scan --untagged           # Find resources without TTL
        lifecycle scan --expiring 7         # Resources expiring in 7 days
        lifecycle scan --check-compliance   # Check AWS Org Tag Policy compliance
        lifecycle scan -y                   # Non-interactive, use cached data
    """
    from tag_manager_cli.database.models import Resource, ResourceLifecyclePolicy
    from rich.prompt import Confirm

    # Check current state: cached resources and multi-account availability
    cached_count = 0
    multi_account_available = False
    enabled_accounts = []

    with _get_db_session() as session:
        cached_count = session.query(Resource).count()

    # Check if multi-account is configured
    try:
        from tag_manager_cli.modules.multi_account_discovery import MultiAccountDiscovery
        multi_account_discovery = MultiAccountDiscovery()
        enabled_accounts = multi_account_discovery.get_enabled_accounts()
        multi_account_available = len(enabled_accounts) > 0
    except Exception:
        pass

    # Determine if we should run discovery
    should_discover = discover  # Explicit --discover flag
    use_multi_account = multi_account  # Explicit --multi-account flag

    if not yes:
        # Interactive mode
        if not discover:
            # Ask about discovery if not explicitly requested
            if cached_count > 0:
                console.print(f"[dim]Found {cached_count} cached resources in database.[/dim]")
                should_discover = Confirm.ask(
                    "Run fresh AWS discovery?",
                    default=False
                )
            else:
                console.print("[yellow]No cached resources found.[/yellow]")
                should_discover = Confirm.ask(
                    "Run AWS discovery to find resources?",
                    default=True
                )

        # Ask about multi-account if discovery will run and multi-account is available
        # (but only if --multi-account wasn't already specified)
        if should_discover and multi_account_available and not multi_account:
            console.print(f"[dim]Multi-account enabled: {len(enabled_accounts)} additional account(s) configured.[/dim]")
            use_multi_account = Confirm.ask(
                "Include all enabled accounts?",
                default=False
            )

    # Run discovery if requested
    if should_discover:
        discover_services = services if services else "all"
        if use_multi_account:
            console.print(f"[bold blue][DISCOVER] Refreshing resources from AWS (all {len(enabled_accounts) + 1} accounts)...[/bold blue]")
        else:
            console.print(f"[bold blue][DISCOVER] Refreshing resources from AWS (current account only)...[/bold blue]")
        if services:
            console.print(f"[dim]Services: {services}[/dim]")
        if regions:
            console.print(f"[dim]Regions: {regions}[/dim]")
        try:
            from tag_manager_cli.commands.discovery_commands import discover_resources_internal
            # Pass services, regions, and single_account flag (inverted from use_multi_account)
            discover_resources_internal(discover_services, regions, True, False, not use_multi_account, None)
            console.print("")
        except typer.Exit:
            # User cancelled discovery - exit cleanly
            raise
        except Exception as e:
            console.print(f"[yellow]Warning:[/yellow] Discovery failed: {e}")
            console.print("Proceeding with cached resources...\n")

    console.print("[bold blue][SCAN] Scanning resource lifecycle status...[/bold blue]")

    # Check AWS Org compliance if requested or if noncompliant filter is used
    org_service = None
    has_org_access = False
    compliance_summary = None

    if check_compliance or noncompliant:
        console.print("[dim]Checking AWS Organizations access...[/dim]")
        has_org_access, org_service, org_message = _check_aws_org_access()

        if has_org_access:
            console.print(f"[green][OK][/green] {org_message}")
        else:
            console.print(f"[yellow]Note:[/yellow] {org_message}")
            if noncompliant:
                console.print("[yellow]Cannot filter by noncompliant - AWS Org access required.[/yellow]")
                console.print("Run: [cyan]tag-manager policy check-access[/cyan] for details.")
                return

    now = datetime.now(timezone.utc)

    with _get_db_session() as session:
        # Get active policies
        policies = session.query(ResourceLifecyclePolicy).filter(
            ResourceLifecyclePolicy.enabled == True
        ).all()

        # Build resource query based on mode
        if noncompliant:
            # Show only noncompliant resources
            query = session.query(Resource).filter(Resource.compliance_status == 'noncompliant')
        elif untagged:
            # Show resources WITHOUT TTL - candidates for policies
            query = session.query(Resource).filter(Resource.expires_at.is_(None))
        elif show_all:
            # Show all resources
            query = session.query(Resource)
        elif expiring is not None:
            # Filter to resources with TTL expiring within N days
            query = session.query(Resource).filter(Resource.expires_at.isnot(None))
        else:
            # DEFAULT: Show resources matching active policies (regardless of TTL status)
            # This is the expected workflow: policies define WHICH resources to manage
            query = session.query(Resource)

        if services:
            service_list = [s.strip().lower() for s in services.split(',')]
            query = query.filter(Resource.service_name.in_(service_list))

        if expiring is not None:
            threshold = now + timedelta(days=expiring)
            query = query.filter(Resource.expires_at <= threshold)

        resources = query.all()

        # Run AWS Org compliance check if requested
        if has_org_access and org_service and check_compliance:
            console.print("[dim]Fetching compliance data from AWS Organizations...[/dim]")
            compliance_summary = _update_resource_compliance(session, resources, org_service)
            if compliance_summary['checked'] > 0:
                console.print(f"[green][OK][/green] Compliance check: {compliance_summary['noncompliant']} noncompliant, {compliance_summary['compliant']} compliant")

        # Filter by policy - ALWAYS apply when policies exist (unless showing all/noncompliant)
        if policy_filter:
            # Specific policy filter
            policy = session.query(ResourceLifecyclePolicy).filter(
                ResourceLifecyclePolicy.name == policy_filter
            ).first()
            if not policy:
                console.print(f"[red]Error:[/red] Policy '{policy_filter}' not found.")
                return
            resources = [r for r in resources if policy.is_applicable_to_resource(r)]
        elif policies and not show_all and not noncompliant:
            # Default mode: filter to resources matching ANY active policy
            resources = [r for r in resources if any(p.is_applicable_to_resource(r) for p in policies)]

        if not resources:
            if untagged:
                console.print("[green]All resources have TTL set![/green]")
            elif not policies:
                console.print("[yellow]No lifecycle policies configured.[/yellow]")
                console.print("\nPolicies define WHICH resources to manage (by service, tags, age).")
                console.print("Create your first policy:")
                console.print("  [cyan]lifecycle policies create[/cyan]")
            else:
                console.print("[yellow]No resources matching your policies.[/yellow]")
                console.print(f"\nActive policies: {', '.join(p.name for p in policies)}")
                console.print("\nOptions:")
                console.print("  [cyan]lifecycle scan --all[/cyan]        # Show all resources")
                console.print("  [cyan]lifecycle policies list[/cyan]     # View policy conditions")
                console.print("  [cyan]lifecycle scan[/cyan]              # Re-scan resources from AWS")
            return

        # Match resources to policies (for display) and update counts
        resource_policies = {}
        policy_resource_counts = {p.id: 0 for p in policies}
        for r in resources:
            for p in policies:
                if p.is_applicable_to_resource(r):
                    resource_policies[r.id] = p.name
                    policy_resource_counts[p.id] += 1
                    break

        # Update resources_affected count on each policy
        for p in policies:
            p.resources_affected = policy_resource_counts.get(p.id, 0)
        session.commit()

        # Handle untagged mode
        if untagged:
            console.print(f"\n[bold]Resources without TTL ({len(resources)})[/bold]")
            console.print("[dim]These resources could be managed by lifecycle policies[/dim]\n")

            table = Table(title="Untagged Resources", show_header=True)
            table.add_column("Service", style="cyan", width=10)
            table.add_column("Resource ID", width=35)
            table.add_column("Region", width=12)
            table.add_column("Matches Policy", style="yellow", width=15)

            for r in resources[:20]:
                policy_name = resource_policies.get(r.id, "-")
                table.add_row(
                    r.service_name.upper(),
                    r.resource_id[:33] + "..." if len(r.resource_id) > 35 else r.resource_id,
                    r.region,
                    policy_name,
                )

            if len(resources) > 20:
                table.add_row("...", f"and {len(resources) - 20} more", "", "")

            console.print(table)

            matched = len([r for r in resources if r.id in resource_policies])
            console.print(f"\n[bold]Summary:[/bold]")
            console.print(f"  Total without TTL: {len(resources)}")
            console.print(f"  Matches a policy: {matched}")
            console.print(f"  No policy match: {len(resources) - matched}")

            console.print("\n[bold]Next Steps:[/bold]")
            console.print("  [cyan]lifecycle set-ttl --ttl-days 30[/cyan]  # Apply TTL to matching resources")
            return

        # Handle noncompliant mode
        if noncompliant:
            console.print(f"\n[bold red]Noncompliant Resources ({len(resources)})[/bold red]")
            console.print("[dim]These resources are missing required tags per AWS Org Tag Policy[/dim]\n")

            table = Table(title="Noncompliant Resources", show_header=True)
            table.add_column("Service", style="cyan", width=10)
            table.add_column("Resource ID", width=30)
            table.add_column("Region", width=12)
            table.add_column("Missing Tags", style="red", width=20)
            table.add_column("TTL Set", style="green", width=8)

            for r in resources[:20]:
                missing = r.missing_tags if r.missing_tags else []
                missing_str = ", ".join(missing[:3])
                if len(missing) > 3:
                    missing_str += f" +{len(missing)-3}"

                table.add_row(
                    r.service_name.upper(),
                    r.resource_id[:28] + "..." if len(r.resource_id) > 30 else r.resource_id,
                    r.region,
                    missing_str if missing_str else "-",
                    "YES" if r.expires_at else "NO"
                )

            if len(resources) > 20:
                table.add_row("...", f"and {len(resources) - 20} more", "", "", "")

            console.print(table)

            with_ttl = len([r for r in resources if r.expires_at])
            console.print(f"\n[bold]Summary:[/bold]")
            console.print(f"  Total noncompliant: {len(resources)}")
            console.print(f"  With TTL set: {with_ttl}")
            console.print(f"  Without TTL: {len(resources) - with_ttl}")

            console.print("\n[bold]Next Steps:[/bold]")
            console.print("  [cyan]lifecycle set-ttl --ttl-days 30[/cyan]  # Apply TTL deadline to fix tags")
            console.print("  [dim]Or fix the missing tags directly in AWS Console[/dim]")
            return

        # DEFAULT MODE: Show resources matching policies
        # This is the expected workflow - policies define WHICH resources to manage
        if not untagged and not noncompliant and not show_all and expiring is None:
            # Count resources by TTL status
            with_ttl = [r for r in resources if r.expires_at]
            without_ttl = [r for r in resources if not r.expires_at]

            console.print(f"\n[bold]Resources Matching Policies ({len(resources)})[/bold]")
            console.print("[dim]These resources match your active lifecycle policies[/dim]\n")

            # Summary
            summary = f"""
[bold]Matching Resources:[/bold] {len(resources)}
[green]With TTL set:[/green] {len(with_ttl)}
[yellow]Without TTL:[/yellow] {len(without_ttl)}
[dim]Active policies:[/dim] {', '.join(p.name for p in policies)}
"""
            console.print(Panel(summary.strip(), title="Policy Match Summary", border_style="blue"))

            # Show table of matching resources
            table = Table(title="Resources Matching Policies", show_header=True)
            table.add_column("Service", style="cyan", width=10)
            table.add_column("Resource ID", width=30)
            table.add_column("Region", width=12)
            table.add_column("Policy", style="yellow", width=15)
            table.add_column("TTL Status", width=12)

            for r in resources[:20]:
                policy_name = resource_policies.get(r.id, "-")
                if r.expires_at:
                    # Handle timezone-naive datetimes from SQLite
                    expires_at = r.expires_at
                    if expires_at.tzinfo is None:
                        expires_at = expires_at.replace(tzinfo=timezone.utc)
                    days_until = (expires_at - now).days
                    if days_until < 0:
                        ttl_status = f"[red]Expired[/red]"
                    elif days_until <= 7:
                        ttl_status = f"[yellow]{days_until}d[/yellow]"
                    else:
                        ttl_status = f"[green]{days_until}d[/green]"
                else:
                    ttl_status = "[dim]No TTL[/dim]"

                table.add_row(
                    r.service_name.upper(),
                    r.resource_id[:28] + "..." if len(r.resource_id) > 30 else r.resource_id,
                    r.region,
                    policy_name[:13] + ".." if len(policy_name) > 15 else policy_name,
                    ttl_status
                )

            if len(resources) > 20:
                table.add_row("...", f"and {len(resources) - 20} more", "", "", "")

            console.print(table)

            # Next steps
            console.print("\n[bold]Next Steps:[/bold]")
            if without_ttl:
                console.print(f"  [cyan]lifecycle set-ttl --ttl-days 30[/cyan]  # Apply TTL to {len(without_ttl)} resources")
            if with_ttl:
                console.print(f"  [cyan]lifecycle review[/cyan]                  # Manage {len(with_ttl)} resources with TTL")
            console.print("  [cyan]lifecycle policies list[/cyan]           # View policy details")
            return

        # Categorize resources by TTL status
        expired = []
        expiring_soon = []  # Within 7 days
        active = []
        protected_count = 0

        for r in resources:
            # Handle timezone-naive datetimes from SQLite
            expires_at = r.expires_at
            if expires_at and expires_at.tzinfo is None:
                expires_at = expires_at.replace(tzinfo=timezone.utc)

            if r.protected:
                protected_count += 1

            if not expires_at:
                continue

            days_until = (expires_at - now).days

            if days_until < 0:
                expired.append((r, abs(days_until)))
            elif days_until <= 7:
                expiring_soon.append((r, days_until))
            else:
                active.append((r, days_until))

        # Summary panel
        summary = f"""
[bold]Resources with TTL:[/bold] {len(resources)}
[red]Expired:[/red] {len(expired)}
[yellow]Expiring soon (7 days):[/yellow] {len(expiring_soon)}
[green]Active:[/green] {len(active)}
[blue]Protected:[/blue] {protected_count}
[dim]Active policies:[/dim] {len(policies)}
"""
        # Add compliance info if available
        if compliance_summary and compliance_summary['checked'] > 0:
            summary += f"""
[bold cyan]AWS Org Compliance:[/bold cyan]
  [green]Compliant:[/green] {compliance_summary['compliant']}
  [red]Noncompliant:[/red] {compliance_summary['noncompliant']}
"""
            if compliance_summary.get('org_policy_name'):
                summary += f"  [dim]Policy:[/dim] {compliance_summary['org_policy_name']}\n"

        console.print(Panel(summary, title="Lifecycle Summary", border_style="blue"))

        # Show expired resources
        if expired:
            table = Table(title=f"[red]Expired Resources ({len(expired)})[/red]", show_header=True)
            table.add_column("Service", style="cyan", width=10)
            table.add_column("Resource ID", style="white", width=28)
            table.add_column("Expired", style="red", width=10)
            table.add_column("Policy", style="yellow", width=14)
            table.add_column("Protected", style="green", width=9)

            for r, days in sorted(expired, key=lambda x: -x[1])[:15]:
                policy_name = resource_policies.get(r.id, "-")
                table.add_row(
                    r.service_name.upper(),
                    r.resource_id[:26] + "..." if len(r.resource_id) > 28 else r.resource_id,
                    f"{days}d ago",
                    policy_name[:12] + ".." if len(policy_name) > 14 else policy_name,
                    "YES" if r.protected else "NO"
                )

            if len(expired) > 15:
                table.add_row("...", f"and {len(expired) - 15} more", "", "", "")

            console.print(table)

        # Show expiring soon
        if expiring_soon:
            table = Table(title=f"[yellow]Expiring Soon ({len(expiring_soon)})[/yellow]", show_header=True)
            table.add_column("Service", style="cyan", width=10)
            table.add_column("Resource ID", style="white", width=28)
            table.add_column("Expires In", style="yellow", width=10)
            table.add_column("Policy", style="yellow", width=14)

            for r, days in sorted(expiring_soon, key=lambda x: x[1])[:10]:
                policy_name = resource_policies.get(r.id, "-")
                table.add_row(
                    r.service_name.upper(),
                    r.resource_id[:26] + "..." if len(r.resource_id) > 28 else r.resource_id,
                    f"{days}d" if days > 0 else "today",
                    policy_name[:12] + ".." if len(policy_name) > 14 else policy_name,
                )

            console.print(table)

        # Show active if requested
        if show_all and active:
            table = Table(title=f"[green]Active Resources ({len(active)})[/green]", show_header=True)
            table.add_column("Service", style="cyan", width=10)
            table.add_column("Resource ID", style="white", width=28)
            table.add_column("Expires In", style="green", width=10)
            table.add_column("Policy", style="dim", width=14)

            for r, days in sorted(active, key=lambda x: x[1])[:10]:
                policy_name = resource_policies.get(r.id, "-")
                table.add_row(
                    r.service_name.upper(),
                    r.resource_id[:26] + "..." if len(r.resource_id) > 28 else r.resource_id,
                    f"{days}d",
                    policy_name[:12] + ".." if len(policy_name) > 14 else policy_name,
                )

            if len(active) > 10:
                console.print(f"  ... and {len(active) - 10} more active resources")

        # Next steps
        console.print("\n[bold]Next Steps:[/bold]")
        if expired:
            console.print(f"  [cyan]lifecycle delete --dry-run[/cyan]  # Preview deletion of {len(expired)} expired resources")
        if expiring_soon:
            console.print(f"  [cyan]lifecycle review[/cyan]            # Review {len(expiring_soon)} expiring resources")
        console.print("  [cyan]lifecycle policies[/cyan]           # Manage lifecycle policies")


@lifecycle_app.command("set-ttl")
def set_ttl_command(
    ttl_days: Optional[int] = typer.Option(None, "--ttl-days", "--days", "-d", help="TTL in days (uses policy TTL if not specified)"),
    policy_name: Optional[str] = typer.Option(None, "--policy", "-p", help="Apply a specific policy (default: all active policies)"),
    services: Optional[str] = typer.Option(None, "--services", "-s", help="Filter by services (comma-separated)"),
    resource_arn: Optional[str] = typer.Option(None, "--resource-arn", "-r", help="Specific resource ARN"),
    owner: Optional[str] = typer.Option(None, "--owner", "-o", help="Set owner email for resources"),
    apply_all: bool = typer.Option(False, "--all", "-a", help="Apply to ALL resources (bypass policy filter)"),
    noncompliant_only: bool = typer.Option(False, "--noncompliant", "-n", help="Apply only to noncompliant resources (from AWS Org policy check)"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Preview without making changes"),
    force: bool = typer.Option(False, "--force", "-f", help="Skip confirmation"),
):
    """
    Set TTL (time-to-live) on resources matching policies.

    By default, applies TTL to resources matching active lifecycle policies.
    Use --all to apply to all resources regardless of policies.
    Use --noncompliant to apply to resources caught by AWS Org Tag Policy.

    Examples:
        lifecycle set-ttl                                 # Apply policies to matching resources
        lifecycle set-ttl --policy dev-cleanup            # Apply specific policy
        lifecycle set-ttl --days 30 --all                 # 30-day TTL on all resources
        lifecycle set-ttl --days 30 --services lambda     # 30-day TTL on Lambda only
        lifecycle set-ttl --days 7 --resource-arn <arn>   # Single resource
        lifecycle set-ttl --owner team@example.com        # Set owner email
        lifecycle set-ttl --noncompliant --days 14        # 14-day TTL on noncompliant resources
    """
    from tag_manager_cli.database.models import Resource, ResourceLifecyclePolicy

    with _get_db_session() as session:
        # Get policies
        if policy_name:
            policy = session.query(ResourceLifecyclePolicy).filter(
                ResourceLifecyclePolicy.name == policy_name
            ).first()
            if not policy:
                console.print(f"[red]Error:[/red] Policy '{policy_name}' not found.")
                return
            policies = [policy]
        elif not apply_all:
            policies = session.query(ResourceLifecyclePolicy).filter(
                ResourceLifecyclePolicy.enabled == True
            ).all()
            if not policies and not resource_arn and not ttl_days:
                console.print("[yellow]No active policies found.[/yellow]")
                console.print("\nCreate a policy first:")
                console.print("  [cyan]lifecycle policies create[/cyan]")
                console.print("\nOr specify TTL directly:")
                console.print("  [cyan]lifecycle set-ttl --days 30 --all[/cyan]")
                return
        else:
            policies = []

        # Determine TTL
        if ttl_days is None and policies:
            # Use first policy's TTL as default
            default_ttl = policies[0].ttl_days if policies else 30
            console.print(f"[dim]Using TTL from policies (default: {default_ttl} days)[/dim]")
        elif ttl_days is None:
            console.print("[red]Error:[/red] Specify --ttl-days or use a policy.")
            return
        else:
            default_ttl = ttl_days

        # Build resource query
        if resource_arn:
            query = session.query(Resource).filter(Resource.resource_arn == resource_arn)
        elif noncompliant_only:
            # Apply to noncompliant resources only (from AWS Org policy check)
            query = session.query(Resource).filter(
                Resource.compliance_status == 'noncompliant',
                Resource.expires_at.is_(None)  # Only those without TTL
            )
        else:
            query = session.query(Resource).filter(Resource.expires_at.is_(None))  # Only untagged

        if services:
            service_list = [s.strip().lower() for s in services.split(',')]
            query = query.filter(Resource.service_name.in_(service_list))

        resources = query.all()

        if not resources:
            console.print("[yellow]No resources found to apply TTL.[/yellow]")
            console.print("\nRun discovery first:")
            console.print("  [cyan]lifecycle scan[/cyan]")
            return

        # Filter by policies (unless --all or specific ARN or noncompliant)
        resources_to_update = []
        now = datetime.now(timezone.utc)

        if noncompliant_only:
            # Apply to noncompliant resources (caught by AWS Org Tag Policy)
            for r in resources:
                resources_to_update.append({
                    'resource': r,
                    'ttl_days': default_ttl,
                    'policy': None,
                    'policy_source': 'aws_org',  # Track that this came from AWS Org policy
                    'org_policy_name': r.org_policy_name,
                    'missing_tags': r.missing_tags,
                    'new_expires': now + timedelta(days=default_ttl),
                })
        elif apply_all or resource_arn:
            # Apply to all matching resources with specified TTL
            for r in resources:
                resources_to_update.append({
                    'resource': r,
                    'ttl_days': default_ttl,
                    'policy': None,
                    'policy_source': 'manual',
                    'new_expires': now + timedelta(days=default_ttl),
                })
        else:
            # Apply based on local policy matching
            # User-provided --ttl-days overrides policy TTL
            for r in resources:
                for p in policies:
                    if p.is_applicable_to_resource(r):
                        # Use user-provided TTL if specified, otherwise use policy's TTL
                        effective_ttl = ttl_days if ttl_days is not None else p.ttl_days
                        resources_to_update.append({
                            'resource': r,
                            'ttl_days': effective_ttl,
                            'policy': p,
                            'policy_source': 'local',  # Local lifecycle policy
                            'new_expires': now + timedelta(days=effective_ttl),
                        })
                        break

        if not resources_to_update:
            console.print("[yellow]No resources match the active policies.[/yellow]")
            console.print("\nOptions:")
            console.print("  [cyan]lifecycle policies create[/cyan]  # Create a new policy")
            console.print("  [cyan]lifecycle set-ttl --all --days 30[/cyan]  # Apply to all resources")
            return

        # Preview
        console.print(f"\n[bold blue]Setting TTL on {len(resources_to_update)} resource(s)[/bold blue]")
        if owner:
            console.print(f"Owner: {owner}")

        table = Table(title="Resources to Update", show_header=True)
        table.add_column("Service", style="cyan", width=10)
        table.add_column("Resource ID", width=28)
        table.add_column("TTL", style="yellow", width=6)
        table.add_column("Source", style="magenta", width=8)
        table.add_column("Policy", style="dim", width=12)
        table.add_column("Expires", style="green", width=12)

        for item in resources_to_update[:20]:
            r = item['resource']
            policy_source = item.get('policy_source', 'manual')
            if item['policy']:
                policy_display = item['policy'].name
            elif item.get('org_policy_name'):
                policy_display = item['org_policy_name']
            else:
                policy_display = "-"

            table.add_row(
                r.service_name.upper(),
                r.resource_id[:26] + "..." if len(r.resource_id) > 28 else r.resource_id,
                f"{item['ttl_days']}d",
                policy_source,
                policy_display[:10] + ".." if len(policy_display) > 12 else policy_display,
                item['new_expires'].strftime('%Y-%m-%d'),
            )

        if len(resources_to_update) > 20:
            table.add_row("...", f"and {len(resources_to_update) - 20} more", "", "", "", "")

        console.print(table)

        if dry_run:
            console.print("\n[yellow][DRY RUN][/yellow] No changes made.")
            return

        # Confirmation
        if not force:
            if not Confirm.ask(f"\nApply TTL to {len(resources_to_update)} resource(s)?"):
                console.print("[yellow]Cancelled.[/yellow]")
                return

        # Apply changes
        updated_count = 0
        aws_tag_success = 0
        aws_tag_failed = 0

        # Import AWS tagging function
        from tag_manager_cli.commands.unified_tags import _apply_tags_to_aws_resource

        console.print("\n[bold]Applying TTL...[/bold]")

        for item in resources_to_update:
            r = item['resource']

            # Determine policy source and name
            policy_source = item.get('policy_source', 'manual')
            if item['policy']:
                policy_name_tag = item['policy'].name
            elif policy_source == 'aws_org' and item.get('org_policy_name'):
                policy_name_tag = item['org_policy_name']
            else:
                policy_name_tag = 'manual'

            # Build AWS tags
            aws_tags = {
                'ManagedBy': 'tag-manager-cli',
                'bluearch:ttl': item['new_expires'].strftime('%Y-%m-%d'),
                'bluearch:policy': policy_name_tag,
                'bluearch:policy-source': policy_source,
            }
            if owner:
                aws_tags['bluearch:owner'] = owner

            # Add noncompliant tags if from AWS Org policy
            if policy_source == 'aws_org' and item.get('missing_tags'):
                missing_tags_str = ','.join(item['missing_tags'][:5])  # Limit to 5 tags
                aws_tags['bluearch:noncompliant-tags'] = missing_tags_str

            # Apply AWS tags to the actual resource
            try:
                if r.resource_arn:
                    tag_success = _apply_tags_to_aws_resource(
                        r.resource_arn,
                        aws_tags,
                        r.service_name,
                        account_id=getattr(r, "account_id", None),
                        region=getattr(r, "region", None),
                        resource_id=getattr(r, "resource_id", None),
                    )
                    if tag_success:
                        aws_tag_success += 1
                    else:
                        aws_tag_failed += 1
                else:
                    # No ARN available, skip AWS tagging
                    aws_tag_failed += 1
            except Exception as e:
                console.print(f"[dim]AWS tag failed for {r.resource_id}: {e}[/dim]")
                aws_tag_failed += 1

            # Update database record
            r.expires_at = item['new_expires']
            r.lifecycle_state = 'active'
            r.ttl_source = 'policy' if item['policy'] else 'manual'
            r.policy_source = policy_source

            if item['policy']:
                r.lifecycle_policy_id = item['policy'].id

            if policy_source == 'aws_org' and item.get('org_policy_name'):
                r.org_policy_name = item['org_policy_name']

            if owner:
                r.owner_email = owner

            # Log audit
            _log_lifecycle_audit(
                session, r,
                operation='TTL_SET',
                old_state='active',
                new_state='active',
                old_expires_at=None,
                new_expires_at=item['new_expires'],
                details={
                    'ttl_days': item['ttl_days'],
                    'policy': item['policy'].name if item['policy'] else None,
                    'policy_source': policy_source,
                    'org_policy_name': item.get('org_policy_name'),
                    'owner': owner,
                    'aws_tags_applied': aws_tags,
                },
            )

            updated_count += 1

        session.commit()

        console.print(f"\n[green][OK][/green] Applied TTL to {updated_count} resource(s)")
        console.print(f"    AWS tags applied: {aws_tag_success}")
        if aws_tag_failed > 0:
            console.print(f"    [yellow]AWS tags failed: {aws_tag_failed}[/yellow]")
        console.print("\n[bold]Next steps:[/bold]")
        console.print("  [cyan]lifecycle scan[/cyan]    # View resources with TTL")
        console.print("  [cyan]lifecycle review[/cyan]  # Review expiring resources")


@lifecycle_app.command("delete")
@requires_tier("lifecycle:auto_delete")
def delete_command(
    services: Optional[str] = typer.Option(None, "--services", "-s", help="Filter by services"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Preview without deleting"),
    force: bool = typer.Option(False, "--force", "-f", help="Skip confirmation"),
):
    """
    Delete expired resources with safety checks.

    Resources go through a warning period before deletion:
    1. TTL expires -> resource marked for warning
    2. Warning sent -> 7-day grace period starts
    3. Grace period ends -> resource can be deleted

    Examples:
        lifecycle delete --dry-run              # Preview what would be deleted
        lifecycle delete --services lambda      # Only Lambda functions
        lifecycle delete --force                # Skip confirmation
    """
    # Import and call existing function
    from tag_manager_cli.commands.unified_tags import _delete_expired_resources
    _delete_expired_resources(services, dry_run, force)


# Create a subgroup for policy management
policies_app = typer.Typer(
    name="policies",
    help="""Manage lifecycle policies.

Policies define WHICH resources to manage and their TTL rules.

COMMANDS:
- policies           - List all policies (default)
- policies create    - Create new policy (interactive wizard)
- policies edit      - Edit existing policy
- policies delete    - Delete a policy

WORKFLOW:
  1. policies create   -> Define which resources to manage
  2. lifecycle scan    -> Find resources matching policies
  3. lifecycle set-ttl -> Apply TTL to matched resources
""",
    no_args_is_help=False,
    invoke_without_command=True,
)


@policies_app.callback(invoke_without_command=True)
def policies_default(ctx: typer.Context):
    """List all lifecycle policies."""
    if ctx.invoked_subcommand is None:
        # Default behavior: list policies
        _list_policies()


def _list_policies():
    """List all lifecycle policies with details."""
    from tag_manager_cli.database.models import ResourceLifecyclePolicy

    with _get_db_session() as session:
        policies = session.query(ResourceLifecyclePolicy).order_by(
            ResourceLifecyclePolicy.priority,
            ResourceLifecyclePolicy.name
        ).all()

        if not policies:
            console.print("[yellow]No lifecycle policies configured.[/yellow]")
            console.print("\nCreate your first policy:")
            console.print("  [cyan]lifecycle policies create[/cyan]")
            return

        table = Table(title=f"Lifecycle Policies ({len(policies)})", show_header=True)
        table.add_column("Name", style="cyan", width=20)
        table.add_column("TTL", style="yellow", width=8)
        table.add_column("Resource Types", width=25)
        table.add_column("Enabled", width=8)
        table.add_column("Auto-Apply", width=10)
        table.add_column("Resources", width=10)

        for p in policies:
            resource_types = ", ".join(p.resource_types[:3]) if p.resource_types else "any"
            if p.resource_types and len(p.resource_types) > 3:
                resource_types += "..."

            table.add_row(
                p.name,
                f"{p.ttl_days}d",
                resource_types,
                "[green]Yes[/green]" if p.enabled else "[red]No[/red]",
                "[green]Yes[/green]" if p.auto_apply else "[dim]No[/dim]",
                str(p.resources_affected),
            )

        console.print(table)

        console.print("\n[bold]Commands:[/bold]")
        console.print("  [cyan]lifecycle policies create[/cyan]  - Create new policy")
        console.print("  [cyan]lifecycle policies edit <name>[/cyan]  - Edit policy")
        console.print("  [cyan]lifecycle policies delete <name>[/cyan]  - Delete policy")


@policies_app.command("list")
def policies_list_command():
    """List all lifecycle policies."""
    _list_policies()


# Available resource types for policy matching
RESOURCE_TYPES = [
    "ec2_instance", "ec2_volume", "ec2_snapshot", "ec2_ami",
    "lambda_function", "lambda_layer",
    "s3_bucket",
    "rds_instance", "rds_cluster", "rds_snapshot",
    "dynamodb_table",
    "elasticache_cluster",
    "ecs_cluster", "ecs_service", "ecs_task_definition",
    "eks_cluster",
    "sns_topic", "sqs_queue",
    "cloudwatch_alarm", "cloudwatch_log_group",
    "secretsmanager_secret",
    "kms_key",
]


@policies_app.command("create")
@requires_tier("lifecycle:policies")
def policies_create_command(
    name: Optional[str] = typer.Option(None, "--name", "-n", help="Policy name"),
    ttl_days: Optional[int] = typer.Option(None, "--ttl-days", "-d", help="TTL in days"),
    non_interactive: bool = typer.Option(False, "--non-interactive", help="Skip interactive prompts"),
):
    """
    Create a new lifecycle policy (interactive wizard).

    Policies define which resources to manage and their TTL settings.

    Examples:
        lifecycle policies create                           # Interactive wizard
        lifecycle policies create --name dev-cleanup       # Pre-fill name
        lifecycle policies create --name dev --ttl-days 30 # Quick create
    """
    from tag_manager_cli.database.models import ResourceLifecyclePolicy

    console.print("\n[bold blue]Create Lifecycle Policy[/bold blue]")
    console.print("This wizard helps you define which resources to manage.\n")

    # Step 1: Policy name
    if not name:
        name = Prompt.ask(
            "[bold]Step 1/5:[/bold] Policy name",
            default="dev-cleanup"
        )

    # Validate unique name
    with _get_db_session() as session:
        existing = session.query(ResourceLifecyclePolicy).filter(
            ResourceLifecyclePolicy.name == name
        ).first()
        if existing:
            console.print(f"[red]Error:[/red] Policy '{name}' already exists.")
            console.print(f"Use [cyan]lifecycle policies edit {name}[/cyan] to modify it.")
            raise typer.Exit(1)

    # Step 2: Description
    description = ""
    if not non_interactive:
        description = Prompt.ask(
            "[bold]Step 2/5:[/bold] Description (optional)",
            default=""
        )

    # Step 3: Resource types
    console.print("\n[bold]Step 3/5:[/bold] Select resource types to manage")
    console.print("[dim]Common types: ec2_instance, lambda_function, s3_bucket, rds_instance[/dim]")

    resource_type_input = Prompt.ask(
        "Resource types (comma-separated, or 'all' for all types)",
        default="ec2_instance,lambda_function"
    )

    if resource_type_input.lower() == "all":
        resource_types = RESOURCE_TYPES.copy()
    else:
        resource_types = [t.strip().lower() for t in resource_type_input.split(",")]
        # Validate resource types
        invalid = [t for t in resource_types if t not in RESOURCE_TYPES]
        if invalid:
            console.print(f"[yellow]Warning:[/yellow] Unknown types: {', '.join(invalid)}")
            console.print(f"[dim]Valid types: {', '.join(RESOURCE_TYPES[:8])}...[/dim]")

    # Step 4: Tag conditions
    console.print("\n[bold]Step 4/5:[/bold] Define tag conditions (which resources to match)")
    console.print("[dim]Examples: Environment=dev, Environment=staging, Team=platform[/dim]")

    conditions = {"tags": []}

    if not non_interactive:
        add_conditions = Confirm.ask("Add tag conditions?", default=True)

        while add_conditions:
            tag_key = Prompt.ask("Tag key", default="Environment")
            tag_operator = Prompt.ask(
                "Operator",
                choices=["equals", "not_equals", "contains", "exists", "not_exists"],
                default="equals"
            )
            tag_value = ""
            if tag_operator not in ["exists", "not_exists"]:
                tag_value = Prompt.ask("Tag value", default="dev")

            conditions["tags"].append({
                "field": f"tags.{tag_key}",
                "operator": tag_operator,
                "value": tag_value if tag_value else None,
            })

            console.print(f"[green][OK][/green] Added: {tag_key} {tag_operator} {tag_value or ''}")
            add_conditions = Confirm.ask("Add another condition?", default=False)

    # Exclusion patterns
    exclude_patterns = {"resource_names": [], "tags": []}

    if not non_interactive:
        console.print("\n[dim]Exclusion patterns prevent matching certain resources[/dim]")
        add_exclusions = Confirm.ask("Add exclusion patterns?", default=False)

        while add_exclusions:
            exclusion_type = Prompt.ask(
                "Exclude by",
                choices=["resource_name", "tag"],
                default="resource_name"
            )

            if exclusion_type == "resource_name":
                pattern = Prompt.ask("Resource name pattern (e.g., *-prod-*)", default="*-prod-*")
                exclude_patterns["resource_names"].append(pattern)
            else:
                tag_key = Prompt.ask("Tag key to exclude", default="Environment")
                tag_value = Prompt.ask("Tag value to exclude", default="production")
                exclude_patterns["tags"].append({"key": tag_key, "value": tag_value})

            add_exclusions = Confirm.ask("Add another exclusion?", default=False)

    # Step 5: TTL settings
    if not ttl_days:
        console.print("\n[bold]Step 5/5:[/bold] TTL settings")
        ttl_days = int(Prompt.ask("TTL (days until expiration)", default="30"))

    warning_schedule = [7, 3, 1]
    grace_period_days = 7
    auto_apply = True

    if not non_interactive:
        warning_input = Prompt.ask(
            "Warning days (comma-separated)",
            default="7,3,1"
        )
        warning_schedule = [int(d.strip()) for d in warning_input.split(",")]

        grace_period_days = int(Prompt.ask("Grace period after expiry (days)", default="7"))
        auto_apply = Confirm.ask("Auto-apply to matching resources?", default=True)

    # Default actions
    actions = [
        {"action": "warn", "trigger": "warning_threshold"},
        {"action": "delete", "trigger": "grace_period_end", "require_confirmation": True},
    ]

    # Summary
    console.print("\n" + "-" * 50)
    console.print("[bold]Policy Summary:[/bold]")
    console.print(f"  Name: {name}")
    console.print(f"  Description: {description or '(none)'}")
    console.print(f"  Resource types: {', '.join(resource_types[:5])}" + ("..." if len(resource_types) > 5 else ""))
    console.print(f"  Tag conditions: {len(conditions.get('tags', []))}")
    console.print(f"  Exclusions: {len(exclude_patterns.get('resource_names', [])) + len(exclude_patterns.get('tags', []))}")
    console.print(f"  TTL: {ttl_days} days")
    console.print(f"  Warning schedule: {warning_schedule}")
    console.print(f"  Grace period: {grace_period_days} days")
    console.print(f"  Auto-apply: {'Yes' if auto_apply else 'No'}")

    if not Confirm.ask("\nCreate this policy?", default=True):
        console.print("[yellow]Cancelled.[/yellow]")
        raise typer.Exit(0)

    # Create policy
    with _get_db_session() as session:
        policy = ResourceLifecyclePolicy(
            name=name,
            description=description or None,
            resource_types=resource_types,
            conditions=conditions,
            ttl_days=ttl_days,
            actions=actions,
            warning_days_before=warning_schedule[0] if warning_schedule else 7,
            warning_schedule=warning_schedule,
            grace_period_days=grace_period_days,
            auto_apply=auto_apply,
            exclude_patterns=exclude_patterns if any(exclude_patterns.values()) else None,
            enabled=True,
            require_confirmation=True,
            auto_delete_enabled=False,
        )
        session.add(policy)
        session.commit()

        console.print(f"\n[green][OK][/green] Policy '{name}' created successfully!")
        console.print("\n[bold]Next steps:[/bold]")
        console.print(f"  [cyan]lifecycle scan[/cyan]              # Find resources matching this policy")
        console.print(f"  [cyan]lifecycle set-ttl --policy {name}[/cyan]  # Apply TTL to matched resources")


@policies_app.command("edit")
@requires_tier("lifecycle:policies")
def policies_edit_command(
    name: str = typer.Argument(..., help="Policy name to edit"),
):
    """
    Edit an existing lifecycle policy.

    Examples:
        lifecycle policies edit dev-cleanup
    """
    from tag_manager_cli.database.models import ResourceLifecyclePolicy

    with _get_db_session() as session:
        policy = session.query(ResourceLifecyclePolicy).filter(
            ResourceLifecyclePolicy.name == name
        ).first()

        if not policy:
            console.print(f"[red]Error:[/red] Policy '{name}' not found.")
            console.print("\nAvailable policies:")
            policies = session.query(ResourceLifecyclePolicy.name).all()
            for p in policies:
                console.print(f"  - {p.name}")
            raise typer.Exit(1)

        console.print(f"\n[bold blue]Edit Policy: {name}[/bold blue]\n")
        console.print("[dim]Press Enter to keep current value[/dim]\n")

        # Edit fields
        new_description = Prompt.ask(
            "Description",
            default=policy.description or ""
        )
        if new_description != (policy.description or ""):
            policy.description = new_description or None

        new_ttl = Prompt.ask(
            "TTL (days)",
            default=str(policy.ttl_days)
        )
        policy.ttl_days = int(new_ttl)

        new_warning = Prompt.ask(
            "Warning schedule (comma-separated days)",
            default=",".join(str(d) for d in (policy.warning_schedule or [7, 3, 1]))
        )
        policy.warning_schedule = [int(d.strip()) for d in new_warning.split(",")]

        new_grace = Prompt.ask(
            "Grace period (days)",
            default=str(policy.grace_period_days or 7)
        )
        policy.grace_period_days = int(new_grace)

        new_enabled = Confirm.ask(
            "Enabled?",
            default=policy.enabled
        )
        policy.enabled = new_enabled

        new_auto_apply = Confirm.ask(
            "Auto-apply to matching resources?",
            default=policy.auto_apply
        )
        policy.auto_apply = new_auto_apply

        # Confirm
        if Confirm.ask("\nSave changes?", default=True):
            session.commit()
            console.print(f"\n[green][OK][/green] Policy '{name}' updated!")
        else:
            session.rollback()
            console.print("[yellow]Cancelled.[/yellow]")


@policies_app.command("delete")
@requires_tier("lifecycle:policies")
def policies_delete_command(
    name: Optional[str] = typer.Option(None, "--name", "-n", help="Policy name to delete"),
    force: bool = typer.Option(False, "--force", "-f", help="Skip confirmation"),
):
    """
    Delete a lifecycle policy.

    If no name is provided, shows an interactive list to select from.

    Examples:
        lifecycle policies delete                    # Interactive selection
        lifecycle policies delete --name dev-cleanup
        lifecycle policies delete --name old-policy --force
    """
    from tag_manager_cli.database.models import ResourceLifecyclePolicy

    with _get_db_session() as session:
        # If no name provided, show interactive selection
        if not name:
            policies = session.query(ResourceLifecyclePolicy).order_by(
                ResourceLifecyclePolicy.name
            ).all()

            if not policies:
                console.print("[yellow]No policies found.[/yellow]")
                raise typer.Exit(0)

            console.print("\n[bold]Select a policy to delete:[/bold]\n")
            for i, p in enumerate(policies, 1):
                status = "[green]enabled[/green]" if p.enabled else "[dim]disabled[/dim]"
                console.print(f"  {i}. {p.name} ({p.ttl_days}d TTL) - {status}")

            console.print(f"  0. Cancel\n")

            choice = Prompt.ask("Enter number", default="0")
            try:
                choice_num = int(choice)
                if choice_num == 0:
                    console.print("[yellow]Cancelled.[/yellow]")
                    raise typer.Exit(0)
                if choice_num < 1 or choice_num > len(policies):
                    console.print("[red]Invalid selection.[/red]")
                    raise typer.Exit(1)
                name = policies[choice_num - 1].name
            except ValueError:
                console.print("[red]Invalid input.[/red]")
                raise typer.Exit(1)

        policy = session.query(ResourceLifecyclePolicy).filter(
            ResourceLifecyclePolicy.name == name
        ).first()

        if not policy:
            console.print(f"[red]Error:[/red] Policy '{name}' not found.")
            raise typer.Exit(1)

        # Show policy info
        console.print(f"\n[bold]Policy: {name}[/bold]")
        console.print(f"  TTL: {policy.ttl_days} days")
        console.print(f"  Resources affected: {policy.resources_affected}")
        console.print(f"  Created: {policy.created_at.strftime('%Y-%m-%d') if policy.created_at else 'unknown'}")

        if not force:
            if not Confirm.ask(f"\n[red]Delete policy '{name}'?[/red]", default=False):
                console.print("[yellow]Cancelled.[/yellow]")
                raise typer.Exit(0)

        session.delete(policy)
        session.commit()

        console.print(f"\n[green][OK][/green] Policy '{name}' deleted.")


# Register the policies subcommand group
lifecycle_app.add_typer(policies_app, name="policies")

def _get_current_user() -> str:
    """Get current user identity for audit logging."""
    import os
    import getpass
    return os.environ.get('USER', getpass.getuser())


def _log_lifecycle_decision(
    session,
    resource,
    decision_type: str,
    previous_expires_at,
    new_expires_at,
    extension_days: Optional[int] = None,
    protection_reason: Optional[str] = None,
    decision_reason: Optional[str] = None,
):
    """Record a lifecycle decision in the database."""
    from tag_manager_cli.database.models import LifecycleDecision

    decision = LifecycleDecision(
        resource_arn=resource.resource_arn,
        resource_id=str(resource.id) if resource.id else None,
        decision_type=decision_type,
        decision_reason=decision_reason,
        previous_state=resource.lifecycle_state,
        new_state=resource.lifecycle_state,
        previous_expires_at=previous_expires_at,
        new_expires_at=new_expires_at,
        extension_days=extension_days,
        protection_reason=protection_reason,
        decided_by=_get_current_user(),
        decided_via='cli',
        executed=True,
        executed_at=datetime.now(timezone.utc),
    )
    session.add(decision)


def _log_lifecycle_audit(
    session,
    resource,
    operation: str,
    old_state: str,
    new_state: str,
    old_expires_at,
    new_expires_at,
    details: Optional[dict] = None,
):
    """Record a lifecycle operation in the audit log."""
    from tag_manager_cli.database.models import LifecycleAuditLog

    audit = LifecycleAuditLog(
        resource_arn=resource.resource_arn,
        resource_id=str(resource.id) if resource.id else None,
        operation=operation,
        operation_details=details,
        old_state=old_state,
        new_state=new_state,
        old_expires_at=old_expires_at,
        new_expires_at=new_expires_at,
        success=True,
        executed_by=_get_current_user(),
    )
    session.add(audit)


@lifecycle_app.command("extend")
def extend_command(
    days: int = typer.Option(30, "--days", "-d", help="Days to extend TTL"),
    resource_arn: Optional[str] = typer.Option(None, "--resource-arn", "-r", help="Specific resource ARN"),
    services: Optional[str] = typer.Option(None, "--services", "-s", help="Filter by services (comma-separated)"),
    expiring_only: bool = typer.Option(True, "--expiring-only", help="Only extend resources expiring within 7 days"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Preview without making changes"),
    force: bool = typer.Option(False, "--force", "-f", help="Skip confirmation"),
):
    """
    Extend TTL for resources.

    Add more time before resources expire. By default, only extends resources
    that are expiring within 7 days or already expired.

    Examples:
        lifecycle extend --days 30 --resource-arn <arn>   # Extend specific resource
        lifecycle extend --days 14 --services lambda      # Extend all Lambda functions
        lifecycle extend --days 30 --expiring-only        # Only near-expiring resources
        lifecycle extend --days 7 --dry-run               # Preview changes
    """
    from tag_manager_cli.database.models import Resource

    if not resource_arn and not services:
        console.print("[red]Error:[/red] Specify --resource-arn or --services to select resources.")
        raise typer.Exit(1)

    if days <= 0:
        console.print("[red]Error:[/red] Days must be positive.")
        raise typer.Exit(1)

    now = datetime.now(timezone.utc)
    new_expires_at = now + timedelta(days=days)

    with _get_db_session() as session:
        # Build query
        query = session.query(Resource).filter(Resource.expires_at.isnot(None))

        if resource_arn:
            query = query.filter(Resource.resource_arn == resource_arn)
        elif services:
            service_list = [s.strip().lower() for s in services.split(',')]
            query = query.filter(Resource.service_name.in_(service_list))

        if expiring_only and not resource_arn:
            # Only resources expiring within 7 days or already expired
            threshold = now + timedelta(days=7)
            query = query.filter(Resource.expires_at <= threshold)

        resources = query.all()

        if not resources:
            if resource_arn:
                console.print(f"[yellow]Resource not found or has no TTL set:[/yellow] {resource_arn}")
            else:
                console.print("[yellow]No matching resources found.[/yellow]")
                if expiring_only:
                    console.print("Try [cyan]--no-expiring-only[/cyan] to extend all resources with TTL.")
            return

        # Preview
        console.print(f"\n[bold blue]Extending TTL by {days} days[/bold blue]")
        console.print(f"New expiration: {new_expires_at.strftime('%Y-%m-%d')}\n")

        table = Table(title=f"Resources to Extend ({len(resources)})", show_header=True)
        table.add_column("Service", style="cyan", width=10)
        table.add_column("Resource ID", width=35)
        table.add_column("Current Expires", style="yellow", width=14)
        table.add_column("New Expires", style="green", width=14)

        for r in resources[:20]:
            current_exp = r.expires_at
            if current_exp and current_exp.tzinfo is None:
                current_exp = current_exp.replace(tzinfo=timezone.utc)

            table.add_row(
                r.service_name.upper(),
                r.resource_id[:33] + "..." if len(r.resource_id) > 35 else r.resource_id,
                current_exp.strftime('%Y-%m-%d') if current_exp else "N/A",
                new_expires_at.strftime('%Y-%m-%d'),
            )

        if len(resources) > 20:
            table.add_row("...", f"and {len(resources) - 20} more", "", "")

        console.print(table)

        if dry_run:
            console.print("\n[yellow][DRY RUN][/yellow] No changes made.")
            return

        # Confirmation
        if not force:
            if not Confirm.ask(f"\nExtend TTL for {len(resources)} resource(s)?"):
                console.print("[yellow]Cancelled.[/yellow]")
                return

        # Apply changes
        extended_count = 0
        aws_tag_success = 0
        aws_tag_failed = 0

        # Import AWS tagging function
        from tag_manager_cli.commands.unified_tags import _apply_tags_to_aws_resource

        console.print("\n[bold]Extending TTL...[/bold]")

        for r in resources:
            old_expires_at = r.expires_at

            # Update AWS tags with new TTL
            aws_tags = {
                'bluearch:ttl': new_expires_at.strftime('%Y-%m-%d'),
            }

            try:
                if r.resource_arn:
                    tag_success = _apply_tags_to_aws_resource(
                        r.resource_arn,
                        aws_tags,
                        r.service_name,
                        account_id=getattr(r, "account_id", None),
                        region=getattr(r, "region", None),
                        resource_id=getattr(r, "resource_id", None),
                    )
                    if tag_success:
                        aws_tag_success += 1
                    else:
                        aws_tag_failed += 1
                else:
                    aws_tag_failed += 1
            except Exception as e:
                console.print(f"[dim]AWS tag failed for {r.resource_id}: {e}[/dim]")
                aws_tag_failed += 1

            # Update database
            r.expires_at = new_expires_at
            r.lifecycle_state = 'active'  # Reset state if it was warned/expired
            r.ttl_source = 'manual'  # Mark as manually extended

            # Log decision
            _log_lifecycle_decision(
                session, r,
                decision_type='extend',
                previous_expires_at=old_expires_at,
                new_expires_at=new_expires_at,
                extension_days=days,
                decision_reason=f"Extended by {days} days via CLI",
            )

            # Log audit
            _log_lifecycle_audit(
                session, r,
                operation='TTL_EXTENDED',
                old_state=r.lifecycle_state or 'active',
                new_state='active',
                old_expires_at=old_expires_at,
                new_expires_at=new_expires_at,
                details={'extension_days': days, 'aws_tags_applied': aws_tags},
            )

            extended_count += 1

        session.commit()

        console.print(f"\n[green][OK][/green] Extended TTL for {extended_count} resource(s)")
        console.print(f"    New expiration date: {new_expires_at.strftime('%Y-%m-%d')}")
        console.print(f"    AWS tags updated: {aws_tag_success}")
        if aws_tag_failed > 0:
            console.print(f"    [yellow]AWS tags failed: {aws_tag_failed}[/yellow]")


@lifecycle_app.command("protect")
def protect_command(
    resource_arn: Optional[str] = typer.Option(None, "--resource-arn", "-r", help="Resource ARN to protect"),
    services: Optional[str] = typer.Option(None, "--services", "-s", help="Filter by services (comma-separated)"),
    reason: Optional[str] = typer.Option(None, "--reason", help="Reason for protection"),
    unprotect: bool = typer.Option(False, "--unprotect", "-u", help="Remove protection"),
    list_protected: bool = typer.Option(False, "--list", "-l", help="List all protected resources"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Preview without making changes"),
    force: bool = typer.Option(False, "--force", "-f", help="Skip confirmation"),
):
    """
    Protect resources from automated deletion.

    Protected resources are excluded from lifecycle cleanup, regardless of TTL.
    Use this for production resources or anything that shouldn't be auto-deleted.

    Examples:
        lifecycle protect --resource-arn <arn> --reason "Production DB"
        lifecycle protect --services rds --reason "All RDS protected"
        lifecycle protect --unprotect --resource-arn <arn>
        lifecycle protect --list                           # List protected resources
    """
    from tag_manager_cli.database.models import Resource

    # List mode
    if list_protected:
        with _get_db_session() as session:
            protected = session.query(Resource).filter(Resource.protected == True).all()

            if not protected:
                console.print("[yellow]No protected resources found.[/yellow]")
                return

            table = Table(title=f"Protected Resources ({len(protected)})", show_header=True)
            table.add_column("Service", style="cyan", width=10)
            table.add_column("Resource ID", width=35)
            table.add_column("Region", width=12)
            table.add_column("Expires", style="yellow", width=12)

            for r in protected:
                expires_str = "N/A"
                if r.expires_at:
                    exp = r.expires_at
                    if exp.tzinfo is None:
                        exp = exp.replace(tzinfo=timezone.utc)
                    expires_str = exp.strftime('%Y-%m-%d')

                table.add_row(
                    r.service_name.upper(),
                    r.resource_id[:33] + "..." if len(r.resource_id) > 35 else r.resource_id,
                    r.region,
                    expires_str,
                )

            console.print(table)
            console.print(f"\nTo remove protection: [cyan]lifecycle protect --unprotect --resource-arn <arn>[/cyan]")
        return

    # Protect/unprotect mode
    if not resource_arn and not services:
        console.print("[red]Error:[/red] Specify --resource-arn or --services, or use --list to view protected resources.")
        raise typer.Exit(1)

    action = "unprotect" if unprotect else "protect"
    action_past = "unprotected" if unprotect else "protected"

    with _get_db_session() as session:
        # Build query
        query = session.query(Resource)

        if resource_arn:
            query = query.filter(Resource.resource_arn == resource_arn)
        elif services:
            service_list = [s.strip().lower() for s in services.split(',')]
            query = query.filter(Resource.service_name.in_(service_list))

        # Filter by current protection state
        if unprotect:
            query = query.filter(Resource.protected == True)
        else:
            query = query.filter(Resource.protected == False)

        resources = query.all()

        if not resources:
            if resource_arn:
                console.print(f"[yellow]Resource not found or already {action_past}:[/yellow] {resource_arn}")
            else:
                console.print(f"[yellow]No resources to {action}.[/yellow]")
            return

        # Preview
        console.print(f"\n[bold blue]{'Removing protection from' if unprotect else 'Protecting'} resources[/bold blue]")
        if reason and not unprotect:
            console.print(f"Reason: {reason}\n")

        table = Table(title=f"Resources to {action.title()} ({len(resources)})", show_header=True)
        table.add_column("Service", style="cyan", width=10)
        table.add_column("Resource ID", width=40)
        table.add_column("Region", width=12)

        for r in resources[:20]:
            table.add_row(
                r.service_name.upper(),
                r.resource_id[:38] + "..." if len(r.resource_id) > 40 else r.resource_id,
                r.region,
            )

        if len(resources) > 20:
            table.add_row("...", f"and {len(resources) - 20} more", "")

        console.print(table)

        if dry_run:
            console.print("\n[yellow][DRY RUN][/yellow] No changes made.")
            return

        # Confirmation
        if not force:
            if not Confirm.ask(f"\n{action.title()} {len(resources)} resource(s)?"):
                console.print("[yellow]Cancelled.[/yellow]")
                return

        # Apply changes
        count = 0
        aws_tag_success = 0
        aws_tag_failed = 0

        # Import AWS tagging function
        from tag_manager_cli.commands.unified_tags import _apply_tags_to_aws_resource

        console.print(f"\n[bold]{'Removing protection...' if unprotect else 'Protecting resources...'}[/bold]")

        for r in resources:
            old_protected = r.protected

            # Update AWS tags for protection status
            if unprotect:
                # Remove protection tag by setting to empty/false
                aws_tags = {'bluearch:protected': 'false'}
            else:
                aws_tags = {
                    'bluearch:protected': 'true',
                }
                if reason:
                    aws_tags['bluearch:protected-reason'] = reason[:255]  # AWS tag value limit

            try:
                if r.resource_arn:
                    tag_success = _apply_tags_to_aws_resource(
                        r.resource_arn,
                        aws_tags,
                        r.service_name,
                        account_id=getattr(r, "account_id", None),
                        region=getattr(r, "region", None),
                        resource_id=getattr(r, "resource_id", None),
                    )
                    if tag_success:
                        aws_tag_success += 1
                    else:
                        aws_tag_failed += 1
                else:
                    aws_tag_failed += 1
            except Exception as e:
                console.print(f"[dim]AWS tag failed for {r.resource_id}: {e}[/dim]")
                aws_tag_failed += 1

            # Update database
            r.protected = not unprotect

            # Log decision
            _log_lifecycle_decision(
                session, r,
                decision_type='unprotect' if unprotect else 'protect',
                previous_expires_at=r.expires_at,
                new_expires_at=r.expires_at,
                protection_reason=reason,
                decision_reason=f"{'Unprotected' if unprotect else 'Protected'} via CLI" + (f": {reason}" if reason else ""),
            )

            # Log audit
            _log_lifecycle_audit(
                session, r,
                operation='PROTECTION_REMOVED' if unprotect else 'PROTECTED',
                old_state=r.lifecycle_state or 'active',
                new_state=r.lifecycle_state or 'active',
                old_expires_at=r.expires_at,
                new_expires_at=r.expires_at,
                details={'reason': reason, 'previous_protected': old_protected, 'aws_tags_applied': aws_tags},
            )

            count += 1

        session.commit()

        console.print(f"\n[green][OK][/green] {action_past.title()} {count} resource(s)")
        console.print(f"    AWS tags updated: {aws_tag_success}")
        if aws_tag_failed > 0:
            console.print(f"    [yellow]AWS tags failed: {aws_tag_failed}[/yellow]")
        if not unprotect:
            console.print("These resources will be excluded from automated deletion.")


def _interactive_review_resource(session, resource, index: int, total: int) -> Optional[str]:
    """Interactive review of a single resource. Returns action taken or None if quit."""
    from rich.panel import Panel
    from rich.text import Text

    now = datetime.now(timezone.utc)
    expires_at = resource.expires_at
    if expires_at and expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)

    days_until = (expires_at - now).days if expires_at else None
    days_str = f"{days_until} days" if days_until and days_until > 0 else "EXPIRED" if days_until and days_until <= 0 else "N/A"

    # Build resource info
    info_lines = [
        f"[bold cyan]{resource.service_name.upper()}[/bold cyan] - {resource.resource_type}",
        f"ID: {resource.resource_id}",
        f"Region: {resource.region} | Account: {resource.account_id}",
        f"Expires: [{'red' if days_until and days_until <= 0 else 'yellow'}]{days_str}[/]" + (f" ({expires_at.strftime('%Y-%m-%d')})" if expires_at else ""),
    ]

    # Show which policy applies to this resource
    policy_label = None
    if resource.lifecycle_policy and resource.lifecycle_policy.name:
        policy_label = resource.lifecycle_policy.name
        source = resource.policy_source or "local"
        info_lines.append(f"Policy: [cyan]{policy_label}[/cyan] ({source})")
    elif resource.org_policy_name:
        info_lines.append(f"Policy: [cyan]{resource.org_policy_name}[/cyan] (aws_org)")
    elif resource.policy_source:
        info_lines.append(f"Policy: [dim]{resource.policy_source}[/dim]")

    if resource.protected:
        info_lines.append("[blue]Status: PROTECTED[/blue]")

    # Show tags if available
    if resource.current_tags:
        tags = resource.current_tags if isinstance(resource.current_tags, dict) else {}
        if tags:
            tag_strs = [f"{k}={v}" for k, v in list(tags.items())[:3]]
            info_lines.append(f"Tags: {', '.join(tag_strs)}" + (" ..." if len(tags) > 3 else ""))

    panel_content = "\n".join(info_lines)
    panel = Panel(
        panel_content,
        title=f"[bold]Resource Review[/bold] [{index}/{total}]",
        border_style="blue",
        padding=(1, 2),
    )
    console.print(panel)

    # Show actions
    console.print("\n[bold]Actions:[/bold]")
    console.print("  [E] Extend TTL (30 days)    [P] Protect from deletion")
    console.print("  [D] Delete now              [S] Skip to next")
    console.print("  [Q] Quit review\n")

    while True:
        choice = Prompt.ask("Choice", choices=["e", "p", "d", "s", "q", "E", "P", "D", "S", "Q"], default="s")
        choice = choice.lower()

        if choice == 'q':
            return None  # Quit

        if choice == 's':
            console.print("[dim]Skipped[/dim]\n")
            return 'skip'

        if choice == 'e':
            # Extend by 30 days
            days = 30
            custom = Prompt.ask("Days to extend", default="30")
            try:
                days = int(custom)
            except ValueError:
                days = 30

            old_expires = resource.expires_at
            new_expires = now + timedelta(days=days)
            resource.expires_at = new_expires
            resource.lifecycle_state = 'active'
            resource.ttl_source = 'manual'

            _log_lifecycle_decision(
                session, resource,
                decision_type='extend',
                previous_expires_at=old_expires,
                new_expires_at=new_expires,
                extension_days=days,
                decision_reason=f"Extended by {days} days via review",
            )
            _log_lifecycle_audit(
                session, resource,
                operation='TTL_EXTENDED',
                old_state=resource.lifecycle_state or 'active',
                new_state='active',
                old_expires_at=old_expires,
                new_expires_at=new_expires,
                details={'extension_days': days, 'via': 'review'},
            )

            console.print(f"[green][OK][/green] Extended by {days} days (expires: {new_expires.strftime('%Y-%m-%d')})\n")
            return 'extend'

        if choice == 'p':
            # Protect
            reason = Prompt.ask("Protection reason (optional)", default="")
            resource.protected = True

            _log_lifecycle_decision(
                session, resource,
                decision_type='protect',
                previous_expires_at=resource.expires_at,
                new_expires_at=resource.expires_at,
                protection_reason=reason or None,
                decision_reason=f"Protected via review" + (f": {reason}" if reason else ""),
            )
            _log_lifecycle_audit(
                session, resource,
                operation='PROTECTED',
                old_state=resource.lifecycle_state or 'active',
                new_state=resource.lifecycle_state or 'active',
                old_expires_at=resource.expires_at,
                new_expires_at=resource.expires_at,
                details={'reason': reason, 'via': 'review'},
            )

            console.print(f"[green][OK][/green] Resource protected\n")
            return 'protect'

        if choice == 'd':
            # Delete - just mark for deletion, don't actually delete
            if not Confirm.ask("[red]Mark for immediate deletion?[/red]"):
                console.print("[yellow]Cancelled[/yellow]\n")
                continue

            resource.lifecycle_state = 'marked_for_deletion'
            resource.delete_after = now

            _log_lifecycle_decision(
                session, resource,
                decision_type='terminate',
                previous_expires_at=resource.expires_at,
                new_expires_at=resource.expires_at,
                decision_reason="Marked for deletion via review",
            )
            _log_lifecycle_audit(
                session, resource,
                operation='MARKED_FOR_DELETION',
                old_state=resource.lifecycle_state or 'active',
                new_state='marked_for_deletion',
                old_expires_at=resource.expires_at,
                new_expires_at=resource.expires_at,
                details={'via': 'review'},
            )

            console.print(f"[red][OK][/red] Marked for deletion\n")
            return 'delete'


@lifecycle_app.command("review")
def review_command(
    services: Optional[str] = typer.Option(None, "--services", "-s", help="Filter by services (comma-separated)"),
    include_active: bool = typer.Option(False, "--include-active", help="Include all resources with TTL, not just expiring"),
    days_threshold: int = typer.Option(7, "--days", "-d", help="Review resources expiring within N days"),
):
    """
    Interactive review of expiring resources.

    Review each expiring resource and decide: extend TTL, protect, delete, or skip.
    Changes are committed after each action.

    Examples:
        lifecycle review                           # Review resources expiring in 7 days
        lifecycle review --days 14                 # Review expiring in 14 days
        lifecycle review --services lambda,ec2    # Filter by service
        lifecycle review --include-active          # Review all resources with TTL
    """
    from tag_manager_cli.database.models import Resource

    now = datetime.now(timezone.utc)
    threshold = now + timedelta(days=days_threshold)

    with _get_db_session() as session:
        # Build query
        query = session.query(Resource).filter(
            Resource.expires_at.isnot(None),
            Resource.protected == False,  # Skip already protected
        )

        if services:
            service_list = [s.strip().lower() for s in services.split(',')]
            query = query.filter(Resource.service_name.in_(service_list))

        if not include_active:
            # Only expiring/expired resources
            query = query.filter(Resource.expires_at <= threshold)

        # Order by expiration (most urgent first)
        query = query.order_by(Resource.expires_at.asc())

        resources = query.all()

        if not resources:
            console.print("[yellow]No resources to review.[/yellow]")
            if not include_active:
                console.print(f"No resources expiring within {days_threshold} days.")
                console.print("Try [cyan]--include-active[/cyan] to review all resources with TTL.")
            return

        # Summary
        console.print(f"\n[bold blue]Resource Review Mode[/bold blue]")
        console.print(f"Found {len(resources)} resource(s) to review")
        console.print(f"Filter: Expiring within {days_threshold} days" + (f", services: {services}" if services else ""))
        console.print("\n" + "-" * 50 + "\n")

        # Stats tracking
        stats = {'extend': 0, 'protect': 0, 'delete': 0, 'skip': 0}

        for i, resource in enumerate(resources, 1):
            action = _interactive_review_resource(session, resource, i, len(resources))

            if action is None:
                # User quit
                console.print("[yellow]Review cancelled.[/yellow]")
                break

            if action in stats:
                stats[action] += 1

            # Commit after each action
            session.commit()

        # Summary
        console.print("-" * 50)
        console.print("\n[bold]Review Summary:[/bold]")
        console.print(f"  Extended:  {stats['extend']}")
        console.print(f"  Protected: {stats['protect']}")
        console.print(f"  Deleted:   {stats['delete']}")
        console.print(f"  Skipped:   {stats['skip']}")

        if stats['delete'] > 0:
            console.print(f"\n[yellow]Note:[/yellow] {stats['delete']} resource(s) marked for deletion.")
            console.print("Run [cyan]lifecycle delete[/cyan] to execute deletions.")


@lifecycle_app.command("notify-setup")
def notify_setup_command(
    webhook_url: Optional[str] = typer.Option(None, "--webhook-url", "-w", help="Slack webhook URL"),
    channel: str = typer.Option("#aws-alerts", "--channel", "-c", help="Channel name (display only)"),
    warning_days: str = typer.Option("7,3,1", "--warning-days", help="Comma-separated warning days"),
    disable: bool = typer.Option(False, "--disable", help="Disable notifications"),
    show: bool = typer.Option(False, "--show", help="Show current configuration"),
):
    """
    Configure Slack notifications for lifecycle events.

    Set up a Slack Incoming Webhook to receive notifications when resources
    are approaching expiration.

    Examples:
        lifecycle notify-setup                             # Interactive setup
        lifecycle notify-setup --webhook-url <url>         # Direct setup
        lifecycle notify-setup --show                      # Show current config
        lifecycle notify-setup --disable                   # Disable notifications
    """
    from tag_manager_cli.services.slack_notification_service import slack_notification_service

    # Show current config
    if show:
        config = slack_notification_service.get_config()
        console.print("\n[bold]Current Slack Configuration:[/bold]\n")

        if config.webhook_url:
            # Mask the webhook URL for security
            masked = config.webhook_url[:35] + "..." + config.webhook_url[-10:]
            console.print(f"  Webhook URL: {masked}")
        else:
            console.print("  Webhook URL: [yellow]Not configured[/yellow]")

        console.print(f"  Channel: {config.channel}")
        console.print(f"  Warning Days: {config.warning_days}")
        console.print(f"  Enabled: {'[green]Yes[/green]' if config.enabled else '[red]No[/red]'}")
        console.print(f"  Max Resources/Message: {config.max_resources_per_message}")

        if not config.webhook_url:
            console.print("\nRun [cyan]lifecycle notify-setup[/cyan] to configure.")
        return

    # Disable
    if disable:
        success, msg = slack_notification_service.disable()
        if success:
            console.print(f"[green][OK][/green] {msg}")
        else:
            console.print(f"[red]Error:[/red] {msg}")
        return

    # Interactive or direct setup
    if not webhook_url:
        console.print("\n[bold blue]Slack Notification Setup[/bold blue]\n")
        console.print("To set up Slack notifications, you need an Incoming Webhook URL.")
        console.print("\n[bold]Steps to create a webhook:[/bold]")
        console.print("1. Go to https://api.slack.com/apps")
        console.print("2. Create a new app (or select existing)")
        console.print("3. Go to 'Incoming Webhooks' and activate")
        console.print("4. Click 'Add New Webhook to Workspace'")
        console.print("5. Select a channel and authorize")
        console.print("6. Copy the webhook URL\n")

        webhook_url = Prompt.ask("Paste your Slack webhook URL")

    if not webhook_url:
        console.print("[yellow]Cancelled.[/yellow]")
        return

    # Parse warning days
    try:
        days_list = [int(d.strip()) for d in warning_days.split(",")]
    except ValueError:
        console.print("[red]Error:[/red] Invalid warning days format. Use comma-separated numbers.")
        raise typer.Exit(1)

    # Configure
    success, msg = slack_notification_service.configure(
        webhook_url=webhook_url,
        channel=channel,
        warning_days=days_list,
        enabled=True,
    )

    if not success:
        console.print(f"[red]Error:[/red] {msg}")
        raise typer.Exit(1)

    console.print(f"[green][OK][/green] {msg}")

    # Test the webhook
    if Confirm.ask("\nSend a test notification?", default=True):
        result = slack_notification_service.test_webhook(webhook_url)
        if result.success:
            console.print("[green][OK][/green] Test notification sent successfully!")
        else:
            console.print(f"[red]Error:[/red] {result.message}")
            if result.error_details:
                console.print(f"  Details: {result.error_details}")

    console.print("\n[bold]Next steps:[/bold]")
    console.print("  [cyan]lifecycle notify --test[/cyan]     # Send another test")
    console.print("  [cyan]lifecycle notify[/cyan]            # Send pending notifications")
    console.print("  [cyan]lifecycle notify-setup --show[/cyan]  # View configuration")


@lifecycle_app.command("notify")
def notify_command(
    dry_run: bool = typer.Option(False, "--dry-run", help="Preview without sending"),
    test: bool = typer.Option(False, "--test", help="Send a test notification"),
    summary: bool = typer.Option(False, "--summary", help="Send summary instead of individual warnings"),
    days: int = typer.Option(7, "--days", "-d", help="Include resources expiring within N days"),
):
    """
    Send Slack notifications for expiring resources.

    Sends notifications for resources approaching expiration based on the
    configured warning schedule (default: 7, 3, 1 days before expiry).

    Examples:
        lifecycle notify                    # Send pending notifications
        lifecycle notify --test             # Send test notification
        lifecycle notify --summary          # Send summary of all expiring
        lifecycle notify --dry-run          # Preview without sending
    """
    from tag_manager_cli.services.slack_notification_service import slack_notification_service
    from tag_manager_cli.database.models import Resource, LifecycleNotification
    import uuid

    # Check if configured
    if not slack_notification_service.is_configured():
        console.print("[yellow]Slack notifications not configured.[/yellow]")
        console.print("Run [cyan]lifecycle notify-setup[/cyan] to configure.")
        raise typer.Exit(1)

    # Test mode
    if test:
        console.print("[bold blue]Sending test notification...[/bold blue]")
        result = slack_notification_service.test_webhook()
        if result.success:
            console.print("[green][OK][/green] Test notification sent!")
        else:
            console.print(f"[red]Error:[/red] {result.message}")
            if result.error_details:
                console.print(f"  Details: {result.error_details}")
        return

    config = slack_notification_service.get_config()
    now = datetime.now(timezone.utc)
    batch_id = str(uuid.uuid4())

    with _get_db_session() as session:
        # Get resources with TTL
        query = session.query(Resource).filter(
            Resource.expires_at.isnot(None),
            Resource.protected == False,
        )

        resources = query.all()

        if not resources:
            console.print("[yellow]No resources with TTL found.[/yellow]")
            return

        # Categorize by days until expiry
        expired = []
        expiring_by_day = {d: [] for d in config.warning_days}

        for r in resources:
            expires_at = r.expires_at
            if expires_at.tzinfo is None:
                expires_at = expires_at.replace(tzinfo=timezone.utc)

            days_until = (expires_at - now).days

            if days_until < 0:
                expired.append(r)
            else:
                for threshold in config.warning_days:
                    if days_until <= threshold:
                        expiring_by_day[threshold].append(r)
                        break

        # Summary mode
        if summary:
            total = len(resources)
            protected_count = session.query(Resource).filter(
                Resource.protected == True
            ).count()

            summary_data = {
                "total_resources": total,
                "expired": len(expired),
                "expiring_1d": len([r for r in resources if 0 <= (r.expires_at.replace(tzinfo=timezone.utc) if r.expires_at.tzinfo is None else r.expires_at - now).days <= 1]),
                "expiring_3d": len([r for r in resources if 0 <= (r.expires_at.replace(tzinfo=timezone.utc) if r.expires_at.tzinfo is None else r.expires_at - now).days <= 3]),
                "expiring_7d": len([r for r in resources if 0 <= (r.expires_at.replace(tzinfo=timezone.utc) if r.expires_at.tzinfo is None else r.expires_at - now).days <= 7]),
                "protected": protected_count,
            }

            console.print("\n[bold]Lifecycle Summary:[/bold]")
            console.print(f"  Total with TTL: {total}")
            console.print(f"  Expired: {len(expired)}")
            console.print(f"  Expiring in 7 days: {summary_data['expiring_7d']}")
            console.print(f"  Protected: {protected_count}")

            if dry_run:
                console.print("\n[yellow][DRY RUN][/yellow] Would send summary notification.")
                return

            result = slack_notification_service.send_batch_summary(summary_data, batch_id)
            if result.success:
                console.print("\n[green][OK][/green] Summary notification sent!")
            else:
                console.print(f"\n[red]Error:[/red] {result.message}")
            return

        # Individual warning notifications
        notifications_to_send = []

        # Expired resources
        if expired:
            notifications_to_send.append({
                "days": 0,
                "resources": expired,
                "label": "EXPIRED",
            })

        # Expiring resources by threshold
        for threshold in sorted(config.warning_days):
            resources_at_threshold = expiring_by_day.get(threshold, [])
            if resources_at_threshold:
                notifications_to_send.append({
                    "days": threshold,
                    "resources": resources_at_threshold,
                    "label": f"Expiring in {threshold}d",
                })

        if not notifications_to_send:
            console.print("[green]No resources need notification.[/green]")
            return

        # Preview
        console.print(f"\n[bold blue]Notifications to Send[/bold blue]\n")
        for n in notifications_to_send:
            console.print(f"  {n['label']}: {len(n['resources'])} resource(s)")

        if dry_run:
            console.print("\n[yellow][DRY RUN][/yellow] No notifications sent.")
            return

        # Send notifications
        sent_count = 0
        failed_count = 0

        for n in notifications_to_send:
            resource_data = [
                {
                    "resource_arn": r.resource_arn,
                    "resource_id": r.resource_id,
                    "service_name": r.service_name,
                    "region": r.region,
                    "expires_at": r.expires_at.isoformat() if r.expires_at else None,
                }
                for r in n["resources"]
            ]

            result = slack_notification_service.send_expiration_warning(
                resources=resource_data,
                days_until_expiry=n["days"],
                batch_id=batch_id,
            )

            if result.success:
                sent_count += 1

                # Record notification in database
                for r in n["resources"]:
                    notification = LifecycleNotification(
                        batch_id=batch_id,
                        resource_arn=r.resource_arn,
                        resource_id=str(r.id) if r.id else None,
                        notification_type=f"warning_{n['days']}d" if n["days"] > 0 else "expired",
                        channel="slack",
                        status="sent",
                        message_summary=f"{n['label']} notification",
                        sent_at=now,
                        expires_at=r.expires_at,
                        days_until_expiry=n["days"],
                    )
                    session.add(notification)

                console.print(f"  [green][OK][/green] Sent: {n['label']}")
            else:
                failed_count += 1
                console.print(f"  [red][FAIL][/red] {n['label']}: {result.message}")

        session.commit()

        # Summary
        console.print(f"\n[bold]Notification Results:[/bold]")
        console.print(f"  Sent: {sent_count}")
        if failed_count:
            console.print(f"  Failed: {failed_count}")


# Export for main.py
__all__ = ['lifecycle_app']
