"""Health check and automation manager for Tag Manager CLI."""

import os
import subprocess
import logging
from datetime import datetime, timedelta, timezone
from typing import Dict, Any, Optional, List
from dataclasses import dataclass

from ..utils.core_client import request_core
from ..utils.display_utils import print_safe, print_error

logger = logging.getLogger(__name__)


@dataclass
class HealthCheckResult:
    """Result of a health check operation."""
    service_name: str
    is_healthy: bool
    status_message: str
    details: Dict[str, Any]
    action_taken: Optional[str] = None


class HealthManager:
    """Manages health checks and automated system maintenance."""

    def __init__(self):
        self.discovery_task_name = "worker_discovery_all"

    def check_worker_discovery_staleness(self) -> HealthCheckResult:
        """Check if worker discovery is stale and needs to run."""
        try:
            last_execution = _get_last_system_execution(self.discovery_task_name)
            is_stale = _is_system_execution_stale(last_execution, hours=24)

            if is_stale:
                message = "Worker discovery is stale (last run >24h ago or never run)"
                last_run = "never" if not last_execution else _format_datetime(last_execution.get("last_execution_at"))
            else:
                message = "Worker discovery is up to date"
                last_run = _format_datetime(last_execution.get("last_execution_at"))

            return HealthCheckResult(
                service_name="worker_discovery",
                is_healthy=not is_stale,
                status_message=message,
                details={
                    "is_stale": is_stale,
                    "last_execution": last_run,
                    "threshold_hours": 24
                }
            )

        except Exception as e:
            logger.error(f"Error checking worker discovery staleness: {e}")
            return HealthCheckResult(
                service_name="worker_discovery",
                is_healthy=False,
                status_message=f"Failed to check staleness: {str(e)}",
                details={"error": str(e)}
            )

    def run_worker_discovery(self) -> bool:
        """Run worker discovery task and record execution."""
        try:
            import sys
            from datetime import datetime

            start_time = datetime.now(timezone.utc)

            # Build command to run worker discovery
            cmd = [
                sys.executable, "-m", "tag_manager_cli.main",
                "workers", "discover", "all"
            ]

            logger.info("Running worker discovery for all services...")

            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=300  # 5 minute timeout
            )

            end_time = datetime.now(timezone.utc)
            duration_ms = int((end_time - start_time).total_seconds() * 1000)

            _create_system_execution(
                {
                    "task_name": self.discovery_task_name,
                    "task_type": "discovery",
                    "last_execution_at": end_time.isoformat(),
                    "execution_status": "success" if result.returncode == 0 else "failed",
                    "execution_duration_ms": duration_ms,
                    "execution_details": {
                        "stdout": result.stdout,
                        "stderr": result.stderr,
                        "returncode": result.returncode
                    },
                    "error_message": result.stderr if result.returncode != 0 else None,
                    "triggered_by": "auto",
                    "execution_context": {"auto_health_check": True}
                }
            )

            if result.returncode == 0:
                logger.info(f"Worker discovery completed successfully in {duration_ms}ms")
                return True
            else:
                logger.error(f"Worker discovery failed: {result.stderr}")
                return False

        except subprocess.TimeoutExpired:
            logger.error("Worker discovery timed out after 5 minutes")
            return False
        except Exception as e:
            logger.error(f"Error running worker discovery: {e}")
            return False

    def ensure_worker_discovery_current(self) -> HealthCheckResult:
        """Ensure worker discovery is current, run if stale."""
        staleness_result = self.check_worker_discovery_staleness()

        if not staleness_result.is_healthy:
            logger.info("Worker discovery is stale, running now...")

            if self.run_worker_discovery():
                # Check again after running
                new_result = self.check_worker_discovery_staleness()
                new_result.action_taken = "ran_discovery"
                logger.info("Successfully ran worker discovery")
                return new_result
            else:
                staleness_result.action_taken = "discovery_failed"
                logger.error("Failed to run worker discovery")

        return staleness_result

    def record_health_check_execution(self) -> None:
        """Record that a health check was performed."""
        try:
            _create_system_execution(
                {
                    "task_name": "worker_health_check",
                    "task_type": "health_check",
                    "last_execution_at": datetime.now(timezone.utc).isoformat(),
                    "execution_status": "success",
                    "triggered_by": "auto",
                    "execution_context": {"routine_health_check": True}
                }
            )
        except Exception as e:
            logger.error(f"Failed to record health check execution: {e}")

    def perform_comprehensive_health_check(self, auto_fix: bool = True) -> List[HealthCheckResult]:
        """Perform comprehensive health check of all systems."""
        results = []

        logger.info("Starting comprehensive health check...")

        # Check worker discovery staleness
        if auto_fix:
            discovery_result = self.ensure_worker_discovery_current()
        else:
            discovery_result = self.check_worker_discovery_staleness()
        results.append(discovery_result)

        # Record this health check
        self.record_health_check_execution()

        logger.info(f"Health check completed. Results: {len([r for r in results if r.is_healthy])}/{len(results)} healthy")

        return results

    def get_health_summary(self) -> Dict[str, Any]:
        """Get a summary of system health status."""
        try:
            worker_discovery = _get_last_system_execution(self.discovery_task_name)
            active_workers = _count_active_workers()

            return {
                "worker_discovery": {
                    "last_run": _format_datetime(worker_discovery.get("last_execution_at")) if worker_discovery else None,
                    "is_stale": _is_system_execution_stale(worker_discovery, 24),
                    "status": worker_discovery.get("execution_status") if worker_discovery else "never_run"
                },
                "active_workers": active_workers,
                "summary_generated_at": datetime.now(timezone.utc).isoformat()
            }

        except Exception as e:
            logger.error(f"Error generating health summary: {e}")
            return {"error": str(e), "summary_generated_at": datetime.now(timezone.utc).isoformat()}


