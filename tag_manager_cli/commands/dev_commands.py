"""Development and debugging commands for Tag Manager CLI."""

import typer
from typing import Optional, List
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from ..testing.component_tests import (
    run_component_test, 
    run_all_component_tests,
    DatabaseTester,
    CacheTester,
    WorkerTester,
    RateLimiterTester
)
from ..utils.core_client import request_core

console = Console()
dev_app = typer.Typer(
    help="Development and debugging commands",
    no_args_is_help=False
)


def show_dev_help():
    """Show enhanced help for dev commands."""
    from ..utils.display_utils import print_safe

    print_safe("\n[bold cyan]Development & Debugging Commands[/bold cyan] - Internal tools\n")

    print_safe("[bold green]COMPONENT TESTING[/bold green] (test individual parts):")
    print_safe("- [cyan]test database[/cyan]  - Test database connectivity and operations")
    print_safe("- [cyan]test cache[/cyan]     - Test Redis cache functionality")
    print_safe("- [cyan]test workers[/cyan]   - Test background worker systems")
    print_safe("- [cyan]test all[/cyan]       - Run comprehensive component tests\n")

    print_safe("[bold yellow]DEBUGGING TOOLS[/bold yellow] (troubleshoot issues):")
    print_safe("- [cyan]debug aws[/cyan]      - Debug AWS authentication and permissions")
    print_safe("- [cyan]debug env[/cyan]      - Debug environment and configuration")
    print_safe("- [cyan]logs[/cyan]           - View detailed application logs\n")

    print_safe("[bold red]ADVANCED OPERATIONS[/bold red] (expert users):")
    print_safe("- [cyan]reset cache[/cyan]    - Clear all cached data")
    print_safe("- [cyan]rebuild[/cyan]        - Rebuild internal data structures")
    print_safe("- [cyan]validate[/cyan]       - Deep validation of system integrity\n")

    print_safe("[bold green]TYPICAL WORKFLOW[/bold green]:")
    print_safe("1. [dim]dev test all[/dim]                       # Run comprehensive tests")
    print_safe("2. [dim]dev debug env[/dim]                      # Check configuration")
    print_safe("3. [dim]dev logs[/dim]                           # Review detailed logs\n")

    print_safe("Pro tips:")
    print_safe("- Use [cyan]test all[/cyan] to quickly identify component issues")
    print_safe("- Debug commands provide detailed diagnostic information")
    print_safe("- These tools are designed for technical troubleshooting")


@dev_app.callback(invoke_without_command=True)
def dev_main(
    ctx: typer.Context,
    help: bool = typer.Option(False, "--help", "-h", help="Show this message and exit.")
):
    """
    Development and debugging tools - Internal testing and troubleshooting.

    Advanced commands for developers, testers, and power users who need
    to debug components, run tests, and troubleshoot Tag Manager internals.
    """
    if help or ctx.invoked_subcommand is None:
        show_dev_help()
        if help:
            raise typer.Exit()


@dev_app.command("test")
def test_component(
    component: str = typer.Argument(
        help="Component to test: database, cache, workers, rate_limiter, or 'all'"
    ),
    debug: bool = typer.Option(
        False, "--debug", "-d", 
        help="Enable debug mode with verbose output"
    ),
    verbose: bool = typer.Option(
        False, "--verbose", "-v", 
        help="Show detailed test results"
    )
):
    """Test individual components or all components in development mode."""
    
    if debug:
        console.print("[yellow]Debug mode enabled - showing detailed output[/yellow]")
    
    try:
        if component.lower() == 'all':
            console.print(Panel(
                "[bold blue]Running All Component Tests[/bold blue]\n"
                "Testing: Database, Cache, Workers, Rate Limiter",
                title="Development Test Suite"
            ))
            
            results = run_all_component_tests(debug=debug)
            
            if verbose:
                _show_detailed_results(results)
        
        else:
            valid_components = ['database', 'cache', 'workers', 'rate_limiter']
            if component not in valid_components:
                console.print(f"[red]Error: Invalid component '{component}'[/red]")
                console.print(f"Valid components: {', '.join(valid_components)}")
                raise typer.Exit(1)
            
            console.print(Panel(
                f"[bold blue]Testing {component.title()} Component[/bold blue]",
                title="Development Test"
            ))
            
            test_results = run_component_test(component, debug=debug)
            
            if verbose:
                _show_detailed_results({component: test_results})
    
    except Exception as e:
        console.print(f"[red]Test execution failed: {e}[/red]")
        if debug:
            import traceback
            console.print(f"[dim]{traceback.format_exc()}[/dim]")
        raise typer.Exit(1)


