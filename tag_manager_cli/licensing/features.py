"""Tier definitions and feature gate registry."""

from enum import Enum


class Tier(str, Enum):
    FREE = "free"
    PRO = "pro"
    ENTERPRISE = "enterprise"


TIER_LEVEL = {
    Tier.FREE: 0,
    Tier.PRO: 1,
    Tier.ENTERPRISE: 2,
}

# Maps feature keys to the minimum tier required.
# Enterprise features are unlocked for Pro until Enterprise customers exist.
FEATURE_GATES = {
    # Resource discovery -- free gets 3 core services
    "collector:vpc":           Tier.FREE,
    "collector:iam":           Tier.PRO,
    "collector:ec2":           Tier.FREE,
    "collector:s3":            Tier.FREE,
    "collector:lambda":        Tier.FREE,
    "collector:rds":           Tier.PRO,
    "collector:dynamodb":      Tier.PRO,
    "collector:ecs":           Tier.PRO,
    "collector:elb":           Tier.PRO,
    "collector:sns":           Tier.PRO,
    "collector:sqs":           Tier.PRO,
    "collector:cloudwatch":    Tier.PRO,
    "collector:eks":           Tier.PRO,
    "collector:elasticache":   Tier.PRO,

    # Lifecycle
    "lifecycle:view":          Tier.FREE,
    "lifecycle:policies":      Tier.PRO,
    "lifecycle:auto_delete":   Tier.PRO,

    # Cost
    "cost:summary":            Tier.FREE,
    "cost:cur_analytics":      Tier.PRO,

    # Cross-account
    "cross_account":           Tier.PRO,

    # Event-driven tracking
    "event_tracking":          Tier.PRO,

    # Web dashboard
    "web:dashboard":           Tier.FREE,
    "web:write_operations":    Tier.PRO,

    # Resource map
    "resource_map":            Tier.PRO,
}