SYSTEM_EXECUTION_FIELDS = {
    "id",
    "task_name",
    "task_type",
    "last_execution_at",
    "execution_status",
    "execution_duration_ms",
    "execution_details",
    "error_message",
    "resources_processed",
    "triggered_by",
    "execution_context",
}


def _storage_path(collection: str, record_key: str | None = None) -> str:
    path = f"/api/v1/storage/tag-manager/{collection}"
    if record_key:
        path = f"{path}/{record_key}"
    return path


def _payload_from_record(record: Dict[str, Any]) -> Dict[str, Any]:
    payload = dict((record or {}).get("payload", record) or {})
    payload.setdefault("id", (record or {}).get("id") or (record or {}).get("record_key") or payload.get("id"))
    return payload


def _list_storage_payloads(
    collection: str,
    *,
    limit: int = 1000,
    filters: list[tuple[str, str]] | None = None,
    order_by: str | None = None,
    descending: bool = True,
) -> List[Dict[str, Any]]:
    params: list[tuple[str, str | int]] = [("limit", limit), ("descending", str(descending).lower())]
    if order_by:
        params.append(("order_by", order_by))
    for key, value in filters or []:
        params.append(("filter", f"{key}={value}"))
    records = request_core(
        "GET",
        _storage_path(collection),
        service_token=True,
        params=params,
        timeout=10.0,
    )
    return [_payload_from_record(record) for record in records or []]


def _create_system_execution(payload: Dict[str, Any]) -> Dict[str, Any]:
    record = request_core(
        "POST",
        _storage_path("system-executions"),
        service_token=True,
        json={"payload": {key: value for key, value in payload.items() if key in SYSTEM_EXECUTION_FIELDS}},
        timeout=10.0,
    )
    return _payload_from_record(record)


def _get_last_system_execution(task_name: str) -> Optional[Dict[str, Any]]:
    rows = _list_storage_payloads(
        "system-executions",
        limit=1,
        filters=[("task_name", task_name)],
        order_by="last_execution_at",
        descending=True,
    )
    return rows[0] if rows else None


def _is_system_execution_stale(execution: Optional[Dict[str, Any]], hours: int = 24) -> bool:
    if not execution:
        return True
    last_execution_at = _parse_datetime(execution.get("last_execution_at"))
    if not last_execution_at:
        return True
    threshold = datetime.now(timezone.utc) - timedelta(hours=hours)
    return last_execution_at < threshold


def _count_active_workers() -> int:
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=5)
    count = 0
    for worker in _list_storage_payloads("worker-status", limit=10000):
        if worker.get("status") not in {"active", "busy", "idle"}:
            continue
        heartbeat = _parse_datetime(worker.get("last_heartbeat"))
        if heartbeat and heartbeat > cutoff:
            count += 1
    return count


def _parse_datetime(value) -> Optional[datetime]:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str) and value:
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    else:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _format_datetime(value) -> Optional[str]:
    parsed = _parse_datetime(value)
    return parsed.isoformat() if parsed else None


# Global health manager instance
health_manager = HealthManager()


def run_automated_health_checks() -> List[HealthCheckResult]:
    """Run automated health checks - called from main command execution."""
    return health_manager.perform_comprehensive_health_check(auto_fix=True)


def check_and_run_discovery_if_stale() -> bool:
    """Quick check and run discovery if stale."""
    result = health_manager.ensure_worker_discovery_current()
    return result.is_healthy
