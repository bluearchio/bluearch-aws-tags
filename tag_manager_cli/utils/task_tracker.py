"""Task tracking system for container-free operation.

Replaces Celery background tasks with a prompt-based system that:
- Tracks when tasks were last run
- Prompts users when maintenance is needed
- Runs tasks synchronously with progress feedback
"""

import os
import json
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any
from enum import Enum

from rich.console import Console
from rich.table import Table
from rich.prompt import Prompt, Confirm
from rich.progress import Progress, SpinnerColumn, TextColumn

console = Console()


class TaskPriority(Enum):
    """Task priority levels."""
    CRITICAL = "critical"  # Must run immediately
    HIGH = "high"         # Should run soon
    MEDIUM = "medium"     # Can wait a bit
    LOW = "low"          # Optional/maintenance


class TrackedTask:
    """Definition of a tracked task."""

    def __init__(
        self,
        name: str,
        display_name: str,
        description: str,
        staleness_hours: float,
        priority: TaskPriority = TaskPriority.MEDIUM,
        command: Optional[str] = None,
        function: Optional[callable] = None
    ):
        self.name = name
        self.display_name = display_name
        self.description = description
        self.staleness_hours = staleness_hours
        self.priority = priority
        self.command = command  # CLI command to run
        self.function = function  # Python function to call

    def is_stale(self, last_run_timestamp: Optional[float]) -> bool:
        """Check if task is stale based on last run time."""
        if last_run_timestamp is None:
            return True

        hours_since_run = (time.time() - last_run_timestamp) / 3600
        return hours_since_run >= self.staleness_hours


