"""Pydantic schemas for account context and permission endpoints."""

from typing import Dict, List, Optional
from pydantic import BaseModel, Field


class AccountContextResponse(BaseModel):
    """A single account context record."""

    id: str
    account_id: str
    account_alias: Optional[str] = None
    aws_profile: Optional[str] = None
    region: Optional[str] = None
    user_arn: Optional[str] = None
    is_current: bool = False
    created_at: Optional[str] = None
    last_used_at: Optional[str] = None


class AccountContextListResponse(BaseModel):
    """List of all known account contexts."""

    contexts: List[AccountContextResponse]
    current_account_id: Optional[str] = None


class AddContextRequest(BaseModel):
    """Request to register a new account context from the active AWS session."""

    alias: Optional[str] = Field(None, description="Friendly name for this account")


class SwitchContextRequest(BaseModel):
    """Request to switch the active account context."""

    account_id: str = Field(..., description="Target account ID to switch to")


class ContextGateResponse(BaseModel):
    """Gate check result indicating whether the dashboard can proceed."""

    status: str  # "ok", "first_run", "switch_required", "add_required"
    message: str
    context: Optional[AccountContextResponse] = None


class ServicePermissionStatus(BaseModel):
    """Permission status for a single AWS service."""

    available: bool
    missing: List[str] = []


class FeatureStatus(BaseModel):
    """Availability status for a dashboard feature."""

    available: bool
    partial: bool = False
    missing: List[str] = []
    services: Optional[Dict[str, ServicePermissionStatus]] = None
    note: Optional[str] = None


class PermissionStatusResponse(BaseModel):
    """Full permission tier and feature availability for an account."""

    account_id: str
    tier: str
    checked_at: Optional[str] = None
    expires_at: Optional[str] = None
    features: Dict[str, FeatureStatus]
