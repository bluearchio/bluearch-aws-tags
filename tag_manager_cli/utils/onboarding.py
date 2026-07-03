"""Interactive onboarding and setup wizard for new users."""

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.prompt import Prompt, Confirm
from rich.progress import Progress, SpinnerColumn, TextColumn
from typing import Optional, Dict, Any
import json
from pathlib import Path

from .env_config import settings
from .aws_auth import aws_auth
from .core_client import request_core
from .core_storage import (
    list_all_records,
    list_objects,
    resource_payload,
    update_record,
    upsert_by_filter,
)

console = Console()


def is_first_time_user() -> bool:
    """Check if this is a first-time user by looking for indicators."""
    # Check for existing core storage content
    try:
        resource_count = len(list_all_records("core", "resources"))
        rule_count = len(list_all_records("tag-manager", "tagging-rules"))

        # If they have resources or rules, they're not a first-time user
        if resource_count > 0 or rule_count > 0:
            return False
    except Exception:
        resource_count = None
        pass
    
    # Check for configuration indicators
    try:
        if settings.get_database_url() and aws_auth.check_aws_credentials():
            # Basic setup exists, check if they've run any scans
            return resource_count == 0 if resource_count is not None else True
    except Exception:
        pass
    
    return True


def show_welcome_message():
    """Display welcome message for new users."""
    welcome_text = """
[bold cyan]Welcome to AWS Tag Manager CLI![/bold cyan]

Stop zombie resources from eating your AWS budget!

[bold green]What this tool does:[/bold green]
- Sets TTL (time-to-live) on AWS resources
- Alerts you when resources are expiring
- Helps you review and clean up resources

[bold green]Recommended: Run the lifecycle wizard[/bold green]
   [cyan]tag-manager lifecycle wizard[/cyan]

The wizard will guide you through:
- Creating lifecycle policies
- Discovering your resources
- Setting TTL tags
- Configuring Slack notifications

[dim]This setup takes about 5-10 minutes.[/dim]
"""

    console.print(Panel(welcome_text, title="AWS Tag Manager Setup", border_style="green"))

    try:
        if not Confirm.ask("Ready to get started?", default=True):
            console.print("[yellow]Setup cancelled. You can run the wizard anytime with: tag-manager lifecycle wizard[/yellow]")
            raise typer.Exit()
    except EOFError:
        console.print("[yellow]Continuing with automated setup (no input available)[/yellow]")


def check_prerequisites() -> Dict[str, bool]:
    """Check and display system prerequisites."""
    console.print("\n[bold blue]Checking Prerequisites...[/bold blue]")
    
    checks = {}
    
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
        transient=True
    ) as progress:
        
        # AWS CLI check
        task = progress.add_task("Checking AWS CLI...", total=None)
        try:
            import boto3
            checks["aws_sdk"] = True
            progress.update(task, description="AWS SDK available - OK")
        except ImportError:
            checks["aws_sdk"] = False
            progress.update(task, description="AWS SDK missing - ERROR")
        
        # AWS Authentication check
        progress.update(task, description="Checking AWS authentication...")
        try:
            if aws_auth.check_aws_credentials():
                profile = aws_auth.get_current_profile()
                if profile:
                    checks["aws_auth"] = True
                    progress.update(task, description=f"AWS profile '{profile}' - OK")
                else:
                    checks["aws_auth"] = True
                    progress.update(task, description="AWS environment variables - OK")
            else:
                checks["aws_auth"] = False
                progress.update(task, description="No AWS credentials configured - WARN")
        except Exception:
            checks["aws_auth"] = False
            progress.update(task, description="AWS authentication failed - ERROR")
        
        # Core runtime check
        progress.update(task, description="Checking bluearch-core...")
        try:
            request_core("GET", "/api/v1/core/health", service_token=False, timeout=2.0)
            checks["database"] = True
            progress.update(task, description="bluearch-core - OK")
        except Exception as e:
            checks["database"] = False
            progress.update(task, description=f"bluearch-core check failed - ERROR")
    
    # Display results
    results_table = Table(title="Prerequisites Check", show_header=True, header_style="bold magenta")
    results_table.add_column("Component", style="cyan", width=20)
    results_table.add_column("Status", style="white", width=15)
    results_table.add_column("Action Needed", style="yellow", width=40)
    
    status_map = {
        "aws_sdk": ("AWS SDK", "OK" if checks.get("aws_sdk") else "ERROR", "" if checks.get("aws_sdk") else "Install boto3: pip install boto3"),
        "aws_auth": ("AWS Authentication", "OK" if checks.get("aws_auth") else "WARN", "" if checks.get("aws_auth") else "Configure AWS profile: aws configure sso"),
        "database": ("BlueArch Core", "OK" if checks.get("database") else "ERROR", "" if checks.get("database") else "Start bluearch-core: bluearch-core start --daemon")
    }
    
    for key, (component, status, action) in status_map.items():
        color = "green" if status == "OK" else "red" if status == "ERROR" else "yellow"
        results_table.add_row(component, f"[{color}]{status}[/{color}]", action)
    
    console.print(results_table)
    
    critical_failures = [k for k in ["aws_sdk", "database"] if not checks.get(k, False)]
    if critical_failures:
        console.print(f"\n[red]Critical setup issues detected. Please resolve the above issues and try again.[/red]")
        return checks
    
    if not checks.get("aws_auth"):
        console.print(f"\n[yellow]AWS authentication not configured. We'll help you set this up.[/yellow]")
    
    return checks


