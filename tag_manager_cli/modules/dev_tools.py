"""Development tools module for Tag Manager CLI."""

from rich.console import Console
from rich.table import Table
from rich.prompt import Prompt, Confirm
from rich.panel import Panel

console = Console()


def run_development_tools():
    """Run the development tools interface."""
    console.print(Panel(
        "[bold blue]Development Tools[/bold blue]\n"
        "Component testing, debugging utilities, and development helpers",
        title="Development Mode"
    ))
    
    while True:
        display_dev_menu()
        choice = Prompt.ask("Select an option", default="q")
        
        if choice.lower() == "q":
            break
        
        handle_dev_selection(choice)


def display_dev_menu():
    """Display development tools menu."""
    table = Table(title="Development Tools", show_header=True, header_style="bold magenta")
    table.add_column("Option", style="cyan", width=8)
    table.add_column("Tool", style="white", width=30)
    table.add_column("Description", style="dim white")
    
    dev_options = [
        ("1", "Test All Components", "Run comprehensive tests on all system components"),
        ("2", "Test Database", "Test database connections and operations"),
        ("3", "Test Cache", "Test Redis cache functionality"),
        ("4", "Test Workers", "Test Celery worker tasks and health"),
        ("5", "Test Rate Limiter", "Test AWS API rate limiting"),
        ("6", "System Status", "Show detailed system component status"),
        ("7", "Debug Worker Tasks", "Run individual worker tasks with debug output"),
        ("8", "Mock AWS Services", "Enable/disable mock AWS for testing"),
        ("9", "Reset Cache", "Clear cache data for testing"),
        ("q", "Back to Main Menu", "Return to main menu")
    ]
    
    for option, tool, description in dev_options:
        table.add_row(option, tool, description)
    
    console.print(table)
    console.print()


def handle_dev_selection(choice: str):
    """Handle development menu selection."""
    try:
        if choice == "1":
            run_all_component_tests()
        elif choice == "2":
            run_component_test("database")
        elif choice == "3":
            run_component_test("cache")
        elif choice == "4":
            run_component_test("workers")
        elif choice == "5":
            run_component_test("rate_limiter")
        elif choice == "6":
            show_system_status()
        elif choice == "7":
            debug_worker_interactive()
        elif choice == "8":
            mock_aws_interactive()
        elif choice == "9":
            reset_cache_interactive()
        else:
            console.print(f"[red]Invalid option: {choice}[/red]")
    
    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")
    
    console.print("\nPress Enter to continue...")
    input()


def run_all_component_tests():
    """Run all component tests."""
    from ..testing.component_tests import run_all_component_tests
    
    debug = Confirm.ask("Enable debug mode?", default=False)
    
    console.print("[cyan]Running all component tests...[/cyan]")
    results = run_all_component_tests(debug=debug)
    
    # Show summary
    total_tests = sum(len(test_results) for test_results in results.values())
    total_passed = sum(
        sum(1 for test in test_results if test['status'] == 'passed')
        for test_results in results.values()
    )
    
    success_rate = (total_passed / total_tests) * 100 if total_tests > 0 else 0
    color = "green" if success_rate == 100 else "yellow" if success_rate >= 70 else "red"
    
    console.print(f"\n[{color}]Overall Result: {total_passed}/{total_tests} tests passed ({success_rate:.1f}%)[/{color}]")


def run_component_test(component: str):
    """Run tests for a specific component."""
    from ..testing.component_tests import run_component_test
    
    debug = Confirm.ask("Enable debug mode?", default=False)
    
    console.print(f"[cyan]Testing {component} component...[/cyan]")
    test_results = run_component_test(component, debug=debug)
    
    # Show results summary
    passed = sum(1 for test in test_results if test['status'] == 'passed')
    total = len(test_results)
    
    color = "green" if passed == total else "yellow" if passed > 0 else "red"
    console.print(f"\n[{color}]{component.title()} Tests: {passed}/{total} passed[/{color}]")


def show_system_status():
    """Show detailed system status."""
    console.print("[cyan]Checking system status...[/cyan]")
    
    # Import and run the status command
    from ..commands.dev_commands import dev_status
    dev_status(check_all=True)


def debug_worker_interactive():
    """Interactive worker debugging."""
    console.print("Available worker debug tasks:")
    console.print("1. health_check - Test worker health")
    console.print("2. system_metrics - Test system metrics collection")
    console.print("3. discovery - Test resource discovery (requires AWS credentials)")
    
    task_choice = Prompt.ask("Select task to debug", choices=["1", "2", "3"])
    
    task_map = {
        "1": "health_check",
        "2": "system_metrics", 
        "3": "discovery"
    }
    
    task_name = task_map[task_choice]
    timeout = int(Prompt.ask("Task timeout (seconds)", default="30"))
    
    from ..commands.dev_commands import debug_worker
    debug_worker(task_name=task_name, timeout=timeout)


def mock_aws_interactive():
    """Interactive mock AWS setup."""
    from ..testing.mock_aws import is_mocking_enabled, get_mock_stats
    
    current_status = "ENABLED" if is_mocking_enabled() else "DISABLED"
    console.print(f"Current mock AWS status: [{('green' if is_mocking_enabled() else 'red')}]{current_status}[/]")
    
    if is_mocking_enabled():
        stats = get_mock_stats()
        console.print(f"Mock statistics: {stats}")
    
    console.print("\nMock AWS options:")
    console.print("1. Enable mock AWS services")
    console.print("2. Disable mock AWS services")
    console.print("3. Enable specific services")
    
    choice = Prompt.ask("Select option", choices=["1", "2", "3"])
    
    from ..commands.dev_commands import mock_aws_setup
    
    if choice == "1":
        mock_aws_setup(enable=True, services=None)
    elif choice == "2":
        mock_aws_setup(enable=False, services=None)
    else:
        console.print("Available services: ec2, s3, lambda")
        services_input = Prompt.ask("Enter services to mock (comma-separated)")
        services = [s.strip() for s in services_input.split(",")]
        mock_aws_setup(enable=True, services=services)


def reset_cache_interactive():
    """Interactive cache reset."""
    console.print("Cache reset options:")
    console.print("1. Clear all cache data")
    console.print("2. Clear specific pattern")
    
    choice = Prompt.ask("Select option", choices=["1", "2"])
    
    from ..commands.dev_commands import reset_cache
    
    if choice == "1":
        if Confirm.ask("Clear ALL cache data?"):
            reset_cache(pattern=None, confirm=True)
    else:
        pattern = Prompt.ask("Enter cache pattern (e.g., 'ec2:*')")
        if Confirm.ask(f"Clear cache pattern '{pattern}'?"):
            reset_cache(pattern=pattern, confirm=True)