"""Data classes for the collection engine."""

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any


@dataclass
class CollectionJob:
    """Represents a single collection job (service + region)."""
    service: str
    region: Optional[str]  # None for global services (S3)
    priority: int
    is_global: bool
    account_id: Optional[str] = None
    session: Any = None  # boto3.Session for cross-account


@dataclass
class CollectorResult:
    """Result from a single service collector run."""
    resources: List[Dict[str, Any]] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    permission_errors: int = 0
    permission_error_details: List[Dict[str, Any]] = field(default_factory=list)
    relationships: List[Dict[str, Any]] = field(default_factory=list)


@dataclass
class CollectionResult:
    """Aggregated result from a full collection run."""
    total_resources: int
    total_errors: int
    permission_errors: int
    duration_seconds: float
    services_scanned: int
    regions_scanned: int
    by_service: Dict[str, int] = field(default_factory=dict)
    by_region: Dict[str, int] = field(default_factory=dict)
    errors: List[str] = field(default_factory=list)
    permission_error_details: List[Dict[str, Any]] = field(default_factory=list)
    permission_error_resource_types: List[str] = field(default_factory=list)
    compliance: Optional[Dict[str, Any]] = None

    def to_summary_dict(self) -> Dict[str, Any]:
        """Return dict matching discover_all_resources_with_tree() format."""
        return {
            'total_resources_discovered': self.total_resources,
            'errors': self.errors,
            'permission_errors': self.permission_errors,
            'permission_error_details': self.permission_error_details,
            'permission_error_resource_types': self.permission_error_resource_types,
            'compliance': self.compliance,
            'services_scanned': self.services_scanned,
            'regions_scanned': self.regions_scanned,
            'duration_seconds': self.duration_seconds,
            'by_service': self.by_service,
            'by_region': self.by_region,
        }
