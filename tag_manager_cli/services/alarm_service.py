"""CloudWatch alarm management service for BlueArch AWS Tags.

Provides CRUD operations for CloudWatch alarms with:
- Tag-based alert routing via OwnerTeamEmail
- Auto-remediation opt-out tagging support
- Audit logging for all operations
- Local state tracking with AWS sync
"""

import json
import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from botocore.exceptions import (
    NoCredentialsError,
    ProfileNotFound,
    ClientError,
    TokenRetrievalError,
)
from rich.console import Console

from ..utils.core_client import request_core

logger = logging.getLogger(__name__)


def _is_credential_error(e: Exception) -> bool:
    """Check if an exception is a credential-related error that should be re-raised."""
    if isinstance(e, (NoCredentialsError, ProfileNotFound, TokenRetrievalError)):
        return True
    if isinstance(e, ClientError):
        error_code = e.response.get('Error', {}).get('Code', '')
        if error_code in ['ExpiredToken', 'InvalidClientTokenId', 'AccessDenied',
                          'UnauthorizedOperation', 'AccessDeniedException']:
            return True
    return False


console = Console()

# Alarm naming prefix
ALARM_NAME_PREFIX = "tag-manager"

# SNS topic naming prefix
SNS_TOPIC_PREFIX = "tag-manager-alerts"

# Standard tags applied to all managed alarms
MANAGED_ALARM_TAGS = {
    "CreatedBy": "tag-manager-cli",
    "ManagedBy": "tag-manager-cli",
}


@dataclass
class AlarmConfig:
    """Configuration for creating a CloudWatch alarm."""
    resource_arn: str
    resource_id: str
    service: str
    template_name: str
    metric_name: str
    namespace: str
    statistic: str
    period: int
    evaluation_periods: int
    threshold: float
    comparison_operator: str
    treat_missing_data: str = "missing"
    dimension_key: str = ""
    dimension_value: str = ""
    owner_email: Optional[str] = None
    auto_remediation: bool = True
    custom_alarm_name: Optional[str] = None
    region: Optional[str] = None
    account_id: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "resource_arn": self.resource_arn,
            "resource_id": self.resource_id,
            "service": self.service,
            "template_name": self.template_name,
            "metric_name": self.metric_name,
            "namespace": self.namespace,
            "statistic": self.statistic,
            "period": self.period,
            "evaluation_periods": self.evaluation_periods,
            "threshold": self.threshold,
            "comparison_operator": self.comparison_operator,
            "treat_missing_data": self.treat_missing_data,
            "dimension_key": self.dimension_key,
            "dimension_value": self.dimension_value,
            "owner_email": self.owner_email,
            "auto_remediation": self.auto_remediation,
            "region": self.region,
            "account_id": self.account_id,
        }


@dataclass
class AlarmResult:
    """Result of an alarm operation."""
    success: bool
    alarm_name: Optional[str] = None
    alarm_arn: Optional[str] = None
    message: str = ""
    error: Optional[str] = None
    details: Optional[Dict[str, Any]] = None


