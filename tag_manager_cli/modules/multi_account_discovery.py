"""
Multi-Account Discovery Module for Cross-Account Resource Scanning

This module enables discovery of AWS resources across multiple accounts in an
AWS Organization using role assumption and parallel processing.
"""

import json
import logging
from typing import Dict, List, Optional, Any, Set
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
import time

from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TaskProgressColumn
from rich.table import Table
from rich.panel import Panel
from rich.tree import Tree
from rich.text import Text

from ..utils.aws_auth import aws_auth
from ..utils.account_iterator import account_iterator
from ..utils.core_storage import (
    clear_relationships,
    clear_resources,
    list_all_records,
    resource_payload,
    upsert_by_filter,
)
from ..utils.error_handlers import handle_aws_errors
from ..modules.discovery import discover_all_resources

logger = logging.getLogger(__name__)
console = Console()


@dataclass
class AccountDiscoveryResult:
    """Result of discovery for a single account"""
    account_id: str
    account_name: str
    success: bool
    resource_count: int
    error_message: Optional[str] = None
    discovered_resources: Optional[List[Dict]] = None
    discovery_time_seconds: float = 0.0
    regions_scanned: List[str] = None
    # Service-level statistics for compact tree display
    service_stats: Optional[Dict[str, Dict[str, Any]]] = None  # {service: {total, compliant, noncompliant, by_region: {region: {total, compliant, noncompliant}}}}
    compliance_summary: Optional[Dict[str, Any]] = None  # {total_compliant, total_noncompliant, required_tags, from_org_policy}


@dataclass
class MultiAccountDiscoveryResult:
    """Aggregated result of multi-account discovery"""
    total_accounts: int
    successful_accounts: int
    failed_accounts: int
    skipped_accounts: int
    total_resources: int
    total_time_seconds: float
    account_results: List[AccountDiscoveryResult]
    enabled_accounts: List[str]
    error_summary: Dict[str, str]


