"""Collection engine orchestrator.

Wires together the scheduler, throttled executor, collectors, batcher
and progress reporter into a single run() call for single-account
discovery and run_multi_account() for cross-account discovery.
"""

import logging
import time
from concurrent.futures import as_completed, ThreadPoolExecutor
from typing import Any, Dict, List, Optional

from rich.console import Console
from rich.live import Live

from ...utils.aws_auth import aws_auth
from ...utils.core_client import request_core
from ...services.org_policy_provider import org_policy_provider

from .models import CollectionJob, CollectionResult, CollectorResult
from .scheduler import JobScheduler
from .executor import ThrottledExecutor
from .collectors import COLLECTORS
from .batcher import ResourceBatcher, RelationshipBatcher
from .progress import ProgressReporter, MultiAccountProgressReporter

logger = logging.getLogger(__name__)


def _permission_detail_with_account(detail: Dict[str, Any], account_id: str) -> Dict[str, Any]:
    enriched = dict(detail)
    enriched["account_id"] = enriched.get("account_id") or account_id
    return enriched


def _permission_resource_types(details: List[Dict[str, Any]]) -> List[str]:
    resource_types = set()
    for detail in details:
        for resource_type in detail.get("resource_types") or []:
            resource_types.add(str(resource_type))
    return sorted(resource_types)