class AlarmService:
    """Service for managing CloudWatch alarms with bluearch-aws-tags integration."""

    def __init__(self):
        self._cloudwatch_client = None
        self._sns_client = None
        self._sts_client = None
        self._current_account_id = None
        self._current_region = None
        self._tables_checked = False
        self._topic_cache: Dict[str, str] = {}  # team_email -> topic_arn

    def _ensure_tables_exist(self) -> None:
        """Ensure the core storage API is reachable before alarm persistence."""
        if self._tables_checked:
            return

        try:
            request_core("GET", "/api/v1/core/db/status", timeout=10.0)
            self._tables_checked = True

        except Exception as e:
            logger.warning(f"Failed to reach core alarm storage: {e}")
            # Don't fail - let the actual operation fail with a clearer error

    def _get_cloudwatch_client(self, region: Optional[str] = None):
        """Get or create CloudWatch client."""
        try:
            from ..utils.aws_auth import aws_auth
            session = aws_auth.initialize_session()
            target_region = region or self._get_current_region()
            return session.client("cloudwatch", region_name=target_region)
        except Exception as e:
            logger.error(f"Failed to create CloudWatch client: {e}")
            raise

    def _get_sns_client(self, region: Optional[str] = None):
        """Get or create SNS client."""
        try:
            from ..utils.aws_auth import aws_auth
            session = aws_auth.initialize_session()
            target_region = region or self._get_current_region()
            return session.client("sns", region_name=target_region)
        except Exception as e:
            logger.error(f"Failed to create SNS client: {e}")
            raise

    def _get_sts_client(self):
        """Get or create STS client."""
        try:
            from ..utils.aws_auth import aws_auth
            session = aws_auth.initialize_session()
            return session.client("sts")
        except Exception as e:
            logger.error(f"Failed to create STS client: {e}")
            raise

    def _get_current_account_id(self) -> str:
        """Get current AWS account ID."""
        if self._current_account_id:
            return self._current_account_id
        try:
            sts = self._get_sts_client()
            self._current_account_id = sts.get_caller_identity()["Account"]
            return self._current_account_id
        except Exception as e:
            logger.error(f"Failed to get account ID: {e}")
            raise

    def _get_current_region(self) -> str:
        """Get current AWS region."""
        if self._current_region:
            return self._current_region
        try:
            from ..utils.aws_auth import aws_auth
            session = aws_auth.initialize_session()
            self._current_region = session.region_name or "us-east-1"
            return self._current_region
        except Exception as e:
            logger.warning(f"Failed to get region, defaulting to us-east-1: {e}")
            return "us-east-1"

    def _build_alarm_name(self, resource_id: str, template_name: str) -> str:
        """Build standardized alarm name."""
        clean_id = resource_id.replace("/", "-").replace(":", "-")
        alarm_name = f"{ALARM_NAME_PREFIX}-{clean_id}-{template_name}".replace("_", "-")
        # CloudWatch alarm name limit is 255 characters
        if len(alarm_name) > 255:
            alarm_name = alarm_name[:255]
        return alarm_name

    def _build_alarm_tags(
        self,
        resource_arn: str,
        template_name: str,
        owner_email: Optional[str] = None,
        auto_remediation: bool = True,
    ) -> Dict[str, str]:
        """Build tags for a managed alarm."""
        tags = {
            **MANAGED_ALARM_TAGS,
            "CreatedAt": datetime.now(timezone.utc).isoformat(),
            "TargetResource": resource_arn,
            "AlertType": template_name,
            "AutoRemediation": "enabled" if auto_remediation else "disabled",
        }
        if owner_email:
            tags["OwnerTeamEmail"] = owner_email
        return tags

    def _get_or_create_team_topic(
        self,
        team_email: str,
        region: Optional[str] = None
    ) -> Tuple[str, bool]:
        """Get or create SNS topic for a team.

        Args:
            team_email: Team email for topic naming and subscription
            region: AWS region for the topic

        Returns:
            Tuple of (topic_arn, was_created)
        """
        # Check cache first
        cache_key = f"{team_email}:{region}"
        if cache_key in self._topic_cache:
            return self._topic_cache[cache_key], False

        try:
            sns = self._get_sns_client(region)

            # Create topic name from email (sanitize for SNS naming rules)
            team_name = team_email.split("@")[0].replace(".", "-").replace("_", "-")
            topic_name = f"{SNS_TOPIC_PREFIX}-{team_name}"

            # SNS topic name limit is 256 characters
            if len(topic_name) > 256:
                topic_name = topic_name[:256]

            # Create topic (idempotent - returns existing if already exists)
            response = sns.create_topic(
                Name=topic_name,
                Tags=[
                    {"Key": "CreatedBy", "Value": "tag-manager-cli"},
                    {"Key": "ManagedBy", "Value": "tag-manager-cli"},
                    {"Key": "TeamEmail", "Value": team_email},
                ]
            )
            topic_arn = response["TopicArn"]

            # Check if email subscription exists
            subscriptions = sns.list_subscriptions_by_topic(TopicArn=topic_arn)
            email_subscribed = any(
                sub["Protocol"] == "email" and sub["Endpoint"] == team_email
                for sub in subscriptions.get("Subscriptions", [])
            )

            was_created = not email_subscribed

            # Subscribe email if not already subscribed
            if not email_subscribed:
                sns.subscribe(
                    TopicArn=topic_arn,
                    Protocol="email",
                    Endpoint=team_email,
                )
                logger.info(f"Created email subscription for {team_email} to topic {topic_name}")

            # Cache the topic ARN
            self._topic_cache[cache_key] = topic_arn

            return topic_arn, was_created

        except Exception as e:
            logger.error(f"Failed to get/create SNS topic for {team_email}: {e}")
            raise

    def create_alarm(
        self,
        config: AlarmConfig,
        dry_run: bool = False,
        executed_by: str = "cli",
        executed_via: str = "cli",
    ) -> AlarmResult:
        """Create a CloudWatch alarm with proper tagging.

        Args:
            config: Alarm configuration
            dry_run: If True, only validate and return preview without creating
            executed_by: Who executed this operation (for audit)
            executed_via: How this was executed (cli, ai_assistant, etc.)

        Returns:
            AlarmResult with success status and details
        """
        try:
            # Determine alarm name
            alarm_name = config.custom_alarm_name or self._build_alarm_name(
                config.resource_id, config.template_name
            )

            # Determine region and account
            region = config.region or self._get_current_region()
            account_id = config.account_id or self._get_current_account_id()

            # Build alarm tags
            alarm_tags = self._build_alarm_tags(
                config.resource_arn,
                config.template_name,
                config.owner_email,
                config.auto_remediation,
            )

            # Get SNS topic for notifications if owner email provided
            alarm_actions = []
            sns_topic_arn = None
            if config.owner_email:
                sns_topic_arn, topic_created = self._get_or_create_team_topic(
                    config.owner_email, region
                )
                alarm_actions.append(sns_topic_arn)

            # Build dimensions
            dimensions = []
            if config.dimension_key and config.dimension_value:
                dimensions.append({
                    "Name": config.dimension_key,
                    "Value": config.dimension_value,
                })

            # Build alarm description
            description = (
                f"Managed by tag-manager-cli. "
                f"Alert type: {config.template_name}. "
                f"Target: {config.resource_arn}"
            )
            if config.owner_email:
                description += f". Owner: {config.owner_email}"

            # Prepare alarm parameters
            alarm_params = {
                "AlarmName": alarm_name,
                "AlarmDescription": description,
                "MetricName": config.metric_name,
                "Namespace": config.namespace,
                "Statistic": config.statistic,
                "Period": config.period,
                "EvaluationPeriods": config.evaluation_periods,
                "Threshold": config.threshold,
                "ComparisonOperator": config.comparison_operator,
                "TreatMissingData": config.treat_missing_data,
                "Tags": [{"Key": k, "Value": v} for k, v in alarm_tags.items()],
            }

            if dimensions:
                alarm_params["Dimensions"] = dimensions

            if alarm_actions:
                alarm_params["AlarmActions"] = alarm_actions
                alarm_params["OKActions"] = alarm_actions

            # Build preview for dry run or confirmation
            preview = {
                "alarm_name": alarm_name,
                "target_resource": config.resource_arn,
                "metric": f"{config.namespace}/{config.metric_name}",
                "condition": f"{config.statistic} {config.comparison_operator} {config.threshold}",
                "period": f"{config.period}s x {config.evaluation_periods} periods",
                "sns_topic": sns_topic_arn,
                "tags": alarm_tags,
                "region": region,
                "account_id": account_id,
            }

            if dry_run:
                return AlarmResult(
                    success=True,
                    alarm_name=alarm_name,
                    message="Dry run - alarm not created",
                    details={"preview": preview, "params": alarm_params}
                )

            # Create the alarm
            cloudwatch = self._get_cloudwatch_client(region)
            cloudwatch.put_metric_alarm(**alarm_params)

            # Get the alarm ARN
            alarm_arn = f"arn:aws:cloudwatch:{region}:{account_id}:alarm:{alarm_name}"

            # Save to local database
            self._save_alarm_to_db(
                alarm_name=alarm_name,
                alarm_arn=alarm_arn,
                config=config,
                alarm_tags=alarm_tags,
                alarm_actions=alarm_actions,
                region=region,
                account_id=account_id,
                executed_by=executed_by,
                executed_via=executed_via,
            )

            # Log audit entry
            self._log_audit(
                alarm_name=alarm_name,
                alarm_arn=alarm_arn,
                operation="create",
                success=True,
                new_configuration=config.to_dict(),
                executed_by=executed_by,
                executed_via=executed_via,
            )

            return AlarmResult(
                success=True,
                alarm_name=alarm_name,
                alarm_arn=alarm_arn,
                message=f"Successfully created alarm: {alarm_name}",
                details={"preview": preview}
            )

        except Exception as e:
            error_msg = str(e)
            logger.error(f"Failed to create alarm: {error_msg}")

            # Log failed audit entry
            self._log_audit(
                alarm_name=config.custom_alarm_name or "unknown",
                operation="create",
                success=False,
                error_message=error_msg,
                new_configuration=config.to_dict(),
                executed_by=executed_by,
                executed_via=executed_via,
            )

            return AlarmResult(
                success=False,
                message="Failed to create alarm",
                error=error_msg
            )

    def delete_alarm(
        self,
        alarm_name: str,
        region: Optional[str] = None,
        executed_by: str = "cli",
        executed_via: str = "cli",
    ) -> AlarmResult:
        """Delete a CloudWatch alarm.

        Args:
            alarm_name: Name of the alarm to delete
            region: AWS region (uses default if not specified)
            executed_by: Who executed this operation
            executed_via: How this was executed

        Returns:
            AlarmResult with success status
        """
        try:
            region = region or self._get_current_region()
            cloudwatch = self._get_cloudwatch_client(region)

            # Get alarm details before deletion for audit
            old_config = None
            alarm_arn = None
            try:
                response = cloudwatch.describe_alarms(AlarmNames=[alarm_name])
                if response.get("MetricAlarms"):
                    alarm = response["MetricAlarms"][0]
                    alarm_arn = alarm.get("AlarmArn")
                    old_config = {
                        "metric_name": alarm.get("MetricName"),
                        "namespace": alarm.get("Namespace"),
                        "threshold": alarm.get("Threshold"),
                    }
            except Exception:
                pass

            # Delete the alarm
            cloudwatch.delete_alarms(AlarmNames=[alarm_name])

            # Update local database
            self._mark_alarm_deleted_in_db(alarm_name, region)

            # Log audit entry
            self._log_audit(
                alarm_name=alarm_name,
                alarm_arn=alarm_arn,
                operation="delete",
                success=True,
                old_configuration=old_config,
                executed_by=executed_by,
                executed_via=executed_via,
            )

            return AlarmResult(
                success=True,
                alarm_name=alarm_name,
                message=f"Successfully deleted alarm: {alarm_name}"
            )

        except Exception as e:
            error_msg = str(e)
            logger.error(f"Failed to delete alarm {alarm_name}: {error_msg}")

            self._log_audit(
                alarm_name=alarm_name,
                operation="delete",
                success=False,
                error_message=error_msg,
                executed_by=executed_by,
                executed_via=executed_via,
            )

            return AlarmResult(
                success=False,
                alarm_name=alarm_name,
                message="Failed to delete alarm",
                error=error_msg
            )

    def list_alarms(
        self,
        service: Optional[str] = None,
        resource_arn: Optional[str] = None,
        state: Optional[str] = None,
        region: Optional[str] = None,
        managed_only: bool = True,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        """List CloudWatch alarms with optional filters.

        Args:
            service: Filter by target service (ec2, rds, lambda, etc.)
            resource_arn: Filter by target resource ARN
            state: Filter by alarm state (OK, ALARM, INSUFFICIENT_DATA)
            region: AWS region (uses default if not specified)
            managed_only: Only return alarms managed by tag-manager-cli
            limit: Maximum alarms to return

        Returns:
            List of alarm details
        """
        try:
            region = region or self._get_current_region()
            cloudwatch = self._get_cloudwatch_client(region)

            # Build request parameters
            params = {"MaxRecords": min(limit, 100)}
            if state:
                params["StateValue"] = state

            alarms = []
            paginator = cloudwatch.get_paginator("describe_alarms")

            for page in paginator.paginate(**params):
                for alarm in page.get("MetricAlarms", []):
                    alarm_name = alarm.get("AlarmName", "")

                    # Filter by managed_only (check if name starts with prefix)
                    if managed_only and not alarm_name.startswith(ALARM_NAME_PREFIX):
                        continue

                    # Get tags for additional filtering
                    alarm_arn = alarm.get("AlarmArn", "")
                    tags = {}
                    try:
                        tag_response = cloudwatch.list_tags_for_resource(
                            ResourceARN=alarm_arn
                        )
                        tags = {
                            t["Key"]: t["Value"]
                            for t in tag_response.get("Tags", [])
                        }
                    except Exception:
                        pass

                    # Apply filters
                    if service:
                        target = tags.get("TargetResource", "")
                        if f":{service}:" not in target.lower():
                            continue

                    if resource_arn:
                        if tags.get("TargetResource") != resource_arn:
                            continue

                    alarms.append({
                        "alarm_name": alarm_name,
                        "alarm_arn": alarm_arn,
                        "state": alarm.get("StateValue"),
                        "state_reason": alarm.get("StateReason"),
                        "metric_name": alarm.get("MetricName"),
                        "namespace": alarm.get("Namespace"),
                        "threshold": alarm.get("Threshold"),
                        "comparison_operator": alarm.get("ComparisonOperator"),
                        "period": alarm.get("Period"),
                        "evaluation_periods": alarm.get("EvaluationPeriods"),
                        "statistic": alarm.get("Statistic"),
                        "dimensions": alarm.get("Dimensions", []),
                        "alarm_actions": alarm.get("AlarmActions", []),
                        "target_resource": tags.get("TargetResource"),
                        "owner_email": tags.get("OwnerTeamEmail"),
                        "alert_type": tags.get("AlertType"),
                        "auto_remediation": tags.get("AutoRemediation"),
                        "created_at": tags.get("CreatedAt"),
                        "tags": tags,
                    })

                    if len(alarms) >= limit:
                        break

                if len(alarms) >= limit:
                    break

            return alarms

        except Exception as e:
            # Re-raise credential/auth errors so they can be handled by error_handlers
            if _is_credential_error(e):
                raise
            logger.error(f"Failed to list alarms: {e}")
            return []

    def suggest_alarms_for_resource(
        self,
        resource_arn: str,
    ) -> List[Dict[str, Any]]:
        """Suggest alarm templates for a given resource.

        Args:
            resource_arn: AWS ARN of the resource

        Returns:
            List of suggested alarm templates
        """
        from ..templates.alarm_templates import (
            extract_service_from_arn,
            extract_resource_id_from_arn,
            suggest_templates_for_service,
        )

        service = extract_service_from_arn(resource_arn)
        if not service:
            return []

        resource_id = extract_resource_id_from_arn(resource_arn)

        templates = suggest_templates_for_service(service)

        # Add resource-specific context
        for template in templates:
            template["resource_arn"] = resource_arn
            template["resource_id"] = resource_id
            template["suggested_alarm_name"] = self._build_alarm_name(
                resource_id or "resource",
                template["template_name"]
            )

        return templates

    def get_alarm_templates(
        self,
        service: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """Get available alarm templates.

        Args:
            service: Filter by service name (optional)

        Returns:
            List of template definitions
        """
        from ..templates.alarm_templates import (
            get_template_summary,
            suggest_templates_for_service,
        )

        if service:
            return suggest_templates_for_service(service)

        return get_template_summary()

    def sync_alarms(
        self,
        region: Optional[str] = None
    ) -> Dict[str, Any]:
        """Sync local alarm state with AWS.

        Args:
            region: AWS region to sync

        Returns:
            Dict with sync results
        """
        try:
            region = region or self._get_current_region()

            # Get alarms from AWS
            aws_alarms = self.list_alarms(
                region=region,
                managed_only=True,
                limit=500
            )

            # Get alarms from local database
            local_alarms = self._get_local_alarms(region)

            # Build sets for comparison
            aws_names = {a["alarm_name"] for a in aws_alarms}
            local_names = {a["alarm_name"] for a in local_alarms}

            # Find differences
            missing_in_aws = local_names - aws_names
            missing_in_local = aws_names - local_names

            # Update local state
            synced = 0
            for alarm_name in missing_in_aws:
                self._mark_alarm_deleted_in_db(alarm_name, region)
                synced += 1

            for alarm in aws_alarms:
                if alarm["alarm_name"] in missing_in_local:
                    self._save_discovered_alarm_to_db(alarm, region)
                    synced += 1
                else:
                    # Update existing alarm state
                    self._update_alarm_state_in_db(
                        alarm["alarm_name"],
                        alarm["state"],
                        region
                    )

            return {
                "success": True,
                "region": region,
                "aws_alarms": len(aws_alarms),
                "local_alarms": len(local_alarms),
                "missing_in_aws": list(missing_in_aws),
                "missing_in_local": list(missing_in_local),
                "synced": synced,
            }

        except Exception as e:
            # Re-raise credential/auth errors so they can be handled by error_handlers
            if _is_credential_error(e):
                raise
            logger.error(f"Failed to sync alarms: {e}")
            return {
                "success": False,
                "error": str(e),
            }

    def _save_alarm_to_db(
        self,
        alarm_name: str,
        alarm_arn: str,
        config: AlarmConfig,
        alarm_tags: Dict[str, str],
        alarm_actions: List[str],
        region: str,
        account_id: str,
        executed_by: str,
        executed_via: str,
    ) -> None:
        """Save created alarm to local database."""
        self._ensure_tables_exist()
        try:
            _upsert_alarm_by_arn(
                alarm_arn,
                {
                    "alarm_name": alarm_name,
                    "alarm_arn": alarm_arn,
                    "target_resource_arn": config.resource_arn,
                    "target_resource_type": config.service,
                    "target_service": config.service,
                    "region": region,
                    "account_id": account_id,
                    "alarm_type": config.template_name,
                    "metric_name": config.metric_name,
                    "namespace": config.namespace,
                    "statistic": config.statistic,
                    "period": config.period,
                    "evaluation_periods": config.evaluation_periods,
                    "threshold": str(config.threshold),
                    "comparison_operator": config.comparison_operator,
                    "treat_missing_data": config.treat_missing_data,
                    "alarm_actions": alarm_actions,
                    "alarm_tags": alarm_tags,
                    "current_state": "UNKNOWN",
                    "created_by": executed_by,
                    "created_via": executed_via,
                    "synced_with_aws": True,
                    "last_synced_at": datetime.now(timezone.utc).isoformat(),
                    "aws_exists": True,
                },
            )
        except Exception as e:
            logger.warning(f"Failed to save alarm to database: {e}")

    def _mark_alarm_deleted_in_db(self, alarm_name: str, region: str) -> None:
        """Mark alarm as deleted in local database."""
        self._ensure_tables_exist()
        try:
            alarm = _get_alarm_by_name_region(alarm_name, region)
            if alarm:
                _update_alarm_record(
                    alarm,
                    {
                        "aws_exists": False,
                        "synced_with_aws": True,
                        "last_synced_at": datetime.now(timezone.utc).isoformat(),
                    },
                )
        except Exception as e:
            logger.warning(f"Failed to update alarm in database: {e}")

    def _update_alarm_state_in_db(
        self,
        alarm_name: str,
        state: str,
        region: str
    ) -> None:
        """Update alarm state in local database."""
        self._ensure_tables_exist()
        try:
            alarm = _get_alarm_by_name_region(alarm_name, region)
            if alarm:
                now = datetime.now(timezone.utc).isoformat()
                _update_alarm_record(
                    alarm,
                    {
                        "current_state": state,
                        "state_updated_at": now,
                        "synced_with_aws": True,
                        "last_synced_at": now,
                        "aws_exists": True,
                    },
                )
        except Exception as e:
            logger.warning(f"Failed to update alarm state in database: {e}")

    def _save_discovered_alarm_to_db(
        self,
        alarm: Dict[str, Any],
        region: str
    ) -> None:
        """Save discovered alarm from AWS to local database."""
        self._ensure_tables_exist()
        try:
            account_id = self._get_current_account_id()

            _upsert_alarm_by_arn(
                alarm["alarm_arn"],
                {
                    "alarm_name": alarm["alarm_name"],
                    "alarm_arn": alarm["alarm_arn"],
                    "target_resource_arn": alarm.get("target_resource", ""),
                    "target_resource_type": alarm.get("alert_type", ""),
                    "target_service": alarm.get("alert_type", "").split("_")[0] if alarm.get("alert_type") else "",
                    "region": region,
                    "account_id": account_id,
                    "alarm_type": alarm.get("alert_type", ""),
                    "metric_name": alarm.get("metric_name", ""),
                    "namespace": alarm.get("namespace", ""),
                    "statistic": alarm.get("statistic", "Average"),
                    "period": alarm.get("period", 300),
                    "evaluation_periods": alarm.get("evaluation_periods", 2),
                    "threshold": str(alarm.get("threshold", 0)),
                    "comparison_operator": alarm.get("comparison_operator", ""),
                    "alarm_actions": alarm.get("alarm_actions", []),
                    "alarm_tags": alarm.get("tags", {}),
                    "current_state": alarm.get("state", "UNKNOWN"),
                    "created_by": "discovered",
                    "created_via": "sync",
                    "synced_with_aws": True,
                    "last_synced_at": datetime.now(timezone.utc).isoformat(),
                    "aws_exists": True,
                },
            )
        except Exception as e:
            logger.warning(f"Failed to save discovered alarm to database: {e}")

    def _get_local_alarms(self, region: str) -> List[Dict[str, Any]]:
        """Get alarms from local database."""
        self._ensure_tables_exist()
        try:
            alarms = _list_alarm_records(filters=[("region", region), ("aws_exists", "true")], limit=10000)
            return [
                {
                    "alarm_name": alarm.get("alarm_name"),
                    "alarm_arn": alarm.get("alarm_arn"),
                    "state": alarm.get("current_state"),
                }
                for alarm in alarms
            ]

        except Exception as e:
            logger.warning(f"Failed to get local alarms: {e}")
            return []

    def _log_audit(
        self,
        alarm_name: str,
        operation: str,
        success: bool,
        alarm_arn: Optional[str] = None,
        old_configuration: Optional[Dict] = None,
        new_configuration: Optional[Dict] = None,
        error_message: Optional[str] = None,
        executed_by: str = "cli",
        executed_via: str = "cli",
    ) -> None:
        """Log alarm operation to audit trail."""
        self._ensure_tables_exist()
        try:
            alarm_id = None
            if alarm_arn:
                alarm = _get_alarm_by_arn(alarm_arn)
                if alarm:
                    alarm_id = str(alarm.get("id") or alarm.get("record_key"))

            _create_alarm_audit_record(
                {
                    "alarm_id": alarm_id,
                    "alarm_name": alarm_name,
                    "alarm_arn": alarm_arn,
                    "operation": operation,
                    "old_configuration": old_configuration,
                    "new_configuration": new_configuration,
                    "success": success,
                    "error_message": error_message,
                    "executed_by": executed_by,
                    "executed_via": executed_via,
                }
            )

        except Exception as e:
            logger.warning(f"Failed to log audit entry: {e}")


def _storage_path(collection: str, record_key: str | None = None) -> str:
    path = f"/api/v1/storage/tag-manager/{collection}"
    if record_key:
        path = f"{path}/{record_key}"
    return path


def _payload_from_record(record: Dict[str, Any]) -> Dict[str, Any]:
    payload = dict((record or {}).get("payload", record) or {})
    payload.setdefault("id", (record or {}).get("id") or (record or {}).get("record_key") or payload.get("id"))
    payload.setdefault("record_key", (record or {}).get("record_key") or payload.get("id"))
    return payload


def _list_storage_payloads(
    collection: str,
    *,
    filters: list[tuple[str, str]] | None = None,
    limit: int = 1000,
) -> List[Dict[str, Any]]:
    params: list[tuple[str, str | int]] = [("limit", limit)]
    for key, value in filters or []:
        params.append(("filter", f"{key}={value}"))
    records = request_core(
        "GET",
        _storage_path(collection),
        service_token=True,
        params=params,
        timeout=10.0,
    )
    return [_payload_from_record(record) for record in records or []]


def _create_storage_payload(collection: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    record = request_core(
        "POST",
        _storage_path(collection),
        service_token=True,
        json={"payload": payload},
        timeout=10.0,
    )
    return _payload_from_record(record)


def _update_storage_payload(collection: str, row: Dict[str, Any], payload: Dict[str, Any]) -> Dict[str, Any]:
    record_key = row.get("record_key") or row.get("id")
    if not record_key:
        raise RuntimeError(f"Cannot update {collection} without a record key")
    record = request_core(
        "PUT",
        _storage_path(collection, str(record_key)),
        service_token=True,
        json={"payload": {**row, **payload}},
        timeout=10.0,
    )
    return _payload_from_record(record)


def _list_alarm_records(
    *,
    filters: list[tuple[str, str]] | None = None,
    limit: int = 1000,
) -> List[Dict[str, Any]]:
    return _list_storage_payloads("cloudwatch-alarms", filters=filters, limit=limit)


def _get_alarm_by_arn(alarm_arn: str) -> Optional[Dict[str, Any]]:
    rows = _list_alarm_records(filters=[("alarm_arn", alarm_arn)], limit=1)
    return rows[0] if rows else None


def _get_alarm_by_name_region(alarm_name: str, region: str) -> Optional[Dict[str, Any]]:
    rows = _list_alarm_records(filters=[("alarm_name", alarm_name), ("region", region)], limit=1)
    return rows[0] if rows else None


def _upsert_alarm_by_arn(alarm_arn: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    row = _get_alarm_by_arn(alarm_arn)
    if row:
        return _update_alarm_record(row, payload)
    return _create_storage_payload("cloudwatch-alarms", payload)


def _update_alarm_record(row: Dict[str, Any], payload: Dict[str, Any]) -> Dict[str, Any]:
    return _update_storage_payload("cloudwatch-alarms", row, payload)


def _create_alarm_audit_record(payload: Dict[str, Any]) -> Dict[str, Any]:
    return _create_storage_payload("alarm-audit-log", payload)


# Global singleton
alarm_service = AlarmService()
