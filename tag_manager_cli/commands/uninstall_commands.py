"""Uninstall command - Completely remove BlueArch AWS Tags and its AWS resources."""

import os
import shutil
import typer
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.prompt import Confirm

from ..utils.core_client import request_core
from ..utils.display_utils import print_safe, print_success, print_warning, print_error
from ..utils.error_handlers import handle_aws_errors

# AWS credential validation result
_aws_credentials_valid = None
_aws_credentials_error = None


def _validate_aws_credentials(region: str = "us-east-1") -> Tuple[bool, str]:
    """
    Validate AWS credentials before proceeding with uninstall.
    Returns (is_valid, error_message).
    """
    global _aws_credentials_valid, _aws_credentials_error

    # Return cached result if available
    if _aws_credentials_valid is not None:
        return _aws_credentials_valid, _aws_credentials_error or ""

    try:
        from ..utils.aws_auth import aws_auth
        sts = aws_auth.get_client("sts", region=region)
        identity = sts.get_caller_identity()
        _aws_credentials_valid = True
        _aws_credentials_error = None
        return True, ""
    except Exception as e:
        _aws_credentials_valid = False
        _aws_credentials_error = str(e)
        return False, str(e)


uninstall_app = typer.Typer(
    help="Uninstall BlueArch AWS Tags and remove all AWS resources",
    no_args_is_help=False
)
console = Console()

# Legacy-compatible AWS resource identifiers still owned by BlueArch AWS Tags
STACKSET_NAME = "BlueArchCLI-CrossAccount-Infrastructure"
MANAGEMENT_STACK_NAME = "BlueArchCLI-Management-Account-Resources"
CUR_STACK_NAME = "TagManagerCUR"
DYNAMODB_TABLE_NAME = "tag-manager-cross-account"
ALARM_NAME_PREFIX = "tag-manager"
SNS_TOPIC_PREFIX = "tag-manager-alerts"
SECRETS_PREFIX = "tag-manager"
RESOURCE_GROUP_NAME = "BlueArch-TagManager"

# Local paths
LOCAL_DATA_DIR = Path.home() / ".tag-manager"
PUBLIC_TAGS_EXECUTABLE = "bluearch-aws-tags"
LEGACY_TAGS_EXECUTABLES = {"tag-manager"}


def _get_aws_clients(region: str = "us-east-1") -> Dict:
    """Get AWS clients for cleanup operations."""
    from ..utils.aws_auth import aws_auth

    return {
        "cloudformation": aws_auth.get_client("cloudformation", region=region),
        "cloudwatch": aws_auth.get_client("cloudwatch", region=region),
        "sns": aws_auth.get_client("sns", region=region),
        "dynamodb": aws_auth.get_client("dynamodb", region=region),
        "secretsmanager": aws_auth.get_client("secretsmanager", region=region),
        "organizations": aws_auth.get_client("organizations", region=region),
        "resource-groups": aws_auth.get_client("resource-groups", region=region),
    }


