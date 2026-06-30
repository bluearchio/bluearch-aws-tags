"""Tagging management commands backed by bluearch-core storage."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

import typer
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.table import Table

from ..utils.core_client import request_core

console = Console()
tagging_app = typer.Typer(help="Automated tagging management commands")
CORE_RESOURCE_PAGE_SIZE = 1000
CORE_RESOURCE_SCAN_LIMIT = 10000


@tagging_app.command("load-rules")
def load_tagging_rules(
    rules_file: str = typer.Argument(..., help="Path to JSON file containing tagging rules"),
    replace_existing: bool = typer.Option(False, "--replace", help="Replace existing rules with same names"),
):
    """Load tagging rules from a JSON configuration file."""
    try:
        rules_path = Path(rules_file)
        if not rules_path.exists():
            console.print(f"[red]Error: Rules file not found: {rules_file}[/red]")
            raise typer.Exit(1)

        rules_data = json.loads(rules_path.read_text(encoding="utf-8"))
        if not isinstance(rules_data, list):
            console.print("[red]Error: Rules file must contain a list of rule objects[/red]")
            raise typer.Exit(1)

        loaded_rules = 0
        updated_rules = 0
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=console,
            transient=True,
        ) as progress:
            task = progress.add_task("Loading tagging rules...", total=len(rules_data))
            for rule_data in rules_data:
                try:
                    rule_name = rule_data.get("name")
                    if not rule_name:
                        console.print("[yellow]Skipping rule without name[/yellow]")
                        progress.advance(task)
                        continue

                    existing_rule = _find_rule_by_name(rule_name)
                    payload = _rule_payload(rule_data)
                    if existing_rule:
                        if not replace_existing:
                            console.print(
                                f"[yellow]Rule '{rule_name}' already exists, skipping "
                                "(use --replace to update)[/yellow]"
                            )
                            progress.advance(task)
                            continue
                        payload["updated_at"] = datetime.now(timezone.utc)
                        _update_storage("tagging-rules", existing_rule["id"], payload)
                        updated_rules += 1
                        progress.update(task, description=f"Updated rule: {rule_name}")
                    else:
                        _create_storage("tagging-rules", payload)
                        loaded_rules += 1
                        progress.update(task, description=f"Loaded rule: {rule_name}")
                    progress.advance(task)
                except Exception as exc:  # noqa: BLE001 - keep loading independent rules.
                    console.print(f"[red]Error processing rule {rule_data.get('name', 'unknown')}: {exc}[/red]")
                    progress.advance(task)

        console.print(
            f"[green]OK[/green] Successfully loaded {loaded_rules} new rules "
            f"and updated {updated_rules} existing rules"
        )
    except typer.Exit:
        raise
    except Exception as exc:
        console.print(f"[red]Error loading tagging rules: {exc}[/red]")
        raise typer.Exit(1)


@tagging_app.command("list-rules")
def list_tagging_rules(
    enabled_only: bool = typer.Option(False, "--enabled-only", help="Show only enabled rules"),
    resource_type: Optional[str] = typer.Option(None, "--resource-type", help="Filter by resource type"),
):
    """List all tagging rules."""
    try:
        rules = _list_rules(enabled_only=enabled_only)
        if resource_type:
            rules = [rule for rule in rules if resource_type in (rule.get("resource_types") or [])]
        rules.sort(key=lambda rule: (rule.get("priority") or 100, rule.get("name") or ""))

        if not rules:
            console.print("[yellow]No tagging rules found[/yellow]")
            return

        table = Table(title="Tagging Rules", show_header=True, header_style="bold magenta")
        table.add_column("Name", style="cyan", width=20)
        table.add_column("Description", style="white", width=30)
        table.add_column("Resource Types", style="green", width=25)
        table.add_column("Priority", style="yellow", width=8)
        table.add_column("Enabled", style="blue", width=8)
        table.add_column("Tags", style="dim", width=15)

        for rule in rules:
            resource_types = rule.get("resource_types") or []
            resource_types_str = ", ".join(resource_types[:2])
            if len(resource_types) > 2:
                resource_types_str += f" (+{len(resource_types) - 2} more)"
            tag_templates = rule.get("tag_templates") or {}
            tag_count = len(tag_templates) if hasattr(tag_templates, "__len__") else 0
            table.add_row(
                rule.get("name") or "",
                rule.get("description") or "No description",
                resource_types_str or "-",
                str(rule.get("priority") or 100),
                "OK" if rule.get("enabled", True) else "ERROR",
                f"{tag_count} tag(s)",
            )

        console.print(table)
    except Exception as exc:
        console.print(f"[red]Error listing tagging rules: {exc}[/red]")
        raise typer.Exit(1)


@tagging_app.command("enable-rule")
def enable_tagging_rule(rule_name: str = typer.Argument(..., help="Name of the rule to enable")):
    """Enable a tagging rule."""
    _set_rule_enabled(rule_name, True)


@tagging_app.command("disable-rule")
def disable_tagging_rule(rule_name: str = typer.Argument(..., help="Name of the rule to disable")):
    """Disable a tagging rule."""
    _set_rule_enabled(rule_name, False)


@tagging_app.command("apply-rules")
def apply_rules_to_resources(
    resource_arns: Optional[list[str]] = typer.Option(None, "--resource-arn", help="Specific resource ARNs to process"),
    rule_names: Optional[list[str]] = typer.Option(None, "--rule-name", help="Specific rule names to apply"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Show what would be tagged without applying changes"),
):
    """Plan tagging rule application against core inventory.

    Actual tag mutation is intentionally left to the product-specific worker
    migration. This command no longer opens SQLite directly and supports
    accurate core-backed dry-runs.
    """
    try:
        rules = _list_rules(enabled_only=True)
        if rule_names:
            requested = set(rule_names)
            rules = [rule for rule in rules if rule.get("name") in requested]
            found = {rule.get("name") for rule in rules}
            missing = sorted(requested - found)
            if missing:
                console.print(f"[red]Rules not found: {', '.join(missing)}[/red]")
                raise typer.Exit(1)

        resources = _list_resources()
        if resource_arns:
            requested_arns = set(resource_arns)
            resources = [resource for resource in resources if resource.get("resource_arn") in requested_arns]

        console.print(f"[dim]Would process {len(resources)} resources with {len(rules)} rules[/dim]")
        for resource in resources[:5]:
            console.print(f"  - {resource.get('resource_arn')}")
        if len(resources) > 5:
            console.print(f"  ... and {len(resources) - 5} more resources")

        if not dry_run:
            execution = _create_storage(
                "tagging-executions",
                {
                    "execution_type": "apply_rules",
                    "description": "Bulk tagging execution requested from CLI",
                    "initiated_by": "cli",
                    "initiated_via": "tag-manager-cli",
                    "status": "blocked_pending_worker_migration",
                    "total_resources": len(resources),
                    "metadata": {
                        "resource_arns": resource_arns or [],
                        "rule_names": rule_names or [],
                        "reason": "Tag mutation worker migration is still pending",
                    },
                },
            )
            console.print(
                "[yellow]Tag mutation worker migration is still pending; "
                f"recorded execution {execution.get('id')} for audit.[/yellow]"
            )
    except typer.Exit:
        raise
    except Exception as exc:
        console.print(f"[red]Error applying tagging rules: {exc}[/red]")
        raise typer.Exit(1)


@tagging_app.command("stats")
def show_tagging_statistics():
    """Show automated tagging statistics from core audit logs."""
    try:
        tagging_stats = _tagging_statistics()
        console.print("\n[bold magenta]Automated Tagging Statistics (24 hours)[/bold magenta]")

        tagging_table = Table(show_header=True, header_style="bold cyan")
        tagging_table.add_column("Metric", style="white", width=30)
        tagging_table.add_column("Value", style="green", width=15)

        tagging_table.add_row("Total Operations", str(tagging_stats.get("total_operations_24h", 0)))
        tagging_table.add_row("Successful Operations", str(tagging_stats.get("successful_operations_24h", 0)))
        tagging_table.add_row("Failed Operations", str(tagging_stats.get("failed_operations_24h", 0)))
        tagging_table.add_row("Success Rate", f"{tagging_stats.get('success_rate_24h', 0):.1f}%")
        tagging_table.add_row("Resources Tagged", str(tagging_stats.get("unique_resources_tagged_24h", 0)))
        tagging_table.add_row("Rules Applied", str(tagging_stats.get("unique_rules_applied_24h", 0)))
        console.print(tagging_table)

        ops_by_type = tagging_stats.get("operations_by_type", {})
        if ops_by_type:
            console.print("\n[bold magenta]Operations by Type[/bold magenta]")
            ops_table = Table(show_header=True, header_style="bold cyan")
            ops_table.add_column("Operation Type", style="white", width=25)
            ops_table.add_column("Total", style="yellow", width=10)
            ops_table.add_column("Successful", style="green", width=10)
            ops_table.add_column("Success Rate", style="blue", width=12)
            for op_type, stats in ops_by_type.items():
                total = stats["total"]
                successful = stats["successful"]
                success_rate = (successful / total * 100) if total else 0
                ops_table.add_row(op_type, str(total), str(successful), f"{success_rate:.1f}%")
            console.print(ops_table)
    except Exception as exc:
        console.print(f"[red]Error getting tagging statistics: {exc}[/red]")
        raise typer.Exit(1)


@tagging_app.command("audit-log")
def show_audit_log(
    resource_arn: Optional[str] = typer.Option(None, "--resource-arn", help="Filter by resource ARN"),
    limit: int = typer.Option(50, "--limit", help="Maximum number of entries to show"),
    success_only: bool = typer.Option(False, "--success-only", help="Show only successful operations"),
):
    """Show tagging audit log."""
    try:
        filters = []
        if resource_arn:
            filters.append(("resource_arn", resource_arn))
        if success_only:
            filters.append(("success", "true"))
        logs = _list_storage("tagging-audit-log", filters=filters, limit=limit, order_by="executed_at")

        if not logs:
            console.print("[yellow]No audit log entries found[/yellow]")
            return

        table = Table(title=f"Tagging Audit Log (Last {len(logs)} entries)", show_header=True, header_style="bold magenta")
        table.add_column("Time", style="dim", width=16)
        table.add_column("Resource", style="cyan", width=25)
        table.add_column("Operation", style="white", width=15)
        table.add_column("Success", style="green", width=8)
        table.add_column("Principal", style="blue", width=20)
        table.add_column("Tags", style="yellow", width=15)

        for log in logs:
            resource_display = _resource_display(log.get("resource_arn") or "")
            principal_info = log.get("principal_info") or {}
            principal_display = principal_info.get("user_name") or _last_segment(principal_info.get("arn")) or "N/A"
            new_tags = log.get("new_tags") or {}
            table.add_row(
                _format_time(log.get("executed_at")),
                resource_display,
                log.get("operation") or "-",
                "OK" if log.get("success") else "ERROR",
                _truncate(principal_display, 18),
                f"{len(new_tags)} tag(s)" if new_tags else "N/A",
            )

        console.print(table)
    except Exception as exc:
        console.print(f"[red]Error showing audit log: {exc}[/red]")
        raise typer.Exit(1)


def _set_rule_enabled(rule_name: str, enabled: bool) -> None:
    try:
        rule = _find_rule_by_name(rule_name)
        if not rule:
            console.print(f"[red]Rule '{rule_name}' not found[/red]")
            raise typer.Exit(1)
        rule["enabled"] = enabled
        rule["updated_at"] = datetime.now(timezone.utc)
        _update_storage("tagging-rules", rule["id"], rule)
        if enabled:
            console.print(f"[green]OK[/green] Enabled rule '{rule_name}'")
        else:
            console.print(f"[yellow]Disabled rule '{rule_name}'[/yellow]")
    except typer.Exit:
        raise
    except Exception as exc:
        action = "enabling" if enabled else "disabling"
        console.print(f"[red]Error {action} rule: {exc}[/red]")
        raise typer.Exit(1)


def _rule_payload(rule_data: dict[str, Any]) -> dict[str, Any]:
    return {
        "name": rule_data.get("name"),
        "description": rule_data.get("description"),
        "resource_types": rule_data.get("resource_types") or [],
        "conditions": rule_data.get("conditions") or [],
        "tag_templates": rule_data.get("tag_templates") or {},
        "priority": rule_data.get("priority", 100),
        "enabled": rule_data.get("enabled", True),
    }


def _find_rule_by_name(name: str) -> Optional[dict[str, Any]]:
    rows = _list_storage("tagging-rules", filters=[("name", name)], limit=1, order_by="priority")
    return rows[0] if rows else None


def _list_rules(*, enabled_only: bool = False) -> list[dict[str, Any]]:
    filters = [("enabled", "true")] if enabled_only else []
    return _list_storage("tagging-rules", filters=filters, limit=10000, order_by="priority", descending=False)


def _list_resources() -> list[dict[str, Any]]:
    resources: list[dict[str, Any]] = []
    target = CORE_RESOURCE_SCAN_LIMIT
    offset = 0
    total: int | None = None

    while len(resources) < target and (total is None or offset < total):
        page_limit = min(CORE_RESOURCE_PAGE_SIZE, target - len(resources))
        payload = request_core("GET", f"/api/v1/resources?limit={page_limit}&offset={offset}", timeout=10.0)
        if not isinstance(payload, dict):
            break
        items = payload.get("items", [])
        if not isinstance(items, list) or not items:
            break
        resources.extend(items)
        raw_total = payload.get("total")
        total = raw_total if isinstance(raw_total, int) else len(resources)
        offset += len(items)

    return resources


def _list_storage(
    collection: str,
    *,
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
    rows = request_core(
        "GET",
        f"/api/v1/storage/tag-manager/{collection}",
        service_token=True,
        params=params,
        timeout=10.0,
    )
    return [row.get("payload", row) for row in rows or []]


def _create_storage(collection: str, payload: dict[str, Any]) -> dict[str, Any]:
    record = request_core(
        "POST",
        f"/api/v1/storage/tag-manager/{collection}",
        service_token=True,
        json={"payload": _jsonable(payload)},
        timeout=10.0,
    )
    return record.get("payload", record)


def _update_storage(collection: str, record_key: str, payload: dict[str, Any]) -> dict[str, Any]:
    record = request_core(
        "PUT",
        f"/api/v1/storage/tag-manager/{collection}/{record_key}",
        service_token=True,
        json={"payload": _jsonable(payload)},
        timeout=10.0,
    )
    return record.get("payload", record)


def _tagging_statistics() -> dict[str, Any]:
    cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
    logs = _list_storage("tagging-audit-log", limit=10000, order_by="executed_at")
    recent = [log for log in logs if (_parse_time(log.get("executed_at")) or datetime.min.replace(tzinfo=timezone.utc)) >= cutoff]
    successes = [log for log in recent if log.get("success")]
    failures = [log for log in recent if not log.get("success")]
    operations: dict[str, dict[str, int]] = {}
    for log in recent:
        op = log.get("operation") or "unknown"
        operations.setdefault(op, {"total": 0, "successful": 0})
        operations[op]["total"] += 1
        if log.get("success"):
            operations[op]["successful"] += 1
    rule_ids = {log.get("rule_id") for log in recent if log.get("rule_id")}
    resource_arns = {log.get("resource_arn") for log in successes if log.get("resource_arn")}
    total = len(recent)
    return {
        "total_operations_24h": total,
        "successful_operations_24h": len(successes),
        "failed_operations_24h": len(failures),
        "success_rate_24h": (len(successes) / total * 100) if total else 0,
        "unique_resources_tagged_24h": len(resource_arns),
        "unique_rules_applied_24h": len(rule_ids),
        "operations_by_type": operations,
    }


def _jsonable(value):
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {key: _jsonable(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_jsonable(item) for item in value]
    return value


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
    return parsed.strftime("%Y-%m-%d %H:%M") if parsed else "-"


def _resource_display(resource_arn: str) -> str:
    value = resource_arn.split(":")[-1] if ":" in resource_arn else resource_arn
    return _truncate(value, 20)


def _last_segment(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    return value.split("/")[-1]


def _truncate(value: str, max_len: int) -> str:
    return value if len(value) <= max_len else value[: max_len - 3] + "..."
