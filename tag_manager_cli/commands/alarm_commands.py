"""CloudWatch alarm management commands for bluearch-aws-tags CLI."""

import typer
from typing import Optional, List
from rich.console import Console
from rich.table import Table
from rich.prompt import Confirm, Prompt
from rich.panel import Panel

from ..utils.display_utils import print_safe, print_success, print_warning, print_error
from ..utils.error_handlers import handle_aws_errors, require_aws_credentials
from ..utils.core_client import request_core

alarm_app = typer.Typer(
    help="Manage CloudWatch alarms for monitored resources",
    no_args_is_help=False
)
console = Console()


# System prompt for AI-powered alarm creation wizard
ALARM_WIZARD_SYSTEM_PROMPT = """You are an AWS CloudWatch alarm creation wizard. Your role is to help users create monitoring alarms for their AWS resources through a conversational interface.

## Your Capabilities
You have access to these tools:
- list_ec2_instances: List EC2 instances to help users find resources
- describe_rds_instances: List RDS databases
- list_lambda_functions: List Lambda functions
- get_alarm_templates: Get available alarm templates for a service
- suggest_cloudwatch_alarms: Get alarm suggestions for a specific resource
- create_cloudwatch_alarm: Create an alarm (REQUIRES user confirmation)

## Conversation Flow
1. First, understand what the user wants to monitor. Ask clarifying questions if needed.
2. Help them identify the resource (list instances if they don't know the ARN)
3. Suggest appropriate alarm templates based on the resource type
4. Gather any additional details (threshold customization, notification email)
5. Preview the alarm configuration and ask for confirmation
6. Create the alarm only after explicit user approval

## Important Guidelines
- Be conversational and helpful, not robotic
- If the user says something vague like "monitor my EC2", list their instances first
- Always explain what each alarm template does before suggesting it
- For write operations (create_cloudwatch_alarm), ALWAYS preview first with preview_only=true
- Only call create_cloudwatch_alarm with preview_only=false after user explicitly confirms
- Keep responses concise - this is a CLI tool

## Example Interactions
User: "I want to monitor my EC2 instance"
You: Let me list your EC2 instances to find the one you want to monitor.
[Use list_ec2_instances tool]
I found these instances: [list]. Which one would you like to create an alarm for?

User: "Create a CPU alarm for i-1234567890abcdef0"
You: I'll help you create a CPU alarm. Let me show you the available templates.
[Use get_alarm_templates for ec2]
Here are the CPU alarm options:
- cpu_high: Alert when CPU > 80% (good for most workloads)
- cpu_critical: Alert when CPU > 95% (for critical alerts only)
Which would you prefer, and would you like to customize the threshold?

Start by greeting the user and asking what they'd like to monitor."""


def _get_service():
    """Lazy import alarm service."""
    from ..services.alarm_service import alarm_service
    return alarm_service


