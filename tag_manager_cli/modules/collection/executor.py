"""Throttled thread pool executor for collection engine.

Wraps ThreadPoolExecutor with per-region semaphores to prevent
overwhelming any single region's API rate limits.
"""

from collections import defaultdict
from concurrent.futures import Future, ThreadPoolExecutor
from threading import Semaphore
from typing import Callable

from .models import CollectionJob, CollectorResult


class ThrottledExecutor:
    """Thread pool with per-region concurrency limits."""

    def __init__(self, max_workers: int = 10, max_per_region: int = 3):
        self._executor = ThreadPoolExecutor(max_workers=max_workers)
        self._region_semaphores: dict = defaultdict(lambda: Semaphore(max_per_region))
        self._global_semaphore = Semaphore(2)

    def submit(self, job: CollectionJob, collector_fn: Callable) -> Future:
        """Submit a job, acquiring the appropriate semaphore before executing."""
        return self._executor.submit(self._run, job, collector_fn)

    def _run(self, job: CollectionJob, collector_fn: Callable) -> CollectorResult:
        """Execute collector_fn while holding the region/global semaphore."""
        sem = self._global_semaphore if job.is_global else self._region_semaphores[job.region]
        sem.acquire()
        try:
            return collector_fn(job)
        finally:
            sem.release()

    def shutdown(self):
        self._executor.shutdown(wait=True)
