"""In-memory async job manager for background tasks."""

import asyncio
import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Callable, Coroutine, Dict, List, Optional

from pydantic import BaseModel, Field


class JobStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class JobRecord(BaseModel):
    """Represents a background job."""

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    job_type: str
    status: JobStatus = JobStatus.PENDING
    progress: int = 0
    progress_message: Optional[str] = None
    progress_data: Optional[Dict[str, Any]] = None
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    created_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    started_at: Optional[str] = None
    completed_at: Optional[str] = None


class JobManager:
    """Manages background jobs with in-memory storage."""

    MAX_COMPLETED = 100

    def __init__(self) -> None:
        self._jobs: Dict[str, JobRecord] = {}
        self._tasks: Dict[str, asyncio.Task] = {}

    def create_job(self, job_type: str) -> JobRecord:
        """Create a new pending job."""
        job = JobRecord(job_type=job_type)
        self._jobs[job.id] = job
        self._cleanup_old_jobs()
        return job

    def get_job(self, job_id: str) -> Optional[JobRecord]:
        """Get a job by ID."""
        return self._jobs.get(job_id)

    def list_jobs(
        self, job_type: Optional[str] = None, status: Optional[JobStatus] = None
    ) -> List[JobRecord]:
        """List jobs, optionally filtered by type or status."""
        jobs = list(self._jobs.values())
        if job_type:
            jobs = [j for j in jobs if j.job_type == job_type]
        if status:
            jobs = [j for j in jobs if j.status == status]
        return sorted(jobs, key=lambda j: j.created_at, reverse=True)

    def mark_running(self, job_id: str) -> None:
        """Mark a job as running."""
        job = self._jobs.get(job_id)
        if job and job.status != JobStatus.CANCELLED:
            job.status = JobStatus.RUNNING
            job.started_at = datetime.now(timezone.utc).isoformat()

    def update_progress(
        self,
        job_id: str,
        progress: int,
        message: Optional[str] = None,
        data: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Update job progress (0-100) with optional structured data."""
        job = self._jobs.get(job_id)
        if job and job.status != JobStatus.CANCELLED:
            job.progress = min(max(progress, 0), 100)
            if message:
                job.progress_message = message
            if data:
                job.progress_data = data

    def mark_completed(
        self, job_id: str, result: Optional[Dict[str, Any]] = None
    ) -> None:
        """Mark a job as completed with optional result data."""
        job = self._jobs.get(job_id)
        if job and job.status != JobStatus.CANCELLED:
            job.status = JobStatus.COMPLETED
            job.progress = 100
            job.result = result
            job.completed_at = datetime.now(timezone.utc).isoformat()

    def mark_failed(self, job_id: str, error: str) -> None:
        """Mark a job as failed with error message."""
        job = self._jobs.get(job_id)
        if job and job.status != JobStatus.CANCELLED:
            job.status = JobStatus.FAILED
            job.error = error
            job.completed_at = datetime.now(timezone.utc).isoformat()

    def cancel_job(self, job_id: str) -> Optional[JobRecord]:
        """Mark a pending/running job as cancelled."""
        job = self._jobs.get(job_id)
        if not job:
            return None
        if job.status in (JobStatus.PENDING, JobStatus.RUNNING):
            job.status = JobStatus.CANCELLED
            job.progress_message = "Scan cancelled"
            job.completed_at = datetime.now(timezone.utc).isoformat()
        return job

    def is_cancelled(self, job_id: str) -> bool:
        """Return True when a job has been cancelled."""
        job = self._jobs.get(job_id)
        return bool(job and job.status == JobStatus.CANCELLED)

    def submit_async(
        self,
        job_id: str,
        coro_fn: Callable[..., Coroutine],
        *args: Any,
        **kwargs: Any,
    ) -> None:
        """Submit a coroutine to run as a background task for the given job."""
        self.mark_running(job_id)

        async def _run() -> None:
            try:
                result = await coro_fn(*args, **kwargs)
                self.mark_completed(job_id, result)
            except asyncio.CancelledError:
                self.cancel_job(job_id)
            except Exception as exc:
                self.mark_failed(job_id, str(exc))
            finally:
                self._tasks.pop(job_id, None)

        task = asyncio.create_task(_run())
        self._tasks[job_id] = task

    def _cleanup_old_jobs(self) -> None:
        """Remove oldest completed/failed jobs when over capacity."""
        terminal = [
            j
            for j in self._jobs.values()
            if j.status in (JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED)
        ]
        if len(terminal) > self.MAX_COMPLETED:
            terminal.sort(key=lambda j: j.completed_at or j.created_at)
            for job in terminal[: len(terminal) - self.MAX_COMPLETED]:
                self._jobs.pop(job.id, None)


# Module-level singleton
job_manager = JobManager()