@dev_app.command("status")
def dev_status(
    check_all: bool = typer.Option(
        False, "--all", "-a",
        help="Check status of all development components"
    )
):
    """Show development environment status."""
    
    console.print(Panel(
        "[bold blue]Development Environment Status[/bold blue]",
        title="Status Check"
    ))
    
    # Quick health checks
    status_table = Table(show_header=True, header_style="bold magenta")
    status_table.add_column("Component", style="cyan")
    status_table.add_column("Status", style="white")
    status_table.add_column("Details", style="dim")
    
    # Core runtime and storage status
    try:
        health = request_core("GET", "/api/v1/core/health", service_token=False, timeout=2.0)
        status = "HEALTHY" if health.get("db_ready") else "UNHEALTHY"
        color = "green" if status == "HEALTHY" else "red"
        details = f"Core: {health.get('version', 'unknown')}"
        status_table.add_row("Core Storage", f"[{color}]{status}[/{color}]", details)
    except Exception as e:
        status_table.add_row("Core Storage", "[red]ERROR[/red]", str(e)[:50])
    
    # Cache status
    try:
        from ..utils.cache import cache
        status = "ENABLED" if cache.enabled else "DISABLED"
        color = "green" if cache.enabled else "yellow"
        details = f"Redis: {cache.redis_client.connection_pool.connection_kwargs.get('host', 'N/A') if cache.enabled else 'N/A'}"
        status_table.add_row("Cache", f"[{color}]{status}[/{color}]", details)
    except Exception as e:
        status_table.add_row("Cache", "[red]ERROR[/red]", str(e)[:50])
    
    # Worker status
    try:
        from datetime import datetime, timedelta

        rows = request_core(
            "GET",
            "/api/v1/storage/tag-manager/worker-status",
            service_token=True,
            params=[("limit", 1000)],
            timeout=5.0,
        )
        cutoff = datetime.utcnow() - timedelta(minutes=5)
        active_workers = 0
        for row in rows or []:
            worker = row.get("payload", row)
            heartbeat = worker.get("last_heartbeat")
            if isinstance(heartbeat, str):
                try:
                    heartbeat = datetime.fromisoformat(heartbeat.replace("Z", "+00:00")).replace(tzinfo=None)
                except ValueError:
                    heartbeat = None
            if worker.get("status") in ['active', 'busy', 'idle'] and heartbeat and heartbeat > cutoff:
                active_workers += 1
        
        status = "ACTIVE" if active_workers > 0 else "NONE"
        color = "green" if active_workers > 0 else "red"
        details = f"{active_workers} active workers"
        status_table.add_row("Workers", f"[{color}]{status}[/{color}]", details)
    except Exception as e:
        status_table.add_row("Workers", "[red]ERROR[/red]", str(e)[:50])
    
    # Rate limiter status
    try:
        from ..utils.rate_limiter import rate_limiter
        # Simple test to see if rate limiter is working
        ec2_limit = rate_limiter.get_service_limit('ec2')
        status = "CONFIGURED" if ec2_limit > 0 else "DEFAULT"
        color = "green" if ec2_limit > 0 else "yellow"
        details = f"EC2 limit: {ec2_limit}/min"
        status_table.add_row("Rate Limiter", f"[{color}]{status}[/{color}]", details)
    except Exception as e:
        status_table.add_row("Rate Limiter", "[red]ERROR[/red]", str(e)[:50])
    
    console.print(status_table)
    
    if check_all:
        console.print("\n[cyan]Running comprehensive health checks...[/cyan]")
        test_component('all', debug=False, verbose=False)


@dev_app.command("mock-aws")
def mock_aws_setup(
    enable: bool = typer.Option(
        True, "--enable/--disable",
        help="Enable or disable AWS mocking"
    ),
    services: Optional[List[str]] = typer.Option(
        None, "--service", "-s",
        help="Specific services to mock (ec2, s3, lambda)"
    )
):
    """Set up mock AWS services for testing without real AWS credentials."""
    
    from ..testing.mock_aws import enable_aws_mocks, disable_aws_mocks, is_mocking_enabled, get_mock_stats
    
    if enable:
        console.print("[yellow]Setting up mock AWS services...[/yellow]")
        
        try:
            enable_aws_mocks(services)
            
            stats = get_mock_stats()
            console.print(f"[green]OK[/green] Mock AWS services enabled")
            console.print(f"[dim]Services available: {services or ['ec2', 's3', 'lambda']}[/dim]")
            
            console.print("\n[blue]Now you can run:[/blue]")
            console.print("- python -m tag_manager_cli.main dev test workers --debug")
            console.print("- python -m tag_manager_cli.main dev debug-worker --task discovery")
            console.print("- python -m tag_manager_cli.main discover ec2")
            
        except Exception as e:
            console.print(f"[red]Failed to enable mock services: {e}[/red]")
            raise typer.Exit(1)
    
    else:
        console.print("[yellow]Disabling mock AWS services...[/yellow]")
        
        if is_mocking_enabled():
            disable_aws_mocks()
            console.print("[green]Mock services disabled[/green]")
        else:
            console.print("[yellow]Mock services were not enabled[/yellow]")


