"""Multi-account management endpoints proxied to bluearch-core."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from ...licensing.gate import check_feature
from ...utils.event_hooks import track_event
from ...utils.core_client import request_core
from ..dependencies import get_current_user, require_role, LocalUser
from ..schemas.accounts import AccountValidationResponse, AccountsListResponse, DeployRequest, StackSetStatusResponse
from ..schemas.jobs import JobSubmittedResponse

router = APIRouter(prefix="/api/v1/accounts", tags=["accounts"])


def _payload(model):
    return model.model_dump() if hasattr(model, "model_dump") else model.dict()


def _core_get(path: str, timeout: float = 10.0):
    return request_core("GET", path, timeout=timeout)


def _core_post(path: str, payload: dict | None = None, timeout: float = 10.0):
    return request_core("POST", path, service_token=True, json=payload or {}, timeout=timeout)


def _submitted(row: dict, job_type: str, message: str) -> JobSubmittedResponse:
    return JobSubmittedResponse(
        job_id=row.get("id") or row.get("job_id") or "",
        job_type=row.get("job_type") or job_type,
        status=row.get("status") or "pending",
        message=row.get("message") or message,
    )


@router.get("/validate", response_model=AccountValidationResponse)
async def validate_account(_user: LocalUser = Depends(get_current_user)):
    """Validate whether the active AWS identity can deploy multi-account infrastructure."""
    check_feature("cross_account")
    try:
        return _core_get("/api/v1/accounts/validate", timeout=15.0)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"bluearch-core account validation unavailable: {exc}") from exc


@router.get("/status", response_model=StackSetStatusResponse)
async def stackset_status(_user: LocalUser = Depends(get_current_user)):
    """Get StackSet status from bluearch-core."""
    check_feature("cross_account")
    try:
        return _core_get("/api/v1/accounts/status", timeout=15.0)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"bluearch-core account status unavailable: {exc}") from exc


@router.get("", response_model=AccountsListResponse)
async def list_accounts(current_user: LocalUser = Depends(get_current_user)):
    """List core-tracked AWS accounts."""
    try:
        rows = _core_get("/api/v1/accounts")
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"bluearch-core accounts unavailable: {exc}") from exc
    try:
        track_event("web.accounts.list", properties={"user_sub": getattr(current_user, "sub", None), "count": len(rows), "source": "bluearch-core"})
    except Exception:
        pass
    return {"accounts": rows, "total": len(rows)}


@router.post("/deploy", response_model=JobSubmittedResponse)
async def deploy_stackset(
    body: DeployRequest,
    _user: LocalUser = Depends(require_role(["admin", "operator"])),
):
    """Deploy cross-account infrastructure through bluearch-core."""
    check_feature("cross_account")
    try:
        return _submitted(_core_post("/api/v1/accounts/deploy", _payload(body), timeout=20.0), "multi_account_deploy", "Multi-account deployment started")
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"bluearch-core account deploy unavailable: {exc}") from exc


@router.post("/update", response_model=JobSubmittedResponse)
async def update_stackset(_user: LocalUser = Depends(require_role(["admin", "operator"]))):
    """Update cross-account infrastructure through bluearch-core."""
    check_feature("cross_account")
    try:
        return _submitted(_core_post("/api/v1/accounts/update", timeout=20.0), "multi_account_update", "Multi-account update started")
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"bluearch-core account update unavailable: {exc}") from exc


@router.post("/remove", response_model=JobSubmittedResponse)
async def remove_stackset(_user: LocalUser = Depends(require_role(["admin", "operator"]))):
    """Remove cross-account infrastructure through bluearch-core."""
    check_feature("cross_account")
    try:
        return _submitted(_core_post("/api/v1/accounts/remove", timeout=20.0), "multi_account_remove", "Multi-account removal started")
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"bluearch-core account removal unavailable: {exc}") from exc
