"""Cost analytics endpoints."""

import asyncio
from datetime import date, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from ..dependencies import get_current_user, require_role, LocalUser
from ...utils.core_client import request_core
from ..schemas.cost import (
    CostByAccountResponse,
    CostByServiceResponse,
    CostCompareRequest,
    CostCompareResponse,
    CostForecastRequest,
    CostForecastResponse,
    CostSummaryResponse,
    CURDeployRequest,
    CURDeployResponse,
    CURStatusResponse,
    CURValidateRequest,
    CostRegionsResponse,
    CostDailyResponse,
    CostTopResourcesResponse,
    CostDataTransferResponse,
    CostSavingsPlansResponse,
    CostReservationsResponse,
    CostServiceDeepDiveResponse,
    CostTrendsRequest,
    CostTrendsResponse,
    CostAnomaliesRequest,
    CostAnomaliesResponse,
    CostChargebackRequest,
    CostChargebackResponse,
    CostGapsRequest,
    CostGapsResponse,
)

router = APIRouter(prefix="/api/v1/cost", tags=["cost"])


def _detect_cur_config():
    """Detect existing CUR configuration (cached per process)."""
    if not hasattr(_detect_cur_config, "_cached"):
        try:
            from ...modules.finops.cur_setup import CURSetup

            setup = CURSetup()
            _detect_cur_config._cached = setup.detect_existing_cur()
        except Exception:
            _detect_cur_config._cached = None
    return _detect_cur_config._cached


def _get_data_source_sync():
    """Get the appropriate cost data source (CUR or Cost Explorer)."""
    from ...modules.finops.cur_client import CostDataSource

    return CostDataSource.get_source(cur_config=_detect_cur_config())


def _default_range(days: int):
    end = date.today()
    start = end - timedelta(days=days)
    return start, end


def _require_cur():
    """Get CUR client, raising 402 if only Cost Explorer is available."""
    from ...modules.finops.cur_client import CostDataSource, CURClient

    ds = CostDataSource.get_source(cur_config=_detect_cur_config())
    if not isinstance(ds, CURClient):
        return None
    return ds


@router.get("/summary", response_model=CostSummaryResponse)
async def cost_summary(
    days: int = Query(30, ge=1, le=365, description="Number of days to look back"),
    current_user: LocalUser = Depends(get_current_user),
):
    """Get cost summary for the given period."""

    def _fetch():
        ds = _get_data_source_sync()
        start, end = _default_range(days)
        result = ds.get_costs_by_service(start, end)
        return {
            "total_cost": result.total_cost,
            "currency": result.currency,
            "start_date": start.isoformat(),
            "end_date": end.isoformat(),
            "source": result.source,
            "by_service": result.data,
        }

    try:
        data = await asyncio.to_thread(_fetch)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Cost data error: {exc}")


    return CostSummaryResponse(**data)


@router.get("/services", response_model=CostByServiceResponse)
async def cost_by_service(
    days: int = Query(30, ge=1, le=365),
    _user: LocalUser = Depends(get_current_user),
):
    """Get cost breakdown by AWS service."""

    def _fetch():
        ds = _get_data_source_sync()
        start, end = _default_range(days)
        result = ds.get_costs_by_service(start, end)
        return {
            "items": result.data,
            "total_cost": result.total_cost,
            "currency": result.currency,
            "start_date": start.isoformat(),
            "end_date": end.isoformat(),
            "source": result.source,
        }

    try:
        data = await asyncio.to_thread(_fetch)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Cost data error: {exc}")

    return CostByServiceResponse(**data)


