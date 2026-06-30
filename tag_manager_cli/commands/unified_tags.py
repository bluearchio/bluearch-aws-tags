"""Unified tag management commands for Tag Manager CLI."""

import json
import time
import typer
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional, List, Dict, Any
from rich.console import Console
from ..utils.console_safe import safe_print, safe_console
from rich.table import Table
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TaskProgressColumn
from rich.tree import Tree
from rich.live import Live
from rich.prompt import Prompt, Confirm
from rich.panel import Panel
from rich import box

from ..database.connection import get_db_session
from ..database.models import Resource, TaggingRule, TaggingAuditLog, ResourceLifecyclePolicy, LifecycleAuditLog, TaggingExecution
from ..utils.aws_auth import aws_auth
from ..utils.env_config import settings
from ..utils.error_handlers import (
    require_aws_credentials,
    require_database,
    require_discovery,
    handle_aws_errors,
    handle_database_errors,
    handle_all_errors
)
from ..utils.execution_tracking import (
    ExecutionTracker, track_execution, create_manual_execution,
    create_bulk_execution, get_execution_history, get_execution_details
)
# TODO: Worker tasks disabled - container-free architecture
# from ..workers.tagging_tasks import apply_tags_to_aws_resource, get_applicable_tagging_rules, get_tagging_statistics, bulk_apply_tagging_rules
# TODO: CloudTrail - Disabled temporarily, will be re-enabled in future
# from ..workers.cloudtrail_tasks import get_cloudtrail_processing_stats
# from ..workers.rollback_tasks import rollback_execution, validate_rollback_feasibility

# Stub functions for worker tasks (container-free architecture)
def apply_tags_to_aws_resource(resource_arn: str, tags: dict) -> bool:
    """Apply tags to AWS resource - stub for container-free architecture."""
    # Return True for now - actual implementation happens later in the file
    return True

def get_applicable_tagging_rules(*args, **kwargs):
    """Get applicable tagging rules - stub for container-free architecture."""
    return []

def get_tagging_statistics(*args, **kwargs):
    """Get tagging statistics - stub for container-free architecture."""
    return {'total_operations_24h': 0, 'stats': {}}

def bulk_apply_tagging_rules(*args, **kwargs):
    """Bulk apply tagging rules - stub for container-free architecture."""
    class MockTask:
        def delay(self, *args, **kwargs):
            return MockResult()
    class MockResult:
        id = 'mock-task-id'
    return MockTask()

def rollback_execution(*args, **kwargs):
    """Rollback execution - stub for container-free architecture."""
    return {'status': 'completed', 'rollback_execution_id': None}

def validate_rollback_feasibility(*args, **kwargs):
    """Validate rollback feasibility - stub for container-free architecture."""
    return {'feasible': True}


def _get_delete_client(resource, service_name: str):
    """Get a boto3 client for the resource's account and region.

    Uses cross-account role assumption when the resource belongs to
    a different account than the current session.
    """
    account_id = getattr(resource, 'account_id', None)
    region = resource.region
    if account_id:
        return aws_auth.get_client_for_account(account_id, service_name, region)
    # Fallback: no account_id on resource, use current session
    session = aws_auth.initialize_session()
    return session.client(service_name, region_name=region)


def _ensure_managed_tag(resource) -> None:
    """Tag the resource with ManagedBy=tag-manager-cli before deletion.

    The cross-account BlueArchRole requires this tag on resources as a
    condition for delete actions.  Uses _apply_enforcement_tags which is
    already cross-account aware.

    Raises RuntimeError if tagging fails, so the caller gets a clear error
    instead of a confusing AccessDeniedException on the delete call.
    """
    import logging
    logger = logging.getLogger(__name__)

    resource_type = getattr(resource, 'resource_type', '')
    # S3 buckets are blocked from deletion anyway; skip tagging
    if resource_type == 'AWS::S3::Bucket':
        return

    resource_info = {
        'resource_arn': resource.resource_arn,
        'service_name': resource.service_name,
        'resource_id': resource.resource_id,
        'region': resource.region,
        'account_id': getattr(resource, 'account_id', ''),
    }
    ok = _apply_enforcement_tags(resource_info, {'ManagedBy': 'tag-manager-cli'})
    if not ok:
        msg = (
            f"Failed to apply ManagedBy tag to {resource.resource_arn}. "
            "The cross-account role requires this tag for delete permissions. "
            "Check that the StackSet has been updated in the target account."
        )
        logger.warning(msg)
        raise RuntimeError(msg)


def _delete_aws_resource(resource) -> dict:
    """Delete an AWS resource based on its type.

    Args:
        resource: Resource model object with resource_type, resource_arn, region, etc.

    Returns:
        dict with 'success': bool, 'message': str, 'error': str (if failed)
    """
    try:
        resource_type = resource.resource_type

        # Ensure the ManagedBy tag is present so the cross-account role
        # policy allows the delete action.
        _ensure_managed_tag(resource)

        # Brief pause for tag-based IAM policy conditions to propagate.
        # AWS tag-based authorization uses eventual consistency; without
        # this delay the delete call may hit AccessDeniedException even
        # though the tag was just applied successfully.
        time.sleep(3)

        # Lambda Functions
        if resource_type == 'AWS::Lambda::Function':
            client = _get_delete_client(resource, 'lambda')
            client.delete_function(FunctionName=resource.resource_id)
            return {'success': True, 'message': f'Deleted Lambda function: {resource.resource_id}'}

        # EC2 Instances
        elif resource_type == 'AWS::EC2::Instance':
            client = _get_delete_client(resource, 'ec2')
            client.terminate_instances(InstanceIds=[resource.resource_id])
            return {'success': True, 'message': f'Terminated EC2 instance: {resource.resource_id}'}

        # EC2 Volumes
        elif resource_type == 'AWS::EC2::Volume':
            client = _get_delete_client(resource, 'ec2')
            client.delete_volume(VolumeId=resource.resource_id)
            return {'success': True, 'message': f'Deleted EBS volume: {resource.resource_id}'}

        # EC2 Snapshots
        elif resource_type == 'AWS::EC2::Snapshot':
            client = _get_delete_client(resource, 'ec2')
            client.delete_snapshot(SnapshotId=resource.resource_id)
            return {'success': True, 'message': f'Deleted EBS snapshot: {resource.resource_id}'}

        # RDS Instances
        elif resource_type == 'AWS::RDS::DBInstance':
            client = _get_delete_client(resource, 'rds')
            client.delete_db_instance(
                DBInstanceIdentifier=resource.resource_id,
                SkipFinalSnapshot=True,
                DeleteAutomatedBackups=True
            )
            return {'success': True, 'message': f'Deleted RDS instance: {resource.resource_id}'}

        # DynamoDB Tables
        elif resource_type == 'AWS::DynamoDB::Table':
            client = _get_delete_client(resource, 'dynamodb')
            client.delete_table(TableName=resource.resource_id)
            return {'success': True, 'message': f'Deleted DynamoDB table: {resource.resource_id}'}

        # S3 Buckets (requires emptying first - DANGEROUS)
        elif resource_type == 'AWS::S3::Bucket':
            # S3 buckets require special handling - must be empty first
            # For safety, we don't auto-delete S3 buckets
            return {
                'success': False,
                'error': 'S3 bucket deletion requires manual emptying first. Use AWS Console or: aws s3 rb s3://{} --force'.format(resource.resource_id)
            }

        # CloudWatch Log Groups
        elif resource_type == 'AWS::Logs::LogGroup':
            client = _get_delete_client(resource, 'logs')
            client.delete_log_group(logGroupName=resource.resource_id)
            return {'success': True, 'message': f'Deleted CloudWatch log group: {resource.resource_id}'}

        # SNS Topics
        elif resource_type == 'AWS::SNS::Topic':
            client = _get_delete_client(resource, 'sns')
            client.delete_topic(TopicArn=resource.resource_arn)
            return {'success': True, 'message': f'Deleted SNS topic: {resource.resource_id}'}

        # SQS Queues
        elif resource_type == 'AWS::SQS::Queue':
            client = _get_delete_client(resource, 'sqs')
            # SQS delete requires queue URL, not ARN
            queue_url = client.get_queue_url(QueueName=resource.resource_id)['QueueUrl']
            client.delete_queue(QueueUrl=queue_url)
            return {'success': True, 'message': f'Deleted SQS queue: {resource.resource_id}'}

        # Unsupported resource type
        else:
            return {
                'success': False,
                'error': f'Deletion not supported for resource type: {resource_type}'
            }

    except Exception as e:
        return {'success': False, 'error': str(e)}


from ..utils.command_suggestions import show_suggestions, show_error_recovery

# Use Rich Console consistently with proper UTF-8 handling
import sys

# Ensure console can handle UTF-8 characters
if hasattr(sys.stdout, 'reconfigure'):
    try:
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
    except Exception:
        pass

console = Console()

tags_app = typer.Typer(
    help="Complete tag management - scan, apply, automate, and report on AWS resource tags",
    no_args_is_help=False
)


def _check_resources_exist() -> bool:
    """Check if resources exist in database, prompt to run discovery/scan if not.

    Returns:
        True if resources exist, False if user should run discovery/scan first
    """
    try:
        with get_db_session() as session:
            # Check if we have any resources in database
            resource_count = session.query(Resource).count()

            if resource_count == 0:
                console.print("\n[yellow]No resources found in local inventory![/yellow]")
                console.print("\nTo get started, you need to populate the resource inventory:")
                console.print("  1. [cyan]discover all[/cyan] - Scan AWS to discover all resources")
                console.print("  2. [cyan]tags scan[/cyan]     - Find resources missing required tags\n")
                console.print("[dim]Both commands help populate your local resource database.[/dim]\n")
                return False

            return True
    except Exception as e:
        # If there's an error checking, just continue - don't block the user
        console.print(f"[dim]Note: Could not check resource inventory: {e}[/dim]")
        return True


def show_tags_help():
    """Show the enhanced tags help format."""
    console.print("\n[bold cyan]Tag Management Commands[/bold cyan] - Your complete tagging toolkit\n")

    console.print("[bold green]RESOURCE TAGGING[/bold green] (start here):")
    console.print("- [cyan]scan[/cyan]          - Find resources missing required tags")
    console.print("- [cyan]apply[/cyan]         - Tag resources interactively or with automation")
    console.print("- [cyan]bulk[/cyan]          - Apply same tag to multiple resources by service\n")

    console.print("[bold yellow]AUTOMATION & RULES[/bold yellow] (scale your tagging):")
    console.print("- [cyan]rules[/cyan]         - Manage automated tagging rules")
    console.print("- [cyan]status[/cyan]        - Show tagging system health and activity\n")

    console.print("[bold red]LIFECYCLE MANAGEMENT[/bold red] (resource cleanup and TTL):")
    console.print("- [cyan]lifecycle[/cyan]     - Manage resource lifecycles, TTL, and cleanup\n")

    console.print("[bold magenta]REPORTING & MONITORING[/bold magenta] (track compliance):")
    console.print("- [cyan]report[/cyan]        - Generate compliance, usage, and audit reports\n")

    console.print("[bold green]QUICK START WORKFLOW[/bold green]:")
    console.print("1. [dim]discover all[/dim]                           # Discover AWS resources first")
    console.print("2. [dim]tags scan[/dim]                           # Find untagged resources")
    console.print("3. [dim]tags apply --interactive[/dim]            # Start tagging manually")
    console.print("4. [dim]tags rules[/dim]                          # Set up automation rules")
    console.print("5. [dim]tags apply --auto[/dim]                   # Apply automated tagging")
    console.print("6. [dim]tags lifecycle set-ttl --ttl-days 30[/dim] # Set TTL for cleanup")
    console.print("7. [dim]tags report compliance[/dim]              # Check compliance status\n")

    console.print("[bold cyan]COOL FEATURES[/bold cyan] (AI & Governance):")
    console.print("- [dim]tag-manager ask question \"Which S3 buckets lack tags?\"[/dim]  # AI assistant")
    console.print("- [dim]tag-manager policy wizard[/dim]                             # Tag governance\n")

    console.print("For detailed help on any command: [cyan]tags [COMMAND] --help[/cyan]")

@tags_app.callback(invoke_without_command=True)
def tags_main(
    ctx: typer.Context,
    help: bool = typer.Option(False, "--help", "-h", help="Show this message and exit.")
):
    """
    Complete tag management - scan, apply, automate, and report on AWS resource tags.

    This is your primary interface for all tagging operations, from finding untagged
    resources to applying automated rules and generating compliance reports.
    """
    if help or ctx.invoked_subcommand is None:
        show_tags_help()
        if help:
            raise typer.Exit()

# === RESOURCE DISCOVERY COMMANDS ===
# NOTE: Discovery has been moved to top-level command: tag-manager discover
# See: discovery_commands.py

# === MANUAL TAGGING COMMANDS ===

@tags_app.command("scan")
@require_aws_credentials
@require_database
@handle_all_errors
def scan_untagged_resources(
    services: Optional[str] = typer.Option(None, "--services", "-s", help="Comma-separated services to scan (ec2,s3,lambda)"),
    regions: Optional[str] = typer.Option(None, "--regions", "-r", help="Comma-separated regions to scan"),
    required_tags: Optional[str] = typer.Option(None, "--required-tags", help="Comma-separated required tag keys (auto-fetched from org policy if not specified)"),
    min_age_hours: int = typer.Option(0, "--min-age", help="Only scan resources older than N hours"),
    limit: int = typer.Option(100, "--limit", help="Maximum resources to display")
):
    """
    Scan AWS resources for missing required tags.

    This command helps identify resources that are missing important tags for compliance,
    cost tracking, and organization. Use this as the first step in your tagging workflow.

    Examples:
        tags scan                                    # Scan all resources for common tags
        tags scan --services ec2,s3 --regions us-east-1   # Scan specific services/regions
        tags scan --required-tags Project,Owner     # Check for custom required tags
        tags scan --min-age 24                      # Only show resources older than 1 day
    """
    # Decorators handle: AWS credentials, database check, and all errors
    # No try-except needed - error handling is automatic

    from rich.live import Live
    from rich.table import Table as RichTable

    # Import org policy provider for auto-fetching required tags
    from ..services.org_policy_provider import org_policy_provider

    service_list = [s.strip() for s in services.split(',')] if services else None
    region_list = [r.strip() for r in regions.split(',')] if regions else None

    # Progress state for live display
    scan_status = {
        'phase': 'Initializing',
        'detail': '',
        'resources_scanned': 0,
        'resources_total': 0,
        'compliant': 0,
        'non_compliant': 0,
        'current_service': ''
    }

    def build_scan_display():
        """Build the live scan progress display"""
        table = RichTable(show_header=False, box=None, padding=(0, 1))
        table.add_column("Status", width=70)

        phase = scan_status['phase']
        detail = scan_status['detail']

        # Phase indicator
        if phase == 'Complete':
            table.add_row(f"[bold green]Scan Complete[/bold green]")
        else:
            table.add_row(f"[bold cyan]{phase}[/bold cyan]")

        if detail:
            table.add_row(f"  [dim]{detail}[/dim]")

        # Show progress during analysis
        total = scan_status['resources_total']
        scanned = scan_status['resources_scanned']
        if total > 0:
            pct = int(scanned / total * 100)
            bar_filled = int(pct / 5)  # 20 char bar
            bar = '[' + '=' * bar_filled + ' ' * (20 - bar_filled) + ']'
            table.add_row(f"  {bar} {scanned}/{total} ({pct}%)")

            compliant = scan_status['compliant']
            non_compliant = scan_status['non_compliant']
            if scanned > 0:
                table.add_row(f"  [green]Compliant: {compliant}[/green] | [red]Non-compliant: {non_compliant}[/red]")

        return table

    with Live(build_scan_display(), console=console, refresh_per_second=4) as live:
        # Step 1: Fetch org policy
        scan_status['phase'] = 'Fetching Tag Policy'
        scan_status['detail'] = 'Checking AWS Organizations for tag policies...'
        live.update(build_scan_display())

        # Determine required tags - either from user input or org policy
        if required_tags:
            # User explicitly specified tags - use them
            required_tag_list = [tag.strip() for tag in required_tags.split(',') if tag.strip()]
            from_org_policy = False
            policy_warning = None
            scan_status['detail'] = f'Using custom tags: {", ".join(required_tag_list)}'
        else:
            # Auto-fetch from organization policy
            required_tag_list, from_org_policy, policy_warning = org_policy_provider.get_required_tags(
                show_warnings=False  # We'll show after live display
            )
            if from_org_policy:
                scan_status['detail'] = f'Found org policy tags: {", ".join(required_tag_list)}'
            else:
                scan_status['detail'] = f'Using default tags: {", ".join(required_tag_list)}'
        live.update(build_scan_display())

        # Step 2: Query database
        scan_status['phase'] = 'Querying Database'
        scan_status['detail'] = 'Building resource query...'
        live.update(build_scan_display())

        with get_db_session() as session:
            # Build query with progress updates - exclude stale resources
            query = session.query(Resource).filter(
                Resource.lifecycle_state != 'stale'
            )

            if service_list:
                query = query.filter(Resource.service_name.in_(service_list))
                scan_status['detail'] = f'Filtering by services: {", ".join(service_list)}'
            else:
                scan_status['detail'] = 'Scanning all services'
            live.update(build_scan_display())

            if region_list:
                query = query.filter(Resource.region.in_(region_list))
                scan_status['detail'] = f'Filtering by regions: {", ".join(region_list)}'
            live.update(build_scan_display())

            if min_age_hours > 0:
                cutoff_time = datetime.now(timezone.utc) - timedelta(hours=min_age_hours)
                query = query.filter(Resource.created_at <= cutoff_time)
                scan_status['detail'] = f'Resources older than {min_age_hours}h'
            live.update(build_scan_display())

            # Fetch resources
            scan_status['detail'] = 'Fetching resources from database...'
            live.update(build_scan_display())
            all_resources = query.order_by(Resource.created_at.desc()).limit(limit * 2).all()

            # Check if database is empty
            if len(all_resources) == 0:
                # Check total resource count in database
                total_resources = session.query(Resource).count()
                if total_resources == 0:
                    scan_status['phase'] = 'No Resources'
                    scan_status['detail'] = 'Database is empty - run discover first'
                    live.update(build_scan_display())
                    # Exit the Live context properly
                    live.stop()
                    safe_print("\n[WARN] No resources found in database!", "yellow")
                    safe_print("\nIt looks like you haven't discovered AWS resources yet.", "yellow")
                    safe_print("Run resource discovery first:", "white")
                    safe_print("  tag-manager discover", "cyan")
                    safe_print("\nThis will scan your AWS accounts and populate the database.", "dim")
                    raise typer.Exit(code=1)

            scan_status['resources_total'] = len(all_resources)

            # Step 3: Analyze for missing tags with detailed progress
            scan_status['phase'] = 'Analyzing Resources'
            scan_status['detail'] = f'Checking {len(all_resources)} resources for tag compliance...'
            live.update(build_scan_display())

            untagged_resources = []
            compliant_resources = []  # Track compliant resources with their matched tags
            compliance_stats = {"fully_compliant": 0, "partially_compliant": 0, "non_compliant": 0}
            service_stats = {}
            risk_analysis = {"high_risk": 0, "medium_risk": 0, "low_risk": 0}

            for i, resource in enumerate(all_resources):
                # Update live display every 5 resources
                if i % 5 == 0:
                    scan_status['resources_scanned'] = i
                    scan_status['current_service'] = resource.service_name
                    scan_status['detail'] = f'Checking {resource.service_name}: {resource.resource_id[:30]}...'
                    live.update(build_scan_display())

                # Handle current_tags which might be a JSON string or dict
                current_tags = resource.current_tags or {}
                if isinstance(current_tags, str):
                    try:
                        current_tags = json.loads(current_tags) if current_tags else {}
                    except json.JSONDecodeError:
                        current_tags = {}

                # Use detailed compliance check with OR/AND logic
                compliance_result = org_policy_provider.check_resource_compliance_detailed(
                    current_tags, required_tag_list, from_org_policy
                )

                missing_tags = compliance_result.missing_tags
                matched_tags = compliance_result.matched_tags
                is_compliant = compliance_result.is_compliant

                # Compliance classification based on actual compliance result
                if is_compliant:
                    compliance_stats["fully_compliant"] += 1
                    scan_status['compliant'] += 1
                elif matched_tags:  # Has some tags but not compliant (only matters for AND mode)
                    compliance_stats["partially_compliant"] += 1
                    scan_status['non_compliant'] += 1
                else:
                    compliance_stats["non_compliant"] += 1
                    scan_status['non_compliant'] += 1
                
                # Service statistics
                service = resource.service_name
                if service not in service_stats:
                    service_stats[service] = {"total": 0, "untagged": 0}
                service_stats[service]["total"] += 1

                # Calculate age for all resources
                age_hours = 0
                if resource.created_at:
                    age_delta = datetime.now(timezone.utc) - resource.created_at.replace(tzinfo=timezone.utc)
                    age_hours = age_delta.total_seconds() / 3600

                if is_compliant:
                    # Track compliant resources with their compliance info
                    compliant_resources.append({
                        'resource_id': resource.resource_id,
                        'service_name': resource.service_name,
                        'region': resource.region,
                        'matched_tags': matched_tags,
                        'policy_source': compliance_result.get_display_source(),
                        'account_id': resource.account_id
                    })
                else:
                    # Non-compliant resource
                    service_stats[service]["untagged"] += 1

                    # Risk analysis based on age and service
                    if age_hours > 168 or service in ["ec2", "rds", "redshift"]:  # > 1 week
                        risk_analysis["high_risk"] += 1
                    elif age_hours > 24:  # > 1 day
                        risk_analysis["medium_risk"] += 1
                    else:
                        risk_analysis["low_risk"] += 1

                    # Extract all needed data within session context to avoid detached instance errors
                    untagged_resources.append({
                        'resource_id': resource.resource_id,
                        'service_name': resource.service_name,
                        'region': resource.region,
                        'resource_type': resource.resource_type,
                        'created_at': resource.created_at,
                        'current_tags': current_tags if isinstance(current_tags, dict) else {},
                        'missing_tags': missing_tags,
                        'matched_tags': matched_tags,
                        'tag_count': len(current_tags) if isinstance(current_tags, dict) else 0,
                        'age_hours': age_hours,
                        'account_id': resource.account_id,
                        'policy_source': compliance_result.get_display_source()
                    })

                if len(untagged_resources) >= limit:
                    break

            # Track actual resources scanned (may be less than total if we hit the limit)
            actual_scanned = i + 1 if 'i' in dir() and all_resources else len(all_resources)

            # Mark analysis complete
            scan_status['resources_scanned'] = actual_scanned
            scan_status['phase'] = 'Complete'
            if actual_scanned < len(all_resources):
                scan_status['detail'] = f'Scanned {actual_scanned}/{len(all_resources)} resources (stopped after finding {limit} non-compliant)'
            else:
                scan_status['detail'] = f'Analyzed {actual_scanned} resources'
            live.update(build_scan_display())

            # Store actual scanned count for later use
            resources_actually_scanned = actual_scanned

    # Show policy source info after live display
    compliance_mode = "AND (all required)" if from_org_policy else "OR (any one sufficient)"
    if from_org_policy:
        console.print(f"\n[green]Using required tags from AWS Organizations policy:[/green] {', '.join(required_tag_list)}")
        console.print(f"[dim]Compliance mode: {compliance_mode}[/dim]")
    else:
        if policy_warning:
            console.print(policy_warning)
        console.print(f"\n[cyan]Required tags (default):[/cyan] {', '.join(required_tag_list)}")
        console.print(f"[dim]Compliance mode: {compliance_mode}[/dim]")
    console.print()

    # Enhanced results display
    if not untagged_resources:
        safe_print("OK All scanned resources have required tags!", "green")
        _show_compliance_overview(compliance_stats, service_stats, resources_actually_scanned)
        # Show suggestions for fully compliant resources
        show_suggestions("tags.scan.no_untagged", data={"total_scanned": resources_actually_scanned})
        return
    
    # Show comprehensive overview first
    _show_scan_overview(resources_actually_scanned, untagged_resources, compliance_stats, service_stats, risk_analysis, required_tag_list)
    
    # Group resources by account
    from collections import defaultdict
    resources_by_account = defaultdict(list)
    for item in untagged_resources:
        resources_by_account[item.get('account_id', 'Unknown')].append(item)

    # Sort accounts for consistent display
    sorted_accounts = sorted(resources_by_account.keys())

    # Display a table for each account
    for account_id in sorted_accounts:
        account_resources = resources_by_account[account_id]

        # Sort resources by priority within each account
        account_resources.sort(key=lambda x: (
            0 if x['age_hours'] > 168 or x['service_name'] in ["ec2", "rds"] else  # High priority
            1 if x['age_hours'] > 24 else  # Medium priority
            2  # Low priority
        ))

        # Create table for this account
        table = Table(
            title=f"Account: {account_id} ({len(account_resources)} resources need attention)",
            show_header=True,
            header_style="bold cyan",
            title_style="bold yellow",
            box=box.ROUNDED,
            padding=(0, 1)
        )

        # Compact column setup
        table.add_column("Service", style="cyan", width=8)
        table.add_column("Resource ID", style="white", width=30)
        table.add_column("Region", style="yellow", width=12)
        table.add_column("Age", style="dim", width=6, justify="right")
        table.add_column("Tags", style="green", width=5, justify="center")
        table.add_column("Missing Tags", style="red", width=25)

        for item in account_resources:
            resource_id = item['resource_id']
            service_name = item['service_name']
            region = item['region']
            missing_tags = item['missing_tags']
            tag_count = item['tag_count']
            age_hours = item['age_hours']

            # Format age display
            if age_hours > 24:
                age_str = f"{int(age_hours // 24)}d"
            else:
                age_str = f"{int(age_hours)}h"

            # Color code age based on priority
            if age_hours > 168 or service_name in ["ec2", "rds", "redshift"]:
                age_style = "bold red"
            elif age_hours > 24:
                age_style = "yellow"
            else:
                age_style = "green"

            table.add_row(
                service_name.upper()[:8],
                resource_id[:28] + ".." if len(resource_id) > 30 else resource_id,
                region,
                f"[{age_style}]{age_str}[/{age_style}]",
                str(tag_count),
                ", ".join(missing_tags[:3]) + ("..." if len(missing_tags) > 3 else "")
            )

        console.print(table)
        console.print()  # Add space between account tables

    # Show compliant resources with their tag source (limited to first few)
    if compliant_resources:
        console.print()
        console.print(f"[green]Compliant Resources[/green] ({len(compliant_resources)} total, showing first 10):")
        console.print()

        compliant_table = Table(
            show_header=True,
            header_style="bold green",
            box=box.SIMPLE,
            padding=(0, 1)
        )
        compliant_table.add_column("Resource ID", style="white", width=35)
        compliant_table.add_column("Service", style="cyan", width=8)
        compliant_table.add_column("Status", style="green", width=10)
        compliant_table.add_column("Matched Tags", style="yellow", width=25)
        compliant_table.add_column("Policy Source", style="dim", width=15)

        for item in compliant_resources[:10]:
            resource_id = item['resource_id']
            matched_tags_str = ', '.join(item['matched_tags'][:3])
            if len(item['matched_tags']) > 3:
                matched_tags_str += "..."

            compliant_table.add_row(
                resource_id[:33] + ".." if len(resource_id) > 35 else resource_id,
                item['service_name'].upper()[:8],
                "compliant",
                matched_tags_str,
                item['policy_source']
            )

        console.print(compliant_table)
        console.print()

    # Show command suggestions based on scan results
    top_service = max(service_stats.items(), key=lambda x: x[1].get("untagged", 0))[0] if service_stats else "ec2"
    show_suggestions("tags.scan", data={
    "untagged_count": len(untagged_resources),
    "top_service": top_service,
    "high_risk_count": risk_analysis.get("high_risk", 0)
    })


