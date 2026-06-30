"""Lifecycle management endpoints backed by bluearch-core storage."""

from __future__ import annotations

import asyncio
import json as json_mod
import logging
import re
import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from ..core_storage import (
    create_storage_payload,
    delete_storage_payload,
    get_storage_payload,
    list_storage_payloads,
    update_storage_payload,
)
from ..dependencies import get_current_user, require_role, LocalUser
from ..schemas.common import PaginatedResponse
from ..schemas.lifecycle import (
    AuditLogResponse,
    ExecuteDeleteRequest,
    ExpiringResourceResponse,
    LifecycleDashboardResponse,
    MatchedResourceItem,
    MatchPreviewRequest,
    MatchPreviewResponse,
    MutationResultResponse,
    PolicyCreateRequest,
    PolicyResponse,
    PolicySaveResult,
    PolicyUpdateRequest,
    ProtectRequest,
    ReviewActionRequest,
    ReviewResourceResponse,
    SetTTLRequest,
    ExtendTTLRequest,
    TTLPreviewItem,
    TTLPreviewResponse,
)
from ...utils.core_client import CoreRuntimeError

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/lifecycle", tags=["lifecycle"])

RESOURCE_TYPE_MAPPING = {
    "AWS::Lambda::Function": "lambda_function",
    "AWS::Lambda::LayerVersion": "lambda_layer",
    "AWS::EC2::Instance": "ec2_instance",
    "AWS::EC2::Volume": "ec2_volume",
    "AWS::EC2::Snapshot": "ec2_snapshot",
    "AWS::EC2::Image": "ec2_ami",
    "AWS::EC2::EIP": "ec2_eip",
    "AWS::S3::Bucket": "s3_bucket",
    "AWS::RDS::DBInstance": "rds_instance",
    "AWS::RDS::DBCluster": "rds_cluster",
    "AWS::RDS::DBSnapshot": "rds_snapshot",
    "AWS::DynamoDB::Table": "dynamodb_table",
    "AWS::ElastiCache::CacheCluster": "elasticache_cluster",
    "AWS::ECS::Cluster": "ecs_cluster",
    "AWS::ECS::Service": "ecs_service",
    "AWS::ECS::TaskDefinition": "ecs_task_definition",
    "AWS::EKS::Cluster": "eks_cluster",
    "AWS::SNS::Topic": "sns_topic",
    "AWS::SQS::Queue": "sqs_queue",
    "AWS::CloudWatch::Alarm": "cloudwatch_alarm",
    "AWS::Logs::LogGroup": "cloudwatch_log_group",
    "AWS::SecretsManager::Secret": "secretsmanager_secret",
    "AWS::KMS::Key": "kms_key",
    "AWS::EC2::VPC": "ec2_vpc",
    "AWS::EC2::Subnet": "ec2_subnet",
    "AWS::EC2::SecurityGroup": "ec2_security_group",
    "AWS::IAM::Role": "iam_role",
}


@router.get("/dashboard", response_model=LifecycleDashboardResponse)
async def lifecycle_dashboard(current_user: LocalUser = Depends(get_current_user)):
    """Get lifecycle dashboard summary."""
    try:
        now = datetime.now(timezone.utc)
        resources = _all_core_resources()
        policies = _all_core_policies()
        active = sum(1 for r in resources if r.get("lifecycle_state") == "active")
        warned = sum(1 for r in resources if r.get("lifecycle_state") == "warned")
        marked = sum(1 for r in resources if r.get("lifecycle_state") == "marked_for_deletion")
        protected = sum(1 for r in resources if r.get("protected"))
        expiring_7d = sum(1 for r in resources if _is_expiring(r, now, 7))
        expiring_30d = sum(1 for r in resources if _is_expiring(r, now, 30))
        expired = sum(1 for r in resources if _is_expired(r, now))
        tagged = sum(1 for r in resources if r.get("current_tags"))
        return LifecycleDashboardResponse(
            total_resources=len(resources),
            active=active,
            warned=warned,
            marked_for_deletion=marked,
            protected=protected,
            expired=expired,
            expiring_7d=expiring_7d,
            expiring_30d=expiring_30d,
            tagged=tagged,
            policies_count=len(policies),
        )
    except CoreRuntimeError as exc:
        raise _core_unavailable(exc) from exc


