"""Graph / resource-map API endpoints backed by bluearch-core."""

from __future__ import annotations

import json
from collections import Counter, defaultdict, deque
from typing import Dict, List, Optional
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, HTTPException, Query

from ..dependencies import get_current_user, LocalUser
from ..schemas.graph import (
    BlastRadiusAffected,
    BlastRadiusDependency,
    BlastRadiusResponse,
    BlastRadiusSummary,
    BlastRadiusTarget,
    GraphEdgeResponse,
    GraphFiltersResponse,
    GraphNodeResponse,
    GraphResponse,
    GraphStatsResponse,
)
from ...utils.core_client import request_core

router = APIRouter(prefix="/api/v1/graph", tags=["graph"])
CORE_RESOURCE_PAGE_SIZE = 1000
CORE_RESOURCE_SCAN_LIMIT = 10000

SERVICE_CATEGORIES = {
    "ec2": {"index": 0, "color": "#f97316"},
    "s3": {"index": 1, "color": "#22c55e"},
    "lambda": {"index": 2, "color": "#a855f7"},
    "rds": {"index": 3, "color": "#3b82f6"},
    "dynamodb": {"index": 4, "color": "#f59e0b"},
    "ecs": {"index": 5, "color": "#14b8a6"},
    "elb": {"index": 6, "color": "#06b6d4"},
    "elbv2": {"index": 6, "color": "#06b6d4"},
    "sns": {"index": 7, "color": "#e11d48"},
    "sqs": {"index": 8, "color": "#8b5cf6"},
    "cloudwatch": {"index": 9, "color": "#ef4444"},
    "logs": {"index": 9, "color": "#ef4444"},
    "eks": {"index": 10, "color": "#0ea5e9"},
    "elasticache": {"index": 11, "color": "#dc2626"},
    "vpc": {"index": 12, "color": "#6b7280"},
    "subnet": {"index": 13, "color": "#9ca3af"},
    "sg": {"index": 14, "color": "#4b5563"},
    "iam": {"index": 15, "color": "#eab308"},
}
CATEGORY_LIST = [{"name": key, "color": value["color"]} for key, value in SERVICE_CATEGORIES.items()]


def _core_resources(**params) -> dict:
    query = urlencode({key: value for key, value in params.items() if value not in (None, "")})
    suffix = f"?{query}" if query else ""
    return request_core("GET", f"/api/v1/resources{suffix}", timeout=10.0)


def _core_all_resources_payload(*, max_items: int = CORE_RESOURCE_SCAN_LIMIT, **params) -> dict:
    resources: list[dict] = []
    offset = 0
    total: int | None = None
    target = max(1, min(max_items, CORE_RESOURCE_SCAN_LIMIT))
    while len(resources) < target:
        page_limit = min(CORE_RESOURCE_PAGE_SIZE, target - len(resources))
        payload = _core_resources(**params, limit=page_limit, offset=offset)
        if total is None and isinstance(payload.get("total"), int):
            total = payload["total"]
        items = payload.get("items", [])
        if not items:
            break
        resources.extend(items)
        offset += len(items)
        if len(items) < page_limit or (isinstance(total, int) and offset >= total):
            break
    return {"items": resources, "total": total if total is not None else len(resources)}


def _core_all_resources(*, max_items: int = CORE_RESOURCE_SCAN_LIMIT, **params) -> list[dict]:
    return _core_all_resources_payload(max_items=max_items, **params)["items"]


def _core_relationships(limit: int = 10000) -> list[dict]:
    rows = request_core(
        "GET",
        f"/api/v1/storage/core/resource-relationships?{urlencode({'limit': limit})}",
        service_token=True,
        timeout=10.0,
    )
    return [row.get("payload", row) for row in rows or []]


def _tags(value) -> dict:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, dict) else {}
        except Exception:
            return {}
    return {}


def _service_from_arn(arn: str) -> str:
    if not arn or not arn.startswith("arn:"):
        return "unknown"
    parts = arn.split(":")
    service = parts[2] if len(parts) > 2 else "unknown"
    resource = parts[5] if len(parts) > 5 else ""
    if service == "ec2" and resource.startswith(("vpc/", "subnet/", "security-group/")):
        return "vpc"
    if service == "elasticloadbalancing":
        return "elb"
    return service


def _type_from_arn(arn: str) -> str:
    if not arn or not arn.startswith("arn:"):
        return "Unknown"
    parts = arn.split(":")
    service = parts[2] if len(parts) > 2 else "unknown"
    resource = parts[5] if len(parts) > 5 else ""
    resource_type = resource.split("/")[0] if "/" in resource else resource
    return f"AWS::{service}::{resource_type}"


