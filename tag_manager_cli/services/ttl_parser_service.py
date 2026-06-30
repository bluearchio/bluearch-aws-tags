"""TTL (Time-To-Live) tag parser service for lifecycle management.

Parses and validates TTL tag values from AWS resources in various formats:
- Duration: "30d", "6m", "1y", "2w", "24h"
- ISO date: "2025-03-15", "2025-03-15T14:30:00Z"
- Unix timestamp: "1742054400"

Supported tag names (in priority order):
- tag-manager:TTL, tag-manager:ExpireAfter, tag-manager:DeleteAfter
- TTL, ExpirationDate, DeleteAfter (compatibility)
"""

import logging
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# Supported TTL tag names in priority order
TTL_TAG_NAMES = [
    # tag-manager namespace (preferred)
    "tag-manager:TTL",
    "tag-manager:ExpireAfter",
    "tag-manager:DeleteAfter",
    # Common tag names (compatibility)
    "TTL",
    "ExpirationDate",
    "DeleteAfter",
    "Expires",
    "ExpireDate",
    "ttl",
    "expiration-date",
    "delete-after",
]

# Duration regex patterns
DURATION_PATTERNS = [
    (re.compile(r"^(\d+)\s*y(?:ears?)?$", re.IGNORECASE), "years"),
    (re.compile(r"^(\d+)\s*mo(?:nths?)?$", re.IGNORECASE), "months"),
    (re.compile(r"^(\d+)\s*m$"), "months"),  # "6m" = 6 months (case sensitive)
    (re.compile(r"^(\d+)\s*w(?:eeks?)?$", re.IGNORECASE), "weeks"),
    (re.compile(r"^(\d+)\s*d(?:ays?)?$", re.IGNORECASE), "days"),
    (re.compile(r"^(\d+)\s*h(?:ours?)?$", re.IGNORECASE), "hours"),
    (re.compile(r"^(\d+)\s*M$"), "minutes"),  # Case sensitive: "30M" = minutes
]

# ISO date patterns
ISO_DATE_PATTERNS = [
    # Full ISO with timezone
    re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:?\d{2})$"),
    # ISO without timezone
    re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?$"),
    # Date only
    re.compile(r"^\d{4}-\d{2}-\d{2}$"),
    # US format with slashes
    re.compile(r"^\d{2}/\d{2}/\d{4}$"),
]


@dataclass
class TTLParseResult:
    """Result of parsing a TTL tag value."""

    expires_at: Optional[datetime]
    is_valid: bool
    error_message: Optional[str]
    source_format: Optional[str]  # 'duration', 'iso_date', 'timestamp'
    original_value: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "expires_at": self.expires_at.isoformat() if self.expires_at else None,
            "is_valid": self.is_valid,
            "error_message": self.error_message,
            "source_format": self.source_format,
            "original_value": self.original_value,
        }


@dataclass
class TTLExtractionResult:
    """Result of extracting TTL from resource tags."""

    expires_at: Optional[datetime]
    tag_key: Optional[str]
    tag_value: Optional[str]
    source_format: Optional[str]
    is_valid: bool
    error_message: Optional[str]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "expires_at": self.expires_at.isoformat() if self.expires_at else None,
            "tag_key": self.tag_key,
            "tag_value": self.tag_value,
            "source_format": self.source_format,
            "is_valid": self.is_valid,
            "error_message": self.error_message,
        }