def configure_aws_authentication():
    """Guide user through AWS authentication setup."""
    console.print("\n[bold blue]AWS Authentication Setup[/bold blue]")
    
    current_profile = aws_auth.get_current_profile()
    if current_profile:
        console.print(f"Current AWS profile: [cyan]{current_profile}[/cyan]")
        try:
            if Confirm.ask("Use this profile?", default=True):
                return current_profile
        except EOFError:
            console.print("[yellow]Using current profile (no input available)[/yellow]")
            return current_profile
    
    console.print("\n[dim]Available options:[/dim]")
    console.print("1. Use existing AWS profile")
    console.print("2. Configure new SSO profile")
    console.print("3. Use environment variables")
    
    choice = Prompt.ask("How would you like to authenticate with AWS?", choices=["1", "2", "3"], default="1")
    
    if choice == "1":
        profile = Prompt.ask("Enter AWS profile name", default="default")
        settings.env.set("AWS_PROFILE", profile)
        console.print(f"Set AWS profile to: [cyan]{profile}[/cyan]")
        return profile
    
    elif choice == "2":
        console.print("\n[yellow]To configure AWS SSO:[/yellow]")
        console.print("1. Run: [cyan]aws configure sso[/cyan]")
        console.print("2. Follow the prompts to set up your SSO profile")
        console.print("3. Return here and select option 1")
        console.print("\nAfter setting up SSO, restart this setup wizard.")
        raise typer.Exit()
    
    else:  # choice == "3"
        console.print("\n[yellow]Using environment variables.[/yellow]")
        console.print("Make sure AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY are set.")
        return None


def _create_safe_default_rules():
    """Create minimal safe default rules inline."""
    safe_rule = {
        "name": "safe_defaults_untagged",
        "description": "Apply safe unknown tags to untagged resources",
        "resource_types": ["AWS::EC2::Instance", "AWS::S3::Bucket", "AWS::Lambda::Function"],
        "conditions": [],
        "tag_templates": [
            {"key": "Environment", "value": "unknown"},
            {"key": "Owner", "value": "unknown"},
            {"key": "ManagedBy", "value": "tag-manager"},
            {"key": "NeedsReview", "value": "true"}
        ],
        "priority": 100,
        "enabled": True
    }
    
    try:
        upsert_by_filter(
            "tag-manager",
            "tagging-rules",
            filters=[("name", safe_rule["name"])],
            payload=safe_rule,
        )
        console.print("[green]Created safe default tagging rule[/green]")
    except Exception as e:
        console.print(f"[yellow]Could not create default rule: {e}[/yellow]")


