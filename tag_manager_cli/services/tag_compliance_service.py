"""Tag compliance analysis service for AI assistant and CLI commands.

Provides cached access to tag compliance data, service breakdown,
and risk analysis with consistent compliance logic.
"""

import json
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from ..utils.core_client import request_core

logger = logging.getLogger(__name__)

# Cache TTLs
COMPLIANCE_SCAN_TTL = 300  # 5 minutes - scan results
COMPLIANCE_SUMMARY_TTL = 600  # 10 minutes - summary statistics


@dataclass
class ComplianceSummary:
    """Summary statistics for tag compliance."""
    total_resources: int
    fully_compliant: int
    partially_compliant: int
    non_compliant: int
    compliance_rate: float
    required_tags: List[str]
    policy_source: str  # 'org_policy' or 'default'
    compliance_mode: str  # 'AND' or 'OR'
    last_scan_time: Optional[str]

    def to_dict(self) -> Dict[str, Any]:
        return {
            'total_resources': self.total_resources,
            'fully_compliant': self.fully_compliant,
            'partially_compliant': self.partially_compliant,
            'non_compliant': self.non_compliant,
            'compliance_rate': round(self.compliance_rate, 2),
            'required_tags': self.required_tags,
            'policy_source': self.policy_source,
            'compliance_mode': self.compliance_mode,
            'last_scan_time': self.last_scan_time
        }


@dataclass
class ServiceCompliance:
    """Compliance statistics for a specific AWS service."""
    service_name: str
    total: int
    compliant: int
    non_compliant: int
    compliance_rate: float

    def to_dict(self) -> Dict[str, Any]:
        return {
            'service_name': self.service_name,
            'total': self.total,
            'compliant': self.compliant,
            'non_compliant': self.non_compliant,
            'compliance_rate': round(self.compliance_rate, 2)
        }


