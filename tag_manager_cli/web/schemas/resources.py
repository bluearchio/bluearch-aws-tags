"""Pydantic schemas for resource endpoints."""

from typing import Any, Dict, List, Optional
from datetime import datetime
from pydantic import BaseModel


class ResourceResponse(BaseModel):
    """Single resource response."""

    id: str
    resource_arn: str
    resource_type: str
    service_name: str
    region: str
    account_id: str
    resource_id: str
    created_by: Optional[str] = None
    created_at: Optional[str] = None
    discovered_at: Optional[str] = None
    last_scanned_at: Optional[str] = None
    current_tags: Optional[Dict[str, Any]] = None
    metadata: Optional[Dict[str, Any]] = None
    expires_at: Optional[str] = None
    lifecycle_state: Optional[str] = None
    delete_after: Optional[str] = None
    protected: Optional[bool] = None
    compliance_status: Optional[str] = None

    model_config = {"from_attributes": True}


class ResourceStatsResponse(BaseModel):
    """Resource statistics breakdown."""

    total_resources: int
    by_service: Dict[str, int]
    by_region: Dict[str, int]
    by_account: Dict[str, int]
    by_lifecycle_state: Dict[str, int]
    by_resource_type: Dict[str, int]
    by_compliance_status: Dict[str, int]
