"""Core tag management commands backed by bluearch-core inventory."""

from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import typer
from rich.console import Console
from rich.panel import Panel
from rich.progress import BarColumn, Progress, SpinnerColumn, TaskProgressColumn, TextColumn
from rich.prompt import Confirm, Prompt
from rich.table import Table

from ..utils.aws_auth import aws_auth
from ..utils.core_client import request_core

console = Console()
tag_mgmt_app = typer.Typer(help="Core tag management and resource tagging commands")

COMMON_REQUIRED_TAGS = ["Environment", "Owner", "CostCenter"]


@tag_mgmt_app.command("scan")
def scan_untagged_resources(
    services: Optional[str] = typer.Option(None, "--services", "-s", help="Comma-separated services (ec2,s3,lambda)"),
    regions: Optional[str] = typer.Option(None, "--regions", "-r", help="Comma-separated regions"),
    required_tags: Optional[str] = typer.Option("Environment,Owner,CostCenter", "--required-tags", help="Comma-separated required tag keys"),
    min_age_hours: int = typer.Option(0, "--min-age", help="Only show resources older than N hours"),
    limit: int = typer.Option(100, "--limit", help="Maximum resources to show"),
):
    """Scan for resources missing required tags."""
    try:
        console.print("[blue][SEARCH] Scanning for untagged resources...[/blue]")
        required_tag_list = _csv(required_tags) or COMMON_REQUIRED_TAGS
        resources = _filter_resources(
            services=_csv(services),
            regions=_csv(regions),
            min_age_hours=min_age_hours,
            limit=limit * 2,
        )
        untagged_resources = _missing_tag_rows(resources, required_tag_list, limit)

        if not untagged_resources:
            console.print("[green]OK All resources have required tags![/green]")
            return

        table = Table(title=f"Untagged Resources ({len(untagged_resources)} found)", show_header=True, header_style="bold magenta")
        table.add_column("Service", style="cyan", width=10)
        table.add_column("Resource ID", style="white", width=25)
        table.add_column("Region", style="yellow", width=12)
        table.add_column("Age", style="dim", width=8)
        table.add_column("Current Tags", style="green", width=8, justify="center")
        table.add_column("Missing Tags", style="red", width=20)
        table.add_column("Actions", style="blue", width=15)

        for item in untagged_resources:
            resource = item["resource"]
            table.add_row(
                str(resource.get("service_name") or "").upper(),
                resource.get("resource_id") or "-",
                resource.get("region") or "-",
                _resource_age(resource),
                str(item["tag_count"]),
                ", ".join(item["missing_tags"]),
                "tag, skip, view",
            )

        console.print(table)
        console.print("\n[bold]Summary:[/bold]")
        console.print(f"- Found [red]{len(untagged_resources)}[/red] resources missing required tags")
        console.print(f"- Required tags: [yellow]{', '.join(required_tag_list)}[/yellow]")
        console.print("\n[bold blue]Next Steps:[/bold blue]")
        console.print("1. Tag resources interactively: [cyan]bluearch-aws-tags tag interactive[/cyan]")
        console.print("2. Apply automatic rules: [cyan]bluearch-aws-tags tag auto-apply[/cyan]")
        console.print("3. Bulk tag by service: [cyan]bluearch-aws-tags tag bulk --service ec2[/cyan]")
    except Exception as exc:
        console.print(f"[red]Error scanning resources: {exc}[/red]")
        raise typer.Exit(1)