@tags_app.command("apply")
def apply_tags(
    interactive: bool = typer.Option(False, "--interactive", "-i", help="Interactively tag resources one by one"),
    auto: bool = typer.Option(False, "--auto", "-a", help="Apply automated tagging rules"),
    services: Optional[str] = typer.Option(None, "--services", "-s", help="Filter by services (comma-separated)"),
    resource_arns: Optional[List[str]] = typer.Option(None, "--resource-arn", help="Specific resource ARNs to tag"),
    rule_names: Optional[List[str]] = typer.Option(None, "--rule-name", help="Specific rule names to apply"),
    max_resources: int = typer.Option(20, "--limit", help="Maximum resources to process"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Show what would be tagged without applying changes")
):
    """
    Apply tags to AWS resources using interactive or automated methods.
    
    This is the primary command for actually tagging your resources. Choose between
    interactive mode for careful manual tagging, or automated mode for bulk operations.
    
    Examples:
        tags apply --interactive                     # Interactively tag untagged resources
        tags apply --auto                           # Apply all enabled automation rules
        tags apply --auto --services ec2,s3        # Auto-tag only specific services
        tags apply --interactive --limit 10        # Tag only first 10 resources
        tags apply --auto --dry-run                 # Preview what would be auto-tagged
    """
    if not interactive and not auto:
        console.print("[red]Error: Must specify either --interactive or --auto[/red]")
        console.print("Use 'tags apply --help' for examples")
        raise typer.Exit(1)
    
    if interactive:
        _interactive_tagging(services, max_resources)
    elif auto:
        _auto_apply_rules(services, resource_arns, rule_names, dry_run, max_resources)


def _interactive_tagging(services: Optional[str], max_resources: int):
    """Interactive tagging implementation."""
    # Check if resources exist in database
    if not _check_resources_exist():
        return

    try:
        console.print("[blue][TAG] Interactive Resource Tagging[/blue]")
        console.print("[dim]You'll be prompted to tag each untagged resource[/dim]\n")
        
        service_list = [s.strip() for s in services.split(',')] if services else None
        
        with get_db_session() as session:
            query = session.query(Resource)
            if service_list:
                query = query.filter(Resource.service_name.in_(service_list))
            
            # Query and prioritize untagged resources first
            resources = query.limit(max_resources * 4).all()  # Get more to sort and prioritize
            
            # Find resources with missing common tags and prioritize them
            required_tags = ["Environment", "Owner", "CostCenter"]
            prioritized_resources = []
            
            for resource in resources:
                current_tags = resource.current_tags or {}
                missing_tags = [tag for tag in required_tags if tag not in current_tags]
                
                if missing_tags:
                    # Calculate priority score (higher score = higher priority)
                    priority_score = 0
                    
                    # Completely untagged resources get highest priority
                    if not current_tags or len(current_tags) == 0:
                        priority_score += 1000
                    
                    # More missing tags = higher priority
                    priority_score += len(missing_tags) * 100
                    
                    # Older resources get higher priority (security concern)
                    if resource.created_at:
                        from datetime import datetime, timezone
                        age_days = (datetime.now(timezone.utc) - resource.created_at.replace(tzinfo=timezone.utc)).days
                        priority_score += min(age_days, 365)  # Cap at 1 year
                    
                    # High-cost services get higher priority
                    if resource.service_name in ["ec2", "rds", "redshift"]:
                        priority_score += 50
                    
                    prioritized_resources.append({
                        'resource': resource,
                        'missing_tags': missing_tags,
                        'priority_score': priority_score,
                        'tag_count': len(current_tags)
                    })
            
            # Sort by priority (highest first) and limit to requested amount
            prioritized_resources.sort(key=lambda x: x['priority_score'], reverse=True)
            untagged_resources = [item['resource'] for item in prioritized_resources[:max_resources]]
            
            if not untagged_resources:
                console.print("[green]OK No untagged resources found![/green]")
                return
            
            console.print(f"Found [yellow]{len(untagged_resources)}[/yellow] resources to tag (prioritized by urgency)\n")
            
            tagged_count = 0
            skipped_count = 0
            
            # Create a lookup for priority info
            priority_lookup = {item['resource'].id: item for item in prioritized_resources[:max_resources]}
            
            for i, resource in enumerate(untagged_resources, 1):
                priority_info = priority_lookup.get(resource.id, {})
                priority_score = priority_info.get('priority_score', 0)
                missing_tags = priority_info.get('missing_tags', [])
                # Determine priority level for display
                if priority_score >= 1000:
                    priority_level = "[bold red]CRITICAL[/bold red] (No tags)"
                    priority_style = "red"
                elif priority_score >= 300:
                    priority_level = "[red]HIGH[/red]"
                    priority_style = "red"
                elif priority_score >= 150:
                    priority_level = "[yellow]MEDIUM[/yellow]"
                    priority_style = "yellow"
                else:
                    priority_level = "[green]LOW[/green]"
                    priority_style = "blue"
                
                # Display resource info with priority
                panel_content = f"""
[bold cyan]{resource.service_name.upper()}[/bold cyan] | [white]{resource.resource_id}[/white] | [yellow]{resource.region}[/yellow]
Priority: {priority_level} (Score: {priority_score})
[dim]ARN: {resource.resource_arn}[/dim]
[dim]Created: {resource.created_at.strftime('%Y-%m-%d %H:%M') if resource.created_at else 'Unknown'}[/dim]

Current tags: [green]{len(resource.current_tags or {})} tags[/green] | Missing: [red]{', '.join(missing_tags)}[/red]
"""
                if resource.current_tags:
                    tag_display = []
                    for k, v in (resource.current_tags or {}).items():
                        tag_display.append(f"[cyan]{k}[/cyan]=[white]{v}[/white]")
                    panel_content += f"Tags: {', '.join(tag_display)}"
                
                console.print(Panel(panel_content, title=f"Resource {i}/{len(untagged_resources)}", border_style=priority_style))
                
                # Ask user what to do
                action = Prompt.ask(
                    "What would you like to do?",
                    choices=["tag", "skip", "view", "quit"],
                    default="tag"
                )
                
                if action == "quit":
                    break
                elif action == "skip":
                    skipped_count += 1
                    continue
                elif action == "view":
                    # Show full resource details
                    console.print(json.dumps({
                        'resource_arn': resource.resource_arn,
                        'current_tags': resource.current_tags,
                        'metadata': resource.metadata
                    }, indent=2, default=str))
                    continue
                elif action == "tag":
                    # Interactive tagging
                    success = _interactive_tag_resource(resource)
                    if success:
                        tagged_count += 1
                
                console.print()  # Add spacing
            
            # Summary
            console.print(f"\n[bold green]OK Tagging Session Complete[/bold green]")
            console.print(f"- Tagged: [green]{tagged_count}[/green] resources")
            console.print(f"- Skipped: [yellow]{skipped_count}[/yellow] resources")

            # Show suggestions after tagging session
            show_suggestions("tags.apply.success", data={
                "resources_tagged": tagged_count,
                "resources_skipped": skipped_count,
                "success": tagged_count > 0
            })

    except Exception as e:
        console.print(f"[red]Error in interactive tagging: {e}[/red]")
        show_error_recovery("database", str(e))
        raise typer.Exit(1)


def _interactive_tag_resource(resource: Resource) -> bool:
    """Interactively tag a single resource."""
    try:
        console.print(f"[bold]Tagging {resource.resource_id}[/bold]")
        
        new_tags = {}
        current_tags = resource.current_tags or {}
        
        # Common tags to suggest
        common_tags = ["Environment", "Owner", "CostCenter", "Project", "Application"]
        
        for tag_key in common_tags:
            if tag_key in current_tags:
                console.print(f"  {tag_key}: [dim]{current_tags[tag_key]} (already set)[/dim]")
                continue
            
            # Suggest values based on tag key
            suggestions = _get_tag_suggestions(tag_key, resource)
            
            if suggestions:
                suggestion_text = f" (suggestions: {', '.join(suggestions[:3])})"
            else:
                suggestion_text = ""
                
            value = Prompt.ask(f"  [cyan]{tag_key}[/cyan]{suggestion_text}", default="")
            
            if value:
                new_tags[tag_key] = value
        
        # Ask for additional custom tags
        while True:
            add_more = Confirm.ask("Add more custom tags?", default=False)
            if not add_more:
                break
            
            key = Prompt.ask("Tag key", default="")
            if not key:
                break
                
            value = Prompt.ask(f"Value for '{key}'", default="")
            if value:
                new_tags[key] = value
        
        if not new_tags:
            console.print("[yellow]No tags specified, skipping[/yellow]")
            return False
        
        # Show preview and confirm
        console.print("\n[bold]Tags to apply:[/bold]")
        for key, value in new_tags.items():
            console.print(f"  [cyan]{key}[/cyan] = [white]{value}[/white]")
        
        if not Confirm.ask("\nApply these tags?", default=True):
            return False
        
        # Apply tags to AWS
        success = apply_tags_to_aws_resource(resource.resource_arn, new_tags)
        
        if success:
            # Update database
            with get_db_session() as session:
                db_resource = session.query(Resource).filter_by(resource_arn=resource.resource_arn).first()
                if db_resource:
                    updated_tags = (db_resource.current_tags or {}).copy()
                    updated_tags.update(new_tags)
                    db_resource.current_tags = updated_tags
                    session.commit()
            
            console.print("[green]OK Tags applied successfully![/green]")
            return True
        else:
            console.print("[red]ERROR Failed to apply tags[/red]")
            return False
            
    except Exception as e:
        console.print(f"[red]Error tagging resource: {e}[/red]")
        return False


def _get_tag_suggestions(tag_key: str, resource: Resource) -> List[str]:
    """Get tag value suggestions based on tag key and resource context."""
    suggestions = []
    
    if tag_key == "Environment":
        if 'prod' in resource.resource_id.lower():
            suggestions.append("production")
        elif 'dev' in resource.resource_id.lower():
            suggestions.append("development")
        elif 'test' in resource.resource_id.lower():
            suggestions.append("testing")
        elif 'stage' in resource.resource_id.lower():
            suggestions.append("staging")
        else:
            suggestions = ["production", "development", "staging", "testing"]
    
    elif tag_key == "Owner":
        # Try to get from existing tags or metadata
        current_tags = resource.current_tags or {}
        if 'CreatedBy' in current_tags:
            suggestions.append(current_tags['CreatedBy'])
        suggestions.extend(["team-platform", "team-data", "team-frontend"])
    
    elif tag_key == "CostCenter":
        suggestions = ["engineering", "operations", "data-science", "marketing"]
    
    elif tag_key == "Project":
        # Infer from resource name
        name_parts = resource.resource_id.lower().split('-')
        if len(name_parts) >= 2:
            suggestions.append(f"{name_parts[0]}-{name_parts[1]}")
        suggestions.extend(["web-app", "data-pipeline", "ml-platform"])
    
    elif tag_key == "Application":
        suggestions = ["web-server", "database", "api", "worker", "cache"]
    
    return suggestions


def _auto_apply_rules(services: Optional[str], resource_arns: Optional[List[str]], rule_names: Optional[List[str]], dry_run: bool, max_resources: int):
    """Auto apply tagging rules implementation."""
    try:
        console.print("[blue]🤖 Applying automatic tagging rules[/blue]")
        
        if dry_run:
            console.print("[yellow]DRY RUN MODE - No changes will be applied[/yellow]")
        
        service_list = [s.strip() for s in services.split(',')] if services else None
        
        with get_db_session() as session:
            # Convert rule names to rule IDs if provided
            rule_ids = None
            if rule_names:
                rules = session.query(TaggingRule).filter(TaggingRule.name.in_(rule_names)).all()
                rule_ids = [str(rule.id) for rule in rules]
                
                if len(rule_ids) != len(rule_names):
                    found_names = [rule.name for rule in rules]
                    missing_names = set(rule_names) - set(found_names)
                    console.print(f"[red]Rules not found: {', '.join(missing_names)}[/red]")
                    raise typer.Exit(1)
            
            if not dry_run:
                # Try to queue bulk tagging job, fallback to direct execution
                try:
                    result = bulk_apply_tagging_rules.delay(
                        resource_arns=resource_arns,
                        rule_ids=rule_ids
                    )
                    
                    console.print(f"[green]OK[/green] Queued bulk tagging job: {result.id}")
                    console.print("[dim]Use 'tag-manager tags status' to monitor progress[/dim]")
                    
                except Exception as e:
                    if "has no attribute 'delay'" in str(e):
                        # Celery not available or task not registered, run directly
                        console.print("[yellow]Celery not available, running rules enforcement directly...[/yellow]")
                        _direct_auto_tagging(session, resource_arns, rule_ids, service_list, max_resources)
                    else:
                        console.print(f"[red]Error queuing tagging job: {e}[/red]")
                        raise typer.Exit(1)
            else:
                # Show what would be processed
                resources_query = session.query(Resource)
                if resource_arns:
                    resources_query = resources_query.filter(Resource.resource_arn.in_(resource_arns))
                elif service_list:
                    resources_query = resources_query.filter(Resource.service_name.in_(service_list))
                
                resources = resources_query.limit(max_resources).all()
                
                rules_query = session.query(TaggingRule).filter(TaggingRule.enabled == True)
                if rule_ids:
                    rules_query = rules_query.filter(TaggingRule.id.in_(rule_ids))
                
                rules = rules_query.all()
                
                console.print(f"[dim]Would process {len(resources)} resources with {len(rules)} rules[/dim]")
                
                for resource in resources[:5]:  # Show first 5
                    console.print(f"  - {resource.resource_arn}")
                
                if len(resources) > 5:
                    console.print(f"  ... and {len(resources) - 5} more resources")
        
    except Exception as e:
        console.print(f"[red]Error applying automatic rules: {e}[/red]")
        raise typer.Exit(1)


def _direct_auto_tagging(session, resource_arns: Optional[List[str]], rule_ids: Optional[List[str]], service_list: Optional[List[str]], max_resources: int):
    """Run automatic tagging directly without Celery workers."""
    
    # Get resources to process
    resources_query = session.query(Resource)
    if resource_arns:
        resources_query = resources_query.filter(Resource.resource_arn.in_(resource_arns))
    elif service_list:
        resources_query = resources_query.filter(Resource.service_name.in_(service_list))
    
    resources = resources_query.limit(max_resources).all()
    
    # Get enabled rules
    rules_query = session.query(TaggingRule).filter(TaggingRule.enabled == True)
    if rule_ids:
        rules_query = rules_query.filter(TaggingRule.id.in_(rule_ids))
    
    rules = rules_query.all()
    
    if not resources:
        console.print("[yellow]No resources found to process[/yellow]")
        return
    
    if not rules:
        console.print("[yellow]No enabled tagging rules found[/yellow]")
        return
    
    console.print(f"[cyan]Processing {len(resources)} resources with {len(rules)} rules...[/cyan]")
    
    # Process each resource
    total_actions = 0
    total_tags_applied = 0
    
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TaskProgressColumn(),
        console=console
    ) as progress:
        task = progress.add_task("Applying tagging rules...", total=len(resources))
        
        for resource in resources:
            resource_actions = 0
            
            # Evaluate each rule for this resource
            for rule in rules:
                try:
                    action = _evaluate_rule_for_resource(resource, rule.to_dict(), session)
                    
                    if action and action.get('tags'):
                        # Apply tags to AWS resource AND database
                        current_tags = resource.current_tags or {}
                        new_tags = action['tags']
                        
                        # First, apply to AWS resource
                        aws_success = False
                        try:
                            aws_success = _apply_tags_to_aws_resource(
                                resource.resource_arn, 
                                new_tags, 
                                resource.service_name,
                                account_id=getattr(resource, "account_id", None),
                                region=getattr(resource, "region", None),
                                resource_id=getattr(resource, "resource_id", None),
                            )
                        except Exception as e:
                            console.print(f"[dim]Warning: Failed to apply tags to AWS resource {resource.resource_id}: {e}[/dim]")
                        
                        # Only update database if AWS call succeeded (or for testing)
                        if aws_success:
                            # Update resource tags in database
                            updated_tags = current_tags.copy()
                            updated_tags.update(new_tags)
                            resource.current_tags = updated_tags
                            
                            resource_actions += len(new_tags)
                            total_tags_applied += len(new_tags)
                            
                            # Log the successful action
                            console.print(f"[green]Applied {len(new_tags)} tags to {resource.service_name.upper()} {resource.resource_id}[/green]")
                        else:
                            console.print(f"[dim]Skipped database update for {resource.resource_id} due to AWS tagging failure[/dim]")
                        
                except Exception as e:
                    console.print(f"[dim]Warning: Could not apply rule '{rule.name}' to {resource.resource_id}: {e}[/dim]")
                    continue
            
            if resource_actions > 0:
                total_actions += 1
            
            progress.advance(task)
        
        # Commit changes
        session.commit()
    
    if total_actions > 0:
        console.print(f"[green]OK[/green] Applied {total_tags_applied} tags to {total_actions} resources")
        console.print("[dim]Tags have been applied to both AWS resources and the local database.[/dim]")
    else:
        console.print("[yellow]No tagging actions were needed - all resources already compliant[/yellow]")


