"""Infrastructure endpoints proxied to bluearch-core."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request

from ..dependencies import get_current_user, require_role, LocalUser
from ..rate_limit import limiter
from ..schemas.infrastructure import InfrastructureStatusResponse, ResourceGroupInfo
from ..schemas.jobs import JobSubmittedResponse
from ...utils.event_hooks import track_event
from ...utils.core_client import request_core

router = APIRouter(prefix="/api/v1/infrastructure", tags=["infrastructure"])

VALID_COMPONENTS = {"cross-account", "management-resources", "assume-role", "cost-reports"}


def _core_request(method: str, path: str, **kwargs: Any) -> Any:
    try:
        return request_core(method, path, **kwargs)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"bluearch-core infrastructure unavailable: {exc}") from exc


def _core_post(path: str, payload: dict[str, Any] | None = None) -> Any:
    return _core_request(
        "POST",
        path,
        service_token=True,
        timeout=30.0,
        json=payload or {},
    )


async def _request_json(request: Request) -> dict[str, Any]:
    try:
        body = await request.json()
    except Exception:
        return {}
    return body if isinstance(body, dict) else {}


@router.get("/status", response_model=InfrastructureStatusResponse)
async def get_infrastructure_status(
    current_user: LocalUser = Depends(get_current_user),
):
    """Get unified infrastructure status from bluearch-core."""
    result = _core_request("GET", "/api/v1/infrastructure/status", timeout=30.0)
    try:
        track_event(
            "web.infrastructure.status",
            properties={
                "user_sub": getattr(current_user, "sub", None),
                "count": len(result.get("stacksets", [])) + len(result.get("stacks", [])),
                "source": "bluearch-core",
            },
        )
    except Exception:
        pass
    return result


@router.post("/resource-group/create", response_model=ResourceGroupInfo)
@limiter.limit("5/minute")
async def create_resource_group(
    request: Request,
    _user: LocalUser = Depends(require_role(["admin"])),
):
    """Create or update the shared Resource Group through bluearch-core."""
    return _core_post("/api/v1/infrastructure/resource-group/create")


@router.post("/resource-group/delete")
@limiter.limit("5/minute")
async def delete_resource_group(
    request: Request,
    _user: LocalUser = Depends(require_role(["admin"])),
):
    """Delete the shared Resource Group through bluearch-core."""
    return _core_post("/api/v1/infrastructure/resource-group/delete")


@router.post("/cur-stack/delete")
@limiter.limit("5/minute")
async def delete_cur_stack(
    request: Request,
    _user: LocalUser = Depends(require_role(["admin"])),
):
    """Delete the CUR stack through bluearch-core."""
    return _core_post("/api/v1/infrastructure/cur-stack/delete")


@router.post("/stacks/cost-reports/deploy", response_model=JobSubmittedResponse)
@router.post("/cur-stack/deploy", response_model=JobSubmittedResponse)
@limiter.limit("3/minute")
async def deploy_cur_stack(
    request: Request,
    _user: LocalUser = Depends(require_role(["admin", "operator"])),
):
    """Deploy the CUR stack through bluearch-core."""
    body = await _request_json(request)
    return _core_post(
        "/api/v1/infrastructure/stacks/cost-reports/deploy",
        {
            "bucket_name": body.get("bucket_name"),
            "report_name": body.get("report_name") or "tag-manager-cur",
        },
    )


@router.post("/stacks/{component}/update", response_model=JobSubmittedResponse)
@limiter.limit("3/minute")
async def update_infrastructure_stack(
    request: Request,
    component: str,
    _user: LocalUser = Depends(require_role(["admin"])),
):
    """Update a deployed infrastructure stack through bluearch-core."""
    if component not in VALID_COMPONENTS:
        raise HTTPException(status_code=400, detail=f"Unknown component: {component}")
    return _core_post(f"/api/v1/infrastructure/stacks/{component}/update")

