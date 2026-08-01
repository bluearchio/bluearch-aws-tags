"""
Setup Wizard Commands for AWS Tag Manager CLI

Interactive setup wizard for initial configuration.
Handles AWS profile selection and guides through setup.
"""

import os
import sys
import subprocess
import json
import time
from pathlib import Path
from datetime import datetime
from typing import Optional
import typer
from rich.console import Console
from rich.prompt import Prompt, Confirm
from rich.table import Table
from rich.panel import Panel
from ..utils.aws_profile_detector import AWSProfileDetector
from ..utils.aws_auth import aws_auth
from ..utils.command_suggestions import show_suggestions
from ..utils.env_config import settings
from ..utils.core_client import CoreRuntimeError, request_core

console = Console()
setup_app = typer.Typer(
    help="Setup and configuration wizard",
    no_args_is_help=False
)

# Constants
CLI_MODULE = "tag_manager_cli.main"


def print_safe(message: str):
    """Print message safely without emojis for PyInstaller compatibility."""
    console.print(message)


def print_error(message: str):
    """Print error message."""
    console.print(f"[red][ERROR] {message}[/red]")


def print_success(message: str):
    """Print success message."""
    console.print(f"[green][OK] {message}[/green]")


def print_warning(message: str):
    """Print warning message."""
    console.print(f"[yellow][WARN] {message}[/yellow]")


def _format_context_time(value) -> str:
    if not value:
        return "-"
    if hasattr(value, "strftime"):
        return value.strftime("%Y-%m-%d %H:%M")
    if isinstance(value, str):
        try:
            from datetime import datetime

            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            return parsed.strftime("%Y-%m-%d %H:%M")
        except ValueError:
            return value
    return str(value)


ASSUME_ROLE_STORAGE_FIELDS = {
    "id",
    "account_id",
    "role_arn",
    "role_name",
    "external_id",
    "is_active",
    "enabled",
    "alias",
    "created_at",
    "updated_at",
    "last_used_at",
}


def _payload_from_core_record(record: dict) -> dict:
    payload = dict((record or {}).get("payload", record) or {})
    payload.setdefault("id", (record or {}).get("id") or (record or {}).get("record_key") or payload.get("id"))
    return payload


def _coerce_assume_role_payload(payload: dict) -> dict:
    return {key: value for key, value in payload.items() if key in ASSUME_ROLE_STORAGE_FIELDS}


def _list_assume_role_configs() -> list[dict]:
    records = request_core(
        "GET",
        "/api/v1/storage/core/assume-role-configurations",
        service_token=True,
        params=[("limit", 10000), ("order_by", "created_at"), ("descending", "false")],
        timeout=10.0,
    )
    return [_payload_from_core_record(record) for record in records or []]


def _find_assume_role_config(account_id: str, role_name: str | None = None) -> Optional[dict]:
    filters = [("filter", f"account_id={account_id}"), ("limit", 10000)]
    records = request_core(
        "GET",
        "/api/v1/storage/core/assume-role-configurations",
        service_token=True,
        params=filters,
        timeout=10.0,
    )
    configs = [_payload_from_core_record(record) for record in records or []]
    if role_name:
        configs = [config for config in configs if config.get("role_name") == role_name]
    return configs[0] if configs else None


def _create_assume_role_config(payload: dict) -> dict:
    record = request_core(
        "POST",
        "/api/v1/storage/core/assume-role-configurations",
        service_token=True,
        json={"payload": _coerce_assume_role_payload(payload)},
        timeout=10.0,
    )
    return _payload_from_core_record(record)


def _update_assume_role_config(record_id: str, payload: dict) -> dict:
    record = request_core(
        "PUT",
        f"/api/v1/storage/core/assume-role-configurations/{record_id}",
        service_token=True,
        json={"payload": _coerce_assume_role_payload(payload)},
        timeout=10.0,
    )
    return _payload_from_core_record(record)


def _save_active_assume_role_config(account_id: str, role_arn: str, role_name: str, external_id: Optional[str]) -> bool:
    for config in _list_assume_role_configs():
        if config.get("is_active"):
            config["is_active"] = False
            _update_assume_role_config(config["id"], config)

    existing = _find_assume_role_config(account_id, role_name)
    payload = {
        "account_id": account_id,
        "role_arn": role_arn,
        "role_name": role_name,
        "external_id": external_id,
        "is_active": True,
        "enabled": True,
        "updated_at": datetime.utcnow().isoformat(),
    }
    if existing:
        _update_assume_role_config(existing["id"], {**existing, **payload})
        return True
    _create_assume_role_config(payload)
    return False


def _list_storage_records(
    namespace: str,
    collection: str,
    *,
    limit: int = 10000,
    filters: list[tuple[str, str]] | None = None,
) -> list[dict]:
    params: list[tuple[str, str | int]] = [("limit", limit)]
    for key, value in filters or []:
        params.append(("filter", f"{key}={value}"))
    return request_core(
        "GET",
        f"/api/v1/storage/{namespace}/{collection}",
        service_token=True,
        params=params,
        timeout=10.0,
    ) or []


def _count_storage_records(namespace: str, collection: str, *, filters: list[tuple[str, str]] | None = None) -> int:
    return len(_list_storage_records(namespace, collection, filters=filters))


def _delete_storage_record(namespace: str, collection: str, record_id: str) -> None:
    request_core(
        "DELETE",
        f"/api/v1/storage/{namespace}/{collection}/{record_id}",
        service_token=True,
        timeout=10.0,
    )


def _submit_core_setup_job(
    path: str,
    *,
    payload: dict | None = None,
    action: str,
    timeout_seconds: int = 900,
) -> dict:
    """Submit a core-owned setup job and wait for completion."""
    job = request_core(
        "POST",
        path,
        service_token=True,
        json=payload or {},
        timeout=20.0,
    )
    job_id = job.get("job_id") or job.get("id")
    if not job_id:
        raise RuntimeError(f"bluearch-aws-core did not return a job id for {action}")
    print_safe(f"[cyan]{action} started in bluearch-aws-core (job {job_id})[/cyan]")
    return _wait_for_core_setup_job(str(job_id), action, timeout_seconds=timeout_seconds)


def _wait_for_core_setup_job(job_id: str, action: str, *, timeout_seconds: int = 900) -> dict:
    deadline = time.time() + timeout_seconds
    last_message = None
    last_progress = None
    while time.time() < deadline:
        job = request_core("GET", f"/api/v1/jobs/{job_id}", timeout=10.0)
        progress = job.get("progress")
        message = job.get("progress_message") or job.get("message") or job.get("status")
        if message != last_message or progress != last_progress:
            if progress is not None:
                console.print(f"[dim]{int(progress):>3}% {message}[/dim]")
            else:
                console.print(f"[dim]{message}[/dim]")
            last_message = message
            last_progress = progress
        if job.get("status") == "completed":
            return job.get("result") or {}
        if job.get("status") == "failed":
            raise RuntimeError(job.get("error") or message or f"{action} failed")
        time.sleep(3)
    raise RuntimeError(f"Timed out waiting for bluearch-aws-core job {job_id}")


def _print_core_stackset_status(status_payload: dict) -> None:
    if not status_payload.get("exists"):
        print_safe("Cross-account StackSet is not deployed.")
        return
    print_safe(f"StackSet status: [cyan]{status_payload.get('status', 'UNKNOWN')}[/cyan]")
    if status_payload.get("template_version"):
        print_safe(f"Template version: [cyan]{status_payload.get('template_version')}[/cyan]")
    instances = status_payload.get("instances") or []
    if not instances:
        print_safe("[dim]No stack instances found.[/dim]")
        return
    table = Table(title=f"Stack Instances ({len(instances)})")
    table.add_column("Account", style="cyan")
    table.add_column("Region")
    table.add_column("Status")
    table.add_column("Reason", style="dim")
    for item in instances:
        table.add_row(
            item.get("account_id") or "-",
            item.get("region") or "-",
            item.get("status") or "UNKNOWN",
            item.get("status_reason") or "-",
        )
    console.print(table)


def _parse_csv_option(value: Optional[str]) -> list[str] | None:
    if not value:
        return None
    parsed = [item.strip() for item in value.split(",") if item.strip()]
    return parsed or None


def _validate_shared_setup_via_core() -> None:
    payload = request_core("GET", "/api/v1/setup/validate", timeout=30.0)
    checks = payload.get("checks") or []
    table = Table(title="Shared Setup Validation")
    table.add_column("Check", style="cyan")
    table.add_column("Status")
    table.add_column("Message")
    for check in checks:
        status = str(check.get("status") or "unknown")
        style = "green" if status == "ok" else "yellow" if status == "warning" else "red"
        table.add_row(
            str(check.get("name") or "-"),
            f"[{style}]{status}[/{style}]",
            str(check.get("message") or "-"),
        )
    console.print(table)
    overall = str(payload.get("overall") or "unknown")
    overall_style = "green" if overall == "ok" else "yellow" if overall == "degraded" else "red"
    print_safe(f"\nSetup status: [{overall_style}]{overall}[/{overall_style}]")
    if overall not in {"ok", "healthy"}:
        raise typer.Exit(1)