@tags_app.command("bulk")
def bulk_tag_resources(
    service: str = typer.Argument(..., help="Service to tag (ec2, s3, lambda, etc.)"),
    tag_key: str = typer.Option(..., "--tag-key", "-k", help="Tag key to apply to all resources"),
    tag_value: str = typer.Option(..., "--tag-value", "-v", help="Tag value to apply to all resources"),
    region: Optional[str] = typer.Option(None, "--region", "-r", help="Specific region to target"),
    filter_untagged: bool = typer.Option(True, "--filter-untagged", help="Only tag resources missing this specific tag key"),
    completely_untagged: bool = typer.Option(False, "--completely-untagged", help="Only tag resources with NO tags at all"),
    ignore_aws_tags: bool = typer.Option(False, "--ignore-aws-tags", help="Ignore AWS-managed tags when checking if resource is untagged"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Show what would be tagged without applying"),
    max_resources: int = typer.Option(50, "--limit", help="Maximum resources to process")
):
    """
    Apply the same tag to multiple resources of a specific service type.
    
    This command is useful for bulk operations like setting environment tags,
    cost center assignments, or other standardized tags across resources.
    
    Examples:
        tags bulk ec2 --tag-key Environment --tag-value production
        tags bulk s3 --tag-key CostCenter --tag-value engineering --region us-east-1
        tags bulk lambda --tag-key Owner --tag-value team-backend --dry-run
    """
    # Check if resources exist in database
    if not _check_resources_exist():
        return

    try:
        console.print(f"[blue][TAG] Bulk tagging {service.upper()} resources[/blue]")
        
        if dry_run:
            console.print("[yellow]DRY RUN MODE - No changes will be applied[/yellow]")
        
        with get_db_session() as session:
            query = session.query(Resource).filter(Resource.service_name == service)
            
            if region:
                query = query.filter(Resource.region == region)
            
            resources = query.limit(max_resources * 2).all()
            
            # Filter resources
            target_resources = []
            for resource in resources:
                current_tags = resource.current_tags or {}
                
                # Apply different filtering strategies
                if completely_untagged:
                    # Only include resources with absolutely no tags
                    if len(current_tags) > 0:
                        continue
                elif ignore_aws_tags:
                    # Only consider user-defined tags (ignore AWS-managed tags)
                    user_tags = {k: v for k, v in current_tags.items() 
                                if not k.startswith('aws:') and k != 'AmazonECSManaged'}
                    if completely_untagged and len(user_tags) > 0:
                        continue
                    elif filter_untagged and tag_key in user_tags:
                        continue
                elif filter_untagged and tag_key in current_tags:
                    # Default behavior: skip if this specific tag exists
                    continue
                
                target_resources.append(resource)
                
                if len(target_resources) >= max_resources:
                    break
            
            if not target_resources:
                console.print("[yellow]No resources found to tag[/yellow]")
                return
            
            # Show preview
            console.print(f"\nWill apply tag [cyan]{tag_key}[/cyan]=[white]{tag_value}[/white] to {len(target_resources)} resources:")
            
            preview_table = Table(show_header=True, header_style="bold magenta")
            preview_table.add_column("Service", style="cyan")
            preview_table.add_column("Resource ID", style="white")
            preview_table.add_column("Region", style="yellow")
            preview_table.add_column("Current Tags", style="green", justify="center")
            
            for resource in target_resources[:10]:  # Show first 10
                tag_count = len(resource.current_tags or {})
                preview_table.add_row(
                    resource.service_name.upper(),
                    resource.resource_id,
                    resource.region,
                    str(tag_count)
                )
            
            if len(target_resources) > 10:
                preview_table.add_row("...", f"and {len(target_resources) - 10} more", "...", "...")
            
            console.print(preview_table)
            
            if dry_run:
                console.print(f"\n[dim]Would tag {len(target_resources)} resources[/dim]")
                return
            
            # Confirm before proceeding
            if not Confirm.ask(f"\nProceed to tag {len(target_resources)} resources?", default=True):
                console.print("[yellow]Operation cancelled[/yellow]")
                return
            
            # Apply tags with progress bar
            success_count = 0
            failed_count = 0
            
            with Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                BarColumn(),
                TaskProgressColumn(),
                console=console
            ) as progress:
                task = progress.add_task("Applying tags...", total=len(target_resources))
                
                for resource in target_resources:
                    progress.update(task, description=f"Tagging {resource.resource_id}")
                    
                    success = apply_tags_to_aws_resource(resource.resource_arn, {tag_key: tag_value})
                    
                    if success:
                        # Update database
                        updated_tags = (resource.current_tags or {}).copy()
                        updated_tags[tag_key] = tag_value
                        resource.current_tags = updated_tags
                        session.commit()
                        success_count += 1
                    else:
                        failed_count += 1
                    
                    progress.advance(task)
            
            # Summary
            console.print(f"\n[bold green]OK Bulk tagging complete[/bold green]")
            console.print(f"- Successfully tagged: [green]{success_count}[/green] resources")
            if failed_count > 0:
                console.print(f"- Failed: [red]{failed_count}[/red] resources")

            # Show suggestions after bulk tagging
            show_suggestions("tags.bulk.complete", data={
                "resources_tagged": success_count,
                "failed_count": failed_count,
                "service": service
            })

    except Exception as e:
        console.print(f"[red]Error in bulk tagging: {e}[/red]")
        show_error_recovery("aws_auth", str(e))
        raise typer.Exit(1)


# === LIFECYCLE MANAGEMENT COMMANDS ===

@tags_app.command("lifecycle")
def manage_lifecycle(
    action: str = typer.Argument(..., help="Action: set-ttl, scan-expired, delete-expired, policies"),
    resource_arns: Optional[List[str]] = typer.Option(None, "--resource-arn", help="Specific resource ARNs to target"),
    ttl_days: Optional[int] = typer.Option(None, "--ttl-days", help="TTL in days (for set-ttl action)"),
    policy_name: Optional[str] = typer.Option(None, "--policy", help="Lifecycle policy name to apply"),
    services: Optional[str] = typer.Option(None, "--services", help="Comma-separated services to target"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Show what would be done without making changes"),
    force: bool = typer.Option(False, "--force", help="Skip confirmation prompts")
):
    """
    Manage resource lifecycles, TTL settings, and automated cleanup.
    
    This command provides comprehensive lifecycle management for your AWS resources,
    including setting TTL dates, finding expired resources, and managing cleanup policies.
    
    Examples:
        tags lifecycle set-ttl --ttl-days 30                    # Set 30-day TTL on untagged resources
        tags lifecycle set-ttl --resource-arn arn:aws:ec2:... --ttl-days 7
        tags lifecycle scan-expired                             # Find expired resources
        tags lifecycle delete-expired --dry-run                # Preview what would be deleted
        tags lifecycle policies                                 # Manage lifecycle policies
    """
    if action == "set-ttl":
        _set_resource_ttl(resource_arns, ttl_days, services, policy_name, dry_run, force)
    elif action == "scan-expired":
        _scan_expired_resources(services, dry_run)
    elif action == "delete-expired":
        _delete_expired_resources(services, dry_run, force)
    elif action == "policies":
        _manage_lifecycle_policies()
    else:
        console.print(f"[red]Unknown lifecycle action: {action}[/red]")
        console.print("Valid actions: set-ttl, scan-expired, delete-expired, policies")
        raise typer.Exit(1)


def _set_resource_ttl(resource_arns: Optional[List[str]], ttl_days: Optional[int],
                     services: Optional[str], policy_name: Optional[str], dry_run: bool, force: bool):
    """Set TTL for resources."""
    if not ttl_days and not policy_name:
        console.print("[red]Error: Must specify either --ttl-days or --policy[/red]")
        raise typer.Exit(1)

    # Check if resources exist in database
    if not _check_resources_exist():
        return

    console.print("[blue][TTL] Setting resource TTL...[/blue]")
    
    with get_db_session() as session:
        # Get target resources
        if resource_arns:
            resources = session.query(Resource).filter(Resource.resource_arn.in_(resource_arns)).all()
        else:
            query = session.query(Resource)
            if services:
                service_list = [s.strip() for s in services.split(',')]
                query = query.filter(Resource.service_name.in_(service_list))
            resources = query.all()
        
        if not resources:
            console.print("[yellow]No resources found matching criteria[/yellow]")
            return
        
        # Calculate expiration date
        if ttl_days:
            from datetime import datetime, timezone, timedelta
            expires_at = datetime.now(timezone.utc) + timedelta(days=ttl_days)
            policy_to_use = None
        else:
            # Get policy and use its TTL
            policy_to_use = session.query(ResourceLifecyclePolicy).filter_by(name=policy_name).first()
            if not policy_to_use:
                console.print(f"[red]Lifecycle policy '{policy_name}' not found[/red]")
                raise typer.Exit(1)
            from datetime import datetime, timezone, timedelta
            expires_at = datetime.now(timezone.utc) + timedelta(days=policy_to_use.ttl_days)
        
        # Filter applicable resources if using policy
        if policy_to_use:
            applicable_resources = [r for r in resources if policy_to_use.is_applicable_to_resource(r)]
        else:
            applicable_resources = resources
        
        if not applicable_resources:
            console.print("[yellow]No resources match the policy criteria[/yellow]")
            return
        
        # Preview
        console.print(f"\n[bold]TTL Assignment Preview[/bold]")
        console.print(f"Target resources: {len(applicable_resources)}")
        console.print(f"TTL expires at: {expires_at.strftime('%Y-%m-%d %H:%M:%S UTC')}")
        if policy_to_use:
            console.print(f"Using policy: {policy_to_use.name}")
        
        if dry_run:
            console.print("[yellow][DRY RUN] Would set TTL on the following resources:[/yellow]")
            for resource in applicable_resources[:10]:  # Show first 10
                console.print(f"  - {resource.resource_arn}")
            if len(applicable_resources) > 10:
                console.print(f"  ... and {len(applicable_resources) - 10} more")
            return
        
        # Confirm unless forced
        if not force:
            if not Confirm.ask(f"Set TTL on {len(applicable_resources)} resources?", default=False):
                console.print("[yellow]Operation cancelled[/yellow]")
                return
        
        # Apply TTL
        updated_count = 0
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TaskProgressColumn(),
            console=console
        ) as progress:
            task = progress.add_task("Setting TTL...", total=len(applicable_resources))
            
            for resource in applicable_resources:
                old_expires_at = resource.expires_at
                resource.expires_at = expires_at
                if policy_to_use:
                    resource.lifecycle_policy_id = policy_to_use.id
                
                # Log the operation
                audit_log = LifecycleAuditLog(
                    resource_arn=resource.resource_arn,
                    resource_id=resource.id,
                    policy_id=policy_to_use.id if policy_to_use else None,
                    operation="TTL_SET",
                    operation_details={
                        "ttl_days": ttl_days or policy_to_use.ttl_days,
                        "method": "manual" if ttl_days else "policy"
                    },
                    old_expires_at=old_expires_at,
                    new_expires_at=expires_at,
                    success=True,
                    executed_by="cli-user"
                )
                session.add(audit_log)
                updated_count += 1
                progress.advance(task)
            
            session.commit()
        
        console.print(f"[green]OK[/green] Set TTL on {updated_count} resources")


def _scan_expired_resources(services: Optional[str], dry_run: bool):
    """Scan for expired resources."""
    console.print("[blue][SCAN] Scanning for expired resources...[/blue]")
    
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc)
    
    with get_db_session() as session:
        query = session.query(Resource).filter(
            Resource.expires_at.isnot(None),
            Resource.expires_at <= now,
            Resource.lifecycle_state != 'deleted'
        )
        
        if services:
            service_list = [s.strip() for s in services.split(',')]
            query = query.filter(Resource.service_name.in_(service_list))
        
        expired_resources = query.order_by(Resource.expires_at).all()
        
        if not expired_resources:
            console.print("[green]No expired resources found[/green]")
            return
        
        # Analyze expired resources
        risk_analysis = {"protected": 0, "deletable": 0, "warning_needed": 0}
        by_service = {}
        
        for resource in expired_resources:
            service = resource.service_name
            if service not in by_service:
                by_service[service] = 0
            by_service[service] += 1
            
            if resource.protected:
                risk_analysis["protected"] += 1
            elif resource.lifecycle_state == "warned":
                risk_analysis["deletable"] += 1
            else:
                risk_analysis["warning_needed"] += 1
        
        # Display results
        console.print(f"\n[bold red]Found {len(expired_resources)} expired resources[/bold red]")
        
        # Summary table
        summary_table = Table(title="Expiration Analysis", show_header=True, header_style="bold red")
        summary_table.add_column("Status", style="white")
        summary_table.add_column("Count", style="cyan", justify="right")
        summary_table.add_column("Action Needed", style="yellow")
        
        summary_table.add_row("Protected", str(risk_analysis["protected"]), "Manual review required")
        summary_table.add_row("Ready to delete", str(risk_analysis["deletable"]), "Can be deleted safely")
        summary_table.add_row("Need warning", str(risk_analysis["warning_needed"]), "Send warnings first")
        
        console.print(summary_table)
        
        # Service breakdown
        service_table = Table(title="Expired Resources by Service", show_header=True, header_style="bold red")
        service_table.add_column("Service", style="cyan")
        service_table.add_column("Count", style="white", justify="right")
        
        for service, count in sorted(by_service.items(), key=lambda x: x[1], reverse=True):
            service_table.add_row(service.upper(), str(count))
        
        console.print(service_table)
        
        # Detailed resource table
        detail_table = Table(title="Expired Resources Details", show_header=True, header_style="bold red")
        detail_table.add_column("Service", style="cyan", width=9)
        detail_table.add_column("Resource ID", style="white", width=25)
        detail_table.add_column("Expired", style="red", width=8)
        detail_table.add_column("State", style="yellow", width=8)
        detail_table.add_column("Protected", style="green", width=9)
        
        for resource in expired_resources[:20]:  # Show first 20
            # Handle timezone-naive datetimes from SQLite
            expires_at = resource.expires_at
            if expires_at.tzinfo is None:
                expires_at = expires_at.replace(tzinfo=timezone.utc)
            expired_days = (now - expires_at).days
            detail_table.add_row(
                resource.service_name.upper(),
                resource.resource_id[:22] + "..." if len(resource.resource_id) > 25 else resource.resource_id,
                f"{expired_days}d ago",
                resource.lifecycle_state,
                "YES" if resource.protected else "NO"
            )
        
        if len(expired_resources) > 20:
            detail_table.add_row("...", f"and {len(expired_resources) - 20} more", "...", "...", "...")
        
        console.print(detail_table)
        
        # Next steps
        console.print(f"\n[bold blue]Recommended Actions:[/bold blue]")
        if risk_analysis["warning_needed"] > 0:
            console.print(f"1. Send warnings: [cyan]tag-manager tags lifecycle delete-expired --dry-run[/cyan]")
        if risk_analysis["deletable"] > 0:
            console.print(f"2. Delete ready resources: [cyan]tag-manager tags lifecycle delete-expired[/cyan]")
        if risk_analysis["protected"] > 0:
            console.print(f"3. Review protected resources manually")


def _delete_expired_resources(services: Optional[str], dry_run: bool, force: bool):
    """Delete expired resources with safety checks."""
    console.print("[red][DELETE] Processing expired resources for deletion...[/red]")
    
    if not dry_run and not force:
        console.print("[bold red]WARNING: This operation can permanently delete AWS resources![/bold red]")
        if not Confirm.ask("Are you sure you want to continue?", default=False):
            console.print("[yellow]Operation cancelled[/yellow]")
            return
    
    from datetime import datetime, timezone, timedelta
    from sqlalchemy import or_
    now = datetime.now(timezone.utc)

    with get_db_session() as session:
        # Find resources that are:
        # 1. Explicitly marked for deletion (via 'lifecycle review'), OR
        # 2. Expired and either warned or active
        query = session.query(Resource).filter(
            Resource.expires_at.isnot(None),
            Resource.protected == False,
            or_(
                # Explicitly marked for deletion - no expiration check needed
                Resource.lifecycle_state == 'marked_for_deletion',
                # Expired and in warned/active state
                (Resource.expires_at <= now) & Resource.lifecycle_state.in_(['warned', 'active'])
            )
        )

        if services:
            service_list = [s.strip() for s in services.split(',')]
            query = query.filter(Resource.service_name.in_(service_list))

        resources_to_process = query.all()

        # Separate into ready for deletion vs needs warning
        ready_for_deletion = []
        needs_warning = []

        for resource in resources_to_process:
            if resource.lifecycle_state == 'marked_for_deletion':
                # User explicitly marked for deletion via 'lifecycle review'
                ready_for_deletion.append(resource)
            elif resource.lifecycle_state == 'warned' and resource.warned_at:
                # Check if grace period has passed (default 7 days after warning)
                grace_period_end = resource.warned_at + timedelta(days=7)
                if now >= grace_period_end:
                    ready_for_deletion.append(resource)
                else:
                    # Still in grace period
                    continue
            elif resource.lifecycle_state == 'active':
                # Never warned, need to warn first
                needs_warning.append(resource)

        if not ready_for_deletion and not needs_warning:
            console.print("[green]No resources ready for deletion or warning[/green]")
            return
        
        # Show what will be done
        if needs_warning:
            console.print(f"[yellow]Will send warnings to {len(needs_warning)} resources[/yellow]")
        
        if ready_for_deletion:
            console.print(f"[red]Will delete {len(ready_for_deletion)} resources that have exceeded grace period[/red]")
            # List the resources that will be deleted
            for resource in ready_for_deletion:
                policy_info = ""
                if hasattr(resource, 'lifecycle_policy') and resource.lifecycle_policy and resource.lifecycle_policy.name:
                    policy_info = f" [dim](policy: {resource.lifecycle_policy.name})[/dim]"
                elif hasattr(resource, 'org_policy_name') and resource.org_policy_name:
                    policy_info = f" [dim](policy: {resource.org_policy_name})[/dim]"
                console.print(
                    f"  [red]-[/red] {resource.service_name.upper()}: "
                    f"[bold]{resource.resource_id}[/bold] "
                    f"[dim]({resource.region})[/dim]"
                    f"{policy_info}"
                )

        if dry_run:
            console.print("\n[yellow][DRY RUN] Actions that would be taken:[/yellow]")
            
            if needs_warning:
                console.print(f"\nWould warn {len(needs_warning)} resources:")
                for resource in needs_warning:
                    console.print(f"  WARN: {resource.resource_arn}")

            if ready_for_deletion:
                console.print(f"\nWould delete {len(ready_for_deletion)} resources:")
                for resource in ready_for_deletion:
                    console.print(f"  DELETE: {resource.resource_arn}")
            return
        
        # Execute actions
        warned_count = 0
        deleted_count = 0
        
        # Send warnings first
        if needs_warning:
            console.print(f"Sending warnings to {len(needs_warning)} resources...")
            for resource in needs_warning:
                resource.lifecycle_state = 'warned'
                resource.warned_at = now
                resource.warning_count = (resource.warning_count or 0) + 1
                
                # Log warning
                audit_log = LifecycleAuditLog(
                    resource_arn=resource.resource_arn,
                    resource_id=resource.id,
                    operation="WARNING_SENT",
                    old_state=resource.lifecycle_state,
                    new_state='warned',
                    success=True,
                    executed_by="cli-user"
                )
                session.add(audit_log)
                warned_count += 1
        
        # Delete ready resources
        failed_deletions = []
        if ready_for_deletion and (force or Confirm.ask(f"Proceed to delete {len(ready_for_deletion)} resources?", default=False)):
            with Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                BarColumn(),
                TaskProgressColumn(),
                console=console
            ) as progress:
                task = progress.add_task("Deleting resources...", total=len(ready_for_deletion))

                for resource in ready_for_deletion:
                    progress.update(task, description=f"Deleting {resource.resource_id}...")

                    # Actually delete the AWS resource
                    deletion_result = _delete_aws_resource(resource)

                    if deletion_result['success']:
                        # Mark as deleted in database
                        old_state = resource.lifecycle_state or 'active'
                        resource.lifecycle_state = 'deleted'
                        resource.delete_after = now

                        # Log successful deletion
                        audit_log = LifecycleAuditLog(
                            resource_arn=resource.resource_arn,
                            resource_id=resource.id,
                            operation="DELETED",
                            old_state=old_state,
                            new_state='deleted',
                            success=True,
                            executed_by="cli-user",
                            operation_details={
                                "deletion_method": "automated_cleanup",
                                "message": deletion_result.get('message', '')
                            }
                        )
                        session.add(audit_log)
                        deleted_count += 1
                    else:
                        # Log failed deletion
                        error_msg = deletion_result.get('error', 'Unknown error')
                        failed_deletions.append((resource, error_msg))

                        audit_log = LifecycleAuditLog(
                            resource_arn=resource.resource_arn,
                            resource_id=resource.id,
                            operation="DELETE_FAILED",
                            old_state=resource.lifecycle_state or 'active',
                            new_state=resource.lifecycle_state or 'active',
                            success=False,
                            executed_by="cli-user",
                            error_message=error_msg,
                            operation_details={"deletion_method": "automated_cleanup"}
                        )
                        session.add(audit_log)

                    progress.advance(task)
        
        session.commit()

        # Summary
        console.print(f"\n[bold green]Lifecycle operation completed:[/bold green]")
        if warned_count > 0:
            console.print(f"- Sent warnings to [yellow]{warned_count}[/yellow] resources")
        if deleted_count > 0:
            console.print(f"- Deleted [red]{deleted_count}[/red] resources")
        if failed_deletions:
            console.print(f"- Failed to delete [yellow]{len(failed_deletions)}[/yellow] resources")
            console.print("\n[bold red]Failed Deletions:[/bold red]")
            for resource, error in failed_deletions:
                console.print(f"  [red]x[/red] {resource.resource_id}: {error}")

        if warned_count > 0:
            console.print(f"\n[dim]Resources will be eligible for deletion after 7-day grace period[/dim]")


def _manage_lifecycle_policies():
    """Manage lifecycle policies."""
    console.print("[blue][POLICY] Lifecycle Policy Management[/blue]")
    console.print("[dim]This feature manages automated lifecycle policies for resources[/dim]\n")
    
    with get_db_session() as session:
        policies = session.query(ResourceLifecyclePolicy).order_by(ResourceLifecyclePolicy.priority).all()
        
        if not policies:
            console.print("[yellow]No lifecycle policies configured[/yellow]")
            console.print("\nTo create policies, add them to your configuration and load via database commands.")
            return
        
        # Display policies
        table = Table(title="Resource Lifecycle Policies", show_header=True, header_style="bold magenta")
        table.add_column("Name", style="cyan", width=15)
        table.add_column("TTL (days)", style="white", width=9)
        table.add_column("Resource Types", style="green", width=25)
        table.add_column("Enabled", style="blue", width=8)
        table.add_column("Auto Apply", style="yellow", width=9)
        table.add_column("Resources", style="dim", width=9)
        
        for policy in policies:
            resource_count = session.query(Resource).filter_by(lifecycle_policy_id=policy.id).count()
            
            table.add_row(
                policy.name,
                str(policy.ttl_days),
                ", ".join(policy.resource_types[:2]) + ("..." if len(policy.resource_types) > 2 else ""),
                "OK" if policy.enabled else "OFF",
                "YES" if policy.auto_apply else "NO",
                str(resource_count)
            )
        
        console.print(table)
        
        # Show statistics
        total_managed = session.query(Resource).filter(Resource.lifecycle_policy_id.isnot(None)).count()
        total_expired = session.query(Resource).filter(
            Resource.expires_at.isnot(None),
            Resource.expires_at <= datetime.now(timezone.utc)
        ).count()
        
        console.print(f"\n[bold]Policy Statistics:[/bold]")
        console.print(f"- Resources under lifecycle management: [cyan]{total_managed}[/cyan]")
        console.print(f"- Currently expired resources: [red]{total_expired}[/red]")
        
        console.print(f"\n[dim]Use database commands to create, modify, or delete policies[/dim]")


# === AUTOMATION RULES COMMANDS ===

