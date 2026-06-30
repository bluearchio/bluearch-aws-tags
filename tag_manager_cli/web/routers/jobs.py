"""Background job endpoints proxied to bluearch-core."""

from __future__ import annotations

from typing import List, Optional
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, HTTPException

from ...utils.event_hooks import track_event
from ...utils.core_client import request_core
from ..dependencies import get_current_user, require_role, LocalUser
from ..schemas.jobs import DeleteJobRequest, JobResponse, JobSubmittedResponse, ScanJobRequest

router = APIRouter(prefix="/api/v1/jobs", tags=["jobs"])

APP_SOURCE = "tag-manager"


def _core_get(path: str):
    return request_core("GET", path, timeout=5.0)


@router.get("", response_model=List[JobResponse])
async def list_jobs(
    job_type: Optional[str] = None,
    current_user: LocalUser = Depends(get_current_user),
) -> List[dict]:
    """List core-owned jobs."""
    query = f"?{urlencode({'job_type': job_type})}" if job_type else ""
    try:
        result = _core_get(f"/api/v1/jobs{query}")
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"bluearch-core jobs unavailable: {exc}") from exc
    try:
        track_event("web.jobs.list", properties={"user_sub": getattr(current_user, "sub", None), "count": len(result)})
    except Exception:
        pass
    return result


@router.get("/{job_id}", response_model=JobResponse)
async def get_job(job_id: str, _user: LocalUser = Depends(get_current_user)) -> dict:
    """Get a core-owned job."""
    try:
        return _core_get(f"/api/v1/jobs/{job_id}")
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"bluearch-core job unavailable: {exc}") from exc


@router.post("/scan", response_model=JobSubmittedResponse)
async def submit_scan(
    request: ScanJobRequest,
    _user: LocalUser = Depends(require_role(["admin", "operator"])),
) -> JobSubmittedResponse:
    """Submit a resource scan through bluearch-core."""
    try:
        job = request_core(
            "POST",
            "/api/v1/scans",
            json={"product": APP_SOURCE, "services": request.services or [], "regions": request.regions or []},
            timeout=10.0,
        )
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"bluearch-core scan submission unavailable: {exc}") from exc
    return JobSubmittedResponse(
        job_id=job.get("id") or job.get("job_id") or "",
        job_type="scan",
        status=job.get("status") or "pending",
        message="Resource scan started",
    )


@router.post("/delete", response_model=JobSubmittedResponse)
async def submit_delete(
    _request: DeleteJobRequest,
    _user: LocalUser = Depends(require_role(["admin", "operator"])),
) -> JobSubmittedResponse:
    """Deprecated local cleanup endpoint."""
    raise HTTPException(status_code=501, detail="Resource cleanup jobs must run through bluearch-core")


@router.post("/{job_id}/cancel", response_model=JobResponse)
async def cancel_job(
    job_id: str,
    _user: LocalUser = Depends(require_role(["admin", "operator"])),
) -> dict:
    """Cancel a core-owned scan job."""
    try:
        return request_core("POST", f"/api/v1/scans/jobs/{job_id}/cancel", timeout=5.0)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"bluearch-core job cancellation unavailable: {exc}") from exc