def show_setup_help():
    """Show enhanced help for setup commands."""
    print_safe("\n[bold cyan]Setup & Configuration Commands[/bold cyan] - Get started quickly\n")

    print_safe("[bold green]INTERACTIVE SETUP[/bold green] (recommended for new users):")
    print_safe("- [cyan]wizard[/cyan]        - Complete guided setup wizard")
    print_safe("- [cyan]validate[/cyan]      - Verify your setup is working correctly\n")

    print_safe("[bold yellow]INDIVIDUAL COMPONENTS[/bold yellow] (configure separately):")
    print_safe("- [cyan]aws[/cyan]           - Configure AWS profile and credentials")
    print_safe("- [cyan]database[/cyan]      - Initialize database and migrations")
    print_safe("- [cyan]assume-role[/cyan]   - Configure assume-role authentication")
    print_safe("- [cyan]multi-account[/cyan] - Deploy cross-account StackSet for multi-account access\n")

    print_safe("[bold green]TYPICAL WORKFLOW[/bold green]:")
    print_safe("1. [dim]setup wizard[/dim]                       # Complete interactive setup")
    print_safe("2. [dim]setup validate[/dim]                     # Verify everything works")
    print_safe("3. [dim]lifecycle scan[/dim]                     # Scan AWS resources")
    print_safe("4. [dim]lifecycle set-ttl[/dim]                  # Apply TTL tags\n")

    print_safe("[bold blue]MULTI-ACCOUNT SETUP[/bold blue] (AWS Organizations):")
    print_safe("- [dim]setup multi-account[/dim]                 # Deploy cross-account IAM roles")
    print_safe("- [dim]lifecycle scan --multi-account[/dim]      # Scan all enabled accounts\n")

    print_safe("Pro tips:")
    print_safe("- Use [cyan]wizard[/cyan] for guided step-by-step configuration")
    print_safe("- Run [cyan]validate[/cyan] after any configuration changes")
    print_safe("- Use [cyan]multi-account[/cyan] to enable scanning across AWS accounts")


@setup_app.callback(invoke_without_command=True)
def setup_main(
    ctx: typer.Context,
    help: bool = typer.Option(False, "--help", "-h", help="Show this message and exit.")
):
    """
    Interactive setup wizard for new users - Get started quickly and easily.

    Guided configuration for AWS profiles, database initialization, and system
    validation. Perfect for first-time users and new installations.
    """
    if help or ctx.invoked_subcommand is None:
        show_setup_help()
        if help:
            raise typer.Exit()


@setup_app.command("wizard")
def setup_wizard(
    skip_aws: bool = typer.Option(False, "--skip-aws", help="Skip AWS profile setup"),
    skip_discovery: bool = typer.Option(False, "--skip-discovery", help="Skip initial resource discovery")
):
    """
    Interactive setup wizard for Tag Manager CLI.

    This wizard will:
    1. Configure AWS profile and credentials
    2. Initialize database
    3. Run initial resource discovery
    """
    console.print(Panel.fit(
        "[bold blue]AWS Tag Manager CLI - Setup Wizard[/bold blue]\n"
        "This wizard will guide you through the initial setup process.",
        border_style="blue"
    ))

    # Step 1: AWS Profile Setup
    if not skip_aws:
        print_safe("\n[bold]Step 1: AWS Profile Configuration[/bold]")
        print_safe("=" * 50)

        profile_name = setup_aws_profile()
        if not profile_name:
            print_error("AWS profile setup failed. Cannot continue.")
            raise typer.Exit(1)

        # Export AWS_PROFILE for current session
        os.environ['AWS_PROFILE'] = profile_name
        print_success(f"AWS_PROFILE set to: {profile_name}")
    else:
        profile_name = os.environ.get('AWS_PROFILE')
        if not profile_name:
            print_error("AWS_PROFILE not set and --skip-aws was used")
            raise typer.Exit(1)

    # Step 2: Initialize Database
    print_safe("\n[bold]Step 2: Database Initialization[/bold]")
    print_safe("=" * 50)

    if Confirm.ask("Initialize database?", default=True):
        initialize_database()

    # Step 3: Initial Resource Discovery
    if not skip_discovery:
        print_safe("\n[bold]Step 3: Initial AWS Resource Discovery[/bold]")
        print_safe("=" * 50)

        if Confirm.ask("Run initial AWS resource discovery?", default=True):
            run_initial_discovery()

    # Step 4: Validation
    print_safe("\n[bold]Step 4: Setup Validation[/bold]")
    print_safe("=" * 50)

    validate_setup_simple()

    # Complete!
    console.print(Panel.fit(
        "[bold green]Setup Complete![/bold green]\n\n"
        "The AWS Tag Manager CLI is ready to use.\n\n"
        "Next steps:\n"
        "1. Run [cyan]bluearch-aws-tags lifecycle wizard[/cyan] for guided workflow\n"
        "2. Or run [cyan]bluearch-aws-tags lifecycle scan[/cyan] to scan resources",
        border_style="green"
    ))

    # Show suggestions for next steps
    show_suggestions("setup.wizard.complete", data={"profile": profile_name})


@setup_app.command("validate")
def validate_command(
    iam: bool = typer.Option(False, "--iam", help="Show verbose IAM policy details for missing permissions"),
):
    """
    Validate your Tag Manager CLI setup.

    Performs comprehensive checks of all system components, AWS configuration,
    database schema, and dependencies to ensure everything is properly configured.

    Use --iam to display the full JSON IAM policies needed to fix missing permissions.
    """
    if not iam:
        print_safe("[blue][SEARCH] Validating shared setup through bluearch-aws-core[/blue]\n")
        try:
            _validate_shared_setup_via_core()
        except CoreRuntimeError as exc:
            print_error(str(exc))
            raise typer.Exit(1) from exc
        return

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

    # Check Database Schema
    print_safe("3. Validating database schema...")
    try:
        status = request_core("GET", "/api/v1/core/db/status", timeout=10.0)
        _list_storage_records("core", "resources", limit=1)
        _list_storage_records("tag-manager", "tagging-rules", limit=1)

        validation_results.append(
            (
                "Database Schema",
                True,
                f"Core database accessible ({status.get('table_count', 0)} tables)",
            )
        )
    except Exception as e:
        validation_results.append(("Database Schema", False, str(e)))

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

    # Check IAM Permissions
    print_safe("5. Checking IAM permissions...")
    try:
        from ..utils.iam_permission_validator import IAMPermissionValidator, ValidationReport
        from ..utils.aws_auth import aws_auth

        # Ensure session is initialized
        if aws_auth.session:
            validator = IAMPermissionValidator(session=aws_auth.session)
            report = validator.validate()

            if report.all_passed:
                validation_results.append((
                    "IAM Permissions",
                    True,
                    f"All {report.total_required} required permissions granted"
                ))
            elif report.error_message:
                # Partial check or unable to fully validate
                validation_results.append((
                    "IAM Permissions",
                    False,
                    report.error_message
                ))

                # If the error is about missing SimulatePrincipalPolicy, show additional warning
                if "iam:SimulatePrincipalPolicy" in report.error_message:
                    print_safe("\n[bold yellow]WARNING: Permission Validator Disabled[/bold yellow]")
                    print_safe("[yellow]The IAM permission validator cannot run without 'iam:SimulatePrincipalPolicy' permission.[/yellow]")

                    if iam:
                        print_safe("\n[bold yellow]To enable permission checking, add this to your IAM policy:[/bold yellow]")
                        simulator_policy = json.dumps({
                            "Version": "2012-10-17",
                            "Statement": [
                                {
                                    "Sid": "TagManagerCLIPermissionValidator",
                                    "Effect": "Allow",
                                    "Action": "iam:SimulatePrincipalPolicy",
                                    "Resource": "*"
                                }
                            ]
                        }, indent=2)
                        print_safe("\n[white]" + simulator_policy + "[/white]\n")
            else:
                # Missing permissions
                missing_count = len(report.missing_actions)
                summary = f"Missing {missing_count} permissions"

                # Add details about affected features
                if report.affected_commands:
                    affected_features = set()
                    for action_features in report.affected_commands.values():
                        affected_features.update(action_features)

                    # Show first few affected features
                    feature_list = list(affected_features)[:3]
                    if len(affected_features) > 3:
                        feature_list.append(f"and {len(affected_features) - 3} more")
                    summary += f" affecting: {', '.join(feature_list)}"

                validation_results.append((
                    "IAM Permissions",
                    False,
                    summary
                ))

                if missing_count > 0 and iam:
                    # --iam flag: show the full JSON policy
                    print_safe("\n[bold yellow]Full IAM policy for missing permissions:[/bold yellow]")
                    missing_policy_json = validator.generate_missing_permissions_json(
                        report.missing_actions, report.policy_doc
                    )
                    print_safe("\n[white]" + missing_policy_json + "[/white]\n")

            # Check assume-role bootstrap permissions separately
            if not report.all_passed:
                print_safe("6. Checking assume-role bootstrap permissions...")
                try:
                    principal_arn, _ = validator.get_current_principal()
                    can_bootstrap, _, bootstrap_missing = validator.check_assume_role_bootstrap(principal_arn)

                    if can_bootstrap:
                        validation_results.append((
                            "Assume Role Bootstrap",
                            True,
                            "Can deploy IAM role via: bluearch-aws-tags setup assume-role"
                        ))
                    else:
                        bootstrap_summary = f"Missing {len(bootstrap_missing)} permissions"
                        bootstrap_actions_str = ', '.join(sorted(bootstrap_missing)[:3])
                        if len(bootstrap_missing) > 3:
                            bootstrap_actions_str += f", and {len(bootstrap_missing) - 3} more"
                        bootstrap_summary += f": {bootstrap_actions_str}"
                        validation_results.append((
                            "Assume Role Bootstrap",
                            False,
                            bootstrap_summary
                        ))

                    if iam:
                        # --iam flag: show the bootstrap policy
                        print_safe("\n[bold yellow]Bootstrap IAM policy (minimum for assume-role deploy):[/bold yellow]")
                        bootstrap_policy = json.dumps(
                            validator.ASSUME_ROLE_BOOTSTRAP_POLICY, indent=2
                        )
                        print_safe("\n[white]" + bootstrap_policy + "[/white]\n")

                except Exception as e:
                    validation_results.append((
                        "Assume Role Bootstrap",
                        False,
                        f"Error checking bootstrap permissions: {str(e)}"
                    ))
        else:
            validation_results.append((
                "IAM Permissions",
                False,
                "AWS session not initialized (check AWS configuration first)"
            ))
    except ImportError:
        validation_results.append((
            "IAM Permissions",
            False,
            "IAM validator module not found"
        ))
    except Exception as e:
        validation_results.append((
            "IAM Permissions",
            False,
            f"Error checking permissions: {str(e)}"
        ))

    # Display results
    print_safe("\n" + "="*60 + "\n")

    from ..utils.display_utils import display_validation_results
    display_validation_results(validation_results)

    all_passed = all(passed for _, passed, _ in validation_results)

    if all_passed:
        print_success("\nOK All validations passed! System is ready to use.")
        print_safe("Start with: [cyan]bluearch-aws-tags lifecycle wizard[/cyan] or [cyan]bluearch-aws-tags lifecycle scan[/cyan]")
    else:
        print_error("\nERROR Some validations failed. Please address the issues above.")

        # Check specific failure patterns for actionable guidance
        iam_failed = any(
            name == "IAM Permissions" and not passed
            for name, passed, _ in validation_results
        )
        bootstrap_passed = any(
            name == "Assume Role Bootstrap" and passed
            for name, passed, _ in validation_results
        )

        if iam_failed and bootstrap_passed:
            print_safe(
                "\n[bold green]TIP:[/bold green] Your IAM user can deploy the TagManagerCLI role, "
                "which includes all required permissions."
            )
            print_safe(
                "Instead of adding all permissions to your IAM user, "
                "deploy the role and let the CLI assume it:"
            )
            print_safe(
                "\n  [cyan]bluearch-aws-tags setup assume-role[/cyan]\n"
            )
        elif iam_failed and not iam:
            print_safe("\n[bold yellow]Run [cyan]setup validate --iam[/cyan] to see the full IAM policies needed to fix permissions.[/bold yellow]")

        print_safe("For help: [cyan]bluearch-aws-tags setup --help[/cyan] or [cyan]bluearch-aws-tags setup wizard[/cyan]")


