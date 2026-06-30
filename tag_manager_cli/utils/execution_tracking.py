"""Execution tracking utilities for tag operations."""

from datetime import datetime
from typing import Dict, Any, Optional, List, Union
from contextlib import contextmanager
from types import SimpleNamespace

from .core_client import request_core


EXECUTION_FIELDS = {
    "id",
    "execution_type",
    "description",
    "initiated_by",
    "initiated_via",
    "started_at",
    "completed_at",
    "status",
    "total_resources",
    "successful_operations",
    "failed_operations",
    "rollback_enabled",
    "rollback_window_hours",
    "parent_execution_id",
    "rolled_back_at",
    "rolled_back_by",
    "metadata_json",
}

AUDIT_LOG_FIELDS = {
    "id",
    "resource_arn",
    "resource_id",
    "execution_id",
    "operation",
    "rule_id",
    "is_rollback",
    "old_tags",
    "new_tags",
    "principal_info",
    "cloudtrail_event_id",
    "success",
    "error_message",
    "executed_at",
}


class ExecutionTracker:
    """Context manager for tracking tag operation executions."""
    
    def __init__(
        self,
        execution_type: str,
        description: str,
        initiated_by: str,
        initiated_via: str = 'cli',
        rollback_enabled: bool = True,
        rollback_window_hours: int = 24,
        metadata: Optional[Dict[str, Any]] = None
    ):
        self.execution_type = execution_type
        self.description = description
        self.initiated_by = initiated_by
        self.initiated_via = initiated_via
        self.rollback_enabled = rollback_enabled
        self.rollback_window_hours = rollback_window_hours
        self.metadata = metadata or {}
        self.execution = None
        self._success_count = 0
        self._failure_count = 0
        self._total_count = 0
    
    def __enter__(self):
        """Create execution record on entry."""
        payload = {
            "execution_type": self.execution_type,
            "description": self.description,
            "initiated_by": self.initiated_by,
            "initiated_via": self.initiated_via,
            "status": "in_progress",
            "rollback_enabled": self.rollback_enabled,
            "rollback_window_hours": self.rollback_window_hours,
            "metadata_json": self.metadata,
        }
        self.execution = _namespace_from_payload(
            _core_create_payload("tagging-executions", payload)
        )

        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Update execution status on exit."""
        if self.execution:
            self.execution.completed_at = datetime.utcnow()
            self.execution.total_resources = self._total_count
            self.execution.successful_operations = self._success_count
            self.execution.failed_operations = self._failure_count
            
            if exc_type is not None:
                # Exception occurred
                self.execution.status = 'failed'
                self.execution.metadata_json['error'] = str(exc_val)
            elif self._failure_count == 0 and self._success_count > 0:
                self.execution.status = 'completed'
            elif self._success_count > 0:
                self.execution.status = 'partially_completed'
            else:
                self.execution.status = 'failed'

            _core_update_payload(
                "tagging-executions",
                str(self.execution.id),
                _execution_to_payload(self.execution),
            )
    
    def track_operation(
        self,
        resource_arn: str,
        operation: str,
        old_tags: Optional[Dict[str, str]] = None,
        new_tags: Optional[Dict[str, str]] = None,
        success: bool = True,
        error_message: Optional[str] = None,
        rule_id: Optional[Union[str, int]] = None,
        principal_info: Optional[Dict[str, Any]] = None,
        cloudtrail_event_id: Optional[str] = None
    ) -> SimpleNamespace:
        """Track a single tag operation."""
        self._total_count += 1
        
        if success:
            self._success_count += 1
        else:
            self._failure_count += 1
        
        # Handle rule_id conversion
        parsed_rule_id = None
        if rule_id and str(rule_id) != 'None':
            try:
                if isinstance(rule_id, str):
                    import uuid
                    parsed_rule_id = uuid.UUID(rule_id)
                else:
                    parsed_rule_id = rule_id
            except (ValueError, TypeError):
                parsed_rule_id = None

        payload = {
            "resource_arn": resource_arn,
            "execution_id": self.execution.id if self.execution else None,
            "operation": operation,
            "rule_id": str(parsed_rule_id) if parsed_rule_id else None,
            "old_tags": old_tags,
            "new_tags": new_tags,
            "principal_info": principal_info,
            "cloudtrail_event_id": cloudtrail_event_id,
            "success": success,
            "error_message": error_message,
            "is_rollback": False,
        }

        return _namespace_from_payload(_core_create_payload("tagging-audit-log", payload))
    
    def update_metadata(self, key: str, value: Any):
        """Update execution metadata."""
        if self.execution and self.execution.metadata_json:
            self.execution.metadata_json[key] = value
    
    def get_execution_id(self) -> Optional[int]:
        """Get the current execution ID."""
        return self.execution.id if self.execution else None


@contextmanager
def track_execution(
    execution_type: str,
    description: str,
    initiated_by: str,
    **kwargs
):
    """Convenience context manager for execution tracking."""
    tracker = ExecutionTracker(
        execution_type=execution_type,
        description=description,
        initiated_by=initiated_by,
        **kwargs
    )
    
    with tracker:
        yield tracker


def create_manual_execution(
    description: str,
    initiated_by: str,
    metadata: Optional[Dict[str, Any]] = None
) -> ExecutionTracker:
    """Create an execution tracker for manual operations."""
    return ExecutionTracker(
        execution_type='manual',
        description=description,
        initiated_by=initiated_by,
        initiated_via='cli',
        metadata=metadata
    )


def create_automated_execution(
    description: str,
    initiated_by: str = 'system',
    metadata: Optional[Dict[str, Any]] = None
) -> ExecutionTracker:
    """Create an execution tracker for automated operations."""
    return ExecutionTracker(
        execution_type='automated',
        description=description,
        initiated_by=initiated_by,
        initiated_via='scheduled',
        metadata=metadata
    )


def create_bulk_execution(
    description: str,
    initiated_by: str,
    resource_count: int,
    metadata: Optional[Dict[str, Any]] = None
) -> ExecutionTracker:
    """Create an execution tracker for bulk operations."""
    metadata = metadata or {}
    metadata['resource_count'] = resource_count
    
    return ExecutionTracker(
        execution_type='bulk',
        description=description,
        initiated_by=initiated_by,
        initiated_via='cli',
        metadata=metadata
    )


def get_execution_history(
    limit: int = 10,
    execution_type: Optional[str] = None,
    status: Optional[str] = None,
    initiated_by: Optional[str] = None,
    include_rollbacks: bool = False
) -> List[Dict[str, Any]]:
    """Get execution history with filters."""
    filters = []
    if execution_type:
        filters.append(("execution_type", execution_type))
    if status:
        filters.append(("status", status))
    if initiated_by:
        filters.append(("initiated_by", initiated_by))

    fetch_limit = limit if include_rollbacks else 10000
    executions = _core_list_payloads(
        "tagging-executions",
        limit=fetch_limit,
        filters=filters,
        order_by="started_at",
        descending=True,
    )
    if not include_rollbacks:
        executions = [item for item in executions if item.get("execution_type") != "rollback"]
    return [_execution_to_dict(item) for item in executions[:limit]]


def get_execution_details(execution_id: Union[str, int]) -> Optional[Dict[str, Any]]:
    """Get detailed information about an execution."""
    execution = _core_get_payload("tagging-executions", str(execution_id))
    if not execution:
        return None

    audit_logs = _core_list_payloads(
        "tagging-audit-log",
        limit=10000,
        filters=[("execution_id", str(execution_id))],
        order_by="executed_at",
        descending=False,
    )

    result = _execution_to_dict(execution)
    result["audit_logs"] = [_audit_log_to_dict(log) for log in audit_logs]

    # Group by resource for easier viewing
    resources_affected = {}
    for log in audit_logs:
        arn = log.get("resource_arn")
        if arn not in resources_affected:
            resources_affected[arn] = {
                "resource_arn": arn,
                "operations": [],
            }
        resources_affected[arn]["operations"].append(
            {
                "operation": log.get("operation"),
                "success": log.get("success"),
                "old_tags": log.get("old_tags"),
                "new_tags": log.get("new_tags"),
                "error_message": log.get("error_message"),
                "executed_at": _format_datetime(log.get("executed_at")),
            }
        )

    result["resources_affected"] = list(resources_affected.values())

    return result


def _core_storage_path(collection: str, record_key: str | None = None) -> str:
    path = f"/api/v1/storage/tag-manager/{collection}"
    if record_key:
        path = f"{path}/{record_key}"
    return path


def _core_list_payloads(
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
        _core_storage_path(collection),
        service_token=True,
        params=params,
        timeout=10.0,
    )
    return [_payload_from_record(record) for record in records or []]


def _core_get_payload(collection: str, record_key: str) -> Optional[Dict[str, Any]]:
    try:
        record = request_core(
            "GET",
            _core_storage_path(collection, record_key),
            service_token=True,
            timeout=10.0,
        )
    except Exception as exc:
        if "404" in str(exc):
            return None
        raise
    return _payload_from_record(record)


def _core_create_payload(collection: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    record = request_core(
        "POST",
        _core_storage_path(collection),
        service_token=True,
        json={"payload": _coerce_payload(collection, payload)},
        timeout=10.0,
    )
    return _payload_from_record(record)


def _core_update_payload(collection: str, record_key: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    record = request_core(
        "PUT",
        _core_storage_path(collection, record_key),
        service_token=True,
        json={"payload": _coerce_payload(collection, payload)},
        timeout=10.0,
    )
    return _payload_from_record(record)


def _payload_from_record(record: Dict[str, Any]) -> Dict[str, Any]:
    payload = dict((record or {}).get("payload", record) or {})
    payload.setdefault("id", (record or {}).get("id") or (record or {}).get("record_key") or payload.get("id"))
    return payload


def _coerce_payload(collection: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    fields = EXECUTION_FIELDS if collection == "tagging-executions" else AUDIT_LOG_FIELDS
    return {key: value for key, value in payload.items() if key in fields}


def _namespace_from_payload(payload: Dict[str, Any]) -> SimpleNamespace:
    return SimpleNamespace(**dict(payload or {}))


def _execution_to_payload(execution: SimpleNamespace) -> Dict[str, Any]:
    return {
        key: getattr(execution, key)
        for key in EXECUTION_FIELDS
        if hasattr(execution, key)
    }


def _execution_to_dict(payload: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "id": payload.get("id"),
        "execution_type": payload.get("execution_type"),
        "description": payload.get("description"),
        "initiated_by": payload.get("initiated_by"),
        "initiated_via": payload.get("initiated_via"),
        "started_at": _format_datetime(payload.get("started_at")),
        "completed_at": _format_datetime(payload.get("completed_at")),
        "status": payload.get("status"),
        "total_resources": payload.get("total_resources") or 0,
        "successful_operations": payload.get("successful_operations") or 0,
        "failed_operations": payload.get("failed_operations") or 0,
        "rollback_enabled": payload.get("rollback_enabled", True),
        "rollback_window_hours": payload.get("rollback_window_hours") or 24,
        "parent_execution_id": payload.get("parent_execution_id"),
        "rolled_back_at": _format_datetime(payload.get("rolled_back_at")),
        "rolled_back_by": payload.get("rolled_back_by"),
        "metadata": payload.get("metadata_json") or payload.get("metadata"),
    }


def _audit_log_to_dict(payload: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "id": payload.get("id"),
        "resource_arn": payload.get("resource_arn"),
        "resource_id": payload.get("resource_id"),
        "execution_id": payload.get("execution_id"),
        "operation": payload.get("operation"),
        "rule_id": payload.get("rule_id"),
        "is_rollback": payload.get("is_rollback"),
        "old_tags": payload.get("old_tags"),
        "new_tags": payload.get("new_tags"),
        "principal_info": payload.get("principal_info"),
        "cloudtrail_event_id": payload.get("cloudtrail_event_id"),
        "success": payload.get("success"),
        "error_message": payload.get("error_message"),
        "executed_at": _format_datetime(payload.get("executed_at")),
    }


def _format_datetime(value) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)
