"""System health, status, and setup validation endpoints."""

import asyncio
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException

from ..dependencies import get_current_user, LocalUser
from ..schemas.common import (
    HealthResponse,
    SetupCheckItem,
    SetupValidateResponse,
)
from ...utils.core_client import request_core

router = APIRouter(prefix="/api/v1/system", tags=["system"])


def _normalize_core_validation(payload: dict) -> SetupValidateResponse:
    checks = payload.get("checks") if isinstance(payload, dict) else {}
    if isinstance(checks, list):
        statuses = [item.get("status") for item in checks if isinstance(item, dict)]
        return SetupValidateResponse(overall=payload.get("overall") or _overall(statuses), checks=checks)

    normalized = []
    if isinstance(checks, dict):
        database = checks.get("database") or {}
        normalized.append(
            SetupCheckItem(
                name="Database",
                status="ok" if database.get("ok") else "error",
                message=f"Core database ready at {database.get('path')}" if database.get("ok") else "Core database is not ready",
                details=database,
            )
        )
        aws = checks.get("aws_credentials") or {}
        identity = aws.get("identity") or {}
        normalized.append(
            SetupCheckItem(
                name="AWS Credentials",
                status="ok" if aws.get("ok") else "error",
                message=f"Authenticated as {identity.get('Arn', 'unknown')}" if aws.get("ok") else f"AWS credentials unavailable: {aws.get('error')}",
                details=aws,
            )
        )
        token = checks.get("service_token") or {}
        normalized.append(
            SetupCheckItem(
                name="BlueArch Core",
                status="ok" if token.get("ok") else "error",
                message=f"Core service token ready at {token.get('path')}" if token.get("ok") else "Core service token missing",
                details=token,
            )
        )
    statuses = [item.status for item in normalized]
    return SetupValidateResponse(overall=payload.get("overall") or _overall(statuses), checks=normalized)


def _overall(statuses: list[str]) -> str:
    if "error" in statuses:
        return "unhealthy"
    if "warning" in statuses:
        return "degraded"
    return "healthy"


@router.get("/health", response_model=HealthResponse)
async def health_check():
    """Check system health through bluearch-core."""
    try:
        core_health = request_core("GET", "/api/v1/core/health", timeout=5.0)
        summary = request_core("GET", "/api/v1/resources/summary", timeout=5.0)
        try:
            from tag_manager_cli import __version__
            version = __version__
        except Exception:
            version = "unknown"
        return HealthResponse(
            status="healthy" if core_health.get("status") == "ok" else "degraded",
            database="connected" if core_health.get("db_ready") else "not ready",
            database_type="bluearch-core",
            tables_exist=bool(core_health.get("db_ready")),
            resource_count=int(summary.get("total") or 0),
            version=version,
        )
    except Exception as exc:
        return HealthResponse(status="unhealthy", database=f"bluearch-core error: {exc}")


@router.get("/setup/validate", response_model=SetupValidateResponse)
async def validate_setup(current_user: LocalUser = Depends(get_current_user)):
    """Validate setup through bluearch-core."""
    try:
        result = _normalize_core_validation(request_core("GET", "/api/v1/setup/validate", timeout=15.0))
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"bluearch-core setup validation unavailable: {exc}") from exc
    return result



@router.get("/setup/iam-policy")
async def get_iam_policy(_user: LocalUser = Depends(get_current_user)):
    """Return the required IAM policy JSON."""
    try:
        return request_core("GET", "/api/v1/setup/iam-policy", timeout=10.0)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"bluearch-core IAM policy unavailable: {exc}") from exc

    import json
    import os

    def _load_policy():
        # Try multiple paths for the policy file
        possible_paths = [
            os.path.join(os.path.dirname(__file__), "../../integrations/iam-policy.json"),
            os.path.expanduser("~/.tag-manager/iam-policy.json"),
        ]

        # Also check for PyInstaller/Nuitka bundled path
        try:
            import sys
            if hasattr(sys, "_MEIPASS"):
                possible_paths.insert(
                    0,
                    os.path.join(
                        sys._MEIPASS,
                        "tag_manager_cli",
                        "integrations",
                        "iam-policy.json",
                    ),
                )
        except Exception:
            pass

        for path in possible_paths:
            if os.path.exists(path):
                with open(path, "r") as f:
                    return json.load(f)

        return None

    try:
        policy = await asyncio.to_thread(_load_policy)
        if policy:
            return policy
        else:
            return {"error": "IAM policy file not found"}
    except Exception as e:
        return {"error": f"Failed to load IAM policy: {e}"}

