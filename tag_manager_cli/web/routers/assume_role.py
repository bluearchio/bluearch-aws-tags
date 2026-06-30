"""Assume-role management endpoints proxied to bluearch-core."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from ...utils.event_hooks import track_event
from ...utils.core_client import request_core
from ..dependencies import get_current_user, require_role, LocalUser
from ..schemas.assume_role import (
    AssumeRoleDeployRequest,
    AssumeRoleDisableRequest,
    AssumeRoleStatusResponse,
)
from ..schemas.jobs import JobSubmittedResponse

router = APIRouter(prefix="/api/v1/assume-role", tags=["assume-role"])


def _payload(model):
    return model.model_dump() if hasattr(model, "model_dump") else model.dict()


def _submitted(row: dict, job_type: str, message: str) -> JobSubmittedResponse:
    return JobSubmittedResponse(
        job_id=row.get("id") or row.get("job_id") or "",
        job_type=row.get("job_type") or job_type,
        status=row.get("status") or "pending",
        message=row.get("message") or message,
    )


@router.get("/status", response_model=AssumeRoleStatusResponse)
async def assume_role_status(_user: LocalUser = Depends(get_current_user)):
    """Get current assume-role configuration and CloudFormation stack status."""
    try:
        return request_core("GET", "/api/v1/assume-role/status", timeout=10.0)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"bluearch-core assume-role status unavailable: {exc}") from exc


@router.get("/configs")
async def list_configs(current_user: LocalUser = Depends(get_current_user)):
    """List assume-role configurations from bluearch-core."""
    try:
        result = request_core("GET", "/api/v1/assume-role/configs", timeout=10.0)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"bluearch-core assume-role configs unavailable: {exc}") from exc
    try:
        track_event("web.assume_role.list", properties={"user_sub": getattr(current_user, "sub", None), "count": len(result), "source": "bluearch-core"})
    except Exception:
        pass
    return result


@router.post("/deploy", response_model=JobSubmittedResponse)
async def deploy_assume_role(
    body: AssumeRoleDeployRequest,
    _user: LocalUser = Depends(require_role(["admin", "operator"])),
):
    """Deploy assume-role CloudFormation through bluearch-core."""
    try:
        row = request_core("POST", "/api/v1/assume-role/deploy", service_token=True, json=_payload(body), timeout=20.0)
        return _submitted(row, "assume_role_deploy", "Assume-role deployment started")
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"bluearch-core assume-role deploy unavailable: {exc}") from exc


@router.post("/disable", response_model=JobSubmittedResponse)
async def disable_assume_role(
    body: AssumeRoleDisableRequest,
    _user: LocalUser = Depends(require_role(["admin", "operator"])),
):
    """Disable assume-role configuration through bluearch-core."""
    try:
        row = request_core("POST", "/api/v1/assume-role/disable", service_token=True, json=_payload(body), timeout=20.0)
        return _submitted(row, "assume_role_delete_stack" if body.delete_stack else "assume_role_disable", "Assume-role disable started")
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"bluearch-core assume-role disable unavailable: {exc}") from exc
