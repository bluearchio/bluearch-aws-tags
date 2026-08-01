# -*- coding: utf-8 -*-
"""Main entry point for AWS Tag Manager CLI."""

import typer
from rich.prompt import Prompt
from typing import Optional
import sys
import os


def _raw_bare_discover_invocation(arguments: list[str]) -> bool:
    """Recognize bare discovery before importing stateful command modules."""
    remaining = list(arguments)
    while remaining and remaining[0] == "--no-prompt":
        remaining.pop(0)
    return remaining == ["discover"]


_HELP_ONLY_BARE_DISCOVER = _raw_bare_discover_invocation(sys.argv[1:])
if _HELP_ONLY_BARE_DISCOVER:
    os.environ["TAG_MANAGER_SUPPRESS_STARTUP_STATE"] = "1"

# Ensure UTF-8 encoding for packaged binaries and all environments
import locale
# Try to set locale programmatically for packaged binary compatibility
try:
    # First try to set UTF-8 locale
    locale.setlocale(locale.LC_ALL, 'C.UTF-8')
except locale.Error:
    try:
        # Fallback to en_US.UTF-8
        locale.setlocale(locale.LC_ALL, 'en_US.UTF-8')
    except locale.Error:
        try:
            # Last fallback - just set LC_CTYPE for character encoding
            locale.setlocale(locale.LC_CTYPE, 'C.UTF-8')
        except locale.Error:
            # If all fails, set environment variables as fallback
            os.environ.setdefault('LC_ALL', 'C.UTF-8')
            os.environ.setdefault('PYTHONUTF8', '1')
            os.environ.setdefault('PYTHONIOENCODING', 'utf-8')

# Ensure console can handle UTF-8 characters
if hasattr(sys.stdout, 'reconfigure'):
    try:
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
    except (AttributeError, Exception):
        pass

# Handle both direct execution and module execution
if __name__ == "__main__" or not __package__:
    # Running directly - add parent directory to path and use absolute imports
    import sys
    import os
    parent_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if parent_dir not in sys.path:
        sys.path.insert(0, parent_dir)
    
    # Use absolute imports when running directly
    from tag_manager_cli.utils.env_config import settings
    from tag_manager_cli.utils.aws_auth import aws_auth
    # from tag_manager_cli.utils.docker_integration import docker_integration  # Removed - Container-free architecture
    from tag_manager_cli.utils.display_utils import display_main_menu, print_safe, print_error
    # PERFORMANCE OPTIMIZATION: Modules import boto3, so we lazy load them
    # from tag_manager_cli.modules import (
    #     cost_allocation,
    #     resource_organization,
    #     # docker_management,  # Disabled - Container-free architecture
    #     dev_tools
    # )
    # from tag_manager_cli.commands.database_commands import database_app  # Disabled - Auto-init handles this
    # PERFORMANCE OPTIMIZATION: Lazy loading - commands imported on-demand
    # from tag_manager_cli.commands.dev_commands import dev_app
    # from tag_manager_cli.commands.unified_tags import tags_app
    # from tag_manager_cli.commands.discovery_commands import discover_app
    # from tag_manager_cli.commands.system_commands import system_app  # Disabled - Merged into setup
    # from tag_manager_cli.commands.slack_commands import slack_app  # Disabled for now
    # from tag_manager_cli.commands.setup_commands import setup_app
    # from tag_manager_cli.commands.service_commands import service_app  # Disabled - Slack related
    # from tag_manager_cli.commands.task_commands import task_app
    # from tag_manager_cli.commands.update_commands import app as update_app
    # from tag_manager_cli.commands.policy_commands import app as policy_app
    # from tag_manager_cli.commands.ai_commands import app as ai_app
    from tag_manager_cli.utils.onboarding import run_onboarding_wizard, is_first_time_user
    from tag_manager_cli.utils.command_suggestions import show_suggestions