@router.get("/accounts", response_model=CostByAccountResponse)
async def cost_by_account(
    days: int = Query(30, ge=1, le=365),
    _user: LocalUser = Depends(get_current_user),
):
    """Get cost breakdown by AWS account."""

    def _fetch():
        ds = _get_data_source_sync()
        start, end = _default_range(days)
        # Try CUR-specific method first, fall back to Cost Explorer
        if hasattr(ds, "get_costs_by_account"):
            result = ds.get_costs_by_account(start, end)
            # Normalize CUR field names (unblended_cost -> cost)
            items = []
            for row in result.data:
                items.append({
                    "account_id": row.get("account_id", ""),
                    "cost": float(
                        row.get("unblended_cost", row.get("cost", 0)) or 0
                    ),
                })
            return {
                "items": items,
                "total_cost": result.total_cost,
                "currency": result.currency,
                "start_date": start.isoformat(),
                "end_date": end.isoformat(),
                "source": result.source,
            }

        # Direct Cost Explorer query grouped by LINKED_ACCOUNT
        import boto3

        ce = boto3.client("ce", region_name="us-east-1")
        resp = ce.get_cost_and_usage(
            TimePeriod={
                "Start": start.isoformat(),
                "End": end.isoformat(),
            },
            Granularity="MONTHLY",
            Metrics=["UnblendedCost"],
            GroupBy=[{"Type": "DIMENSION", "Key": "LINKED_ACCOUNT"}],
        )
        items = []
        total = 0.0
        account_totals: dict = {}
        for period in resp.get("ResultsByTime", []):
            for group in period.get("Groups", []):
                acct = group["Keys"][0]
                cost = float(
                    group["Metrics"]["UnblendedCost"]["Amount"]
                )
                account_totals[acct] = account_totals.get(acct, 0.0) + cost
                total += cost

        for acct, cost in sorted(
            account_totals.items(), key=lambda x: x[1], reverse=True
        ):
            items.append(
                {"account_id": acct, "cost": round(cost, 2)}
            )

        return {
            "items": items,
            "total_cost": round(total, 2),
            "currency": "USD",
            "start_date": start.isoformat(),
            "end_date": end.isoformat(),
            "source": "cost_explorer",
        }

    try:
        data = await asyncio.to_thread(_fetch)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Cost data error: {exc}")

    return CostByAccountResponse(**data)


@router.post("/compare", response_model=CostCompareResponse)
async def compare_periods(body: CostCompareRequest, _user: LocalUser = Depends(get_current_user)):
    """Compare costs between two date periods."""

    def _fetch():
        ds = _get_data_source_sync()
        p1_start = date.fromisoformat(body.period1_start)
        p1_end = date.fromisoformat(body.period1_end)
        p2_start = date.fromisoformat(body.period2_start)
        p2_end = date.fromisoformat(body.period2_end)

        r1 = ds.get_costs_by_service(p1_start, p1_end)
        r2 = ds.get_costs_by_service(p2_start, p2_end)

        change_abs = r2.total_cost - r1.total_cost
        change_pct = None
        if r1.total_cost > 0:
            change_pct = round((change_abs / r1.total_cost) * 100, 2)

        return {
            "period1": {
                "start": body.period1_start,
                "end": body.period1_end,
                "total_cost": r1.total_cost,
                "services": r1.data,
            },
            "period2": {
                "start": body.period2_start,
                "end": body.period2_end,
                "total_cost": r2.total_cost,
                "services": r2.data,
            },
            "change_absolute": round(change_abs, 2),
            "change_percent": change_pct,
        }

    try:
        data = await asyncio.to_thread(_fetch)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Cost comparison error: {exc}")

    return CostCompareResponse(**data)


@router.post("/forecast", response_model=CostForecastResponse)
async def forecast(body: CostForecastRequest, _user: LocalUser = Depends(get_current_user)):
    """Forecast future costs based on historical data."""

    def _fetch():
        ds = _get_data_source_sync()
        # Use last 30 days as basis
        start, end = _default_range(30)
        result = ds.get_costs_by_service(start, end)

        total = result.total_cost
        days_in_period = 30
        daily_avg = total / days_in_period if days_in_period > 0 else 0

        if body.method == "linear":
            projected = daily_avg * body.days
        elif body.method == "weighted":
            # Give more weight to recent data (simple approximation)
            projected = daily_avg * body.days * 1.05
        else:
            projected = daily_avg * body.days

        return {
            "forecast_days": body.days,
            "method": body.method,
            "projected_cost": round(projected, 2),
            "currency": result.currency,
            "daily_average": round(daily_avg, 2),
            "based_on_days": days_in_period,
            "source": result.source,
        }

    try:
        data = await asyncio.to_thread(_fetch)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Forecast error: {exc}")

    return CostForecastResponse(**data)


