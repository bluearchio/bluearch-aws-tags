"""Batch DB writer for collection engine.

Buffers discovered resources and flushes them to SQLite in bulk
transactions, reducing per-resource overhead from 2 transactions
(SELECT + INSERT/UPDATE + COMMIT) to 1 transaction per batch.
"""

import json
import logging
from datetime import datetime, timezone
from threading import Lock
from typing import Dict, List, Any

from ...utils.core_client import request_core

logger = logging.getLogger(__name__)


class BatchDBWriter:
    """Writes resource batches in single transactions."""

    def bulk_upsert(self, resources: List[Dict[str, Any]]) -> int:
        """Upsert a batch of resources in one transaction.

        Returns:
            Number of resources successfully written.
        """
        if not resources:
            return 0

        written = 0
        now = datetime.now(timezone.utc)
        for resource_data in resources:
            arn = resource_data.get('resource_arn')
            if not arn:
                continue

            try:
                _sync_ttl_from_aws_tags(resource_data)
                payload = _resource_payload(resource_data, now)
                existing = _get_resource_by_arn(arn)
                if existing:
                    _update_core_record("core", "resources", existing, payload)
                else:
                    _create_core_record("core", "resources", payload)
                written += 1
            except Exception as e:
                logger.warning("Failed to upsert resource %s through core: %s", arn, e)

        return written


class ResourceBatcher:
    """Thread-safe buffer that auto-flushes to DB at batch_size."""

    def __init__(self, batch_size: int = 100):
        self._buffer: List[Dict[str, Any]] = []
        self._lock = Lock()
        self._writer = BatchDBWriter()
        self._batch_size = batch_size
        self.total_written = 0

    def add_batch(self, resources: List[Dict[str, Any]]):
        """Add resources to buffer, auto-flushing when full."""
        with self._lock:
            self._buffer.extend(resources)
            while len(self._buffer) >= self._batch_size:
                batch = self._buffer[:self._batch_size]
                self._buffer = self._buffer[self._batch_size:]
                count = self._writer.bulk_upsert(batch)
                self.total_written += count

    def flush(self):
        """Flush remaining buffered resources."""
        with self._lock:
            if self._buffer:
                count = self._writer.bulk_upsert(self._buffer)
                self.total_written += count
                self._buffer = []


class RelationshipBatchDBWriter:
    """Writes relationship batches in single transactions."""

    def bulk_upsert(self, relationships: List[Dict[str, Any]]) -> int:
        """Upsert a batch of relationships in one transaction.

        Uses pre-fetch + update/insert pattern for idempotent upserts
        on the (source_arn, target_arn, relationship_type) unique constraint.

        Returns:
            Number of relationships successfully written.
        """
        if not relationships:
            return 0

        written = 0
        now = datetime.now(timezone.utc)
        for rel_data in relationships:
            source_arn = rel_data.get('source_arn')
            target_arn = rel_data.get('target_arn')
            rel_type = rel_data.get('relationship_type')
            if not source_arn or not target_arn or not rel_type:
                continue

            try:
                payload = {
                    "source_arn": source_arn,
                    "target_arn": target_arn,
                    "relationship_type": rel_type,
                    "source_type": rel_data.get('source_type', ''),
                    "target_type": rel_data.get('target_type', ''),
                    "region": rel_data.get('region', ''),
                    "account_id": rel_data.get('account_id', ''),
                    "metadata_json": rel_data.get('metadata'),
                    "last_seen_at": now.isoformat(),
                }
                existing = _get_relationship(source_arn, target_arn, rel_type)
                if existing:
                    _update_core_record("core", "resource-relationships", existing, payload)
                else:
                    payload["discovered_at"] = now.isoformat()
                    _create_core_record("core", "resource-relationships", payload)
                written += 1
            except Exception as e:
                logger.warning("Failed to upsert relationship %s -> %s through core: %s", source_arn, target_arn, e)

        return written


class RelationshipBatcher:
    """Thread-safe buffer that auto-flushes relationships to DB at batch_size."""

    def __init__(self, batch_size: int = 200):
        self._buffer: List[Dict[str, Any]] = []
        self._lock = Lock()
        self._writer = RelationshipBatchDBWriter()
        self._batch_size = batch_size
        self.total_written = 0

    def add_batch(self, relationships: List[Dict[str, Any]]):
        """Add relationships to buffer, auto-flushing when full."""
        with self._lock:
            self._buffer.extend(relationships)
            while len(self._buffer) >= self._batch_size:
                batch = self._buffer[:self._batch_size]
                self._buffer = self._buffer[self._batch_size:]
                count = self._writer.bulk_upsert(batch)
                self.total_written += count

    def flush(self):
        """Flush remaining buffered relationships."""
        with self._lock:
            if self._buffer:
                count = self._writer.bulk_upsert(self._buffer)
                self.total_written += count
                self._buffer = []