@router.get("/expiring", response_model=PaginatedResponse[ExpiringResourceResponse])
async def expiring_resources(
    days: int = Query(7, ge=1, le=365),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    _user: LocalUser = Depends(get_current_user),
):
    now = datetime.now(timezone.utc)
    rows = [r for r in _all_core_resources() if _is_expiring(r, now, days)]
    rows.sort(key=lambda r: _parse_dt(r.get("expires_at")) or datetime.max.replace(tzinfo=timezone.utc))
    policies = _policy_map()
    items = [_expiring_response(r, policies, now) for r in rows[offset : offset + limit]]
    return PaginatedResponse(items=items, total=len(rows), limit=limit, offset=offset)


@router.get("/expired", response_model=PaginatedResponse[ExpiringResourceResponse])
async def expired_resources(
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    _user: LocalUser = Depends(get_current_user),
):
    now = datetime.now(timezone.utc)
    rows = [r for r in _all_core_resources() if _is_expired(r, now)]
    rows.sort(key=lambda r: _parse_dt(r.get("expires_at")) or datetime.max.replace(tzinfo=timezone.utc))
    policies = _policy_map()
    items = [_expiring_response(r, policies, now) for r in rows[offset : offset + limit]]
    return PaginatedResponse(items=items, total=len(rows), limit=limit, offset=offset)


@router.get("/policies", response_model=PaginatedResponse[PolicyResponse])
async def list_policies(
    enabled_only: bool = Query(False),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    _user: LocalUser = Depends(get_current_user),
):
    resources = _all_core_resources()
    rows = _all_core_policies()
    if enabled_only:
        rows = [row for row in rows if row.get("enabled")]
    rows.sort(key=lambda p: (p.get("priority") or 100, p.get("name") or ""))
    items = [
        _policy_response(policy, _policy_resource_count(resources, policy.get("id")))
        for policy in rows[offset : offset + limit]
    ]
    return PaginatedResponse(items=items, total=len(rows), limit=limit, offset=offset)


@router.post("/policies/match-preview", response_model=MatchPreviewResponse)
async def match_preview(
    body: MatchPreviewRequest,
    _user: LocalUser = Depends(get_current_user),
):
    temp_payload = {
        "id": "temp",
        "name": "temp",
        "resource_types": body.resource_types or [],
        "conditions": body.conditions or {"tags": []},
        "exclude_patterns": body.exclude_patterns,
        "ttl_days": 30,
        "warning_days_before": 7,
        "actions": [],
        "priority": 100,
        "enabled": True,
    }
    matched = _matched_core_resources(temp_payload)
    return MatchPreviewResponse(
        matched_count=len(matched),
        resources=[_matched_item(r) for r in matched[:50]],
    )


@router.post("/policies", response_model=PolicySaveResult, status_code=201)
async def create_policy(
    body: PolicyCreateRequest,
    _user: LocalUser = Depends(require_role(["admin", "operator"])),
):
    if any(policy.get("name") == body.name for policy in _all_core_policies()):
        raise HTTPException(status_code=409, detail=f"Policy with name '{body.name}' already exists")
    now = datetime.now(timezone.utc)
    policy = create_storage_payload(
        "tag-manager",
        "resource-lifecycle-policies",
        _policy_create_payload(body, now),
    )
    matched_count, ttl_applied_count = await _apply_policy_to_matching_resources(policy, now)
    return PolicySaveResult(
        policy=_policy_response(policy, matched_count),
        matched_count=matched_count,
        ttl_applied_count=ttl_applied_count,
    )


@router.patch("/policies/{policy_id}", response_model=PolicySaveResult)
async def update_policy(
    policy_id: str,
    body: PolicyUpdateRequest,
    _user: LocalUser = Depends(require_role(["admin", "operator"])),
):
    policy = _get_policy_or_404(policy_id)
    updates = body.model_dump(exclude_unset=True) if hasattr(body, "model_dump") else body.dict(exclude_unset=True)
    field_map = {"warning_days": "warning_days_before"}
    for field, value in updates.items():
        policy[field_map.get(field, field)] = value
    policy["updated_at"] = datetime.now(timezone.utc).isoformat()
    policy = update_storage_payload("tag-manager", "resource-lifecycle-policies", policy_id, policy)
    _clear_policy_links(policy_id)
    matched_count, ttl_applied_count = await _apply_policy_to_matching_resources(policy, datetime.now(timezone.utc))
    return PolicySaveResult(
        policy=_policy_response(policy, matched_count),
        matched_count=matched_count,
        ttl_applied_count=ttl_applied_count,
    )