@tags_app.command("rules")
def manage_rules(
    action: Optional[str] = typer.Argument(None, help="Action: list, load, enable, disable, create, enforce, enforce-workers (defaults to 'list')"),
    target: Optional[str] = typer.Argument(None, help="Rule name or file path (required for load/enable/disable)"),
    enabled_only: bool = typer.Option(False, "--enabled-only", help="Show only enabled rules"),
    resource_type: Optional[str] = typer.Option(None, "--resource-type", help="Filter by resource type"),
    replace_existing: bool = typer.Option(False, "--replace", help="Replace existing rules when loading from file"),
    auto_approve: bool = typer.Option(False, "--auto-approve", help="Auto-approve rule enforcement (no manual confirmation)"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Preview enforcement actions without applying them")
):
    """
    Manage automated tagging rules - the core of automated tag management.
    
    Rules define conditions and tag templates that automatically apply tags to
    new resources based on their properties, name patterns, or other criteria.
    
    Examples:
        tags rules                                   # List all tagging rules (default)
        tags rules --enabled-only                   # Show only active rules
        tags rules --resource-type ec2              # Show rules for EC2 resources
        tags rules list                             # Explicitly list all rules
        tags rules create                           # Interactively create a new rule
        tags rules enforce                          # Apply rules with manual approval
        tags rules enforce --auto-approve           # Apply rules automatically
        tags rules enforce --dry-run                # Preview rule enforcement
        tags rules enforce-workers                  # Enforce via background workers
        tags rules enforce-workers --auto-approve   # Worker enforcement with auto-approval
        tags rules load config/tagging-rules.json  # Load rules from file
        tags rules enable "Environment Auto-Tag"   # Enable a specific rule
        tags rules disable "Cost Center Rule"      # Disable a specific rule
    """
    # Default to "list" if no action provided
    if action is None:
        action = "list"
    
    if action == "list":
        _list_rules(enabled_only, resource_type)
    elif action == "load":
        if not target:
            console.print("[red]Error: File path required for load action[/red]")
            console.print("Example: [cyan]tags rules load config/tagging-rules.json[/cyan]")
            raise typer.Exit(1)
        _load_rules(target, replace_existing)
    elif action == "enable":
        if not target:
            console.print("[red]Error: Rule name required for enable action[/red]")
            console.print("Example: [cyan]tags rules enable \"Environment Auto-Tag\"[/cyan]")
            raise typer.Exit(1)
        _enable_rule(target)
    elif action == "disable":
        if not target:
            console.print("[red]Error: Rule name required for disable action[/red]")
            console.print("Example: [cyan]tags rules disable \"Cost Center Rule\"[/cyan]")
            raise typer.Exit(1)
        _disable_rule(target)
    elif action == "create":
        _interactive_rule_creation()
    elif action == "enforce":
        _enforce_rules(auto_approve, dry_run)
    elif action == "enforce-workers":
        _enforce_rules_via_workers(auto_approve, dry_run)
    else:
        console.print(f"[red]Error: Unknown action '{action}'. Valid actions: list, load, enable, disable, create, enforce, enforce-workers[/red]")
        console.print("Use [cyan]tags rules --help[/cyan] for examples")
        raise typer.Exit(1)


def _list_rules(enabled_only: bool, resource_type: Optional[str]):
    """List tagging rules."""
    try:
        with get_db_session() as session:
            query = session.query(TaggingRule)
            
            if enabled_only:
                query = query.filter(TaggingRule.enabled == True)
            
            if resource_type:
                query = query.filter(TaggingRule.resource_types.contains([resource_type]))
            
            rules = query.order_by(TaggingRule.priority.asc()).all()
            
            if not rules:
                console.print("[yellow]No tagging rules found[/yellow]")
                return
            
            table = Table(title="Automated Tagging Rules", show_header=True, header_style="bold magenta")
            table.add_column("Name", style="cyan", width=15)
            table.add_column("Description", style="white", width=30)
            table.add_column("Resource Types", style="green", width=25)
            table.add_column("Priority", style="yellow", width=8)
            table.add_column("Enabled", style="blue", width=8)
            table.add_column("Tags", style="dim", width=16)
            
            for rule in rules:
                resource_types_str = ", ".join(rule.resource_types[:2])
                if len(rule.resource_types) > 2:
                    resource_types_str += f" (+{len(rule.resource_types) - 2} more)"
                
                tag_count = len(rule.tag_templates) if rule.tag_templates else 0
                
                table.add_row(
                    rule.name,
                    rule.description or "No description",
                    resource_types_str,
                    str(rule.priority),
                    "OK" if rule.enabled else "ERROR",
                    f"{tag_count} tag(s)"
                )
            
            console.print(table)
            
    except Exception as e:
        console.print(f"[red]Error listing tagging rules: {e}[/red]")
        raise typer.Exit(1)


def _load_rules(rules_file: str, replace_existing: bool):
    """Load tagging rules from JSON file."""
    try:
        rules_path = Path(rules_file)
        if not rules_path.exists():
            console.print(f"[red]Error: Rules file not found: {rules_file}[/red]")
            raise typer.Exit(1)
        
        with open(rules_path, 'r') as f:
            rules_data = json.load(f)
        
        if not isinstance(rules_data, list):
            console.print("[red]Error: Rules file must contain a list of rule objects[/red]")
            raise typer.Exit(1)
        
        with get_db_session() as session:
            loaded_rules = 0
            updated_rules = 0
            
            with Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                console=console,
                transient=True
            ) as progress:
                task = progress.add_task("Loading tagging rules...", total=len(rules_data))
                
                for rule_data in rules_data:
                    try:
                        rule_name = rule_data.get('name')
                        if not rule_name:
                            console.print("[yellow]Skipping rule without name[/yellow]")
                            continue
                        
                        # Check if rule already exists
                        existing_rule = session.query(TaggingRule).filter_by(name=rule_name).first()
                        
                        if existing_rule:
                            if replace_existing:
                                # Update existing rule
                                existing_rule.description = rule_data.get('description')
                                existing_rule.resource_types = rule_data.get('resource_types', [])
                                existing_rule.conditions = rule_data.get('conditions', [])
                                existing_rule.tag_templates = rule_data.get('tag_templates', [])
                                existing_rule.priority = rule_data.get('priority', 100)
                                existing_rule.enabled = rule_data.get('enabled', True)
                                existing_rule.updated_at = datetime.utcnow()
                                updated_rules += 1
                                progress.update(task, description=f"Updated rule: {rule_name}")
                            else:
                                console.print(f"[yellow]Rule '{rule_name}' already exists, skipping (use --replace to update)[/yellow]")
                                continue
                        else:
                            # Create new rule
                            new_rule = TaggingRule(
                                name=rule_name,
                                description=rule_data.get('description'),
                                resource_types=rule_data.get('resource_types', []),
                                conditions=rule_data.get('conditions', []),
                                tag_templates=rule_data.get('tag_templates', []),
                                priority=rule_data.get('priority', 100),
                                enabled=rule_data.get('enabled', True)
                            )
                            session.add(new_rule)
                            loaded_rules += 1
                            progress.update(task, description=f"Loaded rule: {rule_name}")
                        
                        progress.advance(task)
                        
                    except Exception as e:
                        console.print(f"[red]Error processing rule {rule_data.get('name', 'unknown')}: {e}[/red]")
            
            session.commit()
            
        console.print(f"[green]OK[/green] Successfully loaded {loaded_rules} new rules and updated {updated_rules} existing rules")
        
    except Exception as e:
        console.print(f"[red]Error loading tagging rules: {e}[/red]")
        raise typer.Exit(1)


def _enable_rule(rule_name: str):
    """Enable a tagging rule."""
    try:
        with get_db_session() as session:
            rule = session.query(TaggingRule).filter_by(name=rule_name).first()
            
            if not rule:
                console.print(f"[red]Rule '{rule_name}' not found[/red]")
                raise typer.Exit(1)
            
            rule.enabled = True
            rule.updated_at = datetime.utcnow()
            session.commit()
            
            console.print(f"[green]OK[/green] Enabled rule '{rule_name}'")
            
    except Exception as e:
        console.print(f"[red]Error enabling rule: {e}[/red]")
        raise typer.Exit(1)


def _disable_rule(rule_name: str):
    """Disable a tagging rule."""
    try:
        with get_db_session() as session:
            rule = session.query(TaggingRule).filter_by(name=rule_name).first()
            
            if not rule:
                console.print(f"[red]Rule '{rule_name}' not found[/red]")
                raise typer.Exit(1)
            
            rule.enabled = False
            rule.updated_at = datetime.utcnow()
            session.commit()
            
            console.print(f"[yellow]Disabled rule '{rule_name}'[/yellow]")
            
    except Exception as e:
        console.print(f"[red]Error disabling rule: {e}[/red]")
        raise typer.Exit(1)


# === VALIDATION AND COMPLIANCE COMMANDS ===
@tags_app.command("validate")
def validate_compliance(
    required_tags: Optional[str] = typer.Option("Environment,Owner,Project,CostCenter", "--required-tags", help="Comma-separated list of required tags"),
    fix_suggestions: bool = typer.Option(True, "--fix-suggestions", help="Show commands to fix issues"),
    output_file: Optional[str] = typer.Option(None, "--output", "-o", help="Save validation report to file"),
    strict: bool = typer.Option(False, "--strict", help="Enforce all organization policies"),
    services: Optional[str] = typer.Option(None, "--services", "-s", help="Filter by services (comma-separated)"),
    limit: int = typer.Option(100, "--limit", help="Maximum resources to validate")
):
    """
    Validate tag compliance without making any changes.
    
    This command performs comprehensive compliance checking to identify:
    - Missing mandatory tags
    - Low-quality tag values (unknown, temp, etc.)
    - Inconsistent tagging across resources
    - Policy violations
    
    Examples:
        tags validate                                      # Check default mandatory tags
        tags validate --required-tags Environment,Owner    # Check specific tags
        tags validate --strict                            # Full policy enforcement
        tags validate --services ec2,s3 --limit 50        # Validate specific services
        tags validate --output report.json                 # Export validation report
        tags validate --no-fix-suggestions                # Hide fix commands
    """
    try:
        console.print("[bold blue][VALIDATE] Tag Compliance Validation[/bold blue]")
        console.print("[dim]Analyzing resources for compliance issues without making changes[/dim]\n")
        
        # Parse required tags
        required_tag_list = [tag.strip() for tag in required_tags.split(',') if tag.strip()]
        service_list = [s.strip() for s in services.split(',')] if services else None
        
        with get_db_session() as session:
            # Get resources to validate
            query = session.query(Resource)
            if service_list:
                query = query.filter(Resource.service_name.in_(service_list))
            resources = query.limit(limit).all()
            
            if not resources:
                console.print("[yellow]No resources found to validate[/yellow]")
                return
            
            # Validation results
            validation_results = {
                "total_resources": len(resources),
                "compliant_resources": 0,
                "issues": [],
                "by_severity": {"critical": 0, "high": 0, "medium": 0, "low": 0},
                "by_type": {},
                "fix_commands": []
            }
            
            # Critical tags for strict mode
            critical_tags = {'Environment', 'Owner', 'Project', 'CostCenter'} if strict else set(required_tag_list)
            
            # Validate each resource
            with Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                BarColumn(),
                TaskProgressColumn(),
                console=console
            ) as progress:
                task = progress.add_task("Validating resources...", total=len(resources))
                
                for resource in resources:
                    issues = _validate_resource_tags(resource, required_tag_list, critical_tags, strict)
                    
                    if not issues:
                        validation_results["compliant_resources"] += 1
                    else:
                        for issue in issues:
                            validation_results["issues"].append({
                                "resource": {
                                    "id": resource.resource_id,
                                    "arn": resource.resource_arn,
                                    "service": resource.service_name,
                                    "region": resource.region
                                },
                                "issue": issue
                            })
                            
                            # Track by severity
                            validation_results["by_severity"][issue["severity"]] += 1
                            
                            # Track by type
                            issue_type = issue["type"]
                            if issue_type not in validation_results["by_type"]:
                                validation_results["by_type"][issue_type] = 0
                            validation_results["by_type"][issue_type] += 1
                            
                            # Generate fix command if requested
                            if fix_suggestions and issue.get("fix_command"):
                                validation_results["fix_commands"].append(issue["fix_command"])
                    
                    progress.advance(task)
            
            # Display validation results
            _display_validation_results(validation_results, fix_suggestions)
            
            # Save to file if requested
            if output_file:
                import json
                with open(output_file, 'w') as f:
                    json.dump(validation_results, f, indent=2, default=str)
                console.print(f"[green]Validation report saved to {output_file}[/green]")
            
    except Exception as e:
        console.print(f"[red]Error during validation: {e}[/red]")
        raise typer.Exit(1)


def _validate_resource_tags(resource, required_tags: List[str], critical_tags: set, strict: bool) -> List[Dict]:
    """Validate a single resource's tags and return issues found."""
    issues = []
    current_tags = resource.current_tags or {}
    
    # Check for missing required tags
    for tag_key in required_tags:
        if tag_key not in current_tags:
            severity = "critical" if tag_key in critical_tags else "high"
            issues.append({
                "type": "missing_tag",
                "severity": severity,
                "tag": tag_key,
                "message": f"Missing required tag: {tag_key}",
                "fix_command": f"tag-manager tags apply --resource-arn {resource.resource_arn} --tag-key {tag_key}"
            })
    
    # Check for low-quality tag values
    for tag_key, tag_value in current_tags.items():
        if _is_low_quality_tag_value(tag_value):
            issues.append({
                "type": "low_quality_value",
                "severity": "medium",
                "tag": tag_key,
                "current_value": tag_value,
                "message": f"Low-quality tag value for {tag_key}: '{tag_value}'",
                "fix_command": f"tag-manager tags apply --resource-arn {resource.resource_arn} --tag-key {tag_key}"
            })
    
    # Strict mode additional checks
    if strict:
        # Check for outdated tags
        if 'LastTaggedAt' in current_tags:
            from datetime import datetime, timedelta
            try:
                last_tagged = datetime.fromisoformat(current_tags['LastTaggedAt'])
                if datetime.now() - last_tagged > timedelta(days=90):
                    issues.append({
                        "type": "outdated_tags",
                        "severity": "low",
                        "message": "Tags haven't been updated in over 90 days",
                        "fix_command": f"tag-manager tags apply --resource-arn {resource.resource_arn} --auto"
                    })
            except:
                pass
        
        # Check for missing lifecycle tags
        lifecycle_tags = {'CreatedDate', 'TTLDays', 'ExpiryDate'}
        missing_lifecycle = lifecycle_tags - set(current_tags.keys())
        if missing_lifecycle:
            issues.append({
                "type": "missing_lifecycle",
                "severity": "medium",
                "tags": list(missing_lifecycle),
                "message": f"Missing lifecycle tags: {', '.join(missing_lifecycle)}",
                "fix_command": f"tag-manager tags lifecycle set-ttl --resource-arn {resource.resource_arn}"
            })
        
        # Check for inconsistent environment tags
        if 'Environment' in current_tags:
            env_value = current_tags['Environment'].lower()
            resource_name = resource.resource_id.lower()
            
            # Check for mismatched environment
            if 'prod' in resource_name and env_value != 'production':
                issues.append({
                    "type": "inconsistent_environment",
                    "severity": "high",
                    "current_value": current_tags['Environment'],
                    "expected_value": "Production",
                    "message": f"Environment tag '{current_tags['Environment']}' doesn't match resource name pattern",
                    "fix_command": f"tag-manager tags apply --resource-arn {resource.resource_arn} --tag-key Environment --tag-value Production"
                })
    
    return issues


def _display_validation_results(results: Dict, show_fixes: bool):
    """Display validation results in a formatted manner."""
    total = results["total_resources"]
    compliant = results["compliant_resources"]
    compliance_rate = (compliant / max(total, 1)) * 100
    
    # Compliance summary
    if compliance_rate == 100:
        console.print("\n[bold green]OK All resources are fully compliant![/bold green]")
    else:
        # Summary panel
        summary_text = f"""[bold]Validation Summary[/bold]

[cyan]Resources Validated:[/cyan] {total}
[green]Compliant Resources:[/green] {compliant}
[red]Resources with Issues:[/red] {total - compliant}
[yellow]Compliance Rate:[/yellow] {compliance_rate:.1f}%

[bold]Issues by Severity:[/bold]
- [red]Critical:[/red] {results['by_severity']['critical']}
- [yellow]High:[/yellow] {results['by_severity']['high']}
- [blue]Medium:[/blue] {results['by_severity']['medium']}
- [dim]Low:[/dim] {results['by_severity']['low']}"""
        
        console.print(Panel(summary_text, title="[bold red]Compliance Validation Results[/bold red]", border_style="red"))
        
        # Issues by type table
        if results["by_type"]:
            type_table = Table(title="Issues by Type", show_header=True, header_style="bold yellow")
            type_table.add_column("Issue Type", style="cyan")
            type_table.add_column("Count", style="white", justify="right")
            type_table.add_column("Impact", style="yellow")
            
            issue_impacts = {
                "missing_tag": "Resources lack required governance tags",
                "low_quality_value": "Tag values are not meaningful",
                "outdated_tags": "Tags haven't been refreshed recently",
                "missing_lifecycle": "No lifecycle management tags",
                "inconsistent_environment": "Environment tags don't match patterns"
            }
            
            for issue_type, count in sorted(results["by_type"].items(), key=lambda x: x[1], reverse=True):
                type_display = issue_type.replace("_", " ").title()
                impact = issue_impacts.get(issue_type, "Compliance violation")
                type_table.add_row(type_display, str(count), impact)
            
            console.print(type_table)
        
        # Sample issues (first 10)
        if results["issues"]:
            console.print("\n[bold]Sample Issues Found:[/bold]")
            
            for i, issue_data in enumerate(results["issues"][:10], 1):
                resource = issue_data["resource"]
                issue = issue_data["issue"]
                
                severity_color = {
                    "critical": "red",
                    "high": "yellow", 
                    "medium": "blue",
                    "low": "dim"
                }.get(issue["severity"], "white")
                
                console.print(f"\n{i}. [{severity_color}][{issue['severity'].upper()}][/{severity_color}] {resource['service'].upper()} | {resource['id']}")
                console.print(f"   Issue: {issue['message']}")
                
                if show_fixes and issue.get("fix_command"):
                    console.print(f"   [green]Fix:[/green] [dim]{issue['fix_command']}[/dim]")
            
            if len(results["issues"]) > 10:
                console.print(f"\n[dim]... and {len(results['issues']) - 10} more issues[/dim]")
        
        # Fix suggestions summary
        if show_fixes and results["fix_commands"]:
            console.print("\n[bold green]Recommended Actions:[/bold green]")
            
            # Group similar commands
            fix_types = {}
            for cmd in results["fix_commands"]:
                if "--interactive" in cmd:
                    fix_types["interactive"] = fix_types.get("interactive", 0) + 1
                elif "--auto" in cmd:
                    fix_types["auto"] = fix_types.get("auto", 0) + 1
                elif "lifecycle" in cmd:
                    fix_types["lifecycle"] = fix_types.get("lifecycle", 0) + 1
                else:
                    fix_types["manual"] = fix_types.get("manual", 0) + 1
            
            if fix_types.get("interactive"):
                console.print(f"1. Fix {fix_types['interactive']} issues interactively:")
                console.print("   [cyan]tag-manager tags apply --interactive[/cyan]")
            
            if fix_types.get("auto"):
                console.print(f"2. Apply automated fixes to {fix_types['auto']} resources:")
                console.print("   [cyan]tag-manager tags apply --auto[/cyan]")
            
            if fix_types.get("lifecycle"):
                console.print(f"3. Set lifecycle tags for {fix_types['lifecycle']} resources:")
                console.print("   [cyan]tag-manager tags lifecycle set-ttl --ttl-days 30[/cyan]")
            
            console.print("\n[dim]Run 'tag-manager tags rules enforce --dry-run' to preview all fixes[/dim]")


# === REPORTING AND MONITORING COMMANDS ===

@tags_app.command("report")
def generate_reports(
    type: str = typer.Argument("compliance", help="Report type: compliance, usage, audit"),
    output_file: Optional[str] = typer.Option(None, "--output", "-o", help="Save report to file"),
    format_type: str = typer.Option("table", "--format", help="Output format: table, json, csv"),
    resource_arn: Optional[str] = typer.Option(None, "--resource-arn", help="Filter by resource ARN (for audit)"),
    limit: int = typer.Option(50, "--limit", help="Maximum number of entries (for audit)"),
    success_only: bool = typer.Option(False, "--success-only", help="Show only successful operations (for audit)")
):
    """
    Generate comprehensive reports on tagging status, usage, and operations.
    
    Multiple report types help you understand your tagging posture and track
    automated tagging effectiveness over time.
    
    Examples:
        tags report compliance                       # Show tagging compliance rates
        tags report compliance --format json --output report.json
        tags report usage                           # Show automation statistics  
        tags report audit                           # Show recent tagging operations
        tags report audit --resource-arn arn:aws:ec2:... # Audit specific resource
    """
    if type == "compliance":
        _generate_compliance_report(output_file, format_type)
    elif type == "usage":
        _show_usage_statistics()
    elif type == "audit":
        _show_audit_log(resource_arn, limit, success_only)
    else:
        console.print(f"[red]Error: Unknown report type '{type}'. Valid types: compliance, usage, audit[/red]")
        raise typer.Exit(1)


def _generate_compliance_report(output_file: Optional[str], format_type: str):
    """Generate tagging compliance report."""
    # Check if resources exist in database
    if not _check_resources_exist():
        return

    try:
        safe_print("[CHART] Generating tagging compliance report...", "blue")
        
        with get_db_session() as session:
            resources = session.query(Resource).all()
            
            # Analyze tagging compliance
            report_data = _analyze_tagging_compliance(resources)
            
            if format_type == "table":
                _display_compliance_table(report_data)
            elif format_type == "json":
                console.print(json.dumps(report_data, indent=2, default=str))
            
            if output_file:
                with open(output_file, 'w') as f:
                    if format_type == "json":
                        json.dump(report_data, f, indent=2, default=str)
                    else:
                        # Write CSV or other formats
                        f.write("Tagging Compliance Report\n")
                        f.write(f"Generated: {datetime.utcnow()}\n")
                
                console.print(f"[green]OK[/green] Report saved to {output_file}")
            
    except Exception as e:
        console.print(f"[red]Error generating report: {e}[/red]")
        raise typer.Exit(1)


def _analyze_tagging_compliance(resources: List[Resource]) -> Dict[str, Any]:
    """Analyze resources for tagging compliance."""
    required_tags = ["Environment", "Owner", "CostCenter"]
    
    report = {
        "summary": {
            "total_resources": len(resources),
            "fully_tagged": 0,
            "partially_tagged": 0,
            "untagged": 0,
            "compliance_rate": 0
        },
        "by_service": {},
        "missing_tags": {},
        "generated_at": datetime.now(timezone.utc)
    }
    
    for resource in resources:
        current_tags = resource.current_tags or {}
        missing_tags = [tag for tag in required_tags if tag not in current_tags]
        
        # Overall stats
        if not missing_tags:
            report["summary"]["fully_tagged"] += 1
        elif len(missing_tags) < len(required_tags):
            report["summary"]["partially_tagged"] += 1
        else:
            report["summary"]["untagged"] += 1
        
        # By service stats
        service = resource.service_name
        if service not in report["by_service"]:
            report["by_service"][service] = {
                "total": 0,
                "fully_tagged": 0,
                "compliance_rate": 0
            }
        
        report["by_service"][service]["total"] += 1
        if not missing_tags:
            report["by_service"][service]["fully_tagged"] += 1
        
        # Missing tags tracking
        for tag in missing_tags:
            if tag not in report["missing_tags"]:
                report["missing_tags"][tag] = 0
            report["missing_tags"][tag] += 1
    
    # Calculate compliance rates
    total = report["summary"]["total_resources"]
    if total > 0:
        report["summary"]["compliance_rate"] = round(
            (report["summary"]["fully_tagged"] / total) * 100, 1
        )
    
    for service_data in report["by_service"].values():
        if service_data["total"] > 0:
            service_data["compliance_rate"] = round(
                (service_data["fully_tagged"] / service_data["total"]) * 100, 1
            )
    
    return report