def discover_initial_resources():
    """Run initial resource discovery and show results."""
    console.print("\n[bold blue]Discovering Your AWS Resources...[/bold blue]")
    console.print("[dim]This will scan your AWS account to find existing resources.[/dim]")
    
    try:
        if not Confirm.ask("Start resource discovery?", default=True):
            console.print("[yellow]Skipping resource discovery. You can run it later with: tag-manager tags scan[/yellow]")
            return
    except EOFError:
        console.print("[yellow]Skipping resource discovery (no input available). You can run it later with: tag-manager tags scan[/yellow]")
        return
    
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
        transient=True
    ) as progress:
        task = progress.add_task("Scanning AWS resources...", total=None)
        
        try:
            # Use direct AWS API calls instead of worker tasks for setup wizard
            progress.update(task, description="Initializing AWS clients...")
            
            # Get available regions (limit to common ones for speed)
            regions = ["us-east-1", "us-west-2", "eu-west-1"]
            services = ["ec2", "s3", "lambda"]
            
            total_resources = 0
            service_counts = {}
            discovered_resources = []
            
            for service in services:
                progress.update(task, description=f"Scanning {service.upper()} resources...")
                service_count = 0
                
                for region in regions:
                    try:
                        if service == "ec2":
                            client = aws_auth.get_client("ec2", region)
                            response = client.describe_instances()
                            for reservation in response.get('Reservations', []):
                                for instance in reservation['Instances']:
                                    discovered_resources.append({
                                        'resource_id': instance['InstanceId'],
                                        'resource_arn': f"arn:aws:ec2:{region}:{instance.get('OwnerId', '000000000000')}:instance/{instance['InstanceId']}",
                                        'service_name': 'ec2',
                                        'resource_type': 'AWS::EC2::Instance',
                                        'region': region,
                                        'account_id': instance.get('OwnerId', '000000000000'),
                                        'current_tags': {tag['Key']: tag['Value'] for tag in instance.get('Tags', [])},
                                        'created_at': instance.get('LaunchTime'),
                                        'metadata': {
                                            'InstanceType': instance.get('InstanceType'),
                                            'State': instance.get('State', {}).get('Name')
                                        }
                                    })
                            service_count += sum(len(r['Instances']) for r in response.get('Reservations', []))
                        elif service == "s3":
                            if region == "us-east-1":  # S3 is global, only check once
                                client = aws_auth.get_client("s3")
                                response = client.list_buckets()
                                for bucket in response.get('Buckets', []):
                                    # Try to get bucket tags
                                    bucket_tags = {}
                                    try:
                                        tags_response = client.get_bucket_tagging(Bucket=bucket['Name'])
                                        bucket_tags = {tag['Key']: tag['Value'] for tag in tags_response.get('TagSet', [])}
                                    except:
                                        pass  # Bucket has no tags
                                    
                                    discovered_resources.append({
                                        'resource_id': bucket['Name'],
                                        'resource_arn': f"arn:aws:s3:::{bucket['Name']}",
                                        'service_name': 's3',
                                        'resource_type': 'AWS::S3::Bucket',
                                        'region': 'us-east-1',  # S3 buckets are global but show as us-east-1
                                        'account_id': '000000000000',  # Will be updated if we can get it
                                        'current_tags': bucket_tags,
                                        'created_at': bucket.get('CreationDate'),
                                        'metadata': {}
                                    })
                                service_count += len(response.get('Buckets', []))
                        elif service == "lambda":
                            client = aws_auth.get_client("lambda", region)
                            response = client.list_functions()
                            for function in response.get('Functions', []):
                                # Try to get function tags
                                function_tags = {}
                                try:
                                    tags_response = client.list_tags(Resource=function['FunctionArn'])
                                    function_tags = tags_response.get('Tags', {})
                                except:
                                    pass  # Function has no tags
                                
                                discovered_resources.append({
                                    'resource_id': function['FunctionName'],
                                    'resource_arn': function['FunctionArn'],
                                    'service_name': 'lambda',
                                    'resource_type': 'AWS::Lambda::Function',
                                    'region': region,
                                    'account_id': function['FunctionArn'].split(':')[4],
                                    'current_tags': function_tags,
                                    'created_at': function.get('LastModified'),
                                    'metadata': {
                                        'Runtime': function.get('Runtime'),
                                        'Handler': function.get('Handler')
                                    }
                                })
                            service_count += len(response.get('Functions', []))
                    except Exception as e:
                        console.print(f"[dim]Warning: Failed to scan {service.upper()} in {region}: {e}[/dim]")
                        continue  # Skip regions/services that fail
                
                service_counts[service] = service_count
                total_resources += service_count
            
            # Store discovered resources in database
            if discovered_resources:
                progress.update(task, description="Storing resources in bluearch-core...")
                for resource_data in discovered_resources:
                    try:
                        payload = resource_payload(resource_data)
                        upsert_by_filter(
                            "core",
                            "resources",
                            filters=[("resource_arn", payload["resource_arn"])],
                            payload=payload,
                        )
                    except Exception as e:
                        console.print(f"[dim]Warning: Could not store {resource_data['resource_id']}: {e}[/dim]")
                        continue
            
            console.print(f"\n[green]Discovery completed![/green]")
            console.print(f"Found {total_resources} resources")
            
            # Show summary by service
            if service_counts:
                from rich.table import Table
                summary_table = Table(title="Resources by Service", show_header=True, header_style="bold magenta")
                summary_table.add_column("Service", style="cyan")
                summary_table.add_column("Count", style="white", justify="right")
                
                for service, count in service_counts.items():
                    summary_table.add_row(service.upper(), str(count))
                
                console.print(summary_table)
            
        except Exception as e:
            console.print(f"[red]Discovery failed: {e}[/red]")
            console.print("[yellow]You can run discovery later with: tag-manager tags scan[/yellow]")