@setup_app.command("aws")
def aws_command():
    """
    Configure AWS profile and credentials.

    Interactive configuration for AWS SSO or standard profiles.
    Automatically detects available profiles and validates credentials.
    """
    print_safe("\n[bold]AWS Profile Configuration[/bold]")
    print_safe("=" * 50 + "\n")

    profile_name = setup_aws_profile()
    if not profile_name:
        print_error("AWS profile setup failed")
        raise typer.Exit(1)

    # Export AWS_PROFILE for current session
    os.environ['AWS_PROFILE'] = profile_name
    print_success(f"\nAWS_PROFILE set to: {profile_name}")
    print_safe("\nRun [cyan]setup validate[/cyan] to verify the configuration")


@setup_app.command("database")
def database_command(
    force: bool = typer.Option(False, "--force", help="Force re-initialization even if database exists")
):
    """
    Initialize database and run migrations.

    Sets up the SQLite database with all required tables and indexes.
    Safe to run multiple times - will skip if already initialized.
    """
    print_safe("\n[bold]Database Initialization[/bold]")
    print_safe("=" * 50 + "\n")

    if force:
        print_warning("Force mode enabled - database will be re-initialized")

    initialize_database()
    print_safe("\nRun [cyan]setup validate[/cyan] to verify the database connection")


def setup_aws_profile() -> Optional[str]:
    """
    Detect and configure AWS profile.

    Returns:
        Selected AWS profile name or None if failed
    """
    # Check if stdin is available for interactive input
    if not sys.stdin.isatty():
        print_warning("Non-interactive terminal detected.")
        current_profile = os.environ.get('AWS_PROFILE')
        if current_profile:
            print_safe(f"Using AWS_PROFILE from environment: {current_profile}")
            return current_profile
        else:
            print_error("No AWS_PROFILE set and running in non-interactive mode.")
            print_safe("Please set AWS_PROFILE environment variable and re-run.")
            return None

    detector = AWSProfileDetector()

    # Check current profile
    current_profile = os.environ.get('AWS_PROFILE', 'default')
    print_safe(f"Current AWS_PROFILE: [cyan]{current_profile}[/cyan]")

    # Validate current profile
    try:
        identity = aws_auth.get_caller_identity()
        print_success(f"Profile validated: {identity['Arn']}")

        # Use simple yes/no prompt
        print(f"Use current profile '{current_profile}'? (y/n) [y]: ", end="", flush=True)
        try:
            response = input().strip().lower()
            if response == '' or response == 'y' or response == 'yes':
                return current_profile
        except (EOFError, KeyboardInterrupt):
            print_safe("\n[yellow]Using current profile due to input error[/yellow]")
            return current_profile

    except Exception as e:
        print_warning(f"Current profile validation failed: {e}")

    # Detect available profiles
    print_safe("\nDetecting AWS profiles...")
    profiles = detector.detect_profiles()

    if not profiles:
        print_warning("No AWS profiles found")
        print_safe("Please configure AWS credentials first:")
        print_safe("  - Run: aws configure")
        print_safe("  - Or: aws sso configure")

        if Confirm.ask("Enter profile name manually?", default=True):
            profile_name = Prompt.ask("AWS Profile name")
            return profile_name
        return None

    # Deduplicate profiles by name
    seen_names = set()
    unique_profiles = []
    for profile in profiles:
        if profile['name'] not in seen_names:
            seen_names.add(profile['name'])
            unique_profiles.append(profile)
    profiles = unique_profiles

    # Display available profiles
    table = Table(title="Available AWS Profiles")
    table.add_column("Index", style="cyan", no_wrap=True)
    table.add_column("Profile Name", style="green")
    table.add_column("Type", style="yellow")

    for idx, profile in enumerate(profiles, 1):
        table.add_row(
            str(idx),
            profile['name'],
            profile.get('type', 'standard').upper()
        )

    console.print(table)

    # Let user select
    try:
        suggested = detector.suggest_profile(profiles)
        default_choice = None

        if suggested:
            for idx, p in enumerate(profiles, 1):
                if p['name'] == suggested:
                    default_choice = str(idx)
                    print_safe(f"\nSuggested profile: [green]{suggested}[/green]")
                    break
    except Exception as e:
        # If suggestion fails, just continue without a default
        print_safe(f"[dim]Could not determine suggested profile: {e}[/dim]")
        default_choice = None

    # Build choices list
    choices = [str(i) for i in range(1, len(profiles) + 1)]
    choices.append('m')  # manual entry

    # Display the prompt
    prompt_text = f"Select profile [1-{len(profiles)}/m]"
    default_val = default_choice if default_choice else "1"

    # Flush output to ensure table is displayed
    console.print("")  # Add empty line for spacing

    # Debug output
    debug = os.environ.get("DEBUG_SETUP", "").lower() == "true"
    if debug:
        print(f"[DEBUG] About to show prompt: {prompt_text}")
        print(f"[DEBUG] Default value: {default_val}")
        print(f"[DEBUG] Valid choices: {choices}")

    # Use standard input for better compatibility
    # Use direct print to avoid any Rich console issues
    print(f"{prompt_text} ({default_val}): ", end="", flush=True)

    try:
        # Get user input
        user_input = input().strip()
        choice = user_input if user_input else default_val

        # Validate choice
        if choice not in choices:
            print_error(f"Invalid choice: '{choice}'. Please select from {choices}")
            print_safe("Using default profile or set AWS_PROFILE manually and re-run with --skip-aws")
            return None

    except (EOFError, KeyboardInterrupt):
        print_safe("\n[yellow]Profile selection cancelled[/yellow]")
        print_safe("You can manually set AWS_PROFILE environment variable and re-run the wizard")
        return None
    except Exception as e:
        print_error(f"Error reading input: {e}")
        print_safe("Please set AWS_PROFILE environment variable and re-run with --skip-aws")
        return None

    if choice == 'm':
        try:
            profile_name = Prompt.ask("Enter AWS profile name")
            return profile_name
        except (EOFError, KeyboardInterrupt):
            print_safe("\n[yellow]Manual entry cancelled[/yellow]")
            return None

    selected_profile = profiles[int(choice) - 1]
    profile_name = selected_profile['name']

    # Check if profile is SSO and execute login
    if selected_profile.get('type') == 'sso':
        print_safe(f"\n[cyan]Profile '{profile_name}' is an SSO profile[/cyan]")
        print_safe("Attempting automatic SSO login...")

        try:
            result = subprocess.run(
                ['aws', 'sso', 'login', '--profile', profile_name],
                capture_output=False,  # Allow interactive browser login
                text=True,
                timeout=120
            )

            if result.returncode == 0:
                print_success("SSO login successful")
            else:
                print_warning("SSO login failed, continuing with validation...")
        except subprocess.TimeoutExpired:
            print_warning("SSO login timed out")
        except Exception as e:
            print_warning(f"SSO login error: {e}")

    # Validate selected profile
    print_safe(f"\nValidating profile '{profile_name}'...")
    os.environ['AWS_PROFILE'] = profile_name

    try:
        identity = aws_auth.get_caller_identity()
        print_success(f"Profile validated: {identity['Arn']}")
        return profile_name
    except Exception as e:
        error_msg = str(e).lower()
        print_error(f"Profile validation failed: {e}")

        # Check if this looks like an SSO authentication issue
        sso_keywords = ['sso', 'token', 'expired', 'refresh failed']
        is_sso_error = any(keyword in error_msg for keyword in sso_keywords)

        if is_sso_error:
            print_safe(f"\n[cyan]This appears to be an SSO authentication issue[/cyan]")
            if Confirm.ask("Attempt SSO login?", default=True):
                print_safe("Attempting SSO login...")

                try:
                    result = subprocess.run(
                        ['aws', 'sso', 'login', '--profile', profile_name],
                        capture_output=False,  # Allow interactive browser login
                        text=True,
                        timeout=120
                    )

                    if result.returncode == 0:
                        print_success("SSO login successful")

                        # Retry validation after successful login
                        print_safe(f"\nRetrying validation for profile '{profile_name}'...")
                        try:
                            identity = aws_auth.get_caller_identity()
                            print_success(f"Profile validated: {identity['Arn']}")
                            return profile_name
                        except Exception as retry_e:
                            print_error(f"Validation still failed: {retry_e}")
                    else:
                        print_warning("SSO login failed")

                except subprocess.TimeoutExpired:
                    print_warning("SSO login timed out")
                except Exception as sso_e:
                    print_warning(f"SSO login error: {sso_e}")

        if Confirm.ask("Try another profile?", default=True):
            return setup_aws_profile()

        return None