@router.get("/cur/status", response_model=CURStatusResponse)
async def cur_status(_user: LocalUser = Depends(get_current_user)):
    """Detect existing CUR configuration."""

    def _detect():
        from ...modules.finops.cur_setup import CURSetup

        setup = CURSetup()
        config = setup.detect_existing_cur()
        if config:
            return {
                "found": True,
                "status": config.status,
                "report_name": config.report_name,
                "s3_bucket": config.s3_bucket,
                "athena_database": config.athena_database,
                "athena_table": config.athena_table,
                "region": config.region,
                "message": "CUR configuration detected",
            }
        return {
            "found": False,
            "message": "No CUR configuration found. Using Cost Explorer fallback.",
        }

    try:
        data = await asyncio.to_thread(_detect)
    except Exception as exc:
        return CURStatusResponse(
            found=False,
            message=f"CUR detection failed: {exc}",
        )

    return CURStatusResponse(**data)


@router.post("/cur/deploy", response_model=CURDeployResponse)
async def cur_deploy(body: CURDeployRequest, _user: LocalUser = Depends(require_role(["admin", "operator"]))):
    """Deploy CUR infrastructure through bluearch-core."""

    def _deploy():
        from ...modules.finops.cur_setup import CURSetup

        setup = CURSetup()

        # Check if CUR already exists
        existing = setup.detect_existing_cur()
        if existing and existing.status == "active":
            return {
                "success": False,
                "message": "CUR is already configured and active.",
            }

        job = request_core(
            "POST",
            "/api/v1/infrastructure/stacks/cost-reports/deploy",
            service_token=True,
            timeout=10.0,
            json={
                "bucket_name": body.bucket_name,
                "report_name": body.report_name,
            },
        )
        if hasattr(_detect_cur_config, "_cached"):
            delattr(_detect_cur_config, "_cached")
        return {
            "success": True,
            "job_id": job.get("job_id"),
            "message": job.get("message") or "CUR deployment started.",
            "estimated_ready_hours": 24,
        }

    try:
        data = await asyncio.to_thread(_deploy)
    except Exception as exc:
        raise HTTPException(
            status_code=502, detail=f"CUR deployment error: {exc}"
        )

    return CURDeployResponse(**data)


@router.post("/cur/validate", response_model=CURStatusResponse)
async def cur_validate(body: CURValidateRequest, _user: LocalUser = Depends(require_role(["admin", "operator"]))):
    """Validate a manual CUR configuration."""

    def _validate():
        from ...modules.finops.cur_setup import CURConfiguration, CURSetup

        setup = CURSetup()
        import boto3

        account_id = boto3.client("sts").get_caller_identity()["Account"]

        config = CURConfiguration(
            account_id=account_id,
            report_name="manual-config",
            s3_bucket="",
            s3_prefix="",
            athena_database=body.database,
            athena_table=body.table,
        )
        result = setup.validate_cur_access(config)
        if result.valid:
            return {
                "found": True,
                "status": "active",
                "athena_database": body.database,
                "athena_table": body.table,
                "message": result.message,
            }
        return {
            "found": False,
            "message": f"Validation failed: {result.message}",
        }

    try:
        data = await asyncio.to_thread(_validate)
    except Exception as exc:
        raise HTTPException(
            status_code=502, detail=f"CUR validation error: {exc}"
        )

    return CURStatusResponse(**data)


# --- CUR-specific endpoints ---