def _display_compliance_table(report: Dict[str, Any]):
    """Display compliance report as formatted tables."""
    summary = report["summary"]
    
    # Summary table
    summary_table = Table(title="Tagging Compliance Summary", show_header=True, header_style="bold magenta")
    summary_table.add_column("Metric", style="white", width=15)
    summary_table.add_column("Count", style="cyan", justify="right", width=9)
    summary_table.add_column("Percentage", style="green", justify="right", width=8)
    
    total = summary["total_resources"]
    summary_table.add_row("Total Resources", str(total), "100.0%")
    summary_table.add_row("Fully Tagged", str(summary["fully_tagged"]), f"{summary['compliance_rate']:.1f}%")
    summary_table.add_row("Partially Tagged", str(summary["partially_tagged"]), f"{(summary['partially_tagged']/total*100):.1f}%" if total > 0 else "0%")
    summary_table.add_row("Untagged", str(summary["untagged"]), f"{(summary['untagged']/total*100):.1f}%" if total > 0 else "0%")
    
    console.print(summary_table)
    
    # By service table
    if report["by_service"]:
        service_table = Table(title="Compliance by Service", show_header=True, header_style="bold magenta")
        service_table.add_column("Service", style="cyan", width=16)
        service_table.add_column("Total", style="white", justify="right", width=8)
        service_table.add_column("Tagged", style="green", justify="right", width=8)
        service_table.add_column("Compliance", style="yellow", justify="right", width=8)
        
        for service, data in report["by_service"].items():
            service_table.add_row(
                service.upper(),
                str(data["total"]),
                str(data["fully_tagged"]),
                f"{data['compliance_rate']:.1f}%"
            )
        
        console.print(service_table)
    
    # Missing tags
    if report["missing_tags"]:
        console.print(f"\n[bold red]Most Common Missing Tags:[/bold red]")
        for tag, count in sorted(report["missing_tags"].items(), key=lambda x: x[1], reverse=True):
            console.print(f"  - [red]{tag}[/red]: {count} resources")


def _show_usage_statistics():
    """Show automated tagging usage statistics."""
    try:
        # Get tagging statistics
        tagging_stats = get_tagging_statistics()

        # TODO: CloudTrail - Disabled temporarily, will be re-enabled in future
        # Get CloudTrail processing statistics
        # cloudtrail_stats = get_cloudtrail_processing_stats()

        console.print("\n[bold magenta]Automated Tagging Statistics (24 hours)[/bold magenta]")
        
        # Create tagging stats table
        tagging_table = Table(show_header=True, header_style="bold cyan")
        tagging_table.add_column("Metric", style="white", width=30)
        tagging_table.add_column("Value", style="green", width=16)
        
        tagging_table.add_row("Total Operations", str(tagging_stats.get('total_operations_24h', 0)))
        tagging_table.add_row("Successful Operations", str(tagging_stats.get('successful_operations_24h', 0)))
        tagging_table.add_row("Failed Operations", str(tagging_stats.get('failed_operations_24h', 0)))
        tagging_table.add_row("Success Rate", f"{tagging_stats.get('success_rate_24h', 0):.1f}%")
        tagging_table.add_row("Resources Tagged", str(tagging_stats.get('unique_resources_tagged_24h', 0)))
        tagging_table.add_row("Rules Applied", str(tagging_stats.get('unique_rules_applied_24h', 0)))
        
        console.print(tagging_table)

        # TODO: CloudTrail - Disabled temporarily, will be re-enabled in future
        # CloudTrail stats
        # console.print("\n[bold magenta]CloudTrail Processing Statistics (24 hours)[/bold magenta]")
        #
        # cloudtrail_table = Table(show_header=True, header_style="bold cyan")
        # cloudtrail_table.add_column("Metric", style="white", width=30)
        # cloudtrail_table.add_column("Value", style="green", width=16)
        #
        # cloudtrail_table.add_row("Events Processed", str(cloudtrail_stats.get('cloudtrail_events_processed_24h', 0)))
        # cloudtrail_table.add_row("Successful Tags", str(cloudtrail_stats.get('successful_tags_24h', 0)))
        # cloudtrail_table.add_row("Failed Tags", str(cloudtrail_stats.get('failed_tags_24h', 0)))
        # cloudtrail_table.add_row("Unique Principals", str(cloudtrail_stats.get('unique_principals_24h', 0)))
        #
        # console.print(cloudtrail_table)

        # Operations by type
        ops_by_type = tagging_stats.get('operations_by_type', {})
        if ops_by_type:
            console.print("\n[bold magenta]Operations by Type[/bold magenta]")
            
            ops_table = Table(show_header=True, header_style="bold cyan")
            ops_table.add_column("Operation Type", style="white", width=25)
            ops_table.add_column("Total", style="yellow", width=9)
            ops_table.add_column("Successful", style="green", width=9)
            ops_table.add_column("Success Rate", style="blue", width=8)
            
            for op_type, stats in ops_by_type.items():
                total = stats['total']
                successful = stats['successful']
                success_rate = (successful / total * 100) if total > 0 else 0
                
                ops_table.add_row(
                    op_type,
                    str(total),
                    str(successful),
                    f"{success_rate:.1f}%"
                )
            
            console.print(ops_table)
        
    except Exception as e:
        console.print(f"[red]Error getting tagging statistics: {e}[/red]")
        raise typer.Exit(1)


def _show_audit_log(resource_arn: Optional[str], limit: int, success_only: bool):
    """Show tagging audit log."""
    try:
        with get_db_session() as session:
            query = session.query(TaggingAuditLog)
            
            if resource_arn:
                query = query.filter(TaggingAuditLog.resource_arn == resource_arn)
            
            if success_only:
                query = query.filter(TaggingAuditLog.success == True)
            
            logs = query.order_by(TaggingAuditLog.executed_at.desc()).limit(limit).all()
            
            if not logs:
                console.print("[yellow]No audit log entries found[/yellow]")
                return
            
            table = Table(title=f"Tagging Audit Log (Last {len(logs)} entries)", 
                         show_header=True, header_style="bold magenta")
            table.add_column("Time", style="dim", width=16)
            table.add_column("Resource", style="cyan", width=25)
            table.add_column("Operation", style="white", width=16)
            table.add_column("Success", style="green", width=8)
            table.add_column("Principal", style="blue", width=15)
            table.add_column("Tags", style="yellow", width=16)
            
            for log in logs:
                resource_display = log.resource_arn.split(':')[-1] if ':' in log.resource_arn else log.resource_arn
                if len(resource_display) > 20:
                    resource_display = resource_display[:17] + "..."
                
                principal_display = "N/A"
                if log.principal_info and 'user_name' in log.principal_info:
                    principal_display = log.principal_info['user_name']
                elif log.principal_info and 'arn' in log.principal_info:
                    principal_display = log.principal_info['arn'].split('/')[-1]
                
                if len(principal_display) > 18:
                    principal_display = principal_display[:15] + "..."
                
                # Count tags
                tag_count = 0
                if log.new_tags:
                    tag_count = len(log.new_tags)
                
                table.add_row(
                    log.executed_at.strftime("%Y-%m-%d %H:%M"),
                    resource_display,
                    log.operation,
                    "OK" if log.success else "ERROR",
                    principal_display,
                    f"{tag_count} tag(s)" if tag_count > 0 else "N/A"
                )
            
            console.print(table)
            
    except Exception as e:
        console.print(f"[red]Error showing audit log: {e}[/red]")
        raise typer.Exit(1)


@tags_app.command("status")
def show_status():
    """
    Show comprehensive tagging system dashboard with status, metrics, and recommendations.
    
    This command provides a complete overview of your tagging system health,
    including compliance metrics, lifecycle management, active rules, recent activity,
    and actionable recommendations for improvement.
    """
    try:
        from datetime import datetime, timezone, timedelta
        
        console.print("\n[bold cyan][DASHBOARD] Tag Management System Dashboard[/bold cyan]")
        console.print("[dim]Comprehensive overview of your AWS tagging infrastructure[/dim]\n")
        
        with get_db_session() as session:
            # === CORE METRICS ===
            total_resources = session.query(Resource).count()
            active_rules = session.query(TaggingRule).filter_by(enabled=True).count()
            total_rules = session.query(TaggingRule).count()
            
            # Lifecycle metrics
            lifecycle_policies = session.query(ResourceLifecyclePolicy).filter_by(enabled=True).count()
            total_lifecycle_policies = session.query(ResourceLifecyclePolicy).count()
            resources_with_ttl = session.query(Resource).filter(Resource.expires_at.isnot(None)).count()
            
            now = datetime.now(timezone.utc)
            expired_resources = session.query(Resource).filter(
                Resource.expires_at.isnot(None),
                Resource.expires_at <= now,
                Resource.lifecycle_state != 'deleted'
            ).count()
            
            # === COMPLIANCE ANALYSIS ===
            required_tags = ["Environment", "Owner", "CostCenter"]
            compliance_stats = {"fully_compliant": 0, "partially_compliant": 0, "untagged": 0}
            service_breakdown = {}
            risk_analysis = {"high_risk": 0, "medium_risk": 0, "low_risk": 0}
            
            for resource in session.query(Resource).all():
                current_tags = resource.current_tags or {}
                missing_tags = [tag for tag in required_tags if tag not in current_tags]
                
                # Compliance classification
                if not missing_tags:
                    compliance_stats["fully_compliant"] += 1
                elif len(missing_tags) < len(required_tags):
                    compliance_stats["partially_compliant"] += 1
                else:
                    compliance_stats["untagged"] += 1
                
                # Service breakdown
                service = resource.service_name
                if service not in service_breakdown:
                    service_breakdown[service] = {"total": 0, "compliant": 0}
                service_breakdown[service]["total"] += 1
                if not missing_tags:
                    service_breakdown[service]["compliant"] += 1
                
                # Risk analysis
                age_hours = 0
                if resource.created_at:
                    age_delta = now - resource.created_at.replace(tzinfo=timezone.utc)
                    age_hours = age_delta.total_seconds() / 3600
                
                if missing_tags:
                    if age_hours > 168 or service in ["ec2", "rds", "redshift"]:  # High-cost services or old
                        risk_analysis["high_risk"] += 1
                    elif age_hours > 24:
                        risk_analysis["medium_risk"] += 1
                    else:
                        risk_analysis["low_risk"] += 1
            
            compliance_rate = (compliance_stats["fully_compliant"] / max(total_resources, 1)) * 100
            
            # === SYSTEM HEALTH OVERVIEW ===
            health_table = Table(title="[HEALTH] System Health Overview", show_header=True, header_style="bold green")
            health_table.add_column("Component", style="white", width=25)
            health_table.add_column("Status", style="cyan", width=16)
            health_table.add_column("Details", style="dim", width=30)
            
            # Health indicators
            health_table.add_row(
                "Resource Discovery",
                f"[green]HEALTHY[/green]" if total_resources > 0 else f"[red]NO DATA[/red]",
                f"{total_resources:,} resources tracked"
            )
            
            health_table.add_row(
                "Tag Compliance",
                f"[green]GOOD[/green]" if compliance_rate >= 80 else f"[yellow]NEEDS ATTENTION[/yellow]" if compliance_rate >= 50 else f"[red]CRITICAL[/red]",
                f"{compliance_rate:.1f}% fully compliant"
            )
            
            health_table.add_row(
                "Automation Rules",
                f"[green]ACTIVE[/green]" if active_rules > 0 else f"[yellow]INACTIVE[/yellow]",
                f"{active_rules}/{total_rules} rules enabled"
            )
            
            health_table.add_row(
                "Lifecycle Management",
                f"[green]CONFIGURED[/green]" if lifecycle_policies > 0 else f"[yellow]NOT CONFIGURED[/yellow]",
                f"{lifecycle_policies}/{total_lifecycle_policies} policies active"
            )
            
            console.print(health_table)
            
            # === COMPLIANCE DASHBOARD ===
            compliance_table = Table(title="[COMPLIANCE] Compliance Dashboard", show_header=True, header_style="bold magenta")
            compliance_table.add_column("Metric", style="white", width=15)
            compliance_table.add_column("Count", style="cyan", justify="right", width=9)
            compliance_table.add_column("Percentage", style="yellow", justify="right", width=8)
            compliance_table.add_column("Trend", style="green", width=9)
            
            compliance_table.add_row("Fully Compliant", str(compliance_stats["fully_compliant"]), f"{(compliance_stats['fully_compliant']/max(total_resources,1)*100):.1f}%", "[ACTIVITY]")
            compliance_table.add_row("Partially Compliant", str(compliance_stats["partially_compliant"]), f"{(compliance_stats['partially_compliant']/max(total_resources,1)*100):.1f}%", "[DASHBOARD]")
            compliance_table.add_row("Untagged", str(compliance_stats["untagged"]), f"{(compliance_stats['untagged']/max(total_resources,1)*100):.1f}%", "[DOWN]" if compliance_stats["untagged"] < total_resources * 0.2 else "[WARN]")
            
            console.print(compliance_table)
            
            # === RISK ANALYSIS ===
            risk_table = Table(title="[WARN] Risk Analysis", show_header=True, header_style="bold red")
            risk_table.add_column("Risk Level", style="white", width=16)
            risk_table.add_column("Resources", style="cyan", justify="right", width=9)
            risk_table.add_column("Impact", style="yellow", width=25)
            risk_table.add_column("Action Required", style="red", width=15)
            
            risk_table.add_row(
                "[red]HIGH RISK[/red]", 
                str(risk_analysis["high_risk"]), 
                "Old/expensive untagged resources",
                "IMMEDIATE" if risk_analysis["high_risk"] > 0 else "None"
            )
            risk_table.add_row(
                "[yellow]MEDIUM RISK[/yellow]", 
                str(risk_analysis["medium_risk"]), 
                "Recent untagged resources",
                "Within 48h" if risk_analysis["medium_risk"] > 0 else "None"
            )
            risk_table.add_row(
                "[green]LOW RISK[/green]", 
                str(risk_analysis["low_risk"]), 
                "Newly created resources",
                "Monitor" if risk_analysis["low_risk"] > 0 else "None"
            )
            
            console.print(risk_table)
            
            # === SERVICE BREAKDOWN ===
            if service_breakdown:
                service_table = Table(title="[SERVICE] Service Compliance Breakdown", show_header=True, header_style="bold blue")
                service_table.add_column("Service", style="cyan", width=16)
                service_table.add_column("Total", style="white", justify="right", width=8)
                service_table.add_column("Compliant", style="green", justify="right", width=9)
                service_table.add_column("Compliance %", style="yellow", justify="right", width=8)
                service_table.add_column("Priority", style="red", width=9)
                
                # Sort by compliance rate (worst first)
                sorted_services = sorted(service_breakdown.items(), 
                                       key=lambda x: x[1]["compliant"] / max(x[1]["total"], 1))
                
                for service, stats in sorted_services[:8]:  # Top 8 services
                    total = stats["total"]
                    compliant = stats["compliant"]
                    compliance_pct = (compliant / max(total, 1)) * 100
                    
                    priority = "HIGH" if compliance_pct < 50 else "MED" if compliance_pct < 80 else "LOW"
                    priority_color = "red" if priority == "HIGH" else "yellow" if priority == "MED" else "green"
                    
                    service_table.add_row(
                        service.upper(),
                        str(total),
                        str(compliant),
                        f"{compliance_pct:.1f}%",
                        f"[{priority_color}]{priority}[/{priority_color}]"
                    )
                
                console.print(service_table)
            
            # === LIFECYCLE MANAGEMENT ===
            if resources_with_ttl > 0 or expired_resources > 0:
                lifecycle_table = Table(title="[TIME] Lifecycle Management Status", show_header=True, header_style="bold purple")
                lifecycle_table.add_column("Metric", style="white", width=25)
                lifecycle_table.add_column("Count", style="cyan", justify="right", width=9)
                lifecycle_table.add_column("Status", style="yellow", width=16)
                
                lifecycle_table.add_row("Resources with TTL", str(resources_with_ttl), "Managed")
                lifecycle_table.add_row("Expired Resources", str(expired_resources), "REQUIRES ACTION" if expired_resources > 0 else "OK")
                lifecycle_table.add_row("Active Policies", str(lifecycle_policies), "Configured" if lifecycle_policies > 0 else "None")
                
                console.print(lifecycle_table)
            
            # === RECENT ACTIVITY ===
            try:
                tagging_stats = get_tagging_statistics()
                recent_ops = tagging_stats.get('total_operations_24h', 0)
                recent_success = tagging_stats.get('successful_operations_24h', 0)
                success_rate = tagging_stats.get('success_rate_24h', 0)
                
                activity_table = Table(title="[ACTIVITY] Recent Activity (24 hours)", show_header=True, header_style="bold cyan")
                activity_table.add_column("Metric", style="white", width=25)
                activity_table.add_column("Count", style="cyan", justify="right", width=9)
                activity_table.add_column("Rate", style="yellow", justify="right", width=9)
                
                activity_table.add_row("Total Operations", str(recent_ops), "-")
                activity_table.add_row("Successful Operations", str(recent_success), f"{success_rate:.1f}%")
                activity_table.add_row("Failed Operations", str(recent_ops - recent_success), f"{(100-success_rate):.1f}%")
                
                console.print(activity_table)
            except:
                pass
            
            # === ACTIONABLE RECOMMENDATIONS ===
            console.print("\n[bold blue][TARGET] Recommended Actions[/bold blue]")
            
            recommendations = []
            
            if compliance_rate < 50:
                recommendations.append(("[CRITICAL] CRITICAL", "Low compliance rate", "tag-manager tags scan && tag-manager tags apply --interactive"))
            elif compliance_rate < 80:
                recommendations.append(("[WARN] IMPORTANT", "Moderate compliance issues", "tag-manager tags scan && tag-manager tags apply --auto"))
            
            if risk_analysis["high_risk"] > 0:
                recommendations.append(("[URGENT] URGENT", f"{risk_analysis['high_risk']} high-risk resources", "tag-manager tags apply --interactive"))
            
            if active_rules == 0:
                recommendations.append(("[SETUP] SETUP", "No automation rules active", "tag-manager tags rules load config/sample_tagging_rules.json"))
            
            if expired_resources > 0:
                recommendations.append(("[CLEANUP] CLEANUP", f"{expired_resources} expired resources", "tag-manager tags lifecycle scan-expired"))
            
            if lifecycle_policies == 0 and total_resources > 50:
                recommendations.append(("[TIME] LIFECYCLE", "No lifecycle management", "Configure lifecycle policies for resource cleanup"))
            
            if not recommendations:
                console.print("[green][OK] System is healthy! No immediate actions required.[/green]")
            else:
                for priority, issue, action in recommendations[:5]:  # Show top 5
                    console.print(f"{priority} {issue}")
                    console.print(f"   [cyan]{action}[/cyan]")
            
            # === QUICK ACTIONS ===
            console.print(f"\n[bold green][ACTION] Quick Actions[/bold green]")
            console.print("- [cyan]tag-manager tags scan[/cyan]                    # Find issues")
            console.print("- [cyan]tag-manager tags apply --interactive[/cyan]     # Fix high-priority resources")
            console.print("- [cyan]tag-manager tags apply --auto[/cyan]            # Apply automation")
            console.print("- [cyan]tag-manager tags lifecycle scan-expired[/cyan] # Check expiring resources")
            console.print("- [cyan]tag-manager tags report compliance[/cyan]      # Generate detailed report")
            
    except Exception as e:
        safe_print(f"Error generating dashboard: {e}", "red")
        raise typer.Exit(1)


# === HELPER FUNCTIONS FOR ENHANCED SCAN RESULTS ===

def _show_compliance_overview(compliance_stats: Dict, service_stats: Dict, total_resources: int):
    """Show compliance overview when all resources are compliant."""
    console.print("\n[bold green]Compliance Overview[/bold green]")
    
    overview_table = Table(show_header=True, header_style="bold green")
    overview_table.add_column("Metric", style="white")
    overview_table.add_column("Value", style="green", justify="right")
    
    overview_table.add_row("Total Resources Scanned", str(total_resources))
    overview_table.add_row("Fully Compliant", str(compliance_stats.get("fully_compliant", 0)))
    overview_table.add_row("Compliance Rate", "100%")
    
    console.print(overview_table)
    
    if service_stats:
        service_table = Table(title="Compliance by Service", show_header=True, header_style="bold green")
        service_table.add_column("Service", style="cyan")
        service_table.add_column("Resources", style="white", justify="right")
        
        for service, stats in service_stats.items():
            service_table.add_row(service.upper(), str(stats["total"]))
        
        console.print(service_table)


def _show_scan_overview(total_resources: int, untagged_resources: List, compliance_stats: Dict, 
                       service_stats: Dict, risk_analysis: Dict, required_tags: List):
    """Show comprehensive scan overview with statistics and risk analysis."""
    
    # Main overview panel
    overview_text = f"""
[bold]Scan Results Summary[/bold]

[cyan]Resources Analyzed:[/cyan] {total_resources}
[red]Untagged Resources:[/red] {len(untagged_resources)}
[green]Compliance Rate:[/green] {(compliance_stats.get('fully_compliant', 0) / max(total_resources, 1) * 100):.1f}%

[bold yellow]Risk Analysis:[/bold yellow]
- [red]High Risk:[/red] {risk_analysis.get('high_risk', 0)} (old/expensive resources)
- [yellow]Medium Risk:[/yellow] {risk_analysis.get('medium_risk', 0)} (1+ days old)
- [green]Low Risk:[/green] {risk_analysis.get('low_risk', 0)} (recently created)
"""
    
    console.print(Panel(overview_text, title="Resource Tagging Analysis", border_style="blue"))
    
    # Compliance breakdown
    if total_resources > 0:
        compliance_table = Table(title="Compliance Breakdown", show_header=True, header_style="bold magenta")
        compliance_table.add_column("Status", style="white")
        compliance_table.add_column("Count", style="cyan", justify="right")
        compliance_table.add_column("Percentage", style="yellow", justify="right")
        
        for status, count in compliance_stats.items():
            percentage = (count / total_resources * 100)
            status_display = status.replace("_", " ").title()
            if status == "fully_compliant":
                compliance_table.add_row(f"[green]{status_display}[/green]", str(count), f"{percentage:.1f}%")
            elif status == "partially_compliant":
                compliance_table.add_row(f"[yellow]{status_display}[/yellow]", str(count), f"{percentage:.1f}%")
            else:
                compliance_table.add_row(f"[red]{status_display}[/red]", str(count), f"{percentage:.1f}%")
        
        console.print(compliance_table)
    
    # Service breakdown
    if service_stats:
        service_table = Table(title="Issues by Service", show_header=True, header_style="bold magenta")
        service_table.add_column("Service", style="cyan")
        service_table.add_column("Total", style="white", justify="right")
        service_table.add_column("Untagged", style="red", justify="right")
        service_table.add_column("Compliance", style="yellow", justify="right")
        
        # Sort by compliance rate (worst first)
        sorted_services = sorted(service_stats.items(), 
                               key=lambda x: (x[1]["total"] - x[1]["untagged"]) / max(x[1]["total"], 1))
        
        for service, stats in sorted_services:
            total = stats["total"]
            untagged = stats["untagged"]
            compliance_rate = ((total - untagged) / max(total, 1)) * 100
            
            color = "green" if compliance_rate >= 80 else "yellow" if compliance_rate >= 50 else "red"
            service_table.add_row(
                service.upper(),
                str(total),
                str(untagged),
                f"[{color}]{compliance_rate:.1f}%[/{color}]"
            )
        
        console.print(service_table)