def _start_alarm_wizard(model: Optional[str] = None, region: str = "us-east-1"):
    """Start AI-powered alarm creation wizard.

    This launches an interactive chat session with a specialized system prompt
    for creating CloudWatch alarms conversationally.
    """
    try:
        from ..integrations.aws_assistant import BedrockAWSAssistant
        import time

        # Create assistant with alarm-specific system prompt
        assistant = BedrockAWSAssistant(model_id=model, region=region)

        # Override the system prompt for alarm creation
        assistant.custom_system_prompt = ALARM_WIZARD_SYSTEM_PROMPT

        # Reset conversation to use new system prompt
        assistant.conversation_history = []
        assistant.session_start_time = time.time()

        # Get model info for display
        from ..integrations.model_info import get_model_info, estimate_cost
        model_info = get_model_info(assistant.model_id)
        typical_cost = estimate_cost(500, 200, assistant.model_id)

        # Show welcome panel
        welcome_panel = Panel(
            f"[bold cyan]Model:[/bold cyan]    {model_info.name}\n"
            f"[bold cyan]Region:[/bold cyan]   {region}\n"
            f"[bold cyan]Cost:[/bold cyan]     ~${typical_cost:.4f} per interaction\n\n"
            f"[bold yellow]What I can help with:[/bold yellow]\n"
            f"  [dim]- Find your AWS resources (EC2, RDS, Lambda)[/dim]\n"
            f"  [dim]- Suggest appropriate alarms for your resources[/dim]\n"
            f"  [dim]- Create CloudWatch alarms with proper tagging[/dim]\n"
            f"  [dim]- Set up email notifications via SNS[/dim]\n\n"
            f"[bold green]Commands:[/bold green]\n"
            f"  [green]exit[/green] - End wizard and return to CLI\n\n"
            f"[dim]Just describe what you want to monitor in plain English![/dim]",
            title="[bold cyan]CloudWatch Alarm Wizard[/bold cyan]",
            border_style="cyan",
            padding=(1, 2)
        )
        console.print(welcome_panel)

        # Get initial greeting from AI
        console.print("\n[bold blue]Assistant:[/bold blue]", end=" ")
        initial_response = ""
        for chunk in assistant.ask_stream("Start the conversation by greeting me and asking what I'd like to monitor."):
            console.print(chunk, end="")
            initial_response += chunk
        console.print()

        # Interactive loop
        while True:
            try:
                user_input = console.input("\n[bold green]You:[/bold green] ").strip()

                if not user_input:
                    continue

                if user_input.lower() in ['exit', 'quit', 'q', 'done']:
                    console.print("\n[yellow]Exiting alarm wizard.[/yellow]")
                    assistant._show_session_summary()
                    break

                # Get AI response with streaming
                console.print("\n[bold blue]Assistant:[/bold blue]", end=" ")
                response = ""
                for chunk in assistant.ask_stream(user_input):
                    console.print(chunk, end="")
                    response += chunk
                console.print()

            except KeyboardInterrupt:
                console.print("\n[yellow]Interrupted. Type 'exit' to quit.[/yellow]")
                continue
            except EOFError:
                console.print("\n[yellow]Exiting alarm wizard.[/yellow]")
                break

    except Exception as e:
        console.print(f"[red]Error starting alarm wizard: {e}[/red]")
        console.print("[dim]Falling back to standard wizard...[/dim]\n")
        return False

    return True


def show_alarms_help():
    """Show the enhanced alarms help format."""
    console.print("\n[bold cyan]CloudWatch Alarm Management[/bold cyan] - Monitor your AWS resources\n")

    console.print("[bold green]ALARM OPERATIONS[/bold green] (start here):")
    console.print("- [cyan]create[/cyan]        - Create alarm (AI-powered wizard)")
    console.print("- [cyan]list[/cyan]          - List alarms managed by BlueArch AWS Tags")
    console.print("- [cyan]delete[/cyan]        - Delete an alarm (wizard)")
    console.print("- [cyan]sync[/cyan]          - Sync local state with AWS\n")

    console.print("[bold yellow]DISCOVERY & TEMPLATES[/bold yellow]:")
    console.print("- [cyan]suggest[/cyan]       - Suggest alarms for a resource")
    console.print("- [cyan]templates[/cyan]     - List available alarm templates\n")

    console.print("[bold magenta]BULK OPERATIONS[/bold magenta]:")
    console.print("- [cyan]bulk-create[/cyan]   - Create alarms for multiple resources\n")

    console.print("[bold green]QUICK START[/bold green]:")
    console.print("  [dim]alarms create[/dim]  [bold]<-- Start here! AI wizard guides you[/bold]\n")

    console.print("[bold cyan]AI-POWERED WIZARD[/bold cyan]:")
    console.print("  The [cyan]create[/cyan] command launches an interactive AI assistant that:")
    console.print("  - Lists your AWS resources (EC2, RDS, Lambda)")
    console.print("  - Suggests appropriate alarms for your workloads")
    console.print("  - Helps configure thresholds and notifications")
    console.print("  - Creates alarms with proper tagging\n")

    console.print("[bold yellow]OPTIONS[/bold yellow]:")
    console.print("  [dim]alarms create --no-ai[/dim]              # Simple prompt mode")
    console.print("  [dim]alarms create --model sonnet[/dim]       # Use more powerful AI model")
    console.print("  [dim]alarms create <arn> -t cpu_high[/dim]    # Direct creation (no wizard)\n")

    console.print("For detailed help on any command: [cyan]alarms [COMMAND] --help[/cyan]")


@alarm_app.callback(invoke_without_command=True)
def alarms_main(
    ctx: typer.Context,
    help: bool = typer.Option(False, "--help", "-h", help="Show this message and exit.")
):
    """
    CloudWatch alarm management - Monitor your AWS resources with ease.

    Create, manage, and track CloudWatch alarms with bluearch-aws-tags integration.
    All alarms are tagged for tracking and support email notifications.
    """
    if help or ctx.invoked_subcommand is None:
        show_alarms_help()
        if help:
            raise typer.Exit()