def setup_initial_tagging_rules():
    """Guide user through setting up their first tagging rules with safe defaults."""
    console.print("\n[bold blue]Setting Up Tagging Policies[/bold blue]")
    console.print("[dim]We'll create safe default rules that won't break anything.[/dim]\n")
    
    console.print("[bold yellow]Available Rule Sets:[/bold yellow]")
    console.print("1. [bold green]Safe Defaults (RECOMMENDED)[/bold green] - Mark untagged resources with 'unknown' values")
    console.print("   [dim]- Sets Environment=unknown, Owner=unknown[/dim]")
    console.print("   [dim]- Marks resources with NeedsReview=true[/dim]")
    console.print("   [dim]- Won't affect resource functionality[/dim]\n")
    
    console.print("2. [cyan]Standard Rules[/cyan] - Common governance and cost tracking tags")
    console.print("3. [yellow]Advanced Rules[/yellow] - Comprehensive tagging with lifecycle management")
    console.print("4. [dim]Skip[/dim] - Set up rules manually later\n")
    
    console.print("[bold green]DEFAULT: Option 1 (Safe Defaults) will be used if you press Enter[/bold green]\n")
    
    try:
        choice = Prompt.ask("Which rule set would you like to start with?", choices=["1", "2", "3", "4"], default="1")
    except EOFError:
        console.print("[yellow]Using safe defaults (no input available)[/yellow]")
        choice = "1"
    
    if choice == "4":
        console.print("[yellow]Skipping rule setup. You can add rules later with: tag-manager tags rules[/yellow]")
        return None
    
    # Load appropriate rules
    try:
        from ..commands.unified_tags import _load_rules
        
        # Find rules file based on choice
        possible_config_dirs = [
            Path(__file__).parent.parent.parent / "config",
            Path.cwd() / "config",
            Path.cwd().parent / "config"
        ]
        
        rule_file_map = {
            "1": "setup_untagged_only.json",  # Use simplified rules for setup
            "2": "production_tagging_rules.json",
            "3": "advanced_tagging_rules.json"
        }
        
        rules_filename = rule_file_map[choice]
        rules_file = None
        
        for config_dir in possible_config_dirs:
            potential_file = config_dir / rules_filename
            if potential_file.exists():
                rules_file = potential_file
                break
        
        if rules_file and rules_file.exists():
            console.print(f"\n[dim]Loading rules from: {rules_file}[/dim]")
            _load_rules(str(rules_file), replace_existing=False)
            
            # Show what was loaded
            with open(rules_file, 'r') as f:
                rules_data = json.load(f)
            
            console.print(f"\n[green]OK Loaded {len(rules_data)} tagging rules:[/green]")
            for rule in rules_data[:3]:  # Show first 3
                console.print(f"  - [cyan]{rule['name']}[/cyan]: {rule['description']}")
            if len(rules_data) > 3:
                console.print(f"  [dim]... and {len(rules_data) - 3} more[/dim]")
            
            return choice
        else:
            console.print("[yellow]Rules file not found. Using fallback safe defaults.[/yellow]")
            # Create minimal safe rules inline
            _create_safe_default_rules()
            return "1"
    
    except Exception as e:
        console.print(f"[red]Failed to load rules: {e}[/red]")
        console.print("[yellow]You can set up rules later with: tag-manager tags rules[/yellow]")
        return None


