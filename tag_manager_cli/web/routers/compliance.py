"""Tag policy compliance endpoints."""

import asyncio
import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from ..dependencies import get_current_user, require_role, LocalUser
from ...utils.event_hooks import track_event

logger = logging.getLogger(__name__)
from ..schemas.compliance import (
    ComplianceAccessResponse,
    ComplianceCheckResponse,
    EffectivePolicyResponse,
    NonCompliantResourceResponse,
    OrgMutationResponse,
    OrgPolicyCreateRequest,
    OrgPolicyDetailResponse,
    OrgPolicyResponse,
    OrgPolicyUpdateRequest,
    OrgStructureResponse,
    PolicyAttachRequest,
    PolicyTargetsResponse,
)

router = APIRouter(prefix="/api/v1/compliance", tags=["compliance"])


def _get_org_service_sync():
    """Create an OrganizationsService instance with proper session."""
    from ...services.organizations_service import OrganizationsService
    from ...utils.aws_auth import aws_auth

    session = aws_auth.initialize_session()
    return OrganizationsService(session=session)


@router.get("/access", response_model=ComplianceAccessResponse)
async def check_access(_user: LocalUser = Depends(get_current_user)):
    """Check AWS Organizations access and tag policies status."""

    def _check():
        svc = _get_org_service_sync()
        return svc.check_access()

    try:
        data = await asyncio.to_thread(_check)
    except Exception as exc:
        return ComplianceAccessResponse(
            has_access=False,
            error=str(exc),
        )

    return ComplianceAccessResponse(
        has_access=data.get("has_access", False),
        org_id=data.get("org_id"),
        master_account=data.get("master_account"),
        current_account=data.get("current_account"),
        tag_policies_enabled=data.get("tag_policies_enabled"),
    )


@router.get("/policies")
async def list_policies(
    detailed: bool = Query(False, description="Include policy content"),
    current_user: LocalUser = Depends(get_current_user),
):
    """List AWS Organizations tag policies."""

    def _fetch():
        svc = _get_org_service_sync()
        # First check if we have org access
        access = svc.check_access()
        if not access.get("has_access"):
            return {"error": access.get("error", "No Organizations access"), "items": []}
        if not access.get("tag_policies_enabled"):
            return {"error": "Tag policies are not enabled in this organization", "items": []}
        return {"items": svc.list_policies(detailed=detailed)}

    try:
        result = await asyncio.to_thread(_fetch)
    except Exception as exc:
        # Return empty list with error instead of 502
        return []

    if "error" in result:
        # Return empty list - the error will be shown via /access endpoint
        return []

    policies = result.get("items", [])
    items = []
    for p in policies:
        items.append(
            OrgPolicyResponse(
                id=p.get("Id", p.get("id", "")),
                name=p.get("Name", p.get("name", "")),
                description=p.get("Description", p.get("description")),
                arn=p.get("Arn", p.get("arn")),
                type=p.get("Type", p.get("type")),
                aws_managed=p.get("AwsManaged", p.get("aws_managed")),
            )
        )

    try:
        track_event(
            "web.compliance.list",
            properties={
                "user_sub": getattr(current_user, "sub", None),
                "count": len(items),
            },
        )
    except Exception:
        pass

    return items