@alarm_app.command("list")
@handle_aws_errors
def list_alarms(
    service: Optional[str] = typer.Option(None, "--service", "-s", help="Filter by service (ec2, rds, lambda)"),
    resource: Optional[str] = typer.Option(None, "--resource", "-r", help="Filter by resource ARN"),
    state: Optional[str] = typer.Option(None, "--state", help="Filter by state (OK, ALARM, INSUFFICIENT_DATA)"),
    region: Optional[str] = typer.Option(None, "--region", help="AWS region"),
    all_alarms: bool = typer.Option(False, "--all", "-a", help="Show all alarms, not just managed ones"),
    limit: int = typer.Option(50, "--limit", "-l", help="Maximum alarms to show"),
):
    """List CloudWatch alarms managed by BlueArch AWS Tags."""
    svc = _get_service()

    # Get region for display
    query_region = region or svc._get_current_region()

    alarms = svc.list_alarms(
        service=service,
        resource_arn=resource,
        state=state,
        region=region,
        managed_only=not all_alarms,
        limit=limit,
    )

    if not alarms:
        if all_alarms:
            print_warning(f"No alarms found in {query_region}")
        else:
            print_warning(f"No managed alarms found in {query_region}. Use --all to see all CloudWatch alarms.")
        return

    # Create table
    table = Table(title=f"CloudWatch Alarms ({len(alarms)} found)", show_header=True, header_style="bold magenta")
    table.add_column("Alarm Name", style="cyan", max_width=40)
    table.add_column("State", width=12)
    table.add_column("Type", width=15)
    table.add_column("Target", max_width=30)
    table.add_column("Owner", max_width=25)

    for alarm in alarms:
        # Format state with color
        state_val = alarm.get("state", "UNKNOWN")
        if state_val == "OK":
            state_display = "[green]OK[/green]"
        elif state_val == "ALARM":
            state_display = "[red]ALARM[/red]"
        elif state_val == "INSUFFICIENT_DATA":
            state_display = "[yellow]NO DATA[/yellow]"
        else:
            state_display = f"[dim]{state_val}[/dim]"

        # Get alert type
        alert_type = alarm.get("alert_type", alarm.get("metric_name", ""))

        # Get target (truncate if needed)
        target = alarm.get("target_resource", "")
        if target:
            # Extract just the resource ID from ARN
            target = target.split("/")[-1].split(":")[-1]

        # Get owner
        owner = alarm.get("owner_email", "")
        if owner:
            owner = owner.split("@")[0]  # Just show username part

        table.add_row(
            alarm.get("alarm_name", ""),
            state_display,
            alert_type,
            target,
            owner,
        )

    console.print(table)

    # Show summary
    states = {}
    for alarm in alarms:
        s = alarm.get("state", "UNKNOWN")
        states[s] = states.get(s, 0) + 1

    summary_parts = []
    if states.get("OK"):
        summary_parts.append(f"[green]{states['OK']} OK[/green]")
    if states.get("ALARM"):
        summary_parts.append(f"[red]{states['ALARM']} ALARM[/red]")
    if states.get("INSUFFICIENT_DATA"):
        summary_parts.append(f"[yellow]{states['INSUFFICIENT_DATA']} NO DATA[/yellow]")

    if summary_parts:
        print_safe(f"\nSummary: {', '.join(summary_parts)}")


