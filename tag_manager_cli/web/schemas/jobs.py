"""Pydantic schemas for background job endpoints."""

from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class ScanJobRequest(BaseModel):
    """Request to start a resource scan job."""

    services: Optional[List[str]] = Field(
        None, description="Services to scan (e.g. ['ec2', 's3']). None = all."
    )
    regions: Optional[List[str]] = Field(
        None, description="Regions to scan. None = US regions. Use ['all'] for all enabled regions."
    )


class DeleteJobRequest(BaseModel):
    """Request to start a delete-expired-resources job."""

    services: Optional[List[str]] = Field(
        None, description="Filter deletion by services."
    )


class JobResponse(BaseModel):
    """Background job status."""

    id: str
    job_type: str
    status: str
    progress: int = 0
    progress_message: Optional[str] = None
    progress_data: Optional[Dict[str, Any]] = None
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    created_at: str
    started_at: Optional[str] = None
    completed_at: Optional[str] = None


class JobSubmittedResponse(BaseModel):
    """Response when a job is submitted."""

    job_id: str
    job_type: str
    status: str
    message: str
