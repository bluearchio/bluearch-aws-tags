"""Resource discovery and listing endpoints proxied to bluearch-core."""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, List, Optional
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from ..core_storage import get_storage_payload, update_storage_payload
from ..dependencies import get_current_user, require_role, LocalUser
from ..schemas.common import PaginatedResponse
from ..schemas.resources import ResourceResponse, ResourceStatsResponse
from ...utils.event_hooks import track_event
from ...utils.core_client import request_core

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/resources", tags=["resources"])


@router.get("", response_model=PaginatedResponse[ResourceResponse])
async def list_resources(
    service: Optional[str] = Query(None, description="Filter by service name (e.g. ec2, s3, lambda)"),
    region: Optional[str] = Query(None, description="Filter by AWS region"),
    account_id: Optional[str] = Query(None, description="Filter by AWS account ID"),
    lifecycle_state: Optional[str] = Query(None, description="Filter by lifecycle state"),
    resource_type: Optional[str] = Query(None, description="Filter by resource type"),
    search: Optional[str] = Query(None, description="Search ARN or resource ID"),
    protected: Optional[bool] = Query(None, description="Filter by protection status"),
    tagged: Optional[bool] = Query(None, description="Filter by tag-manager tags (bluearch:ttl)"),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    current_user: LocalUser = Depends(get_current_user),
):
    """List resources from the core-owned inventory."""
    params = {
        "service": service,
        "region": region,
        "account_id": account_id,
        "lifecycle_state": lifecycle_state,
        "resource_type": resource_type,
        "search": search,
        "protected": protected,
        "tagged": tagged,
        "limit": limit,
        "offset": offset,
    }
    query = urlencode({key: value for key, value in params.items() if value not in (None, "")})
    suffix = f"?{query}" if query else ""
    try:
        result = request_core("GET", f"/api/v1/resources{suffix}", timeout=5.0)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"bluearch-core resources unavailable: {exc}") from exc

    try:
        track_event(
            "web.resources.list",
            properties={
                "user_sub": getattr(current_user, "sub", None),
                "count": len(result.get("items", [])) if isinstance(result, dict) else 0,
                "total": result.get("total") if isinstance(result, dict) else None,
                "limit": limit,
                "offset": offset,
                "service": service,
                "region": region,
                "account_id": account_id,
                "source": "bluearch-core",
            },
        )
    except Exception:
        pass
    return result


@router.get("/stats", response_model=ResourceStatsResponse)
async def resource_stats(_user: LocalUser = Depends(get_current_user)):
    """Get resource count breakdowns from bluearch-core."""
    try:
        return request_core("GET", "/api/v1/resources/stats", timeout=5.0)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"bluearch-core resource stats unavailable: {exc}") from exc


@router.get("/by-arn", response_model=ResourceResponse)
async def get_resource_by_arn(
    arn: str = Query(..., description="Resource ARN"),
    _user: LocalUser = Depends(get_current_user),
):
    """Get a single resource by ARN."""
    try:
        return request_core("GET", f"/api/v1/resources/by-arn?{urlencode({'arn': arn})}", timeout=5.0)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"bluearch-core resource lookup unavailable: {exc}") from exc


@router.get("/{resource_id}", response_model=ResourceResponse)
async def get_resource(
    resource_id: str,
    _user: LocalUser = Depends(get_current_user),
):
    """Get a single resource by ID."""
    try:
        return request_core("GET", f"/api/v1/resources/{resource_id}", timeout=5.0)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"bluearch-core resource unavailable: {exc}") from exc


class RemoveTagsRequest(BaseModel):
    resource_ids: List[str]


class RemoveTagsResponse(BaseModel):
    affected_count: int
    aws_removed: int
    aws_failed: int
    details: str


def _parse_json_field(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, dict) else {}
        except (json.JSONDecodeError, ValueError):
            return {}
    return {}