def _show_intelligent_next_steps(untagged_resources: List, service_stats: Dict, risk_analysis: Dict):
    """Show intelligent next steps based on the analysis."""
    console.print("\n[bold blue]Recommended Actions[/bold blue]")
    
    high_risk_count = risk_analysis.get("high_risk", 0)
    total_untagged = len(untagged_resources)
    
    # Priority-based recommendations
    if high_risk_count > 0:
        console.print(f"[bold red]URGENT:[/bold red] {high_risk_count} high-risk resources need immediate attention!")
        console.print("   [cyan]tag-manager tags apply --interactive[/cyan]  # Tag high-priority resources first")
    
    # Service-specific recommendations
    problem_services = []
    for service, stats in service_stats.items():
        if stats.get("untagged", 0) >= 5:  # 5+ untagged resources
            problem_services.append((service, stats["untagged"]))
    
    if problem_services:
        console.print(f"\n[bold yellow]Bulk Tagging Opportunities:[/bold yellow]")
        for service, count in sorted(problem_services, key=lambda x: x[1], reverse=True)[:3]:
            console.print(f"   [cyan]tag-manager tags bulk {service}[/cyan]     # Fix {count} {service.upper()} resources")
    
    # Automation recommendations
    if total_untagged >= 10:
        console.print(f"\n[bold green]Automation Setup:[/bold green]")
        console.print("   [cyan]tag-manager tags rules load config/sample_tagging_rules.json[/cyan]")
        console.print("   [cyan]tag-manager tags apply --auto[/cyan]        # Apply automation rules")
    
    # General workflow
    console.print(f"\n[bold magenta]Complete Workflow:[/bold magenta]")
    console.print("1. [dim]tag-manager tags apply --interactive[/dim]  # Start with high-priority resources")
    console.print("2. [dim]tag-manager tags bulk <service>[/dim]       # Bulk tag by service type")
    console.print("3. [dim]tag-manager tags rules[/dim]                 # Set up automation rules")
    console.print("4. [dim]tag-manager tags apply --auto[/dim]          # Apply automated tagging")
    console.print("5. [dim]tag-manager tags report compliance[/dim]     # Monitor progress")
    
    console.print(f"\n[dim]For help with any command: tag-manager tags <command> --help[/dim]")


# === RULE MANAGEMENT FUNCTIONS ===

def _list_rules(enabled_only: bool, resource_type: Optional[str]):
    """List tagging rules."""
    console.print("[blue]Automated Tagging Rules[/blue]")
    console.print("[dim]Rules automatically apply tags based on resource properties[/dim]\n")
    
    # TODO: Implement rule listing from database
    console.print("[yellow]Rule listing not yet implemented - loading from config files[/yellow]")


# Duplicate function removed - using the proper implementation above


def _enable_rule(rule_name: str):
    """Enable a specific rule."""
    console.print(f"[yellow]Enabling rule '{rule_name}' - not yet implemented[/yellow]")


def _disable_rule(rule_name: str):
    """Disable a specific rule."""
    console.print(f"[yellow]Disabling rule '{rule_name}' - not yet implemented[/yellow]")


def _interactive_rule_creation():
    """Interactive CLI-based tag rule creation with JSON schema generation."""
    from rich.prompt import Prompt, Confirm
    from rich.table import Table
    from rich.panel import Panel
    import json
    from pathlib import Path
    from datetime import datetime
    
    console.print("[bold blue]Interactive Tag Rule Creation[/bold blue]")
    console.print("[dim]Create meaningful tagging rules with built-in templates and validation[/dim]\n")
    
    # Step 0: Choose creation method
    console.print("[bold]How would you like to create your rule?[/bold]")
    console.print("1. [cyan]Use a pre-built template[/cyan] (recommended for beginners)")
    console.print("2. [yellow]Create from scratch[/yellow] (for advanced users)")
    console.print("3. [green]Quick mandatory tags setup[/green] (enforce essential tags)")
    
    creation_method = Prompt.ask("Choose method", choices=["1", "2", "3"], default="1")
    
    if creation_method == "1":
        return _create_rule_from_template()
    elif creation_method == "3":
        return _create_mandatory_tags_rule()
    # else: continue with from-scratch creation (original code)
    
    # Step 1: Basic rule information
    console.print("\n[bold]Step 1: Rule Information[/bold]")
    rule_name = Prompt.ask("Rule name", default="custom_tagging_rule")
    description = Prompt.ask("Rule description", default="Custom tagging rule created via CLI")
    priority = int(Prompt.ask("Priority (1-1000, higher = more important)", default="100"))
    
    console.print(f"\n[cyan]Rule: {rule_name}[/cyan]")
    console.print(f"Description: {description}")
    console.print(f"Priority: {priority}\n")
    
    # Step 2: Resource types selection
    console.print("[bold]Step 1: Select Resource Types[/bold]")
    console.print("Choose which AWS resource types this rule applies to:")
    
    available_types = [
        "AWS::EC2::Instance",
        "AWS::S3::Bucket", 
        "AWS::Lambda::Function",
        "AWS::EC2::Volume",
        "AWS::RDS::DBInstance",
        "AWS::ECS::Service",
        "AWS::ElasticLoadBalancing::LoadBalancer"
    ]
    
    resource_types = []
    for resource_type in available_types:
        if Confirm.ask(f"  Include {resource_type}?", default=False):
            resource_types.append(resource_type)
    
    if not resource_types:
        console.print("[yellow]No resource types selected. Adding EC2 instances by default.[/yellow]")
        resource_types = ["AWS::EC2::Instance"]
    
    console.print(f"\nSelected resource types: {', '.join(resource_types)}")
    
    # Step 3: Conditions
    console.print("\n[bold]Step 2: Set Conditions (Optional)[/bold]")
    console.print("Add conditions that resources must meet for this rule to apply:")
    
    conditions = []
    add_conditions = Confirm.ask("Add conditions to this rule?", default=False)
    
    while add_conditions:
        condition_field = Prompt.ask("Condition field (e.g., 'resource.name', 'resource.region')", default="resource.name")
        condition_operator = Prompt.ask("Operator", choices=["exists", "contains", "equals", "startswith"], default="exists")
        
        condition = {"field": condition_field, "operator": condition_operator}
        
        if condition_operator != "exists":
            condition["value"] = Prompt.ask(f"Value to {condition_operator}")
        
        conditions.append(condition)
        console.print(f"Added condition: {condition}")
        
        add_conditions = Confirm.ask("Add another condition?", default=False)
    
    # Step 4: Tag templates
    console.print("\n[bold]Step 3: Define Tag Templates[/bold]")
    console.print("Define the tags that will be applied to matching resources:")
    
    tag_templates = []
    
    while True:
        tag_key = Prompt.ask("Tag key (e.g., 'Environment', 'Owner')")
        
        console.print("\nChoose tag value type:")
        console.print("1. Static value (same for all resources)")
        console.print("2. Dynamic template (uses resource properties)")
        console.print("3. Common templates (predefined patterns)")
        
        value_type = Prompt.ask("Value type", choices=["1", "2", "3"], default="1")
        
        if value_type == "1":
            tag_value = Prompt.ask("Static tag value")
        elif value_type == "2":
            console.print("\nDynamic templates use Jinja2 syntax:")
            console.print("  {{ resource.name }}           - Resource name")
            console.print("  {{ resource.region }}         - AWS region")
            console.print("  {{ resource.service_name }}   - Service type")
            console.print("  {{ principal.user_name }}     - Creator username")
            console.print("  {{ date }}                    - Current date")
            console.print("  {{ datetime }}                - Current timestamp")
            
            tag_value = Prompt.ask("Template expression", default="{{ resource.name }}")
        else:  # Common templates
            console.print("\nCommon template options:")
            templates = {
                "1": ("{{ date }}", "Current date (YYYY-MM-DD)"),
                "2": ("{{ principal.user_name | default('unknown') }}", "Resource creator"),
                "3": ("{% if 'prod' in resource.name.lower() %}production{% else %}development{% endif %}", "Environment from name"),
                "4": ("{{ resource.region }}", "AWS region"),
                "5": ("auto-tagged", "Static 'auto-tagged' value")
            }
            
            for num, (template, desc) in templates.items():
                console.print(f"  {num}. {desc}")
            
            choice = Prompt.ask("Choose template", choices=list(templates.keys()), default="1")
            tag_value = templates[choice][0]
        
        tag_templates.append({"key": tag_key, "value": tag_value})
        console.print(f"Added tag: [cyan]{tag_key}[/cyan] = [white]{tag_value}[/white]")
        
        if not Confirm.ask("Add another tag?", default=True):
            break
    
    # Step 5: Review and save
    console.print("\n[bold]Rule Summary[/bold]")
    
    rule_data = {
        "name": rule_name,
        "description": description,
        "resource_types": resource_types,
        "conditions": conditions,
        "tag_templates": tag_templates,
        "priority": priority,
        "enabled": True,
        "created_at": datetime.now().isoformat(),
        "created_by": "tag-manager-cli"
    }
    
    # Display summary table
    summary_table = Table(title="Rule Summary", show_header=True, header_style="bold magenta")
    summary_table.add_column("Property", style="cyan")
    summary_table.add_column("Value", style="white")
    
    summary_table.add_row("Name", rule_name)
    summary_table.add_row("Description", description)
    summary_table.add_row("Priority", str(priority))
    summary_table.add_row("Resource Types", ", ".join(resource_types))
    summary_table.add_row("Conditions", str(len(conditions)))
    summary_table.add_row("Tags", str(len(tag_templates)))
    
    console.print(summary_table)
    
    # Show tag preview
    if tag_templates:
        console.print("\n[bold]Tag Templates:[/bold]")
        tag_table = Table(show_header=True, header_style="bold green")
        tag_table.add_column("Key", style="cyan")
        tag_table.add_column("Value Template", style="white")
        
        for tag in tag_templates:
            tag_table.add_row(tag["key"], tag["value"])
        
        console.print(tag_table)
    
    # Save options
    console.print("\n[bold]Save Options[/bold]")
    save_rule = Confirm.ask("Save this rule?", default=True)
    
    if save_rule:
        # Default to user's custom rules file
        default_path = "config/custom_tagging_rules.json"
        file_path = Prompt.ask("Save to file", default=default_path)
        
        try:
            # Ensure directory exists
            Path(file_path).parent.mkdir(parents=True, exist_ok=True)
            
            # Load existing rules if file exists
            existing_rules = []
            if Path(file_path).exists():
                try:
                    with open(file_path, 'r') as f:
                        existing_rules = json.load(f)
                except:
                    existing_rules = []
            
            # Add new rule
            existing_rules.append(rule_data)
            
            # Save updated rules
            with open(file_path, 'w') as f:
                json.dump(existing_rules, f, indent=2, default=str)
            
            console.print(f"[green]OK Rule saved to {file_path}[/green]")
            console.print(f"[dim]Load it with: tag-manager tags rules load {file_path}[/dim]")
            
        except Exception as e:
            console.print(f"[red]Error saving rule: {e}[/red]")
            
            # Offer to display JSON instead
            if Confirm.ask("Display JSON rule instead?", default=True):
                console.print("\n[bold]Rule JSON:[/bold]")
                console.print(json.dumps(rule_data, indent=2, default=str))
    
    else:
        console.print("[yellow]Rule not saved.[/yellow]")


def _create_rule_from_template():
    """Create a rule from pre-built templates."""
    from rich.prompt import Prompt, Confirm
    from rich.table import Table
    from rich.panel import Panel
    import json
    from pathlib import Path
    from datetime import datetime
    
    console.print("\n[bold green]Pre-Built Rule Templates[/bold green]")
    console.print("[dim]Choose from proven tagging patterns used in production environments[/dim]\n")
    
    # Define useful rule templates
    templates = {
        "1": {
            "name": "Environment Classification",
            "description": "Automatically tag resources with Environment based on naming patterns",
            "use_case": "Classify Dev/Staging/Prod resources by name",
            "example": "my-app-prod-server → Environment: Production",
            "rule": {
                "name": "environment_classification",
                "description": "Classify resources into environments based on naming patterns",
                "resource_types": ["AWS::EC2::Instance", "AWS::S3::Bucket", "AWS::Lambda::Function", "AWS::EC2::Volume"],
                "conditions": [{"field": "resource.name", "operator": "exists"}],
                "tag_templates": [
                    {
                        "key": "Environment",
                        "value": "{% if 'prod' in resource.name.lower() %}Production{% elif 'staging' in resource.name.lower() or 'stage' in resource.name.lower() %}Staging{% elif 'dev' in resource.name.lower() %}Development{% elif 'test' in resource.name.lower() %}Testing{% else %}Unknown{% endif %}"
                    },
                    {
                        "key": "AutoClassified",
                        "value": "true"
                    }
                ],
                "priority": 200,
                "enabled": True
            }
        },
        "2": {
            "name": "Owner Attribution", 
            "description": "Tag resources with owner information from CloudTrail",
            "use_case": "Track who created resources for accountability",
            "example": "EC2 created by john.doe → Owner: john.doe",
            "rule": {
                "name": "owner_attribution",
                "description": "Tag resources with owner information from CloudTrail",
                "resource_types": ["AWS::EC2::Instance", "AWS::S3::Bucket", "AWS::Lambda::Function", "AWS::EC2::Volume", "AWS::RDS::DBInstance"],
                "conditions": [{"field": "resource.created_at", "operator": "exists"}],
                "tag_templates": [
                    {
                        "key": "Owner", 
                        "value": "{{ principal.user_name | default('unknown') }}"
                    },
                    {
                        "key": "CreatedBy",
                        "value": "{{ principal.user_name | default('system') }}"
                    },
                    {
                        "key": "CreatedDate",
                        "value": "{{ resource.created_at.strftime('%Y-%m-%d') if resource.created_at else date }}"
                    }
                ],
                "priority": 300,
                "enabled": True
            }
        },
        "3": {
            "name": "Cost Center Allocation",
            "description": "Add cost tracking and billing tags",
            "use_case": "Enable cost allocation and chargeback",
            "example": "Resources → CostCenter: Engineering, BillingGroup: R&D",
            "rule": {
                "name": "cost_center_allocation", 
                "description": "Add cost tracking and billing tags based on resource patterns",
                "resource_types": ["AWS::EC2::Instance", "AWS::S3::Bucket", "AWS::Lambda::Function", "AWS::RDS::DBInstance", "AWS::EC2::Volume"],
                "conditions": [],
                "tag_templates": [
                    {
                        "key": "CostCenter",
                        "value": "{% if 'data' in resource.name.lower() %}DataEngineering{% elif 'web' in resource.name.lower() or 'api' in resource.name.lower() %}Engineering{% elif 'db' in resource.name.lower() %}Database{% else %}General{% endif %}"
                    },
                    {
                        "key": "BillingGroup", 
                        "value": "{% if 'prod' in resource.name.lower() %}Production{% else %}Development{% endif %}"
                    },
                    {
                        "key": "CostOptimization",
                        "value": "{% if resource.service_name in ['ec2', 'rds'] %}monitor{% else %}standard{% endif %}"
                    }
                ],
                "priority": 150,
                "enabled": True
            }
        },
        "4": {
            "name": "Compliance Classification",
            "description": "Add security and compliance tags",  
            "use_case": "Meet security and regulatory requirements",
            "example": "Resources → DataClassification, BackupRequired, etc.",
            "rule": {
                "name": "compliance_classification",
                "description": "Apply security and compliance tags based on resource characteristics",
                "resource_types": ["AWS::EC2::Instance", "AWS::S3::Bucket", "AWS::Lambda::Function", "AWS::RDS::DBInstance"],
                "conditions": [],
                "tag_templates": [
                    {
                        "key": "DataClassification",
                        "value": "{% if 'prod' in resource.name.lower() %}Internal{% elif 'public' in resource.name.lower() %}Public{% else %}Internal{% endif %}"
                    },
                    {
                        "key": "BackupRequired",
                        "value": "{% if resource.service_name in ['ec2', 'rds'] and 'prod' in resource.name.lower() %}Daily{% elif resource.service_name in ['ec2', 'rds'] %}Weekly{% else %}None{% endif %}"
                    },
                    {
                        "key": "SecurityReview",
                        "value": "{% if 'prod' in resource.name.lower() %}Required{% else %}Optional{% endif %}"
                    }
                ],
                "priority": 250,
                "enabled": True
            }
        },
        "5": {
            "name": "Project Attribution",
            "description": "Tag resources with project information",
            "use_case": "Group resources by project for management",
            "example": "my-ecommerce-api → Project: ecommerce, Component: api",
            "rule": {
                "name": "project_attribution",
                "description": "Infer project and component from resource naming patterns",
                "resource_types": ["AWS::EC2::Instance", "AWS::S3::Bucket", "AWS::Lambda::Function"],
                "conditions": [{"field": "resource.name", "operator": "exists"}],
                "tag_templates": [
                    {
                        "key": "Project",
                        "value": "{% set parts = resource.name.lower().split('-') %}{% if parts|length >= 2 %}{{ parts[0] }}-{{ parts[1] }}{% else %}{{ parts[0] if parts else 'unknown' }}{% endif %}"
                    },
                    {
                        "key": "Component",
                        "value": "{% if 'api' in resource.name.lower() %}API{% elif 'web' in resource.name.lower() %}Frontend{% elif 'db' in resource.name.lower() %}Database{% elif 'worker' in resource.name.lower() %}BackgroundJob{% else %}Application{% endif %}"
                    },
                    {
                        "key": "ServiceTier",
                        "value": "{% if 'web' in resource.name.lower() %}Presentation{% elif 'api' in resource.name.lower() %}Application{% elif 'db' in resource.name.lower() %}Data{% else %}Support{% endif %}"
                    }
                ],
                "priority": 100,
                "enabled": True
            }
        }
    }
    
    # Show template options
    template_table = Table(title="Available Rule Templates", show_header=True, header_style="bold magenta")
    template_table.add_column("Option", style="cyan", width=8)
    template_table.add_column("Template", style="white", width=25)
    template_table.add_column("Use Case", style="dim", width=40)
    template_table.add_column("Example", style="green", width=35)
    
    for key, template in templates.items():
        template_table.add_row(
            key,
            template["name"], 
            template["use_case"],
            template["example"]
        )
    
    console.print(template_table)
    
    # Get user choice
    choice = Prompt.ask("Select template", choices=list(templates.keys()), default="1")
    selected_template = templates[choice]
    
    # Show detailed template info
    console.print(f"\n[bold cyan]Selected: {selected_template['name']}[/bold cyan]")
    console.print(f"[dim]{selected_template['description']}[/dim]\n")
    
    rule_data = selected_template["rule"].copy()
    rule_data["created_at"] = datetime.now().isoformat()
    rule_data["created_by"] = "tag-manager-cli"
    
    # Allow customization
    customize = Confirm.ask("Customize this template?", default=False)
    if customize:
        # Allow basic customization
        rule_data["name"] = Prompt.ask("Rule name", default=rule_data["name"])
        rule_data["description"] = Prompt.ask("Description", default=rule_data["description"])
        rule_data["priority"] = int(Prompt.ask("Priority (1-1000)", default=str(rule_data["priority"])))
    
    # Show preview
    _preview_rule(rule_data)
    
    # Save
    save_rule = Confirm.ask("Save this rule?", default=True)
    if save_rule:
        _save_rule_to_file(rule_data)
    else:
        console.print("[yellow]Rule not saved[/yellow]")


def _create_mandatory_tags_rule():
    """Create a rule to enforce mandatory tags."""
    from rich.prompt import Prompt, Confirm
    import json
    from datetime import datetime
    
    console.print("\n[bold green]Mandatory Tags Enforcement[/bold green]")
    console.print("[dim]Ensure all resources have essential tags for governance and cost tracking[/dim]\n")
    
    # Define the 4 core mandatory tags
    mandatory_tags = [
        {
            "key": "Environment",
            "description": "Deployment environment (Dev/Staging/Prod)",
            "default": "Development",
            "required": True
        },
        {
            "key": "Owner", 
            "description": "Team or person responsible for the resource",
            "default": "unassigned@company.com",
            "required": True
        },
        {
            "key": "Project",
            "description": "Project or application name",
            "default": "unclassified",
            "required": True
        },
        {
            "key": "CostCenter",
            "description": "Billing/cost center for chargeback",
            "default": "general",
            "required": False  # Optional but recommended
        }
    ]
    
    console.print("[bold]The following mandatory tags will be enforced:[/bold]")
    for tag in mandatory_tags:
        required_text = "[red]Required[/red]" if tag["required"] else "[yellow]Recommended[/yellow]"
        console.print(f"  • [cyan]{tag['key']}[/cyan]: {tag['description']} {required_text}")
        console.print(f"    Default: [dim]{tag['default']}[/dim]")
    
    console.print()
    proceed = Confirm.ask("Create enforcement rule for these tags?", default=True)
    
    if not proceed:
        console.print("[yellow]Mandatory tags rule creation cancelled[/yellow]")
        return
    
    # Create the rule
    rule_data = {
        "name": "mandatory_tags_enforcement",
        "description": "Enforce mandatory tags for governance and cost tracking",
        "resource_types": [
            "AWS::EC2::Instance",
            "AWS::S3::Bucket", 
            "AWS::Lambda::Function",
            "AWS::EC2::Volume",
            "AWS::RDS::DBInstance",
            "AWS::ECS::Service"
        ],
        "conditions": [],  # Apply to all resources
        "tag_templates": [
            {
                "key": "Environment",
                "value": "{% if 'prod' in resource.name.lower() %}Production{% elif 'staging' in resource.name.lower() or 'stage' in resource.name.lower() %}Staging{% elif 'test' in resource.name.lower() %}Testing{% else %}Development{% endif %}"
            },
            {
                "key": "Owner", 
                "value": "{{ principal.user_name | default('unassigned@company.com') }}"
            },
            {
                "key": "Project",
                "value": "{% set parts = resource.name.lower().split('-') %}{% if parts|length >= 1 %}{{ parts[0] }}{% else %}unclassified{% endif %}"
            },
            {
                "key": "CostCenter",
                "value": "{% if 'prod' in resource.name.lower() %}production{% elif 'dev' in resource.name.lower() %}development{% else %}general{% endif %}"
            }
        ],
        "priority": 1000,  # Highest priority
        "enabled": True,
        "created_at": datetime.now().isoformat(),
        "created_by": "tag-manager-cli"
    }
    
    # Show preview and save
    _preview_rule(rule_data)
    _save_rule_to_file(rule_data)