@router.get("/check", response_model=ComplianceCheckResponse)
async def check_compliance(
    resource_type: Optional[str] = Query(None, description="Filter by resource type"),
    region: Optional[str] = Query(None, description="Filter by region"),
    tag_key: Optional[str] = Query(None, description="Filter by tag key"),
    max_results: int = Query(100, ge=1, le=500),
    _user: LocalUser = Depends(get_current_user),
):
    """Check non-compliant resources against AWS Organizations tag policies."""

    def _fetch():
        svc = _get_org_service_sync()
        resource_type_filters = [resource_type] if resource_type else None
        region_filters = [region] if region else None
        tag_key_filters = [tag_key] if tag_key else None

        return svc.get_noncompliant_resources(
            resource_type_filters=resource_type_filters,
            region_filters=region_filters,
            tag_key_filters=tag_key_filters,
            max_results=max_results,
        )

    try:
        data = await asyncio.to_thread(_fetch)
    except Exception as exc:
        exc_str = str(exc)
        # Detect access-denied errors and return a helpful message
        access_denied_keywords = (
            "AccessDenied",
            "ForbiddenException",
            "AWSOrganizationsNotInUseException",
            "is not authorized",
            "No Access",
        )
        if any(kw in exc_str for kw in access_denied_keywords):
            logger.info("Compliance check unavailable: %s", exc_str)
            return ComplianceCheckResponse(
                success=False,
                resources=[],
                count=0,
                error=(
                    "AWS Organizations access is not available. "
                    "Compliance checks require organizations:ListPolicies "
                    "and organizations:DescribeOrganization permissions."
                ),
            )
        return ComplianceCheckResponse(
            success=False,
            resources=[],
            count=0,
            error=exc_str,
        )

    resources = []
    for r in data.get("resources", []):
        # Extract account_id from ARN (arn:aws:service:region:account:...)
        arn = r.get("arn", r.get("ResourceArn", r.get("resource_arn")))
        account_id = r.get("account_id", r.get("AccountId"))
        if not account_id and arn and arn.startswith("arn:aws:"):
            parts = arn.split(":")
            account_id = parts[4] if len(parts) > 4 else None

        resources.append(
            NonCompliantResourceResponse(
                resource_arn=arn,
                resource_type=r.get("service", r.get("ResourceType", r.get("resource_type"))),
                region=r.get("region", r.get("Region")),
                account_id=account_id,
                keys_with_noncompliant_values=r.get(
                    "keys_with_noncompliant_values",
                    r.get("KeysWithNoncompliantValues", []),
                ),
                missing_tags=r.get("noncompliant_keys", r.get("MissingTags", r.get("missing_tags"))),
            )
        )

    return ComplianceCheckResponse(
        success=data.get("success", True),
        resources=resources,
        count=data.get("count", len(resources)),
        has_more=data.get("has_more", False),
    )


@router.get("/effective-policy", response_model=EffectivePolicyResponse)
async def effective_policy(
    target_id: Optional[str] = Query(None, description="Account or OU ID"),
    _user: LocalUser = Depends(get_current_user),
):
    """Get the effective tag policy for an account or OU."""

    def _fetch():
        svc = _get_org_service_sync()
        return svc.get_effective_policy(target_id=target_id)

    try:
        data = await asyncio.to_thread(_fetch)
    except Exception as exc:
        raise HTTPException(
            status_code=502, detail=f"Failed to get effective policy: {exc}"
        )

    return EffectivePolicyResponse(
        target_id=data.get("target_id", target_id or "current"),
        content=data.get("content"),
    )


# --- Policy CRUD endpoints ---


@router.post("/policies", response_model=OrgMutationResponse)
async def create_org_policy(body: OrgPolicyCreateRequest, _user: LocalUser = Depends(require_role(["admin", "operator"]))):
    """Create a new AWS Organizations tag policy."""

    def _create():
        svc = _get_org_service_sync()
        # Pass content as dict - the service handles json.dumps internally
        result = svc.create_policy(
            name=body.name,
            description=body.description or "",
            content=body.content,
        )
        return result

    try:
        result = await asyncio.to_thread(_create)
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Failed to create policy: {exc}",
        )

    # The service returns {'success': bool, 'error': str, ...} on failures
    if not result.get("success"):
        error_msg = result.get("error", "Unknown error")
        suggestion = result.get("suggestion", "")
        detail = f"{error_msg}. {suggestion}" if suggestion else error_msg
        raise HTTPException(status_code=400, detail=detail)

    return OrgMutationResponse(
        success=True,
        message=f"Policy '{body.name}' created successfully (ID: {result.get('policy_id', 'N/A')})",
    )