@tag_mgmt_app.command("interactive")
def interactive_tagging(
    services: Optional[str] = typer.Option(None, "--services", "-s", help="Filter by services"),
    max_resources: int = typer.Option(20, "--limit", help="Maximum resources to process"),
):
    """Interactively tag untagged resources."""
    try:
        console.print("[blue][TAG] Interactive Resource Tagging[/blue]")
        console.print("[dim]You'll be prompted to tag each untagged resource[/dim]\n")
        resources = _filter_resources(services=_csv(services), limit=max_resources * 2)
        untagged = [row["resource"] for row in _missing_tag_rows(resources, COMMON_REQUIRED_TAGS, max_resources)]

        if not untagged:
            console.print("[green]OK No untagged resources found![/green]")
            return

        console.print(f"Found [yellow]{len(untagged)}[/yellow] resources to tag\n")
        tagged_count = 0
        skipped_count = 0

        for index, resource in enumerate(untagged, 1):
            console.print(_resource_panel(resource, index, len(untagged)))
            action = Prompt.ask("What would you like to do?", choices=["tag", "skip", "view", "quit"], default="tag")
            if action == "quit":
                break
            if action == "skip":
                skipped_count += 1
                continue
            if action == "view":
                console.print(json.dumps(resource, indent=2, default=str))
                continue
            if interactive_tag_resource(resource):
                tagged_count += 1
            console.print()

        console.print("\n[bold green]OK Tagging Session Complete[/bold green]")
        console.print(f"- Tagged: [green]{tagged_count}[/green] resources")
        console.print(f"- Skipped: [yellow]{skipped_count}[/yellow] resources")
    except Exception as exc:
        console.print(f"[red]Error in interactive tagging: {exc}[/red]")
        raise typer.Exit(1)


def interactive_tag_resource(resource: dict[str, Any]) -> bool:
    """Interactively tag a single resource."""
    try:
        console.print(f"[bold]Tagging {resource.get('resource_id')}[/bold]")
        new_tags: dict[str, str] = {}
        current_tags = resource.get("current_tags") or {}

        for tag_key in ["Environment", "Owner", "CostCenter", "Project", "Application"]:
            if tag_key in current_tags:
                console.print(f"  {tag_key}: [dim]{current_tags[tag_key]} (already set)[/dim]")
                continue
            suggestions = get_tag_suggestions(tag_key, resource)
            suggestion_text = f" (suggestions: {', '.join(suggestions[:3])})" if suggestions else ""
            value = Prompt.ask(f"  [cyan]{tag_key}[/cyan]{suggestion_text}", default="")
            if value:
                new_tags[tag_key] = value

        while Confirm.ask("Add more custom tags?", default=False):
            key = Prompt.ask("Tag key", default="")
            if not key:
                break
            value = Prompt.ask(f"Value for '{key}'", default="")
            if value:
                new_tags[key] = value

        if not new_tags:
            console.print("[yellow]No tags specified, skipping[/yellow]")
            return False

        console.print("\n[bold]Tags to apply:[/bold]")
        for key, value in new_tags.items():
            console.print(f"  [cyan]{key}[/cyan] = [white]{value}[/white]")
        if not Confirm.ask("\nApply these tags?", default=True):
            return False

        return _apply_and_record_tags(resource, new_tags, operation="interactive")
    except Exception as exc:
        console.print(f"[red]Error tagging resource: {exc}[/red]")
        return False


def get_tag_suggestions(tag_key: str, resource: dict[str, Any]) -> list[str]:
    """Get tag value suggestions based on tag key and resource context."""
    resource_id = str(resource.get("resource_id") or "").lower()
    current_tags = resource.get("current_tags") or {}

    if tag_key == "Environment":
        if "prod" in resource_id:
            return ["production"]
        if "dev" in resource_id:
            return ["development"]
        if "test" in resource_id:
            return ["testing"]
        if "stage" in resource_id:
            return ["staging"]
        return ["production", "development", "staging", "testing"]
    if tag_key == "Owner":
        suggestions = []
        if "CreatedBy" in current_tags:
            suggestions.append(current_tags["CreatedBy"])
        suggestions.extend(["team-platform", "team-data", "team-frontend"])
        return suggestions
    if tag_key == "CostCenter":
        return ["engineering", "operations", "data-science", "marketing"]
    if tag_key == "Project":
        name_parts = resource_id.split("-")
        suggestions = [f"{name_parts[0]}-{name_parts[1]}"] if len(name_parts) >= 2 else []
        suggestions.extend(["web-app", "data-pipeline", "ml-platform"])
        return suggestions
    if tag_key == "Application":
        return ["web-server", "database", "api", "worker", "cache"]
    return []