def _preview_rule(rule_data):
    """Preview a rule before saving."""
    from rich.table import Table
    
    console.print(f"\n[bold]Rule Preview: {rule_data['name']}[/bold]")
    
    # Show basic info
    info_table = Table(show_header=True, header_style="bold magenta")
    info_table.add_column("Property", style="cyan")
    info_table.add_column("Value", style="white")
    
    info_table.add_row("Name", rule_data["name"])
    info_table.add_row("Description", rule_data["description"]) 
    info_table.add_row("Priority", str(rule_data["priority"]))
    info_table.add_row("Resource Types", f"{len(rule_data['resource_types'])} types")
    info_table.add_row("Conditions", str(len(rule_data.get("conditions", []))))
    
    console.print(info_table)
    
    # Show tags that will be applied
    if rule_data.get("tag_templates"):
        console.print("\n[bold]Tags that will be applied:[/bold]")
        tag_table = Table(show_header=True, header_style="bold green")
        tag_table.add_column("Tag Key", style="cyan")
        tag_table.add_column("Value Template", style="white")
        
        for tag in rule_data["tag_templates"]:
            tag_table.add_row(tag["key"], tag["value"])
        
        console.print(tag_table)


def _save_rule_to_file(rule_data):
    """Save rule to the custom rules file."""
    import json
    from pathlib import Path
    
    default_path = "config/custom_tagging_rules.json"
    file_path = default_path
    
    try:
        # Ensure directory exists
        Path(file_path).parent.mkdir(parents=True, exist_ok=True)
        
        # Load existing rules
        existing_rules = []
        if Path(file_path).exists():
            try:
                with open(file_path, 'r') as f:
                    existing_rules = json.load(f)
            except:
                existing_rules = []
        
        # Add new rule
        existing_rules.append(rule_data)
        
        # Save updated rules
        with open(file_path, 'w') as f:
            json.dump(existing_rules, f, indent=2, default=str)
        
        console.print(f"\n[green]✅ Rule saved to {file_path}[/green]")
        console.print(f"[dim]Load it with: tag-manager tags rules load {file_path}[/dim]")
        console.print(f"[dim]Test it with: tag-manager tags rules enforce --dry-run[/dim]")
        
    except Exception as e:
        console.print(f"[red]Error saving rule: {e}[/red]")


def _enforce_rules(auto_approve: bool, dry_run: bool):
    """Enforce tag rules with configurable approval workflow."""
    from rich.prompt import Confirm
    from rich.panel import Panel
    from rich.table import Table
    import json
    from pathlib import Path
    from datetime import datetime, timezone
    
    console.print("[bold blue]Tag Rules Enforcement[/bold blue]")
    
    if dry_run:
        console.print("[dim]DRY RUN MODE: No changes will be applied[/dim]")
    elif auto_approve:
        console.print("[yellow]AUTO-APPROVE MODE: Rules will be applied automatically[/yellow]")
    else:
        console.print("[dim]MANUAL APPROVAL MODE: You'll review each enforcement action[/dim]")
    
    console.print()
    
    try:
        # Load available rules
        rules_files = [
            "config/sample_tagging_rules.json",
            "config/advanced_tagging_rules.json", 
            "config/custom_tagging_rules.json"
        ]
        
        all_rules = []
        for rules_file in rules_files:
            if Path(rules_file).exists():
                try:
                    with open(rules_file, 'r') as f:
                        rules = json.load(f)
                        for rule in rules:
                            rule['source_file'] = rules_file
                        all_rules.extend(rules)
                except Exception as e:
                    console.print(f"[yellow]Warning: Could not load {rules_file}: {e}[/yellow]")
        
        if not all_rules:
            console.print("[red]No tag rules found. Create rules first with: tag-manager tags rules create[/red]")
            return
        
        # Filter enabled rules
        enabled_rules = [rule for rule in all_rules if rule.get('enabled', True)]
        console.print(f"Found [cyan]{len(enabled_rules)}[/cyan] enabled rules")
        
        if not enabled_rules:
            console.print("[yellow]No enabled rules found. Enable rules with: tag-manager tags rules enable <rule-name>[/yellow]")
            return
        
        # Get resources to process
        with get_db_session() as session:
            resources = session.query(Resource).limit(50).all()  # Process in batches
            
            if not resources:
                console.print("[yellow]No resources found in database[/yellow]")
                return
            
            console.print(f"Processing [cyan]{len(resources)}[/cyan] resources\n")
            
            enforcement_actions = []
            
            # Process each resource against each rule
            for resource in resources:
                for rule in enabled_rules:
                    action = _evaluate_rule_for_resource(resource, rule, session)
                    if action:
                        enforcement_actions.append(action)
            
            if not enforcement_actions:
                console.print("[green]All resources are already compliant with active rules![/green]")
                return
            
            console.print(f"Found [yellow]{len(enforcement_actions)}[/yellow] enforcement actions needed\n")
            
            # Group actions by priority/type for better presentation
            high_priority_actions = [a for a in enforcement_actions if a['priority'] == 'high']
            medium_priority_actions = [a for a in enforcement_actions if a['priority'] == 'medium']
            low_priority_actions = [a for a in enforcement_actions if a['priority'] == 'low']
            
            all_priority_groups = [
                ("High Priority", high_priority_actions, "red"),
                ("Medium Priority", medium_priority_actions, "yellow"), 
                ("Low Priority", low_priority_actions, "green")
            ]
            
            applied_count = 0
            skipped_count = 0
            
            for priority_name, actions, color in all_priority_groups:
                if not actions:
                    continue
                
                console.print(f"[bold {color}]{priority_name} Actions ({len(actions)})[/bold {color}]")
                
                for i, action in enumerate(actions, 1):
                    resource = action['resource']
                    rule = action['rule']
                    tags_to_apply = action['tags']
                    
                    # Display action details
                    panel_content = f"""
[bold cyan]{resource['service_name'].upper()}[/bold cyan] | [white]{resource['resource_id']}[/white] | [yellow]{resource['region']}[/yellow]

[bold]Rule:[/bold] {rule['name']}
[dim]Description: {rule['description']}[/dim]

[bold]Tags to Apply:[/bold]
"""
                    
                    for tag_key, tag_value in tags_to_apply.items():
                        panel_content += f"  [cyan]{tag_key}[/cyan] = [white]{tag_value}[/white]\n"
                    
                    # Show enforcement reasoning if available
                    if 'enforcement_reasons' in action and action['enforcement_reasons']:
                        panel_content += f"\n[bold yellow]Why apply these tags:[/bold yellow]\n"
                        for reason in action['enforcement_reasons']:
                            panel_content += f"  [dim]- {reason}[/dim]\n"
                    
                    if dry_run:
                        panel_content += f"\n[dim]DRY RUN: No changes would be applied[/dim]"
                    
                    console.print(Panel(
                        panel_content,
                        title=f"{priority_name} Action {i}/{len(actions)}",
                        border_style=color
                    ))
                    
                    # Approval workflow
                    should_apply = False
                    
                    if dry_run:
                        should_apply = False  # Never apply in dry run
                    elif auto_approve:
                        should_apply = True
                        console.print("[green]Auto-approved[/green]")
                    else:
                        # Manual approval
                        try:
                            should_apply = Confirm.ask("Apply this enforcement action?", default=True)
                        except EOFError:
                            console.print("[yellow]EOF detected - skipping remaining actions[/yellow]")
                            break
                    
                    if should_apply:
                        try:
                            # Apply tags via AWS API
                            success = _apply_enforcement_tags(resource, tags_to_apply)
                            if success:
                                console.print("[green]Applied successfully[/green]")
                                applied_count += 1
                            else:
                                console.print("[red]Failed to apply[/red]")
                                skipped_count += 1
                        except Exception as e:
                            console.print(f"[red]Error applying tags: {e}[/red]")
                            skipped_count += 1
                    else:
                        console.print("[yellow]Skipped[/yellow]")
                        skipped_count += 1
                    
                    console.print()  # Add spacing
            
            # Summary
            console.print("[bold]Enforcement Summary[/bold]")
            summary_table = Table(show_header=True, header_style="bold magenta")
            summary_table.add_column("Metric", style="cyan")
            summary_table.add_column("Count", style="white", justify="right")
            
            summary_table.add_row("Total Actions", str(len(enforcement_actions)))
            summary_table.add_row("Applied", str(applied_count))
            summary_table.add_row("Skipped", str(skipped_count))
            summary_table.add_row("Success Rate", f"{(applied_count / max(len(enforcement_actions), 1) * 100):.1f}%")
            
            console.print(summary_table)
            
    except Exception as e:
        console.print(f"[red]Error during rule enforcement: {e}[/red]")


def _evaluate_rule_for_resource(resource, rule, session) -> Optional[Dict]:
    """Evaluate if a rule should be applied to a resource with intelligent enforcement logic."""
    from datetime import datetime, timezone
    
    # Check if resource type matches
    if resource.resource_type and resource.resource_type.startswith('AWS::'):
        resource_aws_type = resource.resource_type
    else:
        resource_aws_type = f"AWS::{resource.service_name.upper()}::{resource.resource_type or 'Resource'}"
    if resource_aws_type not in rule.get('resource_types', []):
        return None
    
    # Check conditions
    for condition in rule.get('conditions', []):
        if not _check_condition(resource, condition):
            return None
    
    # Generate tags from templates
    tags_to_apply = {}
    current_tags = resource.current_tags or {}
    rule_priority = rule.get('priority', 100)
    
    for template in rule.get('tag_templates', []):
        tag_key = template['key']
        tag_value = _render_tag_template(template['value'], resource)
        
        # Skip if template rendering failed or produced empty value
        if not tag_value or tag_value.strip() == '':
            continue
            
        # Enhanced enforcement logic - should we apply this tag?
        should_apply, reason = _should_apply_tag(tag_key, tag_value, current_tags, rule_priority, resource)
        
        if should_apply:
            tags_to_apply[tag_key] = tag_value
    
    if not tags_to_apply:
        return None
    
    # Enhanced priority calculation based on tag importance and resource state
    priority = _calculate_enforcement_priority(current_tags, tags_to_apply, resource, rule)
    
    return {
        'resource': {
            'id': resource.id,
            'resource_id': resource.resource_id,
            'service_name': resource.service_name,
            'region': resource.region,
            'resource_arn': resource.resource_arn
        },
        'rule': rule,
        'tags': tags_to_apply,
        'priority': priority,
        'enforcement_reasons': _get_enforcement_reasons(current_tags, tags_to_apply)
    }


def _should_apply_tag(tag_key: str, new_value: str, current_tags: Dict, rule_priority: int, resource) -> tuple[bool, str]:
    """Determine if a tag should be applied based on intelligent enforcement rules."""
    
    # Core governance tags that should always be enforced if missing
    critical_tags = {'Environment', 'Owner', 'Project', 'CostCenter'}
    
    # Tag doesn't exist - safe to apply
    if tag_key not in current_tags:
        return True, "missing"
    
    current_value = current_tags[tag_key]
    
    # Same value - no need to apply
    if current_value == new_value:
        return False, "same_value"
    
    # Check if current value is "low quality" and new value is better
    if _is_low_quality_tag_value(current_value):
        if not _is_low_quality_tag_value(new_value):
            return True, "quality_improvement"
    
    # For critical governance tags, allow high-priority rules to override
    if tag_key in critical_tags:
        if rule_priority >= 200:  # High priority rules
            # Only override if current value looks auto-generated or generic
            if _looks_auto_generated(current_value) and not _looks_auto_generated(new_value):
                return True, "governance_override"
    
    # Conservative approach: don't override meaningful existing tags
    return False, "preserve_existing"


def _is_low_quality_tag_value(value: str) -> bool:
    """Check if a tag value appears to be low quality or meaningless."""
    if not value:
        return True
        
    value_lower = value.lower().strip()
    
    # Common low-quality patterns
    low_quality_patterns = {
        'unknown', 'none', 'null', 'undefined', 'n/a', 'na', 'temp', 'temporary', 'test',
        'default', 'auto', 'generated', 'untitled', 'unnamed', 'empty', 'todo', 'fixme'
    }
    
    # Check for exact matches
    if value_lower in low_quality_patterns:
        return True
        
    # Check for very short, non-descriptive values
    if len(value_lower) <= 2 and value_lower not in {'qa', 'ui', 'db', 'os'}:
        return True
        
    # Check for placeholder patterns like "tag1", "value123", etc.
    import re
    if re.match(r'^(tag|value|item)\d*$', value_lower):
        return True
        
    return False


def _looks_auto_generated(value: str) -> bool:
    """Check if a value looks like it was auto-generated rather than manually set."""
    if not value:
        return True
        
    value_lower = value.lower()
    
    # Auto-generated patterns
    auto_patterns = {
        'auto-generated', 'system-generated', 'tag-manager', 'automated', 'auto-tagged',
        'cli-generated', 'default-value'
    }
    
    return any(pattern in value_lower for pattern in auto_patterns)


def _calculate_enforcement_priority(current_tags: Dict, tags_to_apply: Dict, resource, rule: Dict) -> str:
    """Calculate enforcement priority based on resource state and tags being applied."""
    critical_tags = {'Environment', 'Owner', 'Project', 'CostCenter'}
    
    # Count critical tags being applied
    critical_being_applied = sum(1 for tag in tags_to_apply.keys() if tag in critical_tags)
    
    # High priority: Critical governance tags missing or multiple important tags
    if critical_being_applied >= 2 or (not current_tags and len(tags_to_apply) >= 3):
        return 'high'
    
    # Medium priority: One critical tag or resource partially tagged
    if critical_being_applied == 1 or (current_tags and len(tags_to_apply) >= 2):
        return 'medium'
    
    # Low priority: Non-critical tags or minor additions
    return 'low'


def _get_enforcement_reasons(current_tags: Dict, tags_to_apply: Dict) -> List[str]:
    """Get human-readable reasons for why tags are being applied."""
    reasons = []
    critical_tags = {'Environment', 'Owner', 'Project', 'CostCenter'}
    
    for tag_key, tag_value in tags_to_apply.items():
        if tag_key not in current_tags:
            if tag_key in critical_tags:
                reasons.append(f"Missing critical governance tag: {tag_key}")
            else:
                reasons.append(f"Adding missing tag: {tag_key}")
        else:
            current_val = current_tags[tag_key]
            if _is_low_quality_tag_value(current_val):
                reasons.append(f"Improving low-quality tag: {tag_key} ('{current_val}' -> '{tag_value}')")
            else:
                reasons.append(f"Updating existing tag: {tag_key} ('{current_val}' -> '{tag_value}')")
    
    return reasons


def _check_condition(resource, condition) -> bool:
    """Check if a resource meets a condition."""
    field = condition['field']
    operator = condition['operator']
    expected_value = condition.get('value', '')
    
    # Get field value from resource
    if field == 'resource.name':
        actual_value = resource.resource_id  # Using resource_id as name
    elif field == 'resource.region':
        actual_value = resource.region
    elif field == 'resource.created_at':
        actual_value = resource.created_at
    elif field == 'resource.service_name':
        actual_value = resource.service_name
    elif field.startswith('current_tags.'):
        # Handle tag-based conditions
        tag_key = field.split('.', 1)[1]  # Extract tag key after 'current_tags.'
        current_tags = resource.current_tags or {}
        actual_value = current_tags.get(tag_key)
    else:
        return False  # Unknown field
    
    # Apply operator
    if operator == 'exists':
        return actual_value is not None
    elif operator == 'not_exists':
        return actual_value is None
    elif operator == 'equals':
        return str(actual_value) == str(expected_value)
    elif operator == 'contains':
        return str(expected_value).lower() in str(actual_value).lower()
    elif operator == 'startswith':
        return str(actual_value).lower().startswith(str(expected_value).lower())
    
    return False


