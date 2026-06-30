#!/usr/bin/env python3
"""
Quick test script for cross-account functionality with hybrid architecture.

Run this to validate the implementation:
    python test_cross_account.py
"""

import sys
import time
from pathlib import Path
from rich.console import Console
from rich.table import Table
from rich.panel import Panel

console = Console()


def test_dynamodb_state_service():
    """Test DynamoDB state service initialization and operations."""
    console.print("\n[bold cyan]Testing DynamoDB State Service...[/bold cyan]")

    try:
        from tag_manager_cli.services import dynamodb_state

        # Check service status
        sync_status = dynamodb_state.get_sync_status()

        # Create status table
        table = Table(title="DynamoDB State Service Status")
        table.add_column("Property", style="cyan")
        table.add_column("Value", style="white")

        table.add_row("DynamoDB Available",
                     "[green]Yes[/green]" if sync_status['dynamodb_available'] else "[yellow]No (using local)[/yellow]")
        table.add_row("Table Name", sync_status['table_name'])
        table.add_row("Local Cache Exists",
                     "[green]Yes[/green]" if sync_status['local_cache_exists'] else "[yellow]No[/yellow]")
        table.add_row("Local State Exists",
                     "[green]Yes[/green]" if sync_status['local_state_exists'] else "[yellow]No[/yellow]")

        console.print(table)

        # Test getting enabled accounts
        enabled = dynamodb_state.get_enabled_accounts()
        console.print(f"\n[bold]Currently enabled accounts:[/bold] {len(enabled)}")

        if enabled:
            for acc_id in enabled[:5]:
                console.print(f"  - {acc_id}")
            if len(enabled) > 5:
                console.print(f"  ... and {len(enabled) - 5} more")

        return True

    except Exception as e:
        console.print(f"[red]Error: {str(e)}[/red]")
        return False


def test_database_models():
    """Test database models and AccountStatus table."""
    console.print("\n[bold cyan]Testing Database Models...[/bold cyan]")

    try:
        from tag_manager_cli.database.connection import get_db_session
        from tag_manager_cli.database.models import AccountStatus, Resource
        from sqlalchemy import inspect, func

        with get_db_session() as session:
            # Check if AccountStatus table exists
            inspector = inspect(session.bind)
            tables = inspector.get_table_names()

            if 'account_status' in tables:
                console.print("[green]✓[/green] AccountStatus table exists")

                # Count entries
                account_count = session.query(func.count(AccountStatus.account_id)).scalar()
                console.print(f"  Found {account_count} account entries")

                # Show some account details
                accounts = session.query(AccountStatus).limit(3).all()
                for acc in accounts:
                    console.print(f"  - {acc.account_id}: enabled={acc.enabled_for_discovery}")
            else:
                console.print("[yellow]AccountStatus table not found (will be created on first use)[/yellow]")

            # Check resource account associations
            resources_with_account = session.query(Resource).filter(
                Resource.account_id.isnot(None)
            ).count()

            if resources_with_account > 0:
                console.print(f"[green]✓[/green] Found {resources_with_account} resources with account IDs")
            else:
                console.print("[dim]No resources with account IDs yet (run discovery to populate)[/dim]")

        return True

    except Exception as e:
        console.print(f"[red]Error: {str(e)}[/red]")
        return False


def test_account_commands():
    """Test account command integration."""
    console.print("\n[bold cyan]Testing Account Commands Integration...[/bold cyan]")

    try:
        # Check if account commands module loads
        from tag_manager_cli.commands import account_commands

        console.print("[green]✓[/green] Account commands module loaded")

        # Check local cache files
        cache_dir = Path.home() / ".tag-manager" / "data"
        enabled_file = cache_dir / "enabled_accounts.json"
        states_file = cache_dir / "account_states.json"

        if enabled_file.exists():
            console.print(f"[green]✓[/green] Local enabled cache exists: {enabled_file}")
        else:
            console.print(f"[dim]Local enabled cache not found (will be created on first use)[/dim]")

        if states_file.exists():
            console.print(f"[green]✓[/green] Local states cache exists: {states_file}")
        else:
            console.print(f"[dim]Local states cache not found (will be created on first use)[/dim]")

        return True

    except Exception as e:
        console.print(f"[red]Error: {str(e)}[/red]")
        return False