@router.get("/policies/{policy_id}", response_model=OrgPolicyDetailResponse)
async def get_policy_detail(policy_id: str, _user: LocalUser = Depends(get_current_user)):
    """Get detailed information about a specific tag policy."""

    def _fetch():
        svc = _get_org_service_sync()
        return svc.get_policy_details(policy_id)

    try:
        data = await asyncio.to_thread(_fetch)
    except Exception as exc:
        raise HTTPException(
            status_code=502, detail=f"Failed to get policy details: {exc}"
        )

    # The service may return either raw AWS format or normalized flat dict.
    # Handle both: check lowercase keys first (service), then AWS SDK keys.
    policy = data.get("Policy", data) if isinstance(data, dict) else data
    summary = policy.get("PolicySummary", policy) if isinstance(policy, dict) else {}

    # Content: service returns dict under 'content', AWS SDK returns JSON string under 'Content'
    content = summary.get("content", None) or summary.get("Content", None)
    if isinstance(content, str):
        import json
        try:
            content = json.loads(content)
        except (json.JSONDecodeError, TypeError):
            content = {"raw": content}

    # Targets: service includes 'targets' list with AWS SDK-cased keys
    raw_targets = summary.get("targets", summary.get("Targets", []))
    targets = []
    for t in (raw_targets or []):
        targets.append({
            "target_id": t.get("target_id", t.get("TargetId", "")),
            "arn": t.get("arn", t.get("Arn", "")),
            "name": t.get("name", t.get("Name", "")),
            "type": t.get("type", t.get("Type", "")),
        })

    return OrgPolicyDetailResponse(
        id=summary.get("id", summary.get("Id", policy_id)),
        name=summary.get("name", summary.get("Name", "")),
        description=summary.get("description", summary.get("Description")),
        arn=summary.get("arn", summary.get("Arn")),
        content=content,
        targets=targets,
        aws_managed=summary.get("aws_managed", summary.get("AwsManaged")),
    )


@router.patch("/policies/{policy_id}", response_model=OrgMutationResponse)
async def update_org_policy(policy_id: str, body: OrgPolicyUpdateRequest, _user: LocalUser = Depends(require_role(["admin", "operator"]))):
    """Update an AWS Organizations tag policy."""

    def _update():
        svc = _get_org_service_sync()
        kwargs = {"policy_id": policy_id}
        if body.name is not None:
            kwargs["name"] = body.name
        if body.description is not None:
            kwargs["description"] = body.description
        if body.content is not None:
            # Pass content as dict - the service handles json.dumps internally
            kwargs["content"] = body.content
        return svc.update_policy(**kwargs)

    try:
        result = await asyncio.to_thread(_update)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Failed to update policy: {exc}")

    if not result.get("success"):
        raise HTTPException(status_code=400, detail=result.get("error", "Update failed"))

    return OrgMutationResponse(success=True, message="Policy updated successfully")


@router.delete("/policies/{policy_id}", response_model=OrgMutationResponse)
async def delete_org_policy(policy_id: str, _user: LocalUser = Depends(require_role(["admin", "operator"]))):
    """Delete an AWS Organizations tag policy."""

    def _delete():
        svc = _get_org_service_sync()
        return svc.delete_policy(policy_id)

    try:
        result = await asyncio.to_thread(_delete)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Failed to delete policy: {exc}")

    if not result.get("success"):
        raise HTTPException(status_code=400, detail=result.get("error", "Delete failed"))

    return OrgMutationResponse(success=True, message="Policy deleted successfully")


@router.post("/policies/{policy_id}/attach", response_model=OrgMutationResponse)
async def attach_policy(policy_id: str, body: PolicyAttachRequest, _user: LocalUser = Depends(require_role(["admin", "operator"]))):
    """Attach a tag policy to an org target."""

    def _attach():
        svc = _get_org_service_sync()
        return svc.attach_policy(policy_id, body.target_id)

    try:
        await asyncio.to_thread(_attach)
    except Exception as exc:
        return OrgMutationResponse(
            success=False, message="Failed to attach policy", error=str(exc)
        )

    return OrgMutationResponse(
        success=True, message=f"Policy attached to {body.target_id}"
    )