class TTLParserService:
    """Service for parsing and validating TTL tag values."""

    def __init__(self):
        self._tag_names = TTL_TAG_NAMES.copy()

    def parse_ttl_value(
        self, value: str, base_time: Optional[datetime] = None
    ) -> TTLParseResult:
        """Parse a TTL value string into a datetime.

        Args:
            value: The TTL value to parse (e.g., "30d", "2025-03-15", "1742054400")
            base_time: Base time for relative durations (defaults to now UTC)

        Returns:
            TTLParseResult with the parsed datetime or error details
        """
        if not value or not isinstance(value, str):
            return TTLParseResult(
                expires_at=None,
                is_valid=False,
                error_message="Empty or invalid TTL value",
                source_format=None,
                original_value=str(value) if value else "",
            )

        value = value.strip()
        if not value:
            return TTLParseResult(
                expires_at=None,
                is_valid=False,
                error_message="Empty TTL value after trimming",
                source_format=None,
                original_value=value,
            )

        base = base_time or datetime.now(timezone.utc)

        # Try duration format first (most common for TTL)
        duration_result = self._parse_duration(value, base)
        if duration_result:
            return duration_result

        # Try ISO date format
        iso_result = self._parse_iso_date(value)
        if iso_result:
            return iso_result

        # Try Unix timestamp
        timestamp_result = self._parse_timestamp(value)
        if timestamp_result:
            return timestamp_result

        return TTLParseResult(
            expires_at=None,
            is_valid=False,
            error_message=f"Unrecognized TTL format: '{value}'. Use duration (30d, 6m, 1y), ISO date (2025-03-15), or Unix timestamp.",
            source_format=None,
            original_value=value,
        )

    def _parse_duration(
        self, value: str, base: datetime
    ) -> Optional[TTLParseResult]:
        """Parse duration format (30d, 6m, 1y, 2w, 24h)."""
        for pattern, unit in DURATION_PATTERNS:
            match = pattern.match(value)
            if match:
                amount = int(match.group(1))

                if amount <= 0:
                    return TTLParseResult(
                        expires_at=None,
                        is_valid=False,
                        error_message=f"Duration must be positive: '{value}'",
                        source_format="duration",
                        original_value=value,
                    )

                try:
                    if unit == "years":
                        # Approximate: 365 days per year
                        expires_at = base + timedelta(days=amount * 365)
                    elif unit == "months":
                        # Approximate: 30 days per month
                        expires_at = base + timedelta(days=amount * 30)
                    elif unit == "weeks":
                        expires_at = base + timedelta(weeks=amount)
                    elif unit == "days":
                        expires_at = base + timedelta(days=amount)
                    elif unit == "hours":
                        expires_at = base + timedelta(hours=amount)
                    elif unit == "minutes":
                        expires_at = base + timedelta(minutes=amount)
                    else:
                        return None

                    return TTLParseResult(
                        expires_at=expires_at,
                        is_valid=True,
                        error_message=None,
                        source_format="duration",
                        original_value=value,
                    )
                except (ValueError, OverflowError) as e:
                    return TTLParseResult(
                        expires_at=None,
                        is_valid=False,
                        error_message=f"Invalid duration value: {e}",
                        source_format="duration",
                        original_value=value,
                    )

        return None

    def _parse_iso_date(self, value: str) -> Optional[TTLParseResult]:
        """Parse ISO date format."""
        # Check if it matches any ISO pattern
        is_iso = any(pattern.match(value) for pattern in ISO_DATE_PATTERNS)
        if not is_iso:
            return None

        try:
            # Handle different formats
            if "T" in value:
                # Full ISO datetime
                if value.endswith("Z"):
                    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
                elif "+" in value or value.count("-") > 2:
                    dt = datetime.fromisoformat(value)
                else:
                    # No timezone, assume UTC
                    dt = datetime.fromisoformat(value).replace(tzinfo=timezone.utc)
            elif "/" in value:
                # US format MM/DD/YYYY
                dt = datetime.strptime(value, "%m/%d/%Y").replace(tzinfo=timezone.utc)
                # Set to end of day
                dt = dt.replace(hour=23, minute=59, second=59)
            else:
                # Date only YYYY-MM-DD, set to end of day
                dt = datetime.fromisoformat(value).replace(tzinfo=timezone.utc)
                dt = dt.replace(hour=23, minute=59, second=59)

            return TTLParseResult(
                expires_at=dt,
                is_valid=True,
                error_message=None,
                source_format="iso_date",
                original_value=value,
            )
        except (ValueError, TypeError) as e:
            return TTLParseResult(
                expires_at=None,
                is_valid=False,
                error_message=f"Invalid ISO date: {e}",
                source_format="iso_date",
                original_value=value,
            )

    def _parse_timestamp(self, value: str) -> Optional[TTLParseResult]:
        """Parse Unix timestamp format."""
        # Must be all digits
        if not value.isdigit():
            return None

        try:
            timestamp = int(value)

            # Sanity check: timestamp should be reasonable (between 2000 and 2100)
            min_ts = 946684800  # 2000-01-01
            max_ts = 4102444800  # 2100-01-01

            # Handle milliseconds (13 digits)
            if timestamp > max_ts:
                timestamp = timestamp // 1000

            if timestamp < min_ts or timestamp > max_ts:
                return TTLParseResult(
                    expires_at=None,
                    is_valid=False,
                    error_message=f"Timestamp out of valid range (2000-2100): {value}",
                    source_format="timestamp",
                    original_value=value,
                )

            expires_at = datetime.fromtimestamp(timestamp, tz=timezone.utc)

            return TTLParseResult(
                expires_at=expires_at,
                is_valid=True,
                error_message=None,
                source_format="timestamp",
                original_value=value,
            )
        except (ValueError, OSError, OverflowError) as e:
            return TTLParseResult(
                expires_at=None,
                is_valid=False,
                error_message=f"Invalid timestamp: {e}",
                source_format="timestamp",
                original_value=value,
            )

    def extract_ttl_from_tags(
        self, tags: Dict[str, str], base_time: Optional[datetime] = None
    ) -> TTLExtractionResult:
        """Extract TTL expiration date from resource tags.

        Checks tags in priority order and returns the first valid TTL found.

        Args:
            tags: Dictionary of resource tags
            base_time: Base time for relative durations

        Returns:
            TTLExtractionResult with extracted TTL or None if not found
        """
        if not tags or not isinstance(tags, dict):
            return TTLExtractionResult(
                expires_at=None,
                tag_key=None,
                tag_value=None,
                source_format=None,
                is_valid=False,
                error_message="No tags provided",
            )

        # Normalize tag keys for case-insensitive matching
        normalized_tags = {k.lower(): (k, v) for k, v in tags.items()}

        # Check tags in priority order
        for tag_name in self._tag_names:
            tag_lower = tag_name.lower()

            if tag_lower in normalized_tags:
                original_key, value = normalized_tags[tag_lower]
                result = self.parse_ttl_value(value, base_time)

                if result.is_valid:
                    return TTLExtractionResult(
                        expires_at=result.expires_at,
                        tag_key=original_key,
                        tag_value=value,
                        source_format=result.source_format,
                        is_valid=True,
                        error_message=None,
                    )
                else:
                    # Found a TTL tag but couldn't parse it
                    logger.warning(
                        f"Found TTL tag '{original_key}' but value is invalid: {result.error_message}"
                    )
                    return TTLExtractionResult(
                        expires_at=None,
                        tag_key=original_key,
                        tag_value=value,
                        source_format=None,
                        is_valid=False,
                        error_message=result.error_message,
                    )

        # No TTL tag found
        return TTLExtractionResult(
            expires_at=None,
            tag_key=None,
            tag_value=None,
            source_format=None,
            is_valid=False,
            error_message="No TTL tag found",
        )

    def validate_ttl_tag(self, key: str, value: str) -> Tuple[bool, str]:
        """Validate a TTL tag key and value.

        Args:
            key: The tag key to validate
            value: The tag value to validate

        Returns:
            Tuple of (is_valid, error_message)
        """
        # Check if key is a recognized TTL tag name
        key_lower = key.lower()
        is_recognized = any(name.lower() == key_lower for name in self._tag_names)

        if not is_recognized:
            return (
                False,
                f"Unrecognized TTL tag key: '{key}'. Use one of: {', '.join(self._tag_names[:6])}",
            )

        # Validate the value
        result = self.parse_ttl_value(value)
        if not result.is_valid:
            return (False, result.error_message or "Invalid TTL value")

        # Check if expiration is in the past
        if result.expires_at and result.expires_at < datetime.now(timezone.utc):
            return (False, f"TTL expiration date is in the past: {result.expires_at}")

        return (True, "")

    def get_supported_tag_names(self) -> List[str]:
        """Return list of supported TTL tag names."""
        return self._tag_names.copy()

    def format_duration(self, delta: timedelta) -> str:
        """Format a timedelta as a human-readable duration string.

        Args:
            delta: The timedelta to format

        Returns:
            Human-readable string like "5 days", "2 hours", etc.
        """
        total_seconds = abs(delta.total_seconds())

        if total_seconds < 60:
            return "less than a minute"

        minutes = total_seconds / 60
        if minutes < 60:
            m = int(minutes)
            return f"{m} minute{'s' if m != 1 else ''}"

        hours = minutes / 60
        if hours < 24:
            h = int(hours)
            return f"{h} hour{'s' if h != 1 else ''}"

        days = hours / 24
        if days < 7:
            d = int(days)
            return f"{d} day{'s' if d != 1 else ''}"

        weeks = days / 7
        if weeks < 4:
            w = int(weeks)
            return f"{w} week{'s' if w != 1 else ''}"

        months = days / 30
        if months < 12:
            m = int(months)
            return f"{m} month{'s' if m != 1 else ''}"

        years = days / 365
        y = round(years, 1)
        if y == int(y):
            y = int(y)
        return f"{y} year{'s' if y != 1 else ''}"

    def create_ttl_tag(
        self, days: int, tag_name: str = "tag-manager:TTL"
    ) -> Tuple[str, str]:
        """Create a TTL tag key-value pair.

        Args:
            days: Number of days until expiration
            tag_name: The tag key to use (default: tag-manager:TTL)

        Returns:
            Tuple of (tag_key, tag_value) ready for AWS tagging
        """
        expires_at = datetime.now(timezone.utc) + timedelta(days=days)
        value = expires_at.strftime("%Y-%m-%d")
        return (tag_name, value)


# Global singleton
ttl_parser_service = TTLParserService()
