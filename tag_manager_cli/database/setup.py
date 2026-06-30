"""Database setup compatibility utilities backed by bluearch-core."""

from __future__ import annotations

from rich.console import Console
from rich.prompt import Confirm
from rich.table import Table

from .migrations import migration_manager
from ..utils.core_client import request_core

console = Console()


def setup_database_command() -> bool:
    """Run the core database migration/import flow."""
    console.print("[bold blue]Setting up bluearch-core database...[/bold blue]")
    try:
        if not migration_manager.setup_database():
            return False
        _show_database_summary()
        return True
    except Exception as exc:
        console.print(f"\n[red]ERROR[/red] Core database setup failed: {exc}")
        return False


def _mask_url(url: str) -> str:
    """Compatibility no-op for old callers."""
    return url


def _show_database_summary():
    """Show core database setup summary."""
    try:
        status = request_core("GET", "/api/v1/core/db/status", service_token=True, timeout=10.0)
        table = Table(title="Core Database", show_header=True, header_style="bold magenta")
        table.add_column("Field", style="cyan")
        table.add_column("Value", style="white")
        table.add_row("Ready", str(status.get("ready", False)))
        table.add_row("Path", str(status.get("path", "")))
        table.add_row("Tables", str(status.get("table_count", 0)))
        console.print("\n")
        console.print(table)
        console.print("\n")
        migration_manager.show_migration_status()
    except Exception as exc:
        console.print(f"[yellow]Could not fetch core database summary: {exc}[/yellow]")


def reset_database() -> bool:
    """Block destructive reset from the product CLI."""
    console.print("[bold red]WARNING: bluearch-core owns the shared database.[/bold red]")
    if Confirm.ask("Open-ended reset is disabled here. Continue without reset?", default=False):
        console.print("[yellow]No database reset was performed.[/yellow]")
    return False


def show_database_status():
    """Show current core database status."""
    console.print("[bold blue]Core Database Status[/bold blue]")
    _show_database_summary()