def _discover_aws_resources(region: str = "us-east-1") -> Dict[str, List]:
    """Discover all AWS resources created by BlueArch AWS Tags."""
    resources = {
        "stacksets": [],
        "stacks": [],
        "resource_groups": [],
        "alarms": [],
        "sns_topics": [],
        "dynamodb_tables": [],
        "secrets": [],
    }

    try:
        clients = _get_aws_clients(region)

        # 1. Check for StackSets
        try:
            cf = clients["cloudformation"]
            paginator = cf.get_paginator("list_stack_sets")
            for page in paginator.paginate(Status="ACTIVE"):
                for ss in page.get("Summaries", []):
                    if ss["StackSetName"] == STACKSET_NAME:
                        resources["stacksets"].append({
                            "name": ss["StackSetName"],
                            "status": ss.get("Status", "UNKNOWN"),
                        })
        except Exception as e:
            console.print(f"[dim]Could not check StackSets: {e}[/dim]")

        # 2. Check for CloudFormation Stacks (Management + CUR)
        try:
            cf = clients["cloudformation"]
            for stack_name in (MANAGEMENT_STACK_NAME, CUR_STACK_NAME):
                try:
                    response = cf.describe_stacks(StackName=stack_name)
                    for stack in response.get("Stacks", []):
                        if stack["StackStatus"] not in ["DELETE_COMPLETE"]:
                            resources["stacks"].append({
                                "name": stack["StackName"],
                                "status": stack["StackStatus"],
                            })
                except cf.exceptions.ClientError as e:
                    if "does not exist" not in str(e):
                        raise
        except Exception as e:
            console.print(f"[dim]Could not check CloudFormation stacks: {e}[/dim]")

        # 2b. Check for Resource Group
        try:
            rg = clients["resource-groups"]
            try:
                rg.get_group(GroupName=RESOURCE_GROUP_NAME)
                resources["resource_groups"].append({
                    "name": RESOURCE_GROUP_NAME,
                })
            except rg.exceptions.NotFoundException:
                pass
        except Exception as e:
            console.print(f"[dim]Could not check Resource Groups: {e}[/dim]")

        # 3. Check for CloudWatch Alarms
        try:
            cw = clients["cloudwatch"]
            paginator = cw.get_paginator("describe_alarms")
            for page in paginator.paginate():
                for alarm in page.get("MetricAlarms", []):
                    if alarm["AlarmName"].startswith(ALARM_NAME_PREFIX):
                        resources["alarms"].append({
                            "name": alarm["AlarmName"],
                            "state": alarm.get("StateValue", "UNKNOWN"),
                        })
        except Exception as e:
            console.print(f"[dim]Could not check CloudWatch alarms: {e}[/dim]")

        # 4. Check for SNS Topics
        try:
            sns = clients["sns"]
            paginator = sns.get_paginator("list_topics")
            for page in paginator.paginate():
                for topic in page.get("Topics", []):
                    topic_arn = topic["TopicArn"]
                    topic_name = topic_arn.split(":")[-1]
                    if topic_name.startswith(SNS_TOPIC_PREFIX):
                        resources["sns_topics"].append({
                            "name": topic_name,
                            "arn": topic_arn,
                        })
        except Exception as e:
            console.print(f"[dim]Could not check SNS topics: {e}[/dim]")

        # 5. Check for DynamoDB Table
        try:
            ddb = clients["dynamodb"]
            try:
                response = ddb.describe_table(TableName=DYNAMODB_TABLE_NAME)
                table = response.get("Table", {})
                if table.get("TableStatus") != "DELETING":
                    resources["dynamodb_tables"].append({
                        "name": DYNAMODB_TABLE_NAME,
                        "status": table.get("TableStatus", "UNKNOWN"),
                    })
            except ddb.exceptions.ResourceNotFoundException:
                pass
        except Exception as e:
            console.print(f"[dim]Could not check DynamoDB tables: {e}[/dim]")

        # 6. Check for Secrets Manager secrets
        try:
            sm = clients["secretsmanager"]
            paginator = sm.get_paginator("list_secrets")
            for page in paginator.paginate():
                for secret in page.get("SecretList", []):
                    if secret["Name"].startswith(SECRETS_PREFIX):
                        resources["secrets"].append({
                            "name": secret["Name"],
                            "arn": secret.get("ARN", ""),
                        })
        except Exception as e:
            console.print(f"[dim]Could not check Secrets Manager: {e}[/dim]")

    except Exception as e:
        console.print(f"[red]Error discovering resources: {e}[/red]")

    return resources


def _wait_for_stackset_operation(cf_client, stackset_name: str, operation_id: str, max_attempts: int = 60, delay: int = 10) -> bool:
    """Wait for a StackSet operation to complete.

    CloudFormation doesn't have a built-in waiter for StackSet operations,
    so we implement manual polling.
    """
    import time

    for attempt in range(max_attempts):
        try:
            response = cf_client.describe_stack_set_operation(
                StackSetName=stackset_name,
                OperationId=operation_id
            )
            status = response.get("StackSetOperation", {}).get("Status", "")

            if status in ("SUCCEEDED", "FAILED", "STOPPED"):
                if status == "SUCCEEDED":
                    return True
                else:
                    console.print(f"  [red]Operation {status}[/red]")
                    return False

            # Still running
            if attempt % 3 == 0:  # Print status every 30 seconds
                console.print(f"  [dim]Operation status: {status} (attempt {attempt + 1}/{max_attempts})...[/dim]")

            time.sleep(delay)

        except Exception as e:
            console.print(f"  [red]Error checking operation status: {e}[/red]")
            return False

    console.print(f"  [red]Timeout waiting for operation to complete[/red]")
    return False


