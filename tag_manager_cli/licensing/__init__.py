"""Open-source feature availability compatibility package."""

from .features import Tier, TIER_LEVEL, FEATURE_GATES
from .license import (
    get_current_tier,
    get_license_info,
    reset_cache,
    save_license_key,
    validate_license_token,
)
from .gate import requires_tier, check_feature, is_feature_allowed, get_available_collectors
