"""Pydantic schemas for cost analytics endpoints."""

from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class CostSummaryResponse(BaseModel):
    """Cost summary for a date range."""

    total_cost: float
    currency: str = "USD"
    start_date: str
    end_date: str
    source: str
    by_service: Optional[List[Dict[str, Any]]] = None


class CostByServiceResponse(BaseModel):
    """Cost breakdown by service."""

    items: List[Dict[str, Any]]
    total_cost: float
    currency: str = "USD"
    start_date: str
    end_date: str
    source: str


class CostByAccountResponse(BaseModel):
    """Cost breakdown by account."""

    items: List[Dict[str, Any]]
    total_cost: float
    currency: str = "USD"
    start_date: str
    end_date: str
    source: str


class CostCompareRequest(BaseModel):
    """Request to compare costs between two periods."""

    period1_start: str = Field(description="Start date for period 1 (YYYY-MM-DD)")
    period1_end: str = Field(description="End date for period 1 (YYYY-MM-DD)")
    period2_start: str = Field(description="Start date for period 2 (YYYY-MM-DD)")
    period2_end: str = Field(description="End date for period 2 (YYYY-MM-DD)")


class CostCompareResponse(BaseModel):
    """Cost comparison between two periods."""

    period1: Dict[str, Any]
    period2: Dict[str, Any]
    change_absolute: float
    change_percent: Optional[float] = None


class CostForecastRequest(BaseModel):
    """Request for cost forecast."""

    days: int = Field(30, ge=1, le=365, description="Days to forecast")
    method: str = Field(
        "average", description="Forecast method: average, linear, weighted"
    )


class CostForecastResponse(BaseModel):
    """Cost forecast result."""

    forecast_days: int
    method: str
    projected_cost: float
    currency: str = "USD"
    daily_average: float
    based_on_days: int
    source: str


class CURStatusResponse(BaseModel):
    """CUR detection status."""

    found: bool
    status: Optional[str] = None  # active, pending, setup_pending
    report_name: Optional[str] = None
    s3_bucket: Optional[str] = None
    athena_database: Optional[str] = None
    athena_table: Optional[str] = None
    region: Optional[str] = None
    message: str = ""


class CURDeployRequest(BaseModel):
    """Request to deploy CUR infrastructure."""

    bucket_name: Optional[str] = Field(
        None, description="S3 bucket name. Auto-generated if not provided."
    )
    report_name: str = Field(
        "tag-manager-cur", description="CUR report name"
    )


class CURDeployResponse(BaseModel):
    """CUR deployment result."""

    success: bool
    job_id: Optional[str] = None
    stack_id: Optional[str] = None
    message: str = ""
    estimated_ready_hours: int = 24


class CURValidateRequest(BaseModel):
    """Request to validate manual CUR configuration."""

    database: str = Field(description="Athena/Glue database name")
    table: str = Field(description="Athena/Glue table name")


# --- CUR-specific endpoint schemas ---


class CostRegionsResponse(BaseModel):
    """Cost breakdown by region."""

    items: List[Dict[str, Any]]
    total_cost: float
    currency: str = "USD"
    start_date: str
    end_date: str
    source: str


class CostDailyResponse(BaseModel):
    """Daily cost summary."""

    items: List[Dict[str, Any]]
    total_cost: float
    currency: str = "USD"
    start_date: str
    end_date: str
    source: str


class CostTopResourcesResponse(BaseModel):
    """Top cost resources."""

    items: List[Dict[str, Any]]
    total_cost: float
    currency: str = "USD"
    start_date: str
    end_date: str
    source: str


class CostDataTransferResponse(BaseModel):
    """Data transfer costs."""

    items: List[Dict[str, Any]]
    total_cost: float
    currency: str = "USD"
    start_date: str
    end_date: str
    source: str


class CostSavingsPlansResponse(BaseModel):
    """Savings Plans coverage."""

    items: List[Dict[str, Any]]
    source: str


class CostReservationsResponse(BaseModel):
    """Reserved Instance utilization."""

    items: List[Dict[str, Any]]
    source: str


class CostServiceDeepDiveResponse(BaseModel):
    """Service-specific cost deep-dive."""

    service: str
    view: str
    items: List[Dict[str, Any]]
    total_cost: Optional[float] = None
    currency: str = "USD"
    start_date: str
    end_date: str
    source: str


# --- Analysis endpoint schemas ---


class CostTrendsRequest(BaseModel):
    """Request for trend analysis."""

    tag_key: str = Field(description="Tag key to analyze")
    periods: int = Field(default=6, ge=2, le=24)
    granularity: str = Field(default="monthly", description="monthly or weekly")
    tag_value: Optional[str] = None


class CostTrendsResponse(BaseModel):
    """Trend analysis result."""

    tag_key: str
    trends: List[Dict[str, Any]]
    summary: Optional[Dict[str, Any]] = None
    source: str


class CostAnomaliesRequest(BaseModel):
    """Request for anomaly detection."""

    tag_key: str = Field(description="Tag key to analyze")
    percent_threshold: float = Field(default=30.0, ge=1.0, le=500.0)
    absolute_threshold: float = Field(default=100.0, ge=0.0)


class CostAnomaliesResponse(BaseModel):
    """Anomaly detection result."""

    tag_key: str
    anomalies: List[Dict[str, Any]]
    total_anomalies: int
    source: str


class CostChargebackRequest(BaseModel):
    """Request for chargeback report."""

    tag_key: str = Field(description="Tag key to group by")
    start_date: str = Field(description="Start date YYYY-MM-DD")
    end_date: str = Field(description="End date YYYY-MM-DD")
    granularity: str = Field(default="monthly")
    group_by: Optional[str] = None


class CostChargebackResponse(BaseModel):
    """Chargeback report result."""

    tag_key: str
    report: Dict[str, Any]
    source: str


class CostGapsRequest(BaseModel):
    """Request for visibility gap analysis."""

    required_tags: List[str] = Field(description="Required tag keys")
    days: int = Field(default=30, ge=1, le=365)
    min_cost: float = Field(default=0.0, ge=0.0)
    show_roi: bool = Field(default=False)


class CostGapsResponse(BaseModel):
    """Visibility gap analysis result."""

    gaps: Dict[str, Any]
    source: str
