"""Pydantic schemas for multi-account management endpoints."""

from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class StackInstanceInfo(BaseModel):
    """Info about a single StackSet instance (one account+region)."""

    account_id: str
    region: str
    status: str  # CURRENT, OUTDATED, INOPERABLE, etc.
    status_reason: Optional[str] = None


class StackSetStatusResponse(BaseModel):
    """StackSet deployment status."""

    exists: bool
    status: Optional[str] = None  # ACTIVE, FAILED, etc.
    status_reason: Optional[str] = None
    template_version: Optional[str] = None
    versions_match: Optional[bool] = None
    local_version: Optional[str] = None
    instance_count: int = 0
    instances: List[StackInstanceInfo] = []


class AccountRecord(BaseModel):
    """An account tracked in the local database."""

    account_id: str
    account_name: Optional[str] = None
    role_arn: Optional[str] = None
    enabled_for_discovery: bool = False
    access_check_status: Optional[str] = None
    last_discovery_at: Optional[str] = None
    total_resources_discovered: Optional[int] = None


class AccountsListResponse(BaseModel):
    """List of tracked accounts."""

    accounts: List[AccountRecord]
    total: int


class DeployRequest(BaseModel):
    """Request to deploy/create StackSet infrastructure."""

    accounts: Optional[List[str]] = Field(
        None, description="Specific account IDs to deploy to. None = entire org."
    )
    regions: Optional[List[str]] = Field(
        None, description="Regions to deploy into. None = current region."
    )
    force_recreate: bool = Field(
        False, description="Delete and recreate StackSet (--clean behavior)."
    )


class AccountValidationResponse(BaseModel):
    """Pre-flight validation for multi-account deployment."""

    is_management_account: bool = False
    is_delegated_admin: bool = False
    can_deploy: bool = False
    current_account_id: Optional[str] = None
    management_account_id: Optional[str] = None
    organization_id: Optional[str] = None
    error: Optional[str] = None
    guidance: Optional[str] = None
