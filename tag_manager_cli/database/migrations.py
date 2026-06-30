"""Compatibility migration utilities backed by bluearch-core."""

from __future__ import annotations

from typing import Any

from rich.console import Console
from rich.table import Table

from ..utils.core_client import request_core

console = Console()


class MigrationManager:
    """Compatibility facade for legacy database migration callers."""

    def init_migrations(self) -> bool:
        console.print("[green]OK[/green] bluearch-core owns database migrations")
        return True

    def create_migration(self, message: str, autogenerate: bool = True) -> bool:
        console.print("[yellow]Migration creation is managed in bluearch-core.[/yellow]")
        return True

    def upgrade_database(self, revision: str = "head") -> bool:
        try:
            request_core("POST", "/api/v1/core/db/migrate?import_legacy=true", service_token=True, timeout=120.0)
            console.print(f"[green]OK[/green] Core database migrated ({revision})")
            return True
        except Exception as exc:
            console.print(f"[red]ERROR[/red] Core database migration failed: {exc}")
            return False

    def downgrade_database(self, revision: str) -> bool:
        console.print("[red]Downgrade is not supported from Tag Manager; manage core DB maintenance in bluearch-core.[/red]")
        return False

    def get_current_revision(self) -> str | None:
        try:
            status = request_core("GET", "/api/v1/core/db/status", service_token=True, timeout=10.0)
            return str(status.get("schema_version") or status.get("version") or "core-managed")
        except Exception:
            return None

    def get_migration_history(self) -> list[dict[str, Any]]:
        current = self.get_current_revision()
        return [{"revision": current or "unknown", "parent": None, "message": "bluearch-core managed schema"}]

    def show_migration_status(self):
        """Display current core migration status."""
        console.print("\n[bold]Core Database Migration Status[/bold]")
        try:
            status = request_core("GET", "/api/v1/core/db/status", service_token=True, timeout=10.0)
            current = status.get("schema_version") or status.get("version") or "core-managed"
            console.print(f"Current Revision: [cyan]{current}[/cyan]")

            table = Table(title="Core Database", show_header=True, header_style="bold magenta")
            table.add_column("Field", style="cyan")
            table.add_column("Value", style="white")
            table.add_row("Ready", str(status.get("ready", False)))
            table.add_row("Path", str(status.get("path", "")))
            table.add_row("Tables", str(status.get("table_count", 0)))
            console.print(table)
        except Exception as exc:
            console.print(f"[red]ERROR[/red] Could not read core database status: {exc}")

    def create_initial_migration(self) -> bool:
        return self.upgrade_database("head")

    def setup_database(self) -> bool:
        return self.upgrade_database("head")


migration_manager = MigrationManager()


def setup_database() -> bool:
    return migration_manager.setup_database()


def create_migration(message: str, autogenerate: bool = True) -> bool:
    return migration_manager.create_migration(message, autogenerate)


def upgrade_database(revision: str = "head") -> bool:
    return migration_manager.upgrade_database(revision)


def show_migration_status():
    migration_manager.show_migration_status()