else:
    # Running as module - use relative imports
    from .utils.env_config import settings
    from .utils.aws_auth import aws_auth
    # from .utils.docker_integration import docker_integration  # Removed - Container-free architecture
    from .utils.display_utils import display_main_menu, print_safe, print_error
    # PERFORMANCE OPTIMIZATION: Modules import boto3, so we lazy load them
    # from .modules import (
    #     cost_allocation,
    #     resource_organization,
    #     # docker_management,  # Disabled - Container-free architecture
    #     dev_tools
    # )
    # from .commands.database_commands import database_app  # Disabled - Auto-init handles this
    # PERFORMANCE OPTIMIZATION: Lazy loading - commands imported on-demand
    # from .commands.dev_commands import dev_app
    # from .commands.unified_tags import tags_app
    # from .commands.discovery_commands import discover_app
    # from .commands.system_commands import system_app  # Disabled - Merged into setup
    # from .commands.slack_commands import slack_app  # Disabled for now
    # from .commands.setup_commands import setup_app
    # from .commands.service_commands import service_app  # Disabled - Slack related
    # from .commands.task_commands import task_app
    # from .commands.update_commands import app as update_app
    # from .commands.policy_commands import app as policy_app
    # from .commands.ai_commands import app as ai_app
    from .utils.onboarding import run_onboarding_wizard, is_first_time_user
    from .utils.command_suggestions import show_suggestions

app = typer.Typer(
    name="bluearch-aws-tags",
    help="AWS Tag Manager CLI - Complete solution for AWS resource tagging, cost allocation, and compliance",
    no_args_is_help=False,
    rich_markup_mode="rich",
    add_completion=True,
    context_settings=dict(
        help_option_names=["-h", "--help"],
    ),
)

# === CORE FEATURES (Primary user commands) ===
# PERFORMANCE OPTIMIZATION: Replaced with lazy loading wrapper commands below
# app.add_typer(discover_app, name="discover")
# app.add_typer(tags_app, name="tags")
# app.add_typer(policy_app, name="policy")
# app.add_typer(ai_app, name="ask")

# === INTEGRATIONS (Third-party service integrations) ===
# app.add_typer(slack_app, name="slack")  # Disabled for now

# === SYSTEM MANAGEMENT (Configuration and setup) ===
# app.add_typer(system_app, name="system")  # Disabled - Merged into setup
# app.add_typer(setup_app, name="setup")  # Replaced with lazy wrapper
# app.add_typer(service_app, name="service")  # Disabled - Slack related
# app.add_typer(update_app, name="update")  # Replaced with lazy wrapper
# app.add_typer(task_app, name="tasks")  # Replaced with lazy wrapper
# app.add_typer(docker_management.docker_app, name="docker")  # Disabled - Container-free architecture
# app.add_typer(database_app, name="database")  # Disabled - Auto-init handles this
# app.add_typer(dev_app, name="dev")  # Replaced with lazy wrapper

# === TELEMETRY INTEGRATION ===

# Note: display_main_menu is now imported from display_utils


def handle_menu_selection(choice: str):
    """Handle user menu selection."""
    # Lazy load modules to improve startup performance
    if __name__ == "__main__":
        from tag_manager_cli.modules import resource_organization, dev_tools
        from tag_manager_cli.commands.cost_commands import _interactive_cost_menu
    else:
        from .modules import resource_organization, dev_tools
        from .commands.cost_commands import _interactive_cost_menu

    menu_handlers = {
        "1": _interactive_cost_menu,  # FinOps Cost Analysis (CUR-powered)
        "2": resource_organization.run_resource_organization,
        "3": dev_tools.run_development_tools,
    }

    if choice.lower() == "q":
        print_safe("[yellow]Goodbye![/yellow]")
        raise typer.Exit()

    if choice in menu_handlers:
        try:
            menu_handlers[choice]()
        except Exception as e:
            print_error(f"Error: {str(e)}")
    else:
        print_error(f"Invalid option: {choice}")


