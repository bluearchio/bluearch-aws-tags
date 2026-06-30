"""Centralized bluearch:* tag definitions for all CloudFormation infrastructure."""

from typing import List, Dict


COMPONENT_CROSS_ACCOUNT = "cross-account"
COMPONENT_MANAGEMENT = "management-resources"
COMPONENT_ASSUME_ROLE = "assume-role"
COMPONENT_EVENT_TRACKING = "event-tracking"
COMPONENT_CUR = "cost-reports"

RESOURCE_GROUP_NAME = "BlueArch-TagManager"


def get_app_version() -> str:
    try:
        from tag_manager_cli import __version__

        return __version__
    except Exception:
        return "LOCAL"


def get_infrastructure_tags(component: str) -> List[Dict[str, str]]:
    """Return CF-format tags for a given component.

    Unified with BlueArch CLI so both apps can share the same IAM role
    (the role's tag-based conditions expect ManagedBy=bluearch-cli).
    """
    version = get_app_version()
    return [
        {"Key": "bluearch:product", "Value": "bluearch"},
        {"Key": "bluearch:component", "Value": component},
        {"Key": "bluearch:managed-by", "Value": "bluearch-cli"},
        {"Key": "bluearch:version", "Value": version},
        {"Key": "Application", "Value": "BlueArchCLI"},
        {"Key": "ManagedBy", "Value": "bluearch-cli"},
    ]
