"""Task management commands for container-free operation."""

import typer
from typing import Optional, List
from rich.console import Console
from rich.table import Table
from datetime import datetime

from ..utils.task_tracker import task_tracker
from ..utils.display_utils import print_safe, print_success, print_warning, print_error

task_app = typer.Typer(help="Manage maintenance tasks and scheduling")
console = Console()


@task_app.command("list")
def list_tasks(
    show_all: bool = typer.Option(False, "--all", help="Show all tasks including non-stale ones")
):
    """List maintenance tasks and their status."""

    # Get task status
    task_status = task_tracker.get_task_status()

    if not show_all:
        # Filter to only stale tasks
        task_status = [t for t in task_status if t["is_stale"]]

    if not task_status:
        if show_all:
            print_warning("No tasks configured")
        else:
            print_success("OK All tasks are up to date!")
        return

    # Create table
    table = Table(title="Maintenance Tasks", show_header=True, header_style="bold magenta")
    table.add_column("Task", style="cyan", width=25)
    table.add_column("Priority", width=10)
    table.add_column("Status", width=12)
    table.add_column("Last Run", width=20)
    table.add_column("Schedule", width=20)

    for task in task_status:
        # Format last run
        if task["last_run"]:
            last_run = task["last_run"].strftime("%Y-%m-%d %H:%M")
        else:
            last_run = "Never"

        # Format status
        if task["is_skipped"]:
            status = "[dim]Skipped[/dim]"
        elif task["is_stale"]:
            status = "[yellow]Stale[/yellow]"
        else:
            status = "[green]Current[/green]"

        # Format priority
        priority_color = {
            "critical": "red",
            "high": "yellow",
            "medium": "blue",
            "low": "dim"
        }
        priority = task["priority"]
        if priority in priority_color:
            priority = f"[{priority_color[priority]}]{priority}[/{priority_color[priority]}]"

        # Format schedule
        hours = task["staleness_hours"]
        if hours < 24:
            schedule = f"Every {hours} hour(s)"
        elif hours == 24:
            schedule = "Daily"
        elif hours == 168:
            schedule = "Weekly"
        else:
            schedule = f"Every {hours/24:.0f} days"

        table.add_row(
            task["name"],
            priority,
            status,
            last_run,
            schedule
        )

    console.print(table)


@task_app.command("schedule")
def show_schedule():
    """Show task execution schedule."""

    console.print("\n[bold]Task Execution Schedule[/bold]\n")

    # Group tasks by frequency
    schedule_groups = {
        "Hourly": [],
        "Daily": [],
        "Weekly": [],
        "Other": []
    }

    for task_name, task in task_tracker.tasks.items():
        task_info = {
            "name": task.display_name,
            "description": task.description,
            "hours": task.staleness_hours
        }

        if task.staleness_hours <= 1:
            schedule_groups["Hourly"].append(task_info)
        elif task.staleness_hours <= 24:
            schedule_groups["Daily"].append(task_info)
        elif task.staleness_hours <= 168:
            schedule_groups["Weekly"].append(task_info)
        else:
            schedule_groups["Other"].append(task_info)

    for group_name, tasks in schedule_groups.items():
        if tasks:
            print_safe(f"[cyan]{group_name}:[/cyan]")
            for task in tasks:
                if task["hours"] == 1:
                    freq = "Every hour"
                elif task["hours"] == 24:
                    freq = "Once per day"
                elif task["hours"] == 168:
                    freq = "Once per week"
                else:
                    freq = f"Every {task['hours']} hours"

                print_safe(f"  • {task['name']} - {task['description']}")
                print_safe(f"    [dim]{freq}[/dim]")
            print_safe("")


@task_app.command("enable")
def enable_prompts():
    """Enable task prompts at CLI startup."""
    task_tracker.enable_prompts()
    print_safe("You will be prompted when maintenance tasks need attention")


@task_app.command("disable")
def disable_prompts(
    hours: Optional[int] = typer.Option(None, "--hours", help="Number of hours to disable")
):
    """Disable task prompts."""

    if hours:
        task_tracker.disable_prompts(hours)
    else:
        task_tracker.disable_prompts()
        print_safe("Run 'tag-manager tasks enable' to re-enable")


@task_app.command("reset")
def reset_history(
    confirm: bool = typer.Option(False, "--confirm", help="Confirm reset")
):
    """Reset task execution history."""

    if not confirm:
        print_error("This will reset all task execution history!")
        print_safe("Add --confirm to proceed")
        return

    # Clear history
    task_tracker.history = {}
    task_tracker._save_history()

    print_success("Task history reset")
    print_safe("All tasks will be considered stale")


@task_app.command("mark")
def mark_task_complete(
    task_name: str = typer.Argument(..., help="Task name to mark as complete")
):
    """Manually mark a task as complete."""

    # Find task
    for internal_name, task_obj in task_tracker.tasks.items():
        if task_obj.display_name.lower() == task_name.lower():
            task_tracker.record_task_execution(internal_name, success=True)
            print_success(f"Marked '{task_obj.display_name}' as complete")
            return

    print_error(f"Unknown task: {task_name}")
    print_safe("Use 'tag-manager tasks list' to see available tasks")


@task_app.command("status")
def task_status():
    """Show detailed task status."""

    console.print("\n[bold]Task System Status[/bold]\n")

    # Check prompt settings
    prefs = task_tracker.preferences
    if prefs.get("quiet_mode"):
        print_warning("Prompts: Disabled permanently")
    elif prefs.get("quiet_until", 0) > 0:
        import time
        remaining = (prefs["quiet_until"] - time.time()) / 3600
        if remaining > 0:
            print_warning(f"Prompts: Disabled for {remaining:.1f} more hours")
        else:
            print_success("Prompts: Enabled")
    else:
        print_success("Prompts: Enabled")

    # Count stale tasks
    stale_tasks = task_tracker.get_stale_tasks()
    if stale_tasks:
        print_warning(f"Stale tasks: {len(stale_tasks)}")
        for task in stale_tasks[:3]:  # Show first 3
            print_safe(f"  • {task.display_name}")
        if len(stale_tasks) > 3:
            print_safe(f"  ... and {len(stale_tasks) - 3} more")
    else:
        print_success("Stale tasks: None")

    # Show data files
    print_safe(f"\n[dim]Data directory: {task_tracker.data_dir}[/dim]")
    print_safe(f"[dim]History file: {task_tracker.history_file}[/dim]")
    print_safe(f"[dim]Preferences file: {task_tracker.prefs_file}[/dim]")