@alarm_app.command("create")
@require_aws_credentials
@handle_aws_errors
def create_alarm(
    resource_arn: Optional[str] = typer.Argument(None, help="Target resource ARN (optional - AI wizard if omitted)"),
    template: Optional[str] = typer.Option(None, "--template", "-t", help="Alarm template (e.g., cpu_high, errors)"),
    owner: Optional[str] = typer.Option(None, "--owner", "-o", help="Owner email for notifications"),
    threshold: Optional[float] = typer.Option(None, "--threshold", help="Override default threshold"),
    region: Optional[str] = typer.Option(None, "--region", help="AWS region"),
    model: Optional[str] = typer.Option(None, "--model", "-m", help="AI model for wizard: haiku (default), sonnet, opus"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Preview without creating"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation prompt"),
    no_ai: bool = typer.Option(False, "--no-ai", help="Use simple prompts instead of AI wizard"),
):
    """Create a CloudWatch alarm for a resource.

    Run without arguments for AI-powered interactive wizard that helps you:
    - Find your AWS resources
    - Choose appropriate alarm templates
    - Configure thresholds and notifications
    - Create alarms with proper tagging

    Use --no-ai for simple prompt-based wizard.
    """
    from ..templates.alarm_templates import (
        extract_service_from_arn,
        extract_resource_id_from_arn,
        get_template,
        get_available_services,
        get_templates_for_service,
    )
    from ..services.alarm_service import AlarmConfig

    svc = _get_service()

    # AI wizard mode if no resource_arn provided (unless --no-ai)
    if not resource_arn and not no_ai:
        wizard_region = region or "us-east-1"
        if _start_alarm_wizard(model=model, region=wizard_region):
            return  # Wizard completed successfully
        # If wizard failed, fall through to simple mode

    # Simple wizard mode if resource_arn not provided
    if not resource_arn:
        console.print("\n[bold cyan]Create CloudWatch Alarm - Simple Mode[/bold cyan]\n")

        # Step 1: Get resource ARN
        resource_arn = Prompt.ask("Resource ARN (e.g., arn:aws:ec2:us-east-1:123456789012:instance/i-xxx)")
        if not resource_arn:
            print_error("Resource ARN is required")
            return

    # Extract service and resource ID from ARN
    service = extract_service_from_arn(resource_arn)
    if not service:
        print_error(f"Could not determine service from ARN: {resource_arn}")
        print_safe("\nSupported services: " + ", ".join(get_available_services()))
        return

    resource_id = extract_resource_id_from_arn(resource_arn)
    if not resource_id:
        print_error(f"Could not extract resource ID from ARN: {resource_arn}")
        return

    # Wizard mode for template if not provided
    if not template:
        # Show available templates for this service
        service_templates = get_templates_for_service(service)
        if not service_templates:
            print_error(f"No templates available for service: {service}")
            return

        console.print(f"\n[bold]Available templates for {service}:[/bold]")
        template_names = list(service_templates.keys())
        for i, name in enumerate(template_names, 1):
            t = service_templates[name]
            console.print(f"  {i}. [cyan]{name}[/cyan] - {t.get('display_name', '')} (threshold: {t.get('threshold')})")

        # Get user selection
        selection = Prompt.ask(
            "\nSelect template",
            choices=[str(i) for i in range(1, len(template_names) + 1)] + template_names,
            default="1"
        )

        # Handle numeric or name selection
        if selection.isdigit():
            template = template_names[int(selection) - 1]
        else:
            template = selection

    # Get template config
    template_config = get_template(service, template)
    if not template_config:
        print_error(f"Unknown template '{template}' for service '{service}'")
        return

    # Wizard mode for owner email if not provided
    if owner is None:
        owner = Prompt.ask("Owner email for notifications (optional, press Enter to skip)", default="")
        if not owner:
            owner = None

    # Wizard mode for threshold if not provided
    if threshold is None:
        default_threshold = template_config.get("threshold", 80)
        threshold_input = Prompt.ask(
            f"Threshold",
            default=str(default_threshold)
        )
        try:
            threshold = float(threshold_input)
        except ValueError:
            threshold = default_threshold

    # Build alarm config
    config = AlarmConfig(
        resource_arn=resource_arn,
        resource_id=resource_id,
        service=service,
        template_name=template,
        metric_name=template_config["metric_name"],
        namespace=template_config["namespace"],
        statistic=template_config["statistic"],
        period=template_config["period"],
        evaluation_periods=template_config["evaluation_periods"],
        threshold=threshold,
        comparison_operator=template_config["comparison_operator"],
        treat_missing_data=template_config.get("treat_missing_data", "missing"),
        dimension_key=template_config.get("dimension_key", ""),
        dimension_value=resource_id,
        owner_email=owner,
        region=region,
    )

    # Show preview
    alarm_name = f"tag-manager-{resource_id}-{template}".replace("_", "-")

    console.print(f"\n[bold cyan]Alarm Preview[/bold cyan]\n")
    console.print(f"  Name:        [cyan]{alarm_name}[/cyan]")
    console.print(f"  Target:      {resource_arn}")
    console.print(f"  Type:        {template_config.get('display_name', template)}")
    console.print(f"  Metric:      {config.namespace}/{config.metric_name}")
    console.print(f"  Condition:   {config.statistic} {config.comparison_operator} {config.threshold}")
    console.print(f"  Period:      {config.period}s x {config.evaluation_periods} evaluations")
    if owner:
        console.print(f"  Notify:      {owner}")
    console.print(f"\n  Tags:")
    console.print(f"    - CreatedBy: tag-manager-cli")
    console.print(f"    - TargetResource: {resource_arn}")
    console.print(f"    - AlertType: {template}")

    if dry_run:
        print_warning("\nDry run - alarm not created")
        return

    # Confirm unless --yes flag
    if not yes:
        console.print("")
        if not Confirm.ask("Create this alarm?", default=True):
            print_warning("Cancelled")
            return

    # Create alarm
    result = svc.create_alarm(
        config=config,
        dry_run=False,
        executed_by="cli_user",
        executed_via="cli",
    )

    if result.success:
        print_success(f"\nCreated alarm: {result.alarm_name}")
        if owner:
            print_safe(f"[dim]SNS notifications will be sent to: {owner}[/dim]")
            print_safe("[dim]Note: Email subscription confirmation may be required[/dim]")
    else:
        print_error(f"Failed to create alarm: {result.error}")