def initialize_database():
    """Initialize the bluearch-core database."""
    print_safe("Initializing bluearch-aws-core database...")
    try:
        status = request_core("GET", "/api/v1/core/db/status", timeout=10.0)
        request_core("POST", "/api/v1/core/db/migrate", timeout=30.0)
        print_success(f"Core database initialized ({status.get('table_count', 0)} tables)")
    except Exception as e:
        print_warning(f"Database initialization warning: {e}")


def run_initial_discovery():
    """Show existing resources and guide user to create policies."""
    try:
        # Check if core has resources and lifecycle policies.
        summary = request_core("GET", "/api/v1/resources/summary", timeout=10.0)
        resource_count = summary.get("total", 0)
        policy_count = _count_storage_records(
            "tag-manager",
            "resource-lifecycle-policies",
            filters=[("enabled", "true")],
        )

        if resource_count == 0:
            print_safe("No resources in core inventory yet.")
            print_safe("\nTo discover AWS resources, run:")
            print_safe("  [cyan]bluearch-aws-tags discover all[/cyan]\n")
            discovery_result = type('obj', (object,), {'returncode': 0})()
            return

        print_safe(f"Found {resource_count} resources in core inventory.")

        if policy_count == 0:
            print_safe("[yellow]No lifecycle policies configured yet.[/yellow]")
            print_safe("\nPolicies define WHICH resources to manage (by service, tags, age).")
            print_safe("Resources matching policies can then have TTL applied.\n")
            print_safe("Create your first policy:")
            print_safe("  [cyan]bluearch-aws-tags lifecycle policies create[/cyan]\n")
            print_safe("Or use the guided workflow:")
            print_safe("  [cyan]bluearch-aws-tags lifecycle wizard[/cyan]\n")
            discovery_result = type('obj', (object,), {'returncode': 0})()
        else:
            print_safe(f"Found {policy_count} active lifecycle policies.")
            print_safe("Showing resources matching policies...\n")
            # Show resources matching policies (default scan behavior)
            discovery_result = subprocess.run(
                ["python", "-m", CLI_MODULE, "lifecycle", "scan"],
                capture_output=False
            )

        if discovery_result.returncode == 0:
            print_success("\nResource discovery completed successfully")
        else:
            print_warning("\nResource discovery encountered issues")
            print_safe("You can run discovery manually later with: bluearch-aws-tags discover all")

    except subprocess.TimeoutExpired:
        print_warning("\nResource discovery timed out")
        print_safe("You can run discovery manually later with: bluearch-aws-tags discover all")
    except Exception as e:
        print_warning(f"\nDiscovery warning: {e}")
        print_safe("You can run discovery manually later with: bluearch-aws-tags discover all")


def validate_setup_simple():
    """Validate the basic setup."""
    print_safe("Validating setup...")

    checks = []

    # Check AWS connectivity
    try:
        aws_auth.get_caller_identity()
        checks.append(("[OK] AWS Authentication", True))
    except Exception:
        checks.append(("[FAIL] AWS Authentication", False))

    # Check database
    try:
        request_core("GET", "/api/v1/core/db/status", timeout=10.0)
        checks.append(("[OK] Core Database Connection", True))
    except Exception:
        checks.append(("[WARN] Core Database Connection (optional)", True))

    # Display results
    table = Table(title="Setup Validation Results")
    table.add_column("Component", style="cyan")
    table.add_column("Status", style="green")

    for check, passed in checks:
        status = "[green]PASS[/green]" if passed else "[red]FAIL[/red]"
        table.add_row(check, status)

    console.print(table)

    # Overall status
    all_critical_passed = all(passed for check, passed in checks if "FAIL" in check)
    if all_critical_passed:
        print_success("Setup validation passed!")
    else:
        print_warning("Some components need attention. Review the results above.")


@setup_app.command("doctor")
def doctor():
    """
    Diagnose installation issues and binary conflicts.

    Checks for:
    - Multiple public Tags binaries (curl vs Homebrew installations)
    - PATH order issues that may cause version conflicts
    - AWS credentials configuration
    - Data directory accessibility

    Useful when you have version conflicts or unexpected behavior.
    """
    from pathlib import Path
    import shutil

    console.print("\n[bold cyan]Tag Manager Doctor[/bold cyan]")
    console.print("=" * 40 + "\n")

    issues_found = 0

    def is_public_binary(path: Path) -> bool:
        if path.name != "bluearch-aws-tags" or not path.is_file() or not os.access(path, os.X_OK):
            return False
        try:
            return path.resolve(strict=True).name == "bluearch-aws-tags"
        except OSError:
            return False

    # 1. Check for binary conflicts
    console.print("[bold]Checking binary installations...[/bold]\n")

    binary_locations = {
        "curl": Path.home() / ".local" / "bin" / "bluearch-aws-tags",
        "homebrew_arm": Path("/opt/homebrew/bin/bluearch-aws-tags"),
        "homebrew_intel": Path("/usr/local/bin/bluearch-aws-tags"),
        "system": Path("/usr/bin/bluearch-aws-tags"),
    }

    found_binaries = {}
    for name, path in binary_locations.items():
        if is_public_binary(path):
            # Get version
            version = "unknown"
            try:
                result = subprocess.run(
                    [str(path), "--version"],
                    capture_output=True,
                    text=True,
                    timeout=10
                )
                if result.returncode == 0:
                    # Extract version from output like "AWS Tag Manager CLI v0.3.4 (production)"
                    for line in result.stdout.split("\n"):
                        if "Tag Manager CLI" in line:
                            version = line.strip()
                            break
            except Exception:
                pass
            found_binaries[name] = {"path": path, "version": version}

    legacy_locations = (
        Path.home() / ".local" / "bin" / "tag-manager",
        Path("/opt/homebrew/bin/tag-manager"),
        Path("/usr/local/bin/tag-manager"),
        Path("/usr/bin/tag-manager"),
    )
    legacy_binaries = [path for path in legacy_locations if path.exists()]
    hidden_legacy_targets = [path for path in binary_locations.values() if path.exists() and not is_public_binary(path)]

    # Display found binaries
    if not found_binaries:
        print_warning("No bluearch-aws-tags binary found!")
        issues_found += 1
    else:
        for name, info in found_binaries.items():
            install_type = {
                "curl": "Curl installer",
                "homebrew_arm": "Homebrew (Apple Silicon)",
                "homebrew_intel": "Homebrew (Intel)",
                "system": "System",
            }.get(name, name)
            console.print(f"  [cyan]{install_type}:[/cyan] {info['path']}")
            console.print(f"    Version: {info['version']}")
    if legacy_binaries:
        print_warning("Legacy tag-manager launchers detected; they are not used by BlueArch AWS Tags.")
        for path in legacy_binaries:
            console.print(f"  [dim]Migration review:[/dim] {path}")
    if hidden_legacy_targets:
        print_warning("Public launcher symlinks with a non-public target are not used.")
        for path in hidden_legacy_targets:
            console.print(f"  [dim]Migration review:[/dim] {path}")

    # Check for conflicts
    if len(found_binaries) > 1:
        console.print("")
        print_warning(f"Multiple installations detected ({len(found_binaries)} binaries)")
        issues_found += 1

        # Check PATH order
        active_binary = shutil.which("bluearch-aws-tags")
        if active_binary:
            console.print(f"\n  [bold]Active binary:[/bold] {active_binary}")

            # Determine which one is active
            active_path = Path(active_binary).resolve()
            for name, info in found_binaries.items():
                if info["path"].resolve() == active_path:
                    if name == "curl" and ("homebrew_arm" in found_binaries or "homebrew_intel" in found_binaries):
                        console.print(f"\n  [yellow]Issue: Curl binary is shadowing Homebrew installation[/yellow]")
                        console.print(f"  [dim]The curl-installed binary comes before Homebrew in your PATH.[/dim]")
                        console.print(f"\n  [bold green]Fix:[/bold green] Remove the curl binary:")
                        console.print(f"    [cyan]rm {binary_locations['curl']}[/cyan]")
                    break

    # 2. Check active binary in PATH
    console.print("\n[bold]Checking PATH...[/bold]\n")
    active_binary = shutil.which("bluearch-aws-tags")
    if active_binary and is_public_binary(Path(active_binary)):
        print_success(f"bluearch-aws-tags found in PATH: {active_binary}")

        # Get active version
        try:
            result = subprocess.run(
                [active_binary, "--version"],
                capture_output=True,
                text=True,
                timeout=10
            )
            if result.returncode == 0:
                console.print(f"  Active version: {result.stdout.split(chr(10))[0].strip()}")
        except Exception:
            pass
    else:
        print_warning("bluearch-aws-tags not found in PATH")
        issues_found += 1
        console.print("  [dim]You may need to add the installation directory to your PATH[/dim]")

    # 3. Check AWS credentials
    console.print("\n[bold]Checking AWS credentials...[/bold]\n")
    try:
        sts = aws_auth.get_client("sts")
        identity = sts.get_caller_identity()
        account_id = identity.get("Account", "unknown")
        arn = identity.get("Arn", "unknown")
        print_success("AWS credentials configured")
        console.print(f"  Account: {account_id}")
        console.print(f"  ARN: {arn}")

        # Show profile if set
        profile = os.environ.get("AWS_PROFILE")
        if profile:
            console.print(f"  Profile: {profile}")
    except Exception as e:
        print_warning("AWS credentials not configured or invalid")
        console.print(f"  [dim]Error: {str(e)[:80]}[/dim]")
        console.print("\n  [bold green]Fix:[/bold green] Configure AWS credentials:")
        console.print("    [cyan]export AWS_PROFILE=your-profile[/cyan]")
        console.print("    [cyan]aws sso login[/cyan]")

    # 4. Check data directory
    console.print("\n[bold]Checking data directory...[/bold]\n")
    data_dir = Path.home() / ".tag-manager"
    if data_dir.exists():
        print_success(f"Data directory exists: {data_dir}")

        # Check subdirectories
        subdirs = ["data", "cache", "config", "backups"]
        for subdir in subdirs:
            subpath = data_dir / subdir
            if subpath.exists():
                console.print(f"  [dim]{subdir}/[/dim] exists")
            else:
                console.print(f"  [dim]{subdir}/[/dim] not found (will be created on first use)")

        # Check database
        db_path = data_dir / "data" / "tag-manager.db"
        if db_path.exists():
            size_mb = db_path.stat().st_size / (1024 * 1024)
            console.print(f"  Database: {size_mb:.2f} MB")
    else:
        console.print(f"  [dim]Data directory not found (will be created on first use)[/dim]")

    # Check writability
    try:
        test_file = data_dir / ".doctor-test"
        data_dir.mkdir(parents=True, exist_ok=True)
        test_file.touch()
        test_file.unlink()
        print_success("Data directory is writable")
    except Exception as e:
        print_warning(f"Data directory is not writable: {e}")
        issues_found += 1

    # 5. Check Homebrew installation status
    console.print("\n[bold]Checking Homebrew installation...[/bold]\n")
    try:
        result = subprocess.run(
            ["brew", "list", "bluearch-aws-tags"],
            capture_output=True,
            text=True,
            timeout=10
        )
        if result.returncode == 0:
            print_success("Installed via Homebrew")
            # Get Homebrew version info
            version_result = subprocess.run(
                ["brew", "info", "bluearch-aws-tags", "--json=v2"],
                capture_output=True,
                text=True,
                timeout=10
            )
            if version_result.returncode == 0:
                try:
                    info = json.loads(version_result.stdout)
                    formulae = info.get("formulae", [])
                    if formulae:
                        version = formulae[0].get("versions", {}).get("stable", "unknown")
                        console.print(f"  Homebrew formula version: {version}")
                except Exception:
                    pass
        else:
            console.print("  [dim]Not installed via Homebrew[/dim]")
    except FileNotFoundError:
        console.print("  [dim]Homebrew not installed[/dim]")
    except Exception as e:
        console.print(f"  [dim]Could not check Homebrew: {e}[/dim]")

    # Summary
    console.print("\n" + "=" * 40)
    if issues_found == 0:
        print_success("No issues found! Your installation looks healthy.")
    else:
        print_warning(f"Found {issues_found} issue(s) that may need attention.")
        console.print("\n[dim]Review the issues above and apply the suggested fixes.[/dim]")