def run_enforcement_preview():
    """Run a dry-run enforcement to show what would be tagged."""
    console.print("\n[bold blue]Preview Tag Enforcement[/bold blue]")
    console.print("[dim]Let's see what tags would be applied to your completely untagged resources.[/dim]\n")
    
    try:
        from ..commands.unified_tags import _evaluate_rule_for_resource

        all_resources = list_objects("core", "resources")
        untagged_resources = [resource for resource in all_resources if not (resource.current_tags or {})][:20]
        resources = untagged_resources[:10]
        rules = [
            rule.to_dict()
            for rule in list_objects("tag-manager", "tagging-rules", filters=[("enabled", "true")])
        ]

        if not resources:
            console.print("[yellow]No resources found. Run discovery first.[/yellow]")
            return

        if not rules:
            console.print("[yellow]No tagging rules enabled.[/yellow]")
            return

        preview_limit = len(resources)
        console.print(f"[cyan]Analyzing {preview_limit} completely untagged resources with {len(rules)} rules...[/cyan]")
        if len(untagged_resources) > len(resources):
            console.print(f"[dim]Note: Found {len(untagged_resources)} completely untagged resources, showing preview of {preview_limit}.[/dim]\n")
        else:
            console.print(f"[dim]Note: Preview shows all {preview_limit} completely untagged resources.[/dim]\n")

        resources_to_tag = []

        for resource in resources:  # Check the filtered untagged resources
            current_tags = resource.current_tags or {}

            # Evaluate each rule against this resource
            would_add_tags = []
            for rule_dict in rules:
                try:
                    action = _evaluate_rule_for_resource(resource, rule_dict, None)
                    if action and action.get('tags'):
                        # Only show new tags that would be added
                        for key, value in action['tags'].items():
                            if key not in current_tags:
                                would_add_tags.append(f"{key}={value}")
                except Exception:
                    continue  # Skip problematic rules in preview

            if would_add_tags:
                resources_to_tag.append({
                    'resource': resource,
                    'current_count': len(current_tags),
                    'would_add': would_add_tags
                })

        # Show up to 5 examples
        for item in resources_to_tag[:5]:
            resource = item['resource']
            console.print(f"[yellow]Resource:[/yellow] {resource.service_name.upper()} - {resource.resource_id}")
            console.print(f"  [dim]Current tags:[/dim] {item['current_count']} tags")
            console.print(f"  [green]Would add:[/green] {', '.join(item['would_add'])}")
            console.print()

        sample_actions = len(resources_to_tag)

        if sample_actions == 0:
            if len(untagged_resources) == 0:
                console.print("[green]All resources already have at least some tags![/green]")
                console.print("[yellow]Checking for resources missing governance tags (Environment/Owner)...[/yellow]")

                governance_resources = [
                    resource for resource in all_resources
                    if resource.current_tags and (
                        "Environment" not in resource.current_tags or "Owner" not in resource.current_tags
                    )
                ][:10]

                if governance_resources:
                    console.print(f"[cyan]Found {len(governance_resources)} resources missing governance tags.[/cyan]")
                    for i, resource in enumerate(governance_resources[:3], 1):
                        current_tags = resource.current_tags or {}
                        missing = []
                        if 'Environment' not in current_tags:
                            missing.append('Environment')
                        if 'Owner' not in current_tags:
                            missing.append('Owner')
                        console.print(f"[yellow]Resource {i}:[/yellow] {resource.service_name.upper()} - {resource.resource_id}")
                        console.print(f"  [dim]Current tags:[/dim] {len(current_tags)} tags")
                        console.print(f"  [red]Missing:[/red] {', '.join(missing)}")
                        console.print()

                    console.print(f"[bold]Summary:[/bold] Would add governance tags to {len(governance_resources)} resources")
                    console.print("[dim]Use 'tag-manager tags apply --auto' to apply comprehensive governance tags.[/dim]")
                else:
                    console.print("[green]All resources have governance tags![/green]")
            else:
                console.print("[green]No tags would be applied to the completely untagged resources![/green]")
        else:
            console.print(f"[bold]Summary:[/bold] Would tag {sample_actions} completely untagged resources with safe defaults")
            console.print("[dim]These tags mark resources for review without breaking anything.[/dim]")
            if len(untagged_resources) > len(resources):
                console.print(f"[yellow]Note: Found {len(untagged_resources)} completely untagged resources total. Preview shows {len(resources)}.[/yellow]")
    
    except Exception as e:
        console.print(f"[yellow]Could not preview enforcement: {e}[/yellow]")