def _parse_managed_web_start_args(default_host: str, default_port: int) -> dict:
    args = sys.argv[3:]
    values = {
        "host": default_host,
        "port": default_port,
        "reload": False,
        "log_level": "info",
        "daemon": False,
        "no_browser": False,
    }
    index = 0
    while index < len(args):
        arg = args[index]
        if arg in ("--daemon", "-d"):
            values["daemon"] = True
        elif arg == "--reload":
            values["reload"] = True
        elif arg == "--no-browser":
            values["no_browser"] = True
        elif arg in ("--host", "-H") and index + 1 < len(args):
            index += 1
            values["host"] = args[index]
        elif arg.startswith("--host="):
            values["host"] = arg.split("=", 1)[1]
        elif arg in ("--port", "-p") and index + 1 < len(args):
            index += 1
            values["port"] = int(args[index])
        elif arg.startswith("--port="):
            values["port"] = int(arg.split("=", 1)[1])
        elif arg == "--log-level" and index + 1 < len(args):
            index += 1
            values["log_level"] = args[index]
        elif arg.startswith("--log-level="):
            values["log_level"] = arg.split("=", 1)[1]
        index += 1
    return values


def _maybe_run_managed_web_start() -> None:
    if os.environ.get("BLUEARCH_CORE_MANAGED_WEB_START") != "1":
        return
    if sys.argv[1:3] != ["web", "start"]:
        return
    from tag_manager_cli.commands.web_commands import start

    try:
        start(**_parse_managed_web_start_args("127.0.0.1", 8096))
    except typer.Exit as exc:
        raise SystemExit(exc.exit_code) from exc
    raise SystemExit(0)


_maybe_run_managed_web_start()


@app.command()
def interactive(
    profile: Optional[str] = typer.Option(None, "--profile", "-p", help="AWS profile to use (overrides AWS_PROFILE env var)"),
    show_config: bool = typer.Option(False, "--show-config", help="Show configuration summary and exit")
):
    """
    Start the interactive Tag Manager CLI with guided menu system.

    The interactive mode provides a user-friendly guided interface for all
    tag management operations. Perfect for users who prefer menu-driven
    workflows over command-line arguments.

    Examples:
        interactive                           # Start interactive mode
        interactive --profile my-aws-profile  # Use specific AWS profile
        interactive --show-config            # Show configuration only
    """
    try:
        # Run background health checks
        run_background_health_checks()

        # Set profile if provided
        if profile:
            settings.env.set('AWS_PROFILE', profile)

        # Show configuration if requested
        if show_config:
            settings.print_config_summary()
            return
        
        # Validate required settings
        settings.validate_required_settings()
        
        # Initialize AWS session
        print_safe("[blue]Initializing AWS Tag Manager...[/blue]")
        aws_auth.initialize_session()

        # Container-free architecture - no Docker services needed
        # All operations run directly using SQLite and diskcache

        # Main menu loop
        while True:
            print_safe("\n" + "="*80 + "\n")
            display_main_menu()
            
            choice = Prompt.ask(
                "Please select an option",
                choices=["1", "2", "3", "q"],
                default="1"
            )
            
            handle_menu_selection(choice)
            
    except KeyboardInterrupt:
        print_safe("\n[yellow]Goodbye![/yellow]")
        raise typer.Exit()
    except Exception as e:
        print_error(f"Error: {str(e)}")
        raise typer.Exit(1)







# ========================================
# LAZY LOADING: Revert to eager loading
# ========================================
# The dynamic loading broke subcommands, so we need to load them normally
# but we can still keep the module imports lazy