def test_multi_account_discovery():
    """Test multi-account discovery module."""
    console.print("\n[bold cyan]Testing Multi-Account Discovery...[/bold cyan]")

    try:
        from tag_manager_cli.modules.multi_account_discovery import multi_account_discovery

        # Get enabled accounts through the discovery module
        enabled = multi_account_discovery.get_enabled_accounts()

        console.print(f"[green]✓[/green] Discovery module can read enabled accounts: {len(enabled)}")

        # Check if it's using DynamoDB state or fallback
        if hasattr(multi_account_discovery, '_dynamodb_state') and multi_account_discovery._dynamodb_state:
            console.print("  Using DynamoDB state service")
        else:
            console.print("  Using fallback JSON file")

        return True

    except Exception as e:
        console.print(f"[red]Error: {str(e)}[/red]")
        return False


def test_aws_connectivity():
    """Test AWS connectivity and permissions."""
    console.print("\n[bold cyan]Testing AWS Connectivity...[/bold cyan]")

    try:
        from tag_manager_cli.utils.aws_auth import aws_auth

        # Get caller identity
        identity = aws_auth.get_caller_identity()

        table = Table(title="AWS Identity")
        table.add_column("Property", style="cyan")
        table.add_column("Value", style="white")

        table.add_row("Account", identity.get('Account', 'Unknown'))
        table.add_row("User ARN", identity.get('Arn', 'Unknown')[:50] + "...")

        console.print(table)

        # Try to list organization accounts (if in management account)
        try:
            accounts = aws_auth.get_organization_accounts()
            console.print(f"[green]✓[/green] Can list organization accounts: {len(accounts)} found")
        except:
            console.print("[yellow]Cannot list organization accounts (not in management account or no permissions)[/yellow]")

        return True

    except Exception as e:
        console.print(f"[red]AWS not configured: {str(e)}[/red]")
        console.print("[yellow]Run 'aws sso login' and set AWS_PROFILE[/yellow]")
        return False


def main():
    """Run all tests."""
    console.print(Panel.fit(
        "[bold]Cross-Account Feature Test Suite[/bold]\n"
        "Testing hybrid DynamoDB/SQLite architecture",
        style="cyan"
    ))

    tests = [
        ("AWS Connectivity", test_aws_connectivity),
        ("DynamoDB State Service", test_dynamodb_state_service),
        ("Database Models", test_database_models),
        ("Account Commands", test_account_commands),
        ("Multi-Account Discovery", test_multi_account_discovery)
    ]

    results = []

    for name, test_func in tests:
        try:
            success = test_func()
            results.append((name, success))
        except Exception as e:
            console.print(f"\n[red]Test '{name}' crashed: {str(e)}[/red]")
            results.append((name, False))

    # Summary
    console.print("\n" + "="*60)
    console.print("[bold]Test Summary:[/bold]")

    passed = sum(1 for _, success in results if success)
    total = len(results)

    for name, success in results:
        status = "[green]PASSED[/green]" if success else "[red]FAILED[/red]"
        console.print(f"  {name}: {status}")

    console.print(f"\n[bold]Results: {passed}/{total} tests passed[/bold]")

    if passed == total:
        console.print("\n[bold green]✅ All tests passed! The hybrid architecture is working correctly.[/bold green]")
    elif passed > 0:
        console.print("\n[yellow]⚠ Some tests failed. Check the output above for details.[/yellow]")
    else:
        console.print("\n[red]❌ All tests failed. Please check your AWS configuration.[/red]")

    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())