@dev_app.command("debug-worker")
def debug_worker(
    task_name: Optional[str] = typer.Option(
        None, "--task", "-t",
        help="Specific task to debug (health_check, system_metrics, discovery)"
    ),
    timeout: int = typer.Option(
        30, "--timeout",
        help="Task timeout in seconds"
    )
):
    """Debug worker tasks with detailed logging."""
    
    console.print(Panel(
        "[bold blue]Worker Debug Mode[/bold blue]",
        title="Debug Worker"
    ))
    
    if not task_name:
        console.print("Available debug tasks:")
        console.print("- health_check - Test worker health check")
        console.print("- system_metrics - Test system metrics collection")
        console.print("- discovery - Test resource discovery (requires AWS credentials)")
        return
    
    try:
        if task_name == 'health_check':
            from ..workers.monitoring_tasks import worker_health_check
            console.print("[cyan]Running health check task...[/cyan]")
            result = worker_health_check.delay()
            output = result.get(timeout=timeout)
            console.print(f"[green]Health check result:[/green] {output}")
        
        elif task_name == 'system_metrics':
            from ..workers.monitoring_tasks import collect_system_metrics
            console.print("[cyan]Running system metrics task...[/cyan]")
            result = collect_system_metrics.delay()
            output = result.get(timeout=timeout)
            console.print(f"[green]System metrics:[/green]")
            for key, value in output.items():
                console.print(f"  {key}: {value}")
        
        elif task_name == 'discovery':
            from ..workers.discovery_tasks import discover_ec2_resources
            console.print("[cyan]Running EC2 discovery task...[/cyan]")
            console.print("[yellow]Note: This requires valid AWS credentials[/yellow]")
            result = discover_ec2_resources.delay('us-east-1')
            output = result.get(timeout=timeout)
            console.print(f"[green]Discovery result:[/green] {output}")
        
        else:
            console.print(f"[red]Unknown task: {task_name}[/red]")
            raise typer.Exit(1)
    
    except Exception as e:
        console.print(f"[red]Debug task failed: {e}[/red]")
        import traceback
        console.print(f"[dim]{traceback.format_exc()}[/dim]")
        raise typer.Exit(1)


@dev_app.command("reset-cache")
def reset_cache(
    pattern: Optional[str] = typer.Option(
        None, "--pattern", "-p",
        help="Clear specific cache pattern (e.g., 'ec2:*')"
    ),
    confirm: bool = typer.Option(
        False, "--yes", "-y",
        help="Skip confirmation prompt"
    )
):
    """Reset cache for development testing."""
    
    try:
        from ..utils.cache import cache
        
        if not cache.enabled:
            console.print("[yellow]Cache is not enabled[/yellow]")
            return
        
        if pattern:
            if not confirm:
                confirm_clear = typer.confirm(f"Clear cache pattern '{pattern}'?")
                if not confirm_clear:
                    console.print("[yellow]Cache clear cancelled[/yellow]")
                    return
            
            cleared = cache.clear_pattern(pattern)
            console.print(f"[green]Cleared {cleared} cache keys matching pattern '{pattern}'[/green]")
        
        else:
            if not confirm:
                confirm_clear = typer.confirm("Clear ALL cache data?")
                if not confirm_clear:
                    console.print("[yellow]Cache clear cancelled[/yellow]")
                    return
            
            cache.redis_client.flushdb()
            console.print("[green]All cache data cleared[/green]")
    
    except Exception as e:
        console.print(f"[red]Failed to reset cache: {e}[/red]")
        raise typer.Exit(1)


def _show_detailed_results(results: dict):
    """Show detailed test results."""
    console.print("\n[bold blue]Detailed Test Results[/bold blue]")
    
    for component, test_results in results.items():
        console.print(f"\n[cyan]{component.title()} Component:[/cyan]")
        
        for test in test_results:
            status_icon = "OK" if test['status'] == 'passed' else "ERROR"
            status_color = "green" if test['status'] == 'passed' else "red"
            
            console.print(f"  [{status_color}]{status_icon}[/{status_color}] {test['name']} ({test['duration']:.3f}s)")
            
            if test['error']:
                console.print(f"    [red]Error: {test['error']['message']}[/red]")
            elif test['result'] and isinstance(test['result'], dict):
                for key, value in test['result'].items():
                    console.print(f"    [dim]{key}: {value}[/dim]")


# Register the dev app with the main CLI
def register_dev_commands(main_app: typer.Typer):
    """Register development commands with the main CLI app."""
    main_app.add_typer(dev_app, name="dev", help="Development and debugging commands")
