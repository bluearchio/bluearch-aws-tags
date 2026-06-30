"""Pydantic schemas for resource graph / relationship map API."""

from typing import Any, Dict, List, Optional

from pydantic import BaseModel


class GraphNodeResponse(BaseModel):
    id: str
    resource_id: str
    resource_type: str
    service_name: str
    region: str
    account_id: str
    name: Optional[str] = None
    lifecycle_state: Optional[str] = None
    expires_at: Optional[str] = None
    protected: Optional[bool] = None
    compliance_status: Optional[str] = None
    missing_tags: Optional[List[str]] = None
    category: int
    symbol_size: int


class GraphEdgeResponse(BaseModel):
    source: str
    target: str
    relationship_type: str
    label: Optional[str] = None


class GraphResponse(BaseModel):
    nodes: List[GraphNodeResponse]
    edges: List[GraphEdgeResponse]
    categories: List[Dict[str, str]]
    total_relationships: int
    truncated: bool


class GraphStatsResponse(BaseModel):
    total_relationships: int
    by_type: Dict[str, int]
    most_connected: List[Dict[str, Any]]


class GraphFiltersResponse(BaseModel):
    vpc_ids: List[str]
    regions: List[str]
    account_ids: List[str]
    services: List[str]
    relationship_types: List[str]


class BlastRadiusTarget(BaseModel):
    arn: str
    name: str
    service: str
    resource_type: str


class BlastRadiusAffected(BaseModel):
    arn: str
    name: str
    service: str
    resource_type: str
    impact: str
    relationship: str
    depth: int
    lifecycle_state: Optional[str] = None
    protected: bool = False


class BlastRadiusDependency(BaseModel):
    arn: str
    name: str
    service: str
    resource_type: str
    relationship: str


class BlastRadiusSummary(BaseModel):
    total_affected: int
    orphaned: int
    disconnected: int
    cascade: int
    protected_affected: int


class BlastRadiusResponse(BaseModel):
    target: BlastRadiusTarget
    affected: List[BlastRadiusAffected]
    summary: BlastRadiusSummary
    dependencies: List[BlastRadiusDependency]
    truncated: bool
