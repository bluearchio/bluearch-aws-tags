"""Rich Live progress display for collection engine.

Provides per-service/region detail with thread-safe updates.
All output is ASCII-only for PyInstaller compatibility.
"""

import time
from threading import Lock
from typing import Dict, List, Optional, Any, Set

from rich.console import Console, RenderableType
from rich.table import Table


class ProgressReporter:
    """Thread-safe progress reporter with Rich Live display."""

    def __init__(
        self,
        console: Console,
        total_jobs: int,
        services: List[str],
        regions: List[str],
    ):
        self._console = console
        self._total_jobs = total_jobs
        self._services = services
        self._regions = regions
        self._lock = Lock()

        self._completed_jobs = 0
        self._total_resources = 0
        self._total_errors = 0
        self._start_time = time.time()

        # Active jobs: {(service, region): start_time}
        self._active: Dict[tuple, float] = {}
        # Completed: {service: {regions_done: set, resource_count: int}}
        self._service_stats: Dict[str, Dict[str, Any]] = {}

    def job_started(self, service: str, region: Optional[str]):
        with self._lock:
            self._active[(service, region)] = time.time()

    def job_completed(self, service: str, region: Optional[str], resource_count: int, errors: int):
        with self._lock:
            self._active.pop((service, region), None)
            self._completed_jobs += 1
            self._total_resources += resource_count
            self._total_errors += errors

            if service not in self._service_stats:
                self._service_stats[service] = {
                    'regions_done': set(),
                    'resource_count': 0,
                }
            stats = self._service_stats[service]
            stats['resource_count'] += resource_count
            if region:
                stats['regions_done'].add(region)

    def job_failed(self, service: str, region: Optional[str], error: str):
        with self._lock:
            self._active.pop((service, region), None)
            self._completed_jobs += 1
            self._total_errors += 1

    def build_display(self) -> RenderableType:
        """Build the Rich renderable for Live display."""
        with self._lock:
            elapsed = time.time() - self._start_time

            table = Table(show_header=False, box=None, padding=(0, 1))
            table.add_column("Info", width=72)

            # Header line
            table.add_row(
                f"[bold cyan][SCAN] Discovering resources "
                f"({self._completed_jobs}/{self._total_jobs} jobs) "
                f"-- {self._total_resources} resources "
                f"-- {elapsed:.1f}s[/bold cyan]"
            )
            table.add_row("")

            # Active jobs
            if self._active:
                table.add_row("  [yellow]Active:[/yellow]")
                for (svc, rgn), start in sorted(self._active.items()):
                    label = f"{svc}/{rgn}" if rgn else svc
                    job_elapsed = time.time() - start
                    table.add_row(f"    {label:<30} scanning... ({job_elapsed:.0f}s)")

            # Completed services
            if self._service_stats:
                table.add_row("")
                table.add_row("  [green]Completed:[/green]")
                # Resource type labels
                type_labels = {
                    'ec2': 'instances + volumes',
                    's3': 'buckets',
                    'lambda': 'functions',
                    'rds': 'databases',
                    'dynamodb': 'tables',
                    'ecs': 'services',
                    'elb': 'load balancers',
                }
                for svc in self._services:
                    stats = self._service_stats.get(svc)
                    if not stats:
                        continue
                    count = stats['resource_count']
                    label = type_labels.get(svc, 'resources')
                    regions_done = stats['regions_done']
                    if svc == 's3':
                        table.add_row(f"    {svc:<14} {count} {label}")
                    else:
                        region_count = len(regions_done)
                        region_word = "region" if region_count == 1 else "regions"
                        table.add_row(
                            f"    {svc:<14} {count} {label} ({region_count} {region_word})"
                        )

            return table

    def get_summary(self) -> Dict[str, Any]:
        """Return summary stats."""
        with self._lock:
            return {
                'completed_jobs': self._completed_jobs,
                'total_jobs': self._total_jobs,
                'total_resources': self._total_resources,
                'total_errors': self._total_errors,
                'elapsed': time.time() - self._start_time,
            }


class MultiAccountProgressReporter:
    """Progress reporter for multi-account discovery."""

    def __init__(
        self,
        console: Console,
        total_accounts: int,
        account_info: Dict[str, str],
    ):
        self._console = console
        self._total_accounts = total_accounts
        self._account_info = account_info
        self._lock = Lock()

        self._start_time = time.time()
        self._total_resources = 0

        # {account_id: {status, service, resources, start_time}}
        self._active_accounts: Dict[str, Dict[str, Any]] = {}
        # [(account_id, name, success, resources, elapsed)]
        self._completed_accounts: List[tuple] = []

    def account_started(self, account_id: str):
        with self._lock:
            self._active_accounts[account_id] = {
                'status': 'starting',
                'service': 'setup',
                'resources': 0,
                'start_time': time.time(),
            }

    def account_progress(self, account_id: str, service: str, status: str, resources: int):
        with self._lock:
            if account_id in self._active_accounts:
                self._active_accounts[account_id]['service'] = service
                self._active_accounts[account_id]['status'] = status
                self._active_accounts[account_id]['resources'] = resources

    def account_completed(self, account_id: str, success: bool, resources: int):
        with self._lock:
            info = self._active_accounts.pop(account_id, {})
            elapsed = time.time() - info.get('start_time', time.time())
            name = self._account_info.get(account_id, account_id)
            self._completed_accounts.append((account_id, name, success, resources, elapsed))
            if success:
                self._total_resources += resources

    def build_display(self) -> RenderableType:
        with self._lock:
            elapsed = time.time() - self._start_time
            done = len(self._completed_accounts)

            table = Table(show_header=False, box=None, padding=(0, 1))
            table.add_column("Info", width=72)

            table.add_row(
                f"[bold cyan][SCAN] Multi-Account Discovery "
                f"({done}/{self._total_accounts} accounts) "
                f"-- {self._total_resources:,} resources "
                f"-- {elapsed:.1f}s[/bold cyan]"
            )
            table.add_row("")

            # Active accounts
            for acc_id, info in self._active_accounts.items():
                name = self._account_info.get(acc_id, acc_id)
                svc = info.get('service', '')
                status = info.get('status', '')
                res = info.get('resources', 0)
                acc_elapsed = time.time() - info.get('start_time', time.time())
                line = f"  Account: {name} ({acc_id})"
                table.add_row(line)
                detail = f"    {svc} {status}"
                if res > 0:
                    detail += f" -- {res} found"
                detail += f" ({acc_elapsed:.0f}s)"
                table.add_row(detail)
                table.add_row("")

            # Completed accounts (last 5)
            for acc_id, name, success, resources, acc_elapsed in self._completed_accounts[-5:]:
                if success:
                    table.add_row(
                        f"  Account: {name} ({acc_id})  --  [green]Done: {resources} resources[/green] ({acc_elapsed:.1f}s)"
                    )
                else:
                    table.add_row(
                        f"  Account: {name} ({acc_id})  --  [red]FAILED[/red]"
                    )

            return table

    def get_summary(self) -> Dict[str, Any]:
        with self._lock:
            return {
                'total_accounts': self._total_accounts,
                'completed_accounts': len(self._completed_accounts),
                'total_resources': self._total_resources,
                'elapsed': time.time() - self._start_time,
            }