@tag_mgmt_app.command("bulk")
def bulk_tag_resources(
    service: str = typer.Argument(..., help="Service to tag (ec2, s3, lambda)"),
    region: Optional[str] = typer.Option(None, "--region", "-r", help="Specific region"),
    tag_key: str = typer.Option(..., "--tag-key", "-k", help="Tag key to apply"),
    tag_value: str = typer.Option(..., "--tag-value", "-v", help="Tag value to apply"),
    filter_untagged: bool = typer.Option(True, "--filter-untagged", help="Only tag resources missing this tag"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Show what would be tagged without applying"),
    max_resources: int = typer.Option(50, "--limit", help="Maximum resources to process"),
):
    """Bulk tag resources by service."""
    try:
        console.print(f"[blue][TAG] Bulk tagging {service.upper()} resources[/blue]")
        if dry_run:
            console.print("[yellow]DRY RUN MODE - No changes will be applied[/yellow]")

        resources = _filter_resources(services=[service], regions=[region] if region else None, limit=max_resources * 2)
        target_resources = []
        for resource in resources:
            current_tags = resource.get("current_tags") or {}
            if filter_untagged and tag_key in current_tags:
                continue
            target_resources.append(resource)
            if len(target_resources) >= max_resources:
                break

        if not target_resources:
            console.print("[yellow]No resources found to tag[/yellow]")
            return

        console.print(f"\nWill apply tag [cyan]{tag_key}[/cyan]=[white]{tag_value}[/white] to {len(target_resources)} resources:")
        preview_table = Table(show_header=True, header_style="bold magenta")
        preview_table.add_column("Service", style="cyan")
        preview_table.add_column("Resource ID", style="white")
        preview_table.add_column("Region", style="yellow")
        preview_table.add_column("Current Tags", style="green", justify="center")
        for resource in target_resources[:10]:
            preview_table.add_row(
                str(resource.get("service_name") or "").upper(),
                resource.get("resource_id") or "-",
                resource.get("region") or "-",
                str(len(resource.get("current_tags") or {})),
            )
        if len(target_resources) > 10:
            preview_table.add_row("...", f"and {len(target_resources) - 10} more", "...", "...")
        console.print(preview_table)

        if dry_run:
            console.print(f"\n[dim]Would tag {len(target_resources)} resources[/dim]")
            return
        if not Confirm.ask(f"\nProceed to tag {len(target_resources)} resources?", default=True):
            console.print("[yellow]Operation cancelled[/yellow]")
            return

        success_count = 0
        failed_count = 0
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TaskProgressColumn(),
            console=console,
        ) as progress:
            task = progress.add_task("Applying tags...", total=len(target_resources))
            for resource in target_resources:
                progress.update(task, description=f"Tagging {resource.get('resource_id')}")
                if _apply_and_record_tags(resource, {tag_key: tag_value}, operation="bulk"):
                    success_count += 1
                else:
                    failed_count += 1
                progress.advance(task)

        console.print("\n[bold green]OK Bulk tagging complete[/bold green]")
        console.print(f"- Successfully tagged: [green]{success_count}[/green] resources")
        if failed_count:
            console.print(f"- Failed: [red]{failed_count}[/red] resources")
    except Exception as exc:
        console.print(f"[red]Error in bulk tagging: {exc}[/red]")
        raise typer.Exit(1)