def _delete_stackset(cf_client, org_client, stackset_name: str) -> Tuple[bool, str]:
    """Delete a StackSet and all its instances.

    Handles both SELF_MANAGED and SERVICE_MANAGED StackSets.
    SERVICE_MANAGED StackSets require deletion by OU, not by account.
    """
    try:
        # First, get the StackSet to check permission model
        console.print(f"  [dim]Checking StackSet configuration...[/dim]")
        stackset_info = cf_client.describe_stack_set(StackSetName=stackset_name)
        stackset = stackset_info.get("StackSet", {})
        permission_model = stackset.get("PermissionModel", "SELF_MANAGED")

        # Get all stack instances
        console.print(f"  [dim]Listing stack instances...[/dim]")
        instances = []
        paginator = cf_client.get_paginator("list_stack_instances")
        for page in paginator.paginate(StackSetName=stackset_name):
            instances.extend(page.get("Summaries", []))

        if instances:
            # Group by region
            regions = list(set(i["Region"] for i in instances))

            console.print(f"  [dim]Deleting {len(instances)} stack instances across {len(regions)} regions...[/dim]")
            console.print(f"  [dim]Permission model: {permission_model}[/dim]")

            if permission_model == "SERVICE_MANAGED":
                # SERVICE_MANAGED StackSets require DeploymentTargets with OUs
                # Get the organization root to delete from all OUs
                try:
                    roots = org_client.list_roots()
                    root_id = roots["Roots"][0]["Id"]

                    console.print(f"  [dim]Using organization root: {root_id}[/dim]")

                    # Delete instances using DeploymentTargets
                    operation_id = cf_client.delete_stack_instances(
                        StackSetName=stackset_name,
                        DeploymentTargets={
                            "OrganizationalUnitIds": [root_id]
                        },
                        Regions=regions,
                        RetainStacks=False,
                    )["OperationId"]
                except Exception as org_error:
                    # If we can't get root, try with the OUs from instances
                    console.print(f"  [dim]Could not get org root, trying with OU from instances...[/dim]")
                    ou_ids = list(set(i.get("OrganizationalUnitId", "") for i in instances if i.get("OrganizationalUnitId")))
                    if ou_ids:
                        operation_id = cf_client.delete_stack_instances(
                            StackSetName=stackset_name,
                            DeploymentTargets={
                                "OrganizationalUnitIds": ou_ids
                            },
                            Regions=regions,
                            RetainStacks=False,
                        )["OperationId"]
                    else:
                        return False, f"SERVICE_MANAGED StackSet but could not determine OUs: {org_error}"
            else:
                # SELF_MANAGED StackSets use Accounts
                accounts = list(set(i["Account"] for i in instances))
                operation_id = cf_client.delete_stack_instances(
                    StackSetName=stackset_name,
                    Accounts=accounts,
                    Regions=regions,
                    RetainStacks=False,
                )["OperationId"]

            # Wait for deletion using manual polling (no built-in waiter for StackSet operations)
            console.print(f"  [dim]Waiting for stack instance deletion (this may take several minutes)...[/dim]")
            if not _wait_for_stackset_operation(cf_client, stackset_name, operation_id):
                return False, "Stack instance deletion failed or timed out"

        # Now delete the StackSet itself
        console.print(f"  [dim]Deleting StackSet...[/dim]")
        cf_client.delete_stack_set(StackSetName=stackset_name)

        return True, "Deleted successfully"

    except Exception as e:
        return False, str(e)