@router.get("/regions", response_model=CostRegionsResponse)
async def cost_by_region(
    days: int = Query(30, ge=1, le=365),
    include_services: bool = Query(False),
    _user: LocalUser = Depends(get_current_user),
):
    """Get cost breakdown by region. Uses CUR if available, falls back to Cost Explorer."""

    def _fetch():
        ds = _require_cur()
        if ds:
            start, end = _default_range(days)
            result = ds.get_costs_by_region(start, end, include_services=include_services)
            return {
                "items": result.data,
                "total_cost": result.total_cost,
                "currency": result.currency,
                "start_date": start.isoformat(),
                "end_date": end.isoformat(),
                "source": result.source,
            }

        # Fall back to Cost Explorer REGION dimension
        from ...utils.aws_auth import aws_auth

        ce = aws_auth.get_client("ce")
        start, end = _default_range(days)
        group_by = [{"Type": "DIMENSION", "Key": "REGION"}]
        if include_services:
            group_by.append({"Type": "DIMENSION", "Key": "SERVICE"})

        response = ce.get_cost_and_usage(
            TimePeriod={
                "Start": start.isoformat(),
                "End": end.isoformat(),
            },
            Granularity="MONTHLY",
            Metrics=["UnblendedCost"],
            GroupBy=group_by,
        )

        region_costs = {}
        for period in response.get("ResultsByTime", []):
            for group in period.get("Groups", []):
                keys = group["Keys"]
                region = keys[0] if keys[0] else "global"
                cost = float(group["Metrics"]["UnblendedCost"]["Amount"])
                if include_services and len(keys) > 1:
                    key = (region, keys[1])
                else:
                    key = (region, None)
                if key not in region_costs:
                    region_costs[key] = {"region": region, "cost": 0}
                    if key[1]:
                        region_costs[key]["service"] = key[1]
                region_costs[key]["cost"] += cost

        items = sorted(region_costs.values(), key=lambda x: x["cost"], reverse=True)
        total_cost = sum(r["cost"] for r in items)
        return {
            "items": items,
            "total_cost": total_cost,
            "currency": "USD",
            "start_date": start.isoformat(),
            "end_date": end.isoformat(),
            "source": "cost_explorer",
        }

    try:
        data = await asyncio.to_thread(_fetch)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Cost data error: {exc}")

    return CostRegionsResponse(**data)


@router.get("/daily", response_model=CostDailyResponse)
async def cost_daily(days: int = Query(30, ge=1, le=365), _user: LocalUser = Depends(get_current_user)):
    """Get daily cost summary. Uses CUR if available, falls back to Cost Explorer."""

    def _fetch():
        ds = _require_cur()
        start, end = _default_range(days)
        if ds:
            result = ds.get_daily_cost_summary(start, end)
            return {
                "items": result.data,
                "total_cost": result.total_cost,
                "currency": result.currency,
                "start_date": start.isoformat(),
                "end_date": end.isoformat(),
                "source": result.source,
            }

        # Fall back to Cost Explorer with DAILY granularity
        import boto3

        ce = boto3.client("ce", region_name="us-east-1")
        resp = ce.get_cost_and_usage(
            TimePeriod={
                "Start": start.isoformat(),
                "End": end.isoformat(),
            },
            Granularity="DAILY",
            Metrics=["UnblendedCost"],
            GroupBy=[{"Type": "DIMENSION", "Key": "SERVICE"}],
        )
        items = []
        total = 0.0
        for period in resp.get("ResultsByTime", []):
            day_date = period["TimePeriod"]["Start"]
            day_total = 0.0
            services = {}
            for group in period.get("Groups", []):
                svc = group["Keys"][0]
                cost = float(group["Metrics"]["UnblendedCost"]["Amount"])
                if cost > 0.001:
                    services[svc] = round(cost, 2)
                day_total += cost
            total += day_total
            items.append({
                "date": day_date,
                "total_cost": round(day_total, 2),
                "by_service": services,
            })

        return {
            "items": items,
            "total_cost": round(total, 2),
            "currency": "USD",
            "start_date": start.isoformat(),
            "end_date": end.isoformat(),
            "source": "cost_explorer",
        }

    try:
        data = await asyncio.to_thread(_fetch)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Cost data error: {exc}")

    return CostDailyResponse(**data)