def _resource_payload(resource_data: Dict[str, Any], now: datetime) -> Dict[str, Any]:
    tags = resource_data.get('current_tags', {})
    if isinstance(tags, str):
        try:
            tags = json.loads(tags)
        except (json.JSONDecodeError, TypeError):
            tags = {}
    metadata = resource_data.get('metadata_json', resource_data.get('metadata', {}))
    if isinstance(metadata, str):
        try:
            metadata = json.loads(metadata)
        except (json.JSONDecodeError, TypeError):
            metadata = {}
    return {
        "resource_arn": resource_data.get('resource_arn'),
        "resource_type": resource_data.get('resource_type', ''),
        "service_name": resource_data.get('service_name', ''),
        "region": resource_data.get('region', 'global'),
        "account_id": resource_data.get('account_id', ''),
        "resource_id": resource_data.get('resource_id', ''),
        "created_at": _format_datetime(resource_data.get('created_at')),
        "current_tags": tags,
        "metadata_json": metadata,
        "last_scanned_at": now.isoformat(),
        "lifecycle_state": resource_data.get('lifecycle_state', 'active'),
        "expires_at": _format_datetime(resource_data.get('expires_at')),
        "policy_source": resource_data.get('policy_source'),
    }


def _core_storage_path(namespace: str, collection: str, record_key: str | None = None) -> str:
    path = f"/api/v1/storage/{namespace}/{collection}"
    if record_key:
        path = f"{path}/{record_key}"
    return path


def _payload_from_record(record: Dict[str, Any]) -> Dict[str, Any]:
    payload = dict((record or {}).get("payload", record) or {})
    payload.setdefault("id", (record or {}).get("id") or (record or {}).get("record_key") or payload.get("id"))
    payload.setdefault("record_key", (record or {}).get("record_key") or payload.get("id"))
    return payload


def _list_core_records(
    namespace: str,
    collection: str,
    *,
    filters: list[tuple[str, str]] | None = None,
    limit: int = 1000,
) -> List[Dict[str, Any]]:
    params: list[tuple[str, str | int]] = [("limit", limit)]
    for key, value in filters or []:
        params.append(("filter", f"{key}={value}"))
    records = request_core(
        "GET",
        _core_storage_path(namespace, collection),
        service_token=True,
        params=params,
        timeout=10.0,
    )
    return [_payload_from_record(record) for record in records or []]


def _create_core_record(namespace: str, collection: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    record = request_core(
        "POST",
        _core_storage_path(namespace, collection),
        service_token=True,
        json={"payload": _drop_none(payload)},
        timeout=10.0,
    )
    return _payload_from_record(record)


def _update_core_record(namespace: str, collection: str, record: Dict[str, Any], payload: Dict[str, Any]) -> Dict[str, Any]:
    record_key = record.get("record_key") or record.get("id")
    if not record_key:
        raise RuntimeError(f"Cannot update {collection} without a record key")
    response = request_core(
        "PUT",
        _core_storage_path(namespace, collection, str(record_key)),
        service_token=True,
        json={"payload": _drop_none({**record, **payload})},
        timeout=10.0,
    )
    return _payload_from_record(response)


def _get_resource_by_arn(resource_arn: str) -> Dict[str, Any] | None:
    records = _list_core_records("core", "resources", filters=[("resource_arn", resource_arn)], limit=1)
    return records[0] if records else None


def _get_relationship(source_arn: str, target_arn: str, relationship_type: str) -> Dict[str, Any] | None:
    records = _list_core_records(
        "core",
        "resource-relationships",
        filters=[("source_arn", source_arn), ("target_arn", target_arn), ("relationship_type", relationship_type)],
        limit=1,
    )
    return records[0] if records else None


def _format_datetime(value: Any) -> str | None:
    if not value:
        return None
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return value
    else:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.isoformat()


def _drop_none(payload: Dict[str, Any]) -> Dict[str, Any]:
    return {key: value for key, value in payload.items() if value is not None}


def _sync_ttl_from_aws_tags(resource_data: Dict[str, Any]):
    """Sync TTL/expires_at from AWS tags if present.

    Checks for bluearch:ttl tag and sets expires_at accordingly.
    """
    tags = resource_data.get('current_tags', {})
    if isinstance(tags, str):
        try:
            tags = json.loads(tags)
        except (json.JSONDecodeError, TypeError):
            tags = {}

    ttl_tag = tags.get('bluearch:ttl')
    policy_source_tag = tags.get('bluearch:policy-source')

    if ttl_tag:
        try:
            expires_at = datetime.strptime(ttl_tag, '%Y-%m-%d').replace(tzinfo=timezone.utc)
            resource_data['expires_at'] = expires_at

            if policy_source_tag:
                resource_data['policy_source'] = policy_source_tag

            now = datetime.now(timezone.utc)
            if expires_at <= now:
                resource_data['lifecycle_state'] = 'expired'
            else:
                resource_data['lifecycle_state'] = 'active'
        except (ValueError, TypeError):
            pass