def _node(arn: str, degree: int, resource: Optional[Dict] = None) -> GraphNodeResponse:
    service = (resource or {}).get("service_name") or _service_from_arn(arn)
    resource_id = (resource or {}).get("resource_id") or (arn.split("/")[-1] if "/" in arn else arn.split(":")[-1])
    tags = _tags((resource or {}).get("current_tags"))
    return GraphNodeResponse(
        id=arn,
        resource_id=resource_id,
        resource_type=(resource or {}).get("resource_type") or _type_from_arn(arn),
        service_name=service,
        region=(resource or {}).get("region") or "unknown",
        account_id=(resource or {}).get("account_id") or "unknown",
        name=tags.get("Name") or resource_id,
        lifecycle_state=(resource or {}).get("lifecycle_state"),
        expires_at=(resource or {}).get("expires_at"),
        protected=(resource or {}).get("protected"),
        compliance_status=(resource or {}).get("compliance_status"),
        missing_tags=(resource or {}).get("missing_tags") if isinstance((resource or {}).get("missing_tags"), list) else None,
        category=SERVICE_CATEGORIES.get(service, {"index": len(CATEGORY_LIST) - 1})["index"],
        symbol_size=max(20, min(60, 20 + degree * 4)),
    )


def _resource_lookup(resources: list[dict]) -> dict[str, dict]:
    return {row.get("resource_arn"): row for row in resources if row.get("resource_arn")}


def _filtered_relationships(relationships: list[dict], *, region=None, account_id=None, service=None) -> list[dict]:
    rows = relationships
    if region:
        rows = [row for row in rows if row.get("region") == region]
    if account_id:
        rows = [row for row in rows if row.get("account_id") == account_id]
    if service:
        rows = [
            row
            for row in rows
            if f"::{service}::" in str(row.get("source_type") or "")
            or f"::{service}::" in str(row.get("target_type") or "")
        ]
    return rows


@router.get("", response_model=GraphResponse)
async def get_graph(
    vpc_id: Optional[str] = Query(None),
    region: Optional[str] = Query(None),
    account_id: Optional[str] = Query(None),
    service: Optional[str] = Query(None),
    resource_arn: Optional[str] = Query(None),
    depth: int = Query(1, ge=1, le=3),
    max_nodes: int = Query(200, ge=50, le=500),
    overlays: Optional[str] = Query(None),
    current_user: LocalUser = Depends(get_current_user),
):
    """Get graph data for the resource map."""
    try:
        resources = _core_all_resources()
        relationships = _core_relationships()
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"bluearch-core graph data unavailable: {exc}") from exc
    resource_map = _resource_lookup(resources)

    if resource_arn:
        visited = {resource_arn}
        frontier = {resource_arn}
        selected_edges = []
        for _ in range(depth):
            if not frontier:
                break
            next_frontier = set()
            for edge in relationships:
                if edge.get("source_arn") in frontier or edge.get("target_arn") in frontier:
                    selected_edges.append(edge)
                    for arn in (edge.get("source_arn"), edge.get("target_arn")):
                        if arn and arn not in visited:
                            visited.add(arn)
                            next_frontier.add(arn)
            frontier = next_frontier
        node_arns = visited
    else:
        selected_edges = _filtered_relationships(relationships, region=region, account_id=account_id, service=service)
        if vpc_id:
            selected_edges = [edge for edge in selected_edges if f"vpc/{vpc_id}" in str(edge.get("source_arn")) or f"vpc/{vpc_id}" in str(edge.get("target_arn"))]
        degree = Counter()
        for edge in selected_edges:
            degree[edge.get("source_arn")] += 1
            degree[edge.get("target_arn")] += 1
        node_arns = set([arn for arn, _ in degree.most_common(max_nodes)])
    truncated = len(node_arns) > max_nodes
    node_arns = set(list(node_arns)[:max_nodes])
    selected_edges = [edge for edge in selected_edges if edge.get("source_arn") in node_arns and edge.get("target_arn") in node_arns]

    degree = Counter()
    for edge in selected_edges:
        degree[edge.get("source_arn")] += 1
        degree[edge.get("target_arn")] += 1
    nodes = [_node(arn, degree.get(arn, 0), resource_map.get(arn)) for arn in node_arns]
    edges = [
        GraphEdgeResponse(
            source=edge.get("source_arn"),
            target=edge.get("target_arn"),
            relationship_type=edge.get("relationship_type") or "",
            label=edge.get("relationship_type") or "",
        )
        for edge in selected_edges
    ]
    result = GraphResponse(nodes=nodes, edges=edges, categories=CATEGORY_LIST, total_relationships=len(relationships), truncated=truncated)
    return result


