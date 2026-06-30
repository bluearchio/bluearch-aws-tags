"""FastAPI dependencies for job manager, account context, and local web context."""

from collections.abc import AsyncGenerator
from dataclasses import dataclass
from typing import Any, Callable, List, Optional

from fastapi import Depends, HTTPException, Request, status

from ..utils.core_client import request_core_response
from .jobs import JobManager, job_manager


@dataclass(frozen=True)
class LocalUser:
    sub: str = "local"
    email: str | None = None
    groups: tuple[str, ...] = ("admin", "operator", "viewer")


async def get_db() -> AsyncGenerator[None, None]:
    """Legacy dependency kept only to fail closed during the core cutover."""
    raise HTTPException(
        status_code=status.HTTP_410_GONE,
        detail="Direct product database sessions moved to bluearch-core APIs.",
    )
    yield None


def get_job_manager() -> JobManager:
    """Return the singleton job manager."""
    return job_manager


def get_current_user(request: Request) -> LocalUser:
    """Return a local dashboard user context."""
    user = getattr(request.state, "user", None)
    return user if isinstance(user, LocalUser) else LocalUser()


def require_groups(allowed: List[str]) -> Callable[..., LocalUser]:
    """Compatibility dependency retained for existing route signatures."""
    def _check(user: LocalUser = Depends(get_current_user)) -> LocalUser:
        return user
    return _check


def require_role(allowed_roles: list[str]):
    """Compatibility dependency retained for existing route signatures."""
    def _check(user: LocalUser = Depends(get_current_user)) -> LocalUser:
        return user
    return _check


async def get_account_context() -> Optional[dict[str, Any]]:
    """Return the current active account context from bluearch-core."""
    try:
        response = request_core_response(
            "GET",
            "/api/v1/system/context",
            timeout=5.0,
            raise_for_status=False,
        )
    except Exception:
        return None
    if response.status_code == 404:
        return None
    if response.status_code >= 400:
        raise HTTPException(
            status_code=502,
            detail=f"bluearch-core context unavailable: {response.status_code} {response.text}",
        )
    return response.json()


def require_account_context():
    """Dependency that requires an active account context."""
    async def _check(ctx: Optional[dict[str, Any]] = Depends(get_account_context)) -> dict[str, Any]:
        if ctx is None:
            raise HTTPException(
                status_code=503,
                detail="No account context configured. Open Setup and add an account context first."
            )
        return ctx
    return Depends(_check)