@router.delete("/policies/{policy_id}", status_code=204)
async def delete_policy(
    policy_id: str,
    _user: LocalUser = Depends(require_role(["admin", "operator"])),
):
    _get_policy_or_404(policy_id)
    _clear_policy_links(policy_id)
    delete_storage_payload("tag-manager", "resource-lifecycle-policies", policy_id)
    return None


@router.get("/policies/{policy_id}/resources", response_model=PaginatedResponse[MatchedResourceItem])
async def get_policy_resources(
    policy_id: str,
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    _user: LocalUser = Depends(get_current_user),
):
    _get_policy_or_404(policy_id)
    rows = [r for r in _all_core_resources() if str(r.get("lifecycle_policy_id")) == str(policy_id)]
    items = [_matched_item(r) for r in rows[offset : offset + limit]]
    return PaginatedResponse(items=items, total=len(rows), limit=limit, offset=offset)


@router.post("/set-ttl/preview", response_model=TTLPreviewResponse)
async def preview_set_ttl(
    body: SetTTLRequest,
    _user: LocalUser = Depends(require_role(["admin", "operator"])),
):
    resources = _select_core_resources(body.resource_ids, body.resource_arns, body.services)
    new_expires = datetime.now(timezone.utc) + timedelta(days=body.ttl_days)
    tag_value = new_expires.strftime("%Y-%m-%d")
    items = [
        TTLPreviewItem(
            resource_id=str(r.get("id")),
            resource_arn=r.get("resource_arn") or "",
            service_name=r.get("service_name") or "",
            region=r.get("region") or "",
            account_id=r.get("account_id") or "",
            current_expires_at=_iso(r.get("expires_at")),
            new_expires_at=new_expires.isoformat(),
            tag_key="bluearch:ttl",
            tag_value=tag_value,
        )
        for r in resources
    ]
    return TTLPreviewResponse(
        resources=items,
        total_count=len(items),
        ttl_days=body.ttl_days,
        apply_aws_tags=body.apply_aws_tags,
    )


@router.post("/set-ttl", response_model=MutationResultResponse)
async def set_ttl(
    body: SetTTLRequest,
    _user: LocalUser = Depends(require_role(["admin", "operator"])),
):
    resources = _select_core_resources(body.resource_ids, body.resource_arns, body.services)
    if not resources:
        return MutationResultResponse(affected_count=0, details="No matching resources")
    new_expires = datetime.now(timezone.utc) + timedelta(days=body.ttl_days)
    detail = await _set_resource_ttl(resources, new_expires, apply_aws_tags=body.apply_aws_tags)
    return MutationResultResponse(affected_count=len(resources), details=detail)


@router.post("/extend", response_model=MutationResultResponse)
async def extend_ttl(
    body: ExtendTTLRequest,
    _user: LocalUser = Depends(require_role(["admin", "operator"])),
):
    resources = [r for r in _select_core_resources(body.resource_ids, body.resource_arns) if r.get("expires_at")]
    if not resources:
        return MutationResultResponse(affected_count=0, details="No matching resources with TTL")
    new_expires = datetime.now(timezone.utc) + timedelta(days=body.days)
    detail = await _set_resource_ttl(resources, new_expires, apply_aws_tags=body.apply_aws_tags, verb=f"Extended by {body.days} days")
    return MutationResultResponse(affected_count=len(resources), details=detail)


@router.post("/protect", response_model=MutationResultResponse)
async def toggle_protect(
    body: ProtectRequest,
    _user: LocalUser = Depends(require_role(["admin", "operator"])),
):
    resources = _select_core_resources(body.resource_ids, body.resource_arns)
    for resource in resources:
        resource["protected"] = body.protect
        _update_core_resource(resource)
    action = "Protected" if body.protect else "Unprotected"
    return MutationResultResponse(affected_count=len(resources), details=f"{action} {len(resources)} resource(s)")


@router.get("/review", response_model=PaginatedResponse[ReviewResourceResponse])
async def review_resources(
    days: Optional[int] = Query(None, ge=1, le=365),
    services: Optional[str] = Query(None),
    include_active: bool = Query(False),
    lifecycle_state: Optional[str] = Query(None),
    account_id: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    _user: LocalUser = Depends(get_current_user),
):
    now = datetime.now(timezone.utc)
    rows = [r for r in _all_core_resources() if not r.get("protected")]
    rows = _filter_review_rows(rows, now, days, services, include_active, lifecycle_state, account_id)
    rows.sort(key=lambda r: _parse_dt(r.get("expires_at")) or datetime.max.replace(tzinfo=timezone.utc))
    policy_names = _policy_map()
    items = [_review_resource_response(r, policy_names, now) for r in rows[offset : offset + limit]]
    return PaginatedResponse(items=items, total=len(rows), limit=limit, offset=offset)


