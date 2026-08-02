"""Shared resource discovery module for Tag Manager CLI.

This module provides service-specific discovery functions that can be called
from both CLI commands and background tasks. Supports EC2, S3, and Lambda resources.
"""

import json
import boto3
import logging
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional, Tuple
from botocore.exceptions import ClientError
from concurrent.futures import ThreadPoolExecutor, as_completed
from threading import Lock
from rich.console import Console
from rich.progress import Progress, TaskID
from rich.tree import Tree
from rich.live import Live
from rich.text import Text

logger = logging.getLogger(__name__)
from ..utils.aws_auth import aws_auth
from ..utils.cache import cache
from ..utils.core_storage import clear_resources, resource_payload, upsert_by_filter
from ..utils.env_config import settings
from ..services.org_policy_provider import org_policy_provider

console = Console()


def _ec2_arn(region, account_id, resource_type, resource_id):
    """Build an EC2-style ARN."""
    return f"arn:aws:ec2:{region}:{account_id}:{resource_type}/{resource_id}"


def _iam_arn(account_id, resource_type, name):
    """Build an IAM ARN (global service)."""
    return f"arn:aws:iam::{account_id}:{resource_type}/{name}"


def discover_all_resources(
    services: Optional[List[str]] = None,
    regions: Optional[List[str]] = None,
    progress: Optional[Progress] = None,
) -> Dict[str, Any]:
    """Discover resources across all enabled services and regions concurrently.

    Args:
        services: List of services to discover (default: ['ec2', 's3', 'lambda'])
        regions: List of regions to scan (default: US regions)
        progress: Optional Rich progress instance for UI updates

    Returns:
        Dictionary with discovery statistics
    """
    # Default services - now includes all implemented services
    if not services:
        services = ["ec2", "s3", "lambda", "rds", "dynamodb", "ecs", "elb"]

    # Default regions
    if not regions:
        regions = ["us-east-1", "us-east-2", "us-west-1", "us-west-2"]

    summary = {
        "services_scanned": len(services),
        "regions_scanned": len(regions),
        "total_resources_discovered": 0,
        "errors": [],
        "start_time": datetime.utcnow(),
    }

    # Build list of discovery jobs (service, region) tuples
    discovery_jobs = []

    for service in services:
        if service == "s3":
            # S3 is global, only scan once
            discovery_jobs.append(("s3", None))
        elif service in ["ec2", "lambda"]:
            # EC2 and Lambda are regional
            for region in regions:
                discovery_jobs.append((service, region))

    # Use ThreadPoolExecutor for concurrent discovery
    max_workers = min(10, len(discovery_jobs))  # Max 10 concurrent discoveries

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        # Submit all jobs and track with progress tasks
        future_to_job = {}
        task_ids = {}

        for service, region in discovery_jobs:
            # Create progress task for each job
            if progress:
                if service == "s3":
                    task_desc = "[cyan]Discovering S3 buckets..."
                elif service == "ec2":
                    task_desc = f"[cyan]Discovering EC2 resources in {region}..."
                elif service == "lambda":
                    task_desc = f"[cyan]Discovering Lambda functions in {region}..."

                task_id = progress.add_task(task_desc, total=None)
                task_ids[(service, region)] = task_id

            # Submit discovery job to thread pool
            if service == "ec2":
                future = executor.submit(discover_ec2_resources, region)
            elif service == "s3":
                future = executor.submit(discover_s3_resources)
            elif service == "lambda":
                future = executor.submit(discover_lambda_resources, region)

            future_to_job[future] = (service, region)

        # Process completed jobs as they finish
        for future in as_completed(future_to_job):
            service, region = future_to_job[future]

            try:
                result = future.result()
                discovered_count = result.get("discovered_count", 0)
                summary["total_resources_discovered"] += discovered_count
                summary["errors"].extend(result.get("errors", []))
                summary["permission_errors"] = summary.get(
                    "permission_errors", 0
                ) + result.get("permission_errors", 0)

                # Update progress with success message
                if progress and (service, region) in task_ids:
                    task_id = task_ids[(service, region)]

                    if service == "s3":
                        desc = f"[green]OK S3: {discovered_count} buckets"
                    elif service == "ec2":
                        desc = (
                            f"[green]OK EC2 in {region}: {discovered_count} resources"
                        )
                    elif service == "lambda":
                        desc = f"[green]OK Lambda in {region}: {discovered_count} functions"

                    progress.update(task_id, description=desc, completed=True)

            except Exception as e:
                error_msg = f"Error discovering {service}"
                if region:
                    error_msg += f" in {region}"
                error_msg += f": {str(e)}"
                summary["errors"].append(error_msg)

                # Update progress with error
                if progress and (service, region) in task_ids:
                    task_id = task_ids[(service, region)]
                    if service == "s3":
                        desc = f"[red]ERROR S3 discovery failed"
                    elif region:
                        desc = f"[red]ERROR {service.upper()} in {region} failed"
                    progress.update(task_id, description=desc, completed=True)

    summary["end_time"] = datetime.utcnow()
    summary["duration_seconds"] = (
        summary["end_time"] - summary["start_time"]
    ).total_seconds()

    return summary


def _clear_all_resources_single_account():
    """Delete all resources from the database before single-account discovery."""
    try:
        deleted_count = clear_resources()
        logger.info(
            f"Cleared {deleted_count} resources from core storage before discovery"
        )
        return deleted_count
    except Exception as e:
        logger.error(f"Failed to clear resources: {str(e)}")
        return 0


