"""Event tracking endpoints proxied to bluearch-core."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from ...licensing.gate import check_feature
from ...utils.event_hooks import track_event
from ...utils.core_client import request_core
from ..dependencies import get_current_user, require_role, LocalUser
from ..schemas.event_tracking import (
    EventTrackingDeployRequest,
    EventTrackingPollRequest,
    EventTrackingRemoveRequest,
    EventTrackingStatusResponse,
    EventTrackingSyncAction,
)
from ..schemas.jobs import JobSubmittedResponse

router = APIRouter(prefix="/api/v1/event-tracking", tags=["event-tracking"])


def _payload(model):
    return model.model_dump() if hasattr(model, "model_dump") else model.dict()


def _core_post(path: str, payload: dict | None = None):
    return request_core("POST", path, service_token=True, json=payload or {}, timeout=30.0)


def _submitted(row: dict, job_type: str, message: str) -> JobSubmittedResponse:
    return JobSubmittedResponse(
        job_id=row.get("id") or row.get("job_id") or "",
        job_type=row.get("job_type") or job_type,
        status=row.get("status") or "pending",
        message=row.get("message") or message,
    )


@router.get("/status", response_model=EventTrackingStatusResponse)
async def get_event_tracking_status(current_user: LocalUser = Depends(get_current_user)):
    """Get event tracking status from bluearch-core."""
    check_feature("event_tracking")
    try:
        result = request_core("GET", "/api/v1/event-tracking/status", timeout=10.0)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"bluearch-core event tracking unavailable: {exc}") from exc
    try:
        track_event(
            "web.event_tracking.status",
            properties={
                "user_sub": getattr(current_user, "sub", None),
                "instances": len(result.get("instances", [])),
                "source": "bluearch-core",
            },
        )
    except Exception:
        pass
    return result


@router.post("/deploy", response_model=JobSubmittedResponse)
async def deploy_event_tracking(
    body: EventTrackingDeployRequest,
    _user: LocalUser = Depends(require_role(["admin", "operator"])),
):
    """Deploy or sync event tracking through bluearch-core."""
    check_feature("event_tracking")
    try:
        return _submitted(_core_post("/api/v1/event-tracking/deploy", _payload(body)), "event_tracking_deploy", "Event tracking deployment started")
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"bluearch-core event tracking deploy unavailable: {exc}") from exc


@router.post("/remove", response_model=JobSubmittedResponse)
async def remove_event_tracking(
    body: EventTrackingRemoveRequest,
    _user: LocalUser = Depends(require_role(["admin", "operator"])),
):
    """Remove selected event tracking targets through bluearch-core."""
    check_feature("event_tracking")
    try:
        return _submitted(_core_post("/api/v1/event-tracking/remove", _payload(body)), "event_tracking_remove", "Event tracking removal started")
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"bluearch-core event tracking remove unavailable: {exc}") from exc


@router.post("/remove-all", response_model=JobSubmittedResponse)
async def remove_all_event_tracking(_user: LocalUser = Depends(require_role(["admin", "operator"]))):
    """Remove all event tracking targets through bluearch-core."""
    check_feature("event_tracking")
    try:
        return _submitted(_core_post("/api/v1/event-tracking/remove-all"), "event_tracking_remove_all", "Event tracking removal started")
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"bluearch-core event tracking remove unavailable: {exc}") from exc


@router.post("/service")
async def service_action(
    body: EventTrackingSyncAction,
    _user: LocalUser = Depends(require_role(["admin", "operator"])),
):
    """Control the core event tracking service."""
    check_feature("event_tracking")
    try:
        return _core_post("/api/v1/event-tracking/service", _payload(body))
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"bluearch-core event tracking service unavailable: {exc}") from exc


@router.post("/poll")
async def poll_event_tracking(
    body: EventTrackingPollRequest,
    _user: LocalUser = Depends(require_role(["admin", "operator"])),
):
    """Poll event queues through bluearch-core."""
    check_feature("event_tracking")
    try:
        return _core_post("/api/v1/event-tracking/poll", _payload(body))
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"bluearch-core event tracking poll unavailable: {exc}") from exc
