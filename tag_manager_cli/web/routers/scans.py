"""Shared scan job endpoints proxied to bluearch-core."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from ...utils.core_client import request_core
from ..dependencies import get_current_user, LocalUser

router = APIRouter(prefix="/api/v1/scans", tags=["scans"])


@router.get("/jobs")
async def list_scan_jobs(current_user: LocalUser = Depends(get_current_user)):
    """List recent scan jobs from bluearch-core."""
    try:
        result = request_core("GET", "/api/v1/scans/jobs", timeout=5.0)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"bluearch-core scan jobs unavailable: {exc}") from exc
    return result


@router.get("/jobs/{job_id}")
async def get_scan_job(
    job_id: str,
    _user: LocalUser = Depends(get_current_user),
):
    """Poll a specific scan job status from bluearch-core."""
    try:
        return request_core("GET", f"/api/v1/scans/jobs/{job_id}", timeout=5.0)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"bluearch-core scan job unavailable: {exc}") from exc