@router.post("/policies/{policy_id}/detach", response_model=OrgMutationResponse)
async def detach_policy(policy_id: str, body: PolicyAttachRequest, _user: LocalUser = Depends(require_role(["admin", "operator"]))):
    """Detach a tag policy from an org target."""

    def _detach():
        svc = _get_org_service_sync()
        return svc.detach_policy(policy_id, body.target_id)

    try:
        await asyncio.to_thread(_detach)
    except Exception as exc:
        return OrgMutationResponse(
            success=False, message="Failed to detach policy", error=str(exc)
        )

    return OrgMutationResponse(
        success=True, message=f"Policy detached from {body.target_id}"
    )


@router.get("/policies/{policy_id}/targets", response_model=PolicyTargetsResponse)
async def list_policy_targets(policy_id: str, _user: LocalUser = Depends(get_current_user)):
    """List targets attached to a policy."""

    def _fetch():
        svc = _get_org_service_sync()
        return svc.list_targets_for_policy(policy_id)

    try:
        data = await asyncio.to_thread(_fetch)
    except Exception as exc:
        raise HTTPException(
            status_code=502, detail=f"Failed to list targets: {exc}"
        )

    targets = data if isinstance(data, list) else data.get("targets", data.get("Targets", []))
    return PolicyTargetsResponse(targets=targets, count=len(targets))


@router.post("/tag-policies/enable", response_model=OrgMutationResponse)
async def enable_tag_policies(_user: LocalUser = Depends(require_role(["admin", "operator"]))):
    """Enable tag policies in the organization."""

    def _enable():
        svc = _get_org_service_sync()
        return svc.enable_tag_policies()

    try:
        await asyncio.to_thread(_enable)
    except Exception as exc:
        return OrgMutationResponse(
            success=False, message="Failed to enable tag policies", error=str(exc)
        )

    return OrgMutationResponse(
        success=True, message="Tag policies enabled successfully"
    )


@router.post("/tag-policies/disable", response_model=OrgMutationResponse)
async def disable_tag_policies(_user: LocalUser = Depends(require_role(["admin", "operator"]))):
    """Disable tag policies in the organization."""

    def _disable():
        svc = _get_org_service_sync()
        return svc.disable_tag_policies()

    try:
        await asyncio.to_thread(_disable)
    except Exception as exc:
        return OrgMutationResponse(
            success=False, message="Failed to disable tag policies", error=str(exc)
        )

    return OrgMutationResponse(
        success=True, message="Tag policies disabled successfully"
    )


@router.get("/org-structure", response_model=OrgStructureResponse)
async def get_org_structure(_user: LocalUser = Depends(get_current_user)):
    """Get organization structure (root, OUs, accounts) for target selection."""

    def _fetch():
        svc = _get_org_service_sync()
        # Get root
        roots = []
        ous = []
        accounts = []
        try:
            org_client = svc.session.client("organizations")
            roots_resp = org_client.list_roots()
            roots = roots_resp.get("Roots", [])
            root_id = roots[0]["Id"] if roots else None

            if root_id:
                # Get OUs
                paginator = org_client.get_paginator("list_organizational_units_for_parent")
                for page in paginator.paginate(ParentId=root_id):
                    for ou in page.get("OrganizationalUnits", []):
                        ous.append({
                            "id": ou["Id"],
                            "name": ou["Name"],
                            "arn": ou.get("Arn", ""),
                        })

                # Get accounts
                paginator = org_client.get_paginator("list_accounts")
                for page in paginator.paginate():
                    for acct in page.get("Accounts", []):
                        accounts.append({
                            "id": acct["Id"],
                            "name": acct.get("Name", ""),
                            "email": acct.get("Email", ""),
                            "status": acct.get("Status", ""),
                        })

            return {
                "root_id": root_id,
                "ous": ous,
                "accounts": accounts,
            }
        except Exception:
            return {"root_id": None, "ous": [], "accounts": []}

    try:
        data = await asyncio.to_thread(_fetch)
    except Exception as exc:
        raise HTTPException(
            status_code=502, detail=f"Failed to get org structure: {exc}"
        )

    return OrgStructureResponse(**data)