@router.post("/review/extend", response_model=MutationResultResponse)
async def review_extend(
    body: ReviewActionRequest,
    _user: LocalUser = Depends(require_role(["admin", "operator"])),
):
    if not body.days:
        raise HTTPException(status_code=400, detail="'days' is required for extend")
    resources = _select_core_resources(body.resource_ids, None)
    new_expires = datetime.now(timezone.utc) + timedelta(days=body.days)
    _review_update(resources, "extend", "TTL_EXTENDED", body.reason, new_expires, body.days)
    return MutationResultResponse(affected_count=len(resources), details=f"Extended {len(resources)} resource(s) by {body.days} days")


@router.post("/review/protect", response_model=MutationResultResponse)
async def review_protect(
    body: ReviewActionRequest,
    _user: LocalUser = Depends(require_role(["admin", "operator"])),
):
    resources = _select_core_resources(body.resource_ids, None)
    _review_update(resources, "protect", "PROTECTED", body.reason, protect=True)
    return MutationResultResponse(affected_count=len(resources), details=f"Protected {len(resources)} resource(s)")


@router.post("/review/mark-delete", response_model=MutationResultResponse)
async def review_mark_delete(
    body: ReviewActionRequest,
    _user: LocalUser = Depends(require_role(["admin", "operator"])),
):
    resources = _select_core_resources(body.resource_ids, None)
    _review_update(resources, "terminate", "DELETION_SCHEDULED", body.reason, new_state="marked_for_deletion")
    return MutationResultResponse(affected_count=len(resources), details=f"Marked {len(resources)} resource(s) for deletion")


@router.post("/review/execute-delete", response_model=MutationResultResponse)
async def review_execute_delete(
    body: ExecuteDeleteRequest,
    _user: LocalUser = Depends(require_role(["admin", "operator"])),
):
    if body.confirmation != "DELETE":
        raise HTTPException(status_code=400, detail="Confirmation must be exactly 'DELETE'")
    resources = [
        r
        for r in _select_core_resources(body.resource_ids, None)
        if r.get("lifecycle_state") == "marked_for_deletion" and not r.get("protected")
    ]
    if not resources:
        raise HTTPException(status_code=400, detail="No eligible resources found (must be marked_for_deletion and not protected)")

    def _sync_delete():
        from ...commands.unified_tags import _delete_aws_resource

        return [(resource, _delete_aws_resource(_resource_namespace(resource))) for resource in resources]

    delete_results = await asyncio.to_thread(_sync_delete)
    success_count = 0
    fail_messages = []
    user = _get_current_user()
    for resource, result in delete_results:
        old_state = resource.get("lifecycle_state")
        if result.get("success"):
            resource["lifecycle_state"] = "deleted"
            _update_core_resource(resource)
            success_count += 1
            _create_core_audit(
                resource_arn=resource.get("resource_arn"),
                resource_id=str(resource.get("id")),
                operation="RESOURCE_DELETED",
                old_state=old_state,
                new_state="deleted",
                success=True,
                executed_by=user,
                operation_details={"message": result.get("message", ""), "via": "web"},
            )
        else:
            error = result.get("error", "Unknown error")
            fail_messages.append(f"{resource.get('resource_arn')}: {error}")
            _create_core_audit(
                resource_arn=resource.get("resource_arn"),
                resource_id=str(resource.get("id")),
                operation="RESOURCE_DELETED",
                old_state=old_state,
                new_state=old_state,
                success=False,
                error_message=error,
                executed_by=user,
                operation_details={"via": "web"},
            )
    parts = []
    if success_count:
        parts.append(f"Deleted {success_count} resource(s)")
    if fail_messages:
        parts.append(f"Failed {len(fail_messages)}: {'; '.join(fail_messages[:3])}")
    return MutationResultResponse(affected_count=success_count, details=". ".join(parts))


@router.get("/audit-log", response_model=PaginatedResponse[AuditLogResponse])
async def lifecycle_audit_log(
    resource_id: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    _user: LocalUser = Depends(get_current_user),
):
    filters = [("resource_id", resource_id)] if resource_id else None
    rows = list_storage_payloads(
        "tag-manager",
        "lifecycle-audit-log",
        limit=10000,
        filters=filters,
        order_by="executed_at",
        descending=True,
    )
    items = [_audit_response(a) for a in rows[offset : offset + limit]]
    return PaginatedResponse(items=items, total=len(rows), limit=limit, offset=offset)