def apply_initial_tags():
    """Interactive tag application with preview, selection, and AWS resource updates."""
    console.print("\n[bold blue]Apply Initial Tags[/bold blue]")
    console.print("[dim]Let's apply safe default tags to completely untagged resources.[/dim]\n")
    
    try:
        from ..commands.unified_tags import _evaluate_rule_for_resource, _apply_tags_to_aws_resource
        from rich.table import Table
        from rich.prompt import Prompt, Confirm

        all_resources = list_objects("core", "resources")
        untagged_resources = [resource for resource in all_resources if not (resource.current_tags or {})][:20]

        # Debug: show what we found
        console.print(f"[dim]Debug: Found {len(untagged_resources)} completely untagged resources[/dim]")
        for resource in untagged_resources[:3]:  # Show first 3 for debugging
            current_tags = resource.current_tags or {}
            console.print(f"[dim]  - {resource.service_name.upper()} {resource.resource_id}: {len(current_tags)} tags (completely untagged)[/dim]")

        # Get enabled rules for later use
        rules = [
            rule.to_dict()
            for rule in list_objects("tag-manager", "tagging-rules", filters=[("enabled", "true")])
        ]
        if not rules:
            console.print("[yellow]No tagging rules enabled. Use 'tag-manager tags rules load' first.[/yellow]")
            return

        if not untagged_resources:
            console.print("[green]All resources already have at least some tags![/green]")
            console.print("[yellow]However, some resources may be missing governance tags like Environment and Owner.[/yellow]")

            try:
                continue_governance = Confirm.ask(
                    "\nWould you like to apply governance tags to resources missing Environment/Owner tags?",
                    default=True
                )
            except EOFError:
                console.print("[yellow]Continuing with governance tagging (no input available)[/yellow]")
                continue_governance = True

            if not continue_governance:
                console.print("[dim]Setup complete. You can run governance tagging later with: tag-manager tags apply --auto[/dim]")
                return

            # Switch to governance tagging mode
            console.print("[cyan]Switching to governance tagging mode...[/cyan]")
            untagged_resources = [
                resource for resource in all_resources
                if resource.current_tags and (
                    "Environment" not in resource.current_tags or "Owner" not in resource.current_tags
                )
            ][:20]

            if not untagged_resources:
                console.print("[green]All resources already have governance tags![/green]")
                return

            console.print(f"[cyan]Found {len(untagged_resources)} resources missing governance tags[/cyan]")
            for resource in untagged_resources[:3]:
                current_tags = resource.current_tags or {}
                console.print(f"[dim]  - {resource.service_name.upper()} {resource.resource_id}: Missing {'Environment' if 'Environment' not in current_tags else ''} {'Owner' if 'Owner' not in current_tags else ''}[/dim]")

        # Re-evaluate each resource to get the exact tags that would be applied
        taggable_resources = []
        for resource in untagged_resources:
            tags_to_apply = {}
            for rule_dict in rules:
                try:
                    action = _evaluate_rule_for_resource(resource, rule_dict, None)
                    if action and action.get('tags'):
                        current_tags = resource.current_tags or {}
                        # Only add tags that don't already exist
                        for key, value in action['tags'].items():
                            if key not in current_tags:
                                tags_to_apply[key] = value
                except Exception as e:
                    console.print(f"[dim]Debug: Tag evaluation error for {resource.resource_id}: {e}[/dim]")
                    continue

            if tags_to_apply:
                taggable_resources.append({
                    'resource': resource,
                    'tags': tags_to_apply
                })

        if not taggable_resources:
            console.print("[green]All completely untagged resources already have the basic tags![/green]")
            return

        resource_type = "completely untagged" if len([r for r in untagged_resources if not (r.current_tags or {})]) > 0 else "governance-missing"
        console.print(f"[cyan]Found {len(taggable_resources)} {resource_type} resources that need tagging:[/cyan]\n")

        table = Table(show_header=True, header_style="bold blue")
        table.add_column("#", style="dim", width=3)
        table.add_column("Service", style="cyan")
        table.add_column("Resource ID", style="yellow")
        table.add_column("Tags to Apply", style="green")
        table.add_column("Count", justify="center")

        for i, item in enumerate(taggable_resources[:10], 1):  # Show first 10
            resource = item['resource']
            tags = item['tags']
            tag_display = ", ".join([f"{k}={v}" for k, v in list(tags.items())[:3]])
            if len(tags) > 3:
                tag_display += f" +{len(tags)-3} more"

            table.add_row(
                str(i),
                resource.service_name.upper(),
                resource.resource_id,
                tag_display,
                str(len(tags))
            )

        console.print(table)

        if len(taggable_resources) > 10:
            console.print(f"[dim]... and {len(taggable_resources)-10} more resources[/dim]")

        # Interactive confirmation
        try:
            action = Prompt.ask(
                "\nWhat would you like to do?",
                choices=["apply", "customize", "skip"],
                default="apply"
            )
        except EOFError:
            console.print("[yellow]Skipping tag application (no input available)[/yellow]")
            return

        if action == "skip":
            console.print("[yellow]Skipping tag application. You can apply tags later with: tag-manager tags apply --auto[/yellow]")
            return
        elif action == "customize":
            console.print("[yellow]Advanced customization not implemented yet. Using default tags.[/yellow]")

        # Apply tags to AWS resources and core storage
        console.print("\n[bold green]Applying tags to AWS resources...[/bold green]")

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=console,
            transient=False
        ) as progress:
            task = progress.add_task("Tagging resources", total=len(taggable_resources))

            success_count = 0
            error_count = 0

            for item in taggable_resources:
                resource = item['resource']
                tags = item['tags']

                try:
                    progress.update(task, description=f"Tagging {resource.service_name.upper()} {resource.resource_id}")

                    # Apply to AWS resource
                    aws_success = _apply_tags_to_aws_resource(resource.resource_arn, tags, resource.service_name)

                    if aws_success:
                        current_tags = resource.current_tags or {}
                        current_tags.update(tags)
                        update_record(
                            "core",
                            "resources",
                            resource.to_dict(),
                            {"current_tags": current_tags},
                        )
                        success_count += 1
                    else:
                        error_count += 1

                except Exception as e:
                    console.print(f"[red]Error tagging {resource.resource_id}: {e}[/red]")
                    error_count += 1

                progress.advance(task)

            # Show results
            console.print(f"\n[bold green]Tagging Complete![/bold green]")
            console.print(f"[green]Successfully tagged: {success_count} resources[/green]")
            if error_count > 0:
                console.print(f"[red]Failed to tag: {error_count} resources[/red]")
            console.print("[dim]All changes have been applied to both AWS and bluearch-core.[/dim]")
    
    except Exception as e:
        console.print(f"[yellow]Could not apply tags: {e}[/yellow]")
        console.print("[dim]You can apply tags manually with: tag-manager tags apply --auto[/dim]")


