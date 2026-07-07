"""System management commands for Tag Manager CLI.

TODO: This module is disabled as its functionality has been merged into setup_commands.
All system validation, configuration, and management features are now available
through the 'setup' command for better organization.
"""

import os
import typer
from rich.panel import Panel

from ..utils.env_config import settings
from ..utils.core_client import request_core
from ..utils.display_utils import (
    display_system_status_table, 
    display_validation_results,
    print_safe,
    print_error,
    print_success,
    print_warning,
    display_safe_panel
)
system_app = typer.Typer(
    help="Application configuration, status, and system management",
    no_args_is_help=False
)

def show_system_help():
    """Show the enhanced system help format."""
    print_safe("\n[bold cyan]System Management Commands[/bold cyan] - Configure and monitor your installation\n")

    print_safe("[bold green]SYSTEM INFORMATION[/bold green] (check what you have):")
    print_safe("- [cyan]config[/cyan]        - Show current configuration and environment settings")
    print_safe("- [cyan]version[/cyan]       - Show version information and build details")
    print_safe("- [cyan]status[/cyan]        - Check system health and service connectivity\n")

    print_safe("[bold yellow]SETUP & TROUBLESHOOTING[/bold yellow] (fix issues):")
    print_safe("- [cyan]validate[/cyan]      - Comprehensive system setup validation")
    print_safe("- [cyan]reset[/cyan]         - Reset system to clean state (use with caution)\n")

    print_safe("[bold green]TYPICAL WORKFLOW[/bold green]:")
    print_safe("1. [dim]system validate[/dim]                     # Verify everything is working")
    print_safe("2. [dim]system status[/dim]                       # Check component health")
    print_safe("3. [dim]system config[/dim]                       # Review configuration\n")

    print_safe("If you have issues:")
    print_safe("- Check [cyan]system status[/cyan] for component problems")
    print_safe("- Run [cyan]system validate[/cyan] for detailed diagnostics")
    print_safe("- Use [cyan]system reset --confirm[/cyan] for clean reinstall\n")

    print_safe("For detailed help on any command: [cyan]system [COMMAND] --help[/cyan]")

@system_app.callback(invoke_without_command=True)
def system_main(
    ctx: typer.Context,
    help: bool = typer.Option(False, "--help", "-h", help="Show this message and exit.")
):
    """
    Application configuration, status, and system management.

    These commands help you configure, monitor, and troubleshoot your Tag Manager
    installation and ensure all components are working correctly.
    """
    if help or ctx.invoked_subcommand is None:
        show_system_help()
        if help:
            raise typer.Exit()


@system_app.command("config")
def show_config():
    """
    Display current application configuration and environment settings.
    
    Shows all configuration values, environment variables, and system status
    to help with troubleshooting and verification of your setup.
    """
    print_safe("[blue][CONFIG] Application Configuration[/blue]\n")
    settings.print_config_summary()


@system_app.command("version")
def show_version():
    """
    Show version information and build details.
    
    Displays the current version of the Tag Manager CLI along with
    component versions and system information.
    """
    try:
        from .. import __version__
        version_str = __version__
    except ImportError:
        version_str = "development"
    
    version_content = (
        f"[bold cyan]AWS Tag Manager CLI[/bold cyan]\n"
        f"Version: [white]{version_str}[/white]\n"
        f"Built for comprehensive AWS tag management and automation"
    )
    
    display_safe_panel(version_content, "Version Information", "blue")


@system_app.command("status")
def show_system_status():
    """
    Show overall system health and service status.
    
    Checks the status of all system components including AWS connectivity,
    database connection, Redis cache, and background services.
    """
    print_safe("[blue][CHECK] System Health Check[/blue]\n")
    
    status_data = []
    
    # Check AWS Configuration
    try:
        settings.validate_required_settings()
        aws_status = "OK Connected"
        aws_details = f"Profile: {settings.env.get('AWS_PROFILE', 'default')}"
    except Exception as e:
        aws_status = "ERROR Error"
        aws_details = str(e)
    
    status_data.append(("AWS Configuration", aws_status, aws_details))
    
    # Check Core runtime and storage
    try:
        health = request_core("GET", "/api/v1/core/health", service_token=False, timeout=2.0)
        if not health.get("db_ready"):
            raise RuntimeError("Core database is not ready")
        db_status = "OK Connected"
        db_details = f"bluearch-core {health.get('version', 'unknown')}"
    except Exception as e:
        db_status = "ERROR Error"
        db_details = str(e)
    
    status_data.append(("Database", db_status, db_details))
    
    # Check Local Cache
    try:
        from ..utils.cache import cache
        if cache.enabled:
            stats = cache.get_stats()
            cache_status = "OK Active"
            cache_details = f"Hit rate: {stats.get('hit_rate', 0):.1%}, Items: {stats.get('disk_cache', {}).get('count', 0)}"
        else:
            cache_status = "WARN Disabled"
            cache_details = "Caching disabled"
    except Exception as e:
        cache_status = "WARN Unavailable"
        cache_details = f"Error: {str(e)}"

    status_data.append(("Local Cache", cache_status, cache_details))
    
    # Check Docker Services
    try:
        from ..utils.docker_integration import docker_integration
        if docker_integration.service_manager.check_docker_availability():
            docker_status = "OK Available"
            docker_details = "Docker daemon running"
            
            # Check service status
            service_status = docker_integration.service_manager.get_service_status()
            running_services = [svc for svc, status in service_status.items() if status == 'running']
            
            if running_services:
                docker_details += f" ({len(running_services)} services running)"
            
        else:
            docker_status = "WARN Unavailable"
            docker_details = "Docker not available"
    except Exception:
        docker_status = "WARN Unavailable"
        docker_details = "Docker not available"
    
    status_data.append(("Docker Services", docker_status, docker_details))
    
    display_system_status_table(status_data)
    
    # Show next steps if there are issues
    if "ERROR" in [aws_status, db_status]:
        print_warning("\nWARN  Issues detected. Try these commands:")
        if "ERROR" in aws_status:
            print_safe("   [dim]aws sso login[/dim]")
            print_safe("   [dim]export AWS_PROFILE=your-profile[/dim]")
        if "ERROR" in db_status:
            print_safe("   [dim]tag-manager database init[/dim]")


