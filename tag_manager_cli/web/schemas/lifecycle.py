"""Pydantic schemas for lifecycle endpoints."""

from typing import Any, Dict, List, Optional, Union
from pydantic import BaseModel, Field


class LifecycleDashboardResponse(BaseModel):
    """Lifecycle dashboard summary."""

    total_resources: int
    active: int
    warned: int
    marked_for_deletion: int
    protected: int
    expired: int
    expiring_7d: int
    expiring_30d: int
    tagged: int
    policies_count: int


class ExpiringResourceResponse(BaseModel):
    """Resource that is expiring soon."""

    id: str
    resource_arn: str
    resource_type: str
    service_name: str
    region: str
    account_id: str
    expires_at: Optional[str] = None
    lifecycle_state: Optional[str] = None
    protected: bool = False
    owner_email: Optional[str] = None
    days_until_expiry: Optional[int] = None
    policy_id: Optional[str] = None
    policy_name: Optional[str] = None


class PolicyResponse(BaseModel):
    """Lifecycle policy response."""

    id: str
    name: str
    description: Optional[str] = None
    resource_types: Optional[List[str]] = None
    regions: Optional[List[str]] = None
    account_ids: Optional[List[str]] = None
    default_ttl_days: Optional[int] = None
    warning_days: Optional[int] = None
    enabled: bool = True
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    resource_count: Optional[int] = None
    conditions: Optional[Union[Dict[str, Any], List[Any]]] = None
    exclude_patterns: Optional[Union[Dict[str, Any], List[Any]]] = None
    warning_schedule: Optional[List[int]] = None
    grace_period_days: Optional[int] = None
    auto_apply: Optional[bool] = None


# --- Mutation request/response schemas ---


class TagCondition(BaseModel):
    """A tag-based condition for policy matching."""

    field: str = Field(description="Tag field, e.g. 'tags.Environment'")
    operator: str = Field(
        default="equals",
        description="Operator: equals, not_equals, contains, exists, not_exists",
    )
    value: Optional[str] = Field(None, description="Value to compare against")


class PolicyCreateRequest(BaseModel):
    """Create a new lifecycle policy."""

    name: str = Field(min_length=1, max_length=255)
    description: Optional[str] = None
    resource_types: Optional[List[str]] = None
    regions: Optional[List[str]] = None
    account_ids: Optional[List[str]] = None
    ttl_days: int = Field(ge=1, le=3650)
    warning_days: int = Field(default=7, ge=0, le=365)
    priority: int = Field(default=100, ge=1, le=10000)
    enabled: bool = True
    # Advanced fields matching CLI wizard
    conditions: Optional[Dict[str, Any]] = Field(
        None, description="Tag conditions for policy matching, e.g. {'tags': [...]}"
    )
    exclude_patterns: Optional[Dict[str, Any]] = Field(
        None,
        description="Exclusion patterns: {'resource_names': [...], 'tags': [...]}",
    )
    warning_schedule: Optional[List[int]] = Field(
        None, description="Warning schedule in days before expiry, e.g. [7, 3, 1]"
    )
    grace_period_days: Optional[int] = Field(
        None, ge=0, le=365, description="Grace period after expiry before deletion"
    )
    auto_apply: Optional[bool] = Field(
        None, description="Auto-apply to matching resources"
    )


class PolicyUpdateRequest(BaseModel):
    """Partial update for a lifecycle policy."""

    name: Optional[str] = Field(None, min_length=1, max_length=255)
    description: Optional[str] = None
    resource_types: Optional[List[str]] = None
    regions: Optional[List[str]] = None
    account_ids: Optional[List[str]] = None
    ttl_days: Optional[int] = Field(None, ge=1, le=3650)
    warning_days: Optional[int] = Field(None, ge=0, le=365)
    priority: Optional[int] = Field(None, ge=1, le=10000)
    enabled: Optional[bool] = None
    conditions: Optional[Dict[str, Any]] = None
    exclude_patterns: Optional[Dict[str, Any]] = None
    warning_schedule: Optional[List[int]] = None
    grace_period_days: Optional[int] = Field(None, ge=0, le=365)
    auto_apply: Optional[bool] = None


class SetTTLRequest(BaseModel):
    """Set TTL on resources."""

    resource_ids: Optional[List[str]] = Field(
        None, description="Specific resource IDs (db ids)"
    )
    resource_arns: Optional[List[str]] = Field(
        None, description="Specific resource ARNs"
    )
    services: Optional[List[str]] = Field(
        None, description="Filter by services"
    )
    ttl_days: int = Field(ge=1, le=3650)
    apply_aws_tags: bool = Field(
        default=True, description="Also apply TTL tag to AWS resources"
    )