# Import command apps - we need these at startup for Typer to work correctly
# NOTE: Simplified CLI structure - lifecycle is the flagship feature
# Removed tangential commands: tags, accounts, alarms
# These commands still exist in the codebase for future use if needed
if __name__ == "__main__":
    from tag_manager_cli.commands.discovery_commands import discover_app
    from tag_manager_cli.commands.lifecycle_commands import lifecycle_app
    from tag_manager_cli.commands.policy_commands import app as policy_app
    from tag_manager_cli.commands.ai_commands import app as ai_app
    from tag_manager_cli.commands.setup_commands import setup_app
    from tag_manager_cli.commands.update_commands import app as update_app
    from tag_manager_cli.commands.uninstall_commands import uninstall_app
    from tag_manager_cli.commands.cost_commands import cost_app
    from tag_manager_cli.commands.web_commands import web_app
else:
    from .commands.discovery_commands import discover_app
    from .commands.lifecycle_commands import lifecycle_app
    from .commands.policy_commands import app as policy_app
    from .commands.ai_commands import app as ai_app
    from .commands.setup_commands import setup_app
    from .commands.update_commands import app as update_app
    from .commands.uninstall_commands import uninstall_app
    from .commands.cost_commands import cost_app
    from .commands.web_commands import web_app

# Register the command apps with Typer
# Hybrid policy system: lifecycle + AWS Org policies
app.add_typer(lifecycle_app, name="lifecycle")  # FLAGSHIP - Resource lifecycle management
app.add_typer(discover_app, name="discover")    # Friendly first-run resource discovery alias
app.add_typer(policy_app, name="policy")        # AWS Organizations Tag Policies
app.add_typer(ai_app, name="ask")               # AI helper (can execute commands)
app.add_typer(cost_app, name="cost")            # FinOps cost analysis (CUR-powered)
app.add_typer(setup_app, name="setup")          # One-time setup
app.add_typer(update_app, name="update")        # Update CLI
app.add_typer(uninstall_app, name="uninstall")  # Remove CLI
app.add_typer(web_app, name="web")              # Web dashboard

# Health check integration
def run_background_health_checks():
    """Run optimized background health checks with intelligent scheduling."""
    try:
        import os
        from .utils.smart_health_manager import smart_health_manager

        # Run smart health checks with caching and adaptive intervals
        results = smart_health_manager.run_smart_health_checks()

        # Optional: log results for debugging (only if debug mode)
        if os.environ.get('TAG_MANAGER_DEBUG') == '1' and not results.get('skipped', False):
            checks_performed = results.get('summary', {}).get('checks_performed', 0)
            if checks_performed > 0:
                print_safe(f"[dim]Health checks: {checks_performed} performed[/dim]")

    except Exception:
        # Silently fail if smart health manager can't be imported
        # Fall back to no health checks rather than breaking functionality
        pass