@system_app.command("validate")
def validate_setup():
    """
    Validate the complete system setup and configuration.
    
    Performs comprehensive checks of all system components, configuration files,
    AWS permissions, and dependencies to ensure everything is properly configured.
    """
    print_safe("[blue][SEARCH] Validating System Setup[/blue]\n")
    
    validation_results = []
    
    # Check AWS Configuration
    print_safe("1. Checking AWS configuration...")
    try:
        settings.validate_required_settings()
        validation_results.append(("AWS Configuration", True, "Profile and credentials configured"))
    except Exception as e:
        validation_results.append(("AWS Configuration", False, str(e)))
    
    # Check AWS Connectivity
    print_safe("2. Testing AWS connectivity...")
    try:
        from ..utils.aws_auth import aws_auth
        aws_auth.initialize_session()
        validation_results.append(("AWS Connectivity", True, "Successfully connected to AWS"))
    except Exception as e:
        validation_results.append(("AWS Connectivity", False, str(e)))
    
    # Check Core storage contract
    print_safe("3. Validating core storage contract...")
    try:
        request_core(
            "GET",
            "/api/v1/storage/core/resources",
            service_token=True,
            params=[("limit", 1)],
            timeout=5.0,
        )
        request_core(
            "GET",
            "/api/v1/storage/tag-manager/tagging-rules",
            service_token=True,
            params=[("limit", 1)],
            timeout=5.0,
        )
        request_core(
            "GET",
            "/api/v1/storage/tag-manager/tagging-audit-log",
            service_token=True,
            params=[("limit", 1)],
            timeout=5.0,
        )
        validation_results.append(("Core Storage", True, "Required core storage collections are accessible"))
    except Exception as e:
        validation_results.append(("Core Storage", False, str(e)))
    
    # Check Required Dependencies
    print_safe("4. Checking Python dependencies...")
    try:
        import boto3
        import typer
        import rich
        import sqlalchemy
        validation_results.append(("Python Dependencies", True, "All required packages available"))
    except ImportError as e:
        validation_results.append(("Python Dependencies", False, f"Missing package: {e}"))
    
    # Check Optional Dependencies
    print_safe("5. Checking optional components...")
    optional_status = []
    
    try:
        import redis
        optional_status.append("Redis support")
    except ImportError:
        pass
    
    try:
        import docker
        optional_status.append("Docker support")
    except ImportError:
        pass
    
    if optional_status:
        validation_results.append(("Optional Components", True, f"Available: {', '.join(optional_status)}"))
    else:
        validation_results.append(("Optional Components", False, "No optional components available"))
    
    # Display results
    print_safe("\n" + "="*60 + "\n")
    
    display_validation_results(validation_results)
    
    all_passed = all(passed for _, passed, _ in validation_results)
    
    if all_passed:
        print_success("\nOK All validations passed! System is ready to use.")
        print_safe("Start with: [cyan]tag-manager interactive[/cyan] or [cyan]tag-manager tags scan[/cyan]")
    else:
        print_error("\nERROR Some validations failed. Please address the issues above.")
        print_safe("For help: [cyan]bluearch-aws-tags system config[/cyan] or [cyan]bluearch-aws-tags --help[/cyan]")


@system_app.command("reset")
def reset_system(
    confirm: bool = typer.Option(False, "--confirm", help="Confirm the reset operation"),
    keep_config: bool = typer.Option(True, "--keep-config", help="Keep configuration files")
):
    """
    Reset system to clean state (use with caution).
    
    This command clears all cached data, resets the database, and optionally
    removes configuration files. Use this for troubleshooting or clean reinstalls.
    
    WARNING: This will delete all local tagging data and audit logs.
    """
    if not confirm:
        print_error("This operation will reset all system data!")
        print_safe("Add --confirm flag to proceed with reset")
        return
    
    print_warning("WARN  Resetting system to clean state...")
    
    # Clear Local cache
    try:
        from ..utils.cache import cache
        if cache.enabled:
            count = cache.cache.clear()
            print_success(f"OK Cleared local cache ({count} items)")
    except Exception as e:
        print_warning(f"WARN Could not clear cache: {e}")
    
    print_warning("WARN Storage is owned by bluearch-core and was not reset by Tag Manager.")
    print_safe("Use [cyan]bluearch-core db backup[/cyan] before any core storage reset operation.")
    
    # Remove config files if requested
    if not keep_config:
        import os
        from pathlib import Path
        
        config_files = [
            Path.home() / ".tag-manager" / "config.json",
            Path.cwd() / ".env"
        ]
        
        for config_file in config_files:
            if config_file.exists():
                config_file.unlink()
                print_success(f"OK Removed {config_file}")
    
    print_success("\nOK System reset complete!")
    print_safe("Run validation: [cyan]tag-manager system validate[/cyan]")
