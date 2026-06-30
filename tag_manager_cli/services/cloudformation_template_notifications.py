"""CloudFormation template-version notifications."""

import hashlib
import json
import logging
import os
import re
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional, Tuple

import boto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError

from .. import __version__
from .notification_service import NotificationResult, NotificationService

logger = logging.getLogger(__name__)

AWS_CLIENT_CONFIG = Config(
    connect_timeout=10,
    read_timeout=20,
    retries={"max_attempts": 2, "mode": "standard"},
)
TAG_MANAGER_STACK_MARKERS = (
    "tag-manager",
    "tagmanager",
    "bluearch",
    "bluearchcli",
    "bluearch-cli",
)
TEMPLATE_METADATA_KEYS = ("TagManagerCLI", "BlueArchCLI")
DEPLOYABLE_TEMPLATE_SETUP_PATHS = {
    ("stackset", "tagmanagercli-crossaccount-infrastructure"): "/setup/multi-account",
    ("stackset", "bluearchcli-crossaccount-infrastructure"): "/setup/multi-account",
    ("stack", "tagmanagercli-management-account-resources"): "/setup",
    ("stack", "tagmanagercli-management-resources"): "/setup",
    ("stack", "bluearchcli-management-account-resources"): "/setup",
    ("stack", "tagmanagercli-role"): "/setup/assume-role",
    ("stack", "bluearchcli-role"): "/setup/assume-role",
    ("stack", "bluearchcur"): "/cost",
    ("stack", "tagmanagercur"): "/cost",
}


@dataclass(frozen=True)
class DeprecatedTemplate:
    kind: str
    name: str
    region: str
    deployed_version: str
    current_version: str
    template_version_key: str
    metadata_key: str
    setup_path: str


def notify_deprecated_cloudformation_templates(
    *,
    session: Optional["boto3.Session"] = None,
    current_version: Optional[str] = None,
    force: bool = False,
) -> NotificationResult:
    """Detect and record once when Tag Manager CloudFormation templates are old."""
    version = _effective_current_version(current_version)
    if not _is_comparable_version(version):
        return NotificationResult(sent=False, status="skipped_local_version")

    findings = detect_deprecated_cloudformation_templates(session=session, current_version=version)
    if not findings:
        return NotificationResult(sent=False, status="no_findings")

    payload = {
        "current_version": version,
        "templates": [finding.__dict__ for finding in findings],
    }
    event_key = f"deprecated-cloudformation-templates:{version}:{_payload_hash(payload)}"
    title = "Tag Manager CloudFormation Templates Need Update"
    message = _format_message(findings, version)

    return NotificationService().record_once(
        source="cloudformation-template-version",
        event_key=event_key,
        severity="warning",
        title=title,
        message=message,
        payload=payload,
        force=force,
    )


def detect_deprecated_cloudformation_templates(
    *,
    session: Optional["boto3.Session"] = None,
    current_version: Optional[str] = None,
    regions: Optional[Iterable[str]] = None,
) -> List[DeprecatedTemplate]:
    """Return deployed Tag Manager templates whose embedded version is older."""
    version = _effective_current_version(current_version)
    if not _is_comparable_version(version):
        return []

    aws_session = session or _default_session()
    findings: List[DeprecatedTemplate] = []
    for region in _template_check_regions(aws_session, regions):
        try:
            client = aws_session.client("cloudformation", region_name=region, config=AWS_CLIENT_CONFIG)
            findings.extend(_detect_stacksets(client, region, version))
            findings.extend(_detect_stacks(client, region, version))
        except (BotoCoreError, ClientError) as exc:
            logger.debug("CloudFormation template version check failed in %s: %s", region, exc)
        except Exception as exc:
            logger.debug("Unexpected CloudFormation template version check error in %s: %s", region, exc)

    return _dedupe_findings(findings)


def compare_versions(left: str, right: str) -> Optional[int]:
    """Compare two semantic versions. Returns -1, 0, 1, or None."""
    left_parts = _parse_version(left)
    right_parts = _parse_version(right)
    if left_parts is None or right_parts is None:
        return None
    if left_parts < right_parts:
        return -1
    if left_parts > right_parts:
        return 1
    return 0