class TaskTracker:
    """Manages task tracking and user prompts."""

    def __init__(self, data_dir: Optional[str] = None):
        """Initialize task tracker with data directory."""
        if data_dir is None:
            data_dir = os.path.expanduser("~/.tag-manager/data")

        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)

        # Task execution history file
        self.history_file = self.data_dir / "task_history.json"

        # User preferences file (skip/remind settings)
        self.prefs_file = self.data_dir / "task_preferences.json"

        # Load existing data
        self.history = self._load_history()
        self.preferences = self._load_preferences()

        # Define tracked tasks
        self.tasks = self._define_tasks()

    def _define_tasks(self) -> Dict[str, TrackedTask]:
        """Define all tracked tasks and their staleness thresholds."""
        tasks = {}

        # Resource discovery
        tasks["resource_discovery"] = TrackedTask(
            name="resource_discovery",
            display_name="Resource Discovery",
            description="Scan AWS resources to update local inventory",
            staleness_hours=24,  # Daily
            priority=TaskPriority.HIGH,
            command="discover"
        )

        # TODO: CloudTrail processing - Disabled temporarily, will be re-enabled in future
        # CloudTrail processing (not yet implemented for container-free)
        # tasks["cloudtrail_processing"] = TrackedTask(
        #     name="cloudtrail_processing",
        #     display_name="CloudTrail Processing",
        #     description="Process CloudTrail events for automated tagging",
        #     staleness_hours=24,  # Daily (less frequent since manual)
        #     priority=TaskPriority.LOW,
        #     command=None,  # Not implemented yet - would need CloudTrail integration
        #     function=None
        # )

        # Cache cleanup (uses local cache, not critical)
        tasks["cache_cleanup"] = TrackedTask(
            name="cache_cleanup",
            display_name="Cache Cleanup",
            description="Clean up old cache entries to free disk space",
            staleness_hours=168,  # Weekly (less critical with diskcache)
            priority=TaskPriority.LOW,
            command=None,  # Cache auto-manages itself with size limits
            function=None
        )

        # Database maintenance
        tasks["database_maintenance"] = TrackedTask(
            name="database_maintenance",
            display_name="Database Maintenance",
            description="Optimize database performance and clean old records",
            staleness_hours=168,  # Weekly
            priority=TaskPriority.LOW,
            command="database optimize"
        )

        # Tag compliance check (user runs this manually)
        tasks["compliance_check"] = TrackedTask(
            name="compliance_check",
            display_name="Tag Compliance Check",
            description="Check resources for required tags",
            staleness_hours=168,  # Weekly (users run manually)
            priority=TaskPriority.LOW,
            command=None,  # Users run 'tags scan' manually when needed
            function=None
        )

        return tasks

    def _load_history(self) -> Dict[str, Any]:
        """Load task execution history from file."""
        if self.history_file.exists():
            try:
                with open(self.history_file, 'r') as f:
                    return json.load(f)
            except (json.JSONDecodeError, IOError):
                return {}
        return {}

    def _save_history(self):
        """Save task execution history to file."""
        try:
            with open(self.history_file, 'w') as f:
                json.dump(self.history, f, indent=2)
        except IOError as e:
            console.print(f"[yellow]Warning: Could not save task history: {e}[/yellow]")

    def _load_preferences(self) -> Dict[str, Any]:
        """Load user preferences from file."""
        if self.prefs_file.exists():
            try:
                with open(self.prefs_file, 'r') as f:
                    return json.load(f)
            except (json.JSONDecodeError, IOError):
                return {}
        return {}

    def _save_preferences(self):
        """Save user preferences to file."""
        try:
            with open(self.prefs_file, 'w') as f:
                json.dump(self.preferences, f, indent=2)
        except IOError as e:
            console.print(f"[yellow]Warning: Could not save preferences: {e}[/yellow]")

    def record_task_execution(
        self,
        task_name: str,
        success: bool = True,
        error_message: Optional[str] = None
    ):
        """Record that a task was executed."""
        if task_name not in self.history:
            self.history[task_name] = {}

        self.history[task_name]["last_run"] = time.time()
        self.history[task_name]["last_success"] = success
        self.history[task_name]["error_message"] = error_message
        self.history[task_name]["run_count"] = self.history[task_name].get("run_count", 0) + 1

        self._save_history()

    def get_stale_tasks(self) -> List[TrackedTask]:
        """Get list of tasks that are stale and need to run."""
        stale_tasks = []

        for task_name, task in self.tasks.items():
            # Check if task is skipped by user preference
            if self.preferences.get(f"skip_{task_name}", False):
                continue

            # Get last run time
            last_run = None
            if task_name in self.history:
                last_run = self.history[task_name].get("last_run")

            # Check if task is stale
            if task.is_stale(last_run):
                stale_tasks.append(task)

        # Sort by priority (critical first) and staleness
        stale_tasks.sort(
            key=lambda t: (
                list(TaskPriority).index(t.priority),
                -self._get_staleness_hours(t.name)
            )
        )

        return stale_tasks

    def _get_staleness_hours(self, task_name: str) -> float:
        """Get how many hours a task has been stale."""
        if task_name not in self.history:
            return float('inf')  # Never run

        last_run = self.history[task_name].get("last_run")
        if last_run is None:
            return float('inf')

        return (time.time() - last_run) / 3600

    def prompt_for_stale_tasks(self, no_prompt: bool = False) -> List[str]:
        """Check for stale tasks without showing warnings.

        Warnings are disabled to avoid annoying users. Tasks can still be
        checked manually using 'tag-manager tasks list' command.

        Args:
            no_prompt: If True, skip showing warning (for CI/automation)

        Returns:
            Empty list (warnings disabled)
        """
        # Task maintenance warnings are disabled
        # Users can check tasks manually with: tag-manager tasks list
        return []

    def run_task(self, task_name: str, progress: Optional[Progress] = None) -> bool:
        """Run a specific task.

        Args:
            task_name: Name of the task to run
            progress: Optional progress bar to update

        Returns:
            True if task succeeded, False otherwise
        """
        if task_name not in self.tasks:
            console.print(f"[red]Unknown task: {task_name}[/red]")
            return False

        task = self.tasks[task_name]

        # Update progress if provided
        if progress:
            task_id = progress.add_task(f"Running {task.display_name}...", total=None)

        try:
            # Run the task
            if task.function:
                # Call Python function
                success = task.function()
            elif task.command:
                # Execute CLI command with timeout
                import subprocess
                try:
                    result = subprocess.run(
                        f"tag-manager {task.command}",
                        shell=True,
                        capture_output=True,
                        text=True,
                        timeout=60  # 60 second timeout per task
                    )
                    success = result.returncode == 0
                    if not success:
                        console.print(f"[red]Error: {result.stderr}[/red]")
                except subprocess.TimeoutExpired:
                    console.print(f"[red]Task timed out after 60 seconds[/red]")
                    success = False
            else:
                # Task has no implementation - skip it
                if progress:
                    progress.update(task_id, description=f"[dim]⊘ {task.display_name} skipped (not implemented)[/dim]")
                # Don't record as failure - just skip
                return None  # Return None to indicate skipped

            # Record execution
            self.record_task_execution(task_name, success)

            # Update progress
            if progress:
                if success:
                    progress.update(task_id, description=f"[green]✓ {task.display_name} completed[/green]")
                else:
                    progress.update(task_id, description=f"[red]✗ {task.display_name} failed[/red]")

            return success

        except Exception as e:
            console.print(f"[red]Error running {task_name}: {e}[/red]")
            self.record_task_execution(task_name, False, str(e))

            if progress:
                progress.update(task_id, description=f"[red]✗ {task.display_name} error[/red]")

            return False

    def run_selected_tasks(self, task_names: List[str]):
        """Run a list of selected tasks with progress display."""
        if not task_names:
            return

        console.print(f"\n[blue]Running {len(task_names)} task(s)...[/blue]\n")

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=console,
            transient=False
        ) as progress:

            success_count = 0
            for task_name in task_names:
                if self.run_task(task_name, progress):
                    success_count += 1

        # Summary
        console.print(f"\n[green]Completed {success_count}/{len(task_names)} tasks[/green]")

    def enable_prompts(self):
        """Re-enable task prompts."""
        self.preferences["quiet_mode"] = False
        self.preferences.pop("quiet_until", None)
        self._save_preferences()
        console.print("[green]Task prompts enabled[/green]")

    def disable_prompts(self, hours: Optional[int] = None):
        """Disable task prompts.

        Args:
            hours: Number of hours to disable (None = permanent)
        """
        if hours:
            self.preferences["quiet_until"] = time.time() + (hours * 3600)
            console.print(f"[yellow]Task prompts disabled for {hours} hours[/yellow]")
        else:
            self.preferences["quiet_mode"] = True
            console.print("[yellow]Task prompts disabled permanently[/yellow]")

        self._save_preferences()

    def get_task_status(self) -> List[Dict[str, Any]]:
        """Get status of all tracked tasks."""
        status = []

        for task_name, task in self.tasks.items():
            task_info = {
                "name": task.display_name,
                "priority": task.priority.value,
                "staleness_hours": task.staleness_hours,
                "is_stale": False,
                "last_run": None,
                "hours_since_run": None,
                "is_skipped": self.preferences.get(f"skip_{task_name}", False)
            }

            if task_name in self.history:
                last_run = self.history[task_name].get("last_run")
                if last_run:
                    task_info["last_run"] = datetime.fromtimestamp(last_run)
                    task_info["hours_since_run"] = (time.time() - last_run) / 3600
                    task_info["is_stale"] = task.is_stale(last_run)
            else:
                task_info["is_stale"] = True

            status.append(task_info)

        return status