def discover_all_resources_with_tree(
    services: List[str],
    regions: List[str],
    console: Console,
    required_tags: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Discover resources with compact tree-style hierarchical display and compliance checking.

    Shows a compact tree structure with:
    - Account ID at root level
    - Only regions with resources (0 resource regions are collapsed)
    - Service-level summaries
    - Compliance indicators

    Args:
        services: List of services to discover
        regions: List of regions to scan
        console: Rich console for display
        required_tags: Optional list of required tag keys (auto-fetched from org policy if None)

    Returns:
        Dictionary with discovery statistics including compliance data
    """
    from rich.progress import (
        Progress,
        SpinnerColumn,
        TextColumn,
        BarColumn,
        TaskProgressColumn,
    )

    # Get current account ID
    try:
        sts_client = aws_auth.get_client("sts")
        account_id = sts_client.get_caller_identity()["Account"]
    except Exception:
        account_id = "unknown"

    # Clear all resources from database before discovery
    deleted_count = _clear_all_resources_single_account()
    if deleted_count > 0:
        console.print(
            f"[yellow]Cleared {deleted_count} existing resources from database[/yellow]\n"
        )

    # Get required tags for compliance checking
    from_org_policy = False
    policy_warning = None
    if required_tags is None:
        required_tags, from_org_policy, policy_warning = (
            org_policy_provider.get_required_tags(show_warnings=True)
        )

    # Show policy source information
    if from_org_policy:
        console.print(
            f"[green]Checking compliance against AWS Organizations policy[/green]"
        )
        console.print(f"[dim]Required tags: {', '.join(required_tags)}[/dim]\n")
    elif policy_warning:
        console.print(policy_warning)
        console.print()

    # Track compliance stats
    compliance_summary = {
        "total_compliant": 0,
        "total_noncompliant": 0,
        "by_service": {},
        "by_region": {},
        "required_tags": required_tags,
        "from_org_policy": from_org_policy,
    }

    summary = {
        "services_scanned": len(services),
        "regions_scanned": len(regions),
        "total_resources_discovered": 0,
        "errors": [],
        "start_time": datetime.utcnow(),
        "compliance": compliance_summary,
    }

    # Build discovery jobs
    discovery_jobs = []
    for service in services:
        if service == "s3":
            discovery_jobs.append(("s3", None))
        elif service in ["ec2", "lambda", "rds", "dynamodb", "ecs", "elb"]:
            for region in regions:
                discovery_jobs.append((service, region))

    # Store detailed results for building compact tree later
    discovery_results = (
        {}
    )  # {(service, region): {'count': N, 'compliant': N, 'noncompliant': N}}
    update_lock = Lock()

    # Use progress bar during discovery
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TaskProgressColumn(),
        console=console,
        transient=True,
    ) as progress:
        task = progress.add_task(
            f"[cyan]Discovering resources across {len(services)} services...",
            total=len(discovery_jobs),
        )
        max_workers = min(10, len(discovery_jobs))

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_to_job = {}

            # Submit all jobs
            for service, region in discovery_jobs:
                if service == "ec2":
                    future = executor.submit(discover_ec2_resources, region)
                elif service == "s3":
                    future = executor.submit(discover_s3_resources)
                elif service == "lambda":
                    future = executor.submit(discover_lambda_resources, region)
                elif service == "rds":
                    # discover_rds_resources expects a list of regions
                    future = executor.submit(discover_rds_resources, [region])
                elif service == "dynamodb":
                    # discover_dynamodb_resources expects a list of regions
                    future = executor.submit(discover_dynamodb_resources, [region])
                elif service == "ecs":
                    from ..modules.discovery_ecs_elb import discover_ecs_resources

                    future = executor.submit(discover_ecs_resources, region)
                elif service == "elb":
                    from ..modules.discovery_ecs_elb import discover_elb_resources

                    future = executor.submit(discover_elb_resources, region)

                future_to_job[future] = (service, region)

            # Process completions
            for future in as_completed(future_to_job):
                service, region = future_to_job[future]

                try:
                    result = future.result()
                    discovered_count = result.get("discovered_count", 0)

                    with update_lock:
                        summary["total_resources_discovered"] += discovered_count
                        summary["errors"].extend(result.get("errors", []))

                        # Calculate compliance for discovered resources
                        compliant_count = 0
                        noncompliant_count = 0
                        discovered_resources = result.get("discovered_resources", [])

                        for res in discovered_resources:
                            res_tags = (
                                res.get("tags", {}) or res.get("current_tags", {}) or {}
                            )
                            if isinstance(res_tags, str):
                                try:
                                    import json

                                    res_tags = json.loads(res_tags) if res_tags else {}
                                except:
                                    res_tags = {}
                            is_compliant, _ = (
                                org_policy_provider.check_resource_compliance(
                                    res_tags, required_tags, from_org_policy
                                )
                            )
                            if is_compliant:
                                compliant_count += 1
                            else:
                                noncompliant_count += 1

                        # Store results for compact tree
                        discovery_results[(service, region)] = {
                            "count": discovered_count,
                            "compliant": compliant_count,
                            "noncompliant": noncompliant_count,
                        }

                        # Update compliance summary
                        if service not in compliance_summary["by_service"]:
                            compliance_summary["by_service"][service] = {
                                "compliant": 0,
                                "noncompliant": 0,
                                "total": 0,
                                "regions_with_resources": 0,
                            }
                        compliance_summary["by_service"][service][
                            "compliant"
                        ] += compliant_count
                        compliance_summary["by_service"][service][
                            "noncompliant"
                        ] += noncompliant_count
                        compliance_summary["by_service"][service][
                            "total"
                        ] += discovered_count
                        if discovered_count > 0:
                            compliance_summary["by_service"][service][
                                "regions_with_resources"
                            ] += 1

                        compliance_summary["total_compliant"] += compliant_count
                        compliance_summary["total_noncompliant"] += noncompliant_count

                        progress.update(task, advance=1)

                except Exception as e:
                    error_msg = f"Error discovering {service}"
                    if region:
                        error_msg += f" in {region}"
                    error_msg += f": {str(e)}"

                    with update_lock:
                        summary["errors"].append(error_msg)
                        discovery_results[(service, region)] = {
                            "count": 0,
                            "compliant": 0,
                            "noncompliant": 0,
                            "error": True,
                        }
                        progress.update(task, advance=1)

    summary["end_time"] = datetime.utcnow()
    summary["duration_seconds"] = (
        summary["end_time"] - summary["start_time"]
    ).total_seconds()

    # Build compact tree after discovery
    _build_compact_tree(
        console, account_id, services, regions, discovery_results, compliance_summary
    )

    # Display compliance summary
    _display_compliance_summary(console, compliance_summary)

    return summary


def _build_compact_tree(
    console: Console,
    account_id: str,
    services: List[str],
    regions: List[str],
    discovery_results: Dict[Tuple[str, Optional[str]], Dict[str, int]],
    compliance_summary: Dict[str, Any],
) -> None:
    """Build and display a compact tree showing only regions with resources.

    Args:
        console: Rich console for display
        account_id: AWS account ID
        services: List of services discovered
        regions: List of regions scanned
        discovery_results: Results from discovery {(service, region): {count, compliant, noncompliant}}
        compliance_summary: Compliance statistics
    """
    # Create tree with account ID at root
    tree = Tree(f"[bold cyan]AWS Resource Discovery[/bold cyan]")
    account_node = tree.add(f"[bold white]{account_id}/[/bold white]")

    # Resource type labels
    resource_types = {
        "ec2": "instances",
        "s3": "buckets",
        "lambda": "functions",
        "rds": "databases",
        "dynamodb": "tables",
        "ecs": "services",
        "elb": "load balancers",
    }

    # Check if we should show compliance info
    from_org_policy = compliance_summary.get("from_org_policy", False)
    show_compliance = from_org_policy and bool(compliance_summary.get("required_tags"))

    for service in services:
        service_stats = compliance_summary["by_service"].get(service, {})
        total = service_stats.get("total", 0)
        compliant = service_stats.get("compliant", 0)
        noncompliant = service_stats.get("noncompliant", 0) if show_compliance else 0
        regions_with_resources = service_stats.get("regions_with_resources", 0)
        resource_type = resource_types.get(service, "resources")

        # Determine service status and style
        if total == 0:
            # No resources found - show collapsed with dim style
            service_text = Text(f"{service}/", style="dim")
            service_text.append(f" (no {resource_type})", style="dim")
            account_node.add(service_text)
        elif not show_compliance or noncompliant == 0:
            # No compliance checking or all compliant - show collapsed
            service_text = Text(f"{service}/", style="bold cyan")
            if service == "s3":
                service_text.append(f" ({total} {resource_type})", style="cyan")
            else:
                region_label = "region" if regions_with_resources == 1 else "regions"
                service_text.append(
                    f" ({total} {resource_type} in {regions_with_resources} {region_label})",
                    style="cyan",
                )
            account_node.add(service_text)
        else:
            # Has non-compliant resources - expand to show regions
            service_text = Text(f"{service}/", style="bold yellow")
            if service == "s3":
                service_text.append(f" ({total} {resource_type}, ", style="yellow")
            else:
                region_label = "region" if regions_with_resources == 1 else "regions"
                service_text.append(
                    f" ({total} {resource_type} in {regions_with_resources} {region_label}, ",
                    style="yellow",
                )
            service_text.append(f"{noncompliant} non-compliant", style="red")
            service_text.append(")", style="yellow")
            service_node = account_node.add(service_text)

            # Add regions with resources (expanded view)
            if service == "s3":
                result = discovery_results.get((service, None), {})
                if result.get("count", 0) > 0:
                    region_text = Text("global/", style="dim")
                    region_text.append(
                        f" {result['count']} {resource_type}", style="white"
                    )
                    if result.get("noncompliant", 0) > 0:
                        region_text.append(
                            f", {result['noncompliant']} non-compliant", style="red"
                        )
                    service_node.add(region_text)
            else:
                # Sort regions: those with non-compliant first, then by count
                region_results = []
                for region in regions:
                    result = discovery_results.get((service, region), {})
                    if result.get("count", 0) > 0:
                        region_results.append((region, result))

                # Sort by non-compliant count (desc), then by total count (desc)
                region_results.sort(
                    key=lambda x: (-x[1].get("noncompliant", 0), -x[1].get("count", 0))
                )

                for region, result in region_results:
                    region_text = Text(f"{region}/", style="dim")
                    region_text.append(
                        f" {result['count']} {resource_type}", style="white"
                    )
                    if result.get("noncompliant", 0) > 0:
                        region_text.append(
                            f", {result['noncompliant']} non-compliant", style="red"
                        )
                    service_node.add(region_text)

                # Show collapsed empty regions count
                empty_regions = len(regions) - len(region_results)
                if empty_regions > 0:
                    collapsed_text = Text(
                        f"[{empty_regions} regions with no {resource_type}]",
                        style="dim italic",
                    )
                    service_node.add(collapsed_text)

    console.print(tree)
    console.print()


def _display_compliance_summary(
    console: Console, compliance_summary: Dict[str, Any]
) -> None:
    """Display compliance summary after discovery.

    Args:
        console: Rich console for output
        compliance_summary: Dictionary with compliance statistics
    """
    from rich.table import Table
    from rich.panel import Panel

    required_tags = compliance_summary.get("required_tags", [])
    from_org_policy = compliance_summary.get("from_org_policy", False)

    # Skip compliance display if no tag policies are defined
    if not required_tags or not from_org_policy:
        return

    total_compliant = compliance_summary.get("total_compliant", 0)
    total_noncompliant = compliance_summary.get("total_noncompliant", 0)
    total = total_compliant + total_noncompliant

    if total == 0:
        return

    compliance_rate = (total_compliant / total * 100) if total > 0 else 0

    console.print()

    # Build summary text
    policy_source = "AWS Organizations policy" if from_org_policy else "default tags"
    compliance_mode = (
        "AND (all required)" if from_org_policy else "OR (any one sufficient)"
    )

    # Create summary panel (ASCII-safe for PyInstaller)
    summary_lines = [
        f"[bold]Tag Compliance Summary[/bold] (based on {policy_source})",
        "",
        f"[cyan]Required Tags:[/cyan] {', '.join(required_tags)}",
        f"[dim]Compliance Mode:[/dim] {compliance_mode}",
        f"[green]Compliant:[/green] {total_compliant} resources ({compliance_rate:.1f}%)",
        f"[red]Non-compliant:[/red] {total_noncompliant} resources ({100 - compliance_rate:.1f}%)",
    ]

    console.print(
        Panel(
            "\n".join(summary_lines), title="Compliance Overview", border_style="blue"
        )
    )

    # Show breakdown by service if there are non-compliant resources
    if total_noncompliant > 0 and compliance_summary.get("by_service"):
        table = Table(
            title="Non-compliant Resources by Service",
            show_header=True,
            header_style="bold cyan",
        )
        table.add_column("Service", style="cyan")
        table.add_column("Compliant", style="green", justify="right")
        table.add_column("Non-compliant", style="red", justify="right")
        table.add_column("Rate", style="yellow", justify="right")

        for service, stats in compliance_summary["by_service"].items():
            svc_total = stats.get("compliant", 0) + stats.get("noncompliant", 0)
            if svc_total == 0:
                continue
            svc_rate = (
                (stats.get("compliant", 0) / svc_total * 100) if svc_total > 0 else 0
            )
            table.add_row(
                service.upper(),
                str(stats.get("compliant", 0)),
                str(stats.get("noncompliant", 0)),
                f"{svc_rate:.1f}%",
            )

        console.print(table)
        console.print()
        console.print(
            "[dim]Run 'bluearch-aws-tags policy check-compliance --details' "
            "to see detailed non-compliant resources.[/dim]"
        )

        if not from_org_policy:
            console.print(
                "[dim]Run 'bluearch-aws-tags policy wizard' to set up "
                "organization-wide tag policies.[/dim]"
            )


def discover_ec2_resources(
    region: str = None,
    regions: List[str] = None,
    account_id: str = None,
    role_name: str = None,
    store_directly: bool = True,
    session: Any = None,  # boto3.Session to use instead of global aws_auth
) -> Dict[str, Any]:
    """Discover EC2 resources (instances and EBS volumes) in a region or multiple regions.

    Args:
        region: Single AWS region to scan (deprecated, use regions)
        regions: List of AWS regions to scan
        account_id: Target account ID for cross-account discovery
        role_name: IAM role name for cross-account access

    Returns:
        Dictionary with discovery statistics or List of resources for multi-account
    """
    # Handle backward compatibility
    if region and not regions:
        regions = [region]
    elif not regions:
        regions = ["us-east-1", "us-west-2"]

    # For multi-account discovery, we want to return the resources
    # but also maintain backwards compatibility for single-account mode

    # Initialize discovery stats with discovered_resources for both modes
    discovery_stats = {
        "region": regions[0] if len(regions) == 1 else "multiple",
        "discovered_count": 0,
        "cached_count": 0,
        "errors": [],
        "resource_types": {},
        "discovered_resources": [],  # Add this for collecting resources
    }

    for region in regions:
        try:
            # Check cache first (include account_id to prevent cross-account cache pollution)
            effective_account_id = account_id or get_current_account_id()
            cache_key = cache.generate_key(
                "ec2",
                "describe_instances",
                region=region,
                account_id=effective_account_id,
            )
            cached_instances = cache.get(cache_key)

            if cached_instances:
                discovery_stats["cached_count"] += len(cached_instances)
                instances_data = cached_instances
            else:
                # Fetch from AWS API
                # Use provided session if available, otherwise fall back to global aws_auth
                if session:
                    ec2_client = session.client("ec2", region_name=region)
                else:
                    ec2_client = aws_auth.get_client("ec2", region=region)

                try:
                    # Handle pagination to get ALL instances
                    instances_data = []
                    next_token = None

                    while True:
                        if next_token:
                            response = ec2_client.describe_instances(
                                NextToken=next_token
                            )
                        else:
                            response = ec2_client.describe_instances()

                        for reservation in response.get("Reservations", []):
                            instances_data.extend(reservation.get("Instances", []))

                        # Check if there are more results
                        next_token = response.get("NextToken")
                        if not next_token:
                            break

                    # Cache the complete results
                    cache.set(
                        cache_key, instances_data, ttl=settings.cache_ttl_resources
                    )

                except ClientError as e:
                    from ..utils.error_handlers import check_permission_error

                    if check_permission_error(e):
                        # Log the permission error but continue discovery for other resources
                        discovery_stats["errors"].append(
                            f"No permission to describe EC2 instances in {region}"
                        )
                        discovery_stats["permission_errors"] = (
                            discovery_stats.get("permission_errors", 0) + 1
                        )
                        return discovery_stats
                    else:
                        raise

            # Process instances
            for instance_data in instances_data:
                try:
                    resource = process_ec2_instance(instance_data, region)
                    if resource:
                        if store_directly:
                            store_resource(
                                resource
                            )  # Store immediately for single-account discovery
                        discovery_stats["discovered_resources"].append(
                            resource
                        )  # Collect the resource
                        discovery_stats["discovered_count"] += 1
                        discovery_stats["resource_types"]["ec2_instance"] = (
                            discovery_stats["resource_types"].get("ec2_instance", 0) + 1
                        )

                except Exception as e:
                    discovery_stats["errors"].append(
                        f"Error processing instance {instance_data.get('InstanceId', 'unknown')}: {str(e)}"
                    )

            # Discover EBS volumes
            try:
                volumes_result = discover_ebs_volumes(
                    region,
                    store_directly=store_directly,
                    session=session,
                    account_id=effective_account_id,
                )
                discovery_stats["discovered_count"] += volumes_result.get(
                    "discovered_count", 0
                )
                discovery_stats["resource_types"]["ebs_volume"] = volumes_result.get(
                    "discovered_count", 0
                )
                discovery_stats["errors"].extend(volumes_result.get("errors", []))
                # Collect EBS volume resources if returned
                if "discovered_resources" in volumes_result:
                    discovery_stats["discovered_resources"].extend(
                        volumes_result["discovered_resources"]
                    )
            except Exception as e:
                discovery_stats["errors"].append(
                    f"Error discovering EBS volumes: {str(e)}"
                )

        except Exception as e:
            discovery_stats["errors"].append(
                f"Error discovering EC2 resources in {region}: {str(e)}"
            )

    return discovery_stats


def discover_ebs_volumes(
    region: str,
    store_directly: bool = True,
    session: Any = None,
    account_id: str = None,
) -> Dict[str, Any]:
    """Discover EBS volumes in a region.

    Args:
        region: AWS region to scan
        store_directly: If True, store resources immediately in database.
                       If False, just return resources (for multi-account discovery)
        session: Optional boto3.Session to use instead of global aws_auth
        account_id: Account ID for cache key generation

    Returns:
        Dictionary with discovery statistics
    """
    volume_stats = {"discovered_count": 0, "errors": [], "discovered_resources": []}

    try:
        # Use provided session if available, otherwise fall back to global aws_auth
        if session:
            ec2_client = session.client("ec2", region_name=region)
        else:
            ec2_client = aws_auth.get_client("ec2", region=region)

        # Handle pagination to get ALL volumes
        volumes_data = []
        next_token = None

        while True:
            if next_token:
                response = ec2_client.describe_volumes(NextToken=next_token)
            else:
                response = ec2_client.describe_volumes()

            volumes_data.extend(response.get("Volumes", []))

            # Check if there are more results
            next_token = response.get("NextToken")
            if not next_token:
                break

        for volume_data in volumes_data:
            try:
                resource = process_ebs_volume(volume_data, region)
                if resource:
                    if store_directly:
                        store_resource(
                            resource
                        )  # Store immediately for single-account discovery
                    volume_stats["discovered_resources"].append(resource)
                    volume_stats["discovered_count"] += 1

            except Exception as e:
                volume_stats["errors"].append(
                    f"Error processing volume {volume_data.get('VolumeId', 'unknown')}: {str(e)}"
                )

    except ClientError as e:
        from ..utils.error_handlers import check_permission_error

        if not check_permission_error(e):
            raise
        volume_stats["errors"].append(
            f"No permission to describe EBS volumes in {region}"
        )
        volume_stats["permission_errors"] = volume_stats.get("permission_errors", 0) + 1

    return volume_stats


def discover_s3_resources(
    region: Optional[str] = None,
    store_directly: bool = True,
    session: Any = None,
    account_id: str = None,
) -> Dict[str, Any]:
    """Discover S3 buckets across all regions or filtered by region.

    Args:
        region: Optional region filter (default: all regions)
        store_directly: If True, store resources to database immediately (for single-account discovery)
                       If False, just return resources (for multi-account discovery)
        session: Optional boto3.Session to use instead of global aws_auth
        account_id: Account ID for cache key generation

    Returns:
        Dictionary with discovery statistics
    """
    discovery_stats = {
        "discovered_count": 0,
        "errors": [],
        "resource_types": {"s3_bucket": 0},
        "discovered_resources": [],  # Add this to collect resources
    }

    try:
        # S3 is global, but we'll associate buckets with regions
        # Use provided session if available, otherwise fall back to global aws_auth
        if session:
            s3_client = session.client("s3")
        else:
            s3_client = aws_auth.get_client("s3")

        # Check cache first (include account_id to prevent cross-account cache pollution)
        effective_account_id = account_id or get_current_account_id()
        cache_key = cache.generate_key(
            "s3", "list_buckets", account_id=effective_account_id
        )
        cached_buckets = cache.get(cache_key)

        if cached_buckets:
            buckets_data = cached_buckets
        else:
            response = s3_client.list_buckets()
            buckets_data = response.get("Buckets", [])

            # Cache for longer since S3 buckets don't change frequently
            cache.set(cache_key, buckets_data, ttl=settings.cache_ttl_resources * 4)

        for bucket_data in buckets_data:
            try:
                # Get bucket region
                bucket_name = bucket_data["Name"]
                bucket_region = get_bucket_region(bucket_name)

                # If region filter is specified, skip buckets in other regions
                if region and bucket_region != region:
                    continue

                resource = process_s3_bucket(bucket_data, bucket_region)
                if resource:
                    if store_directly:
                        store_resource(
                            resource
                        )  # Store immediately for single-account discovery
                    discovery_stats["discovered_resources"].append(
                        resource
                    )  # Collect the resource
                    discovery_stats["discovered_count"] += 1
                    discovery_stats["resource_types"]["s3_bucket"] += 1

            except Exception as e:
                discovery_stats["errors"].append(
                    f"Error processing bucket {bucket_data.get('Name', 'unknown')}: {str(e)}"
                )

    except ClientError as e:
        from ..utils.error_handlers import check_permission_error

        if not check_permission_error(e):
            raise
        discovery_stats["errors"].append("No permission to list S3 buckets")
        discovery_stats["permission_errors"] = (
            discovery_stats.get("permission_errors", 0) + 1
        )

    return discovery_stats


def get_bucket_region(bucket_name: str) -> str:
    """Get the region of an S3 bucket.

    Args:
        bucket_name: S3 bucket name

    Returns:
        AWS region (default: 'us-east-1')
    """
    try:
        cache_key = cache.generate_key("s3", "bucket_location", bucket=bucket_name)
        cached_region = cache.get(cache_key)

        if cached_region:
            return cached_region

        s3_client = aws_auth.get_client("s3")
        response = s3_client.get_bucket_location(Bucket=bucket_name)
        region = response.get("LocationConstraint") or "us-east-1"

        # Cache bucket region for a long time
        cache.set(cache_key, region, ttl=86400)  # 24 hours

        return region

    except Exception:
        return "us-east-1"  # Default region


def discover_lambda_resources(
    region: str,
    store_directly: bool = True,
    session: Any = None,
    account_id: str = None,
) -> Dict[str, Any]:
    """Discover Lambda functions in a region.

    Args:
        region: AWS region to scan
        store_directly: If True, store resources immediately in database
        session: Optional boto3.Session to use instead of global aws_auth
        account_id: Account ID for cache key generation

    Returns:
        Dictionary with discovery statistics
    """
    discovery_stats = {
        "region": region,
        "discovered_count": 0,
        "errors": [],
        "resource_types": {"lambda_function": 0},
        "discovered_resources": [],  # Add this to collect resources
    }

    try:
        # Use provided session if available, otherwise fall back to global aws_auth
        if session:
            lambda_client = session.client("lambda", region_name=region)
        else:
            lambda_client = aws_auth.get_client("lambda", region=region)

        # Check cache first (include account_id to prevent cross-account cache pollution)
        effective_account_id = account_id or get_current_account_id()
        cache_key = cache.generate_key(
            "lambda", "list_functions", region=region, account_id=effective_account_id
        )
        cached_functions = cache.get(cache_key)

        if cached_functions:
            functions_data = cached_functions
        else:
            # Handle pagination to get ALL functions
            functions_data = []
            next_marker = None

            while True:
                if next_marker:
                    response = lambda_client.list_functions(Marker=next_marker)
                else:
                    response = lambda_client.list_functions()

                functions_data.extend(response.get("Functions", []))

                # Check if there are more results
                next_marker = response.get("NextMarker")
                if not next_marker:
                    break

            # Cache the complete results
            cache.set(cache_key, functions_data, ttl=settings.cache_ttl_resources)

        for function_data in functions_data:
            try:
                resource = process_lambda_function(function_data, region)
                if resource:
                    if store_directly:
                        store_resource(
                            resource
                        )  # Store immediately for single-account discovery
                    discovery_stats["discovered_resources"].append(
                        resource
                    )  # Collect the resource
                    discovery_stats["discovered_count"] += 1
                    discovery_stats["resource_types"]["lambda_function"] += 1

            except Exception as e:
                discovery_stats["errors"].append(
                    f"Error processing function {function_data.get('FunctionName', 'unknown')}: {str(e)}"
                )

    except ClientError as e:
        from ..utils.error_handlers import check_permission_error

        if not check_permission_error(e):
            raise
        discovery_stats["errors"].append(
            f"No permission to list Lambda functions in {region}"
        )
        discovery_stats["permission_errors"] = (
            discovery_stats.get("permission_errors", 0) + 1
        )

    return discovery_stats


# Resource processing helper functions


def get_current_account_id() -> str:
    """Get current AWS account ID from STS.

    Returns:
        AWS account ID or 'unknown'
    """
    try:
        sts_client = aws_auth.get_client("sts")
        identity = sts_client.get_caller_identity()
        return identity["Account"]
    except Exception:
        return "unknown"


def process_ec2_instance(
    instance_data: Dict[str, Any], region: str
) -> Optional[Dict[str, Any]]:
    """Process EC2 instance data into standardized resource format.

    Args:
        instance_data: Raw EC2 instance data from AWS API
        region: AWS region

    Returns:
        Standardized resource dictionary
    """
    try:
        instance_id = instance_data["InstanceId"]

        # Extract tags
        tags = {}
        for tag in instance_data.get("Tags", []):
            tags[tag["Key"]] = tag["Value"]

        # Get account ID from OwnerId or fallback to STS
        account_id = instance_data.get("OwnerId") or get_current_account_id()

        # Build relationships
        relationships = []
        instance_arn = f"arn:aws:ec2:{region}:{account_id}:instance/{instance_id}"
        vpc_id = instance_data.get("VpcId")
        if vpc_id:
            relationships.append(
                {
                    "source_arn": instance_arn,
                    "target_arn": _ec2_arn(region, account_id, "vpc", vpc_id),
                    "relationship_type": "RUNS_IN",
                    "source_type": "AWS::EC2::Instance",
                    "target_type": "AWS::EC2::VPC",
                    "region": region,
                    "account_id": account_id,
                }
            )
        subnet_id = instance_data.get("SubnetId")
        if subnet_id:
            relationships.append(
                {
                    "source_arn": instance_arn,
                    "target_arn": _ec2_arn(region, account_id, "subnet", subnet_id),
                    "relationship_type": "RUNS_IN",
                    "source_type": "AWS::EC2::Instance",
                    "target_type": "AWS::EC2::Subnet",
                    "region": region,
                    "account_id": account_id,
                }
            )
        for sg in instance_data.get("SecurityGroups", []):
            sg_id = sg.get("GroupId")
            if sg_id:
                relationships.append(
                    {
                        "source_arn": instance_arn,
                        "target_arn": _ec2_arn(
                            region, account_id, "security-group", sg_id
                        ),
                        "relationship_type": "USES",
                        "source_type": "AWS::EC2::Instance",
                        "target_type": "AWS::EC2::SecurityGroup",
                        "region": region,
                        "account_id": account_id,
                    }
                )
        iam_profile = instance_data.get("IamInstanceProfile", {})
        profile_arn = iam_profile.get("Arn", "")
        if profile_arn:
            relationships.append(
                {
                    "source_arn": instance_arn,
                    "target_arn": profile_arn,
                    "relationship_type": "USES",
                    "source_type": "AWS::EC2::Instance",
                    "target_type": "AWS::IAM::InstanceProfile",
                    "region": region,
                    "account_id": account_id,
                }
            )

        return {
            "resource_arn": instance_arn,
            "resource_type": "AWS::EC2::Instance",
            "service_name": "ec2",
            "region": region,
            "account_id": account_id,
            "resource_id": instance_id,
            "created_at": instance_data.get("LaunchTime"),
            "current_tags": tags,
            "metadata_json": {
                "instance_type": instance_data.get("InstanceType"),
                "state": instance_data.get("State", {}).get("Name"),
                "vpc_id": instance_data.get("VpcId"),
                "subnet_id": instance_data.get("SubnetId"),
                "public_ip": instance_data.get("PublicIpAddress"),
                "private_ip": instance_data.get("PrivateIpAddress"),
            },
            "relationships": relationships,
        }
    except KeyError as e:
        raise ValueError(f"Missing required field in EC2 instance data: {e}")


def process_ebs_volume(
    volume_data: Dict[str, Any], region: str
) -> Optional[Dict[str, Any]]:
    """Process EBS volume data into standardized resource format.

    Args:
        volume_data: Raw EBS volume data from AWS API
        region: AWS region

    Returns:
        Standardized resource dictionary
    """
    try:
        volume_id = volume_data["VolumeId"]

        # Extract tags
        tags = {}
        for tag in volume_data.get("Tags", []):
            tags[tag["Key"]] = tag["Value"]

        # Get account ID from OwnerId or fallback to STS
        account_id = volume_data.get("OwnerId") or get_current_account_id()

        # Build relationships
        relationships = []
        for attachment in volume_data.get("Attachments", []):
            inst_id = attachment.get("InstanceId")
            if inst_id:
                relationships.append(
                    {
                        "source_arn": f"arn:aws:ec2:{region}:{account_id}:volume/{volume_id}",
                        "target_arn": f"arn:aws:ec2:{region}:{account_id}:instance/{inst_id}",
                        "relationship_type": "ATTACHED_TO",
                        "source_type": "AWS::EC2::Volume",
                        "target_type": "AWS::EC2::Instance",
                        "region": region,
                        "account_id": account_id,
                    }
                )

        return {
            "resource_arn": f"arn:aws:ec2:{region}:{account_id}:volume/{volume_id}",
            "resource_type": "AWS::EC2::Volume",
            "service_name": "ec2",
            "region": region,
            "account_id": account_id,
            "resource_id": volume_id,
            "created_at": volume_data.get("CreateTime"),
            "current_tags": tags,
            "metadata_json": {
                "size_gb": volume_data.get("Size"),
                "volume_type": volume_data.get("VolumeType"),
                "state": volume_data.get("State"),
                "availability_zone": volume_data.get("AvailabilityZone"),
                "encrypted": volume_data.get("Encrypted", False),
                "iops": volume_data.get("Iops"),
                "throughput": volume_data.get("Throughput"),
            },
            "relationships": relationships,
        }
    except KeyError as e:
        raise ValueError(f"Missing required field in EBS volume data: {e}")


def process_ec2_eip(
    address_data: Dict[str, Any], region: str
) -> Optional[Dict[str, Any]]:
    """Process Elastic IP address data into standardized resource format.

    Args:
        address_data: Raw EIP data from AWS API (describe_addresses)
        region: AWS region

    Returns:
        Standardized resource dictionary
    """
    try:
        allocation_id = address_data.get("AllocationId", "")
        public_ip = address_data.get("PublicIp", "")

        # Extract tags
        tags = {}
        for tag in address_data.get("Tags", []):
            tags[tag["Key"]] = tag["Value"]

        account_id = (
            address_data.get("NetworkBorderGroup", "").split(":")[0]
            if ":" in address_data.get("NetworkBorderGroup", "")
            else get_current_account_id()
        )

        resource_id = allocation_id or public_ip

        # Build relationships
        relationships = []
        eip_arn = (
            f"arn:aws:ec2:{region}:{account_id}:elastic-ip/{allocation_id}"
            if allocation_id
            else f"arn:aws:ec2:{region}:{account_id}:elastic-ip/{public_ip}"
        )
        attached_instance = address_data.get("InstanceId")
        if attached_instance:
            relationships.append(
                {
                    "source_arn": eip_arn,
                    "target_arn": f"arn:aws:ec2:{region}:{account_id}:instance/{attached_instance}",
                    "relationship_type": "ATTACHED_TO",
                    "source_type": "AWS::EC2::EIP",
                    "target_type": "AWS::EC2::Instance",
                    "region": region,
                    "account_id": account_id,
                }
            )
        attached_eni = address_data.get("NetworkInterfaceId")
        if attached_eni and not attached_instance:
            relationships.append(
                {
                    "source_arn": eip_arn,
                    "target_arn": _ec2_arn(
                        region, account_id, "network-interface", attached_eni
                    ),
                    "relationship_type": "ATTACHED_TO",
                    "source_type": "AWS::EC2::EIP",
                    "target_type": "AWS::EC2::NetworkInterface",
                    "region": region,
                    "account_id": account_id,
                }
            )

        return {
            "resource_arn": eip_arn,
            "resource_type": "AWS::EC2::EIP",
            "service_name": "ec2",
            "region": region,
            "account_id": account_id,
            "resource_id": resource_id,
            "created_at": None,
            "current_tags": tags,
            "metadata_json": {
                "public_ip": public_ip,
                "allocation_id": allocation_id,
                "association_id": address_data.get("AssociationId"),
                "instance_id": address_data.get("InstanceId"),
                "network_interface_id": address_data.get("NetworkInterfaceId"),
                "domain": address_data.get("Domain", "vpc"),
                "private_ip": address_data.get("PrivateIpAddress"),
            },
            "relationships": relationships,
        }
    except KeyError as e:
        raise ValueError(f"Missing required field in EIP data: {e}")


def process_ec2_image(
    image_data: Dict[str, Any], region: str
) -> Optional[Dict[str, Any]]:
    """Process EC2 AMI data into standardized resource format.

    Args:
        image_data: Raw AMI data from AWS API (describe_images)
        region: AWS region

    Returns:
        Standardized resource dictionary
    """
    try:
        from datetime import datetime

        image_id = image_data["ImageId"]

        # Extract tags
        tags = {}
        for tag in image_data.get("Tags", []):
            tags[tag["Key"]] = tag["Value"]

        account_id = image_data.get("OwnerId") or get_current_account_id()

        # CreationDate comes as ISO string from AWS - parse to datetime
        created_at = None
        raw_date = image_data.get("CreationDate")
        if raw_date and isinstance(raw_date, str):
            try:
                created_at = datetime.fromisoformat(raw_date.replace("Z", "+00:00"))
            except (ValueError, TypeError):
                created_at = None
        elif raw_date:
            created_at = raw_date

        return {
            "resource_arn": f"arn:aws:ec2:{region}:{account_id}:image/{image_id}",
            "resource_type": "AWS::EC2::Image",
            "service_name": "ec2",
            "region": region,
            "account_id": account_id,
            "resource_id": image_id,
            "created_at": created_at,
            "current_tags": tags,
            "metadata_json": {
                "name": image_data.get("Name"),
                "state": image_data.get("State"),
                "architecture": image_data.get("Architecture"),
                "platform": image_data.get("PlatformDetails"),
                "root_device_type": image_data.get("RootDeviceType"),
                "virtualization_type": image_data.get("VirtualizationType"),
                "public": image_data.get("Public", False),
            },
        }
    except KeyError as e:
        raise ValueError(f"Missing required field in AMI data: {e}")


def discover_rds_resources(
    regions: Optional[List[str]] = None,
    store_directly: bool = True,
    session: Any = None,
    account_id: str = None,
) -> Dict[str, Any]:
    """Discover RDS resources (DB instances and clusters) across regions.

    Args:
        regions: List of AWS regions to scan. If None, scans all regions.
        store_directly: If True, store resources immediately in database.
                       If False, just return resources (for multi-account discovery)
        session: Optional boto3.Session to use instead of global aws_auth
        account_id: Account ID for cache key generation

    Returns:
        Dictionary with discovery statistics
    """
    discovery_stats = {
        "discovered_count": 0,
        "errors": [],
        "resource_types": {},
        "discovered_resources": [],
    }

    # If no regions specified, get all regions
    if not regions:
        try:
            if session:
                ec2_client = session.client("ec2", region_name="us-east-1")
            else:
                ec2_client = aws_auth.get_client("ec2", region="us-east-1")
            response = ec2_client.describe_regions()
            regions = [r["RegionName"] for r in response["Regions"]]
        except Exception as e:
            logger.warning(f"Failed to get regions list: {e}. Using defaults.")
            regions = ["us-east-1", "us-west-2", "eu-west-1"]

    for region in regions:
        try:
            # Use provided session if available, otherwise fall back to global aws_auth
            if session:
                rds_client = session.client("rds", region_name=region)
            else:
                rds_client = aws_auth.get_client("rds", region=region)

            # Discover DB instances with pagination
            db_instances = []
            next_marker = None

            while True:
                if next_marker:
                    response = rds_client.describe_db_instances(Marker=next_marker)
                else:
                    response = rds_client.describe_db_instances()

                db_instances.extend(response.get("DBInstances", []))

                # Check if there are more results
                next_marker = response.get("Marker")
                if not next_marker:
                    break

            # Process DB instances
            for db_instance in db_instances:
                try:
                    resource = process_rds_instance(db_instance, region)
                    if resource:
                        if store_directly:
                            store_resource(resource)
                        discovery_stats["discovered_resources"].append(resource)
                        discovery_stats["discovered_count"] += 1
                        discovery_stats["resource_types"]["rds_instance"] = (
                            discovery_stats["resource_types"].get("rds_instance", 0) + 1
                        )
                except Exception as e:
                    discovery_stats["errors"].append(
                        f"Error processing RDS instance {db_instance.get('DBInstanceIdentifier', 'unknown')}: {str(e)}"
                    )

            # Discover DB clusters with pagination
            db_clusters = []
            next_marker = None

            while True:
                if next_marker:
                    response = rds_client.describe_db_clusters(Marker=next_marker)
                else:
                    response = rds_client.describe_db_clusters()

                db_clusters.extend(response.get("DBClusters", []))

                # Check if there are more results
                next_marker = response.get("Marker")
                if not next_marker:
                    break

            # Process DB clusters
            for db_cluster in db_clusters:
                try:
                    resource = process_rds_cluster(db_cluster, region)
                    if resource:
                        if store_directly:
                            store_resource(resource)
                        discovery_stats["discovered_resources"].append(resource)
                        discovery_stats["discovered_count"] += 1
                        discovery_stats["resource_types"]["rds_cluster"] = (
                            discovery_stats["resource_types"].get("rds_cluster", 0) + 1
                        )
                except Exception as e:
                    discovery_stats["errors"].append(
                        f"Error processing RDS cluster {db_cluster.get('DBClusterIdentifier', 'unknown')}: {str(e)}"
                    )

        except ClientError as e:
            from ..utils.error_handlers import check_permission_error

            if not check_permission_error(e):
                raise
            discovery_stats["errors"].append(
                f"No permission to describe RDS resources in {region}"
            )
            discovery_stats["permission_errors"] = (
                discovery_stats.get("permission_errors", 0) + 1
            )

        except Exception as e:
            discovery_stats["errors"].append(
                f"Error discovering RDS resources in {region}: {str(e)}"
            )

    return discovery_stats


def process_rds_instance(
    db_instance: Dict[str, Any], region: str
) -> Optional[Dict[str, Any]]:
    """Process RDS DB instance data into standardized resource format.

    Args:
        db_instance: Raw RDS DB instance data from AWS API
        region: AWS region

    Returns:
        Standardized resource dictionary
    """
    try:
        db_instance_id = db_instance["DBInstanceIdentifier"]
        db_instance_arn = db_instance["DBInstanceArn"]

        # Extract tags
        tags = {}
        for tag in db_instance.get("TagList", []):
            tags[tag["Key"]] = tag["Value"]

        # Extract account ID from ARN
        arn_parts = db_instance_arn.split(":")
        account_id = arn_parts[4] if len(arn_parts) > 4 else get_current_account_id()

        # Build relationships
        relationships = []
        for sg in db_instance.get("VpcSecurityGroups", []):
            sg_id = sg.get("VpcSecurityGroupId")
            if sg_id:
                relationships.append(
                    {
                        "source_arn": db_instance_arn,
                        "target_arn": _ec2_arn(
                            region, account_id, "security-group", sg_id
                        ),
                        "relationship_type": "USES",
                        "source_type": "AWS::RDS::DBInstance",
                        "target_type": "AWS::EC2::SecurityGroup",
                        "region": region,
                        "account_id": account_id,
                    }
                )
        cluster_id = db_instance.get("DBClusterIdentifier")
        if cluster_id:
            relationships.append(
                {
                    "source_arn": db_instance_arn,
                    "target_arn": f"arn:aws:rds:{region}:{account_id}:cluster:{cluster_id}",
                    "relationship_type": "BELONGS_TO",
                    "source_type": "AWS::RDS::DBInstance",
                    "target_type": "AWS::RDS::DBCluster",
                    "region": region,
                    "account_id": account_id,
                }
            )
        source_db_arn = db_instance.get("ReadReplicaSourceDBInstanceIdentifier")
        if source_db_arn:
            if not source_db_arn.startswith("arn:"):
                source_db_arn = f"arn:aws:rds:{region}:{account_id}:db:{source_db_arn}"
            relationships.append(
                {
                    "source_arn": db_instance_arn,
                    "target_arn": source_db_arn,
                    "relationship_type": "REPLICA_OF",
                    "source_type": "AWS::RDS::DBInstance",
                    "target_type": "AWS::RDS::DBInstance",
                    "region": region,
                    "account_id": account_id,
                }
            )
        # VPC and Subnet from DBSubnetGroup
        subnet_group = db_instance.get("DBSubnetGroup", {})
        vpc_id = subnet_group.get("VpcId")
        if vpc_id:
            relationships.append(
                {
                    "source_arn": db_instance_arn,
                    "target_arn": _ec2_arn(region, account_id, "vpc", vpc_id),
                    "relationship_type": "RUNS_IN",
                    "source_type": "AWS::RDS::DBInstance",
                    "target_type": "AWS::EC2::VPC",
                    "region": region,
                    "account_id": account_id,
                }
            )
        for subnet_info in subnet_group.get("Subnets", []):
            subnet_id = subnet_info.get("SubnetIdentifier")
            if subnet_id:
                relationships.append(
                    {
                        "source_arn": db_instance_arn,
                        "target_arn": _ec2_arn(region, account_id, "subnet", subnet_id),
                        "relationship_type": "RUNS_IN",
                        "source_type": "AWS::RDS::DBInstance",
                        "target_type": "AWS::EC2::Subnet",
                        "region": region,
                        "account_id": account_id,
                    }
                )

        return {
            "resource_arn": db_instance_arn,
            "resource_type": "AWS::RDS::DBInstance",
            "service_name": "rds",
            "region": region,
            "account_id": account_id,
            "resource_id": db_instance_id,
            "created_at": db_instance.get("InstanceCreateTime"),
            "current_tags": tags,
            "metadata_json": {
                "engine": db_instance.get("Engine"),
                "engine_version": db_instance.get("EngineVersion"),
                "instance_class": db_instance.get("DBInstanceClass"),
                "status": db_instance.get("DBInstanceStatus"),
                "multi_az": db_instance.get("MultiAZ", False),
                "storage_gb": db_instance.get("AllocatedStorage"),
                "storage_encrypted": db_instance.get("StorageEncrypted", False),
                "publicly_accessible": db_instance.get("PubliclyAccessible", False),
                "storage_type": db_instance.get("StorageType"),
                "deletion_protection": db_instance.get("DeletionProtection", False),
                "backup_retention_period": db_instance.get("BackupRetentionPeriod", 0),
            },
            "relationships": relationships,
        }
    except KeyError as e:
        raise ValueError(f"Missing required field in RDS instance data: {e}")


def process_rds_cluster(
    db_cluster: Dict[str, Any], region: str
) -> Optional[Dict[str, Any]]:
    """Process RDS DB cluster data into standardized resource format.

    Args:
        db_cluster: Raw RDS DB cluster data from AWS API
        region: AWS region

    Returns:
        Standardized resource dictionary
    """
    try:
        db_cluster_id = db_cluster["DBClusterIdentifier"]
        db_cluster_arn = db_cluster["DBClusterArn"]

        # Extract tags
        tags = {}
        for tag in db_cluster.get("TagList", []):
            tags[tag["Key"]] = tag["Value"]

        # Extract account ID from ARN
        arn_parts = db_cluster_arn.split(":")
        account_id = arn_parts[4] if len(arn_parts) > 4 else get_current_account_id()

        # Build relationships
        relationships = []
        for sg in db_cluster.get("VpcSecurityGroups", []):
            sg_id = sg.get("VpcSecurityGroupId")
            if sg_id:
                relationships.append(
                    {
                        "source_arn": db_cluster_arn,
                        "target_arn": _ec2_arn(
                            region, account_id, "security-group", sg_id
                        ),
                        "relationship_type": "USES",
                        "source_type": "AWS::RDS::DBCluster",
                        "target_type": "AWS::EC2::SecurityGroup",
                        "region": region,
                        "account_id": account_id,
                    }
                )
        # VPC from subnet group (clusters also have DBSubnetGroup)
        subnet_group = db_cluster.get("DBSubnetGroup") or {}
        # Clusters may also expose VpcId directly or inside DBSubnetGroup
        vpc_id = subnet_group.get("VpcId")
        if vpc_id:
            relationships.append(
                {
                    "source_arn": db_cluster_arn,
                    "target_arn": _ec2_arn(region, account_id, "vpc", vpc_id),
                    "relationship_type": "RUNS_IN",
                    "source_type": "AWS::RDS::DBCluster",
                    "target_type": "AWS::EC2::VPC",
                    "region": region,
                    "account_id": account_id,
                }
            )
        for subnet_info in subnet_group.get("Subnets", []):
            subnet_id = subnet_info.get("SubnetIdentifier")
            if subnet_id:
                relationships.append(
                    {
                        "source_arn": db_cluster_arn,
                        "target_arn": _ec2_arn(region, account_id, "subnet", subnet_id),
                        "relationship_type": "RUNS_IN",
                        "source_type": "AWS::RDS::DBCluster",
                        "target_type": "AWS::EC2::Subnet",
                        "region": region,
                        "account_id": account_id,
                    }
                )

        return {
            "resource_arn": db_cluster_arn,
            "resource_type": "AWS::RDS::DBCluster",
            "service_name": "rds",
            "region": region,
            "account_id": account_id,
            "resource_id": db_cluster_id,
            "created_at": db_cluster.get("ClusterCreateTime"),
            "current_tags": tags,
            "metadata_json": {
                "engine": db_cluster.get("Engine"),
                "engine_version": db_cluster.get("EngineVersion"),
                "status": db_cluster.get("Status"),
                "multi_az": db_cluster.get("MultiAZ", False),
                "storage_encrypted": db_cluster.get("StorageEncrypted", False),
                "database_name": db_cluster.get("DatabaseName"),
            },
            "relationships": relationships,
        }
    except KeyError as e:
        raise ValueError(f"Missing required field in RDS cluster data: {e}")


def discover_dynamodb_resources(
    regions: Optional[List[str]] = None,
    store_directly: bool = True,
    session: Any = None,
    account_id: str = None,
) -> Dict[str, Any]:
    """Discover DynamoDB tables across regions.

    Args:
        regions: List of AWS regions to scan. If None, scans all regions.
        store_directly: If True, store resources immediately in database.
                       If False, just return resources (for multi-account discovery)
        session: Optional boto3.Session to use instead of global aws_auth
        account_id: Account ID for cache key generation

    Returns:
        Dictionary with discovery statistics
    """
    discovery_stats = {
        "discovered_count": 0,
        "errors": [],
        "resource_types": {},
        "discovered_resources": [],
    }

    # If no regions specified, get all regions
    if not regions:
        try:
            if session:
                ec2_client = session.client("ec2", region_name="us-east-1")
            else:
                ec2_client = aws_auth.get_client("ec2", region="us-east-1")
            response = ec2_client.describe_regions()
            regions = [r["RegionName"] for r in response["Regions"]]
        except Exception as e:
            logger.warning(f"Failed to get regions list: {e}. Using defaults.")
            regions = ["us-east-1", "us-west-2", "eu-west-1"]

    for region in regions:
        try:
            # Use provided session if available, otherwise fall back to global aws_auth
            if session:
                dynamodb_client = session.client("dynamodb", region_name=region)
            else:
                dynamodb_client = aws_auth.get_client("dynamodb", region=region)

            # List DynamoDB tables with pagination
            table_names = []
            last_evaluated_table = None

            while True:
                if last_evaluated_table:
                    response = dynamodb_client.list_tables(
                        ExclusiveStartTableName=last_evaluated_table
                    )
                else:
                    response = dynamodb_client.list_tables()

                table_names.extend(response.get("TableNames", []))

                # Check if there are more results
                last_evaluated_table = response.get("LastEvaluatedTableName")
                if not last_evaluated_table:
                    break

            # Get detailed information for each table
            for table_name in table_names:
                try:
                    # Describe table to get full details
                    table_response = dynamodb_client.describe_table(
                        TableName=table_name
                    )
                    table_data = table_response.get("Table", {})

                    # Get tags for the table
                    table_arn = table_data.get("TableArn", "")
                    tags_response = dynamodb_client.list_tags_of_resource(
                        ResourceArn=table_arn
                    )
                    tag_list = tags_response.get("Tags", [])

                    resource = process_dynamodb_table(table_data, tag_list, region)
                    if resource:
                        if store_directly:
                            store_resource(resource)
                        discovery_stats["discovered_resources"].append(resource)
                        discovery_stats["discovered_count"] += 1
                        discovery_stats["resource_types"]["dynamodb_table"] = (
                            discovery_stats["resource_types"].get("dynamodb_table", 0)
                            + 1
                        )

                except Exception as e:
                    discovery_stats["errors"].append(
                        f"Error processing DynamoDB table {table_name}: {str(e)}"
                    )

        except ClientError as e:
            from ..utils.error_handlers import check_permission_error

            if not check_permission_error(e):
                raise
            discovery_stats["errors"].append(
                f"No permission to describe DynamoDB resources in {region}"
            )
            discovery_stats["permission_errors"] = (
                discovery_stats.get("permission_errors", 0) + 1
            )

        except Exception as e:
            discovery_stats["errors"].append(
                f"Error discovering DynamoDB resources in {region}: {str(e)}"
            )

    return discovery_stats


def process_dynamodb_table(
    table_data: Dict[str, Any], tag_list: List[Dict[str, str]], region: str
) -> Optional[Dict[str, Any]]:
    """Process DynamoDB table data into standardized resource format.

    Args:
        table_data: Raw DynamoDB table data from describe_table API
        tag_list: List of tags from list_tags_of_resource API
        region: AWS region

    Returns:
        Standardized resource dictionary
    """
    try:
        table_name = table_data["TableName"]
        table_arn = table_data["TableArn"]

        # Extract tags
        tags = {}
        for tag in tag_list:
            tags[tag["Key"]] = tag["Value"]

        # Extract account ID from ARN
        arn_parts = table_arn.split(":")
        account_id = arn_parts[4] if len(arn_parts) > 4 else get_current_account_id()

        return {
            "resource_arn": table_arn,
            "resource_type": "AWS::DynamoDB::Table",
            "service_name": "dynamodb",
            "region": region,
            "account_id": account_id,
            "resource_id": table_name,
            "created_at": table_data.get("CreationDateTime"),
            "current_tags": tags,
            "metadata_json": {
                "table_status": table_data.get("TableStatus"),
                "table_size_bytes": table_data.get("TableSizeBytes", 0),
                "item_count": table_data.get("ItemCount", 0),
                "billing_mode": table_data.get("BillingModeSummary", {}).get(
                    "BillingMode"
                ),
                "stream_enabled": table_data.get("StreamSpecification", {}).get(
                    "StreamEnabled", False
                ),
                "encryption_type": table_data.get("SSEDescription", {}).get("SSEType"),
                "deletion_protection": table_data.get(
                    "DeletionProtectionEnabled", False
                ),
                "table_class": table_data.get("TableClassSummary", {}).get(
                    "TableClass"
                ),
            },
        }
    except KeyError as e:
        raise ValueError(f"Missing required field in DynamoDB table data: {e}")


def process_s3_bucket(
    bucket_data: Dict[str, Any], region: str
) -> Optional[Dict[str, Any]]:
    """Process S3 bucket data into standardized resource format.

    Args:
        bucket_data: Raw S3 bucket data from AWS API
        region: AWS region

    Returns:
        Standardized resource dictionary
    """
    try:
        bucket_name = bucket_data["Name"]

        # Get bucket tags (separate API call)
        tags = get_s3_bucket_tags(bucket_name)

        # Get the actual AWS account ID - don't use bucket ACL owner ID (that's a canonical user ID)
        account_id = get_current_account_id()

        # Handle CreationDate which might be datetime or string (from cache)
        creation_date = bucket_data.get("CreationDate")
        creation_date_str = None
        if creation_date:
            if hasattr(creation_date, "isoformat"):
                # It's a datetime object
                creation_date_str = creation_date.isoformat()
            else:
                # It's already a string
                creation_date_str = str(creation_date)

        return {
            "resource_arn": f"arn:aws:s3:::{bucket_name}",
            "resource_type": "AWS::S3::Bucket",
            "service_name": "s3",
            "region": region,
            "account_id": account_id,
            "resource_id": bucket_name,
            "created_at": creation_date,
            "current_tags": tags,
            "metadata_json": {
                "bucket_name": bucket_name,
                "creation_date": creation_date_str,
            },
        }
    except KeyError as e:
        raise ValueError(f"Missing required field in S3 bucket data: {e}")


def get_s3_bucket_tags(bucket_name: str) -> Dict[str, str]:
    """Get tags for an S3 bucket.

    Args:
        bucket_name: S3 bucket name

    Returns:
        Dictionary of tag key-value pairs
    """
    try:
        cache_key = cache.generate_key("s3", "bucket_tags", bucket=bucket_name)
        cached_tags = cache.get(cache_key)

        if cached_tags:
            return cached_tags

        s3_client = aws_auth.get_client("s3")
        response = s3_client.get_bucket_tagging(Bucket=bucket_name)

        tags = {}
        for tag in response.get("TagSet", []):
            tags[tag["Key"]] = tag["Value"]

        # Cache tags for a while
        cache.set(cache_key, tags, ttl=settings.cache_ttl_resources)

        return tags

    except ClientError as e:
        if e.response["Error"]["Code"] == "NoSuchTagSet":
            return {}  # No tags set
        raise


def process_lambda_function(
    function_data: Dict[str, Any], region: str
) -> Optional[Dict[str, Any]]:
    """Process Lambda function data into standardized resource format.

    Args:
        function_data: Raw Lambda function data from AWS API
        region: AWS region

    Returns:
        Standardized resource dictionary
    """
    try:
        function_name = function_data["FunctionName"]
        function_arn = function_data["FunctionArn"]

        # Extract account ID from ARN
        arn_parts = function_arn.split(":")
        account_id = arn_parts[4] if len(arn_parts) > 4 else "unknown"

        # Get function tags (separate API call)
        tags = get_lambda_function_tags(function_arn)

        # Build relationships
        relationships = []
        role_arn = function_data.get("Role")
        if role_arn:
            relationships.append(
                {
                    "source_arn": function_arn,
                    "target_arn": role_arn,
                    "relationship_type": "USES",
                    "source_type": "AWS::Lambda::Function",
                    "target_type": "AWS::IAM::Role",
                    "region": region,
                    "account_id": account_id,
                }
            )
        vpc_config = function_data.get("VpcConfig", {})
        for subnet_id in vpc_config.get("SubnetIds", []):
            relationships.append(
                {
                    "source_arn": function_arn,
                    "target_arn": _ec2_arn(region, account_id, "subnet", subnet_id),
                    "relationship_type": "RUNS_IN",
                    "source_type": "AWS::Lambda::Function",
                    "target_type": "AWS::EC2::Subnet",
                    "region": region,
                    "account_id": account_id,
                }
            )
        for sg_id in vpc_config.get("SecurityGroupIds", []):
            relationships.append(
                {
                    "source_arn": function_arn,
                    "target_arn": _ec2_arn(region, account_id, "security-group", sg_id),
                    "relationship_type": "USES",
                    "source_type": "AWS::Lambda::Function",
                    "target_type": "AWS::EC2::SecurityGroup",
                    "region": region,
                    "account_id": account_id,
                }
            )
        for layer in function_data.get("Layers", []):
            layer_arn = layer.get("Arn")
            if layer_arn:
                relationships.append(
                    {
                        "source_arn": function_arn,
                        "target_arn": layer_arn,
                        "relationship_type": "USES",
                        "source_type": "AWS::Lambda::Function",
                        "target_type": "AWS::Lambda::LayerVersion",
                        "region": region,
                        "account_id": account_id,
                    }
                )

        return {
            "resource_arn": function_arn,
            "resource_type": "AWS::Lambda::Function",
            "service_name": "lambda",
            "region": region,
            "account_id": account_id,
            "resource_id": function_name,
            "created_at": datetime.fromisoformat(
                function_data["LastModified"].replace("Z", "+00:00")
            ),
            "current_tags": tags,
            "metadata_json": {
                "function_name": function_name,
                "runtime": function_data.get("Runtime"),
                "handler": function_data.get("Handler"),
                "code_size": function_data.get("CodeSize"),
                "timeout": function_data.get("Timeout"),
                "memory_size": function_data.get("MemorySize"),
                "last_modified": function_data.get("LastModified"),
                "architectures": function_data.get("Architectures", ["x86_64"]),
            },
            "relationships": relationships,
        }
    except KeyError as e:
        raise ValueError(f"Missing required field in Lambda function data: {e}")


def get_lambda_function_tags(function_arn: str) -> Dict[str, str]:
    """Get tags for a Lambda function.

    Args:
        function_arn: Lambda function ARN

    Returns:
        Dictionary of tag key-value pairs
    """
    try:
        cache_key = cache.generate_key("lambda", "function_tags", arn=function_arn)
        cached_tags = cache.get(cache_key)

        if cached_tags:
            return cached_tags

        lambda_client = aws_auth.get_client("lambda")
        response = lambda_client.list_tags(Resource=function_arn)

        tags = response.get("Tags", {})

        # Cache tags
        cache.set(cache_key, tags, ttl=settings.cache_ttl_resources)

        return tags

    except ClientError:
        return {}  # Return empty if can't get tags


def process_rds_snapshot(
    snapshot_data: Dict[str, Any], tag_list: List[Dict[str, str]], region: str
) -> Optional[Dict[str, Any]]:
    """Process RDS DB snapshot data into standardized resource format."""
    try:
        snapshot_id = snapshot_data["DBSnapshotIdentifier"]
        snapshot_arn = snapshot_data.get("DBSnapshotArn", "")
        arn_parts = snapshot_arn.split(":")
        account_id = arn_parts[4] if len(arn_parts) > 4 else get_current_account_id()

        tags = {t["Key"]: t["Value"] for t in tag_list}

        created_at = snapshot_data.get("SnapshotCreateTime")
        if created_at and isinstance(created_at, str):
            try:
                created_at = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
            except (ValueError, TypeError):
                created_at = None

        return {
            "resource_arn": snapshot_arn,
            "resource_type": "AWS::RDS::DBSnapshot",
            "service_name": "rds",
            "region": region,
            "account_id": account_id,
            "resource_id": snapshot_id,
            "created_at": created_at,
            "current_tags": tags,
            "metadata_json": {
                "db_instance_identifier": snapshot_data.get("DBInstanceIdentifier"),
                "engine": snapshot_data.get("Engine"),
                "engine_version": snapshot_data.get("EngineVersion"),
                "status": snapshot_data.get("Status"),
                "snapshot_type": snapshot_data.get("SnapshotType"),
                "allocated_storage": snapshot_data.get("AllocatedStorage"),
            },
        }
    except KeyError as e:
        raise ValueError(f"Missing required field in RDS snapshot data: {e}")


def process_lambda_layer(
    layer_data: Dict[str, Any], region: str
) -> Optional[Dict[str, Any]]:
    """Process Lambda layer data into standardized resource format."""
    try:
        layer_name = layer_data["LayerName"]
        layer_arn = layer_data.get("LayerArn", "")
        arn_parts = layer_arn.split(":")
        account_id = arn_parts[4] if len(arn_parts) > 4 else get_current_account_id()

        latest = layer_data.get("LatestMatchingVersion", {})
        created_at = latest.get("CreatedDate")
        if created_at and isinstance(created_at, str):
            try:
                created_at = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
            except (ValueError, TypeError):
                created_at = None

        return {
            "resource_arn": layer_arn,
            "resource_type": "AWS::Lambda::LayerVersion",
            "service_name": "lambda",
            "region": region,
            "account_id": account_id,
            "resource_id": layer_name,
            "created_at": created_at,
            "current_tags": {},
            "metadata_json": {
                "layer_name": layer_name,
                "latest_version": latest.get("Version"),
                "description": latest.get("Description"),
                "compatible_runtimes": latest.get("CompatibleRuntimes", []),
                "license_info": latest.get("LicenseInfo"),
            },
        }
    except KeyError as e:
        raise ValueError(f"Missing required field in Lambda layer data: {e}")


def process_ecs_task_definition(
    taskdef_data: Dict[str, Any], tag_list: List[Dict[str, str]], region: str
) -> Optional[Dict[str, Any]]:
    """Process ECS task definition data into standardized resource format."""
    try:
        taskdef_arn = taskdef_data["taskDefinitionArn"]
        family = taskdef_data.get("family", "")
        arn_parts = taskdef_arn.split(":")
        account_id = arn_parts[4] if len(arn_parts) > 4 else get_current_account_id()

        tags = {t["key"]: t["value"] for t in tag_list}

        registered_at = taskdef_data.get("registeredAt")
        if registered_at and isinstance(registered_at, str):
            try:
                registered_at = datetime.fromisoformat(
                    registered_at.replace("Z", "+00:00")
                )
            except (ValueError, TypeError):
                registered_at = None

        return {
            "resource_arn": taskdef_arn,
            "resource_type": "AWS::ECS::TaskDefinition",
            "service_name": "ecs",
            "region": region,
            "account_id": account_id,
            "resource_id": f"{family}:{taskdef_data.get('revision', '')}",
            "created_at": registered_at,
            "current_tags": tags,
            "metadata_json": {
                "family": family,
                "revision": taskdef_data.get("revision"),
                "status": taskdef_data.get("status"),
                "cpu": taskdef_data.get("cpu"),
                "memory": taskdef_data.get("memory"),
                "network_mode": taskdef_data.get("networkMode"),
                "container_count": len(taskdef_data.get("containerDefinitions", [])),
            },
        }
    except KeyError as e:
        raise ValueError(f"Missing required field in ECS task definition data: {e}")


def process_sns_topic(
    topic_attrs: Dict[str, Any], tag_list: List[Dict[str, str]], region: str
) -> Optional[Dict[str, Any]]:
    """Process SNS topic data into standardized resource format."""
    try:
        topic_arn = topic_attrs["TopicArn"]
        arn_parts = topic_arn.split(":")
        account_id = arn_parts[4] if len(arn_parts) > 4 else get_current_account_id()
        topic_name = arn_parts[-1] if arn_parts else topic_arn

        tags = {t["Key"]: t["Value"] for t in tag_list}

        return {
            "resource_arn": topic_arn,
            "resource_type": "AWS::SNS::Topic",
            "service_name": "sns",
            "region": region,
            "account_id": account_id,
            "resource_id": topic_name,
            "created_at": None,
            "current_tags": tags,
            "metadata_json": {
                "display_name": topic_attrs.get("DisplayName"),
                "subscriptions_confirmed": topic_attrs.get("SubscriptionsConfirmed"),
                "subscriptions_pending": topic_attrs.get("SubscriptionsPending"),
                "kms_master_key_id": topic_attrs.get("KmsMasterKeyId"),
                "fifo_topic": topic_attrs.get("FifoTopic", "false") == "true",
            },
        }
    except (KeyError, IndexError) as e:
        raise ValueError(f"Missing required field in SNS topic data: {e}")


def process_sqs_queue(
    queue_url: str, queue_attrs: Dict[str, Any], tag_dict: Dict[str, str], region: str
) -> Optional[Dict[str, Any]]:
    """Process SQS queue data into standardized resource format."""
    try:
        queue_arn = queue_attrs["QueueArn"]
        arn_parts = queue_arn.split(":")
        account_id = arn_parts[4] if len(arn_parts) > 4 else get_current_account_id()
        queue_name = arn_parts[-1] if arn_parts else queue_url.split("/")[-1]

        created_at = None
        ts = queue_attrs.get("CreatedTimestamp")
        if ts:
            try:
                created_at = datetime.fromtimestamp(int(ts), tz=timezone.utc)
            except (ValueError, TypeError, OSError):
                pass

        # Build relationships
        relationships = []
        redrive_raw = queue_attrs.get("RedrivePolicy")
        if redrive_raw:
            try:
                redrive = (
                    json.loads(redrive_raw)
                    if isinstance(redrive_raw, str)
                    else redrive_raw
                )
                dlq_arn = redrive.get("deadLetterTargetArn")
                if dlq_arn:
                    relationships.append(
                        {
                            "source_arn": queue_arn,
                            "target_arn": dlq_arn,
                            "relationship_type": "USES",
                            "source_type": "AWS::SQS::Queue",
                            "target_type": "AWS::SQS::Queue",
                            "region": region,
                            "account_id": account_id,
                        }
                    )
            except (ValueError, TypeError):
                pass

        return {
            "resource_arn": queue_arn,
            "resource_type": "AWS::SQS::Queue",
            "service_name": "sqs",
            "region": region,
            "account_id": account_id,
            "resource_id": queue_name,
            "created_at": created_at,
            "current_tags": tag_dict,
            "relationships": relationships,
            "metadata_json": {
                "queue_url": queue_url,
                "approximate_messages": queue_attrs.get("ApproximateNumberOfMessages"),
                "approximate_messages_delayed": queue_attrs.get(
                    "ApproximateNumberOfMessagesDelayed"
                ),
                "visibility_timeout": queue_attrs.get("VisibilityTimeout"),
                "fifo_queue": queue_attrs.get("FifoQueue", "false") == "true",
                "kms_master_key_id": queue_attrs.get("KmsMasterKeyId"),
                "message_retention_period": queue_attrs.get("MessageRetentionPeriod"),
            },
        }
    except (KeyError, IndexError) as e:
        raise ValueError(f"Missing required field in SQS queue data: {e}")


def process_cloudwatch_alarm(
    alarm_data: Dict[str, Any], tag_list: List[Dict[str, str]], region: str
) -> Optional[Dict[str, Any]]:
    """Process CloudWatch alarm data into standardized resource format."""
    try:
        alarm_arn = alarm_data["AlarmArn"]
        alarm_name = alarm_data["AlarmName"]
        arn_parts = alarm_arn.split(":")
        account_id = arn_parts[4] if len(arn_parts) > 4 else get_current_account_id()

        tags = {t["Key"]: t["Value"] for t in tag_list}

        config_updated = alarm_data.get("AlarmConfigurationUpdatedTimestamp")
        if config_updated and isinstance(config_updated, str):
            try:
                config_updated = datetime.fromisoformat(
                    config_updated.replace("Z", "+00:00")
                )
            except (ValueError, TypeError):
                config_updated = None

        # Build relationships
        relationships = []
        for action_arn in alarm_data.get("AlarmActions", []):
            if ":sns:" in action_arn:
                relationships.append(
                    {
                        "source_arn": alarm_arn,
                        "target_arn": action_arn,
                        "relationship_type": "NOTIFIES",
                        "source_type": "AWS::CloudWatch::Alarm",
                        "target_type": "AWS::SNS::Topic",
                        "region": region,
                        "account_id": account_id,
                    }
                )

        return {
            "resource_arn": alarm_arn,
            "resource_type": "AWS::CloudWatch::Alarm",
            "service_name": "cloudwatch",
            "region": region,
            "account_id": account_id,
            "resource_id": alarm_name,
            "created_at": config_updated,
            "current_tags": tags,
            "metadata_json": {
                "namespace": alarm_data.get("Namespace"),
                "metric_name": alarm_data.get("MetricName"),
                "state_value": alarm_data.get("StateValue"),
                "actions_enabled": alarm_data.get("ActionsEnabled"),
                "comparison_operator": alarm_data.get("ComparisonOperator"),
                "threshold": alarm_data.get("Threshold"),
            },
            "relationships": relationships,
        }
    except KeyError as e:
        raise ValueError(f"Missing required field in CloudWatch alarm data: {e}")


def process_log_group(
    log_group_data: Dict[str, Any], tag_dict: Dict[str, str], region: str
) -> Optional[Dict[str, Any]]:
    """Process CloudWatch Log Group data into standardized resource format."""
    try:
        log_group_name = log_group_data["logGroupName"]
        log_group_arn = log_group_data.get("arn", "")
        # ARN ends with :* for log groups, strip it
        if log_group_arn.endswith(":*"):
            log_group_arn = log_group_arn[:-2]
        arn_parts = log_group_arn.split(":")
        account_id = arn_parts[4] if len(arn_parts) > 4 else get_current_account_id()

        created_at = None
        ts = log_group_data.get("creationTime")
        if ts:
            try:
                created_at = datetime.fromtimestamp(int(ts) / 1000, tz=timezone.utc)
            except (ValueError, TypeError, OSError):
                pass

        return {
            "resource_arn": log_group_arn,
            "resource_type": "AWS::Logs::LogGroup",
            "service_name": "logs",
            "region": region,
            "account_id": account_id,
            "resource_id": log_group_name,
            "created_at": created_at,
            "current_tags": tag_dict,
            "metadata_json": {
                "retention_days": log_group_data.get("retentionInDays"),
                "stored_bytes": log_group_data.get("storedBytes"),
                "metric_filter_count": log_group_data.get("metricFilterCount"),
                "kms_key_id": log_group_data.get("kmsKeyId"),
            },
        }
    except KeyError as e:
        raise ValueError(f"Missing required field in CloudWatch Log Group data: {e}")


def process_eks_cluster(
    cluster_data: Dict[str, Any], region: str
) -> Optional[Dict[str, Any]]:
    """Process EKS cluster data into standardized resource format."""
    try:
        cluster_name = cluster_data["name"]
        cluster_arn = cluster_data.get("arn", "")
        arn_parts = cluster_arn.split(":")
        account_id = arn_parts[4] if len(arn_parts) > 4 else get_current_account_id()

        tags = cluster_data.get("tags", {})

        created_at = cluster_data.get("createdAt")
        if created_at and isinstance(created_at, str):
            try:
                created_at = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
            except (ValueError, TypeError):
                created_at = None

        # Build relationships
        relationships = []
        role_arn = cluster_data.get("roleArn")
        if role_arn:
            relationships.append(
                {
                    "source_arn": cluster_arn,
                    "target_arn": role_arn,
                    "relationship_type": "USES",
                    "source_type": "AWS::EKS::Cluster",
                    "target_type": "AWS::IAM::Role",
                    "region": region,
                    "account_id": account_id,
                }
            )
        resources_vpc = cluster_data.get("resourcesVpcConfig", {})
        for subnet_id in resources_vpc.get("subnetIds", []):
            relationships.append(
                {
                    "source_arn": cluster_arn,
                    "target_arn": _ec2_arn(region, account_id, "subnet", subnet_id),
                    "relationship_type": "RUNS_IN",
                    "source_type": "AWS::EKS::Cluster",
                    "target_type": "AWS::EC2::Subnet",
                    "region": region,
                    "account_id": account_id,
                }
            )
        for sg_id in resources_vpc.get("securityGroupIds", []):
            relationships.append(
                {
                    "source_arn": cluster_arn,
                    "target_arn": _ec2_arn(region, account_id, "security-group", sg_id),
                    "relationship_type": "USES",
                    "source_type": "AWS::EKS::Cluster",
                    "target_type": "AWS::EC2::SecurityGroup",
                    "region": region,
                    "account_id": account_id,
                }
            )
        cluster_sg = resources_vpc.get("clusterSecurityGroupId")
        if cluster_sg:
            relationships.append(
                {
                    "source_arn": cluster_arn,
                    "target_arn": _ec2_arn(
                        region, account_id, "security-group", cluster_sg
                    ),
                    "relationship_type": "USES",
                    "source_type": "AWS::EKS::Cluster",
                    "target_type": "AWS::EC2::SecurityGroup",
                    "region": region,
                    "account_id": account_id,
                }
            )

        return {
            "resource_arn": cluster_arn,
            "resource_type": "AWS::EKS::Cluster",
            "service_name": "eks",
            "region": region,
            "account_id": account_id,
            "resource_id": cluster_name,
            "created_at": created_at,
            "current_tags": tags,
            "metadata_json": {
                "status": cluster_data.get("status"),
                "version": cluster_data.get("version"),
                "platform_version": cluster_data.get("platformVersion"),
                "endpoint": cluster_data.get("endpoint"),
            },
            "relationships": relationships,
        }
    except KeyError as e:
        raise ValueError(f"Missing required field in EKS cluster data: {e}")


def process_elasticache_cluster(
    cluster_data: Dict[str, Any], tag_list: List[Dict[str, str]], region: str
) -> Optional[Dict[str, Any]]:
    """Process ElastiCache cluster data into standardized resource format."""
    try:
        cluster_id = cluster_data["CacheClusterId"]
        cluster_arn = cluster_data.get("ARN", "")
        arn_parts = cluster_arn.split(":")
        account_id = arn_parts[4] if len(arn_parts) > 4 else get_current_account_id()

        tags = {t["Key"]: t["Value"] for t in tag_list}

        created_at = cluster_data.get("CacheClusterCreateTime")
        if created_at and isinstance(created_at, str):
            try:
                created_at = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
            except (ValueError, TypeError):
                created_at = None

        # Build relationships
        relationships = []
        for sg in cluster_data.get("SecurityGroups", []):
            sg_id = sg.get("SecurityGroupId")
            if sg_id:
                relationships.append(
                    {
                        "source_arn": cluster_arn,
                        "target_arn": _ec2_arn(
                            region, account_id, "security-group", sg_id
                        ),
                        "relationship_type": "USES",
                        "source_type": "AWS::ElastiCache::CacheCluster",
                        "target_type": "AWS::EC2::SecurityGroup",
                        "region": region,
                        "account_id": account_id,
                    }
                )

        return {
            "resource_arn": cluster_arn,
            "resource_type": "AWS::ElastiCache::CacheCluster",
            "service_name": "elasticache",
            "region": region,
            "account_id": account_id,
            "resource_id": cluster_id,
            "created_at": created_at,
            "current_tags": tags,
            "metadata_json": {
                "engine": cluster_data.get("Engine"),
                "engine_version": cluster_data.get("EngineVersion"),
                "cache_node_type": cluster_data.get("CacheNodeType"),
                "num_cache_nodes": cluster_data.get("NumCacheNodes"),
                "status": cluster_data.get("CacheClusterStatus"),
            },
            "relationships": relationships,
        }
    except KeyError as e:
        raise ValueError(f"Missing required field in ElastiCache cluster data: {e}")


def process_vpc(vpc_data: Dict[str, Any], region: str) -> Optional[Dict[str, Any]]:
    """Process VPC data into standardized resource format."""
    try:
        vpc_id = vpc_data["VpcId"]
        account_id = vpc_data.get("OwnerId") or get_current_account_id()

        tags = {}
        for tag in vpc_data.get("Tags", []):
            tags[tag["Key"]] = tag["Value"]

        return {
            "resource_arn": f"arn:aws:ec2:{region}:{account_id}:vpc/{vpc_id}",
            "resource_type": "AWS::EC2::VPC",
            "service_name": "vpc",
            "region": region,
            "account_id": account_id,
            "resource_id": vpc_id,
            "created_at": None,
            "current_tags": tags,
            "lifecycle_state": "infrastructure",
            "metadata_json": {
                "cidr_block": vpc_data.get("CidrBlock"),
                "is_default": vpc_data.get("IsDefault", False),
                "state": vpc_data.get("State"),
                "dhcp_options_id": vpc_data.get("DhcpOptionsId"),
            },
        }
    except KeyError as e:
        raise ValueError(f"Missing required field in VPC data: {e}")


def process_subnet(
    subnet_data: Dict[str, Any], region: str
) -> Optional[Dict[str, Any]]:
    """Process Subnet data into standardized resource format."""
    try:
        subnet_id = subnet_data["SubnetId"]
        account_id = subnet_data.get("OwnerId") or get_current_account_id()
        vpc_id = subnet_data.get("VpcId")

        tags = {}
        for tag in subnet_data.get("Tags", []):
            tags[tag["Key"]] = tag["Value"]

        relationships = []
        if vpc_id:
            relationships.append(
                {
                    "source_arn": f"arn:aws:ec2:{region}:{account_id}:subnet/{subnet_id}",
                    "target_arn": _ec2_arn(region, account_id, "vpc", vpc_id),
                    "relationship_type": "BELONGS_TO",
                    "source_type": "AWS::EC2::Subnet",
                    "target_type": "AWS::EC2::VPC",
                    "region": region,
                    "account_id": account_id,
                }
            )

        return {
            "resource_arn": f"arn:aws:ec2:{region}:{account_id}:subnet/{subnet_id}",
            "resource_type": "AWS::EC2::Subnet",
            "service_name": "vpc",
            "region": region,
            "account_id": account_id,
            "resource_id": subnet_id,
            "created_at": None,
            "current_tags": tags,
            "lifecycle_state": "infrastructure",
            "metadata_json": {
                "cidr_block": subnet_data.get("CidrBlock"),
                "availability_zone": subnet_data.get("AvailabilityZone"),
                "map_public_ip_on_launch": subnet_data.get(
                    "MapPublicIpOnLaunch", False
                ),
                "available_ip_count": subnet_data.get("AvailableIpAddressCount"),
                "vpc_id": vpc_id,
            },
            "relationships": relationships,
        }
    except KeyError as e:
        raise ValueError(f"Missing required field in Subnet data: {e}")


def process_security_group(
    sg_data: Dict[str, Any], region: str
) -> Optional[Dict[str, Any]]:
    """Process Security Group data into standardized resource format."""
    try:
        sg_id = sg_data["GroupId"]
        account_id = sg_data.get("OwnerId") or get_current_account_id()
        vpc_id = sg_data.get("VpcId")

        tags = {}
        for tag in sg_data.get("Tags", []):
            tags[tag["Key"]] = tag["Value"]

        relationships = []
        if vpc_id:
            relationships.append(
                {
                    "source_arn": _ec2_arn(region, account_id, "security-group", sg_id),
                    "target_arn": _ec2_arn(region, account_id, "vpc", vpc_id),
                    "relationship_type": "BELONGS_TO",
                    "source_type": "AWS::EC2::SecurityGroup",
                    "target_type": "AWS::EC2::VPC",
                    "region": region,
                    "account_id": account_id,
                }
            )

        return {
            "resource_arn": _ec2_arn(region, account_id, "security-group", sg_id),
            "resource_type": "AWS::EC2::SecurityGroup",
            "service_name": "vpc",
            "region": region,
            "account_id": account_id,
            "resource_id": sg_id,
            "created_at": None,
            "current_tags": tags,
            "lifecycle_state": "infrastructure",
            "metadata_json": {
                "group_name": sg_data.get("GroupName"),
                "description": sg_data.get("Description"),
                "vpc_id": vpc_id,
                "inbound_rules_count": len(sg_data.get("IpPermissions", [])),
                "outbound_rules_count": len(sg_data.get("IpPermissionsEgress", [])),
            },
            "relationships": relationships,
        }
    except KeyError as e:
        raise ValueError(f"Missing required field in Security Group data: {e}")


def process_iam_role(role_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Process IAM Role data into standardized resource format."""
    try:
        role_name = role_data["RoleName"]
        role_arn = role_data["Arn"]
        arn_parts = role_arn.split(":")
        account_id = arn_parts[4] if len(arn_parts) > 4 else get_current_account_id()

        tags = {}
        for tag in role_data.get("Tags", []):
            tags[tag["Key"]] = tag["Value"]

        created_at = role_data.get("CreateDate")
        if created_at and isinstance(created_at, str):
            try:
                created_at = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
            except (ValueError, TypeError):
                created_at = None

        return {
            "resource_arn": role_arn,
            "resource_type": "AWS::IAM::Role",
            "service_name": "iam",
            "region": "global",
            "account_id": account_id,
            "resource_id": role_name,
            "created_at": created_at,
            "current_tags": tags,
            "lifecycle_state": "infrastructure",
            "metadata_json": {
                "role_name": role_name,
                "path": role_data.get("Path"),
                "description": role_data.get("Description", ""),
                "max_session_duration": role_data.get("MaxSessionDuration"),
            },
        }
    except KeyError as e:
        raise ValueError(f"Missing required field in IAM Role data: {e}")


def _sync_ttl_from_aws_tags(resource_data: Dict[str, Any]):
    """Sync TTL/expires_at from AWS tags if present.

    Checks for bluearch:ttl tag and sets expires_at accordingly.
    This ensures resources with existing TTL tags retain their expiration.
    """
    tags = resource_data.get("current_tags", {})
    if isinstance(tags, str):
        try:
            import json

            tags = json.loads(tags)
        except (json.JSONDecodeError, TypeError):
            tags = {}

    ttl_tag = tags.get("bluearch:ttl")
    policy_source_tag = tags.get("bluearch:policy-source")

    if ttl_tag:
        try:
            # Parse the TTL date (format: YYYY-MM-DD)
            from datetime import datetime, timezone

            expires_at = datetime.strptime(ttl_tag, "%Y-%m-%d").replace(
                tzinfo=timezone.utc
            )
            resource_data["expires_at"] = expires_at

            # Set policy source if present
            if policy_source_tag:
                resource_data["policy_source"] = policy_source_tag

            # Set lifecycle state based on expiration
            now = datetime.now(timezone.utc)
            if expires_at <= now:
                resource_data["lifecycle_state"] = "expired"
            else:
                resource_data["lifecycle_state"] = "active"

        except (ValueError, TypeError):
            # Invalid date format, skip TTL sync
            pass


def store_resource(resource_data: Dict[str, Any]):
    """Store or update resource in database.

    Args:
        resource_data: Standardized resource dictionary
    """
    # Sync TTL from AWS tags if present
    _sync_ttl_from_aws_tags(resource_data)

    try:
        payload = resource_payload(resource_data)
        if not payload.get("resource_arn"):
            return
        upsert_by_filter(
            "core",
            "resources",
            filters=[("resource_arn", payload["resource_arn"])],
            payload=payload,
        )
    except Exception as e:
        console.print(
            f"[red]Error storing resource {resource_data.get('resource_arn', 'unknown')}: {e}[/red]"
        )


def discover_all_resources_v2(
    services: List[str],
    regions: List[str],
    console: Console,
    required_tags: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """V2 discovery using CollectionEngine for improved performance.

    Drop-in replacement for discover_all_resources_with_tree() with:
    - Batch DB writes (1 txn per 100 resources instead of per-resource)
    - Per-region throttling to avoid API rate limits
    - Parallel S3 bucket location lookups
    - Per-service/region progress display
    - Smart job scheduling (slow services first)

    Args:
        services: List of services to discover
        regions: List of regions to scan
        console: Rich console for display
        required_tags: Optional list of required tag keys

    Returns:
        Dictionary with discovery statistics including compliance data
    """
    from .collection.engine import CollectionEngine

    engine = CollectionEngine(
        services=services,
        regions=regions,
        console=console,
        required_tags=required_tags,
    )
    result = engine.run()
    return result.to_summary_dict()