def extract_template_version(template_body: Any) -> Tuple[Optional[str], Optional[str], Optional[str]]:
    """Extract Tag Manager or shared BlueArch template version metadata."""
    metadata = _template_metadata(template_body)
    if isinstance(metadata, dict):
        for metadata_key in TEMPLATE_METADATA_KEYS:
            product_meta = metadata.get(metadata_key)
            if not isinstance(product_meta, dict):
                continue
            cli_version = product_meta.get("CLIVersion")
            template_version = product_meta.get("Version")
            if cli_version:
                return str(cli_version), "CLIVersion", metadata_key
            if template_version:
                return str(template_version), "Version", metadata_key

    if isinstance(template_body, str):
        cli_match = re.search(r"CLIVersion:\s*['\"]?([^'\"\n]+)", template_body)
        if cli_match:
            return cli_match.group(1).strip(), "CLIVersion", "Unknown"

    return None, None, None


def _detect_stacksets(client: Any, region: str, current_version: str) -> List[DeprecatedTemplate]:
    findings = []
    paginator = client.get_paginator("list_stack_sets")
    for page in paginator.paginate(Status="ACTIVE"):
        for summary in page.get("Summaries", []):
            name = summary.get("StackSetName") or ""
            if not _is_tag_manager_name(name):
                continue
            try:
                response = client.describe_stack_set(StackSetName=name)
            except (BotoCoreError, ClientError) as exc:
                logger.debug("Failed to describe StackSet %s in %s: %s", name, region, exc)
                continue
            stackset = response.get("StackSet") or {}
            tags = {tag.get("Key", ""): tag.get("Value", "") for tag in stackset.get("Tags", [])}
            if not _is_deployable_tag_manager_template("stackset", name, tags):
                continue
            finding = _deprecated_template(
                "stackset",
                name,
                region,
                stackset.get("TemplateBody"),
                current_version,
                tags=tags,
            )
            if finding:
                findings.append(finding)
    return findings


def _detect_stacks(client: Any, region: str, current_version: str) -> List[DeprecatedTemplate]:
    findings = []
    paginator = client.get_paginator("describe_stacks")
    for page in paginator.paginate():
        for stack in page.get("Stacks", []):
            name = stack.get("StackName") or ""
            tags = {tag.get("Key", ""): tag.get("Value", "") for tag in stack.get("Tags", [])}
            if not _is_deployable_tag_manager_template("stack", name, tags):
                continue
            try:
                response = client.get_template(StackName=name, TemplateStage="Original")
            except (BotoCoreError, ClientError) as exc:
                logger.debug("Failed to fetch template for stack %s in %s: %s", name, region, exc)
                continue
            finding = _deprecated_template(
                "stack",
                name,
                region,
                response.get("TemplateBody"),
                current_version,
                tags=tags,
            )
            if finding:
                findings.append(finding)
    return findings


def _deprecated_template(
    kind: str,
    name: str,
    region: str,
    template_body: Any,
    current_version: str,
    tags: Optional[Dict[str, str]] = None,
) -> Optional[DeprecatedTemplate]:
    deployed_version, version_key, metadata_key = extract_template_version(template_body)
    if tags and (not deployed_version or compare_versions(deployed_version, current_version) is None):
        tag_version = tags.get("bluearch:version") or tags.get("tag-manager:version")
        if tag_version:
            deployed_version = str(tag_version)
            version_key = "bluearch:version" if tags.get("bluearch:version") else "tag-manager:version"
            metadata_key = "TagManagerCLI"
    if not deployed_version or not version_key or not metadata_key:
        return None
    if deployed_version.upper() == "LOCAL":
        is_deprecated = True
    else:
        is_deprecated = compare_versions(deployed_version, current_version) == -1
    if not is_deprecated:
        return None
    return DeprecatedTemplate(
        kind=kind,
        name=name,
        region=region,
        deployed_version=deployed_version,
        current_version=current_version,
        template_version_key=version_key,
        metadata_key=metadata_key,
        setup_path=_setup_path_for_template(kind, name, tags or {}),
    )


def _default_session() -> "boto3.Session":
    try:
        from ..utils.aws_auth import aws_auth

        return aws_auth.session or aws_auth.initialize_session()
    except Exception:
        return boto3.Session()


def _effective_current_version(version: Optional[str]) -> str:
    return (version or os.environ.get("TAG_MANAGER_CLI_VERSION") or __version__ or "").strip()


def _is_comparable_version(version: str) -> bool:
    return version.upper() != "LOCAL" and _parse_version(version) is not None


