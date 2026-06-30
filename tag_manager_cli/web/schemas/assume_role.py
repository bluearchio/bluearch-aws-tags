"""Pydantic schemas for assume-role management endpoints."""

from typing import List, Optional
from pydantic import BaseModel, Field


class AssumeRoleStatusResponse(BaseModel):
    """Current assume-role configuration and stack status."""

    configured: bool = False
    enabled: bool = False
    role_arn: Optional[str] = None
    role_name: Optional[str] = None
    account_id: Optional[str] = None
    external_id_configured: bool = False
    last_used_at: Optional[str] = None
    stack_exists: bool = False
    stack_status: Optional[str] = None


class AssumeRoleConfigRecord(BaseModel):
    """A single assume-role configuration record."""

    id: str
    account_id: str
    role_arn: str
    role_name: str
    is_active: bool
    enabled: bool
    external_id_configured: bool = False
    last_used_at: Optional[str] = None
    created_at: Optional[str] = None


class AssumeRoleDeployRequest(BaseModel):
    """Request to deploy the assume-role CloudFormation stack."""

    trust_mode: str = Field(
        "AnyPrincipal",
        description="Trust policy mode: AnyPrincipal, CurrentUser, or SpecificArn",
    )
    specific_arn: Optional[str] = Field(
        None, description="IAM ARN when trust_mode is SpecificArn"
    )
    external_id: Optional[str] = Field(
        None, description="External ID for role assumption (auto-retrieved if not set)"
    )
    role_name: str = Field(
        "BlueArchCLIRole", description="Name of the IAM role to create"
    )


class AssumeRoleDisableRequest(BaseModel):
    """Request to disable assume-role configuration."""

    delete_stack: bool = Field(
        False, description="Also delete the CloudFormation stack"
    )