@router.get("/top-resources", response_model=CostTopResourcesResponse)
async def cost_top_resources(
    days: int = Query(30, ge=1, le=365),
    limit: int = Query(50, ge=1, le=500),
    _user: LocalUser = Depends(get_current_user),
):
    """Get top cost resources (CUR required)."""

    def _fetch():
        ds = _require_cur()
        if not ds:
            return None
        start, end = _default_range(days)
        result = ds.get_top_cost_resources(start, end, limit=limit)
        return {
            "items": result.data,
            "total_cost": result.total_cost,
            "currency": result.currency,
            "start_date": start.isoformat(),
            "end_date": end.isoformat(),
            "source": result.source,
        }

    try:
        data = await asyncio.to_thread(_fetch)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Cost data error: {exc}")

    if data is None:
        raise HTTPException(
            status_code=402, detail="CUR required for resource-level costs"
        )
    return CostTopResourcesResponse(**data)


@router.get("/data-transfer", response_model=CostDataTransferResponse)
async def cost_data_transfer(days: int = Query(30, ge=1, le=365), _user: LocalUser = Depends(get_current_user)):
    """Get data transfer costs (CUR required)."""

    def _fetch():
        ds = _require_cur()
        if not ds:
            return None
        start, end = _default_range(days)
        result = ds.get_data_transfer_costs(start, end)
        return {
            "items": result.data,
            "total_cost": result.total_cost,
            "currency": result.currency,
            "start_date": start.isoformat(),
            "end_date": end.isoformat(),
            "source": result.source,
        }

    try:
        data = await asyncio.to_thread(_fetch)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Cost data error: {exc}")

    if data is None:
        raise HTTPException(
            status_code=402, detail="CUR required for data transfer costs"
        )
    return CostDataTransferResponse(**data)


@router.get("/savings-plans", response_model=CostSavingsPlansResponse)
async def cost_savings_plans(days: int = Query(30, ge=1, le=365), _user: LocalUser = Depends(get_current_user)):
    """Get Savings Plans coverage (CUR required)."""

    def _fetch():
        ds = _require_cur()
        if not ds:
            return None
        start, end = _default_range(days)
        result = ds.get_savings_plans_coverage(start, end)
        return {"items": result.data, "source": result.source}

    try:
        data = await asyncio.to_thread(_fetch)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Cost data error: {exc}")

    if data is None:
        raise HTTPException(
            status_code=402, detail="CUR required for Savings Plans data"
        )
    return CostSavingsPlansResponse(**data)


@router.get("/reservations", response_model=CostReservationsResponse)
async def cost_reservations(days: int = Query(30, ge=1, le=365), _user: LocalUser = Depends(get_current_user)):
    """Get Reserved Instance utilization (CUR required)."""

    def _fetch():
        ds = _require_cur()
        if not ds:
            return None
        start, end = _default_range(days)
        result = ds.get_reserved_instance_utilization(start, end)
        return {"items": result.data, "source": result.source}

    try:
        data = await asyncio.to_thread(_fetch)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Cost data error: {exc}")

    if data is None:
        raise HTTPException(
            status_code=402, detail="CUR required for reservation data"
        )
    return CostReservationsResponse(**data)


# --- Service deep-dive endpoints ---

_EC2_VIEWS = {
    "instances": "get_ec2_costs_by_instance_type",
    "families": "get_ec2_costs_by_family",
    "pricing": "get_ec2_pricing_breakdown",
}

_S3_VIEWS = {
    "buckets": "get_s3_costs_by_bucket",
    "storage": "get_s3_costs_by_storage_class",
    "operations": "get_s3_costs_by_operation",
}

_RDS_VIEWS = {
    "engines": "get_rds_costs_by_engine",
    "instances": "get_rds_costs_by_instance_type",
    "breakdown": "get_rds_costs_breakdown",
}