@alarm_app.command("delete")
@require_aws_credentials
@handle_aws_errors
def delete_alarm(
    alarm_name: Optional[str] = typer.Argument(None, help="Name of the alarm to delete (optional - wizard if omitted)"),
    region: Optional[str] = typer.Option(None, "--region", help="AWS region"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation prompt"),
):
    """Delete a CloudWatch alarm.

    Run without arguments for interactive wizard mode.
    """
    svc = _get_service()

    # Wizard mode if alarm_name not provided
    if not alarm_name:
        console.print("\n[bold cyan]Delete CloudWatch Alarm - Wizard[/bold cyan]\n")

        # List existing alarms
        alarms = svc.list_alarms(managed_only=True, limit=20)

        if not alarms:
            print_warning("No managed alarms found to delete")
            return

        console.print("[bold]Your managed alarms:[/bold]")
        for i, alarm in enumerate(alarms, 1):
            state = alarm.get("state", "UNKNOWN")
            target = alarm.get("target_resource", "")
            if target:
                target = target.split("/")[-1].split(":")[-1]
            console.print(f"  {i}. [cyan]{alarm['alarm_name']}[/cyan] ({state}) - {target}")

        # Get user selection
        selection = Prompt.ask(
            "\nSelect alarm to delete (number or name)",
            default="1"
        )

        if selection.isdigit():
            idx = int(selection) - 1
            if 0 <= idx < len(alarms):
                alarm_name = alarms[idx]["alarm_name"]
            else:
                print_error("Invalid selection")
                return
        else:
            alarm_name = selection

    # Confirm unless --yes flag
    if not yes:
        print_warning(f"This will delete alarm: {alarm_name}")
        if not Confirm.ask("Are you sure?", default=False):
            print_warning("Cancelled")
            return

    result = svc.delete_alarm(
        alarm_name=alarm_name,
        region=region,
        executed_by="cli_user",
        executed_via="cli",
    )

    if result.success:
        print_success(f"Deleted alarm: {alarm_name}")
    else:
        print_error(f"Failed to delete alarm: {result.error}")


@alarm_app.command("suggest")
@handle_aws_errors
def suggest_alarms(
    resource_arn: Optional[str] = typer.Argument(None, help="Resource ARN to get suggestions for"),
    service: Optional[str] = typer.Option(None, "--service", "-s", help="Filter templates by service"),
):
    """Suggest alarm templates for a resource or service."""
    svc = _get_service()

    if resource_arn:
        # Get suggestions for specific resource
        suggestions = svc.suggest_alarms_for_resource(resource_arn)

        if not suggestions:
            print_warning("No alarm templates available for this resource type")
            return

        # Get resource ID for display
        from ..templates.alarm_templates import extract_resource_id_from_arn
        resource_id = extract_resource_id_from_arn(resource_arn) or "resource"

        table = Table(
            title=f"Suggested Alarms for {resource_id}",
            show_header=True,
            header_style="bold magenta"
        )
        table.add_column("Template", style="cyan", width=20)
        table.add_column("Name", width=25)
        table.add_column("Metric", width=20)
        table.add_column("Threshold", width=15)

        for s in suggestions:
            table.add_row(
                s["template_name"],
                s.get("display_name", ""),
                s.get("metric_name", ""),
                f"{s.get('comparison_operator', '>')} {s.get('threshold', '')}",
            )

        console.print(table)
        console.print(f"\n[dim]Create with: alarms create {resource_arn} --template <template_name>[/dim]")
        console.print(f"[dim]Or run: alarms create   (for wizard mode)[/dim]")

    else:
        # Show all templates (optionally filtered by service)
        templates = svc.get_alarm_templates(service)

        if not templates:
            if service:
                print_warning(f"No templates found for service: {service}")
            else:
                print_warning("No templates available")
            return

        table = Table(
            title="Available Alarm Templates",
            show_header=True,
            header_style="bold magenta"
        )
        table.add_column("Service", style="cyan", width=12)
        table.add_column("Template", width=20)
        table.add_column("Description", width=35)
        table.add_column("Default Threshold", width=15)

        for t in templates:
            table.add_row(
                t.get("service", ""),
                t.get("template_name", ""),
                t.get("description", t.get("display_name", "")),
                str(t.get("threshold", "")),
            )

        console.print(table)


@alarm_app.command("templates")
def list_templates(
    service: Optional[str] = typer.Option(None, "--service", "-s", help="Filter by service"),
):
    """List available alarm templates."""
    # Delegate to suggest command
    suggest_alarms(resource_arn=None, service=service)


@alarm_app.command("sync")
@handle_aws_errors
def sync_alarms(
    region: Optional[str] = typer.Option(None, "--region", help="AWS region to sync"),
):
    """Sync local alarm state with AWS."""
    svc = _get_service()

    print_safe("Syncing alarms with AWS...")
    result = svc.sync_alarms(region=region)

    if result.get("success"):
        print_success("Sync completed")
        print_safe(f"  AWS alarms: {result.get('aws_alarms', 0)}")
        print_safe(f"  Local alarms: {result.get('local_alarms', 0)}")

        if result.get("missing_in_aws"):
            print_warning(f"  Deleted from AWS: {len(result['missing_in_aws'])}")
        if result.get("missing_in_local"):
            print_safe(f"  Discovered in AWS: {len(result['missing_in_local'])}")
    else:
        print_error(f"Sync failed: {result.get('error', 'Unknown error')}")


@alarm_app.command("bulk-create")
@handle_aws_errors
def bulk_create_alarms(
    service: Optional[str] = typer.Option(None, "--service", "-s", help="Service type (ec2, rds, lambda)"),
    template: Optional[str] = typer.Option(None, "--template", "-t", help="Alarm template to apply"),
    owner: Optional[str] = typer.Option(None, "--owner", "-o", help="Owner email for notifications"),
    region: Optional[str] = typer.Option(None, "--region", help="AWS region"),
    tag_filter: Optional[str] = typer.Option(None, "--tag", help="Filter resources by tag (Key=Value)"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Preview without creating"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation prompt"),
    limit: int = typer.Option(10, "--limit", "-l", help="Maximum resources to create alarms for"),
):
    """Create alarms for multiple resources matching criteria.

    Run without arguments for interactive wizard mode.
    """
    from ..templates.alarm_templates import get_template, extract_resource_id_from_arn, get_available_services, get_templates_for_service
    from ..services.alarm_service import AlarmConfig

    svc = _get_service()

    # Wizard mode if service not provided
    if not service:
        console.print("\n[bold cyan]Bulk Create Alarms - Wizard[/bold cyan]\n")

        available_services = get_available_services()
        console.print("[bold]Available services:[/bold]")
        for i, s in enumerate(available_services, 1):
            console.print(f"  {i}. [cyan]{s}[/cyan]")

        selection = Prompt.ask(
            "\nSelect service",
            choices=[str(i) for i in range(1, len(available_services) + 1)] + available_services,
            default="1"
        )

        if selection.isdigit():
            service = available_services[int(selection) - 1]
        else:
            service = selection

    # Wizard mode for template if not provided
    if not template:
        service_templates = get_templates_for_service(service)
        if not service_templates:
            print_error(f"No templates available for service: {service}")
            return

        console.print(f"\n[bold]Available templates for {service}:[/bold]")
        template_names = list(service_templates.keys())
        for i, name in enumerate(template_names, 1):
            t = service_templates[name]
            console.print(f"  {i}. [cyan]{name}[/cyan] - {t.get('display_name', '')}")

        selection = Prompt.ask(
            "\nSelect template",
            choices=[str(i) for i in range(1, len(template_names) + 1)] + template_names,
            default="1"
        )

        if selection.isdigit():
            template = template_names[int(selection) - 1]
        else:
            template = selection

    # Get template config
    template_config = get_template(service, template)
    if not template_config:
        print_error(f"Unknown template '{template}' for service '{service}'")
        return

    # Wizard mode for owner email if not provided
    if owner is None:
        owner = Prompt.ask("Owner email for notifications (optional)", default="")
        if not owner:
            owner = None

    params = [
        ("filter", f"service_name={service}"),
        ("limit", 10000),
        ("order_by", "created_at"),
        ("descending", "true"),
    ]
    records = request_core(
        "GET",
        "/api/v1/storage/core/resources",
        service_token=True,
        params=params,
        timeout=10.0,
    )
    resources = []
    tag_key = tag_value = None
    if tag_filter and "=" in tag_filter:
        tag_key, tag_value = tag_filter.split("=", 1)
        print_warning(f"Tag filtering by {tag_key}={tag_value} (simplified matching)")

    for record in records or []:
        resource = record.get("payload", record)
        if resource.get("lifecycle_state") == "stale":
            continue
        if region and resource.get("region") != region:
            continue
        if tag_key:
            current_tags = resource.get("current_tags") or {}
            if current_tags.get(tag_key) != tag_value:
                continue
        resources.append(resource)
        if len(resources) >= limit:
            break

    if not resources:
        print_warning(f"No {service} resources found matching criteria")
        print_safe("\n[dim]Run 'discover all' first to populate the resource inventory[/dim]")
        return

    console.print(f"\n[bold]Found {len(resources)} {service} resources[/bold]")
    console.print(f"Template: {template} ({template_config.get('display_name', '')})")
    console.print(f"Threshold: {template_config.get('comparison_operator', '>')} {template_config.get('threshold', '')}")
    if owner:
        console.print(f"Notifications: {owner}")

    # Preview resources
    table = Table(title="Resources", show_header=True, header_style="bold")
    table.add_column("Resource ID", style="cyan")
    table.add_column("Region")
    table.add_column("Alarm Name")

    for resource in resources[:10]:
        resource_arn = resource.get("resource_arn") or ""
        resource_id = extract_resource_id_from_arn(resource_arn) or resource.get("resource_id") or "-"
        alarm_name = f"tag-manager-{resource_id}-{template}".replace("_", "-")
        table.add_row(resource_id, resource.get("region") or "-", alarm_name)

    if len(resources) > 10:
        table.add_row("...", "...", f"... and {len(resources) - 10} more")

    console.print(table)

    if dry_run:
        print_warning("\nDry run - no alarms created")
        return

    if not yes:
        console.print("")
        if not Confirm.ask(f"Create {len(resources)} alarms?", default=False):
            print_warning("Cancelled")
            return

    # Create alarms
    created = 0
    failed = 0

    for resource in resources:
        resource_arn = resource.get("resource_arn") or ""
        resource_id = extract_resource_id_from_arn(resource_arn) or resource.get("resource_id") or "-"

        config = AlarmConfig(
            resource_arn=resource_arn,
            resource_id=resource_id,
            service=service,
            template_name=template,
            metric_name=template_config["metric_name"],
            namespace=template_config["namespace"],
            statistic=template_config["statistic"],
            period=template_config["period"],
            evaluation_periods=template_config["evaluation_periods"],
            threshold=template_config["threshold"],
            comparison_operator=template_config["comparison_operator"],
            treat_missing_data=template_config.get("treat_missing_data", "missing"),
            dimension_key=template_config.get("dimension_key", ""),
            dimension_value=resource_id,
            owner_email=owner,
            region=resource.get("region"),
            account_id=resource.get("account_id"),
        )

        result = svc.create_alarm(
            config=config,
            executed_by="cli_user",
            executed_via="cli_bulk",
        )

        if result.success:
            created += 1
            print_safe(f"  [green][OK][/green] {result.alarm_name}")
        else:
            failed += 1
            print_safe(f"  [red][FAIL][/red] {resource_id}: {result.error}")

    console.print("")
    if created > 0:
        print_success(f"Created {created} alarms")
    if failed > 0:
        print_error(f"Failed to create {failed} alarms")