def _all_core_resources() -> list[dict[str, Any]]:
    return list_storage_payloads("core", "resources", limit=10000)


def _all_core_policies() -> list[dict[str, Any]]:
    return list_storage_payloads(
        "tag-manager",
        "resource-lifecycle-policies",
        limit=10000,
        order_by="priority",
        descending=False,
    )


def _parse_dt(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, str) and value:
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
        except ValueError:
            return None
    return None


def _iso(value: Any) -> str | None:
    parsed = _parse_dt(value)
    return parsed.isoformat() if parsed else None


def _is_expiring(resource: dict[str, Any], now: datetime, days: int) -> bool:
    exp = _parse_dt(resource.get("expires_at"))
    return bool(exp and not resource.get("protected") and now < exp <= now + timedelta(days=days))


def _is_expired(resource: dict[str, Any], now: datetime) -> bool:
    exp = _parse_dt(resource.get("expires_at"))
    return bool(exp and not resource.get("protected") and exp < now)


def _resource_namespace(resource: dict[str, Any]) -> SimpleNamespace:
    payload = dict(resource)
    payload.setdefault("resource_id", payload.get("id") or payload.get("resource_arn") or "")
    return SimpleNamespace(**payload)


def _policy_matches_resource(policy: dict[str, Any], resource: dict[str, Any]) -> bool:
    resource_type = resource.get("resource_type") or ""
    normalized_type = RESOURCE_TYPE_MAPPING.get(resource_type, resource_type.lower())
    resource_types = policy.get("resource_types") or []
    if resource_types and normalized_type not in resource_types:
        return False

    current_tags = _tags(resource)
    exclude_patterns = policy.get("exclude_patterns") or {}
    resource_name = str(resource.get("resource_id") or resource.get("id") or "").lower()
    for pattern in exclude_patterns.get("resource_names", []):
        normalized_pattern = str(pattern).lower()
        regex_pattern = normalized_pattern
        if "*" in regex_pattern or "?" in regex_pattern:
            regex_pattern = re.escape(regex_pattern).replace(r"\*", ".*").replace(r"\?", ".")
        try:
            if re.search(regex_pattern, resource_name):
                return False
        except re.error:
            if normalized_pattern in resource_name:
                return False

    for tag_exclusion in exclude_patterns.get("tags", []):
        tag_key = tag_exclusion.get("key")
        tag_value = tag_exclusion.get("value")
        if tag_key in current_tags and (not tag_value or current_tags[tag_key] == tag_value):
            return False

    conditions = policy.get("conditions") or {"tags": []}
    conditions_list = conditions.get("tags", []) if isinstance(conditions, dict) else conditions
    for condition in conditions_list or []:
        field = condition.get("field", "")
        operator = condition.get("operator", "equals")
        value = condition.get("value")
        if field.startswith("resource."):
            field_name = field.replace("resource.", "", 1)
            resource_value = resource.get(field_name)
        elif field.startswith("tags."):
            tag_name = field.replace("tags.", "", 1)
            resource_value = current_tags.get(tag_name)
        else:
            continue
        if operator == "equals" and resource_value != value:
            return False
        if operator == "not_equals" and resource_value == value:
            return False
        if operator == "contains" and (not resource_value or str(value) not in str(resource_value)):
            return False
        if operator == "exists" and not resource_value:
            return False
        if operator == "not_exists" and resource_value:
            return False
    return True


def _policy_response(policy: dict[str, Any], resource_count: int = 0) -> PolicyResponse:
    return PolicyResponse(
        id=str(policy.get("id")),
        name=policy.get("name") or "",
        description=policy.get("description"),
        resource_types=policy.get("resource_types") or [],
        default_ttl_days=policy.get("ttl_days"),
        warning_days=policy.get("warning_days_before"),
        enabled=policy.get("enabled", True),
        created_at=_iso(policy.get("created_at")),
        updated_at=_iso(policy.get("updated_at")),
        resource_count=resource_count,
        conditions=policy.get("conditions"),
        exclude_patterns=policy.get("exclude_patterns"),
        warning_schedule=policy.get("warning_schedule"),
        grace_period_days=policy.get("grace_period_days"),
        auto_apply=policy.get("auto_apply"),
    )