@tag_mgmt_app.command("auto-apply")
def auto_apply_rules(
    services: Optional[str] = typer.Option(None, "--services", "-s", help="Filter by services"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Show what would be tagged"),
    max_resources: int = typer.Option(100, "--limit", help="Maximum resources to process"),
):
    """Plan automatic tagging rules against core inventory."""
    try:
        console.print("[blue][AUTO] Applying automatic tagging rules[/blue]")
        if dry_run:
            console.print("[yellow]DRY RUN MODE - No changes will be applied[/yellow]")

        resources = _filter_resources(services=_csv(services), limit=max_resources)
        rules = _list_storage("tagging-rules", filters=[("enabled", "true")], limit=10000, order_by="priority", descending=False)

        if not resources:
            console.print("[yellow]No resources found[/yellow]")
            return
        console.print(f"[dim]Would process {len(resources)} resources with automatic rules[/dim]")
        console.print(f"\nActive rules: [green]{len(rules)}[/green]")
        for rule in rules[:5]:
            console.print(f"  - [cyan]{rule.get('name')}[/cyan] - {len(rule.get('resource_types') or [])} resource types")

        if not dry_run:
            execution = _create_storage(
                "tagging-executions",
                {
                    "execution_type": "auto_apply",
                    "description": "Automatic tagging requested from CLI",
                    "initiated_by": "cli",
                    "initiated_via": "tag-manager-cli",
                    "status": "blocked_pending_worker_migration",
                    "total_resources": len(resources),
                    "metadata": {
                        "services": _csv(services) or [],
                        "reason": "Automatic rule execution worker migration is still pending",
                    },
                },
            )
            console.print(
                "[yellow]Automatic tag mutation worker migration is still pending; "
                f"recorded execution {execution.get('id')} for audit.[/yellow]"
            )
    except Exception as exc:
        console.print(f"[red]Error applying automatic rules: {exc}[/red]")
        raise typer.Exit(1)


@tag_mgmt_app.command("report")
def generate_tagging_report(
    output_file: Optional[str] = typer.Option(None, "--output", "-o", help="Save report to file"),
    format_type: str = typer.Option("table", "--format", help="Output format: table, json, csv"),
):
    """Generate a comprehensive tagging compliance report."""
    try:
        console.print("[blue][CHART] Generating tagging compliance report...[/blue]")
        resources = _list_resources()
        report_data = analyze_tagging_compliance(resources)

        if format_type == "table":
            display_compliance_table(report_data)
        elif format_type == "json":
            console.print(json.dumps(report_data, indent=2, default=str))
        else:
            console.print(json.dumps(report_data, indent=2, default=str))

        if output_file:
            with open(output_file, "w", encoding="utf-8") as handle:
                if format_type == "json":
                    json.dump(report_data, handle, indent=2, default=str)
                else:
                    handle.write("Tagging Compliance Report\n")
                    handle.write(f"Generated: {datetime.now(timezone.utc)}\n")
                    handle.write(json.dumps(report_data, default=str))
            console.print(f"[green]OK[/green] Report saved to {output_file}")
    except Exception as exc:
        console.print(f"[red]Error generating report: {exc}[/red]")
        raise typer.Exit(1)


def analyze_tagging_compliance(resources: list[dict[str, Any]]) -> dict[str, Any]:
    """Analyze resources for tagging compliance."""
    report = {
        "summary": {
            "total_resources": len(resources),
            "fully_tagged": 0,
            "partially_tagged": 0,
            "untagged": 0,
            "compliance_rate": 0,
        },
        "by_service": {},
        "missing_tags": {},
        "generated_at": datetime.now(timezone.utc),
    }

    for resource in resources:
        current_tags = resource.get("current_tags") or {}
        missing_tags = [tag for tag in COMMON_REQUIRED_TAGS if tag not in current_tags]
        if not missing_tags:
            report["summary"]["fully_tagged"] += 1
        elif len(missing_tags) < len(COMMON_REQUIRED_TAGS):
            report["summary"]["partially_tagged"] += 1
        else:
            report["summary"]["untagged"] += 1

        service = resource.get("service_name") or "unknown"
        report["by_service"].setdefault(service, {"total": 0, "fully_tagged": 0, "compliance_rate": 0})
        report["by_service"][service]["total"] += 1
        if not missing_tags:
            report["by_service"][service]["fully_tagged"] += 1
        for tag in missing_tags:
            report["missing_tags"][tag] = report["missing_tags"].get(tag, 0) + 1

    total = report["summary"]["total_resources"]
    if total:
        report["summary"]["compliance_rate"] = round((report["summary"]["fully_tagged"] / total) * 100, 1)
    for service_data in report["by_service"].values():
        if service_data["total"]:
            service_data["compliance_rate"] = round((service_data["fully_tagged"] / service_data["total"]) * 100, 1)
    return report


def display_compliance_table(report: dict[str, Any]) -> None:
    """Display compliance report as formatted tables."""
    summary = report["summary"]
    total = summary["total_resources"]
    summary_table = Table(title="Tagging Compliance Summary", show_header=True, header_style="bold magenta")
    summary_table.add_column("Metric", style="white", width=20)
    summary_table.add_column("Count", style="cyan", justify="right", width=10)
    summary_table.add_column("Percentage", style="green", justify="right", width=12)
    summary_table.add_row("Total Resources", str(total), "100.0%")
    summary_table.add_row("Fully Tagged", str(summary["fully_tagged"]), f"{summary['compliance_rate']:.1f}%")
    summary_table.add_row("Partially Tagged", str(summary["partially_tagged"]), _pct(summary["partially_tagged"], total))
    summary_table.add_row("Untagged", str(summary["untagged"]), _pct(summary["untagged"], total))
    console.print(summary_table)

    if report["by_service"]:
        service_table = Table(title="Compliance by Service", show_header=True, header_style="bold magenta")
        service_table.add_column("Service", style="cyan", width=15)
        service_table.add_column("Total", style="white", justify="right", width=8)
        service_table.add_column("Tagged", style="green", justify="right", width=8)
        service_table.add_column("Compliance", style="yellow", justify="right", width=12)
        for service, data in sorted(report["by_service"].items()):
            service_table.add_row(service.upper(), str(data["total"]), str(data["fully_tagged"]), f"{data['compliance_rate']:.1f}%")
        console.print(service_table)

    if report["missing_tags"]:
        console.print("\n[bold red]Most Common Missing Tags:[/bold red]")
        for tag, count in sorted(report["missing_tags"].items(), key=lambda item: item[1], reverse=True):
            console.print(f"  - [red]{tag}[/red]: {count} resources")


def _filter_resources(
    *,
    services: Optional[list[str]] = None,
    regions: Optional[list[str]] = None,
    min_age_hours: int = 0,
    limit: Optional[int] = None,
) -> list[dict[str, Any]]:
    resources = _list_resources()
    if services:
        wanted = {service.lower() for service in services}
        resources = [
            resource
            for resource in resources
            if str(resource.get("service_name") or "").lower() in wanted
        ]
    if regions:
        wanted_regions = {region.lower() for region in regions}
        resources = [
            resource
            for resource in resources
            if str(resource.get("region") or "").lower() in wanted_regions
        ]
    if min_age_hours > 0:
        cutoff = datetime.now(timezone.utc) - timedelta(hours=min_age_hours)
        resources = [resource for resource in resources if (_parse_time(resource.get("created_at")) or datetime.now(timezone.utc)) <= cutoff]
    resources.sort(key=lambda row: _parse_time(row.get("created_at")) or datetime.min.replace(tzinfo=timezone.utc), reverse=True)
    return resources[:limit] if limit else resources


def _missing_tag_rows(resources: list[dict[str, Any]], required_tags: list[str], limit: int) -> list[dict[str, Any]]:
    rows = []
    for resource in resources:
        current_tags = resource.get("current_tags") or {}
        missing_tags = [tag for tag in required_tags if tag not in current_tags]
        if missing_tags:
            rows.append({"resource": resource, "missing_tags": missing_tags, "tag_count": len(current_tags)})
        if len(rows) >= limit:
            break
    return rows


def _list_resources() -> list[dict[str, Any]]:
    rows = _list_storage("resources", namespace="core", limit=10000, order_by="last_scanned_at")
    return rows


def _list_storage(
    collection: str,
    *,
    namespace: str = "tag-manager",
    filters: list[tuple[str, str]] | None = None,
    limit: int = 100,
    order_by: str | None = None,
    descending: bool = True,
) -> list[dict[str, Any]]:
    params: list[tuple[str, str | int]] = [("limit", limit), ("descending", str(descending).lower())]
    if order_by:
        params.append(("order_by", order_by))
    for field, value in filters or []:
        params.append(("filter", f"{field}={value}"))
    records = request_core(
        "GET",
        f"/api/v1/storage/{namespace}/{collection}",
        service_token=True,
        params=params,
        timeout=10.0,
    )
    return [record.get("payload", record) for record in records or []]


def _create_storage(collection: str, payload: dict[str, Any], *, namespace: str = "tag-manager") -> dict[str, Any]:
    record = request_core(
        "POST",
        f"/api/v1/storage/{namespace}/{collection}",
        service_token=True,
        json={"payload": _jsonable(payload)},
        timeout=10.0,
    )
    return record.get("payload", record)


def _update_storage(collection: str, record_key: str, payload: dict[str, Any], *, namespace: str = "tag-manager") -> dict[str, Any]:
    record = request_core(
        "PUT",
        f"/api/v1/storage/{namespace}/{collection}/{record_key}",
        service_token=True,
        json={"payload": _jsonable(payload)},
        timeout=10.0,
    )
    return record.get("payload", record)


def _apply_and_record_tags(resource: dict[str, Any], tags: dict[str, str], *, operation: str) -> bool:
    resource_arn = resource.get("resource_arn")
    if not resource_arn:
        console.print("[red]ERROR Resource ARN missing[/red]")
        return False

    old_tags = dict(resource.get("current_tags") or {})
    success = _apply_tags_to_aws_resource(resource_arn, tags, resource.get("region"))
    if success:
        updated_tags = dict(old_tags)
        updated_tags.update(tags)
        resource["current_tags"] = updated_tags
        if resource.get("id"):
            _update_storage("resources", resource["id"], resource, namespace="core")
        console.print("[green]OK Tags applied successfully![/green]")
    else:
        console.print("[red]ERROR Failed to apply tags[/red]")

    _create_storage(
        "tagging-audit-log",
        {
            "resource_arn": resource_arn,
            "resource_id": resource.get("id"),
            "operation": operation,
            "old_tags": old_tags,
            "new_tags": tags,
            "principal_info": {"source": "tag-manager-cli"},
            "success": success,
            "error_message": None if success else "tag_resources failed",
            "executed_at": datetime.now(timezone.utc),
        },
    )
    return success


def _apply_tags_to_aws_resource(resource_arn: str, tags: dict[str, str], region: Optional[str]) -> bool:
    try:
        target_region = region or _region_from_arn(resource_arn) or os.environ.get("AWS_REGION") or "us-east-1"
        client = aws_auth.get_client("resourcegroupstaggingapi", region=target_region)
        response = client.tag_resources(ResourceARNList=[resource_arn], Tags=tags)
        failed = response.get("FailedResourcesMap") or {}
        if failed:
            err = next(iter(failed.values()), {})
            console.print(f"[red]tag_resources failed: {err.get('ErrorMessage', 'unknown error')}[/red]")
            return False
        return True
    except Exception as exc:
        console.print(f"[red]Error applying tags to {resource_arn}: {exc}[/red]")
        return False


def _resource_panel(resource: dict[str, Any], index: int, total: int) -> Panel:
    current_tags = resource.get("current_tags") or {}
    panel_content = f"""
[bold cyan]{str(resource.get('service_name') or '').upper()}[/bold cyan] | [white]{resource.get('resource_id') or '-'}[/white] | [yellow]{resource.get('region') or '-'}[/yellow]
[dim]ARN: {resource.get('resource_arn') or '-'}[/dim]
[dim]Created: {_format_time(resource.get('created_at'))}[/dim]

Current tags: [green]{len(current_tags)} tags[/green]
"""
    if current_tags:
        tag_display = [f"[cyan]{key}[/cyan]=[white]{value}[/white]" for key, value in current_tags.items()]
        panel_content += f"Tags: {', '.join(tag_display)}"
    return Panel(panel_content, title=f"Resource {index}/{total}", border_style="blue")


def _resource_age(resource: dict[str, Any]) -> str:
    created_at = _parse_time(resource.get("created_at"))
    if not created_at:
        return "unknown"
    delta = datetime.now(timezone.utc) - created_at
    return f"{delta.days}d" if delta.days > 0 else f"{delta.seconds // 3600}h"


def _region_from_arn(resource_arn: str) -> Optional[str]:
    parts = resource_arn.split(":")
    return parts[3] if len(parts) > 3 and parts[3] else None


def _csv(value: Optional[str]) -> Optional[list[str]]:
    if not value:
        return None
    return [item.strip() for item in value.split(",") if item.strip()]


def _parse_time(value) -> Optional[datetime]:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, str) and value:
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
        except ValueError:
            return None
    return None


def _format_time(value) -> str:
    parsed = _parse_time(value)
    return parsed.strftime("%Y-%m-%d %H:%M") if parsed else "Unknown"


def _pct(value: int, total: int) -> str:
    return f"{(value / total * 100):.1f}%" if total else "0%"


def _jsonable(value):
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {key: _jsonable(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_jsonable(item) for item in value]
    return value
