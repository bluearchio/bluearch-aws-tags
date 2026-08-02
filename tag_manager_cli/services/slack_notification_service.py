"""Slack notification service for lifecycle management.

Uses Slack Incoming Webhooks for simple notification delivery.
No external dependencies required beyond requests.

Configuration is stored in ~/.tag-manager/config.json
"""

import json
import logging
import os
import urllib.request
import urllib.error
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# Config file path
CONFIG_DIR = Path.home() / ".tag-manager"
CONFIG_FILE = CONFIG_DIR / "config.json"


@dataclass
class SlackConfig:
    """Slack notification configuration."""

    webhook_url: str = ""
    channel: str = "#aws-alerts"  # Display only, webhook determines actual channel
    warning_days: List[int] = field(default_factory=lambda: [7, 3, 1])
    enabled: bool = True
    include_resource_details: bool = True
    max_resources_per_message: int = 10

    def to_dict(self) -> Dict[str, Any]:
        return {
            "webhook_url": self.webhook_url,
            "channel": self.channel,
            "warning_days": self.warning_days,
            "enabled": self.enabled,
            "include_resource_details": self.include_resource_details,
            "max_resources_per_message": self.max_resources_per_message,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SlackConfig":
        return cls(
            webhook_url=data.get("webhook_url", ""),
            channel=data.get("channel", "#aws-alerts"),
            warning_days=data.get("warning_days", [7, 3, 1]),
            enabled=data.get("enabled", True),
            include_resource_details=data.get("include_resource_details", True),
            max_resources_per_message=data.get("max_resources_per_message", 10),
        )


@dataclass
class NotificationResult:
    """Result of sending a notification."""

    success: bool
    message: str
    response_code: Optional[int] = None
    error_details: Optional[str] = None


class SlackNotificationService:
    """Service for sending Slack notifications via webhooks."""

    def __init__(self):
        self._config: Optional[SlackConfig] = None

    def _load_config(self) -> SlackConfig:
        """Load configuration from file."""
        if self._config is not None:
            return self._config

        if CONFIG_FILE.exists():
            try:
                with open(CONFIG_FILE, "r") as f:
                    data = json.load(f)
                    slack_config = data.get("slack", {})
                    self._config = SlackConfig.from_dict(slack_config)
            except (json.JSONDecodeError, IOError) as e:
                logger.warning(f"Failed to load config: {e}")
                self._config = SlackConfig()
        else:
            self._config = SlackConfig()

        return self._config

    def _save_config(self, config: SlackConfig) -> bool:
        """Save configuration to file."""
        try:
            CONFIG_DIR.mkdir(parents=True, exist_ok=True)

            # Load existing config to preserve other settings
            existing = {}
            if CONFIG_FILE.exists():
                with open(CONFIG_FILE, "r") as f:
                    existing = json.load(f)

            existing["slack"] = config.to_dict()

            with open(CONFIG_FILE, "w") as f:
                json.dump(existing, f, indent=2)

            self._config = config
            return True
        except IOError as e:
            logger.error(f"Failed to save config: {e}")
            return False

    def get_config(self) -> SlackConfig:
        """Get current Slack configuration."""
        return self._load_config()

    def configure(
        self,
        webhook_url: str,
        channel: str = "#aws-alerts",
        warning_days: Optional[List[int]] = None,
        enabled: bool = True,
    ) -> Tuple[bool, str]:
        """Configure Slack notifications.

        Args:
            webhook_url: Slack incoming webhook URL
            channel: Channel name (display only)
            warning_days: Days before expiry to send warnings
            enabled: Whether notifications are enabled

        Returns:
            Tuple of (success, message)
        """
        if not webhook_url.startswith("https://hooks.slack.com/"):
            return (False, "Invalid webhook URL. Must start with https://hooks.slack.com/")

        config = SlackConfig(
            webhook_url=webhook_url,
            channel=channel,
            warning_days=warning_days or [7, 3, 1],
            enabled=enabled,
        )

        if self._save_config(config):
            return (True, "Slack configuration saved successfully")
        return (False, "Failed to save configuration")

    def is_configured(self) -> bool:
        """Check if Slack is configured."""
        config = self._load_config()
        return bool(config.webhook_url) and config.enabled

    def test_webhook(self, webhook_url: Optional[str] = None) -> NotificationResult:
        """Test the webhook by sending a test message.

        Args:
            webhook_url: Optional webhook URL to test (uses configured if not provided)

        Returns:
            NotificationResult with success/failure details
        """
        url = webhook_url or self._load_config().webhook_url

        if not url:
            return NotificationResult(
                success=False,
                message="No webhook URL configured",
            )

        payload = {
            "text": "[TAG-MANAGER] Test Notification",
            "blocks": [
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": "*[TAG-MANAGER] Test Notification*\n\nThis is a test message from AWS Tag Manager CLI.\nSlack notifications are working correctly!",
                    },
                },
                {
                    "type": "context",
                    "elements": [
                        {
                            "type": "mrkdwn",
                            "text": f"Sent at: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}",
                        }
                    ],
                },
            ],
        }

        return self._send_webhook(url, payload)

    def _send_webhook(self, url: str, payload: Dict[str, Any]) -> NotificationResult:
        """Send a payload to the Slack webhook.

        Args:
            url: Webhook URL
            payload: JSON payload to send

        Returns:
            NotificationResult
        """
        try:
            data = json.dumps(payload).encode("utf-8")
            req = urllib.request.Request(
                url,
                data=data,
                headers={"Content-Type": "application/json"},
                method="POST",
            )

            import ssl
            ssl_ctx = ssl.create_default_context()
            try:
                import certifi
                ssl_ctx.load_verify_locations(certifi.where())
            except ImportError:
                pass
            with urllib.request.urlopen(req, timeout=30, context=ssl_ctx) as response:
                status = response.getcode()
                body = response.read().decode("utf-8")

                if status == 200 and body == "ok":
                    return NotificationResult(
                        success=True,
                        message="Notification sent successfully",
                        response_code=status,
                    )
                else:
                    return NotificationResult(
                        success=False,
                        message=f"Unexpected response: {body}",
                        response_code=status,
                        error_details=body,
                    )

        except urllib.error.HTTPError as e:
            return NotificationResult(
                success=False,
                message=f"HTTP error: {e.code}",
                response_code=e.code,
                error_details=str(e.reason),
            )
        except urllib.error.URLError as e:
            return NotificationResult(
                success=False,
                message=f"Connection error: {e.reason}",
                error_details=str(e.reason),
            )
        except Exception as e:
            return NotificationResult(
                success=False,
                message=f"Error sending notification: {str(e)}",
                error_details=str(e),
            )

    def send_expiration_warning(
        self,
        resources: List[Dict[str, Any]],
        days_until_expiry: int,
        batch_id: Optional[str] = None,
    ) -> NotificationResult:
        """Send expiration warning notification for resources.

        Args:
            resources: List of resource dicts with keys: resource_arn, resource_id,
                      service_name, region, expires_at
            days_until_expiry: Days until expiration (for message title)
            batch_id: Optional batch ID for tracking

        Returns:
            NotificationResult
        """
        config = self._load_config()

        if not config.webhook_url or not config.enabled:
            return NotificationResult(
                success=False,
                message="Slack notifications not configured or disabled",
            )

        if not resources:
            return NotificationResult(
                success=False,
                message="No resources to notify about",
            )

        # Build message
        if days_until_expiry <= 0:
            title = f"*[TAG-MANAGER] {len(resources)} Resources EXPIRED*"
            urgency = ":rotating_light:"
        elif days_until_expiry == 1:
            title = f"*[TAG-MANAGER] {len(resources)} Resources Expiring TOMORROW*"
            urgency = ":warning:"
        else:
            title = f"*[TAG-MANAGER] {len(resources)} Resources Expiring in {days_until_expiry} Days*"
            urgency = ":clock3:"

        blocks = [
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"{urgency} {title}",
                },
            },
        ]

        # Add resource details
        if config.include_resource_details:
            resource_lines = []
            for r in resources[: config.max_resources_per_message]:
                service = r.get("service_name", "unknown").upper()
                resource_id = r.get("resource_id", r.get("resource_arn", "unknown"))
                region = r.get("region", "")

                # Truncate long IDs
                if len(resource_id) > 40:
                    resource_id = resource_id[:37] + "..."

                resource_lines.append(f"- `{service}` {resource_id} ({region})")

            if len(resources) > config.max_resources_per_message:
                resource_lines.append(
                    f"_... and {len(resources) - config.max_resources_per_message} more_"
                )

            blocks.append(
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": "\n".join(resource_lines),
                    },
                }
            )

        # Add action hint
        blocks.append(
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": "*Actions:* Run `bluearch-aws-tags lifecycle review` to extend, protect, or delete these resources.",
                },
            }
        )

        # Add context
        context_text = f"Sent: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}"
        if batch_id:
            context_text += f" | Batch: {batch_id[:8]}"

        blocks.append(
            {
                "type": "context",
                "elements": [{"type": "mrkdwn", "text": context_text}],
            }
        )

        payload = {"blocks": blocks}

        return self._send_webhook(config.webhook_url, payload)

    def send_batch_summary(
        self,
        summary: Dict[str, Any],
        batch_id: Optional[str] = None,
    ) -> NotificationResult:
        """Send a daily/batch summary notification.

        Args:
            summary: Dict with keys: total_resources, expired, expiring_7d,
                    expiring_3d, expiring_1d, protected, deleted
            batch_id: Optional batch ID

        Returns:
            NotificationResult
        """
        config = self._load_config()

        if not config.webhook_url or not config.enabled:
            return NotificationResult(
                success=False,
                message="Slack notifications not configured or disabled",
            )

        total = summary.get("total_resources", 0)
        expired = summary.get("expired", 0)
        exp_7d = summary.get("expiring_7d", 0)
        exp_3d = summary.get("expiring_3d", 0)
        exp_1d = summary.get("expiring_1d", 0)
        protected = summary.get("protected", 0)

        # Determine urgency
        if expired > 0:
            urgency = ":rotating_light:"
            status = "ACTION REQUIRED"
        elif exp_1d > 0:
            urgency = ":warning:"
            status = "Urgent"
        elif exp_3d > 0:
            urgency = ":clock3:"
            status = "Attention Needed"
        else:
            urgency = ":white_check_mark:"
            status = "All Clear"

        blocks = [
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"{urgency} *[TAG-MANAGER] Lifecycle Summary - {status}*",
                },
            },
            {
                "type": "section",
                "fields": [
                    {"type": "mrkdwn", "text": f"*Total with TTL:*\n{total}"},
                    {"type": "mrkdwn", "text": f"*Protected:*\n{protected}"},
                    {"type": "mrkdwn", "text": f"*Expired:*\n{expired}"},
                    {"type": "mrkdwn", "text": f"*Expiring 1d:*\n{exp_1d}"},
                    {"type": "mrkdwn", "text": f"*Expiring 3d:*\n{exp_3d}"},
                    {"type": "mrkdwn", "text": f"*Expiring 7d:*\n{exp_7d}"},
                ],
            },
        ]

        if expired > 0 or exp_1d > 0 or exp_3d > 0:
            blocks.append(
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": "*Actions:* Run `bluearch-aws-tags lifecycle review` or `bluearch-aws-tags lifecycle scan` to manage resources.",
                    },
                }
            )

        # Context
        context_text = f"Generated: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}"
        if batch_id:
            context_text += f" | Batch: {batch_id[:8]}"

        blocks.append(
            {
                "type": "context",
                "elements": [{"type": "mrkdwn", "text": context_text}],
            }
        )

        payload = {"blocks": blocks}

        return self._send_webhook(config.webhook_url, payload)

    def disable(self) -> Tuple[bool, str]:
        """Disable Slack notifications."""
        config = self._load_config()
        config.enabled = False
        if self._save_config(config):
            return (True, "Slack notifications disabled")
        return (False, "Failed to update configuration")

    def enable(self) -> Tuple[bool, str]:
        """Enable Slack notifications."""
        config = self._load_config()
        if not config.webhook_url:
            return (False, "Cannot enable: No webhook URL configured. Run notify-setup first.")
        config.enabled = True
        if self._save_config(config):
            return (True, "Slack notifications enabled")
        return (False, "Failed to update configuration")


# Global singleton
slack_notification_service = SlackNotificationService()