def _policy_create_payload(body: PolicyCreateRequest, now: datetime) -> dict[str, Any]:
    return {
        "id": str(uuid.uuid4()),
        "name": body.name,
        "description": body.description,
        "resource_types": body.resource_types or [],
        "conditions": body.conditions or {"tags": []},
        "ttl_days": body.ttl_days,
        "warning_days_before": body.warning_days,
        "actions": [
            {"action": "warn", "trigger": "warning_threshold"},
            {"action": "delete", "trigger": "grace_period_end", "require_confirmation": True},
        ],
        "priority": body.priority,
        "enabled": body.enabled,
        "auto_apply": body.auto_apply if body.auto_apply is not None else True,
        "require_confirmation": True,
        "max_deletions_per_day": 0,
        "exclude_patterns": body.exclude_patterns,
        "warning_schedule": body.warning_schedule or [7, 3, 1],
        "grace_period_days": body.grace_period_days if body.grace_period_days is not None else 7,
        "auto_delete_enabled": False,
        "created_at": now.isoformat(),
        "updated_at": now.isoformat(),
    }


def _policy_map() -> dict[str, str]:
    return {str(policy.get("id")): policy.get("name") or "" for policy in _all_core_policies() if policy.get("id")}


def _policy_resource_count(resources: list[dict[str, Any]], policy_id: Any) -> int:
    return sum(1 for resource in resources if str(resource.get("lifecycle_policy_id")) == str(policy_id))


def _matched_core_resources(policy_payload: dict[str, Any]) -> list[dict[str, Any]]:
    matched = []
    for resource in _all_core_resources():
        try:
            if _policy_matches_resource(policy_payload, resource):
                matched.append(resource)
        except Exception:
            continue
    return matched


async def _apply_policy_to_matching_resources(policy: dict[str, Any], now: datetime) -> tuple[int, int]:
    matched = _matched_core_resources(policy)
    ttl_applied = 0
    tagged_resources = []
    new_expires = now + timedelta(days=policy.get("ttl_days") or 30)
    for resource in matched:
        resource["lifecycle_policy_id"] = policy["id"]
        if policy.get("auto_apply") and not resource.get("expires_at"):
            resource["expires_at"] = new_expires.isoformat()
            resource["lifecycle_state"] = "active"
            resource["ttl_source"] = "policy"
            ttl_applied += 1
            tagged_resources.append(resource)
            _create_core_audit(
                resource_arn=resource.get("resource_arn"),
                resource_id=str(resource.get("id")),
                policy_id=policy["id"],
                operation="TTL_SET",
                old_state=None,
                new_state="active",
                old_expires_at=None,
                new_expires_at=new_expires.isoformat(),
                success=True,
                executed_by="web-policy-auto-apply",
                operation_details={"policy_id": policy["id"], "policy_name": policy.get("name"), "ttl_days": policy.get("ttl_days"), "via": "web"},
            )
        _update_core_resource(resource)
    if tagged_resources:
        await _apply_core_tags(tagged_resources, new_expires)
    return len(matched), ttl_applied


def _clear_policy_links(policy_id: str) -> None:
    for resource in _all_core_resources():
        if str(resource.get("lifecycle_policy_id")) == str(policy_id):
            resource["lifecycle_policy_id"] = None
            _update_core_resource(resource)


def _get_policy_or_404(policy_id: str) -> dict[str, Any]:
    try:
        return get_storage_payload("tag-manager", "resource-lifecycle-policies", policy_id)
    except CoreRuntimeError as exc:
        if "404" in str(exc):
            raise HTTPException(status_code=404, detail="Policy not found") from exc
        raise _core_unavailable(exc) from exc


def _select_core_resources(
    resource_ids: list[str] | None = None,
    resource_arns: list[str] | None = None,
    services: list[str] | None = None,
) -> list[dict[str, Any]]:
    resources = _all_core_resources()
    if resource_ids:
        wanted = set(resource_ids)
        resources = [resource for resource in resources if str(resource.get("id")) in wanted]
    elif resource_arns:
        wanted = set(resource_arns)
        resources = [resource for resource in resources if resource.get("resource_arn") in wanted]
    else:
        raise HTTPException(status_code=400, detail="Provide resource_ids or resource_arns")
    if services:
        allowed = set(services)
        resources = [resource for resource in resources if resource.get("service_name") in allowed]
    return resources