@router.get("/blast-radius", response_model=BlastRadiusResponse)
async def get_blast_radius(
    arn: str = Query(..., description="Resource ARN to analyze"),
    _user: LocalUser = Depends(get_current_user),
):
    """Compute blast-radius analysis for a resource."""
    try:
        resources = _core_all_resources()
        relationships = _core_relationships()
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"bluearch-core blast radius unavailable: {exc}") from exc
    resource_map = _resource_lookup(resources)
    incoming = defaultdict(list)
    outgoing = defaultdict(list)
    for edge in relationships:
        outgoing[edge.get("source_arn")].append(edge)
        incoming[edge.get("target_arn")].append(edge)

    dependencies = []
    for edge in outgoing.get(arn, []):
        target_arn = edge.get("target_arn")
        info = resource_map.get(target_arn, {})
        dependencies.append(
            BlastRadiusDependency(
                arn=target_arn,
                name=info.get("resource_id") or str(target_arn).split("/")[-1],
                service=info.get("service_name") or _service_from_arn(target_arn),
                resource_type=info.get("resource_type") or _type_from_arn(target_arn),
                relationship=edge.get("relationship_type") or "",
            )
        )

    affected = []
    visited = {arn}
    queue = deque([(edge.get("source_arn"), edge.get("relationship_type") or "", 1) for edge in incoming.get(arn, [])])
    while queue and len(affected) < 100:
        current, rel_type, depth = queue.popleft()
        if not current or current in visited:
            continue
        visited.add(current)
        info = resource_map.get(current, {})
        impact = "cascade" if rel_type == "BELONGS_TO" else ("orphaned" if len(outgoing.get(current, [])) <= 1 else "disconnected")
        affected.append(
            BlastRadiusAffected(
                arn=current,
                name=info.get("resource_id") or current.split("/")[-1],
                service=info.get("service_name") or _service_from_arn(current),
                resource_type=info.get("resource_type") or _type_from_arn(current),
                impact=impact,
                relationship=rel_type,
                depth=depth,
                lifecycle_state=info.get("lifecycle_state"),
                protected=bool(info.get("protected")),
            )
        )
        if depth < 3:
            for edge in incoming.get(current, []):
                queue.append((edge.get("source_arn"), edge.get("relationship_type") or "", depth + 1))

    target_info = resource_map.get(arn, {})
    summary = BlastRadiusSummary(
        total_affected=len(affected),
        orphaned=sum(1 for item in affected if item.impact == "orphaned"),
        disconnected=sum(1 for item in affected if item.impact == "disconnected"),
        cascade=sum(1 for item in affected if item.impact == "cascade"),
        protected_affected=sum(1 for item in affected if item.protected),
    )
    return BlastRadiusResponse(
        target=BlastRadiusTarget(
            arn=arn,
            name=target_info.get("resource_id") or arn.split("/")[-1],
            service=target_info.get("service_name") or _service_from_arn(arn),
            resource_type=target_info.get("resource_type") or _type_from_arn(arn),
        ),
        affected=affected,
        summary=summary,
        dependencies=dependencies,
        truncated=len(affected) >= 100,
    )


@router.get("/stats", response_model=GraphStatsResponse)
async def get_graph_stats(
    region: Optional[str] = Query(None),
    account_id: Optional[str] = Query(None),
    _user: LocalUser = Depends(get_current_user),
):
    """Get aggregate relationship statistics."""
    try:
        relationships = _filtered_relationships(_core_relationships(), region=region, account_id=account_id)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"bluearch-core graph stats unavailable: {exc}") from exc
    by_type = Counter(edge.get("relationship_type") or "unknown" for edge in relationships)
    most = Counter(edge.get("source_arn") for edge in relationships if edge.get("source_arn")).most_common(10)
    return GraphStatsResponse(
        total_relationships=len(relationships),
        by_type=dict(by_type),
        most_connected=[{"arn": arn, "edge_count": count} for arn, count in most],
    )


@router.get("/filters", response_model=GraphFiltersResponse)
async def get_graph_filters(_user: LocalUser = Depends(get_current_user)):
    """Get available filter values for the graph."""
    try:
        resources = _core_all_resources()
        relationships = _core_relationships()
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"bluearch-core graph filters unavailable: {exc}") from exc
    vpc_ids = sorted(
        {
            str(row.get("resource_arn")).split("/")[-1]
            for row in resources
            if row.get("resource_type") == "AWS::EC2::VPC" and row.get("resource_arn")
        }
    )
    return GraphFiltersResponse(
        vpc_ids=vpc_ids,
        regions=sorted({row.get("region") for row in relationships if row.get("region")}),
        account_ids=sorted({row.get("account_id") for row in relationships if row.get("account_id")}),
        services=sorted({row.get("service_name") for row in resources if row.get("service_name")}),
        relationship_types=sorted({row.get("relationship_type") for row in relationships if row.get("relationship_type")}),
    )