# Default command when no subcommand is provided
def show_main_help():
    """Show the enhanced main CLI help format - focused on lifecycle management."""
    print_safe("\n[bold cyan]AWS Tag Manager CLI[/bold cyan] - Stop zombie resources from eating your AWS budget.\n")

    print_safe("[bold cyan]CORE FEATURES[/bold cyan]:")
    print_safe("- [cyan]lifecycle[/cyan]     - Resource lifecycle management (TTL, expiration, cleanup) [bold yellow]<- MAIN FEATURE[/bold yellow]")
    print_safe("- [cyan]discover[/cyan]      - First-run AWS resource discovery")
    print_safe("- [cyan]cost[/cyan]          - FinOps cost analysis (CUR-powered)")
    print_safe("- [cyan]policy[/cyan]        - AWS Organizations Tag Policies (enterprise governance)")
    print_safe("- [cyan]ask[/cyan]           - AI-powered AWS assistant (natural language queries)")

    print_safe("\n[bold yellow]SYSTEM MANAGEMENT[/bold yellow]:")
    print_safe("- [cyan]setup[/cyan]         - Setup wizard (AWS credentials, multi-account)")
    print_safe("- [cyan]update[/cyan]        - Update CLI to the latest version")
    print_safe("- [cyan]uninstall[/cyan]     - Remove CLI and all AWS resources")
    print_safe("- [cyan]web[/cyan]           - Web dashboard controls (started by Core)\n")

    print_safe("[bold green]QUICK START[/bold green] (new users):")
    print_safe("  [cyan]bluearch-aws-core start --daemon[/cyan] <- Start local services")
    print_safe("  [cyan]bluearch-aws-tags discover all[/cyan]   <- Discover AWS resources first")
    print_safe("  [cyan]bluearch-aws-tags lifecycle wizard[/cyan] <- Recommended! Complete guided workflow\n")

    print_safe("[bold green]MANUAL WORKFLOW[/bold green] (experienced users):")
    print_safe("  1. [dim]bluearch-aws-tags lifecycle policies create[/dim]  - Define resource rules")
    print_safe("  2. [dim]bluearch-aws-tags lifecycle scan[/dim]             - Find matching resources")
    print_safe("  3. [dim]bluearch-aws-tags lifecycle set-ttl[/dim]          - Apply TTL tags")
    print_safe("  4. [dim]bluearch-aws-tags lifecycle review[/dim]           - Manage expiring resources\n")

    print_safe("[bold green]AWS ORG POLICIES[/bold green] (enterprise):")
    print_safe("  [dim]bluearch-aws-tags policy check-access[/dim]           - Check AWS Org access")
    print_safe("  [dim]bluearch-aws-tags policy create[/dim]                 - Create AWS Org Tag Policy")
    print_safe("  [dim]bluearch-aws-tags policy check-compliance[/dim]       - Check resource compliance\n")

    print_safe("[bold green]DAILY OPERATIONS[/bold green]:")
    print_safe("  [dim]bluearch-aws-tags lifecycle scan --expiring 7[/dim]   - Resources expiring in 7 days")
    print_safe("  [dim]bluearch-aws-tags lifecycle review[/dim]              - Interactive review")
    print_safe("  [dim]bluearch-aws-tags lifecycle notify[/dim]              - Send Slack alerts\n")

    print_safe("[bold green]COST ANALYSIS[/bold green]:")
    print_safe("  [dim]bluearch-aws-tags cost setup detect[/dim]             - Detect existing CUR")
    print_safe("  [dim]bluearch-aws-tags cost summary[/dim]                  - Cost overview")
    print_safe("  [dim]bluearch-aws-tags cost services[/dim]                 - Cost by service")
    print_safe("  [dim]bluearch-aws-tags cost compare this-month last-month[/dim] - MoM comparison\n")

    print_safe("[bold green]AI ASSISTANT[/bold green]:")
    print_safe("  [dim]bluearch-aws-tags ask \"what resources are expiring?\"[/dim]")
    print_safe("  [dim]bluearch-aws-tags ask chat[/dim]                      - Interactive AI chat\n")

    print_safe("[bold green]SHELL COMPLETION[/bold green]:")
    print_safe("  [dim]bluearch-aws-tags --install-completion[/dim]      - Enable TAB completion for your shell\n")

    print_safe("For detailed help: [cyan]bluearch-aws-tags discover --help[/cyan] or [cyan]bluearch-aws-tags lifecycle --help[/cyan]")


def _is_bare_discover_invocation() -> bool:
    """Return true only for the help-only public `discover` invocation."""
    return _HELP_ONLY_BARE_DISCOVER