_LAMBDA_VIEWS = {
    "memory": "get_lambda_costs_by_memory",
    "functions": "get_lambda_costs_by_function",
}


def _service_deep_dive(service_name: str, views_map: dict, view: str, days: int):
    """Generic service deep-dive handler."""
    ds = _require_cur()
    if not ds:
        return None

    if view == "summary":
        start, end = _default_range(days)
        result = ds.get_costs_by_service(start, end)
        service_items = [
            item
            for item in result.data
            if service_name.lower()
            in str(item.get("service", item.get("Service", ""))).lower()
        ]
        return {
            "service": service_name,
            "view": view,
            "items": service_items,
            "total_cost": sum(
                float(item.get("cost", item.get("Cost", 0)))
                for item in service_items
            ),
            "currency": result.currency,
            "start_date": start.isoformat(),
            "end_date": end.isoformat(),
            "source": result.source,
        }

    method_name = views_map.get(view)
    if not method_name:
        valid = ", ".join(list(views_map.keys()) + ["summary"])
        raise ValueError(f"Invalid view '{view}'. Valid views: {valid}")

    method = getattr(ds, method_name, None)
    if not method:
        raise ValueError(f"Method {method_name} not available on data source")

    start, end = _default_range(days)
    result = method(start, end)
    return {
        "service": service_name,
        "view": view,
        "items": result.data,
        "total_cost": result.total_cost,
        "currency": result.currency,
        "start_date": start.isoformat(),
        "end_date": end.isoformat(),
        "source": result.source,
    }


@router.get("/ec2", response_model=CostServiceDeepDiveResponse)
async def cost_ec2(
    days: int = Query(30, ge=1, le=365),
    view: str = Query(
        "instances", description="instances|families|pricing|summary"
    ),
    _user: LocalUser = Depends(get_current_user),
):
    """EC2 cost deep-dive (CUR required)."""

    def _fetch():
        return _service_deep_dive("EC2", _EC2_VIEWS, view, days)

    try:
        data = await asyncio.to_thread(_fetch)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Cost data error: {exc}")

    if data is None:
        raise HTTPException(status_code=402, detail="CUR required for EC2 deep-dive")
    return CostServiceDeepDiveResponse(**data)


@router.get("/s3", response_model=CostServiceDeepDiveResponse)
async def cost_s3(
    days: int = Query(30, ge=1, le=365),
    view: str = Query(
        "buckets", description="buckets|storage|operations|summary"
    ),
    _user: LocalUser = Depends(get_current_user),
):
    """S3 cost deep-dive (CUR required)."""

    def _fetch():
        return _service_deep_dive("S3", _S3_VIEWS, view, days)

    try:
        data = await asyncio.to_thread(_fetch)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Cost data error: {exc}")

    if data is None:
        raise HTTPException(status_code=402, detail="CUR required for S3 deep-dive")
    return CostServiceDeepDiveResponse(**data)


@router.get("/rds", response_model=CostServiceDeepDiveResponse)
async def cost_rds(
    days: int = Query(30, ge=1, le=365),
    view: str = Query(
        "engines", description="engines|instances|breakdown|summary"
    ),
    _user: LocalUser = Depends(get_current_user),
):
    """RDS cost deep-dive (CUR required)."""

    def _fetch():
        return _service_deep_dive("RDS", _RDS_VIEWS, view, days)

    try:
        data = await asyncio.to_thread(_fetch)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Cost data error: {exc}")

    if data is None:
        raise HTTPException(status_code=402, detail="CUR required for RDS deep-dive")
    return CostServiceDeepDiveResponse(**data)


@router.get("/lambda", response_model=CostServiceDeepDiveResponse)
async def cost_lambda(
    days: int = Query(30, ge=1, le=365),
    view: str = Query(
        "functions", description="memory|functions|summary"
    ),
    _user: LocalUser = Depends(get_current_user),
):
    """Lambda cost deep-dive (CUR required)."""

    def _fetch():
        return _service_deep_dive("Lambda", _LAMBDA_VIEWS, view, days)

    try:
        data = await asyncio.to_thread(_fetch)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Cost data error: {exc}")

    if data is None:
        raise HTTPException(
            status_code=402, detail="CUR required for Lambda deep-dive"
        )
    return CostServiceDeepDiveResponse(**data)