async def _set_resource_ttl(
    resources: list[dict[str, Any]],
    expires_at: datetime,
    *,
    apply_aws_tags: bool,
    verb: str = "TTL set",
) -> str:
    tag_ok = tag_fail = 0
    tag_errors: list[str] = []
    tagged_arns: list[str] = []
    if apply_aws_tags:
        tag_ok, tag_fail, tag_errors, tagged_arns = await _apply_core_tags(resources, expires_at)
    tag_value = expires_at.strftime("%Y-%m-%d")
    for resource in resources:
        resource["expires_at"] = expires_at.isoformat()
        resource["lifecycle_state"] = "active"
        resource["ttl_source"] = "manual"
        if resource.get("resource_arn") in tagged_arns:
            tags = _tags(resource)
            tags["bluearch:ttl"] = tag_value
            resource["current_tags"] = tags
        _update_core_resource(resource)
    parts = [f"{verb} (expires {expires_at.strftime('%Y-%m-%d')})"]
    if tag_ok:
        parts.append(f"AWS tags applied to {tag_ok} resource(s)")
    if tag_fail:
        parts.append(f"AWS tagging FAILED on {tag_fail} resource(s): {'; '.join(tag_errors[:3])}")
    detail = ". ".join(parts)
    if tag_fail and tag_ok == 0:
        raise HTTPException(status_code=502, detail=detail)
    return detail


async def _apply_core_tags(resources: list[dict[str, Any]], expires_at: datetime) -> tuple[int, int, list[str], list[str]]:
    if not resources:
        return 0, 0, [], []
    tag_value = expires_at.strftime("%Y-%m-%d")

    def _sync_tag():
        from ...commands.unified_tags import _apply_tags_to_aws_resource

        ok = 0
        fail = 0
        errors = []
        ok_arns = []
        for resource in resources:
            arn = resource.get("resource_arn")
            if not arn:
                continue
            try:
                result = _apply_tags_to_aws_resource(arn, {"bluearch:ttl": tag_value}, resource.get("service_name"))
                if result:
                    ok += 1
                    ok_arns.append(arn)
                else:
                    fail += 1
                    errors.append(f"{arn}: tagging returned false")
            except Exception as exc:
                fail += 1
                errors.append(f"{arn}: {exc}")
                logger.warning("Failed to tag %s: %s", arn, exc)
        return ok, fail, errors, ok_arns

    return await asyncio.to_thread(_sync_tag)


def _review_update(
    resources: list[dict[str, Any]],
    decision_type: str,
    operation: str,
    reason: str | None,
    new_expires: datetime | None = None,
    extension_days: int | None = None,
    protect: bool | None = None,
    new_state: str | None = None,
) -> None:
    now = datetime.now(timezone.utc)
    user = _get_current_user()
    for resource in resources:
        old_state = resource.get("lifecycle_state")
        old_expires = resource.get("expires_at")
        effective_state = new_state or old_state
        if new_expires is not None:
            resource["expires_at"] = new_expires.isoformat()
            resource["lifecycle_state"] = "active"
            resource["ttl_source"] = "manual"
            effective_state = "active"
        if protect is not None:
            resource["protected"] = protect
        if new_state:
            resource["lifecycle_state"] = new_state
        _update_core_resource(resource)
        _create_core_decision(
            resource_arn=resource.get("resource_arn"),
            resource_id=str(resource.get("id")),
            decision_type=decision_type,
            decision_reason=reason,
            previous_state=old_state,
            new_state=effective_state,
            previous_expires_at=old_expires,
            new_expires_at=new_expires.isoformat() if new_expires else None,
            extension_days=extension_days,
            protection_reason=reason if protect else None,
            decided_by=user,
            decided_via="web",
            executed=True,
            executed_at=now.isoformat(),
        )
        _create_core_audit(
            resource_arn=resource.get("resource_arn"),
            resource_id=str(resource.get("id")),
            operation=operation,
            old_state=old_state,
            new_state=effective_state,
            old_expires_at=old_expires,
            new_expires_at=new_expires.isoformat() if new_expires else None,
            success=True,
            executed_by=user,
            operation_details={"days": extension_days, "reason": reason, "via": "web"},
        )


