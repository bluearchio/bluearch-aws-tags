"""Pydantic schemas for tag policy compliance endpoints."""

from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class ComplianceAccessResponse(BaseModel):
    """AWS Organizations access check."""

    has_access: bool
    org_id: Optional[str] = None
    master_account: Optional[str] = None
    current_account: Optional[str] = None
    tag_policies_enabled: Optional[bool] = None
    error: Optional[str] = None


class OrgPolicyResponse(BaseModel):
    """AWS Organizations tag policy."""

    id: str
    name: str
    description: Optional[str] = None
    arn: Optional[str] = None
    type: Optional[str] = None
    aws_managed: Optional[bool] = None


class NonCompliantResourceResponse(BaseModel):
    """Non-compliant resource from AWS Organizations check."""

    resource_arn: Optional[str] = None
    resource_type: Optional[str] = None
    region: Optional[str] = None
    account_id: Optional[str] = None
    keys_with_noncompliant_values: Optional[List[str]] = None
    missing_tags: Optional[List[str]] = None


class ComplianceCheckResponse(BaseModel):
    """Compliance check result."""

    success: bool
    resources: List[NonCompliantResourceResponse]
    count: int
    has_more: bool = False
    error: Optional[str] = None


class EffectivePolicyResponse(BaseModel):
    """Effective tag policy for an account."""

    target_id: str
    content: Optional[Dict[str, Any]] = None
    error: Optional[str] = None


class OrgPolicyCreateRequest(BaseModel):
    """Request to create an AWS Organizations tag policy."""
    name: str = Field(min_length=1, max_length=255)
    description: Optional[str] = None
    content: Dict[str, Any] = Field(description="Tag policy JSON content")


class OrgPolicyUpdateRequest(BaseModel):
    """Request to update an AWS Organizations tag policy."""
    name: Optional[str] = Field(None, min_length=1, max_length=255)
    description: Optional[str] = None
    content: Optional[Dict[str, Any]] = None


class PolicyAttachRequest(BaseModel):
    """Request to attach/detach a policy to/from a target."""
    target_id: str = Field(description="Root, OU, or Account ID")


class OrgPolicyDetailResponse(BaseModel):
    """Detailed AWS Organizations tag policy."""
    id: str
    name: str
    description: Optional[str] = None
    arn: Optional[str] = None
    content: Optional[Dict[str, Any]] = None
    targets: Optional[List[Dict[str, Any]]] = None
    aws_managed: Optional[bool] = None
    create_date: Optional[str] = None
    update_date: Optional[str] = None


class PolicyTargetsResponse(BaseModel):
    """Targets attached to a policy."""
    targets: List[Dict[str, Any]]
    count: int


class OrgStructureResponse(BaseModel):
    """Organization structure for target selection."""
    root_id: Optional[str] = None
    ous: List[Dict[str, Any]] = []
    accounts: List[Dict[str, Any]] = []


class OrgMutationResponse(BaseModel):
    """Result of an org policy mutation."""
    success: bool
    message: str
    error: Optional[str] = None