def _ensure_core_for_command(ctx: typer.Context, help_requested: bool, version_requested: bool) -> None:
    """Require a compatible core runtime for product commands.

    `bluearch-aws-tags update` is intentionally exempt so users can repair or install
    the required core runtime through the product updater.
    """
    if ctx.invoked_subcommand in (None, "update", "web") or _is_bare_discover_invocation():
        return
    if help_requested or version_requested:
        return
    if any(arg in sys.argv for arg in ("--help", "-h", "--install-completion", "--show-completion")):
        return
    try:
        if __name__ == "__main__" or not __package__:
            from tag_manager_cli.utils.core_client import MINIMUM_CORE_VERSION, check_core_dependency
        else:
            from .utils.core_client import MINIMUM_CORE_VERSION, check_core_dependency

        check_core_dependency("tag-manager")
    except Exception as exc:
        print_safe("[red][ERROR] bluearch-aws-core is required before using Tags commands.[/red]")
        print_safe(f"[dim]{exc}[/dim]")
        print_safe(f"[cyan]Required version:[/cyan] bluearch-aws-core >= {MINIMUM_CORE_VERSION}")
        print_safe("[cyan]Install or update it with:[/cyan] bluearch-aws-tags update")
        print_safe("[cyan]Start it with:[/cyan] bluearch-aws-core start --daemon")
        raise typer.Exit(1)