def _remove_multi_account(force: bool = False) -> None:
    """Remove cross-account infrastructure through bluearch-core."""
    console.print("\n[bold red]Cross-Account Infrastructure Removal[/bold red]\n")
    if not force and not Confirm.ask("[bold red]Remove ALL cross-account infrastructure?[/bold red]", default=False):
        console.print("[dim]Removal cancelled.[/dim]")
        raise typer.Exit(0)
    try:
        result = _submit_core_setup_job(
            "/api/v1/accounts/remove",
            action="Cross-account removal",
            timeout_seconds=1800,
        )
    except Exception as exc:
        print_error(f"Failed to remove cross-account infrastructure through bluearch-aws-core: {exc}")
        raise typer.Exit(1)
    print_success(result.get("message") or "Cross-account infrastructure removed")


@setup_app.command("multi-account")
def multi_account_setup(
    validate_only: bool = typer.Option(False, "--validate-only", help="Only validate prerequisites without deploying"),
    accounts: Optional[str] = typer.Option(None, "--accounts", help="Comma-separated list of account IDs"),
    organizational_units: Optional[str] = typer.Option(None, "--ous", help="Comma-separated list of OU IDs"),
    regions: Optional[str] = typer.Option(None, "--regions", help="Comma-separated list of regions"),
    force: bool = typer.Option(False, "--force", "-f", help="Skip confirmation prompts"),
    clean: bool = typer.Option(False, "--clean", help="Delete existing StackSet and recreate from scratch"),
    update: bool = typer.Option(False, "--update", help="Update existing StackSet to latest template version"),
    complete: bool = typer.Option(False, "--complete", help="Complete setup: deploy, test, list, and enable all accounts"),
    remove: bool = typer.Option(False, "--remove", help="Remove all cross-account infrastructure (StackSets, stacks, account IDs)"),
):
    """
    Deploy cross-account infrastructure using CloudFormation StackSets.

    This enables multi-account resource discovery and lifecycle management
    by deploying IAM roles across your AWS Organization.

    Examples:
        setup multi-account                  # Interactive guided setup
        setup multi-account --complete       # Full automated setup
        setup multi-account --update         # Update existing deployment
        setup multi-account --validate-only  # Check prerequisites only
        setup multi-account --remove         # Remove all cross-account infrastructure
    """
    if remove:
        _remove_multi_account(force=force)
        return

    console.print("\n[bold cyan]Cross-Account Infrastructure Setup[/bold cyan]\n")

    try:
        validation = request_core("GET", "/api/v1/accounts/validate", timeout=15.0)
    except Exception as exc:
        print_error(f"bluearch-aws-core account validation unavailable: {exc}")
        raise typer.Exit(1)

    current_account = validation.get("current_account_id") or "-"
    console.print(f"Current account: [cyan]{current_account}[/cyan]")
    if validation.get("organization_id"):
        console.print(f"Organization: [cyan]{validation.get('organization_id')}[/cyan]")
    if validation.get("management_account_id"):
        console.print(f"Management account: [cyan]{validation.get('management_account_id')}[/cyan]")

    if not validation.get("can_deploy"):
        guidance = validation.get("guidance") or validation.get("error") or "Run from the management account or delegated StackSets admin."
        print_error(f"Prerequisites check failed: {guidance}")
        raise typer.Exit(1)

    print_success("Prerequisites validated by bluearch-aws-core")

    if validate_only:
        console.print("\n[dim]Validation complete. Use without --validate-only to deploy.[/dim]")
        return

    status_payload = request_core("GET", "/api/v1/accounts/status", timeout=15.0)
    console.print("\n[bold]Existing Infrastructure[/bold]")
    _print_core_stackset_status(status_payload)
    if status_payload.get("exists") and not update and not clean and not complete:
        console.print("\n[dim]StackSet already deployed. Use --update to update or --clean to recreate.[/dim]")
        return

    if not force and not complete:
        console.print("\n[bold]Confirm Deployment[/bold]")
        target_info = []
        if accounts:
            target_info.append(f"Accounts: {accounts}")
        if organizational_units:
            target_info.append(f"OUs: {organizational_units}")
        if regions:
            target_info.append(f"Regions: {regions}")
        if not target_info:
            target_info.append("Target: All accounts in organization (all regions)")

        console.print("\nDeployment targets:")
        for info in target_info:
            console.print(f"  - {info}")

        if not Confirm.ask("\nProceed with deployment?", default=True):
            console.print("[dim]Deployment cancelled.[/dim]")
            raise typer.Exit(0)

    try:
        if update and status_payload.get("exists") and not clean:
            result = _submit_core_setup_job(
                "/api/v1/accounts/update",
                action="Cross-account update",
                timeout_seconds=1800,
            )
        else:
            result = _submit_core_setup_job(
                "/api/v1/accounts/deploy",
                payload={
                    "accounts": _parse_csv_option(accounts),
                    "organizational_units": _parse_csv_option(organizational_units),
                    "regions": _parse_csv_option(regions),
                    "force_recreate": clean,
                },
                action="Cross-account deployment",
                timeout_seconds=1800,
            )
    except Exception as exc:
        print_error(f"Deployment failed through bluearch-aws-core: {exc}")
        raise typer.Exit(1)

    deployed_accounts = result.get("deployed_accounts") or []
    failed_accounts = result.get("failed_accounts") or []
    synced_accounts = result.get("synced_accounts")
    if failed_accounts:
        print_warning(f"Failed accounts: {', '.join(failed_accounts)}")
    if deployed_accounts:
        print_success(f"StackSet deployed to {len(deployed_accounts)} account(s)")
    if synced_accounts is not None:
        print_success(f"{synced_accounts} account target(s) synced in core storage")

    console.print("\n" + "=" * 50)
    print_success("Cross-account setup complete!")
    console.print("\nNext steps:")
    console.print("  [cyan]lifecycle scan[/cyan]                    # Scan (will ask about multi-account)")
    console.print("  [cyan]lifecycle scan --discover -m[/cyan]      # Force multi-account discovery")
    console.print("=" * 50 + "\n")


