"""Organization tag policy provider with caching support.

Provides centralized access to AWS Organizations tag policies for compliance
checking in tags scan and discover commands.
"""

import logging
from dataclasses import dataclass
from typing import Dict, List, Optional, Any, Tuple

from rich.console import Console

logger = logging.getLogger(__name__)
console = Console()

# Cache TTL for organization policy (1 hour - policies don't change often)
POLICY_CACHE_TTL = 3600

# Default required tags when no org policy available (OR logic - any one is sufficient)
DEFAULT_REQUIRED_TAGS = ['Environment', 'Owner', 'CostCenter']

# Policy source identifiers
POLICY_SOURCE_ORG = 'org_policy'
POLICY_SOURCE_DEFAULT = 'default'


@dataclass
class ComplianceResult:
    """Result of a compliance check with detailed information."""
    is_compliant: bool
    matched_tags: List[str]  # Tags that were found on the resource
    missing_tags: List[str]  # Tags that are missing (for AND logic)
    policy_source: str       # 'org_policy' or 'default'
    policy_id: Optional[str] # Policy ID if from org policy
    compliance_mode: str     # 'AND' or 'OR'

    def get_display_source(self) -> str:
        """Get human-readable policy source for display."""
        if self.policy_source == POLICY_SOURCE_ORG:
            if self.policy_id:
                return f"policy:{self.policy_id}"
            return "org_policy"
        return "default_tags"

    def get_matched_tag_display(self) -> str:
        """Get display string for matched tags."""
        if self.matched_tags:
            return ', '.join(self.matched_tags)
        return "none"