class CollectionEngine:
    """Orchestrates resource collection for single or multi-account."""

    def __init__(
        self,
        services: List[str],
        regions: List[str],
        console: Console,
        account_id: Optional[str] = None,
        session: Any = None,
        required_tags: Optional[List[str]] = None,
        max_workers: int = 10,
        max_per_region: int = 3,
        batch_size: int = 100,
    ):
        self.services = services
        self.regions = regions
        self.console = console
        self.account_id = account_id
        self.session = session
        self.required_tags = required_tags
        self.max_workers = max_workers
        self.max_per_region = max_per_region
        self.batch_size = batch_size

    # ------------------------------------------------------------------
    # Single-account pipeline
    # ------------------------------------------------------------------

    def run(self) -> CollectionResult:
        """Run single-account collection pipeline."""
        start = time.time()

        # 1. Resolve account ID
        if not self.account_id:
            try:
                sts = aws_auth.get_client('sts')
                self.account_id = sts.get_caller_identity()['Account']
            except Exception:
                self.account_id = 'unknown'

        # 2. Clear existing resources
        deleted = _clear_all_resources_single_account()
        if deleted > 0:
            self.console.print(f"[yellow]Cleared {deleted} existing resources from database[/yellow]\n")

        # 3. Fetch required tags for compliance
        from_org_policy = False
        policy_warning = None
        if self.required_tags is None:
            self.required_tags, from_org_policy, policy_warning = org_policy_provider.get_required_tags(
                show_warnings=True
            )

        if from_org_policy:
            self.console.print("[green]Checking compliance against AWS Organizations policy[/green]")
            self.console.print(f"[dim]Required tags: {', '.join(self.required_tags)}[/dim]\n")
        elif policy_warning:
            self.console.print(policy_warning)
            self.console.print()

        # 4. Build jobs
        scheduler = JobScheduler()
        jobs = scheduler.build_jobs(self.services, self.regions, self.account_id, self.session)

        # 5. Set up components
        batcher = ResourceBatcher(batch_size=self.batch_size)
        rel_batcher = RelationshipBatcher()
        reporter = ProgressReporter(
            console=self.console,
            total_jobs=len(jobs),
            services=self.services,
            regions=self.regions,
        )
        executor = ThrottledExecutor(
            max_workers=self.max_workers,
            max_per_region=self.max_per_region,
        )

        all_errors: List[str] = []
        total_permission_errors = 0
        total_permission_error_details: List[Dict[str, Any]] = []
        by_service: Dict[str, int] = {}
        by_region: Dict[str, int] = {}

        # Compliance tracking
        compliance_summary = {
            'total_compliant': 0,
            'total_noncompliant': 0,
            'by_service': {},
            'required_tags': self.required_tags,
            'from_org_policy': from_org_policy,
        }

        # 6. Submit & process with Live display
        try:
            with Live(reporter.build_display(), console=self.console, refresh_per_second=4, transient=True) as live:
                futures = {}
                for job in jobs:
                    collector = COLLECTORS.get(job.service)
                    if not collector:
                        continue
                    reporter.job_started(job.service, job.region)
                    future = executor.submit(job, collector.collect)
                    futures[future] = job

                for future in as_completed(futures):
                    job = futures[future]
                    try:
                        collector_result: CollectorResult = future.result()

                        # Feed to batcher
                        if collector_result.resources:
                            batcher.add_batch(collector_result.resources)
                        if collector_result.relationships:
                            rel_batcher.add_batch(collector_result.relationships)

                        resource_count = len(collector_result.resources)
                        error_count = len(collector_result.errors)
                        all_errors.extend(collector_result.errors)
                        total_permission_errors += collector_result.permission_errors
                        total_permission_error_details.extend([
                            _permission_detail_with_account(
                                detail,
                                job.account_id or self.account_id or "unknown",
                            )
                            for detail in collector_result.permission_error_details
                        ])

                        # Track by service/region
                        by_service[job.service] = by_service.get(job.service, 0) + resource_count
                        if job.region:
                            by_region[job.region] = by_region.get(job.region, 0) + resource_count

                        # Compliance check
                        self._update_compliance(
                            collector_result.resources, job.service, job.region,
                            compliance_summary, from_org_policy,
                        )

                        reporter.job_completed(job.service, job.region, resource_count, error_count)

                    except Exception as e:
                        error_msg = f"Error discovering {job.service}"
                        if job.region:
                            error_msg += f" in {job.region}"
                        error_msg += f": {e}"
                        all_errors.append(error_msg)
                        reporter.job_failed(job.service, job.region, error_msg)

                    live.update(reporter.build_display())
        finally:
            executor.shutdown()

        # 7. Flush remaining
        batcher.flush()
        rel_batcher.flush()

        duration = time.time() - start

        # 8. Build compact tree
        discovery_results = self._build_discovery_results(by_service, by_region, compliance_summary)
        from ..discovery import _build_compact_tree, _display_compliance_summary
        _build_compact_tree(
            self.console, self.account_id, self.services, self.regions,
            discovery_results, compliance_summary,
        )
        _display_compliance_summary(self.console, compliance_summary)
        _notify_deprecated_cloudformation_templates(self.console, self.session)

        # 9. Return result
        return CollectionResult(
            total_resources=batcher.total_written,
            total_errors=len(all_errors),
            permission_errors=total_permission_errors,
            duration_seconds=duration,
            services_scanned=len(self.services),
            regions_scanned=len(self.regions),
            by_service=by_service,
            by_region=by_region,
            errors=all_errors,
            permission_error_details=total_permission_error_details,
            permission_error_resource_types=_permission_resource_types(total_permission_error_details),
            compliance=compliance_summary,
        )

    # ------------------------------------------------------------------
    # Multi-account pipeline
    # ------------------------------------------------------------------

    def run_multi_account(
        self,
        target_accounts: List[str],
        account_info: Dict[str, str],
        role_name: str,
    ) -> Dict[str, Any]:
        """Multi-account collection pipeline.

        Returns a dict compatible with MultiAccountDiscoveryResult.
        """
        from ..multi_account_discovery import AccountDiscoveryResult, MultiAccountDiscoveryResult

        start = time.time()

        # Clear all resources
        _clear_all_resources_single_account()

        ma_reporter = MultiAccountProgressReporter(
            console=self.console,
            total_accounts=len(target_accounts),
            account_info=account_info,
        )

        account_results: List[AccountDiscoveryResult] = []
        error_summary: Dict[str, str] = {}
        total_resources = 0

        def _discover_one_account(acc_id: str) -> AccountDiscoveryResult:
            """Discover resources for a single account using CollectionEngine."""
            acc_start = time.time()
            ma_reporter.account_started(acc_id)

            try:
                current_account = aws_auth.get_current_account_id()
            except Exception:
                current_account = None

            acc_session = None
            if acc_id != current_account:
                try:
                    role_arn = f"arn:aws:iam::{acc_id}:role/{role_name}"
                    external_id = aws_auth.get_cross_account_external_id()
                    acc_session = aws_auth.assume_role(
                        role_arn=role_arn,
                        external_id=external_id,
                        session_name=f"tag-manager-discovery-{acc_id}",
                    )
                except Exception as e:
                    ma_reporter.account_completed(acc_id, False, 0)
                    return AccountDiscoveryResult(
                        account_id=acc_id,
                        account_name=account_info.get(acc_id, 'Unknown'),
                        success=False,
                        resource_count=0,
                        error_message=f"Role assumption failed: {e}",
                        discovery_time_seconds=time.time() - acc_start,
                    )
            else:
                acc_session = aws_auth.session

            # Run collection for this account (without clearing DB or showing tree)
            engine = _AccountCollectionEngine(
                services=self.services,
                regions=self.regions,
                session=acc_session,
                account_id=acc_id,
                batch_size=self.batch_size,
                progress_callback=lambda data: ma_reporter.account_progress(
                    acc_id,
                    data.get('service', ''),
                    'running',
                    data.get('total_resources', 0),
                ),
            )
            resources, errors, _permission_details = engine.run()

            ma_reporter.account_completed(acc_id, True, len(resources))

            return AccountDiscoveryResult(
                account_id=acc_id,
                account_name=account_info.get(acc_id, 'Unknown'),
                success=True,
                resource_count=len(resources),
                discovered_resources=resources,
                discovery_time_seconds=time.time() - acc_start,
                regions_scanned=self.regions,
            )

        with Live(ma_reporter.build_display(), console=self.console, refresh_per_second=4) as live:
            with ThreadPoolExecutor(max_workers=5) as pool:
                future_to_acc = {
                    pool.submit(_discover_one_account, acc_id): acc_id
                    for acc_id in target_accounts
                }

                for future in as_completed(future_to_acc):
                    acc_id = future_to_acc[future]
                    try:
                        result = future.result()
                        account_results.append(result)
                        if result.success:
                            total_resources += result.resource_count
                        else:
                            error_summary[acc_id] = result.error_message or 'Unknown error'
                    except Exception as e:
                        error_summary[acc_id] = str(e)
                        account_results.append(AccountDiscoveryResult(
                            account_id=acc_id,
                            account_name=account_info.get(acc_id, 'Unknown'),
                            success=False,
                            resource_count=0,
                            error_message=str(e),
                        ))

                    live.update(ma_reporter.build_display())

        successful = sum(1 for r in account_results if r.success)
        failed = sum(1 for r in account_results if not r.success)
        total_time = time.time() - start
        _notify_deprecated_cloudformation_templates(self.console, self.session)

        return MultiAccountDiscoveryResult(
            total_accounts=len(target_accounts),
            successful_accounts=successful,
            failed_accounts=failed,
            skipped_accounts=0,
            total_resources=total_resources,
            total_time_seconds=total_time,
            account_results=account_results,
            enabled_accounts=target_accounts,
            error_summary=error_summary,
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _update_compliance(
        self,
        resources: List[Dict],
        service: str,
        region: Optional[str],
        compliance_summary: Dict,
        from_org_policy: bool,
    ):
        """Update compliance_summary from collected resources."""
        required_tags = compliance_summary.get('required_tags', [])
        if not required_tags:
            return

        compliant = 0
        noncompliant = 0

        for res in resources:
            res_tags = res.get('current_tags', {}) or {}
            if isinstance(res_tags, str):
                try:
                    import json
                    res_tags = json.loads(res_tags) if res_tags else {}
                except Exception:
                    res_tags = {}
            is_compliant, _ = org_policy_provider.check_resource_compliance(
                res_tags, required_tags, from_org_policy,
            )
            if is_compliant:
                compliant += 1
            else:
                noncompliant += 1

        compliance_summary['total_compliant'] += compliant
        compliance_summary['total_noncompliant'] += noncompliant

        if service not in compliance_summary['by_service']:
            compliance_summary['by_service'][service] = {
                'compliant': 0, 'noncompliant': 0, 'total': 0, 'regions_with_resources': 0,
            }
        svc = compliance_summary['by_service'][service]
        svc['compliant'] += compliant
        svc['noncompliant'] += noncompliant
        svc['total'] += len(resources)
        if len(resources) > 0:
            svc['regions_with_resources'] += 1

    def _build_discovery_results(
        self,
        by_service: Dict[str, int],
        by_region: Dict[str, int],
        compliance_summary: Dict,
    ) -> Dict:
        """Build discovery_results dict for _build_compact_tree."""
        results = {}
        # For services with compliance data, build per-(service, region) entries
        for service, svc_stats in compliance_summary.get('by_service', {}).items():
            if service == 's3':
                results[(service, None)] = {
                    'count': svc_stats.get('total', 0),
                    'compliant': svc_stats.get('compliant', 0),
                    'noncompliant': svc_stats.get('noncompliant', 0),
                }
            else:
                # Distribute count across regions (we track totals per service)
                total = svc_stats.get('total', 0)
                regions_with = svc_stats.get('regions_with_resources', 0)
                if regions_with > 0:
                    # Set the total on the first region that has data
                    # The tree only uses service-level aggregation anyway
                    first = True
                    for region in self.regions:
                        if first:
                            results[(service, region)] = {
                                'count': total,
                                'compliant': svc_stats.get('compliant', 0),
                                'noncompliant': svc_stats.get('noncompliant', 0),
                            }
                            first = False
                        else:
                            results[(service, region)] = {'count': 0, 'compliant': 0, 'noncompliant': 0}
        return results


def _notify_deprecated_cloudformation_templates(console: Console, session: Any) -> None:
    """Record a best-effort warning when deployed Tag Manager templates are stale."""
    try:
        from ...services.cloudformation_template_notifications import (
            notify_deprecated_cloudformation_templates,
        )

        result = notify_deprecated_cloudformation_templates(session=session)
        if result.status in {"recorded", "duplicate"}:
            console.print("[yellow]CloudFormation template update warning recorded[/yellow]")
        elif result.status not in {"no_findings", "skipped_local_version"}:
            logger.debug("CloudFormation template notification status: %s (%s)", result.status, result.error)
    except Exception as exc:
        logger.debug("CloudFormation template notification check failed: %s", exc)


class _AccountCollectionEngine:
    """Lightweight engine for a single account in multi-account mode.

    Does not clear DB or display trees -- just collects and batches.
    """

    def __init__(
        self,
        services: List[str],
        regions: List[str],
        session: Any,
        account_id: str,
        batch_size: int = 100,
        progress_callback=None,
    ):
        self.services = services
        self.regions = regions
        self.session = session
        self.account_id = account_id
        self.batch_size = batch_size
        self._progress_callback = progress_callback

    def run(self):
        """Returns (all_resources, all_errors, permission_error_details)."""
        scheduler = JobScheduler()
        jobs = scheduler.build_jobs(self.services, self.regions, self.account_id, self.session)

        batcher = ResourceBatcher(batch_size=self.batch_size)
        rel_batcher = RelationshipBatcher()
        executor = ThrottledExecutor(max_workers=10, max_per_region=3)
        all_resources: List[Dict] = []
        all_errors: List[str] = []
        permission_error_details: List[Dict[str, Any]] = []
        permission_errors_count = 0

        jobs_done = 0
        # Track per-service: resource count and regions completed
        service_resources: Dict[str, int] = {}
        service_regions_done: Dict[str, set] = {s: set() for s in self.services}
        # Count total jobs per service for progress
        service_total_jobs: Dict[str, int] = {}
        service_jobs_done: Dict[str, int] = {s: 0 for s in self.services}
        for j in jobs:
            service_total_jobs[j.service] = service_total_jobs.get(j.service, 0) + 1

        try:
            futures = {}
            for job in jobs:
                collector = COLLECTORS.get(job.service)
                if not collector:
                    continue
                future = executor.submit(job, collector.collect)
                futures[future] = job

            for future in as_completed(futures):
                job = futures[future]
                try:
                    result: CollectorResult = future.result()
                    if result.resources:
                        batcher.add_batch(result.resources)
                        all_resources.extend(result.resources)
                    if result.relationships:
                        rel_batcher.add_batch(result.relationships)
                    all_errors.extend(result.errors)
                    permission_errors_count += result.permission_errors
                    permission_error_details.extend([
                        _permission_detail_with_account(detail, self.account_id)
                        for detail in result.permission_error_details
                    ])

                    jobs_done += 1
                    svc = job.service
                    rgn = job.region or 'global'
                    resource_count = len(result.resources)
                    service_resources[svc] = service_resources.get(svc, 0) + resource_count
                    service_regions_done[svc].add(rgn)
                    service_jobs_done[svc] = service_jobs_done.get(svc, 0) + 1

                    if self._progress_callback:
                        self._progress_callback({
                            'service': svc,
                            'region': rgn,
                            'jobs_done': jobs_done,
                            'total_jobs': len(jobs),
                            'total_resources': len(all_resources),
                            'service_resources': dict(service_resources),
                            'service_jobs_done': dict(service_jobs_done),
                            'service_total_jobs': dict(service_total_jobs),
                            'permission_errors_count': permission_errors_count,
                            'permission_error_details': permission_error_details[-10:],
                            'permission_error_resource_types': _permission_resource_types(permission_error_details),
                        })
                except Exception as e:
                    all_errors.append(f"Error in {job.service}/{job.region}: {e}")
        finally:
            executor.shutdown()

        batcher.flush()
        rel_batcher.flush()
        return all_resources, all_errors, permission_error_details


def _clear_all_resources_single_account() -> int:
    """Clear all resources from database before discovery."""
    try:
        _nullify_all_resource_references()
        deleted = _delete_storage_collection("core", "resources")
        _delete_storage_collection("core", "resource-relationships")
        logger.info(f"Cleared {deleted} resources from core before discovery")
        return deleted
    except Exception as e:
        logger.error(f"Failed to clear resources: {e}")
        return 0


def _clear_resources_for_account(account_id: str) -> int:
    """Clear resources for a specific account before re-scanning."""
    try:
        resources = _list_storage_records("core", "resources", filters=[("account_id", account_id)])
        resource_ids = {str(resource.get("id") or resource.get("record_key")) for resource in resources}
        if resource_ids:
            _nullify_resource_references(resource_ids)
        deleted = _delete_records(resources, "core", "resources")
        relationships = _list_storage_records("core", "resource-relationships", filters=[("account_id", account_id)])
        _delete_records(relationships, "core", "resource-relationships")
        logger.info(f"Cleared {deleted} resources for account {account_id}")
        return deleted
    except Exception as e:
        logger.error(f"Failed to clear resources for account {account_id}: {e}")
        return 0


REFERENCE_COLLECTIONS = (
    ("tag-manager", "lifecycle-audit-log"),
    ("tag-manager", "tagging-audit-log"),
    ("tag-manager", "lifecycle-notifications"),
    ("tag-manager", "lifecycle-decisions"),
)


def _storage_path(namespace: str, collection: str, record_key: str | None = None) -> str:
    path = f"/api/v1/storage/{namespace}/{collection}"
    if record_key:
        path = f"{path}/{record_key}"
    return path


def _payload_from_record(record: Dict[str, Any]) -> Dict[str, Any]:
    payload = dict((record or {}).get("payload", record) or {})
    payload.setdefault("id", (record or {}).get("id") or (record or {}).get("record_key") or payload.get("id"))
    payload.setdefault("record_key", (record or {}).get("record_key") or payload.get("id"))
    return payload


def _list_storage_records(
    namespace: str,
    collection: str,
    *,
    filters: list[tuple[str, str]] | None = None,
) -> List[Dict[str, Any]]:
    limit = 10000
    offset = 0
    results: List[Dict[str, Any]] = []
    while True:
        params: list[tuple[str, str | int]] = [("limit", limit), ("offset", offset)]
        for key, value in filters or []:
            params.append(("filter", f"{key}={value}"))
        records = request_core(
            "GET",
            _storage_path(namespace, collection),
            service_token=True,
            params=params,
            timeout=20.0,
        )
        batch = [_payload_from_record(record) for record in records or []]
        results.extend(batch)
        if len(batch) < limit:
            break
        offset += limit
    return results


def _delete_storage_collection(namespace: str, collection: str) -> int:
    return _delete_records(_list_storage_records(namespace, collection), namespace, collection)


def _delete_records(records: List[Dict[str, Any]], namespace: str, collection: str) -> int:
    deleted = 0
    for record in records:
        record_key = record.get("record_key") or record.get("id")
        if not record_key:
            continue
        request_core(
            "DELETE",
            _storage_path(namespace, collection, str(record_key)),
            service_token=True,
            timeout=10.0,
        )
        deleted += 1
    return deleted


def _update_record(namespace: str, collection: str, record: Dict[str, Any], payload: Dict[str, Any]) -> None:
    record_key = record.get("record_key") or record.get("id")
    if not record_key:
        return
    request_core(
        "PUT",
        _storage_path(namespace, collection, str(record_key)),
        service_token=True,
        json={"payload": {**record, **payload}},
        timeout=10.0,
    )


def _nullify_all_resource_references() -> None:
    for namespace, collection in REFERENCE_COLLECTIONS:
        for record in _list_storage_records(namespace, collection):
            if record.get("resource_id"):
                _update_record(namespace, collection, record, {"resource_id": None})


def _nullify_resource_references(resource_ids: set[str]) -> None:
    for namespace, collection in REFERENCE_COLLECTIONS:
        for record in _list_storage_records(namespace, collection):
            if str(record.get("resource_id")) in resource_ids:
                _update_record(namespace, collection, record, {"resource_id": None})