@setup_app.command("assume-role")
def setup_assume_role(
    role_name: Optional[str] = typer.Option("BlueArchCLIRole", "--role-name", "-r", help="IAM role name to assume"),
    external_id: Optional[str] = typer.Option(None, "--external-id", "-e", help="External ID for role assumption (auto-retrieved from Secrets Manager if not specified)"),
    disable: bool = typer.Option(False, "--disable", help="Disable assume role and use direct credentials"),
    delete_stack: bool = typer.Option(False, "--delete-stack", help="Also delete CloudFormation stack when disabling"),
    deploy: bool = typer.Option(False, "--deploy", "-d", help="Deploy CloudFormation stack directly from CLI"),
    show_url: bool = typer.Option(False, "--show-url", "-u", help="Show CloudFormation quick-create URL"),
    status: bool = typer.Option(False, "--status", "-s", help="Show current assume role configuration"),
    force: bool = typer.Option(False, "--force", "-f", help="Skip confirmation prompts"),
):
    """
    Configure assume role for the CLI.

    This command helps you set up assume-role based authentication.
    Instead of using your direct AWS credentials, the CLI will assume
    a dedicated IAM role with the necessary permissions.

    This provides better security through temporary credentials
    and centralized permission management via the IAM role.

    Examples:
        # Check if role exists and configure it
        bluearch-aws-tags setup assume-role

        # Deploy the CloudFormation stack directly from CLI
        bluearch-aws-tags setup assume-role

        # Show the CloudFormation quick-create URL
        bluearch-aws-tags setup assume-role --show-url

        # Configure with custom role name
        bluearch-aws-tags setup assume-role --role-name MyRole

        # Disable assume role (use direct credentials)
        bluearch-aws-tags setup assume-role --disable

        # Disable and delete the CloudFormation stack
        bluearch-aws-tags setup assume-role --disable --delete-stack

        # Check current configuration
        bluearch-aws-tags setup assume-role --status
    """
    from ..utils.cloudformation_urls import (
        get_quick_create_url,
        format_quick_create_instructions,
        DEFAULT_ROLE_NAME
    )

    # Initialize AWS session
    try:
        aws_auth.initialize_session()
    except Exception as e:
        print_error(f"Failed to initialize AWS session: {e}")
        print_safe("[dim]Please ensure AWS credentials are configured (AWS_PROFILE or access keys)[/dim]")
        raise typer.Exit(1)

    # Get current account and region
    try:
        identity = aws_auth.get_caller_identity()
        account_id = identity.get('Account')
        current_user_arn = identity.get('Arn')
        region = aws_auth.region or 'us-east-1'
    except Exception as e:
        print_error(f"Failed to get AWS identity: {e}")
        raise typer.Exit(1)

    # Handle --status flag
    if status:
        _show_assume_role_status(account_id)
        return

    # Handle --show-url flag
    if show_url:
        _show_quick_create_url(region, current_user_arn, external_id)
        return

    # Handle --disable flag
    if disable:
        _disable_assume_role(account_id, force, delete_stack, role_name)
        return

    # Handle --deploy flag
    if deploy:
        _deploy_assume_role_stack(region, current_user_arn, external_id, role_name, force)
        return

    # Default flow: Check if role exists and configure
    print_safe(f"\n[bold]Assume Role Configuration[/bold]")
    print_safe("=" * 50)
    print_safe(f"Account ID: {account_id}")
    print_safe(f"Region: {region}")
    print_safe(f"Role Name: {role_name}")
    print_safe("")

    # Check if role exists
    iam_client = aws_auth.get_client('iam')
    role_exists = False
    role_arn = None

    try:
        response = iam_client.get_role(RoleName=role_name)
        role_exists = True
        role_arn = response['Role']['Arn']
        print_success(f"Role '{role_name}' found in account {account_id}")
        console.print(f"[dim]Role ARN: {role_arn}[/dim]")
    except iam_client.exceptions.NoSuchEntityException:
        print_warning(f"Role '{role_name}' not found in account {account_id}")
        print_safe("")
        print_safe("The role needs to be deployed first.")
        print_safe("")

        # Ask user how they want to deploy
        if sys.stdin.isatty():
            print_safe("[bold]Deployment Options:[/bold]")
            print_safe("  [1] Deploy automatically from CLI [green](Recommended)[/green]")
            print_safe("  [2] Show CloudFormation Quick Create URL (manual)")
            print_safe("")

            choice = Prompt.ask("Select", choices=["1", "2"], default="1")

            if choice == "1":
                _deploy_assume_role_stack(region, current_user_arn, external_id, role_name, force)
                return
            else:
                # Show quick create URL
                _show_quick_create_url(region, current_user_arn, external_id, show_full_instructions=True)
                raise typer.Exit(0)
        else:
            # Non-interactive: show URL
            _show_quick_create_url(region, current_user_arn, external_id, show_full_instructions=True)
            raise typer.Exit(0)
    except Exception as e:
        print_error(f"Failed to check role: {e}")
        raise typer.Exit(1)

    # Try to get external ID from Secrets Manager if not provided
    if not external_id:
        external_id = _get_external_id_from_secrets_manager()
        if external_id:
            print_safe(f"[dim]External ID retrieved from Secrets Manager[/dim]")

    # Validate we can assume the role
    print_safe("")
    print_safe("Validating role assumption...")

    sts_client = aws_auth.get_client('sts')
    try:
        assume_params = {
            'RoleArn': role_arn,
            'RoleSessionName': 'tag-manager-cli-test',
            'DurationSeconds': 900  # 15 minutes for test
        }
        if external_id:
            assume_params['ExternalId'] = external_id

        sts_client.assume_role(**assume_params)
        print_success("Successfully assumed role")
    except Exception as e:
        print_error(f"Failed to assume role: {e}")
        print_safe("")
        print_safe("[bold]Troubleshooting:[/bold]")
        print_safe("1. Check that your current IAM identity is in the role's trust policy")
        print_safe("2. If using External ID, ensure it matches the role's trust policy")
        print_safe("3. Verify the role has the correct permissions")
        print_safe("")
        print_safe("Current IAM identity:")
        console.print(f"[dim]{current_user_arn}[/dim]")
        raise typer.Exit(1)

    # Save configuration to core storage
    if not force:
        if not Confirm.ask("\nSave this configuration?", default=True):
            print_safe("Configuration not saved.")
            raise typer.Exit(0)

    try:
        updated = _save_active_assume_role_config(account_id, role_arn, role_name, external_id)
        if updated:
            print_safe("[dim]Updated existing configuration[/dim]")
        else:
            print_safe("[dim]Created new configuration[/dim]")

        print_safe("")
        print_success("Assume role configured successfully!")
        print_safe("")
        print_safe("[bold]All CLI operations will now use temporary credentials from:[/bold]")
        console.print(f"  Role: [cyan]{role_arn}[/cyan]")
        print_safe("")
        print_safe("To disable: [dim]bluearch-aws-tags setup assume-role --disable[/dim]")
        print_safe("To check status: [dim]bluearch-aws-tags setup assume-role --status[/dim]")

    except Exception as e:
        print_error(f"Failed to save configuration: {e}")
        raise typer.Exit(1)


def _show_assume_role_status(account_id: str):
    """Show current assume role configuration status."""
    print_safe("\n[bold]Assume Role Configuration Status[/bold]")
    print_safe("=" * 50)

    try:
        configs = _list_assume_role_configs()

        if not configs:
            print_safe("No assume role configurations found.")
            print_safe("")
            print_safe("To configure: [dim]bluearch-aws-tags setup assume-role[/dim]")
            return

        # Create a table
        table = Table(title="Configurations")
        table.add_column("Account ID", style="cyan")
        table.add_column("Role Name", style="green")
        table.add_column("Active", style="yellow")
        table.add_column("Enabled", style="yellow")
        table.add_column("External ID", style="dim")
        table.add_column("Last Used", style="dim")

        for config in configs:
            table.add_row(
                config.get("account_id") or "-",
                config.get("role_name") or "-",
                "[OK]" if config.get("is_active") else "-",
                "[OK]" if config.get("enabled") else "[X]",
                "***" if config.get("external_id") else "-",
                _format_context_time(config.get("last_used_at")),
            )

        console.print(table)

        # Show active configuration details
        active = next((c for c in configs if c.get("is_active") and c.get("enabled")), None)
        if active:
            print_safe("")
            print_safe("[bold green]Active configuration:[/bold green]")
            console.print(f"  Role ARN: [cyan]{active.get('role_arn')}[/cyan]")
            console.print(f"  Created: [dim]{_format_context_time(active.get('created_at'))}[/dim]")
        else:
            print_safe("")
            print_warning("No active configuration. CLI is using direct credentials.")

    except CoreRuntimeError as e:
        print_error(f"Failed to get status: {e}")
        raise typer.Exit(1)


def _show_quick_create_url(
    region: str,
    current_user_arn: str,
    external_id: Optional[str] = None,
    show_full_instructions: bool = False
):
    """Show the CloudFormation quick-create URL with interactive prompts."""
    from ..utils.cloudformation_urls import (
        get_quick_create_url,
        format_quick_create_instructions
    )

    # Interactive prompt for trust mode (only if TTY available)
    if sys.stdin.isatty():
        print_safe("\n[bold]CloudFormation Quick Create URL Generator[/bold]")
        print_safe("=" * 50)
        print_safe("")
        print_safe("Who should be able to assume the TagManagerCLI role?")
        print_safe("")
        print_safe(f"  [1] Current user only")
        console.print(f"      [dim]{current_user_arn}[/dim]")
        print_safe(f"  [2] Any principal in this account [green](Recommended)[/green]")
        print_safe(f"  [3] Specific IAM ARN (I'll enter it manually)")
        print_safe("")

        choice = Prompt.ask("Select", choices=["1", "2", "3"], default="2")

        if choice == "1":
            trusted_mode = "CurrentUser"
            specific_arn = None
            deploying_user_arn = current_user_arn
        elif choice == "2":
            trusted_mode = "AnyPrincipal"
            specific_arn = None
            deploying_user_arn = None
        else:
            trusted_mode = "SpecificArn"
            specific_arn = Prompt.ask("Enter IAM ARN")
            deploying_user_arn = None
    else:
        # Non-interactive: default to AnyPrincipal
        trusted_mode = "AnyPrincipal"
        specific_arn = None
        deploying_user_arn = None

    # Try to get external ID from Secrets Manager if not provided
    if not external_id:
        external_id = _get_external_id_from_secrets_manager()

    # Generate URL
    url = get_quick_create_url(
        region=region,
        trusted_principal_mode=trusted_mode,
        specific_principal_arn=specific_arn,
        external_id=external_id,
        deploying_user_arn=deploying_user_arn
    )

    # Show formatted instructions
    instructions = format_quick_create_instructions(
        url=url,
        region=region,
        trusted_principal_mode=trusted_mode,
        current_user_arn=current_user_arn if trusted_mode == "CurrentUser" else None
    )
    print_safe(instructions)


