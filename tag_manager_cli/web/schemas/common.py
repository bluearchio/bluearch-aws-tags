"""Common Pydantic schemas for pagination and error responses."""

from typing import Any, Generic, List, Optional, TypeVar
from pydantic import BaseModel, Field

T = TypeVar("T")


class PaginationParams(BaseModel):
    """Query parameters for paginated endpoints."""

    limit: int = Field(default=50, ge=1, le=500)
    offset: int = Field(default=0, ge=0)


class PaginatedResponse(BaseModel, Generic[T]):
    """Paginated response wrapper."""

    items: List[T]
    total: int
    limit: int
    offset: int

    @property
    def has_more(self) -> bool:
        return self.offset + self.limit < self.total


class HealthResponse(BaseModel):
    """Health check response."""

    status: str
    database: str
    database_type: Optional[str] = None
    tables_exist: Optional[bool] = None
    resource_count: Optional[int] = None
    version: Optional[str] = None


class ErrorResponse(BaseModel):
    """Error response."""

    detail: str
    code: Optional[str] = None


class SetupCheckItem(BaseModel):
    """Individual setup validation check."""

    name: str
    status: str  # ok, warning, error
    message: str
    details: Optional[Any] = None


class SetupValidateResponse(BaseModel):
    """Full setup validation result."""

    overall: str  # healthy, degraded, unhealthy
    checks: List[SetupCheckItem]