def _delete_stack(cf_client, stack_name: str) -> Tuple[bool, str]:
    """Delete a CloudFormation stack."""
    try:
        cf_client.delete_stack(StackName=stack_name)

        # Wait for deletion
        console.print(f"  [dim]Waiting for stack deletion...[/dim]")
        waiter = cf_client.get_waiter("stack_delete_complete")
        waiter.wait(
            StackName=stack_name,
            WaiterConfig={"Delay": 5, "MaxAttempts": 60}
        )

        return True, "Deleted successfully"

    except Exception as e:
        return False, str(e)


def _delete_alarms(cw_client, alarm_names: List[str]) -> Tuple[int, int]:
    """Delete CloudWatch alarms in batches."""
    deleted = 0
    failed = 0

    # CloudWatch delete_alarms accepts up to 100 alarms at once
    batch_size = 100
    for i in range(0, len(alarm_names), batch_size):
        batch = alarm_names[i:i + batch_size]
        try:
            cw_client.delete_alarms(AlarmNames=batch)
            deleted += len(batch)
        except Exception as e:
            console.print(f"  [red]Failed to delete batch: {e}[/red]")
            failed += len(batch)

    return deleted, failed


def _delete_sns_topics(sns_client, topic_arns: List[str]) -> Tuple[int, int]:
    """Delete SNS topics."""
    deleted = 0
    failed = 0

    for arn in topic_arns:
        try:
            sns_client.delete_topic(TopicArn=arn)
            deleted += 1
        except Exception as e:
            console.print(f"  [red]Failed to delete {arn}: {e}[/red]")
            failed += 1

    return deleted, failed


def _delete_dynamodb_table(ddb_client, table_name: str) -> Tuple[bool, str]:
    """Delete a DynamoDB table."""
    try:
        ddb_client.delete_table(TableName=table_name)

        # Wait for deletion
        console.print(f"  [dim]Waiting for table deletion...[/dim]")
        waiter = ddb_client.get_waiter("table_not_exists")
        waiter.wait(
            TableName=table_name,
            WaiterConfig={"Delay": 5, "MaxAttempts": 30}
        )

        return True, "Deleted successfully"

    except Exception as e:
        return False, str(e)


def _delete_secrets(sm_client, secret_names: List[str]) -> Tuple[int, int]:
    """Delete Secrets Manager secrets."""
    deleted = 0
    failed = 0

    for name in secret_names:
        try:
            # Force delete without recovery window
            sm_client.delete_secret(
                SecretId=name,
                ForceDeleteWithoutRecovery=True
            )
            deleted += 1
        except Exception as e:
            console.print(f"  [red]Failed to delete {name}: {e}[/red]")
            failed += 1

    return deleted, failed


def _delete_local_data() -> Tuple[bool, str]:
    """Delete the local BlueArch AWS Tags data directory."""
    try:
        if LOCAL_DATA_DIR.exists():
            shutil.rmtree(LOCAL_DATA_DIR)
            return True, f"Deleted {LOCAL_DATA_DIR}"
        return True, "No local data found"
    except Exception as e:
        return False, str(e)


def _get_binary_path() -> Optional[Path]:
    """Find only the public Tags binary if installed."""
    # Check common installation paths
    paths_to_check = [
        Path.home() / ".local" / "bin" / PUBLIC_TAGS_EXECUTABLE,
        Path("/opt/homebrew/bin") / PUBLIC_TAGS_EXECUTABLE,
        Path("/usr/local/bin") / PUBLIC_TAGS_EXECUTABLE,
        Path("/usr/bin") / PUBLIC_TAGS_EXECUTABLE,
    ]

    for path in paths_to_check:
        if _is_public_tags_executable(path):
            return path

    resolved = shutil.which(PUBLIC_TAGS_EXECUTABLE)
    if resolved and _is_public_tags_executable(Path(resolved)):
        return Path(resolved)

    return None


def _is_public_tags_executable(path: Path) -> bool:
    """Reject legacy names and public symlinks that conceal legacy targets."""
    if path.name in LEGACY_TAGS_EXECUTABLES or path.name != PUBLIC_TAGS_EXECUTABLE:
        return False
    if not path.is_file() or not os.access(path, os.X_OK):
        return False
    try:
        return path.resolve(strict=True).name == PUBLIC_TAGS_EXECUTABLE
    except OSError:
        return False