def _disable_assume_role(account_id: str, force: bool = False, delete_stack: bool = False, role_name: str = "BlueArchCLIRole"):
    """Disable assume role configuration."""
    print_safe("\n[bold]Disable Assume Role[/bold]")
    print_safe("=" * 50)

    if delete_stack:
        print_safe("[yellow]This will also delete the CloudFormation stack.[/yellow]")

    if not force:
        confirm_msg = "Disable assume role"
        if delete_stack:
            confirm_msg += " and delete CloudFormation stack"
        confirm_msg += "? CLI will use direct credentials."
        if not Confirm.ask(confirm_msg, default=False):
            print_safe("Cancelled.")
            raise typer.Exit(0)

    try:
        result = _submit_core_setup_job(
            "/api/v1/assume-role/disable",
            payload={"delete_stack": delete_stack},
            action="Assume-role disable",
            timeout_seconds=600,
        )
        print_success(result.get("message") or "Assume role disabled.")
        print_safe("CLI will now use direct credentials.")
    except Exception as e:
        print_error(f"Failed to disable through bluearch-aws-core: {e}")
        raise typer.Exit(1)


def _get_external_id_from_secrets_manager() -> Optional[str]:
    """Try to retrieve external ID from Secrets Manager (same as multi-account feature)."""
    try:
        # Get organization ID first
        org_client = aws_auth.get_client('organizations')
        org_response = org_client.describe_organization()
        org_id = org_response['Organization']['Id']

        # Try to get external ID from Secrets Manager
        secrets_client = aws_auth.get_client('secretsmanager')
        secret_name = f"tag-manager-cli/v2/external-id/{org_id}"

        response = secrets_client.get_secret_value(SecretId=secret_name)
        secret_string = response.get('SecretString')

        if secret_string:
            # The secret is stored as JSON with ExternalId field
            import json
            try:
                secret_data = json.loads(secret_string)
                return secret_data.get('ExternalId')
            except json.JSONDecodeError:
                # If it's not JSON, assume it's the raw external ID
                return secret_string

        return None
    except Exception:
        # External ID not found or not accessible - that's OK
        return None


def _deploy_assume_role_stack(
    region: str,
    current_user_arn: str,
    external_id: Optional[str] = None,
    role_name: str = "BlueArchCLIRole",
    force: bool = False
):
    """Deploy the assume-role stack through bluearch-core."""

    print_safe("\n[bold]Deploy Assume-Role Stack[/bold]")
    print_safe("=" * 50)

    # Interactive prompt for trust mode (only if TTY available)
    if sys.stdin.isatty() and not force:
        print_safe("")
        print_safe("Who should be able to assume the TagManagerCLI role?")
        print_safe("")
        print_safe("  [1] Current user only")
        console.print(f"      [dim]{current_user_arn}[/dim]")
        print_safe("  [2] Any principal in this account [green](Recommended)[/green]")
        print_safe("  [3] Specific IAM ARN (I'll enter it manually)")
        print_safe("")

        choice = Prompt.ask("Select", choices=["1", "2", "3"], default="2")

        if choice == "1":
            trusted_mode = "CurrentUser"
            specific_arn = None
        elif choice == "2":
            trusted_mode = "AnyPrincipal"
            specific_arn = None
        else:
            trusted_mode = "SpecificArn"
            specific_arn = Prompt.ask("Enter IAM ARN")
    else:
        # Non-interactive: default to AnyPrincipal
        trusted_mode = "AnyPrincipal"
        specific_arn = None

    # Try to get external ID from Secrets Manager if not provided
    if not external_id:
        external_id = _get_external_id_from_secrets_manager()
        if external_id:
            print_safe("[dim]External ID retrieved from Secrets Manager[/dim]")

    print_safe("")
    print_safe("Submitting deployment to bluearch-aws-core")
    print_safe(f"  Trust Mode: {trusted_mode}")
    if trusted_mode == "CurrentUser":
        console.print(f"  [dim]Trusted Principal: {current_user_arn}[/dim]")
    elif trusted_mode == "SpecificArn":
        console.print(f"  [dim]Trusted Principal: {specific_arn}[/dim]")
    print_safe("")

    try:
        result = _submit_core_setup_job(
            "/api/v1/assume-role/deploy",
            payload={
                "trust_mode": trusted_mode,
                "specific_arn": specific_arn,
                "external_id": external_id,
                "role_name": role_name,
            },
            action="Assume-role deployment",
            timeout_seconds=900,
        )
        if result.get("role_arn"):
            console.print(f"  Role ARN: [cyan]{result['role_arn']}[/cyan]")
        print_success("Assume-role deployed and configured by bluearch-aws-core.")

    except Exception as e:
        print_error(f"Failed to deploy assume-role through bluearch-aws-core: {e}")
        raise typer.Exit(1)


def _delete_assume_role_stack(stack_name: str, force: bool = False):
    """Delete the assume-role stack through bluearch-core."""
    print_safe("[bold]Delete CloudFormation Stack[/bold]")
    print_safe("-" * 50)
    try:
        result = _submit_core_setup_job(
            "/api/v1/assume-role/disable",
            payload={"delete_stack": True},
            action="Assume-role stack deletion",
            timeout_seconds=600,
        )
        print_success(result.get("message") or "CloudFormation stack deleted successfully!")
    except Exception as e:
        print_error(f"Failed to delete stack through bluearch-aws-core: {e}")
        raise typer.Exit(1)