class MultiAccountDiscovery:
    """Discover AWS resources across multiple accounts"""

    def __init__(self):
        self.max_workers = 5  # Max parallel account discovery
        self.role_name = "BlueArchRole"
        self.enabled_accounts_file = Path.home() / ".tag-manager" / "data" / "enabled_accounts.json"
        self._dynamodb_state = None

    def get_enabled_accounts(self) -> List[str]:
        """Get list of enabled accounts for scanning.

        Checks DynamoDB state, the local scan-target database, local cache, and
        falls back to auto-discovery from AWS Organizations if no accounts are
        configured locally.
        """
        enabled_accounts: Set[str] = set()

        # Try to use DynamoDB state service
        try:
            if self._dynamodb_state is None:
                from ..services import dynamodb_state
                self._dynamodb_state = dynamodb_state

            # Get enabled accounts from DynamoDB/local cache
            accounts = self._dynamodb_state.get_enabled_accounts()
            if accounts:
                enabled_accounts.update(accounts)
        except ImportError:
            logger.warning("DynamoDB state service not available, falling back to JSON file")
        except Exception as e:
            logger.warning(f"Failed to get accounts from DynamoDB state: {str(e)}, falling back to JSON file")

        try:
            rows = list_all_records(
                "core",
                "account-status",
                filters=[
                    ("enabled_for_discovery", "true"),
                    ("status", "ACTIVE"),
                ],
            )
            enabled_accounts.update(row["account_id"] for row in rows if row.get("account_id"))
        except Exception as e:
            logger.debug(f"Failed to load enabled accounts from AccountStatus: {e}")

        # Fallback to direct JSON file reading for backward compatibility
        if self.enabled_accounts_file.exists():
            try:
                with open(self.enabled_accounts_file, 'r') as f:
                    accounts = json.load(f)
                    if accounts:
                        enabled_accounts.update(accounts)
            except Exception as e:
                logger.error(f"Failed to load enabled accounts: {str(e)}")

        if enabled_accounts:
            return sorted(enabled_accounts)

        # Auto-discover from AWS Organizations when no local state exists
        return self._auto_discover_org_accounts()

    def _auto_discover_org_accounts(self) -> List[str]:
        """Auto-discover scannable accounts from AWS Organizations.

        Lists all ACTIVE accounts in the organization, excludes the current
        account, and validates that the cross-account role can be assumed.
        Results are cached locally so subsequent calls don't re-probe.
        """
        try:
            session = aws_auth.initialize_session()
            if session is None:
                return []

            # Get current account to exclude from the list
            sts = session.client('sts')
            current_account = sts.get_caller_identity()['Account']

            # List all accounts from AWS Organizations
            org_client = session.client('organizations')
            all_accounts = []
            paginator = org_client.get_paginator('list_accounts')
            for page in paginator.paginate():
                for account in page.get('Accounts', []):
                    if (account['Status'] == 'ACTIVE'
                            and account['Id'] != current_account):
                        all_accounts.append(account['Id'])

            if not all_accounts:
                return []

            logger.info(
                f"Auto-discovered {len(all_accounts)} org accounts, "
                f"validating cross-account access..."
            )

            # Get ExternalId once for all validations
            external_id = aws_auth.get_cross_account_external_id()

            # Validate which accounts have the BlueArchRole deployed
            enabled = []
            for account_id in all_accounts:
                if aws_auth.validate_cross_account_access(
                    account_id,
                    role_name=self.role_name,
                    external_id=external_id,
                ):
                    enabled.append(account_id)

            if enabled:
                logger.info(
                    f"Auto-enabled {len(enabled)}/{len(all_accounts)} "
                    f"accounts with BlueArchRole"
                )
                # Persist so we don't re-probe every time
                self._save_auto_discovered_accounts(enabled)

            return enabled

        except Exception as e:
            logger.debug(f"Auto-discovery from Organizations failed: {e}")
            return []

    def _save_auto_discovered_accounts(self, account_ids: List[str]) -> None:
        """Persist auto-discovered accounts to local cache and DynamoDB."""
        try:
            # Save to DynamoDB state if available
            if self._dynamodb_state is None:
                from ..services import dynamodb_state
                self._dynamodb_state = dynamodb_state
            self._dynamodb_state.enable_accounts(
                account_ids, enabled_by="auto-discovery"
            )
        except Exception:
            pass

        # Always save to local JSON as fallback
        try:
            self.enabled_accounts_file.parent.mkdir(parents=True, exist_ok=True)
            with open(self.enabled_accounts_file, 'w') as f:
                json.dump(account_ids, f)
        except Exception as e:
            logger.warning(f"Failed to save auto-discovered accounts: {e}")

    def _clear_all_resources(self):
        """Delete all resources from the database before discovery."""
        try:
            relationship_count = clear_relationships()
            deleted_count = clear_resources()
            logger.info(
                f"Cleared {deleted_count} resources and {relationship_count} relationships from core storage before discovery"
            )
            console.print(f"[yellow]Cleared {deleted_count} existing resources from core storage[/yellow]")
            return deleted_count
        except Exception as e:
            logger.error(f"Failed to clear resources: {str(e)}")
            return 0

    def clear_all_enabled_accounts(self):
        """Clear all enabled accounts from the database/cache."""
        try:
            # Get all currently enabled accounts
            enabled = self.get_enabled_accounts()

            if enabled:
                # Clear from DynamoDB state if available
                if self._dynamodb_state is None:
                    from ..services import dynamodb_state
                    self._dynamodb_state = dynamodb_state

                # Disable all enabled accounts
                self._dynamodb_state.disable_accounts(enabled, disabled_by="remove-stacks-command")
                logger.info(f"Disabled {len(enabled)} accounts from state")

            # Also clear the local JSON file if it exists
            if self.enabled_accounts_file.exists():
                self.enabled_accounts_file.unlink()
                logger.info("Removed local enabled accounts file")

            return True
        except Exception as e:
            logger.error(f"Failed to clear enabled accounts: {str(e)}")
            # Try to at least clear the local file
            try:
                if self.enabled_accounts_file.exists():
                    self.enabled_accounts_file.unlink()
            except:
                pass
            return False

    def discover_all_accounts(
        self,
        account_ids: Optional[List[str]] = None,
        services: Optional[List[str]] = None,
        regions: Optional[List[str]] = None,
        role_name: Optional[str] = None,
        max_workers: Optional[int] = None,
        show_progress: bool = True,
        save_to_database: bool = True
    ) -> MultiAccountDiscoveryResult:
        """
        Discover resources across multiple AWS accounts.

        Args:
            account_ids: Specific accounts to scan (None = all enabled)
            services: Services to discover (default: ec2, s3, lambda)
            regions: Regions to scan (None = all regions)
            role_name: IAM role name to assume
            max_workers: Max parallel workers
            show_progress: Show progress bars
            save_to_database: Save results to database

        Returns:
            MultiAccountDiscoveryResult with discovery details
        """
        start_time = time.time()
        role_name = role_name or self.role_name
        max_workers = max_workers or self.max_workers

        # Default services if not specified
        if not services:
            services = ['ec2', 's3', 'lambda']

        # Get target accounts
        if account_ids:
            target_accounts = account_ids
        else:
            # Use enabled accounts plus current account
            target_accounts = self.get_enabled_accounts()

            # Always include current account in multi-account discovery
            try:
                current_identity = aws_auth.get_caller_identity()
                current_account = current_identity['Account']
                if current_account and current_account not in target_accounts:
                    target_accounts = [current_account] + target_accounts
            except Exception:
                pass

        if not target_accounts:
            console.print("[yellow]No accounts enabled for scanning.[/yellow]")
            console.print("Enable accounts with 'tag-manager accounts enable'")
            return MultiAccountDiscoveryResult(
                total_accounts=0,
                successful_accounts=0,
                failed_accounts=0,
                skipped_accounts=0,
                total_resources=0,
                total_time_seconds=0,
                account_results=[],
                enabled_accounts=[],
                error_summary={}
            )

        console.print(f"\n[bold cyan]Multi-Account Resource Discovery[/bold cyan]")
        console.print(f"Scanning {len(target_accounts)} accounts across {services}")
        if regions:
            console.print(f"Regions: {regions}")
        else:
            console.print(f"Regions: ALL AWS regions")
        console.print("")

        # Get account details
        all_org_accounts = []
        try:
            all_org_accounts = aws_auth.get_organization_accounts()
        except Exception as e:
            logger.warning(f"Could not fetch organization accounts: {str(e)}")

        # Prepare account info
        account_info = {}
        for acc_id in target_accounts:
            account = next((a for a in all_org_accounts if a['Id'] == acc_id), None)
            account_info[acc_id] = account['Name'] if account else "Unknown"

        # Clear all resources from database before discovery
        if save_to_database:
            self._clear_all_resources()

        # Results storage
        account_results = []
        error_summary = {}
        total_resources = 0

        if show_progress:
            from rich.live import Live
            from rich.table import Table as RichTable
            from threading import Lock

            RESOURCE_TYPE_LABELS = {
                'ec2': 'instances + volumes',
                's3': 'buckets',
                'lambda': 'functions',
                'rds': 'databases',
                'dynamodb': 'tables',
                'ecs': 'services',
                'elb': 'load balancers',
            }

            # Thread-safe progress tracking
            progress_lock = Lock()
            # Per-account state:
            #   'start_time', 'phase' (setup|collecting),
            #   'service_resources' {svc: count},
            #   'service_jobs_done' {svc: n}, 'service_total_jobs' {svc: n},
            #   'total_resources', 'jobs_done', 'total_jobs',
            #   'last_service', 'last_region', 'setup_status'
            account_progress = {}
            completed_accounts = []  # [(account_id, name, success, resources, elapsed)]
            live_ref = [None]  # Mutable ref for callback to trigger display refresh

            def progress_callback(account_id: str, data):
                """Thread-safe progress callback -- receives structured dict."""
                with progress_lock:
                    if account_id not in account_progress:
                        return

                    ap = account_progress[account_id]

                    if isinstance(data, dict) and data.get('phase') == 'setup':
                        # Setup phase (connecting / assuming role)
                        ap['phase'] = 'setup'
                        ap['setup_status'] = data.get('status', '')
                    elif isinstance(data, dict):
                        # Collection engine progress
                        ap['phase'] = 'collecting'
                        ap['last_service'] = data.get('service', '')
                        ap['last_region'] = data.get('region', '')
                        ap['jobs_done'] = data.get('jobs_done', 0)
                        ap['total_jobs'] = data.get('total_jobs', 0)
                        ap['total_resources'] = data.get('total_resources', 0)
                        ap['service_resources'] = data.get('service_resources', {})
                        ap['service_jobs_done'] = data.get('service_jobs_done', {})
                        ap['service_total_jobs'] = data.get('service_total_jobs', {})

                # Trigger live display refresh
                if live_ref[0]:
                    try:
                        live_ref[0].update(build_progress_display())
                    except Exception:
                        pass

            def build_progress_display():
                """Build tree-structured live progress display."""
                table = RichTable(show_header=False, box=None, padding=(0, 0))
                table.add_column("Info", no_wrap=True)

                # Header
                done_count = len(completed_accounts)
                total_res_all = sum(c[3] for c in completed_accounts)
                with progress_lock:
                    for ap in account_progress.values():
                        total_res_all += ap.get('total_resources', 0)
                elapsed = time.time() - start_time

                table.add_row(
                    f"[bold cyan][SCAN] Multi-Account Discovery "
                    f"({done_count}/{len(target_accounts)} accounts) "
                    f"-- {total_res_all:,} resources "
                    f"-- {elapsed:.1f}s[/bold cyan]"
                )
                table.add_row("")

                # Active accounts as tree nodes
                with progress_lock:
                    active_items = list(account_progress.items())

                for acc_id, ap in active_items:
                    name = account_info.get(acc_id, acc_id)
                    acc_elapsed = time.time() - ap.get('start_time', time.time())
                    acc_resources = ap.get('total_resources', 0)
                    phase = ap.get('phase', 'setup')

                    # Account header line
                    header = f"  [bold white]{name}[/bold white] [dim]({acc_id})[/dim]"
                    if acc_resources > 0:
                        header += f"  [green]{acc_resources} found[/green]"
                    header += f"  [dim]{acc_elapsed:.0f}s[/dim]"
                    table.add_row(header)

                    if phase == 'setup':
                        status = ap.get('setup_status', 'connecting')
                        table.add_row(f"    [dim]|--[/dim] [yellow]{status}...[/yellow]")
                    else:
                        # Show per-service tree
                        svc_resources = ap.get('service_resources', {})
                        svc_jobs_done = ap.get('service_jobs_done', {})
                        svc_total_jobs = ap.get('service_total_jobs', {})
                        last_svc = ap.get('last_service', '')
                        last_rgn = ap.get('last_region', '')

                        for i, svc in enumerate(services):
                            s_done = svc_jobs_done.get(svc, 0)
                            s_total = svc_total_jobs.get(svc, 0)
                            s_res = svc_resources.get(svc, 0)
                            label = RESOURCE_TYPE_LABELS.get(svc, 'resources')
                            is_last = (i == len(services) - 1)
                            prefix = "`--" if is_last else "|--"

                            if s_total == 0:
                                # Service not in job list (shouldn't happen)
                                continue
                            elif s_done >= s_total:
                                # Service complete
                                if s_res > 0:
                                    table.add_row(
                                        f"    [dim]{prefix}[/dim] [green]{svc}[/green]"
                                        f"  [green]{s_res} {label}[/green]"
                                    )
                                else:
                                    table.add_row(
                                        f"    [dim]{prefix}[/dim] [dim]{svc}  (no {label})[/dim]"
                                    )
                            else:
                                # Service in progress
                                progress_pct = f"{s_done}/{s_total}"
                                line = f"    [dim]{prefix}[/dim] [cyan]{svc}[/cyan]  scanning ({progress_pct})"
                                if s_res > 0:
                                    line += f"  [green]{s_res} found[/green]"
                                table.add_row(line)

                    table.add_row("")

                # Completed accounts
                for acc_id, name, success, resources, acc_elapsed in completed_accounts:
                    if success:
                        table.add_row(
                            f"  [bold white]{name}[/bold white] [dim]({acc_id})[/dim]"
                            f"  --  [green]Done: {resources} resources[/green]"
                            f"  [dim]{acc_elapsed:.1f}s[/dim]"
                        )
                    else:
                        table.add_row(
                            f"  [bold white]{name}[/bold white] [dim]({acc_id})[/dim]"
                            f"  --  [red]FAILED[/red]"
                        )

                return table

            with Live(build_progress_display(), console=console, refresh_per_second=4) as live:
                live_ref[0] = live
                # Process accounts in parallel
                with ThreadPoolExecutor(max_workers=max_workers) as executor:
                    # Submit discovery tasks and track start times
                    future_to_account = {}
                    for acc_id in target_accounts:
                        with progress_lock:
                            account_progress[acc_id] = {
                                'phase': 'setup',
                                'setup_status': 'starting',
                                'start_time': time.time(),
                                'total_resources': 0,
                                'jobs_done': 0,
                                'total_jobs': 0,
                                'service_resources': {},
                                'service_jobs_done': {},
                                'service_total_jobs': {},
                                'last_service': '',
                                'last_region': '',
                            }
                        future = executor.submit(
                            self._discover_account,
                            acc_id,
                            account_info.get(acc_id, "Unknown"),
                            services,
                            regions,
                            role_name,
                            save_to_database,
                            progress_callback
                        )
                        future_to_account[future] = acc_id
                        live.update(build_progress_display())

                    # Process results as they complete
                    for future in as_completed(future_to_account):
                        account_id = future_to_account[future]

                        # Get elapsed time before removing from progress
                        with progress_lock:
                            start_time = account_progress.get(account_id, {}).get('start_time', time.time())
                            elapsed = time.time() - start_time
                            # Remove from in-progress
                            account_progress.pop(account_id, None)

                        try:
                            result = future.result()
                            account_results.append(result)

                            if result.success:
                                total_resources += result.resource_count
                                completed_accounts.append((
                                    account_id,
                                    account_info.get(account_id, account_id),
                                    True,
                                    result.resource_count,
                                    elapsed
                                ))
                            else:
                                error_summary[account_id] = result.error_message
                                completed_accounts.append((
                                    account_id,
                                    account_info.get(account_id, account_id),
                                    False,
                                    0,
                                    elapsed
                                ))

                        except Exception as e:
                            error_summary[account_id] = str(e)
                            account_results.append(
                                AccountDiscoveryResult(
                                    account_id=account_id,
                                    account_name=account_info.get(account_id, "Unknown"),
                                    success=False,
                                    resource_count=0,
                                    error_message=str(e)
                                )
                            )
                            completed_accounts.append((
                                account_id,
                                account_info.get(account_id, account_id),
                                False,
                                0,
                                elapsed
                            ))

                        # Update live display
                        live.update(build_progress_display())

        else:
            # No progress display
            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                futures = [
                    executor.submit(
                        self._discover_account,
                        acc_id,
                        account_info.get(acc_id, "Unknown"),
                        services,
                        regions,
                        role_name,
                        save_to_database
                    )
                    for acc_id in target_accounts
                ]

                for future in as_completed(futures):
                    try:
                        result = future.result()
                        account_results.append(result)
                        if result.success:
                            total_resources += result.resource_count
                        else:
                            error_summary[result.account_id] = result.error_message
                    except Exception as e:
                        logger.error(f"Discovery failed: {str(e)}")

        # Calculate summary
        successful = sum(1 for r in account_results if r.success)
        failed = sum(1 for r in account_results if not r.success)
        total_time = time.time() - start_time

        # Display summary
        self._display_summary(account_results, total_resources, total_time)

        return MultiAccountDiscoveryResult(
            total_accounts=len(target_accounts),
            successful_accounts=successful,
            failed_accounts=failed,
            skipped_accounts=0,
            total_resources=total_resources,
            total_time_seconds=total_time,
            account_results=account_results,
            enabled_accounts=target_accounts,
            error_summary=error_summary
        )

    def _discover_account(
        self,
        account_id: str,
        account_name: str,
        services: List[str],
        regions: Optional[List[str]],
        role_name: str,
        save_to_database: bool,
        progress_callback: Optional[callable] = None
    ) -> AccountDiscoveryResult:
        """Discover resources in a single account using the collection engine.

        Uses parallel collection with throttling and batch DB writes for
        improved performance over the previous sequential approach.

        Args:
            progress_callback: Optional callback(account_id, progress_data_dict)
                progress_data_dict is either:
                - A str-keyed dict with 'phase'='setup', 'status'=str
                - A dict from _AccountCollectionEngine with per-service detail
        """
        start_time = time.time()

        def report_progress(data):
            """Report progress to callback if available"""
            if progress_callback:
                try:
                    progress_callback(account_id, data)
                except:
                    pass  # Don't let callback errors break discovery

        try:
            # Get current account
            report_progress({'phase': 'setup', 'status': 'connecting'})
            current_identity = aws_auth.get_caller_identity()
            current_account = current_identity['Account']

            # Set up the session for the target account
            # IMPORTANT: Do NOT modify the global aws_auth.session - it's not thread-safe!
            session = None
            if account_id != current_account:
                try:
                    report_progress({'phase': 'setup', 'status': 'assuming role'})
                    role_arn = f"arn:aws:iam::{account_id}:role/{role_name}"
                    external_id = aws_auth.get_cross_account_external_id()
                    session = aws_auth.assume_role(
                        role_arn=role_arn,
                        external_id=external_id,
                        session_name=f"tag-manager-discovery-{account_id}"
                    )
                except Exception as e:
                    return AccountDiscoveryResult(
                        account_id=account_id,
                        account_name=account_name,
                        success=False,
                        resource_count=0,
                        error_message=f"Role assumption failed: {str(e)}",
                        discovery_time_seconds=time.time() - start_time
                    )
            else:
                session = aws_auth.session

            # Resolve regions if not provided
            if not regions:
                try:
                    ec2_client = session.client('ec2', region_name='us-east-1')
                    response = ec2_client.describe_regions()
                    regions = [r['RegionName'] for r in response['Regions']]
                except Exception:
                    regions = ['us-east-1', 'us-west-2', 'eu-west-1']

            # Use collection engine for parallel discovery with throttling
            from ..modules.collection.engine import _AccountCollectionEngine

            def _engine_progress(data):
                report_progress(data)

            engine = _AccountCollectionEngine(
                services=services,
                regions=regions,
                session=session,
                account_id=account_id,
                batch_size=100,
                progress_callback=_engine_progress,
            )

            resources, errors, _permission_details = engine.run()

            # Save to database if requested (engine already batched writes)
            # The _AccountCollectionEngine batcher handles DB writes internally,
            # but we also need to update AccountStatus
            if save_to_database and resources:
                self._update_account_status(account_id, len(resources))

            regions_scanned = list(set(regions))

            # Calculate service-level statistics for compact tree display
            service_stats, compliance_summary = self._calculate_service_stats(
                resources, services, regions_scanned
            )

            return AccountDiscoveryResult(
                account_id=account_id,
                account_name=account_name,
                success=True,
                resource_count=len(resources),
                discovered_resources=resources,
                discovery_time_seconds=time.time() - start_time,
                regions_scanned=regions_scanned,
                service_stats=service_stats,
                compliance_summary=compliance_summary
            )

        except Exception as e:
            logger.error(f"Failed to discover resources in account {account_id}: {str(e)}")
            return AccountDiscoveryResult(
                account_id=account_id,
                account_name=account_name,
                success=False,
                resource_count=0,
                error_message=str(e),
                discovery_time_seconds=time.time() - start_time
            )

    def _update_account_status(self, account_id: str, resource_count: int):
        """Update AccountStatus table after discovery."""
        try:
            upsert_by_filter(
                "core",
                "account-status",
                filters=[("account_id", account_id)],
                payload={
                    "account_id": account_id,
                    "account_name": account_id,
                    "status": "ACTIVE",
                    "enabled_for_discovery": True,
                    "enabled_for_tagging": True,
                    "last_discovery_at": datetime.now(timezone.utc).isoformat(),
                    "total_resources_discovered": resource_count,
                },
            )
        except Exception as e:
            logger.error(f"Failed to update account status for {account_id}: {e}")

    def _save_resources_to_database(self, resources: List[Dict], account_id: str, services: List[str]):
        """Save discovered resources through bluearch-core storage.

        Args:
            resources: List of discovered resources
            account_id: AWS account ID
            services: List of services that were discovered (e.g., ['ec2', 's3', 'lambda'])
        """
        resources_saved = 0
        try:
            self._update_account_status(account_id, len(resources))
            for resource_data in resources:
                resource_arn = resource_data.get("resource_arn", "")
                if not resource_arn:
                    logger.warning(f"Skipping resource without ARN: {resource_data}")
                    continue
                try:
                    payload = resource_payload(resource_data, default_account_id=account_id)
                    payload["lifecycle_state"] = "active"
                    upsert_by_filter(
                        "core",
                        "resources",
                        filters=[("resource_arn", payload["resource_arn"])],
                        payload=payload,
                    )
                    resources_saved += 1
                except Exception as e:
                    logger.error(f"Error saving resource {resource_arn}: {str(e)}")

            logger.info(f"Saved {resources_saved} resources for account {account_id}")

        except Exception as e:
            logger.error(f"Failed to save resources to database: {str(e)}")

    def _calculate_service_stats(
        self,
        resources: List[Dict],
        services: List[str],
        regions_scanned: List[str]
    ) -> tuple:
        """Calculate service-level statistics with compliance data for compact tree.

        Args:
            resources: List of discovered resources
            services: List of services that were discovered
            regions_scanned: List of regions that were scanned

        Returns:
            Tuple of (service_stats, compliance_summary)
        """
        from ..services.org_policy_provider import org_policy_provider

        # Get required tags for compliance checking
        required_tags, from_org_policy, _ = org_policy_provider.get_required_tags(show_warnings=False)

        # Initialize service stats
        service_stats = {}
        for service in services:
            service_stats[service] = {
                'total': 0,
                'compliant': 0,
                'noncompliant': 0,
                'by_region': {}
            }
            # Initialize region stats
            if service == 's3':
                service_stats[service]['by_region']['global'] = {'total': 0, 'compliant': 0, 'noncompliant': 0}
            else:
                for region in regions_scanned:
                    service_stats[service]['by_region'][region] = {'total': 0, 'compliant': 0, 'noncompliant': 0}

        # Compliance totals
        total_compliant = 0
        total_noncompliant = 0

        # Process each resource
        for resource in resources:
            # Get service name
            service_name = resource.get('service_name', '').lower()
            if service_name not in service_stats:
                continue

            # Get region (S3 is global)
            region = resource.get('region', 'global')
            if service_name == 's3':
                region = 'global'

            # Get tags
            res_tags = resource.get('tags', {}) or resource.get('current_tags', {}) or {}
            if isinstance(res_tags, str):
                try:
                    res_tags = json.loads(res_tags) if res_tags else {}
                except:
                    res_tags = {}

            # Check compliance
            is_compliant, _ = org_policy_provider.check_resource_compliance(
                res_tags, required_tags, from_org_policy
            )

            # Update stats
            service_stats[service_name]['total'] += 1
            if is_compliant:
                service_stats[service_name]['compliant'] += 1
                total_compliant += 1
            else:
                service_stats[service_name]['noncompliant'] += 1
                total_noncompliant += 1

            # Update region stats
            if region in service_stats[service_name]['by_region']:
                service_stats[service_name]['by_region'][region]['total'] += 1
                if is_compliant:
                    service_stats[service_name]['by_region'][region]['compliant'] += 1
                else:
                    service_stats[service_name]['by_region'][region]['noncompliant'] += 1

        compliance_summary = {
            'total_compliant': total_compliant,
            'total_noncompliant': total_noncompliant,
            'required_tags': required_tags,
            'from_org_policy': from_org_policy
        }

        return service_stats, compliance_summary

    def _display_summary(self, account_results: List[AccountDiscoveryResult], total_resources: int, total_time: float):
        """Display discovery summary with compact tree view"""
        console.print("\n[bold]Discovery Summary[/bold]\n")

        # Resource type labels
        resource_types = {
            'ec2': 'instances',
            's3': 'buckets',
            'lambda': 'functions',
            'rds': 'databases',
            'dynamodb': 'tables',
            'ecs': 'services',
            'elb': 'load balancers'
        }

        # Build compact tree for all accounts
        tree = Tree("[bold cyan]AWS Resource Discovery[/bold cyan]")

        # Sort results by success, then by resource count
        sorted_results = sorted(
            account_results,
            key=lambda x: (x.success, x.resource_count),
            reverse=True
        )

        # Track overall compliance
        overall_compliant = 0
        overall_noncompliant = 0
        required_tags = []
        from_org_policy = False

        for result in sorted_results:
            # Account node
            if result.success:
                account_text = Text(f"{result.account_id}/", style="bold white")
                account_text.append(f" ({result.account_name})", style="dim")
                account_text.append(f" [{result.resource_count} resources]", style="cyan")
            else:
                account_text = Text(f"{result.account_id}/", style="bold red")
                account_text.append(f" ({result.account_name})", style="dim")
                account_text.append(f" [FAILED]", style="red")

            account_node = tree.add(account_text)

            if not result.success:
                # Show error for failed accounts
                error_text = Text(result.error_message[:60] if result.error_message else "Unknown error", style="red dim")
                account_node.add(error_text)
                continue

            # Update overall compliance
            if result.compliance_summary:
                overall_compliant += result.compliance_summary.get('total_compliant', 0)
                overall_noncompliant += result.compliance_summary.get('total_noncompliant', 0)
                if not required_tags:
                    required_tags = result.compliance_summary.get('required_tags', [])
                    from_org_policy = result.compliance_summary.get('from_org_policy', False)

            # Build service nodes for this account
            if result.service_stats:
                for service, stats in result.service_stats.items():
                    total = stats.get('total', 0)
                    compliant = stats.get('compliant', 0)
                    noncompliant = stats.get('noncompliant', 0)
                    resource_type = resource_types.get(service, 'resources')

                    if total == 0:
                        # No resources - show collapsed dim
                        service_text = Text(f"{service}/", style="dim")
                        service_text.append(" [OK] ", style="green dim")
                        service_text.append(f"(no {resource_type})", style="dim")
                        account_node.add(service_text)
                    elif noncompliant == 0:
                        # All compliant - show collapsed green
                        service_text = Text(f"{service}/", style="bold green")
                        service_text.append(" [OK] ", style="green")
                        service_text.append(f"({total} {resource_type}, all compliant)", style="green")
                        account_node.add(service_text)
                    else:
                        # Has non-compliant - expand to show regions
                        service_text = Text(f"{service}/", style="bold yellow")
                        by_region = stats.get('by_region', {})
                        regions_with_resources = sum(1 for r, s in by_region.items() if s.get('total', 0) > 0)

                        if service == 's3':
                            service_text.append(f" ({total} {resource_type}, ", style="yellow")
                        else:
                            region_label = "region" if regions_with_resources == 1 else "regions"
                            service_text.append(f" ({total} {resource_type} in {regions_with_resources} {region_label}, ", style="yellow")
                        service_text.append(f"{noncompliant} non-compliant", style="red")
                        service_text.append(")", style="yellow")

                        service_node = account_node.add(service_text)

                        # Add regions with resources (sorted by non-compliant count)
                        region_items = [(r, s) for r, s in by_region.items() if s.get('total', 0) > 0]
                        region_items.sort(key=lambda x: (-x[1].get('noncompliant', 0), -x[1].get('total', 0)))

                        for region, region_stats in region_items:
                            region_text = Text(f"{region}/", style="dim")
                            region_text.append(f" {region_stats['total']} {resource_type}", style="white")
                            if region_stats.get('noncompliant', 0) > 0:
                                region_text.append(f", {region_stats['noncompliant']} non-compliant", style="red")
                            service_node.add(region_text)

                        # Show collapsed empty regions count
                        empty_regions = len(by_region) - len(region_items)
                        if empty_regions > 0:
                            collapsed_text = Text(f"[{empty_regions} regions with no {resource_type}]", style="dim italic")
                            service_node.add(collapsed_text)

        console.print(tree)
        console.print()

        # Summary statistics
        successful = sum(1 for r in account_results if r.success)
        failed = sum(1 for r in account_results if not r.success)
        total_scanned = overall_compliant + overall_noncompliant

        # Build summary panel
        summary_lines = [
            f"[bold]Total Accounts:[/bold] {len(account_results)}",
            f"[green]Successful:[/green] {successful}",
            f"[red]Failed:[/red] {failed}",
            f"[bold]Total Resources:[/bold] {total_resources}",
            f"[bold]Total Time:[/bold] {total_time:.1f} seconds"
        ]

        # Add compliance info if available
        if total_scanned > 0:
            compliance_rate = (overall_compliant / total_scanned * 100) if total_scanned > 0 else 0
            policy_source = "AWS Organizations policy" if from_org_policy else "default tags"
            summary_lines.extend([
                "",
                f"[cyan]Required Tags:[/cyan] {', '.join(required_tags)}",
                f"[dim]Source:[/dim] {policy_source}",
                f"[green]Compliant:[/green] {overall_compliant} ({compliance_rate:.1f}%)",
                f"[red]Non-compliant:[/red] {overall_noncompliant} ({100 - compliance_rate:.1f}%)"
            ])

        summary_panel = Panel.fit(
            '\n'.join(summary_lines),
            title="[bold cyan]Results[/bold cyan]"
        )
        console.print(summary_panel)

    def get_discovery_status(self) -> Dict:
        """Get current discovery status and statistics"""
        enabled_accounts = self.get_enabled_accounts()

        # Get last discovery results from database
        try:
            resources = list_all_records("core", "resources")
            stats_dict: dict[str, int] = {}
            for resource in resources:
                account_id = resource.get("account_id")
                if account_id:
                    stats_dict[account_id] = stats_dict.get(account_id, 0) + 1

            return {
                'enabled_accounts': enabled_accounts,
                'total_enabled': len(enabled_accounts),
                'discovered_accounts': len(stats_dict),
                'resource_counts': stats_dict,
                'total_resources': sum(stats_dict.values())
            }

        except Exception as e:
            logger.error(f"Failed to get discovery status: {str(e)}")
            return {
                'enabled_accounts': enabled_accounts,
                'total_enabled': len(enabled_accounts),
                'discovered_accounts': 0,
                'resource_counts': {},
                'total_resources': 0
            }


# Singleton instance
multi_account_discovery = MultiAccountDiscovery()