class OrgPolicyProvider:
    """Provides cached access to AWS Organizations tag policies."""

    def __init__(self):
        """Initialize the policy provider."""
        self._service = None
        self._last_error: Optional[str] = None
        self._policy_available: Optional[bool] = None
        self._current_policy_id: Optional[str] = None

    def _get_service(self):
        """Lazy initialize the OrganizationsService."""
        if self._service is None:
            try:
                from ..utils.aws_auth import aws_auth
                from .organizations_service import OrganizationsService

                session = aws_auth.initialize_session()
                self._service = OrganizationsService(session)
            except Exception as e:
                logger.warning(f"Failed to initialize OrganizationsService: {e}")
                self._service = None
        return self._service

    def _get_cache(self):
        """Get cache manager (lazy import to avoid circular dependencies)."""
        try:
            from ..utils.cache import cache
            return cache
        except Exception:
            return None

    def get_required_tags(
        self,
        use_cache: bool = True,
        show_warnings: bool = True
    ) -> Tuple[List[str], bool, Optional[str]]:
        """
        Get required tags from organization policy or fallback to defaults.

        Args:
            use_cache: Whether to use cached policy data
            show_warnings: Whether to generate warning messages

        Returns:
            Tuple of (required_tags_list, from_org_policy, warning_message)
        """
        cache = self._get_cache()
        cache_key = 'org_policy:required_tags'

        # Try cache first
        if use_cache and cache:
            try:
                cached_data = cache.get(cache_key)
                if cached_data and isinstance(cached_data, dict):
                    tags = cached_data.get('tags', [])
                    policy_id = cached_data.get('policy_id')
                    if tags:
                        self._current_policy_id = policy_id
                        self._policy_available = True
                        return tags, True, None
            except Exception as e:
                logger.debug(f"Cache read failed: {e}")

        # Try to fetch from org policy
        try:
            service = self._get_service()
            if service is None:
                return self._handle_fallback('no_service', show_warnings)

            access_info = service.check_access()

            if not access_info.get('has_access'):
                return self._handle_fallback('no_access', show_warnings)

            if not access_info.get('tag_policies_enabled'):
                return self._handle_fallback('not_enabled', show_warnings)

            effective_policy = service.get_effective_policy()

            if effective_policy.get('error'):
                logger.debug(f"Effective policy error: {effective_policy.get('error')}")
                return self._handle_fallback('fetch_failed', show_warnings)

            content = effective_policy.get('content', {})
            required_tags = self._extract_required_tags(content)
            policy_id = effective_policy.get('policy_id')

            if not required_tags:
                return self._handle_fallback('no_tags', show_warnings)

            # Store policy ID
            self._current_policy_id = policy_id

            # Cache successful result with policy ID
            if cache:
                try:
                    cache.set(cache_key, {'tags': required_tags, 'policy_id': policy_id}, ttl=POLICY_CACHE_TTL)
                except Exception as e:
                    logger.debug(f"Cache write failed: {e}")

            self._policy_available = True
            return required_tags, True, None

        except Exception as e:
            logger.warning(f"Failed to fetch org policy: {str(e)}")
            return self._handle_fallback('exception', show_warnings)

    def _extract_required_tags(self, policy_content: Dict[str, Any]) -> List[str]:
        """Extract required tag keys from AWS Organizations policy content.

        The policy content structure from AWS Organizations looks like:
        {
            "tags": {
                "Environment": { ... },
                "CostCenter": { ... }
            }
        }

        All tags defined in the policy are considered required.
        """
        tags = policy_content.get('tags', {})
        if isinstance(tags, dict):
            return list(tags.keys())
        return []

    def _handle_fallback(
        self,
        reason: str,
        show_warnings: bool
    ) -> Tuple[List[str], bool, Optional[str]]:
        """Handle fallback when no org policy is available.

        Args:
            reason: The reason for fallback
            show_warnings: Whether to generate warning message

        Returns:
            Tuple of (empty_tags, False, None) - no compliance checking without org policy
        """
        self._policy_available = False
        # Return empty list - no compliance checking without org policy
        # Resources are compliant by default until policies are created
        return [], False, None

    def _build_warning_message(self, reason: str) -> str:
        """Build ASCII-safe warning message based on failure reason.

        NOTE: Using ASCII-only output for packaged binary compatibility.
        """
        default_tags_str = ', '.join(DEFAULT_REQUIRED_TAGS)

        messages = {
            'no_service': (
                "[yellow]Note: Could not initialize AWS Organizations service.[/yellow]\n"
                f"[dim]Using default required tags: {default_tags_str}[/dim]"
            ),
            'no_access': (
                "[yellow]Note: Cannot access AWS Organizations.[/yellow]\n"
                f"[dim]Using default required tags: {default_tags_str}[/dim]\n"
                "[dim]To use organization tag policies, ensure your account is part of an organization.[/dim]"
            ),
            'not_enabled': (
                "[yellow]Note: AWS Organizations tag policies are not enabled.[/yellow]\n"
                f"[dim]Using default required tags: {default_tags_str}[/dim]\n"
                "[dim]Run 'policy wizard' to enable and create tag policies for your organization.[/dim]"
            ),
            'fetch_failed': (
                "[yellow]Note: Could not fetch organization tag policy.[/yellow]\n"
                f"[dim]Using default required tags: {default_tags_str}[/dim]\n"
                "[dim]Run 'policy check-access' to diagnose the issue.[/dim]"
            ),
            'no_tags': (
                "[yellow]Note: Organization tag policy exists but defines no required tags.[/yellow]\n"
                f"[dim]Using default required tags: {default_tags_str}[/dim]\n"
                "[dim]Run 'policy wizard' to add required tags to your policy.[/dim]"
            ),
            'exception': (
                "[yellow]Note: Error fetching organization tag policy.[/yellow]\n"
                f"[dim]Using default required tags: {default_tags_str}[/dim]"
            )
        }
        return messages.get(reason, messages['exception'])

    def check_resource_compliance(
        self,
        resource_tags: Dict[str, str],
        required_tags: Optional[List[str]] = None,
        from_org_policy: Optional[bool] = None
    ) -> Tuple[bool, List[str]]:
        """Check if resource tags comply with required tags.

        For default tags: Uses OR logic (compliant if ANY tag is present)
        For org policy tags: Uses AND logic (compliant if ALL tags are present)

        Args:
            resource_tags: Dictionary of tag key-value pairs from the resource
            required_tags: List of required tag keys (auto-fetched if None)
            from_org_policy: Whether tags are from org policy (auto-detected if None)

        Returns:
            Tuple of (is_compliant, missing_tags_list)
        """
        # Preserve explicit from_org_policy parameter
        explicit_from_org = from_org_policy
        if required_tags is None:
            required_tags, fetched_from_org, _ = self.get_required_tags(show_warnings=False)
            # Only use fetched value if not explicitly specified
            if explicit_from_org is None:
                from_org_policy = fetched_from_org
            else:
                from_org_policy = explicit_from_org
        elif from_org_policy is None:
            from_org_policy = self._policy_available if self._policy_available is not None else False

        # Handle None or invalid resource_tags
        if not resource_tags or not isinstance(resource_tags, dict):
            resource_tags = {}

        # No required tags means everything is compliant
        if not required_tags:
            return True, []

        matched_tags = [tag for tag in required_tags if tag in resource_tags]
        missing_tags = [tag for tag in required_tags if tag not in resource_tags]

        # Use different logic based on policy source
        if from_org_policy:
            # Org policy: AND logic - all tags required
            is_compliant = len(missing_tags) == 0
        else:
            # No org policy and no required tags = compliant
            is_compliant = True

        return is_compliant, missing_tags

    def check_resource_compliance_detailed(
        self,
        resource_tags: Dict[str, str],
        required_tags: Optional[List[str]] = None,
        from_org_policy: Optional[bool] = None
    ) -> ComplianceResult:
        """Check resource compliance with detailed result including policy source.

        For default tags: Uses OR logic (compliant if ANY tag is present)
        For org policy tags: Uses AND logic (compliant if ALL tags are present)

        Args:
            resource_tags: Dictionary of tag key-value pairs from the resource
            required_tags: List of required tag keys (auto-fetched if None)
            from_org_policy: Whether tags are from org policy (auto-detected if None)

        Returns:
            ComplianceResult with detailed compliance information
        """
        # Preserve explicit from_org_policy parameter
        explicit_from_org = from_org_policy
        if required_tags is None:
            required_tags, fetched_from_org, _ = self.get_required_tags(show_warnings=False)
            # Only use fetched value if not explicitly specified
            if explicit_from_org is None:
                from_org_policy = fetched_from_org
            else:
                from_org_policy = explicit_from_org
        elif from_org_policy is None:
            from_org_policy = self._policy_available if self._policy_available is not None else False

        # Handle None or invalid resource_tags
        if not resource_tags or not isinstance(resource_tags, dict):
            resource_tags = {}

        # No required tags means everything is compliant
        if not required_tags:
            return ComplianceResult(
                is_compliant=True,
                matched_tags=[],
                missing_tags=[],
                policy_source=POLICY_SOURCE_DEFAULT,
                policy_id=None,
                compliance_mode='NONE'
            )

        matched_tags = [tag for tag in required_tags if tag in resource_tags]
        missing_tags = [tag for tag in required_tags if tag not in resource_tags]

        # Use different logic based on policy source
        if from_org_policy:
            # Org policy: AND logic - all tags required
            is_compliant = len(missing_tags) == 0
            compliance_mode = 'AND'
            policy_source = POLICY_SOURCE_ORG
            policy_id = self._current_policy_id
        else:
            # No org policy = compliant by default
            is_compliant = True
            compliance_mode = 'NONE'
            policy_source = POLICY_SOURCE_DEFAULT
            policy_id = None

        return ComplianceResult(
            is_compliant=is_compliant,
            matched_tags=matched_tags,
            missing_tags=missing_tags,
            policy_source=policy_source,
            policy_id=policy_id,
            compliance_mode=compliance_mode
        )

    def get_compliance_indicator(
        self,
        resource_tags: Dict[str, str],
        required_tags: Optional[List[str]] = None
    ) -> str:
        """Get ASCII-safe compliance indicator for display.

        Args:
            resource_tags: Dictionary of tag key-value pairs
            required_tags: List of required tag keys (auto-fetched if None)

        Returns:
            String indicator like "[OK]" or "[MISSING:2]"
        """
        is_compliant, missing_tags = self.check_resource_compliance(
            resource_tags, required_tags
        )
        if is_compliant:
            return "[OK]"
        return f"[MISSING:{len(missing_tags)}]"

    @property
    def policy_available(self) -> Optional[bool]:
        """Return whether org policy was available in last check."""
        return self._policy_available

    def clear_cache(self) -> None:
        """Clear the cached policy data."""
        cache = self._get_cache()
        if cache:
            try:
                cache.delete('org_policy:required_tags')
            except Exception as e:
                logger.debug(f"Cache clear failed: {e}")


# Global singleton instance
org_policy_provider = OrgPolicyProvider()