@setup_app.command("infrastructure")
def infrastructure_status_cmd(
    create_resource_group: bool = typer.Option(False, "--create-rg", help="Create the BlueArch-TagManager Resource Group"),
    delete_resource_group: bool = typer.Option(False, "--delete-rg", help="Delete the BlueArch-TagManager Resource Group"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Show additional details"),
):
    """Show infrastructure status across all deployed CloudFormation resources."""
    from rich.table import Table
    from ..utils.resource_group_manager import resource_group_manager

    STACKSET_NAME = "BlueArchCLI-CrossAccount-Infrastructure"
    MANAGEMENT_STACK_NAME = "BlueArchCLI-Management-Account-Resources"
    ASSUME_ROLE_STACK_NAME = "BlueArchCLI-Role"

    # Handle Resource Group actions first
    if create_resource_group:
        print_safe("Creating Resource Group...")
        status = resource_group_manager.create_or_update()
        if status.exists:
            print_success(f"Resource Group '{status.name}' is active ({status.resource_count} resources)")
        else:
            print_error(f"Failed to create Resource Group: {status.error or 'Unknown error'}")
        return

    if delete_resource_group:
        print_safe("Deleting Resource Group...")
        if resource_group_manager.delete():
            print_success("Resource Group deleted")
        else:
            print_error("Failed to delete Resource Group")
        return

    # Initialize AWS
    try:
        aws_auth.initialize_session()
    except Exception as e:
        print_error(f"AWS authentication failed: {e}")
        raise typer.Exit(1)

    cf_client = aws_auth.get_client("cloudformation")

    # StackSets table
    ss_table = Table(title="StackSets", show_lines=False)
    ss_table.add_column("Name", style="cyan")
    ss_table.add_column("Status")
    ss_table.add_column("Instances", justify="right")
    ss_table.add_column("Healthy", justify="right")
    ss_table.add_column("Failed", justify="right")

    try:
        resp = cf_client.describe_stack_set(StackSetName=STACKSET_NAME)
        ss = resp["StackSet"]
        status = ss.get("Status", "UNKNOWN")

        instance_count = 0
        healthy = 0
        failed = 0
        try:
            paginator = cf_client.get_paginator("list_stack_instances")
            for page in paginator.paginate(StackSetName=STACKSET_NAME):
                for inst in page.get("Summaries", []):
                    instance_count += 1
                    if inst.get("Status") == "CURRENT":
                        healthy += 1
                    elif inst.get("Status") in ("OUTDATED", "FAILED", "INOPERABLE"):
                        failed += 1
        except Exception:
            pass

        status_style = "green" if status == "ACTIVE" and failed == 0 else "yellow" if failed > 0 else "dim"
        ss_table.add_row(
            STACKSET_NAME,
            f"[{status_style}]{status}[/{status_style}]",
            str(instance_count),
            f"[green]{healthy}[/green]",
            f"[red]{failed}[/red]" if failed > 0 else str(failed),
        )
    except Exception as e:
        if "StackSetNotFoundException" in str(type(e).__name__) or "StackSetNotFound" in str(e):
            ss_table.add_row(STACKSET_NAME, "[dim]Not Deployed[/dim]", "-", "-", "-")
        else:
            ss_table.add_row(STACKSET_NAME, f"[red]Error: {e}[/red]", "-", "-", "-")

    console.print(ss_table)
    console.print()

    # Standalone Stacks table
    stacks_table = Table(title="Standalone Stacks", show_lines=False)
    stacks_table.add_column("Name", style="cyan")
    stacks_table.add_column("Status")
    stacks_table.add_column("Region")
    stacks_table.add_column("Last Updated")

    for stack_name in [MANAGEMENT_STACK_NAME, ASSUME_ROLE_STACK_NAME]:
        try:
            resp = cf_client.describe_stacks(StackName=stack_name)
            stacks = resp.get("Stacks", [])
            if stacks:
                stack = stacks[0]
                s_status = stack.get("StackStatus", "UNKNOWN")
                if "DELETE_COMPLETE" in s_status:
                    stacks_table.add_row(stack_name, "[dim]Deleted[/dim]", "-", "-")
                    continue
                last_updated = stack.get("LastUpdatedTime") or stack.get("CreationTime")
                last_str = str(last_updated)[:19] if last_updated else "-"
                region = aws_auth.region or "-"
                is_ok = "COMPLETE" in s_status and "FAILED" not in s_status and "ROLLBACK" not in s_status
                style = "green" if is_ok else "red"
                stacks_table.add_row(stack_name, f"[{style}]{s_status}[/{style}]", region, last_str)
            else:
                stacks_table.add_row(stack_name, "[dim]Not Deployed[/dim]", "-", "-")
        except Exception as e:
            if "does not exist" in str(e) or "ValidationError" in str(type(e).__name__):
                stacks_table.add_row(stack_name, "[dim]Not Deployed[/dim]", "-", "-")
            else:
                stacks_table.add_row(stack_name, f"[red]Error[/red]", "-", "-")

    console.print(stacks_table)
    console.print()

    # Resource Group
    rg_status = resource_group_manager.get_status()
    rg_table = Table(title="Resource Group", show_lines=False)
    rg_table.add_column("Name", style="cyan")
    rg_table.add_column("Status")
    rg_table.add_column("Resources", justify="right")

    if rg_status.exists:
        rg_table.add_row(
            rg_status.name,
            "[green]Active[/green]",
            str(rg_status.resource_count),
        )
    else:
        rg_table.add_row(
            rg_status.name,
            "[dim]Not Created[/dim]",
            "-",
        )
        if rg_status.error and verbose:
            console.print(f"  [dim]{rg_status.error}[/dim]")

    console.print(rg_table)

    if verbose:
        console.print()
        try:
            sts = aws_auth.get_client("sts")
            identity = sts.get_caller_identity()
            console.print(f"  Account: {identity.get('Account', '-')}")
            console.print(f"  Region:  {aws_auth.region or '-'}")
        except Exception:
            pass


# ------------------------------------------------------------------
# Account Context Commands
# ------------------------------------------------------------------


@setup_app.command("add-context")
def add_context_cmd(
    alias: Optional[str] = typer.Option(None, "--alias", "-a", help="Friendly name for this account"),
):
    """Register the current AWS account as a context."""
    from ..services.account_context_service import account_context_service

    try:
        session = aws_auth.initialize_session()
        sts = session.client("sts")
        identity = sts.get_caller_identity()
    except Exception as e:
        print_error(f"Failed to get AWS identity: {e}")
        raise typer.Exit(1)

    account_id = identity.get("Account", "")
    user_arn = identity.get("Arn", "")
    region = session.region_name

    try:
        all_contexts = account_context_service.get_all_contexts()
        is_first = len(all_contexts) == 0

        ctx = account_context_service.add_context(
            None,
            account_id=account_id,
            user_arn=user_arn,
            alias=alias,
            region=region,
            set_current=is_first,
        )

        print_success(f"Registered account {account_id}")
        if alias:
            console.print(f"  Alias:   {alias}")
        console.print(f"  Region:  {region or '-'}")
        console.print(f"  Profile: {ctx.aws_profile or '-'}")
        if is_first:
            console.print("  [cyan]Set as current context (first account)[/cyan]")
    except ValueError as e:
        print_error(str(e))
        raise typer.Exit(1)
    except Exception as e:
        print_error(f"Failed to register context: {e}")
        raise typer.Exit(1)


@setup_app.command("switch-context")
def switch_context_cmd():
    """Switch the active account context."""
    from ..services.account_context_service import account_context_service

    try:
        contexts = account_context_service.get_all_contexts()

        if not contexts:
            print_error("No account contexts registered. Use 'setup add-context' first.")
            raise typer.Exit(1)

        table = Table(title="Registered Account Contexts", show_lines=False)
        table.add_column("#", justify="right", style="dim")
        table.add_column("Account ID", style="cyan")
        table.add_column("Alias")
        table.add_column("Profile")
        table.add_column("Region")
        table.add_column("Current")

        for i, ctx in enumerate(contexts, 1):
            current_marker = "*" if ctx.is_current else ""
            table.add_row(
                str(i),
                ctx.account_id,
                ctx.account_alias or "-",
                ctx.aws_profile or "-",
                ctx.region or "-",
                current_marker,
            )

        console.print(table)
        console.print()

        choice = Prompt.ask(
            "Select account number to switch to",
            choices=[str(i) for i in range(1, len(contexts) + 1)],
        )
        selected = contexts[int(choice) - 1]

        account_context_service.switch_context(None, selected.account_id)
        label = selected.account_alias or selected.account_id
        print_success(f"Switched to account {label} ({selected.account_id})")
    except typer.Exit:
        raise
    except Exception as e:
        print_error(f"Failed to switch context: {e}")
        raise typer.Exit(1)


@setup_app.command("list-contexts")
def list_contexts_cmd():
    """Show all registered account contexts."""
    from ..services.account_context_service import account_context_service

    try:
        contexts = account_context_service.get_all_contexts()

        if not contexts:
            print_warning("No account contexts registered. Use 'setup add-context' to register one.")
            return

        table = Table(title="Account Contexts", show_lines=False)
        table.add_column("#", justify="right", style="dim")
        table.add_column("Account ID", style="cyan")
        table.add_column("Alias")
        table.add_column("Profile")
        table.add_column("Region")
        table.add_column("Current")
        table.add_column("Last Used")

        for i, ctx in enumerate(contexts, 1):
            current_marker = "*" if ctx.is_current else ""
            last_used = "-"
            if ctx.last_used_at:
                last_used = ctx.last_used_at.strftime("%Y-%m-%d %H:%M:%S")
            table.add_row(
                str(i),
                ctx.account_id,
                ctx.account_alias or "-",
                ctx.aws_profile or "-",
                ctx.region or "-",
                current_marker,
                last_used,
            )

        console.print(table)
    except Exception as e:
        print_error(f"Failed to list contexts: {e}")
        raise typer.Exit(1)


@setup_app.command("remove-context")
def remove_context_cmd():
    """Remove a registered account context."""
    from ..services.account_context_service import account_context_service

    try:
        contexts = account_context_service.get_all_contexts()

        if not contexts:
            print_error("No account contexts registered.")
            raise typer.Exit(1)

        table = Table(title="Registered Account Contexts", show_lines=False)
        table.add_column("#", justify="right", style="dim")
        table.add_column("Account ID", style="cyan")
        table.add_column("Alias")
        table.add_column("Current")

        for i, ctx in enumerate(contexts, 1):
            current_marker = "*" if ctx.is_current else ""
            table.add_row(
                str(i),
                ctx.account_id,
                ctx.account_alias or "-",
                current_marker,
            )

        console.print(table)
        console.print()

        choice = Prompt.ask(
            "Select account number to remove",
            choices=[str(i) for i in range(1, len(contexts) + 1)],
        )
        selected = contexts[int(choice) - 1]

        if not Confirm.ask(f"Remove account {selected.account_id}?"):
            console.print("[dim]Cancelled.[/dim]")
            return

        removed = account_context_service.remove_context(None, selected.account_id)
        if removed:
            print_success(f"Removed account {selected.account_id}")
        else:
            print_error(f"Account {selected.account_id} not found.")
    except typer.Exit:
        raise
    except Exception as e:
        print_error(f"Failed to remove context: {e}")
        raise typer.Exit(1)


@setup_app.command("event-tracking")
def event_tracking_cmd(
    remove: bool = typer.Option(False, "--remove", help="Deactivate event tracking (clean DB records)"),
    status: bool = typer.Option(False, "--status", help="Show event tracking status only"),
):
    """Activate or manage real-time event tracking.

    Event tracking infrastructure is deployed automatically as part of
    the cross-account setup (setup multi-account). This command activates
    tracking by syncing queue URLs from the deployed infrastructure.
    """
    try:
        from ..utils.core_client import request_core

        if status:
            status_payload = request_core("GET", "/api/v1/event-tracking/status", timeout=10.0)
            records = status_payload.get("instances", [])
            et_deployed = bool(status_payload.get("stackset_exists"))

            table = Table(title="Event Tracking Status")
            table.add_column("Account", style="cyan")
            table.add_column("Region")
            table.add_column("Status")
            table.add_column("Queue URL", style="dim")
            table.add_column("Events Today", justify="right")
            table.add_column("Last Polled")

            if not records:
                console.print("[dim]No event tracking instances found.[/dim]")
                console.print(f"Infrastructure deployed: {'Yes' if et_deployed else 'No'}")
                if et_deployed:
                    console.print("[blue]Run 'setup event-tracking' to activate.[/blue]")
                else:
                    console.print("[blue]Run 'setup multi-account' to deploy infrastructure.[/blue]")
                raise typer.Exit(0)

            for r in records:
                last_polled = _format_context_time(r.get("last_polled_at"))
                table.add_row(
                    r.get("account_id") or "-",
                    r.get("region") or "-",
                    r.get("status") or "unknown",
                    r.get("queue_url") or "-",
                    str(r.get("events_today") or 0),
                    last_polled,
                )

            console.print(table)
            console.print(f"\nInfrastructure deployed: {'Yes' if et_deployed else 'No'}")
            raise typer.Exit(0)

        if remove:
            if not Confirm.ask("Deactivate event tracking? (infrastructure remains deployed)"):
                console.print("[dim]Cancelled.[/dim]")
                raise typer.Exit(0)
            console.print("[yellow]Deactivating event tracking...[/yellow]")
            records = request_core(
                "GET",
                "/api/v1/storage/core/event-sync-configuration",
                service_token=True,
                params=[("limit", 10000)],
                timeout=10.0,
            )
            removed = 0
            for record in records or []:
                record_key = record.get("record_key") or record.get("id")
                if not record_key:
                    continue
                request_core(
                    "DELETE",
                    f"/api/v1/storage/core/event-sync-configuration/{record_key}",
                    service_token=True,
                    timeout=10.0,
                )
                removed += 1
            print_success(f"Event tracking deactivated ({removed} DB record(s) removed)")
            raise typer.Exit(0)

        # Default: activate by syncing from deployed infrastructure
        console.print("[blue]Checking cross-account infrastructure...[/blue]")
        console.print("[blue]Syncing queue URLs from deployed infrastructure...[/blue]")
        result = request_core(
            "POST",
            "/api/v1/event-tracking/service",
            service_token=True,
            json={"action": "sync"},
            timeout=30.0,
        )
        updated = result.get("records_updated", 0)
        if not updated:
            print_warning(
                "No event tracking queues were found. If the infrastructure is not deployed, "
                "run 'setup multi-account' first."
            )

        print_success(f"Event tracking activated ({updated} queue(s) synced)")

    except typer.Exit:
        raise
    except Exception as e:
        print_error(f"Event tracking operation failed: {e}")
        raise typer.Exit(1)


@setup_app.command("upgrade")
def upgrade_cmd():
    """Show open-source feature availability."""
    console = Console()
    console.print("\n  [green][OK] All open-source features are enabled locally.[/green]\n")