def _render_tag_template(template: str, resource) -> str:
    """Render a Jinja2 tag template with resource data."""
    from datetime import datetime
    
    # Enhanced template rendering with better Jinja2 support
    result = template
    
    # If template contains Jinja2 syntax, provide intelligent defaults
    if '{{' in template or '{%' in template:
        # For creator-related templates  
        if 'principal.user_name' in template:
            return 'unknown'
        elif 'principal.type' in template:
            return 'unknown'
        elif 'time' in template and '{{' in template:
            return datetime.now().strftime('%H:%M:%S')
        elif 'resource.created_at.strftime' in template:
            return resource.created_at.strftime('%Y-%m-%d') if resource.created_at else datetime.now().strftime('%Y-%m-%d')
        elif template == 'true' or 'AutoTagged' in template:
            return 'true'
        # For environment classification
        elif any(env in template.lower() for env in ['prod', 'dev', 'test', 'stage']) and 'resource.name.lower()' in template:
            name_lower = resource.resource_id.lower()
            if 'prod' in name_lower:
                return 'Production'
            elif any(term in name_lower for term in ['staging', 'stage']):
                return 'Staging'
            elif 'dev' in name_lower:
                return 'Development'
            elif 'test' in name_lower:
                return 'Testing'
            else:
                return 'Unknown'
        # For quarter calculations
        elif 'now.month' in template or 'Quarter' in template:
            quarter = ((datetime.now().month - 1) // 3) + 1
            return f'Q{quarter}-{datetime.now().year}'
        # For static values
        elif 'tag-manager-cli' in template:
            return 'tag-manager-cli'
        else:
            return 'auto-generated'
    
    # Replace simple placeholders for non-Jinja2 templates
    now = datetime.now()
    if resource.resource_id:
        result = result.replace('{{ resource.name }}', resource.resource_id)
    if resource.region:
        result = result.replace('{{ resource.region }}', resource.region)
    if resource.service_name:
        result = result.replace('{{ resource.service_name }}', resource.service_name)
    
    result = result.replace('{{ date }}', now.strftime('%Y-%m-%d'))
    result = result.replace('{{ datetime }}', now.isoformat())
    
    return result


def _get_client_for_resource(service_name: str, resource_info: Dict):
    """Get a boto3 client for the correct account, assuming a role if needed.

    Uses a module-level cache to avoid repeated STS assume-role calls
    for the same account within a session.
    """
    from ..utils.aws_auth import aws_auth

    account_id = resource_info.get('account_id', '')
    region = resource_info.get('region') or None

    # Determine current account
    try:
        current_account = aws_auth.get_caller_identity()['Account']
    except Exception:
        current_account = None

    base_session = None
    base_account = None
    try:
        base_session = aws_auth.get_base_session()
        base_account = base_session.client("sts").get_caller_identity()["Account"]
    except Exception:
        base_session = None
        base_account = None

    if account_id and account_id == base_account and base_session is not None:
        kwargs = {}
        if region:
            kwargs["region_name"] = region
        return base_session.client(service_name, **kwargs)

    # Same account or unknown -> use default session
    if not account_id or account_id == current_account:
        return aws_auth.get_client(service_name, region=region)

    # Cross-account: assume role (with simple caching)
    cache_key = account_id
    if not hasattr(_get_client_for_resource, '_session_cache'):
        _get_client_for_resource._session_cache = {}

    session = _get_client_for_resource._session_cache.get(cache_key)
    if session is None:
        role_arn = f"arn:aws:iam::{account_id}:role/BlueArchRole"
        external_id = aws_auth.get_cross_account_external_id()
        session = aws_auth.assume_role(
            role_arn=role_arn,
            external_id=external_id,
            session_name=f"tag-manager-tags-{account_id}",
        )
        _get_client_for_resource._session_cache[cache_key] = session

    kwargs = {}
    if region:
        kwargs['region_name'] = region
    return session.client(service_name, **kwargs)


def _apply_enforcement_tags(resource_info: Dict, tags: Dict) -> bool:
    """Apply tags to a resource via AWS API.

    Automatically handles cross-account resources by assuming the
    BlueArchRole in the target account when needed.
    """
    try:
        # Get the appropriate AWS client (cross-account aware)
        service_name = resource_info['service_name'].lower()
        resource_arn = resource_info['resource_arn']

        if service_name == 'ec2':
            client = _get_client_for_resource('ec2', resource_info)
            resource_id = resource_info['resource_id']

            tag_list = [{'Key': k, 'Value': str(v)} for k, v in tags.items()]
            client.create_tags(Resources=[resource_id], Tags=tag_list)

        elif service_name == 's3':
            client = _get_client_for_resource('s3', resource_info)
            bucket_name = resource_info['resource_id']

            # Get existing tags
            try:
                response = client.get_bucket_tagging(Bucket=bucket_name)
                existing_tags = {tag['Key']: tag['Value'] for tag in response.get('TagSet', [])}
            except Exception:
                existing_tags = {}

            existing_tags.update(tags)
            tag_set = [{'Key': k, 'Value': str(v)} for k, v in existing_tags.items()]
            client.put_bucket_tagging(
                Bucket=bucket_name,
                Tagging={'TagSet': tag_set}
            )

        elif service_name == 'lambda':
            client = _get_client_for_resource('lambda', resource_info)

            client.tag_resource(
                Resource=resource_arn,
                Tags={k: str(v) for k, v in tags.items()}
            )

        elif service_name == 'dynamodb':
            client = _get_client_for_resource('dynamodb', resource_info)
            client.tag_resource(
                ResourceArn=resource_arn,
                Tags=[{'Key': k, 'Value': str(v)} for k, v in tags.items()]
            )

        elif service_name == 'rds':
            client = _get_client_for_resource('rds', resource_info)
            client.add_tags_to_resource(
                ResourceName=resource_arn,
                Tags=[{'Key': k, 'Value': str(v)} for k, v in tags.items()]
            )

        else:
            # Generic resource tagging via Resource Groups Tagging API
            client = _get_client_for_resource('resourcegroupstaggingapi', resource_info)
            resp = client.tag_resources(
                ResourceARNList=[resource_arn],
                Tags={k: str(v) for k, v in tags.items()}
            )
            failed = resp.get('FailedResourcesMap', {})
            if failed:
                err = next(iter(failed.values()), {})
                msg = err.get('ErrorMessage', 'unknown error')
                raise RuntimeError(f"tag_resources failed: {msg}")

        return True

    except Exception as e:
        console.print(f"[red]Error applying tags to {resource_info['resource_id']}: {e}[/red]")
        return False


def _apply_tags_to_aws_resource(
    resource_arn: str,
    tags: Dict,
    service_name: str,
    account_id: str | None = None,
    region: str | None = None,
    resource_id: str | None = None,
) -> bool:
    """Apply tags to AWS resource using Resource ARN and service name."""
    try:
        # Parse ARN to extract components
        arn_parts = resource_arn.split(':')
        if len(arn_parts) < 6:
            console.print(f"[red]Invalid ARN format: {resource_arn}[/red]")
            return False
        
        parsed_region = arn_parts[3]
        parsed_account_id = arn_parts[4]
        resource_part = arn_parts[5]
        effective_region = region or parsed_region or None
        effective_account_id = account_id or parsed_account_id or ""
        
        # Extract resource ID based on service
        if not resource_id:
            if service_name.lower() == 'ec2':
                resource_id = resource_part.split('/')[1] if '/' in resource_part else resource_part
            elif service_name.lower() == 's3':
                resource_id = resource_part
            elif service_name.lower() == 'lambda':
                resource_id = resource_part.split(':')[1] if ':' in resource_part else resource_part
            else:
                resource_id = resource_part
        
        # Create resource info dict for existing function
        resource_info = {
            'resource_arn': resource_arn,
            'service_name': service_name,
            'resource_id': resource_id,
            'region': effective_region,
            'account_id': effective_account_id,
        }
        
        return _apply_enforcement_tags(resource_info, tags)
        
    except Exception as e:
        console.print(f"[red]Error parsing ARN {resource_arn}: {e}[/red]")
        return False


def _enforce_rules_via_workers(auto_approve: bool, dry_run: bool):
    """Enforce tag rules using Celery workers with approval workflow."""
    from rich.prompt import Confirm
    from rich.panel import Panel
    from rich.table import Table
    from rich.progress import Progress, SpinnerColumn, TextColumn
    import time
    
    console.print("[bold blue]Worker-Based Tag Rules Enforcement[/bold blue]")
    
    # Check if workers are available - handle packaged binary compatibility
    # Container-free version: Workers are no longer used
    console.print("[yellow]Background workers have been replaced with synchronous execution[/yellow]")
    console.print("[info]Rules will be applied directly without background processing[/info]")

    # Direct enforcement is now the default
    console.print("\n[cyan]Use direct enforcement:[/cyan]")
    console.print("[cyan]tag-manager tags rules enforce[/cyan]")
    return
    
    if dry_run:
        console.print("[dim]DRY RUN MODE: Tasks will be queued but not executed[/dim]")
    elif auto_approve:
        console.print("[yellow]AUTO-APPROVE MODE: All enforcement tasks will be queued automatically[/yellow]")
    else:
        console.print("[dim]MANUAL APPROVAL MODE: You'll review before queueing tasks[/dim]")
    
    console.print()
    
    try:
        # Get resources to process
        with get_db_session() as session:
            resources = session.query(Resource).limit(100).all()
            
            if not resources:
                console.print("[yellow]No resources found in database[/yellow]")
                return
            
            console.print(f"Preparing enforcement tasks for [cyan]{len(resources)}[/cyan] resources")
            
            # Group resources by service for better batching
            resources_by_service = {}
            for resource in resources:
                service = resource.service_name
                if service not in resources_by_service:
                    resources_by_service[service] = []
                resources_by_service[service].append(resource)
            
            console.print(f"Services: {', '.join(resources_by_service.keys())}")
            
            tasks_to_queue = []
            
            # Prepare enforcement tasks
            for service, service_resources in resources_by_service.items():
                console.print(f"\n[bold cyan]{service.upper()}[/bold cyan] ({len(service_resources)} resources)")
                
                for resource in service_resources:
                    # Create task info
                    task_info = {
                        'resource_arn': resource.resource_arn,
                        'resource_id': resource.resource_id,
                        'service': resource.service_name,
                        'region': resource.region,
                        'current_tags': len(resource.current_tags or {})
                    }
                    
                    tasks_to_queue.append(task_info)
            
            if not tasks_to_queue:
                console.print("[green]No enforcement tasks needed[/green]")
                return
            
            # Show task summary
            console.print(f"\n[bold]Task Summary[/bold]")
            task_table = Table(show_header=True, header_style="bold magenta")
            task_table.add_column("Service", style="cyan")
            task_table.add_column("Resources", style="white", justify="right")
            task_table.add_column("Sample Resource", style="dim")
            
            for service, service_resources in resources_by_service.items():
                sample_resource = service_resources[0].resource_id[:30] + "..." if len(service_resources[0].resource_id) > 30 else service_resources[0].resource_id
                task_table.add_row(
                    service.upper(),
                    str(len(service_resources)),
                    sample_resource
                )
            
            console.print(task_table)
            
            # Approval workflow
            should_proceed = False
            
            if auto_approve:
                should_proceed = True
                console.print("[green]Auto-approved - queuing all tasks[/green]")
            else:
                try:
                    should_proceed = Confirm.ask(f"Queue {len(tasks_to_queue)} enforcement tasks for background processing?", default=True)
                except EOFError:
                    console.print("[yellow]EOF detected - aborting[/yellow]")
                    return
            
            if should_proceed and not dry_run:
                console.print("[bold]Queueing Enforcement Tasks...[/bold]")
                
                queued_tasks = []
                failed_tasks = []
                
                with Progress(
                    SpinnerColumn(),
                    TextColumn("[progress.description]{task.description}"),
                    console=console,
                    transient=True
                ) as progress:
                    queue_task = progress.add_task("Queueing tasks...", total=len(tasks_to_queue))
                    
                    for i, task_info in enumerate(tasks_to_queue):
                        try:
                            # Import the worker task
                            from ..workers.tagging_tasks import apply_automated_tags
                            
                            # Queue the task
                            result = apply_automated_tags.delay(
                                resource_arn=task_info['resource_arn'],
                                principal_info={'user_name': 'tag-manager-cli'},
                                event_metadata={'source': 'rules-enforcement', 'auto_approve': auto_approve}
                            )
                            
                            queued_tasks.append({
                                'task_id': result.id,
                                'resource_arn': task_info['resource_arn'],
                                'resource_id': task_info['resource_id'],
                                'service': task_info['service']
                            })
                            
                            progress.update(queue_task, advance=1, 
                                          description=f"Queued {i+1}/{len(tasks_to_queue)} tasks...")
                            
                        except Exception as e:
                            failed_tasks.append({
                                'resource_arn': task_info['resource_arn'],
                                'error': str(e)
                            })
                
                # Show results
                console.print(f"\n[bold green]Queuing Complete[/bold green]")
                
                results_table = Table(show_header=True, header_style="bold magenta")
                results_table.add_column("Status", style="cyan")
                results_table.add_column("Count", style="white", justify="right")
                results_table.add_column("Details", style="dim")
                
                results_table.add_row("Queued", str(len(queued_tasks)), "Tasks sent to workers")
                results_table.add_row("Failed", str(len(failed_tasks)), "Could not queue")
                
                console.print(results_table)
                
                if queued_tasks:
                    console.print(f"\n[bold]Monitoring Tasks[/bold]")
                    console.print("[dim]You can monitor task progress with:[/dim]")
                    console.print("[cyan]tag-manager workers status[/cyan]")
                    console.print("[cyan]tag-manager tags report compliance[/cyan]")
                    
                    # Optionally wait for a few tasks to complete
                    if len(queued_tasks) <= 5 and Confirm.ask("Wait for tasks to complete?", default=False):
                        _monitor_enforcement_tasks(queued_tasks[:5])
                
                if failed_tasks:
                    console.print(f"\n[red]Failed to queue {len(failed_tasks)} tasks:[/red]")
                    for failed in failed_tasks[:5]:  # Show first 5 failures
                        console.print(f"  [dim]{failed['resource_arn']}: {failed['error']}[/dim]")
            
            elif dry_run:
                console.print(f"[dim]DRY RUN: Would queue {len(tasks_to_queue)} enforcement tasks[/dim]")
                console.print("[dim]Use --auto-approve to skip confirmation prompts[/dim]")
            else:
                console.print("[yellow]Enforcement cancelled[/yellow]")
    
    except Exception as e:
        console.print(f"[red]Error during worker enforcement: {e}[/red]")


def _monitor_enforcement_tasks(queued_tasks: List[Dict], timeout: int = 60):
    """Monitor enforcement tasks and show progress."""
    from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TaskProgressColumn
    import time
    
    try:
        from ..workers.celery_app import celery_app
        
        console.print(f"[dim]Monitoring {len(queued_tasks)} tasks (timeout: {timeout}s)...[/dim]")
        
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TaskProgressColumn(),
            console=console
        ) as progress:
            
            monitor_task = progress.add_task("Monitoring tasks...", total=len(queued_tasks))
            completed_count = 0
            start_time = time.time()
            
            while completed_count < len(queued_tasks) and (time.time() - start_time) < timeout:
                current_completed = 0
                
                for task_info in queued_tasks:
                    result = celery_app.AsyncResult(task_info['task_id'])
                    if result.ready():
                        current_completed += 1
                
                if current_completed > completed_count:
                    completed_count = current_completed
                    progress.update(monitor_task, 
                                  completed=completed_count,
                                  description=f"Completed {completed_count}/{len(queued_tasks)} tasks")
                
                time.sleep(2)  # Check every 2 seconds
            
            if completed_count == len(queued_tasks):
                console.print("[green]All monitored tasks completed![/green]")
            else:
                console.print(f"[yellow]Monitoring timeout - {completed_count}/{len(queued_tasks)} completed[/yellow]")
    
    except Exception as e:
        console.print(f"[yellow]Could not monitor tasks: {e}[/yellow]")
        console.print("[dim]Check task status with: tag-manager workers status[/dim]")

# === EXECUTION HISTORY AND ROLLBACK COMMANDS ===

@tags_app.command("history")
def show_execution_history(
    limit: int = typer.Option(10, "--limit", "-l", help="Number of executions to show"),
    execution_type: Optional[str] = typer.Option(None, "--type", "-t", help="Filter by type: manual, automated, bulk, setup, rollback"),
    status: Optional[str] = typer.Option(None, "--status", "-s", help="Filter by status: completed, failed, in_progress, rolled_back"),
    user: Optional[str] = typer.Option(None, "--user", "-u", help="Filter by user who initiated"),
    show_rollbacks: bool = typer.Option(False, "--show-rollbacks", "-r", help="Include rollback executions"),
    details: Optional[int] = typer.Option(None, "--details", "-d", help="Show details for specific execution ID")
):
    """
    View history of tag operations with execution tracking.
    
    Shows a history of all tagging executions, including:
    - Manual tag applications
    - Automated rule enforcement
    - Bulk tagging operations
    - Setup operations
    - Rollback operations (if enabled)
    
    Use --details <execution-id> to see detailed information about a specific execution.
    """
    import os
    
    try:
        # Handle details view first
        if details:
            execution_details = get_execution_details(details)
            
            if not execution_details:
                console.print(f"[red]ERROR[/red] Execution not found: {details}")
                return
            
            # Display execution details
            console.print(f"\n[bold cyan][EXECUTION] Execution Details[/bold cyan]")
            console.print(f"[dim]Execution ID: {execution_details['id']}[/dim]\n")
            
            # Basic information
            info_table = Table(show_header=False, box=None)
            info_table.add_column("Field", style="white", width=15)
            info_table.add_column("Value", style="cyan")
            
            info_table.add_row("Type", execution_details['execution_type'])
            info_table.add_row("Description", execution_details['description'] or "N/A")
            info_table.add_row("Status", f"[{'green' if execution_details['status'] == 'completed' else 'yellow' if 'partial' in execution_details['status'] else 'red'}]{execution_details['status']}[/]")
            info_table.add_row("Initiated By", execution_details['initiated_by'])
            info_table.add_row("Started At", execution_details['started_at'])
            info_table.add_row("Completed At", execution_details['completed_at'] or "In Progress")
            info_table.add_row("Total Resources", str(execution_details['total_resources']))
            info_table.add_row("Successful", str(execution_details['successful_operations']))
            info_table.add_row("Failed", str(execution_details['failed_operations']))
            
            if execution_details['parent_execution_id']:
                info_table.add_row("Parent Execution", execution_details['parent_execution_id'])
            
            if execution_details['rolled_back_at']:
                info_table.add_row("Rolled Back At", execution_details['rolled_back_at'])
                info_table.add_row("Rolled Back By", execution_details['rolled_back_by'])
            
            console.print(info_table)
            
            # Resources affected
            if execution_details.get('resources_affected'):
                console.print(f"\n[bold yellow][RESOURCES] Resources Affected ({len(execution_details['resources_affected'])})[/bold yellow]")
                
                resource_table = Table(show_header=True, header_style="bold magenta")
                resource_table.add_column("Resource ARN", style="white", width=60)
                resource_table.add_column("Operations", style="cyan", width=16)
                resource_table.add_column("Success", style="green", width=9)
                resource_table.add_column("Failed", style="red", width=9)
                
                for resource in execution_details['resources_affected'][:20]:  # Limit to 20 for readability
                    ops = resource['operations']
                    success_count = sum(1 for op in ops if op['success'])
                    failed_count = sum(1 for op in ops if not op['success'])
                    
                    # Truncate long ARNs
                    arn = resource['resource_arn']
                    if len(arn) > 57:
                        arn = arn[:54] + "..."
                    
                    resource_table.add_row(
                        arn,
                        str(len(ops)),
                        str(success_count),
                        str(failed_count)
                    )
                
                console.print(resource_table)
                
                if len(execution_details['resources_affected']) > 20:
                    console.print(f"[dim]... and {len(execution_details['resources_affected']) - 20} more resources[/dim]")
            
            # Audit logs summary
            if execution_details.get('audit_logs'):
                console.print(f"\n[bold magenta][AUDIT] Operation Summary[/bold magenta]")
                
                # Group operations by type
                operation_counts = {}
                for log in execution_details['audit_logs']:
                    op = log['operation']
                    if op not in operation_counts:
                        operation_counts[op] = {'success': 0, 'failed': 0}
                    
                    if log['success']:
                        operation_counts[op]['success'] += 1
                    else:
                        operation_counts[op]['failed'] += 1
                
                op_table = Table(show_header=True, header_style="bold cyan")
                op_table.add_column("Operation", style="white", width=25)
                op_table.add_column("Successful", style="green", width=16)
                op_table.add_column("Failed", style="red", width=16)
                
                for op, counts in operation_counts.items():
                    op_table.add_row(op, str(counts['success']), str(counts['failed']))
                
                console.print(op_table)
            
            # Rollback status
            if execution_details['rollback_enabled']:
                console.print(f"\n[bold yellow][ROLLBACK] Rollback Information[/bold yellow]")
                
                # Check if can rollback
                with get_db_session() as session:
                    execution = session.query(TaggingExecution).filter_by(id=details).first()
                    if execution:
                        can_rollback, reason = execution.can_rollback()
                        
                        if can_rollback:
                            console.print(f"[green]This execution can be rolled back[/green]")
                            console.print(f"[dim]Use: tag-manager tags rollback {details}[/dim]")
                        else:
                            console.print(f"[yellow]Cannot rollback: {reason}[/yellow]")
            
            return
        
        # Get execution history
        executions = get_execution_history(
            limit=limit,
            execution_type=execution_type,
            status=status,
            initiated_by=user,
            include_rollbacks=show_rollbacks
        )
        
        if not executions:
            console.print("[yellow]No execution history found matching criteria[/yellow]")
            return
        
        # Display execution history table
        console.print(f"\n[bold cyan][HISTORY] Tag Operation History[/bold cyan]")
        console.print(f"[dim]Showing {len(executions)} most recent executions[/dim]\n")
        
        history_table = Table(show_header=True, header_style="bold magenta")
        history_table.add_column("Execution ID", style="white", width=8)
        history_table.add_column("Type", style="cyan", width=8)
        history_table.add_column("Status", style="yellow", width=16)
        history_table.add_column("Resources", style="white", width=9)
        history_table.add_column("Success/Fail", style="green", width=8)
        history_table.add_column("User", style="blue", width=15)
        history_table.add_column("Started", style="dim", width=15)
        
        for execution in executions:
            # Format status with color
            status_color = "green" if execution['status'] == 'completed' else "yellow" if 'partial' in execution['status'] else "red"
            status_text = f"[{status_color}]{execution['status']}[/{status_color}]"
            
            # Format success/fail counts
            success_fail = f"{execution['successful_operations']}/{execution['failed_operations']}"
            
            # Format time
            started = execution['started_at']
            if started:
                try:
                    started_dt = datetime.fromisoformat(started.replace('Z', '+00:00'))
                    started = started_dt.strftime("%Y-%m-%d %H:%M")
                except:
                    started = started[:19]  # Fallback to raw string
            
            history_table.add_row(
                str(execution['id']),  # Truncate ID for readability
                execution['execution_type'],
                status_text,
                str(execution['total_resources']),
                success_fail,
                execution['initiated_by'][:20],  # Truncate long usernames
                started
            )
        
        console.print(history_table)
        
        console.print(f"\n[dim]Use --details <execution-id> to see detailed information about a specific execution[/dim]")
        console.print(f"[dim]Use --show-rollbacks to include rollback operations in the history[/dim]")
        
    except Exception as e:
        console.print(f"[red]ERROR[/red] Failed to retrieve execution history: {e}")
        import traceback
        if os.getenv('TAG_MANAGER_DEBUG'):
            console.print(f"[dim]{traceback.format_exc()}[/dim]")


@tags_app.command("rollback")
def rollback_tag_execution(
    execution_id: int = typer.Argument(..., help="Execution ID to rollback"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Preview what would be rolled back without making changes"),
    validate_only: bool = typer.Option(False, "--validate", help="Only validate if rollback is feasible"),
    force: bool = typer.Option(False, "--force", "-f", help="Skip confirmation prompt"),
    async_mode: bool = typer.Option(False, "--async", help="Run rollback as background task")
):
    """
    Rollback a previous tag execution to restore original tag state.
    
    This command allows you to undo tag changes made by a previous execution.
    It will:
    - Remove tags that were added
    - Restore tags that were modified to their previous values
    - Re-add tags that were removed
    
    Use --dry-run to preview changes before applying them.
    Use --validate to check if rollback is feasible without making changes.
    """
    import os
    
    try:
        # First validate the execution exists and can be rolled back
        execution_details = get_execution_details(execution_id)
        
        if not execution_details:
            console.print(f"[red]ERROR[/red] Execution not found: {execution_id}")
            return
        
        console.print(f"\n[bold cyan][ROLLBACK] Tag Execution Rollback[/bold cyan]")
        console.print(f"[dim]Execution ID: {execution_id}[/dim]\n")
        
        # Display execution summary
        console.print(f"[yellow]Execution Summary:[/yellow]")
        console.print(f"  Type: {execution_details['execution_type']}")
        console.print(f"  Description: {execution_details['description'] or 'N/A'}")
        console.print(f"  Status: {execution_details['status']}")
        console.print(f"  Resources Affected: {execution_details['total_resources']}")
        console.print(f"  Initiated By: {execution_details['initiated_by']}")
        console.print(f"  Executed At: {execution_details['started_at']}")
        
        if execution_details['rolled_back_at']:
            console.print(f"\n[red]WARNING[/red] This execution was already rolled back:")
            console.print(f"  Rolled Back At: {execution_details['rolled_back_at']}")
            console.print(f"  Rolled Back By: {execution_details['rolled_back_by']}")
            return
        
        # Validate rollback feasibility
        if validate_only or not force:
            console.print(f"\n[blue]Validating rollback feasibility...[/blue]")
            
            try:
                # Try to use worker for validation if available
                from ..workers.rollback_tasks import validate_rollback_feasibility as validate_task
                
                if async_mode:
                    result = validate_task.delay(execution_id)
                    console.print(f"[dim]Validation task queued: {result.id}[/dim]")
                    validation_result = result.get(timeout=30)
                else:
                    validation_result = validate_task(execution_id)
                
            except Exception as e:
                # Fallback to direct validation
                with get_db_session() as session:
                    execution = session.query(TaggingExecution).filter_by(id=execution_id).first()
                    if execution:
                        can_rollback, reason = execution.can_rollback()
                        validation_result = {
                            'can_rollback': can_rollback,
                            'reason': reason,
                            'warnings': []
                        }
                    else:
                        validation_result = {
                            'can_rollback': False,
                            'reason': 'Execution not found',
                            'warnings': []
                        }
            
            if not validation_result['can_rollback']:
                console.print(f"[red]Cannot rollback:[/red] {validation_result['reason']}")
                return
            
            console.print(f"[green]Rollback is feasible[/green]")
            
            if validation_result.get('warnings'):
                console.print(f"\n[yellow]Warnings:[/yellow]")
                for warning in validation_result['warnings']:
                    console.print(f"  - {warning}")
            
            if validate_only:
                return
        
        # Confirm rollback
        if not force and not dry_run:
            if not Confirm.ask(f"\nAre you sure you want to rollback execution {execution_id}...?"):
                console.print("[yellow]Rollback cancelled[/yellow]")
                return
        
        # Get current user for audit
        current_user = os.getenv('USER', 'unknown')
        
        # Perform rollback
        console.print(f"\n[blue]{'Simulating' if dry_run else 'Performing'} rollback...[/blue]")
        
        try:
            if async_mode and not dry_run:
                # Queue as background task
                from ..workers.rollback_tasks import rollback_execution as rollback_task
                
                result = rollback_task.delay(execution_id, current_user, dry_run)
                console.print(f"[green]Rollback task queued successfully[/green]")
                console.print(f"[dim]Task ID: {result.id}[/dim]")
                console.print(f"[dim]Check status with: tag-manager workers status[/dim]")
                
            else:
                # Execute synchronously
                from ..workers.rollback_tasks import rollback_execution as rollback_func
                
                rollback_result = rollback_func(execution_id, current_user, dry_run)
                
                # Display results
                console.print(f"\n[bold {'yellow' if dry_run else 'green'}][{'DRY RUN' if dry_run else 'COMPLETE'}] Rollback {'Simulation' if dry_run else 'Complete'}[/bold {'yellow' if dry_run else 'green'}]")
                
                # Summary table
                summary_table = Table(show_header=False, box=None)
                summary_table.add_column("Metric", style="white", width=25)
                summary_table.add_column("Value", style="cyan")
                
                summary_table.add_row("Total Operations", str(rollback_result['total_operations']))
                summary_table.add_row("Successful Rollbacks", str(rollback_result['successful_rollbacks']))
                summary_table.add_row("Failed Rollbacks", str(rollback_result['failed_rollbacks']))
                summary_table.add_row("Skipped Rollbacks", str(rollback_result['skipped_rollbacks']))
                
                if rollback_result.get('rollback_execution_id'):
                    summary_table.add_row("Rollback Execution ID", str(rollback_result['rollback_execution_id']))
                
                console.print(summary_table)
                
                # Show operation details if there were failures
                if rollback_result['failed_rollbacks'] > 0:
                    console.print(f"\n[red]Failed Operations:[/red]")
                    
                    failed_ops = [op for op in rollback_result['operations'] if op['status'] == 'failed']
                    for op in failed_ops[:10]:  # Limit to 10 for readability
                        arn = op['resource_arn']
                        if len(arn) > 60:
                            arn = arn[:57] + "..."
                        console.print(f"  - {arn}")
                        console.print(f"    [dim]{op['message']}[/dim]")
                    
                    if len(failed_ops) > 10:
                        console.print(f"  [dim]... and {len(failed_ops) - 10} more[/dim]")
                
                if dry_run:
                    console.print(f"\n[yellow]This was a dry run. No changes were made.[/yellow]")
                    console.print(f"[dim]Remove --dry-run to perform the actual rollback[/dim]")
                else:
                    console.print(f"\n[green]Rollback completed successfully![/green]")
                    
                    if rollback_result['failed_rollbacks'] > 0:
                        console.print(f"[yellow]Note: Some operations failed. Review the details above.[/yellow]")
        
        except Exception as e:
            console.print(f"[red]ERROR[/red] Rollback failed: {e}")
            import traceback
            if os.getenv('TAG_MANAGER_DEBUG'):
                console.print(f"[dim]{traceback.format_exc()}[/dim]")
    
    except Exception as e:
        console.print(f"[red]ERROR[/red] Failed to process rollback: {e}")
        import traceback
        if os.getenv('TAG_MANAGER_DEBUG'):
            console.print(f"[dim]{traceback.format_exc()}[/dim]")