# --- Analysis endpoints (work with both CUR and Cost Explorer) ---


@router.post("/trends", response_model=CostTrendsResponse)
async def cost_trends(body: CostTrendsRequest, _user: LocalUser = Depends(get_current_user)):
    """Analyze cost trends by tag key."""

    def _fetch():
        from ...modules.finops.trend_analyzer import TrendAnalyzer

        ds = _get_data_source_sync()
        analyzer = TrendAnalyzer(ds)
        result = analyzer.analyze_trends(
            tag_key=body.tag_key,
            periods=body.periods,
            granularity=body.granularity,
            tag_value=body.tag_value,
        )
        return {
            "tag_key": body.tag_key,
            "trends": result.get("trends", []),
            "summary": result.get("summary"),
            "source": result.get("source", "unknown"),
        }

    try:
        data = await asyncio.to_thread(_fetch)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Trend analysis error: {exc}")

    return CostTrendsResponse(**data)


@router.post("/anomalies", response_model=CostAnomaliesResponse)
async def cost_anomalies(body: CostAnomaliesRequest, _user: LocalUser = Depends(get_current_user)):
    """Detect cost anomalies by tag key."""

    def _fetch():
        from ...modules.finops.anomaly_detector import AnomalyDetector

        ds = _get_data_source_sync()
        detector = AnomalyDetector(ds)
        result = detector.detect_anomalies(
            tag_key=body.tag_key,
            percent_threshold=body.percent_threshold,
            absolute_threshold=body.absolute_threshold,
        )
        anomalies = result.get("anomalies", [])
        return {
            "tag_key": body.tag_key,
            "anomalies": anomalies,
            "total_anomalies": len(anomalies),
            "source": result.get("source", "unknown"),
        }

    try:
        data = await asyncio.to_thread(_fetch)
    except Exception as exc:
        raise HTTPException(
            status_code=502, detail=f"Anomaly detection error: {exc}"
        )

    return CostAnomaliesResponse(**data)


@router.post("/report", response_model=CostChargebackResponse)
async def cost_chargeback_report(body: CostChargebackRequest, _user: LocalUser = Depends(get_current_user)):
    """Generate a chargeback report."""

    def _fetch():
        from ...modules.finops.chargeback_reporter import ChargebackReporter

        ds = _get_data_source_sync()
        reporter = ChargebackReporter(ds)
        result = reporter.generate_report(
            tag_key=body.tag_key,
            start_date=body.start_date,
            end_date=body.end_date,
            granularity=body.granularity,
            group_by=body.group_by,
        )
        return {
            "tag_key": body.tag_key,
            "report": result,
            "source": result.get("source", "unknown"),
        }

    try:
        data = await asyncio.to_thread(_fetch)
    except Exception as exc:
        raise HTTPException(
            status_code=502, detail=f"Chargeback report error: {exc}"
        )

    return CostChargebackResponse(**data)


@router.post("/gaps", response_model=CostGapsResponse)
async def cost_visibility_gaps(body: CostGapsRequest, _user: LocalUser = Depends(get_current_user)):
    """Analyze tagging visibility gaps."""

    def _fetch():
        from ...modules.finops.visibility_gap_analyzer import VisibilityGapAnalyzer

        ds = _get_data_source_sync()
        start, end = _default_range(body.days)
        analyzer = VisibilityGapAnalyzer(ds)
        result = analyzer.analyze_gaps(
            required_tags=body.required_tags,
            start_date=start,
            end_date=end,
            min_cost=body.min_cost,
            show_roi=body.show_roi,
        )
        return {
            "gaps": result,
            "source": result.get("source", "unknown"),
        }

    try:
        data = await asyncio.to_thread(_fetch)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Gap analysis error: {exc}")

    return CostGapsResponse(**data)