def _filter_review_rows(
    rows: list[dict[str, Any]],
    now: datetime,
    days: int | None,
    services: str | None,
    include_active: bool,
    lifecycle_state: str | None,
    account_id: str | None,
) -> list[dict[str, Any]]:
    if lifecycle_state:
        if lifecycle_state == "expired":
            rows = [r for r in rows if _is_expired(r, now)]
        elif lifecycle_state == "expiring":
            rows = [r for r in rows if _is_expiring(r, now, days or 7)]
        else:
            rows = [r for r in rows if r.get("lifecycle_state") == lifecycle_state]
    elif not include_active:
        if days is not None:
            cutoff = now + timedelta(days=days)
            rows = [r for r in rows if (exp := _parse_dt(r.get("expires_at"))) is not None and exp <= cutoff]
        else:
            rows = [r for r in rows if r.get("expires_at")]
    if services:
        svc_list = {s.strip() for s in services.split(",") if s.strip()}
        rows = [r for r in rows if r.get("service_name") in svc_list]
    if account_id:
        rows = [r for r in rows if r.get("account_id") == account_id]
    return rows


def _matched_item(resource: dict[str, Any]) -> MatchedResourceItem:
    return MatchedResourceItem(
        id=str(resource.get("id")),
        resource_arn=resource.get("resource_arn") or "",
        resource_type=resource.get("resource_type") or "",
        service_name=resource.get("service_name") or "",
        region=resource.get("region") or "",
        account_id=resource.get("account_id") or "",
        has_ttl=resource.get("expires_at") is not None,
    )


def _expiring_response(resource: dict[str, Any], policy_names: dict[str, str], now: datetime) -> ExpiringResourceResponse:
    expires_at = _parse_dt(resource.get("expires_at"))
    days_left = (expires_at - now).days if expires_at else None
    policy_id = str(resource.get("lifecycle_policy_id")) if resource.get("lifecycle_policy_id") else None
    return ExpiringResourceResponse(
        id=str(resource.get("id")),
        resource_arn=resource.get("resource_arn") or "",
        resource_type=resource.get("resource_type") or "",
        service_name=resource.get("service_name") or "",
        region=resource.get("region") or "",
        account_id=resource.get("account_id") or "",
        expires_at=expires_at.isoformat() if expires_at else None,
        lifecycle_state=resource.get("lifecycle_state"),
        protected=resource.get("protected") or False,
        owner_email=resource.get("owner_email"),
        days_until_expiry=days_left,
        policy_id=policy_id,
        policy_name=policy_names.get(policy_id) if policy_id else None,
    )


def _review_resource_response(resource: dict[str, Any], policy_names: dict[str, str], now: datetime) -> ReviewResourceResponse:
    expiring = _expiring_response(resource, policy_names, now)
    policy_id = expiring.policy_id
    return ReviewResourceResponse(
        **expiring.model_dump() if hasattr(expiring, "model_dump") else expiring.dict(),
        current_tags=_tags(resource),
        lifecycle_policy_id=policy_id,
    )


def _audit_response(audit: dict[str, Any]) -> AuditLogResponse:
    return AuditLogResponse(
        id=str(audit.get("id")),
        resource_arn=audit.get("resource_arn") or "",
        resource_id=str(audit.get("resource_id")) if audit.get("resource_id") else None,
        operation=audit.get("operation") or "",
        old_state=audit.get("old_state"),
        new_state=audit.get("new_state"),
        old_expires_at=_iso(audit.get("old_expires_at")),
        new_expires_at=_iso(audit.get("new_expires_at")),
        success=bool(audit.get("success")),
        error_message=audit.get("error_message"),
        executed_by=audit.get("executed_by"),
        executed_at=_iso(audit.get("executed_at")),
        operation_details=audit.get("operation_details"),
    )


def _tags(resource: dict[str, Any]) -> dict[str, str]:
    tags = resource.get("current_tags") or {}
    if isinstance(tags, str):
        try:
            tags = json_mod.loads(tags)
        except Exception:
            tags = {}
    return tags if isinstance(tags, dict) else {}


def _update_core_resource(resource: dict[str, Any]) -> None:
    update_storage_payload("core", "resources", str(resource["id"]), resource)


def _create_core_audit(**payload) -> None:
    payload.setdefault("id", str(uuid.uuid4()))
    payload.setdefault("executed_at", datetime.now(timezone.utc).isoformat())
    create_storage_payload("tag-manager", "lifecycle-audit-log", payload)


def _create_core_decision(**payload) -> None:
    payload.setdefault("id", str(uuid.uuid4()))
    payload.setdefault("decided_at", datetime.now(timezone.utc).isoformat())
    create_storage_payload("tag-manager", "lifecycle-decisions", payload)


def _get_current_user() -> str:
    import getpass
    import os

    return os.environ.get("USER", getpass.getuser())


def _core_unavailable(exc: Exception) -> HTTPException:
    return HTTPException(status_code=502, detail=f"bluearch-core lifecycle storage unavailable: {exc}")
