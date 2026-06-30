"""Dynamic model version resolution for Bedrock.

For each alias (``haiku`` / ``sonnet`` / ``opus``) we want the *latest active*
release in the customer's region with no hand-maintained version numbers.
Anthropic retires older Claude releases ("LEGACY"); invoking one returns
``Access denied. This Model is marked by provider as Legacy``.

The resolver therefore:
1. Lists ``list_inference_profiles`` and keeps profiles whose id/name
   contains the alias. Inference profiles are the only invocable path for
   Claude 4.x and always reflect the current generation.
2. Prefers the profile whose id starts with the region's cross-region
   prefix (``us.`` / ``eu.`` / ``apac.``).
3. Sorts by the 8-digit release date embedded in the id (for example
   ``anthropic.claude-haiku-4-5-20251001-v1:0`` -> ``20251001``) and picks
   the most recent.
4. Falls back to ``list_foundation_models`` for older families (Claude 3.x
   Haiku still accepts direct on-demand invocation), skipping anything
   whose ``modelLifecycle.status`` is ``LEGACY``.
5. Only if both list APIs fail do we use the static ``_FALLBACK_MODELS``
   map — kept on the current generation, best-effort.
"""

import re
import time
from typing import Any, Dict, List, Optional


# ---------------------------------------------------------------------------
# Public API — kept stable so aws_assistant.py / aws_tools.py don't change
# ---------------------------------------------------------------------------

_DATE_RE = re.compile(r"(\d{8})")

# Last-resort hardcoded IDs — used only when both list APIs are unreachable.
# Kept on the current Claude 4.x generation.
_FALLBACK_MODELS: Dict[str, str] = {
    "haiku": "us.anthropic.claude-haiku-4-5-20251001-v1:0",
    "sonnet": "us.anthropic.claude-sonnet-4-5-20250929-v1:0",
    "opus": "us.anthropic.claude-opus-4-1-20250805-v1:0",
}


def parse_model_version(model_id: str) -> Optional[int]:
    """Extract the YYYYMMDD release date from a Bedrock model id.

    Examples:
        - anthropic.claude-3-haiku-20240307-v1:0 -> 20240307
        - anthropic.claude-haiku-4-5-20251001-v1:0 -> 20251001
        - us.anthropic.claude-3-5-sonnet-20241022-v2:0 -> 20241022
    """
    if not model_id:
        return None
    m = _DATE_RE.search(model_id)
    return int(m.group(1)) if m else None


def get_model_family(model_id: str) -> Optional[str]:
    """Identify the Claude family (haiku, sonnet, opus) for a model id."""
    if not model_id:
        return None
    lc = model_id.lower()
    if "haiku" in lc:
        return "haiku"
    if "sonnet" in lc:
        return "sonnet"
    if "opus" in lc:
        return "opus"
    return None


# ---------------------------------------------------------------------------
# Resolution helpers
# ---------------------------------------------------------------------------

def _region_prefix(region: str) -> str:
    """Cross-region inference-profile prefix for the given AWS region."""
    if region.startswith("eu-"):
        return "eu"
    if region.startswith("ap-"):
        return "apac"
    # us-*, ca-*, sa-*, unknown -> us (most widely available)
    return "us"


def _contains_alias(candidate: Optional[str], alias_lc: str) -> bool:
    if not candidate:
        return False
    return alias_lc in candidate.lower()


def _latest_by_date(items: List[Dict[str, Any]], id_key: str) -> Optional[Dict[str, Any]]:
    if not items:
        return None
    items.sort(key=lambda it: parse_model_version(it.get(id_key, "")) or 0, reverse=True)
    return items[0]


def _from_inference_profiles(bedrock, alias_lc: str, region: str) -> Optional[str]:
    try:
        resp = bedrock.list_inference_profiles()
    except Exception:
        return None

    profiles = resp.get("inferenceProfileSummaries", []) or []
    matches = [
        p for p in profiles
        if _contains_alias(p.get("inferenceProfileId"), alias_lc)
        or _contains_alias(p.get("inferenceProfileName"), alias_lc)
    ]
    if not matches:
        return None

    prefix = _region_prefix(region) + "."
    regional = [p for p in matches if (p.get("inferenceProfileId") or "").startswith(prefix)]
    chosen = _latest_by_date(regional or matches, "inferenceProfileId")
    return chosen.get("inferenceProfileId") if chosen else None


def _from_foundation_models(bedrock, alias_lc: str) -> Optional[str]:
    try:
        resp = bedrock.list_foundation_models(
            byProvider="Anthropic",
            byOutputModality="TEXT",
        )
    except Exception:
        return None

    candidates: List[Dict[str, Any]] = []
    for m in resp.get("modelSummaries", []) or []:
        mid = m.get("modelId", "")
        if not _contains_alias(mid, alias_lc):
            continue
        lifecycle = (m.get("modelLifecycle") or {}).get("status", "")
        if lifecycle and lifecycle.upper() == "LEGACY":
            continue
        inference_types = m.get("inferenceTypesSupported") or []
        if inference_types and "ON_DEMAND" not in inference_types:
            continue
        candidates.append(m)

    chosen = _latest_by_date(candidates, "modelId")
    return chosen.get("modelId") if chosen else None


def _resolve_alias(alias: str, region: str) -> str:
    """Return an invocable model id for the given alias."""
    from ..utils.aws_auth import aws_auth

    alias_lc = (alias or "").lower()
    try:
        bedrock = aws_auth.get_client("bedrock", region=region)
    except Exception:
        bedrock = None

    resolved: Optional[str] = None
    if bedrock is not None:
        resolved = _from_inference_profiles(bedrock, alias_lc, region)
        if resolved is None:
            resolved = _from_foundation_models(bedrock, alias_lc)

    return resolved or _FALLBACK_MODELS.get(alias_lc, _FALLBACK_MODELS["sonnet"])


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def get_latest_model_versions(region: str = "us-east-1") -> Dict[str, str]:
    """Get the latest invocable model id for each Anthropic family.

    Returns:
        Dictionary mapping family names to invocable ids, e.g.
        ``{"haiku": "us.anthropic.claude-haiku-4-5-20251001-v1:0", ...}``
    """
    return {family: _resolve_alias(family, region) for family in ("haiku", "sonnet", "opus")}


def get_latest_haiku(region: str = "us-east-1") -> str:
    return _resolve_alias("haiku", region)


def get_latest_sonnet(region: str = "us-east-1") -> str:
    return _resolve_alias("sonnet", region)


def get_latest_opus(region: str = "us-east-1") -> str:
    return _resolve_alias("opus", region)


# ---------------------------------------------------------------------------
# Cache (1h TTL) so new model releases become visible without restart, and
# we avoid hammering Bedrock list APIs on every chat turn.
# ---------------------------------------------------------------------------

_version_cache: Dict[str, Dict[str, str]] = {}
_cache_timestamp: Dict[str, float] = {}
CACHE_TTL = 3600


def get_latest_model_versions_cached(region: str = "us-east-1", force_refresh: bool = False) -> Dict[str, str]:
    cache_key = region
    current_time = time.time()

    if not force_refresh and cache_key in _version_cache:
        if current_time - _cache_timestamp.get(cache_key, 0) < CACHE_TTL:
            return _version_cache[cache_key]

    versions = get_latest_model_versions(region)
    _version_cache[cache_key] = versions
    _cache_timestamp[cache_key] = current_time
    return versions
