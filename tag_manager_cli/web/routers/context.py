"""Account context and permission status endpoints."""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Response

from ..dependencies import get_current_user, LocalUser
from ..schemas.context import (
    AccountContextResponse,
    AccountContextListResponse,
    AddContextRequest,
    SwitchContextRequest,
    ContextGateResponse,
    PermissionStatusResponse,
)
from ...utils.core_client import request_core

router = APIRouter(prefix="/api/v1/system", tags=["context"])


# ---------------------------------------------------------------------------
# Context CRUD
# ---------------------------------------------------------------------------


@router.get("/context", response_model=AccountContextResponse)
async def get_current_context(
    _user: LocalUser = Depends(get_current_user),
):
    """Return the current active account context."""
    try:
        return request_core("GET", "/api/v1/system/context", timeout=5.0)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"bluearch-core context unavailable: {exc}") from exc


@router.get("/contexts", response_model=AccountContextListResponse)
async def list_contexts(
    current_user: LocalUser = Depends(get_current_user),
):
    """Return all registered account contexts."""
    try:
        return request_core("GET", "/api/v1/system/contexts", timeout=5.0)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"bluearch-core contexts unavailable: {exc}") from exc


@router.post("/context", response_model=AccountContextResponse)
async def add_context(
    body: Optional[AddContextRequest] = None,
    _user: LocalUser = Depends(get_current_user),
):
    """Register the current AWS session as a new account context.

    Calls STS GetCallerIdentity to determine account_id and user_arn,
    then persists the context.  If this is the first context being added
    it is automatically set as current.
    """
    try:
        return request_core(
            "POST",
            "/api/v1/system/context",
            service_token=True,
            json=_model_dump(body) if body else {},
            timeout=10.0,
        )
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"bluearch-core context registration unavailable: {exc}") from exc


@router.post("/context/switch", response_model=AccountContextResponse)
async def switch_context(
    body: SwitchContextRequest,
    _user: LocalUser = Depends(get_current_user),
):
    """Switch the active account context to a different registered account."""
    try:
        return request_core(
            "POST",
            "/api/v1/system/context/switch",
            service_token=True,
            json=_model_dump(body),
            timeout=5.0,
        )
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"bluearch-core context switch unavailable: {exc}") from exc


@router.delete("/context/{account_id}", status_code=204)
async def remove_context(
    account_id: str,
    _user: LocalUser = Depends(get_current_user),
):
    """Remove a registered account context."""
    try:
        request_core(
            "DELETE",
            f"/api/v1/system/context/{account_id}",
            service_token=True,
            timeout=5.0,
        )
        return Response(status_code=204)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"bluearch-core context removal unavailable: {exc}") from exc


# ---------------------------------------------------------------------------
# Startup gate
# ---------------------------------------------------------------------------


@router.get("/context/gate", response_model=ContextGateResponse)
async def context_gate(
    _user: LocalUser = Depends(get_current_user),
):
    """Startup gate check: ensure a valid account context exists.

    Calls STS GetCallerIdentity and then runs the ensure_context logic
    to auto-register on first run or detect mismatches.
    """
    try:
        return request_core("GET", "/api/v1/system/context/gate", timeout=10.0)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"bluearch-core context gate unavailable: {exc}") from exc


# ---------------------------------------------------------------------------
# Permissions
# ---------------------------------------------------------------------------


@router.get("/permissions", response_model=PermissionStatusResponse)
async def get_permissions(
    _user: LocalUser = Depends(get_current_user),
):
    """Return cached permission status for the current account context."""
    try:
        return request_core("GET", "/api/v1/system/permissions", timeout=5.0)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"bluearch-core permissions unavailable: {exc}") from exc


def _model_dump(model) -> dict:
    if hasattr(model, "model_dump"):
        return model.model_dump()
    return model.dict()


@router.post("/permissions/refresh", response_model=PermissionStatusResponse)
async def refresh_permissions(
    _user: LocalUser = Depends(get_current_user),
):
    """Force re-validate IAM permissions for the current account context."""
    try:
        return request_core(
            "POST",
            "/api/v1/system/permissions/refresh",
            service_token=True,
            timeout=10.0,
        )
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"bluearch-core permissions refresh unavailable: {exc}") from exc