# Global task tracker instance
task_tracker = TaskTracker()


def check_and_prompt_tasks(no_prompt: bool = False) -> List[str]:
    """Check for stale tasks and prompt user if needed.

    This should be called at CLI startup.

    Args:
        no_prompt: If True, skip prompting (for CI/automation)

    Returns:
        List of task names that should be run
    """
    # Skip task prompts if AWS is not configured
    # Most tasks require AWS credentials, so don't bother users who haven't set up AWS yet
    import os
    from pathlib import Path

    # Check multiple ways AWS could be configured
    has_aws_env_profile = os.environ.get('AWS_PROFILE') is not None
    has_aws_env_keys = (
        os.environ.get('AWS_ACCESS_KEY_ID') is not None and
        os.environ.get('AWS_SECRET_ACCESS_KEY') is not None
    )
    has_aws_config_dir = Path.home().joinpath('.aws').exists()

    # Only prompt if AWS is configured in some way
    if not has_aws_env_profile and not has_aws_env_keys and not has_aws_config_dir:
        # AWS not configured at all - skip task prompts
        return []

    # Check if quiet mode is active
    prefs = task_tracker.preferences

    # Check temporary quiet period
    quiet_until = prefs.get("quiet_until", 0)
    if quiet_until > time.time():
        return []

    # Get tasks to run
    return task_tracker.prompt_for_stale_tasks(no_prompt)


def run_maintenance_tasks(task_names: Optional[List[str]] = None, no_prompt: bool = False):
    """Run maintenance tasks.

    Args:
        task_names: Specific tasks to run (None = check and prompt)
        no_prompt: If True, skip prompting
    """
    if task_names is None:
        task_names = check_and_prompt_tasks(no_prompt)

    if task_names:
        task_tracker.run_selected_tasks(task_names)