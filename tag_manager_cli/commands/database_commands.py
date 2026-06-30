"""Database management commands for Tag Manager CLI.

bluearch-core owns the shared SQLite database. These commands are compatibility
wrappers that inspect or initialize the core database without opening a
product-local SQLite file.
"""

from typing import Optional

import typer
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.table import Table

from ..utils.core_client import get_core_url, request_core

database_app = typer.Typer(help="Database management commands")
console = Console()


def initialize_database(auto_init: bool = False, force: bool = False, migrate_from_postgres: bool = False) -> bool:
    """
    Programmatic database initialization function.

    Args:
        auto_init: If True, skip confirmations and initialize silently
        force: Force initialization even if database exists
        migrate_from_postgres: Migrate data from PostgreSQL

    Returns:
        True if initialization successful, False otherwise
    """
    try:
        if force and not auto_init:
            console.print("[yellow]Core database initialization is idempotent; --force is ignored.[/yellow]")
        if migrate_from_postgres and not auto_init:
            console.print("[yellow]PostgreSQL import is no longer handled by Tag Manager.[/yellow]")

        result = _migrate_core_database(import_legacy=True)
        if not auto_init:
            console.print("\n[green]OK[/green] Core database initialized successfully")
            console.print(f"[INFO] Database location: {result.get('db_path', 'bluearch-core')}")

        return True

    except Exception as e:
        if not auto_init:
            console.print(f"[red]ERROR[/red] Failed to initialize database: {e}")
        return False


@database_app.command("init")
def init_db(
    force: bool = typer.Option(False, "--force", help="Force initialization even if database exists"),
    migrate_from_postgres: bool = typer.Option(False, "--migrate-from-postgres", help="Migrate data from PostgreSQL")
):
    """Initialize the Tag Manager database."""
    console.print("[INFO] Initializing database...")

    # Use the programmatic initialization function
    success = initialize_database(auto_init=False, force=force, migrate_from_postgres=migrate_from_postgres)

    if not success:
        raise typer.Exit(1)


@database_app.command("status")
def db_status():
    """Check database status and health."""
    console.print("[INFO] Checking bluearch-core database status...")
    health = request_core("GET", "/api/v1/core/health", timeout=5.0)
    status = request_core("GET", "/api/v1/core/db/status", timeout=5.0)

    # Create status table
    table = Table(title="Database Status", show_header=True, header_style="bold magenta")
    table.add_column("Property", style="cyan", width=30)
    table.add_column("Value", style="white")

    table.add_row("Owner", "bluearch-core")
    table.add_row("Core URL", get_core_url())
    table.add_row("Core Version", str(health.get("version", "unknown")))
    table.add_row("API Status", str(health.get("status", "unknown")))
    table.add_row("Database Ready", str(health.get("db_ready", False)))
    table.add_row("Location", str(status.get("db_path", health.get("db_path", "-"))))
    table.add_row("Exists", str(status.get("exists", False)))
    table.add_row("Tables", str(status.get("table_count", 0)))

    console.print(table)


@database_app.command("migrate")
def db_migrate():
    """Run pending database migrations."""
    console.print("[INFO] Running database migrations...")

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
        transient=True
    ) as progress:
        task = progress.add_task("Checking migration status...", total=None)

        progress.update(task, description="Running migrations...")

        result = _migrate_core_database(import_legacy=True)
        progress.update(task, description="[green]Migrations completed[/green]")
        console.print("\n[green]OK[/green] Core database migrations completed successfully")
        console.print(f"[INFO] Database location: {result.get('db_path', 'bluearch-core')}")
        for item in result.get("imports", []):
            status_text = "imported" if item.get("imported") else "skipped"
            if item.get("error"):
                status_text = f"failed: {item['error']}"
            console.print(f"[dim]{item.get('source_path')}: {status_text}[/dim]")


@database_app.command("backup")
def db_backup(
    output: Optional[str] = typer.Option(None, "--output", "-o", help="Output file path for backup")
):
    """Create a backup of the database."""
    console.print("[INFO] Database backups are owned by bluearch-core.")
    destination = f" --destination {output}" if output else ""
    console.print(f"[cyan]bluearch-core db backup{destination}[/cyan]")


@database_app.command("optimize")
def db_optimize():
    """Optimize database performance (VACUUM and ANALYZE)."""
    console.print("[yellow]Database optimization is owned by bluearch-core.[/yellow]")
    console.print("[dim]No product-local database was opened.[/dim]")


@database_app.command("reset")
def db_reset(
    confirm: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation prompt")
):
    """Reset the database (DANGEROUS - deletes all data)."""
    if not confirm:
        confirm_text = typer.prompt(
            "[red]WARNING[/red] This will delete ALL data. Type 'DELETE' to confirm",
            type=str
        )
        if confirm_text != 'DELETE':
            console.print("[yellow]Reset cancelled[/yellow]")
            return

    console.print("[red]Reset is disabled from Tag Manager because bluearch-core owns the shared database.[/red]")
    console.print("[yellow]Back up the core database first, then manage destructive maintenance from bluearch-core.[/yellow]")
    raise typer.Exit(1)


def _migrate_core_database(import_legacy: bool = True) -> dict:
    return request_core(
        "POST",
        "/api/v1/core/db/migrate",
        params=[("import_legacy", str(import_legacy).lower())],
        timeout=60.0,
    )


if __name__ == "__main__":
    database_app()
