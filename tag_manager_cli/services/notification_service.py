"""Shared notification delivery and de-duplication."""

from dataclasses import dataclass
from typing import Any, Dict, Optional

from ..utils.core_client import CoreRuntimeError, request_core


@dataclass
class NotificationResult:
    sent: bool
    status: str
    event_id: Optional[str] = None
    error: Optional[str] = None


class NotificationService:
    """Record Tag Manager notifications for the local dashboard."""

    def record_once(
        self,
        *,
        source: str,
        event_key: str,
        severity: str,
        title: str,
        message: str,
        payload: Optional[Dict[str, Any]] = None,
        force: bool = False,
    ) -> NotificationResult:
        """Record a dashboard notification once per source/event_key."""
        existing = _find_event(source=source, event_key=event_key)
        if not existing:
            existing = _find_event(source=source, title=title)

        record = {
            "source": source,
            "event_key": event_key,
            "severity": severity,
            "title": title,
            "message": message,
            "payload": payload or {},
            "notification_sent": False,
            "notification_error": None,
            "sent_at": None,
        }

        if existing:
            event_id = existing.get("id")
            request_core(
                "PUT",
                f"/api/v1/storage/core/notification-events/{event_id}",
                service_token=True,
                json={"payload": record},
            )
            return NotificationResult(sent=False, status="recorded", event_id=event_id)

        try:
            created = request_core(
                "POST",
                "/api/v1/storage/core/notification-events",
                service_token=True,
                json={"payload": record},
            )
        except CoreRuntimeError:
            try:
                duplicate = _find_event(source=source, event_key=event_key)
            except CoreRuntimeError:
                duplicate = None
            return NotificationResult(
                sent=False,
                status="duplicate" if duplicate else "error",
                event_id=duplicate.get("id") if duplicate else None,
                error=None if duplicate else "bluearch-core notification storage unavailable",
            )
        return NotificationResult(sent=False, status="recorded", event_id=created.get("id"))


def _find_event(*, source: str, event_key: str | None = None, title: str | None = None) -> dict[str, Any] | None:
    filters = [("source", source)]
    if event_key is not None:
        filters.append(("event_key", event_key))
    if title is not None:
        filters.append(("title", title))
    params = [("limit", 1), ("order_by", "created_at"), ("descending", "true")]
    params.extend(("filter", f"{field}={value}") for field, value in filters)
    rows = request_core(
        "GET",
        "/api/v1/storage/core/notification-events",
        service_token=True,
        params=params,
    )
    if not rows:
        return None
    record = rows[0]
    payload = record.get("payload") if isinstance(record, dict) else None
    if isinstance(payload, dict):
        payload.setdefault("id", record.get("id"))
        return payload
    return record if isinstance(record, dict) else None