def run_compliance_check():
    """Run a compliance check to show the current state."""
    console.print("\n[bold blue]Compliance Check[/bold blue]")
    console.print("[dim]Let's check your current tagging compliance.[/dim]\n")
    
    try:
        resources = list_all_records("core", "resources")
        total_resources = len(resources)
        tagged_resources = sum(1 for resource in resources if resource.get("current_tags"))

        if total_resources == 0:
            console.print("[yellow]No resources found. Run discovery first.[/yellow]")
            return

        compliance_rate = (tagged_resources / total_resources) * 100

        # Display compliance summary
        from rich.panel import Panel
        summary = f"""
[bold]Tagging Compliance Summary[/bold]

[cyan]Total Resources:[/cyan] {total_resources}
[green]Tagged Resources:[/green] {tagged_resources}
[red]Untagged Resources:[/red] {total_resources - tagged_resources}
[yellow]Compliance Rate:[/yellow] {compliance_rate:.1f}%

{"[green]Great job! All resources are tagged![/green]" if compliance_rate == 100 else
 "[yellow]Some resources still need tags. Use 'tag-manager tags apply --auto' to fix.[/yellow]" if compliance_rate > 50 else
 "[red]Many resources are untagged. Consider running automated tagging.[/red]"}
"""
        console.print(Panel(summary, title="Compliance Status", border_style="cyan"))
    
    except Exception as e:
        console.print(f"[yellow]Could not check compliance: {e}[/yellow]")