@uninstall_app.callback(invoke_without_command=True)
@handle_aws_errors
def uninstall(
    ctx: typer.Context,
    region: str = typer.Option("us-east-1", "--region", "-r", help="AWS region"),
    skip_aws: bool = typer.Option(False, "--skip-aws", help="Skip AWS resource deletion"),
    skip_local: bool = typer.Option(False, "--skip-local", help="Skip local data deletion"),
    skip_binary: bool = typer.Option(False, "--skip-binary", help="Skip CLI binary removal"),
    keep_cur: bool = typer.Option(False, "--keep-cur", help="Keep CUR (Cost & Usage Report) stack during uninstall"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Show what would be deleted without deleting"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation prompts"),
    force: bool = typer.Option(False, "--force", help="Force uninstall even if AWS credentials are invalid (will skip AWS cleanup)"),
):
    """
    Completely uninstall BlueArch AWS Tags and remove all AWS resources.

    This command will:

    1. Delete AWS resources:
       - CloudFormation StackSets (cross-account infrastructure)
       - CloudFormation Stacks (management account resources)
       - CloudWatch Alarms (tag-manager-* prefix)
       - SNS Topics (tag-manager-alerts-* prefix)
       - DynamoDB Table (tag-manager-cross-account)
       - Secrets Manager secrets (tag-manager-* prefix)

    2. Delete local data:
       - SQLite database (~/.tag-manager/data/)
       - Cache files (~/.tag-manager/cache/)
       - Configuration (~/.tag-manager/)

    3. Remove CLI binary (if installed via install script)

    Use --dry-run to preview what would be deleted.
    """
    console.print("\n[bold red]TAG-MANAGER UNINSTALL[/bold red]\n")

    if dry_run:
        console.print("[yellow]DRY RUN MODE - No changes will be made[/yellow]\n")

    # Phase 0: Validate AWS credentials (if not skipping AWS)
    credentials_valid = True
    credentials_error = ""
    aws_resources = {}

    if not skip_aws:
        console.print("[bold cyan]Phase 0: Validating AWS credentials...[/bold cyan]\n")
        credentials_valid, credentials_error = _validate_aws_credentials(region)

        if not credentials_valid:
            console.print(f"[red]AWS credentials are not valid or not configured.[/red]")
            console.print(f"[dim]Error: {credentials_error}[/dim]\n")

            if not force:
                # Check if there might be AWS resources (we can't scan without credentials)
                console.print(Panel(
                    "[bold yellow]Cannot proceed without AWS credentials[/bold yellow]\n\n"
                    "AWS resources created by BlueArch AWS Tags cannot be discovered or deleted\n"
                    "without valid AWS credentials. This may leave orphaned resources.\n\n"
                    "[bold]Options:[/bold]\n"
                    "  1. Configure AWS credentials and try again:\n"
                    "     [cyan]export AWS_PROFILE=your-profile && aws sso login[/cyan]\n\n"
                    "  2. Force local-only uninstall (AWS resources will remain):\n"
                    "     [cyan]bluearch-aws-tags uninstall --force[/cyan]\n\n"
                    "  3. Explicitly skip AWS cleanup:\n"
                    "     [cyan]bluearch-aws-tags uninstall --skip-aws[/cyan]",
                    title="[bold red]AWS Credentials Required[/bold red]",
                    border_style="red"
                ))
                raise typer.Exit(1)
            else:
                # Force mode: warn and skip AWS
                console.print(Panel(
                    "[bold yellow]Proceeding with --force flag[/bold yellow]\n\n"
                    "AWS resource cleanup will be skipped.\n"
                    "Any BlueArch AWS Tags resources will remain in your account.\n\n"
                    "To clean them up later, configure credentials and run:\n"
                    "[cyan]bluearch-aws-tags uninstall[/cyan]",
                    title="[bold yellow]Warning: AWS Cleanup Skipped[/bold yellow]",
                    border_style="yellow"
                ))
                skip_aws = True  # Force skip AWS since credentials are invalid
        else:
            console.print("[green]AWS credentials validated successfully.[/green]\n")

    # Phase 1: Discover resources
    console.print("[bold cyan]Phase 1: Discovering resources...[/bold cyan]\n")

    if not skip_aws:
        with console.status("[dim]Scanning AWS resources...[/dim]"):
            aws_resources = _discover_aws_resources(region)

        # Filter out CUR stack if --keep-cur
        if keep_cur and aws_resources.get("stacks"):
            kept = [s for s in aws_resources["stacks"] if s["name"] == CUR_STACK_NAME]
            aws_resources["stacks"] = [s for s in aws_resources["stacks"] if s["name"] != CUR_STACK_NAME]
            if kept:
                console.print(f"[dim]Keeping CUR stack: {CUR_STACK_NAME} (--keep-cur)[/dim]")

    # Check local data
    local_data_exists = LOCAL_DATA_DIR.exists()
    local_data_size = 0
    if local_data_exists:
        for f in LOCAL_DATA_DIR.rglob("*"):
            if f.is_file():
                local_data_size += f.stat().st_size

    # Check binary
    binary_path = _get_binary_path() if not skip_binary else None

    # Phase 2: Display summary
    console.print("[bold cyan]Phase 2: Resources to be deleted[/bold cyan]\n")

    # AWS Resources Table
    if not skip_aws:
        table = Table(title="AWS Resources", show_header=True, header_style="bold magenta")
        table.add_column("Resource Type", style="cyan")
        table.add_column("Count", justify="right")
        table.add_column("Details")

        total_aws = 0

        if aws_resources.get("stacksets"):
            table.add_row(
                "StackSets",
                str(len(aws_resources["stacksets"])),
                ", ".join(s["name"] for s in aws_resources["stacksets"])
            )
            total_aws += len(aws_resources["stacksets"])

        if aws_resources.get("stacks"):
            table.add_row(
                "CloudFormation Stacks",
                str(len(aws_resources["stacks"])),
                ", ".join(s["name"] for s in aws_resources["stacks"])
            )
            total_aws += len(aws_resources["stacks"])

        if aws_resources.get("resource_groups"):
            table.add_row(
                "Resource Groups",
                str(len(aws_resources["resource_groups"])),
                ", ".join(g["name"] for g in aws_resources["resource_groups"])
            )
            total_aws += len(aws_resources["resource_groups"])

        if aws_resources.get("alarms"):
            alarm_names = [a["name"] for a in aws_resources["alarms"]]
            display = alarm_names[:3]
            if len(alarm_names) > 3:
                display.append(f"...and {len(alarm_names) - 3} more")
            table.add_row(
                "CloudWatch Alarms",
                str(len(aws_resources["alarms"])),
                ", ".join(display)
            )
            total_aws += len(aws_resources["alarms"])

        if aws_resources.get("sns_topics"):
            topic_names = [t["name"] for t in aws_resources["sns_topics"]]
            display = topic_names[:3]
            if len(topic_names) > 3:
                display.append(f"...and {len(topic_names) - 3} more")
            table.add_row(
                "SNS Topics",
                str(len(aws_resources["sns_topics"])),
                ", ".join(display)
            )
            total_aws += len(aws_resources["sns_topics"])

        if aws_resources.get("dynamodb_tables"):
            table.add_row(
                "DynamoDB Tables",
                str(len(aws_resources["dynamodb_tables"])),
                ", ".join(t["name"] for t in aws_resources["dynamodb_tables"])
            )
            total_aws += len(aws_resources["dynamodb_tables"])

        if aws_resources.get("secrets"):
            table.add_row(
                "Secrets Manager",
                str(len(aws_resources["secrets"])),
                ", ".join(s["name"] for s in aws_resources["secrets"])
            )
            total_aws += len(aws_resources["secrets"])

        if total_aws == 0:
            console.print("[green]No AWS resources found to delete.[/green]\n")
        else:
            console.print(table)
            console.print(f"\n[bold]Total AWS resources: {total_aws}[/bold]\n")

    # Local Data
    if not skip_local:
        if local_data_exists:
            size_mb = local_data_size / (1024 * 1024)
            console.print(f"[cyan]Local Data:[/cyan] {LOCAL_DATA_DIR} ({size_mb:.2f} MB)")
        else:
            console.print("[green]No local data found.[/green]")

    # Binary
    if not skip_binary:
        if binary_path:
            console.print(f"[cyan]CLI Binary:[/cyan] {binary_path}")
        else:
            console.print("[dim]CLI binary not found in standard locations.[/dim]")

    console.print()

    # Check if there's anything to delete
    has_aws = any(aws_resources.get(k) for k in aws_resources) if aws_resources else False
    has_local = local_data_exists and not skip_local
    has_binary = binary_path is not None and not skip_binary

    if not has_aws and not has_local and not has_binary:
        console.print("[green]Nothing to uninstall. BlueArch AWS Tags is already clean.[/green]")
        return

    if dry_run:
        console.print("[yellow]DRY RUN complete. Use without --dry-run to actually delete.[/yellow]")
        return

    # Phase 3: Confirmation
    console.print("[bold cyan]Phase 3: Confirmation[/bold cyan]\n")

    warning_panel = Panel(
        "[bold yellow]This will remove BlueArch AWS Tags and its AWS resources.[/bold yellow]\n\n"
        "[dim]Only BlueArch AWS Tags resources will be deleted:[/dim]\n"
        "  - StackSets and Stacks created by BlueArch AWS Tags\n"
        "  - CloudWatch alarms with 'tag-manager' prefix\n"
        "  - SNS topics with 'tag-manager-alerts' prefix\n"
        "  - DynamoDB table 'tag-manager-cross-account'\n"
        "  - Secrets Manager entries for tag-manager\n\n"
        "[green]Your other AWS resources will NOT be affected.[/green]",
        title="[bold yellow]Uninstall Confirmation[/bold yellow]",
        border_style="yellow"
    )
    console.print(warning_panel)
    console.print()

    if not yes:
        confirm = Confirm.ask(
            "Proceed with uninstall?",
            default=False
        )
        if not confirm:
            console.print("[yellow]Uninstall cancelled.[/yellow]")
            return

        # Double confirmation for AWS resources
        if has_aws:
            confirm2 = Confirm.ask(
                "Confirm deletion of BlueArch AWS Tags resources?",
                default=False
            )
            if not confirm2:
                console.print("[yellow]Uninstall cancelled.[/yellow]")
                return

    # Phase 4: Delete resources
    console.print("\n[bold cyan]Phase 4: Deleting resources...[/bold cyan]\n")

    errors = []

    # Delete AWS resources
    if not skip_aws and has_aws:
        clients = _get_aws_clients(region)

        # 1. Delete StackSets first (takes longest)
        for ss in aws_resources.get("stacksets", []):
            console.print(f"[yellow]Deleting StackSet:[/yellow] {ss['name']}")
            success, msg = _delete_stackset(
                clients["cloudformation"],
                clients["organizations"],
                ss["name"]
            )
            if success:
                print_success(f"  Deleted: {ss['name']}")
            else:
                print_error(f"  Failed: {msg}")
                errors.append(f"StackSet {ss['name']}: {msg}")

        # 2. Delete Resource Groups
        for rg in aws_resources.get("resource_groups", []):
            console.print(f"[yellow]Deleting Resource Group:[/yellow] {rg['name']}")
            try:
                clients["resource-groups"].delete_group(GroupName=rg["name"])
                print_success(f"  Deleted: {rg['name']}")
            except Exception as e:
                print_error(f"  Failed: {e}")
                errors.append(f"Resource Group {rg['name']}: {e}")

        # 3. Delete CloudFormation Stacks
        for stack in aws_resources.get("stacks", []):
            console.print(f"[yellow]Deleting Stack:[/yellow] {stack['name']}")
            success, msg = _delete_stack(clients["cloudformation"], stack["name"])
            if success:
                print_success(f"  Deleted: {stack['name']}")
            else:
                print_error(f"  Failed: {msg}")
                errors.append(f"Stack {stack['name']}: {msg}")

        # 4. Delete CloudWatch Alarms
        if aws_resources.get("alarms"):
            alarm_names = [a["name"] for a in aws_resources["alarms"]]
            console.print(f"[yellow]Deleting {len(alarm_names)} CloudWatch Alarms...[/yellow]")
            deleted, failed = _delete_alarms(clients["cloudwatch"], alarm_names)
            if deleted > 0:
                print_success(f"  Deleted: {deleted} alarms")
            if failed > 0:
                print_error(f"  Failed: {failed} alarms")
                errors.append(f"CloudWatch Alarms: {failed} failed to delete")

        # 5. Delete SNS Topics
        if aws_resources.get("sns_topics"):
            topic_arns = [t["arn"] for t in aws_resources["sns_topics"]]
            console.print(f"[yellow]Deleting {len(topic_arns)} SNS Topics...[/yellow]")
            deleted, failed = _delete_sns_topics(clients["sns"], topic_arns)
            if deleted > 0:
                print_success(f"  Deleted: {deleted} topics")
            if failed > 0:
                print_error(f"  Failed: {failed} topics")
                errors.append(f"SNS Topics: {failed} failed to delete")

        # 6. Delete DynamoDB Table
        for table in aws_resources.get("dynamodb_tables", []):
            console.print(f"[yellow]Deleting DynamoDB Table:[/yellow] {table['name']}")
            success, msg = _delete_dynamodb_table(clients["dynamodb"], table["name"])
            if success:
                print_success(f"  Deleted: {table['name']}")
            else:
                print_error(f"  Failed: {msg}")
                errors.append(f"DynamoDB {table['name']}: {msg}")

        # 7. Delete Secrets
        if aws_resources.get("secrets"):
            secret_names = [s["name"] for s in aws_resources["secrets"]]
            console.print(f"[yellow]Deleting {len(secret_names)} Secrets...[/yellow]")
            deleted, failed = _delete_secrets(clients["secretsmanager"], secret_names)
            if deleted > 0:
                print_success(f"  Deleted: {deleted} secrets")
            if failed > 0:
                print_error(f"  Failed: {failed} secrets")
                errors.append(f"Secrets: {failed} failed to delete")

        # 8. Clean up EventSyncConfiguration core records
        try:
            records = request_core(
                "GET",
                "/api/v1/storage/core/event-sync-configuration",
                service_token=True,
                params=[("limit", 10000)],
                timeout=10.0,
            )
            count = 0
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
                count += 1
            if count:
                print_success(f"  Deleted {count} EventSyncConfiguration core record(s)")
        except Exception as e:
            console.print(f"[dim]Could not clean EventSync core records: {e}[/dim]")

    # Delete local data
    if not skip_local and has_local:
        console.print(f"[yellow]Deleting local data:[/yellow] {LOCAL_DATA_DIR}")
        success, msg = _delete_local_data()
        if success:
            print_success(f"  {msg}")
        else:
            print_error(f"  Failed: {msg}")
            errors.append(f"Local data: {msg}")

    # Delete binary
    if not skip_binary and has_binary:
        console.print(f"[yellow]Deleting CLI binary:[/yellow] {binary_path}")
        if not _is_public_tags_executable(binary_path):
            print_warning(f"  Not deleting non-public or legacy launcher: {binary_path}")
        else:
            try:
                binary_path.unlink()
                print_success(f"  Deleted: {binary_path}")
            except Exception as e:
                print_error(f"  Failed: {e}")
                errors.append(f"Binary: {e}")
                console.print(f"  [dim]You may need to manually delete: sudo rm {binary_path}[/dim]")

    # Phase 5: Summary
    console.print("\n[bold cyan]Phase 5: Summary[/bold cyan]\n")

    if errors:
        print_warning(f"Uninstall completed with {len(errors)} error(s):")
        for err in errors:
            console.print(f"  [red]-[/red] {err}")
        console.print("\n[yellow]Some resources may need manual cleanup.[/yellow]")
    else:
        print_success("Uninstall completed successfully!")
        console.print("\n[green]All BlueArch AWS Tags resources have been removed.[/green]")
        console.print("[dim]Thank you for using BlueArch AWS Tags![/dim]")