@app.callback(invoke_without_command=True)
def main(
    ctx: typer.Context,
    version_flag: bool = typer.Option(False, "--version", "-V", help="Show version and exit"),
    help: bool = typer.Option(False, "--help", "-h", help="Show this message and exit."),
    no_prompt: bool = typer.Option(False, "--no-prompt", help="Disable task prompts (for CI/automation)")
):
    """
    AWS Tag Manager CLI - Stop zombie resources from eating your AWS budget.

    [bold cyan]CORE FEATURES[/bold cyan]:
    - [cyan]lifecycle[/cyan]     - Resource lifecycle management (TTL, expiration, cleanup)
    - [cyan]discover[/cyan]      - First-run AWS resource discovery
    - [cyan]cost[/cyan]          - FinOps cost analysis (CUR-powered)
    - [cyan]policy[/cyan]        - AWS Organizations Tag Policies (enterprise governance)
    - [cyan]ask[/cyan]           - AI-powered AWS assistant (natural language queries)

    [bold yellow]SYSTEM MANAGEMENT[/bold yellow]:
    - [cyan]setup[/cyan]         - Setup wizard (AWS credentials, multi-account)
    - [cyan]update[/cyan]        - Update CLI to the latest version
    - [cyan]uninstall[/cyan]     - Remove CLI and all AWS resources

    [bold green]QUICK START[/bold green]:
    Run [cyan]bluearch-aws-tags discover all[/cyan] first, then [cyan]bluearch-aws-tags lifecycle wizard[/cyan] for guided setup.

    [bold green]MANUAL WORKFLOW[/bold green]:
    1. [dim]lifecycle policies create[/dim]  - Define resource rules
    2. [dim]lifecycle scan[/dim]             - Find matching resources
    3. [dim]lifecycle set-ttl[/dim]          - Apply TTL tags
    4. [dim]lifecycle review[/dim]           - Manage expiring resources
    """
    if version_flag:
        import subprocess
        from rich.prompt import Confirm

        try:
            if __name__ == "__main__" or not __package__:
                from tag_manager_cli import __version__
                from tag_manager_cli.utils.version_checker import get_updates, is_dev_version
            else:
                from . import __version__
                from .utils.version_checker import get_updates, is_dev_version
            version_str = __version__
        except:
            version_str = "development"

        # Detect if this is a dev or prod version
        is_dev = is_dev_version(version_str)
        channel = "development" if is_dev else "production"

        print_safe(f"AWS Tag Manager CLI {version_str} ({channel})")

        # Skip update check for --help to improve performance
        # Only check for updates when explicitly running --version without other flags
        import sys
        skip_update_check = os.environ.get("TAG_MANAGER_SKIP_UPDATE_CHECK", "").lower() in {
            "1",
            "true",
            "yes",
            "on",
        }
        if (
            not skip_update_check
            and not os.environ.get("BLUEARCH_CORE_VERSION_PROBE")
            and not help
            and '--help' not in sys.argv
            and '-h' not in sys.argv
        ):
            # Check for available updates from the appropriate channel
            try:
                # For dev versions, also check prod to see if stable version is available
                if is_dev:
                    # First check production updates
                    prod_updates = get_updates(force_development=False)
                    if prod_updates:
                        print_safe(f"\n[yellow]You are running a development build.[/yellow]")
                        print_safe(f"[green]A stable production version is available: {prod_updates[0]['version']}[/green]")
                        if Confirm.ask("Would you like to upgrade to the production version?", default=False):
                            print_safe("\n[blue]Upgrading to production version...[/blue]")
                            cmd = "brew upgrade bluearchio/tap/bluearch-aws-tags"
                            print_safe(f"[dim]Executing: {cmd}[/dim]")
                            subprocess.run(cmd.split())
                            return
                        print_safe("")  # Add spacing

                    # Then check dev updates
                    updates = get_updates(force_development=True)
                else:
                    # For prod versions, check prod updates
                    updates = get_updates(force_development=False)

                if updates:
                    print_safe(f"\n[yellow]Updates available ({channel} channel):[/yellow]")
                    for update in updates[:3]:  # Show only the latest 3 updates
                        print_safe(f"  - [green]{update['version']}[/green] - {update['date']}")
                        if update['message'].strip():
                            # Clean up the message - remove JSON escaping and extra quotes
                            message = update['message'].replace('\\n', '\n').strip('"').strip()
                            if message:
                                # Split into lines and indent properly
                                lines = message.split('\n')
                                for line in lines:
                                    if line.strip():
                                        print_safe(f"    {line.strip()}")
                            print_safe("")  # Add spacing after each update
                    print_safe(f"\nRun [cyan]bluearch-aws-tags update[/cyan] to update")
                else:
                    print_safe("[green]You are up to date![/green]")
            except Exception as e:
                # Silently fail on update check - don't break version display
                pass  # Don't even print the error for performance

        return

    _ensure_core_for_command(ctx, help, version_flag)

    # Check for stale tasks when running commands (not for help or version)
    # Skip task prompts if --help flag is present
    import sys
    is_help_command = '--help' in sys.argv or '-h' in sys.argv

    if ctx.invoked_subcommand is not None and not _is_bare_discover_invocation() and not no_prompt and not is_help_command:
        # Only check tasks for actual commands, not help/version
        try:
            if __name__ == "__main__" or not __package__:
                from tag_manager_cli.utils.task_tracker import check_and_prompt_tasks, run_maintenance_tasks
            else:
                from .utils.task_tracker import check_and_prompt_tasks, run_maintenance_tasks

            # Check if we should prompt for tasks
            tasks_to_run = check_and_prompt_tasks(no_prompt=no_prompt)

            if tasks_to_run:
                # Run selected tasks before executing the command
                run_maintenance_tasks(tasks_to_run)
                print_safe("")  # Add spacing before command output
        except ImportError:
            # Task tracker not available (shouldn't happen in normal operation)
            pass
        except Exception:
            # Don't break the CLI if task checking fails
            pass

    if help or ctx.invoked_subcommand is None:
        show_main_help()

        # Check if this is a first-time user and offer setup wizard (only when no help flag)
        if not help and is_first_time_user():
            show_suggestions("first_time", show_workflow=True, workflow_type="initial_setup")

        if help:
            raise typer.Exit()


@app.command()
def setup():
    """
    Legacy setup command - redirects to new setup wizard.

    For the full production setup wizard, use: bluearch-aws-tags setup wizard
    """
    print_safe("[yellow]This command has been replaced with the production setup wizard.[/yellow]")
    print_safe("Run: [cyan]bluearch-aws-tags setup wizard[/cyan] for complete guided setup")
    print_safe("Or run: [cyan]bluearch-aws-tags setup validate[/cyan] to check system status")

    # Still run the legacy onboarding for backward compatibility
    run_onboarding_wizard()


def cli():
    """Entry point for the CLI when used as a module."""
    app()


if __name__ == "__main__":
    cli()