def _remove_tags_from_aws(resource_arn: str, service_name: str, tag_keys: List[str], resource_info: dict) -> bool:
    """Remove tags from an AWS resource."""
    from ...commands.unified_tags import _get_client_for_resource

    try:
        svc = service_name.lower()
        if svc == "ec2":
            client = _get_client_for_resource("ec2", resource_info)
            client.delete_tags(Resources=[resource_info["resource_id"]], Tags=[{"Key": key} for key in tag_keys])
        elif svc == "s3":
            client = _get_client_for_resource("s3", resource_info)
            bucket_name = resource_info["resource_id"]
            try:
                existing = client.get_bucket_tagging(Bucket=bucket_name).get("TagSet", [])
            except Exception:
                existing = []
            new_tags = [tag for tag in existing if tag["Key"] not in tag_keys]
            if new_tags:
                client.put_bucket_tagging(Bucket=bucket_name, Tagging={"TagSet": new_tags})
            else:
                client.delete_bucket_tagging(Bucket=bucket_name)
        elif svc == "lambda":
            client = _get_client_for_resource("lambda", resource_info)
            client.untag_resource(Resource=resource_arn, TagKeys=tag_keys)
        else:
            client = _get_client_for_resource("resourcegroupstaggingapi", resource_info)
            response = client.untag_resources(ResourceARNList=[resource_arn], TagKeys=tag_keys)
            failed = response.get("FailedResourcesMap", {})
            if failed:
                error = next(iter(failed.values()), {})
                raise RuntimeError(error.get("ErrorMessage", "unknown error"))
        return True
    except Exception as exc:
        logger.warning("Failed to remove tags from %s: %s", resource_arn, exc)
        return False


@router.post("/remove-tags", response_model=RemoveTagsResponse)
async def remove_tags(
    body: RemoveTagsRequest,
    _user: LocalUser = Depends(require_role(["admin", "operator"])),
):
    """Remove bluearch:ttl tags from AWS and the core-owned resource records."""
    resources = []
    for resource_id in body.resource_ids:
        try:
            resources.append(get_storage_payload("core", "resources", resource_id))
        except Exception:
            continue
    if not resources:
        return RemoveTagsResponse(affected_count=0, aws_removed=0, aws_failed=0, details="No matching resources")

    tag_targets = []
    for resource in resources:
        arn_parts = str(resource.get("resource_arn") or "").split(":")
        tag_targets.append(
            (
                resource,
                {
                    "resource_arn": resource.get("resource_arn"),
                    "service_name": resource.get("service_name"),
                    "resource_id": resource.get("resource_id"),
                    "region": arn_parts[3] if len(arn_parts) > 3 else resource.get("region"),
                    "account_id": resource.get("account_id"),
                },
            )
        )

    def _sync_remove():
        ok = 0
        fail = 0
        for _, resource_info in tag_targets:
            result = _remove_tags_from_aws(
                resource_info["resource_arn"],
                resource_info["service_name"],
                ["bluearch:ttl"],
                resource_info,
            )
            if result:
                ok += 1
            else:
                fail += 1
        return ok, fail

    aws_ok, aws_fail = await asyncio.to_thread(_sync_remove)

    for resource, _ in tag_targets:
        tags = _parse_json_field(resource.get("current_tags"))
        tags.pop("bluearch:ttl", None)
        resource["current_tags"] = tags
        resource["expires_at"] = None
        resource["lifecycle_state"] = None
        resource["ttl_source"] = None
        resource["lifecycle_policy_id"] = None
        update_storage_payload("core", "resources", str(resource["id"]), resource)

    parts = [f"Removed tag-manager tags from {len(resources)} resource(s)"]
    if aws_ok:
        parts.append(f"AWS tags removed from {aws_ok}")
    if aws_fail:
        parts.append(f"AWS removal failed on {aws_fail}")
    return RemoveTagsResponse(
        affected_count=len(resources),
        aws_removed=aws_ok,
        aws_failed=aws_fail,
        details=". ".join(parts),
    )