class ExtendTTLRequest(BaseModel):
    """Extend TTL on resources."""

    resource_ids: Optional[List[str]] = Field(
        None, description="Specific resource IDs (db ids)"
    )
    resource_arns: Optional[List[str]] = Field(
        None, description="Specific resource ARNs"
    )
    days: int = Field(default=7, ge=1, le=3650, description="Days to extend")
    apply_aws_tags: bool = Field(
        default=True, description="Also update TTL tag on AWS resources"
    )


class ProtectRequest(BaseModel):
    """Toggle resource protection."""

    resource_ids: Optional[List[str]] = Field(
        None, description="Specific resource IDs (db ids)"
    )
    resource_arns: Optional[List[str]] = Field(
        None, description="Specific resource ARNs"
    )
    protect: bool = Field(default=True, description="True to protect, False to unprotect")


class TTLPreviewItem(BaseModel):
    """Preview of a TTL operation on a single resource."""

    resource_id: str
    resource_arn: str
    service_name: str
    region: str
    account_id: str
    current_expires_at: Optional[str] = None
    new_expires_at: str
    tag_key: str = "bluearch:ttl"
    tag_value: str


class TTLPreviewResponse(BaseModel):
    """Preview of a TTL operation before confirmation."""

    resources: List[TTLPreviewItem]
    total_count: int
    ttl_days: int
    apply_aws_tags: bool


class MutationResultResponse(BaseModel):
    """Result of a mutation operation."""

    affected_count: int
    details: Optional[str] = None


# --- Review & Audit schemas ---


class ReviewResourceResponse(BaseModel):
    """Resource in review list with additional context."""
    id: str
    resource_arn: str
    resource_type: str
    service_name: str
    region: str
    account_id: str
    expires_at: Optional[str] = None
    lifecycle_state: Optional[str] = None
    protected: bool = False
    owner_email: Optional[str] = None
    days_until_expiry: Optional[int] = None
    current_tags: Optional[Dict[str, str]] = None
    lifecycle_policy_id: Optional[str] = None
    policy_id: Optional[str] = None
    policy_name: Optional[str] = None


class ReviewActionRequest(BaseModel):
    """Request for a review action (extend/protect/mark-delete)."""
    resource_ids: List[str] = Field(min_length=1)
    days: Optional[int] = Field(None, ge=1, le=3650, description="Days to extend")
    reason: Optional[str] = None


class ExecuteDeleteRequest(BaseModel):
    """Execute AWS deletion of marked resources."""
    resource_ids: List[str] = Field(min_length=1)
    confirmation: str = Field(description="Must be 'DELETE' to confirm")


class AuditLogResponse(BaseModel):
    """Lifecycle audit log entry."""
    id: str
    resource_arn: str
    resource_id: Optional[str] = None
    operation: str
    old_state: Optional[str] = None
    new_state: Optional[str] = None
    old_expires_at: Optional[str] = None
    new_expires_at: Optional[str] = None
    success: bool
    error_message: Optional[str] = None
    executed_by: Optional[str] = None
    executed_at: Optional[str] = None
    operation_details: Optional[Dict[str, Any]] = None


# --- Match Preview schemas ---


class MatchPreviewRequest(BaseModel):
    """Preview which resources match given policy criteria."""

    resource_types: Optional[List[str]] = Field(
        None, description="Resource types to match (empty = all)"
    )
    conditions: Optional[Dict[str, Any]] = Field(
        None, description="Tag conditions, e.g. {'tags': [...]}"
    )
    exclude_patterns: Optional[Dict[str, Any]] = Field(
        None,
        description="Exclusion patterns: {'resource_names': [...], 'tags': [...]}",
    )


class MatchedResourceItem(BaseModel):
    """A resource matched by policy criteria."""

    id: str
    resource_arn: str
    resource_type: str
    service_name: str
    region: str
    account_id: str
    has_ttl: bool = False


class MatchPreviewResponse(BaseModel):
    """Result of a match preview."""

    matched_count: int
    resources: List[MatchedResourceItem] = Field(
        default_factory=list, description="First N matched resources"
    )


class PolicySaveResult(BaseModel):
    """Enriched result returned after creating/updating a policy."""

    policy: PolicyResponse
    matched_count: int = 0
    ttl_applied_count: int = 0