def _parse_version(version: Optional[str]) -> Optional[Tuple[int, int, int]]:
    if not version:
        return None
    match = re.match(r"^\s*v?(\d+)(?:\.(\d+))?(?:\.(\d+))?", str(version))
    if not match:
        return None
    return tuple(int(part or 0) for part in match.groups())


def _template_metadata(template_body: Any) -> Dict[str, Any]:
    if isinstance(template_body, dict):
        metadata = template_body.get("Metadata")
        return metadata if isinstance(metadata, dict) else {}
    return {}


def _template_check_regions(
    aws_session: "boto3.Session",
    regions: Optional[Iterable[str]],
) -> List[str]:
    if regions:
        return list(dict.fromkeys(region for region in regions if region))

    env_regions = os.environ.get("TAG_MANAGER_TEMPLATE_CHECK_REGIONS")
    if env_regions:
        return [region.strip() for region in env_regions.split(",") if region.strip()]

    candidates = [
        getattr(aws_session, "region_name", None),
        os.environ.get("AWS_REGION"),
        os.environ.get("AWS_DEFAULT_REGION"),
        "us-east-1",
        "us-west-2",
    ]
    return list(dict.fromkeys(region for region in candidates if region))


def _is_tag_manager_name(value: str) -> bool:
    normalized = value.replace("_", "-").lower()
    return any(marker in normalized for marker in TAG_MANAGER_STACK_MARKERS)


def _is_known_deployable_template(kind: str, name: str) -> bool:
    return (kind, _normalize_template_name(name)) in DEPLOYABLE_TEMPLATE_SETUP_PATHS


def _is_deployable_tag_manager_template(kind: str, name: str, tags: Dict[str, str]) -> bool:
    return _is_known_deployable_template(kind, name) or _has_tag_manager_tags(tags)


def _has_tag_manager_tags(tags: Dict[str, str]) -> bool:
    normalized = {key.lower(): str(value).lower() for key, value in tags.items()}
    return (
        normalized.get("bluearch:product") == "tag-manager"
        or normalized.get("bluearch:product") == "bluearch"
        or normalized.get("bluearch:managed-by") == "tag-manager-cli"
        or normalized.get("bluearch:managed-by") == "bluearch-cli"
        or normalized.get("managedby") == "tag-manager-cli"
        or normalized.get("managedby") == "bluearch-cli"
        or normalized.get("application") == "tagmanagercli"
        or normalized.get("application") == "bluearchcli"
        or normalized.get("component") == "cur-finops"
        or normalized.get("bluearch:component") in {"cur", "cur-finops"}
    )


def _dedupe_findings(findings: List[DeprecatedTemplate]) -> List[DeprecatedTemplate]:
    unique = {}
    for finding in findings:
        unique[(finding.kind, finding.region, finding.name)] = finding
    return [unique[key] for key in sorted(unique)]


def _payload_hash(payload: Dict[str, Any]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()[:16]


def _format_message(findings: List[DeprecatedTemplate], current_version: str) -> str:
    lines = [
        f"Tag Manager CLI {current_version} detected deployed CloudFormation templates from older CLI versions.",
        "Update the CloudFormation stack or StackSet templates before relying on the latest permissions "
        "and setup behavior.",
        "",
    ]
    for finding in findings[:10]:
        lines.append(
            f"- {finding.kind} `{finding.name}` in `{finding.region}`: "
            f"{finding.template_version_key} `{finding.deployed_version}` < `{current_version}`"
        )
    if len(findings) > 10:
        lines.append(f"- ...and {len(findings) - 10} more template(s)")
    return "\n".join(lines)


def _setup_path_for_template(kind: str, name: str, tags: Dict[str, str]) -> str:
    known_path = DEPLOYABLE_TEMPLATE_SETUP_PATHS.get((kind, _normalize_template_name(name)))
    if known_path:
        return known_path

    component = tags.get("bluearch:component", "").lower()
    normalized_name = name.lower()
    if kind == "stackset" or component == "cross-account" or "crossaccount" in normalized_name:
        return "/setup/multi-account"
    if component == "assume-role" or "role" in normalized_name:
        return "/setup/assume-role"
    if component in {"cur", "cur-finops"} or "cur" in normalized_name:
        return "/cost"
    return "/setup"


def _normalize_template_name(name: str) -> str:
    return name.replace("_", "-").lower()