class TagComplianceService:
    """Service for analyzing tag compliance across AWS resources."""

    def __init__(self):
        self._cache_prefix = 'tag_compliance'

    def _get_cache(self):
        """Get cache manager (lazy import to avoid circular dependencies)."""
        try:
            from ..utils.cache import cache
            return cache
        except Exception:
            return None

    def _get_cache_key(self, operation: str, **kwargs) -> str:
        """Generate cache key for compliance operations."""
        if kwargs:
            # Filter out None values
            filtered = {k: v for k, v in kwargs.items() if v is not None}
            if filtered:
                params_str = json.dumps(filtered, sort_keys=True)
                return f"{self._cache_prefix}:{operation}:{params_str}"
        return f"{self._cache_prefix}:{operation}"

    def _parse_tags(self, current_tags: Any) -> Dict[str, str]:
        """Parse current_tags from database (handles string or dict)."""
        if not current_tags:
            return {}
        if isinstance(current_tags, str):
            try:
                return json.loads(current_tags) if current_tags else {}
            except json.JSONDecodeError:
                return {}
        if isinstance(current_tags, dict):
            return current_tags
        return {}

    def _parse_time(self, value: Any) -> Optional[datetime]:
        """Parse datetime values returned by bluearch-core storage APIs."""
        if isinstance(value, datetime):
            return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
        if isinstance(value, str) and value:
            try:
                parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
                return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
            except ValueError:
                return None
        return None

    def _list_core_resources(
        self,
        services: Optional[List[str]] = None,
        regions: Optional[List[str]] = None,
        account_ids: Optional[List[str]] = None,
        min_age_hours: int = 0,
        limit: Optional[int] = None,
        multiplier: int = 1,
    ) -> List[Dict[str, Any]]:
        """Fetch and filter resources from bluearch-core inventory."""
        fetch_limit = min(max((limit or 10000) * max(multiplier, 1), 1), 10000)
        params = [
            ("limit", fetch_limit),
            ("order_by", "created_at"),
            ("descending", "true"),
        ]
        records = request_core(
            "GET",
            "/api/v1/storage/core/resources",
            service_token=True,
            params=params,
            timeout=10.0,
        )
        resources = [record.get("payload", record) for record in records or []]

        service_filter = {item.lower() for item in services or []}
        region_filter = {item.lower() for item in regions or []}
        account_filter = set(account_ids or [])
        cutoff = None
        if min_age_hours > 0:
            cutoff = datetime.now(timezone.utc) - timedelta(hours=min_age_hours)

        filtered = []
        for resource in resources:
            if resource.get("lifecycle_state") == "stale":
                continue
            if service_filter and str(resource.get("service_name") or "").lower() not in service_filter:
                continue
            if region_filter and str(resource.get("region") or "").lower() not in region_filter:
                continue
            if account_filter and str(resource.get("account_id") or "") not in account_filter:
                continue
            if cutoff:
                created_at = self._parse_time(resource.get("created_at"))
                if not created_at or created_at > cutoff:
                    continue
            filtered.append(resource)
            if limit and multiplier <= 1 and len(filtered) >= limit:
                break

        return filtered

    def get_compliance_summary(
        self,
        services: Optional[List[str]] = None,
        regions: Optional[List[str]] = None,
        account_ids: Optional[List[str]] = None,
        use_cache: bool = True
    ) -> ComplianceSummary:
        """Get overall tag compliance summary.

        Args:
            services: Filter by service names (e.g., ['ec2', 's3'])
            regions: Filter by regions
            account_ids: Filter by account IDs
            use_cache: Whether to use cached results

        Returns:
            ComplianceSummary with statistics
        """
        cache = self._get_cache()
        cache_key = self._get_cache_key(
            'summary',
            services=services,
            regions=regions,
            account_ids=account_ids
        )

        if use_cache and cache:
            try:
                cached = cache.get(cache_key)
                if cached:
                    return ComplianceSummary(**cached)
            except Exception as e:
                logger.debug(f"Cache read failed: {e}")

        from .org_policy_provider import org_policy_provider

        # Fetch required tags from org policy
        required_tags, from_org_policy, _ = org_policy_provider.get_required_tags(
            show_warnings=False
        )

        resources = self._list_core_resources(
            services=services,
            regions=regions,
            account_ids=account_ids,
        )
        stats = {"fully_compliant": 0, "partially_compliant": 0, "non_compliant": 0}

        for resource in resources:
            current_tags = self._parse_tags(resource.get("current_tags"))

            result = org_policy_provider.check_resource_compliance_detailed(
                current_tags, required_tags, from_org_policy
            )

            if result.is_compliant:
                stats["fully_compliant"] += 1
            elif result.matched_tags:
                stats["partially_compliant"] += 1
            else:
                stats["non_compliant"] += 1

        total = len(resources)
        compliance_rate = (stats["fully_compliant"] / max(total, 1)) * 100

        summary = ComplianceSummary(
            total_resources=total,
            fully_compliant=stats["fully_compliant"],
            partially_compliant=stats["partially_compliant"],
            non_compliant=stats["non_compliant"],
            compliance_rate=compliance_rate,
            required_tags=required_tags,
            policy_source='org_policy' if from_org_policy else 'default',
            compliance_mode='AND' if from_org_policy else 'OR',
            last_scan_time=datetime.now(timezone.utc).isoformat()
        )

        # Cache result
        if cache:
            try:
                cache.set(cache_key, summary.to_dict(), ttl=COMPLIANCE_SUMMARY_TTL)
            except Exception as e:
                logger.debug(f"Cache write failed: {e}")

        return summary

    def get_service_breakdown(
        self,
        services: Optional[List[str]] = None,
        regions: Optional[List[str]] = None,
        account_ids: Optional[List[str]] = None,
        use_cache: bool = True
    ) -> List[ServiceCompliance]:
        """Get compliance breakdown by AWS service.

        Args:
            services: Filter by services
            regions: Filter by regions
            account_ids: Filter by account IDs
            use_cache: Whether to use cached results

        Returns:
            List of ServiceCompliance objects sorted by compliance rate (worst first)
        """
        cache = self._get_cache()
        cache_key = self._get_cache_key(
            'service_breakdown',
            services=services,
            regions=regions,
            account_ids=account_ids
        )

        if use_cache and cache:
            try:
                cached = cache.get(cache_key)
                if cached:
                    return [ServiceCompliance(**s) for s in cached]
            except Exception as e:
                logger.debug(f"Cache read failed: {e}")

        from .org_policy_provider import org_policy_provider

        required_tags, from_org_policy, _ = org_policy_provider.get_required_tags(
            show_warnings=False
        )

        service_stats: Dict[str, Dict[str, int]] = {}

        resources = self._list_core_resources(
            services=services,
            regions=regions,
            account_ids=account_ids,
        )
        for resource in resources:
            service = resource.get("service_name") or "unknown"
            if service not in service_stats:
                service_stats[service] = {"total": 0, "compliant": 0}
            service_stats[service]["total"] += 1

            current_tags = self._parse_tags(resource.get("current_tags"))

            result = org_policy_provider.check_resource_compliance_detailed(
                current_tags, required_tags, from_org_policy
            )

            if result.is_compliant:
                service_stats[service]["compliant"] += 1

        # Convert to ServiceCompliance objects
        result_list = []
        for service, stats in service_stats.items():
            total = stats["total"]
            compliant = stats["compliant"]
            non_compliant = total - compliant
            rate = (compliant / max(total, 1)) * 100

            result_list.append(ServiceCompliance(
                service_name=service,
                total=total,
                compliant=compliant,
                non_compliant=non_compliant,
                compliance_rate=rate
            ))

        # Sort by compliance rate (worst first)
        result_list.sort(key=lambda x: x.compliance_rate)

        # Cache
        if cache:
            try:
                cache.set(
                    cache_key,
                    [s.to_dict() for s in result_list],
                    ttl=COMPLIANCE_SUMMARY_TTL
                )
            except Exception as e:
                logger.debug(f"Cache write failed: {e}")

        return result_list

    def get_non_compliant_resources(
        self,
        services: Optional[List[str]] = None,
        regions: Optional[List[str]] = None,
        account_ids: Optional[List[str]] = None,
        min_age_hours: int = 0,
        risk_level: Optional[str] = None,  # 'high', 'medium', 'low'
        limit: int = 50,
        use_cache: bool = True
    ) -> Dict[str, Any]:
        """Get detailed list of non-compliant resources with risk analysis.

        Args:
            services: Filter by services
            regions: Filter by regions
            account_ids: Filter by account IDs
            min_age_hours: Only include resources older than N hours
            risk_level: Filter by risk level ('high', 'medium', 'low')
            limit: Maximum resources to return
            use_cache: Whether to use cached results

        Returns:
            Dict with resources list and risk analysis
        """
        cache = self._get_cache()
        cache_key = self._get_cache_key(
            'non_compliant',
            services=services,
            regions=regions,
            account_ids=account_ids,
            min_age_hours=min_age_hours,
            risk_level=risk_level,
            limit=limit
        )

        if use_cache and cache:
            try:
                cached = cache.get(cache_key)
                if cached:
                    return cached
            except Exception as e:
                logger.debug(f"Cache read failed: {e}")

        from .org_policy_provider import org_policy_provider

        required_tags, from_org_policy, _ = org_policy_provider.get_required_tags(
            show_warnings=False
        )

        resources_list = []
        risk_analysis = {"high_risk": 0, "medium_risk": 0, "low_risk": 0}
        high_risk_details = []

        # High-risk services (expensive or critical)
        high_risk_services = {"ec2", "rds", "redshift", "elasticsearch", "opensearch"}

        resources = self._list_core_resources(
            services=services,
            regions=regions,
            account_ids=account_ids,
            min_age_hours=min_age_hours,
            limit=limit,
            multiplier=3,
        )
        for resource in resources:
            if len(resources_list) >= limit:
                break

            current_tags = self._parse_tags(resource.get("current_tags"))

            result = org_policy_provider.check_resource_compliance_detailed(
                current_tags, required_tags, from_org_policy
            )

            if result.is_compliant:
                continue

            age_hours = 0.0
            created_at = self._parse_time(resource.get("created_at"))
            if created_at:
                age_delta = datetime.now(timezone.utc) - created_at
                age_hours = age_delta.total_seconds() / 3600

            service = resource.get("service_name") or "unknown"
            if age_hours > 168 or service in high_risk_services:
                current_risk = "high"
                risk_analysis["high_risk"] += 1
            elif age_hours > 24:
                current_risk = "medium"
                risk_analysis["medium_risk"] += 1
            else:
                current_risk = "low"
                risk_analysis["low_risk"] += 1

            if risk_level and current_risk != risk_level:
                continue

            resource_data = {
                'resource_id': resource.get("resource_id"),
                'resource_arn': resource.get("resource_arn"),
                'service_name': service,
                'region': resource.get("region"),
                'account_id': resource.get("account_id"),
                'missing_tags': result.missing_tags,
                'matched_tags': result.matched_tags,
                'tag_count': len(current_tags),
                'age_hours': round(age_hours, 1),
                'age_display': f"{int(age_hours // 24)}d" if age_hours > 24 else f"{int(age_hours)}h",
                'risk_level': current_risk
            }

            resources_list.append(resource_data)

            if current_risk == "high":
                high_risk_details.append(resource_data)

        result_data = {
            'resources': resources_list,
            'count': len(resources_list),
            'required_tags': required_tags,
            'policy_source': 'org_policy' if from_org_policy else 'default',
            'compliance_mode': 'AND' if from_org_policy else 'OR',
            'risk_analysis': risk_analysis,
            'high_risk_resources': high_risk_details[:10]
        }

        if cache:
            try:
                cache.set(cache_key, result_data, ttl=COMPLIANCE_SCAN_TTL)
            except Exception as e:
                logger.debug(f"Cache write failed: {e}")

        return result_data


# Global singleton
tag_compliance_service = TagComplianceService()