def show_next_steps():
    """Display recommended next steps for the user."""
    next_steps_text = """
[bold green]Setup Complete![/bold green] Here are your recommended next steps:

[bold yellow]1. Run the lifecycle wizard (Recommended)[/bold yellow]
   [cyan]tag-manager lifecycle wizard[/cyan]   # Complete guided workflow

[bold yellow]2. Or follow the manual workflow:[/bold yellow]
   [cyan]tag-manager lifecycle policies create[/cyan]  # Define resource rules
   [cyan]tag-manager lifecycle scan[/cyan]             # Find matching resources
   [cyan]tag-manager lifecycle set-ttl[/cyan]          # Apply TTL tags
   [cyan]tag-manager lifecycle review[/cyan]           # Manage expiring resources

[bold yellow]3. Daily operations[/bold yellow]
   [cyan]tag-manager lifecycle scan --expiring 7[/cyan]  # Resources expiring soon
   [cyan]tag-manager lifecycle review[/cyan]             # Interactive review
   [cyan]tag-manager lifecycle notify[/cyan]             # Send Slack alerts

[bold yellow]4. AI assistant[/bold yellow]
   [cyan]tag-manager ask "what resources are expiring?"[/cyan]
   [cyan]tag-manager ask chat[/cyan]                   # Interactive chat

[dim]For help with any command, add --help (e.g., tag-manager lifecycle --help)[/dim]
"""

    console.print(Panel(next_steps_text, title="What's Next?", border_style="green"))


def run_onboarding_wizard():
    """Run the complete onboarding wizard with full workflow demonstration."""
    try:
        # Step 1: Welcome
        show_welcome_message()
        
        # Step 2: Prerequisites check
        checks = check_prerequisites()
        critical_issues = [k for k in ["aws_sdk", "database"] if not checks.get(k, False)]
        if critical_issues:
            raise typer.Exit(1)
        
        # Step 3: AWS Authentication (if needed)
        if not checks.get("aws_auth"):
            configure_aws_authentication()
        
        # Step 4: Initial resource discovery
        discover_initial_resources()
        
        # Step 5: Setup tagging rules with safe defaults
        rule_choice = setup_initial_tagging_rules()
        
        # Step 6: Preview what would be tagged (dry run)
        if rule_choice:
            run_enforcement_preview()
        
        # Step 7: Apply initial tags (with confirmation)
        if rule_choice in ["1", "2"]:
            apply_initial_tags()
        
        # Step 8: Run compliance check
        run_compliance_check()
        
        # Step 9: Show next steps
        show_next_steps()
        
        console.print("\n[bold green]Setup Complete! Your AWS resources are now being managed by Tag Manager.[/bold green]")
        console.print("[dim]Remember: All default tags are safe and won't affect resource functionality.[/dim]")
        
    except KeyboardInterrupt:
        console.print("\n[yellow]Setup cancelled by user.[/yellow]")
        raise typer.Exit()
    except Exception as e:
        console.print(f"\n[red]Setup failed: {e}[/red]")
        console.print("[dim]You can restart the setup with: tag-manager setup[/dim]")
        raise typer.Exit(1)
