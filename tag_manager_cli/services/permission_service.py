"""Permission service for IAM permission checking, caching, tier computation, and feature gating.

Validates AWS IAM permissions via SimulatePrincipalPolicy, caches results in
the local SQLite database, computes a permission tier (none/basic/standard/enterprise),
and exposes per-feature availability for the web dashboard and CLI.
"""

import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from botocore.exceptions import ClientError

from ..utils.core_client import request_core

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Feature gates: maps feature names to the IAM actions they require.
#
# "required"    - actions that MUST all be granted for the feature to work
# "per_service" - groups of actions per sub-service (partial availability)
# "optional"    - actions that enhance the feature but are not required
# ---------------------------------------------------------------------------
FEATURE_GATES = {
    "discover_resources": {
        "required": [],
        "per_service": {
            "ec2": [
                "ec2:DescribeInstances",
                "ec2:DescribeVolumes",
                "ec2:DescribeVpcs",
                "ec2:DescribeSubnets",
                "ec2:DescribeSecurityGroups",
            ],
            "s3": [
                "s3:ListAllMyBuckets",
                "s3:GetBucketTagging",
                "s3:GetBucketLocation",
            ],
            "lambda": [
                "lambda:ListFunctions",
                "lambda:ListTags",
            ],
            "rds": [
                "rds:DescribeDBInstances",
                "rds:ListTagsForResource",
            ],
            "dynamodb": [
                "dynamodb:ListTables",
                "dynamodb:DescribeTable",
                "dynamodb:ListTagsOfResource",
            ],
            "ecs": [
                "ecs:ListClusters",
                "ecs:DescribeClusters",
                "ecs:ListTagsForResource",
            ],
            "elb": [
                "elasticloadbalancing:DescribeLoadBalancers",
                "elasticloadbalancing:DescribeTags",
            ],
            "sns": [
                "sns:ListTopics",
                "sns:ListTagsForResource",
            ],
            "sqs": [
                "sqs:ListQueues",
                "sqs:ListQueueTags",
            ],
            "cloudwatch": [
                "cloudwatch:DescribeAlarms",
                "cloudwatch:ListTagsForResource",
            ],
            "eks": [
                "eks:ListClusters",
                "eks:DescribeCluster",
            ],
            "elasticache": [
                "elasticache:DescribeCacheClusters",
                "elasticache:ListTagsForResource",
            ],
        },
    },
    "tag_operations": {
        "required": [
            "tag:GetResources",
            "tag:TagResources",
        ],
    },
    "lifecycle_management": {
        "required": [
            "tag:GetResources",
        ],
        "per_service": {
            "ec2_delete": ["ec2:TerminateInstances"],
            "s3_delete": ["s3:DeleteBucket"],
            "lambda_delete": ["lambda:DeleteFunction"],
            "rds_delete": ["rds:DeleteDBInstance"],
            "dynamodb_delete": ["dynamodb:DeleteTable"],
            "sns_delete": ["sns:DeleteTopic"],
            "sqs_delete": ["sqs:DeleteQueue"],
            "cloudwatch_delete": ["cloudwatch:DeleteAlarms"],
        },
    },
    "cost_report": {
        "required": [
            "ce:GetCostAndUsage",
        ],
        "optional": [
            "athena:StartQueryExecution",
            "glue:GetTable",
        ],
    },
    "ai_assistant": {
        "required": [
            "bedrock:InvokeModel",
            "bedrock:ConverseStream",
        ],
    },
    "compliance": {
        "required": [
            "organizations:DescribeOrganization",
            "organizations:ListPolicies",
        ],
    },
    "cross_account": {
        "required": [
            "organizations:ListAccounts",
            "sts:AssumeRole",
            "cloudformation:CreateStackSet",
        ],
    },
    "setup_deploy_role": {
        "required": [
            "cloudformation:CreateStack",
            "iam:CreateRole",
            "iam:PutRolePolicy",
        ],
    },
}

# Cache TTL: 1 hour
CACHE_TTL_SECONDS = 3600

# Actions that define the "standard" tier (single-account features)
_STANDARD_FEATURES = {
    "discover_resources",
    "tag_operations",
    "lifecycle_management",
    "cost_report",
    "ai_assistant",
    "setup_deploy_role",
}

# Actions that upgrade "standard" to "enterprise"
_ENTERPRISE_FEATURES = {
    "compliance",
    "cross_account",
}


def _collect_all_actions() -> List[str]:
    """Flatten every action referenced in FEATURE_GATES into a deduplicated list."""
    actions = set()
    for gate in FEATURE_GATES.values():
        for action in gate.get("required", []):
            actions.add(action)
        for action in gate.get("optional", []):
            actions.add(action)
        for svc_actions in gate.get("per_service", {}).values():
            actions.update(svc_actions)
    return sorted(actions)


def _batched(iterable, n):
    """Yield successive n-sized chunks from iterable."""
    lst = list(iterable)
    for i in range(0, len(lst), n):
        yield lst[i : i + n]


class PermissionService:
    """Backend service for IAM permission checking, caching, and feature gating."""

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def validate_permissions(self, db, account_id, user_arn, boto3_session):
        """Run SimulatePrincipalPolicy for all FEATURE_GATES actions.

        Caches results in ``permission_cache``, computes the tier,
        builds the feature map, persists to ``permission_tier``,
        and returns the full PermissionStatusResponse-shaped dict.

        Parameters
        ----------
        db : sqlalchemy.orm.Session
        account_id : str
        user_arn : str
        boto3_session : boto3.Session

        Returns
        -------
        dict  - the full permission status response
        """
        all_actions = _collect_all_actions()
        logger.info(
            "Validating %d IAM actions for account=%s user=%s",
            len(all_actions),
            account_id,
            user_arn,
        )

        # --- Resolve the principal ARN for simulation -----------------
        principal_arn = self._resolve_principal_arn(boto3_session, user_arn)

        # --- Simulate permissions via IAM -----------------------------
        permissions = self._simulate_all(boto3_session, principal_arn, all_actions)

        # --- Persist to permission_cache ------------------------------
        now = datetime.now(timezone.utc)
        self._save_permission_cache(db, account_id, user_arn, permissions, now)

        # --- Compute tier & feature map -------------------------------
        tier = self.compute_tier(permissions)
        features = self.build_feature_map(permissions)
        expires_at = now + timedelta(seconds=CACHE_TTL_SECONDS)

        # --- Persist to permission_tier (upsert) ----------------------
        self._save_permission_tier(
            db, account_id, user_arn, tier, features, now, expires_at
        )

        return {
            "account_id": account_id,
            "tier": tier,
            "checked_at": now.isoformat(),
            "expires_at": expires_at.isoformat(),
            "features": features,
        }

    def get_cached_permissions(self, db, account_id, user_arn):
        """Read cached permission tier data if it has not expired.

        Returns
        -------
        dict or None
            The ``features_json`` dict if still valid, else ``None``.
        """
        row = self._get_permission_tier(account_id, user_arn)
        if row is None:
            return None

        now = datetime.now(timezone.utc)
        expires_at = _parse_datetime(row.get("expires_at"))
        if expires_at is None:
            return None
        if now > expires_at:
            logger.debug("Cached permissions expired for %s/%s", account_id, user_arn)
            return None

        features = row.get("features_json")
        if isinstance(features, str):
            features = json.loads(features)
        return features

    def get_feature_status(self, db, account_id, user_arn, feature_name):
        """Return the availability status of a single feature.

        Returns
        -------
        dict
            ``{available, partial, missing, services}``
        """
        features = self.get_cached_permissions(db, account_id, user_arn)
        if features is None:
            return {
                "available": False,
                "partial": False,
                "missing": [],
                "services": {},
            }

        feature = features.get(feature_name)
        if feature is None:
            return {
                "available": False,
                "partial": False,
                "missing": [],
                "services": {},
            }
        return feature

    def get_full_status(self, db, account_id, user_arn):
        """Return the full permission status response from cache.

        Returns
        -------
        dict
            ``{account_id, tier, checked_at, expires_at, features}``
        """
        row = self._get_permission_tier(account_id, user_arn)
        if row is None:
            return {
                "account_id": account_id,
                "tier": "none",
                "checked_at": None,
                "expires_at": None,
                "features": {},
            }

        features = row.get("features_json")
        if isinstance(features, str):
            features = json.loads(features)

        checked_at = _format_datetime(row.get("checked_at"))
        expires_at = _format_datetime(row.get("expires_at"))

        return {
            "account_id": account_id,
            "tier": row.get("tier"),
            "checked_at": checked_at,
            "expires_at": expires_at,
            "features": features,
        }

    # ------------------------------------------------------------------
    # Tier & feature computation (stateless helpers)
    # ------------------------------------------------------------------

    def compute_tier(self, permissions):
        """Compute the permission tier from a flat ``{action: bool}`` map.

        Tiers (highest to lowest):
        - ``"enterprise"`` -- all standard + org + cross-account perms granted
        - ``"standard"``   -- all standard single-account perms granted
        - ``"basic"``      -- has SimulatePrincipalPolicy (can at least validate)
        - ``"none"``       -- nothing useful
        """
        if not permissions:
            return "none"

        def _all_granted(feature_name):
            gate = FEATURE_GATES.get(feature_name, {})
            for action in gate.get("required", []):
                if not permissions.get(action):
                    return False
            for svc_actions in gate.get("per_service", {}).values():
                for action in svc_actions:
                    if not permissions.get(action):
                        return False
            return True

        # Check standard features
        standard_ok = all(_all_granted(f) for f in _STANDARD_FEATURES)

        # Check enterprise features
        enterprise_ok = standard_ok and all(
            _all_granted(f) for f in _ENTERPRISE_FEATURES
        )

        if enterprise_ok:
            return "enterprise"
        if standard_ok:
            return "standard"

        # Basic: at least has SimulatePrincipalPolicy
        if permissions.get("iam:SimulatePrincipalPolicy"):
            return "basic"

        return "none"

    def build_feature_map(self, permissions):
        """Build per-feature availability from a flat ``{action: bool}`` map.

        Returns
        -------
        dict
            ``{feature_name: {available, partial, missing, services}}``
        """
        result = {}
        for feature_name, gate in FEATURE_GATES.items():
            missing = []
            # Check required actions
            for action in gate.get("required", []):
                if not permissions.get(action):
                    missing.append(action)

            # Check per-service actions
            services = {}
            per_service = gate.get("per_service", {})
            for svc_name, svc_actions in per_service.items():
                svc_missing = [a for a in svc_actions if not permissions.get(a)]
                services[svc_name] = {
                    "available": len(svc_missing) == 0,
                    "missing": svc_missing,
                }
                missing.extend(svc_missing)

            # A feature is "available" if all required actions and all per-service
            # actions are granted (no missing at all).
            # It is "partial" if required actions are met but some per-service
            # actions are missing.
            required_met = all(
                permissions.get(a) for a in gate.get("required", [])
            ) if gate.get("required") else True
            any_service_available = any(
                s["available"] for s in services.values()
            ) if services else False

            available = len(missing) == 0
            partial = (not available) and required_met and any_service_available

            result[feature_name] = {
                "available": available,
                "partial": partial,
                "missing": missing,
                "services": services,
            }
        return result

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _resolve_principal_arn(self, boto3_session, user_arn):
        """Convert an assumed-role ARN to a role ARN for SimulatePrincipalPolicy.

        The IAM simulator requires the role ARN, not the session ARN.
        """
        if ":assumed-role/" in user_arn:
            parts = user_arn.split(":")
            if len(parts) >= 6:
                account = parts[4]
                role_session = parts[5].split("/")
                if len(role_session) >= 2 and role_session[0] == "assumed-role":
                    role_name = role_session[1]
                    resolved = f"arn:aws:iam::{account}:role/{role_name}"
                    logger.debug(
                        "Resolved assumed-role ARN to role ARN: %s", resolved
                    )
                    return resolved
        return user_arn

    def _simulate_all(self, boto3_session, principal_arn, all_actions):
        """Call SimulatePrincipalPolicy in batches and return ``{action: bool}``.

        If the caller lacks ``iam:SimulatePrincipalPolicy`` itself, all
        actions are returned as ``False`` and a warning is logged.
        """
        iam_client = boto3_session.client("iam")
        results = {}

        for batch in _batched(all_actions, 100):
            try:
                response = iam_client.simulate_principal_policy(
                    PolicySourceArn=principal_arn,
                    ActionNames=list(batch),
                )
                for item in response.get("EvaluationResults", []):
                    action = item["EvalActionName"]
                    results[action] = item["EvalDecision"] == "allowed"

                # Handle pagination
                while response.get("IsTruncated"):
                    response = iam_client.simulate_principal_policy(
                        PolicySourceArn=principal_arn,
                        ActionNames=list(batch),
                        Marker=response["Marker"],
                    )
                    for item in response.get("EvaluationResults", []):
                        action = item["EvalActionName"]
                        results[action] = item["EvalDecision"] == "allowed"

            except ClientError as exc:
                error_code = exc.response["Error"]["Code"]
                if error_code in ("AccessDenied", "UnauthorizedOperation"):
                    logger.warning(
                        "Caller lacks iam:SimulatePrincipalPolicy -- "
                        "marking all actions as denied"
                    )
                    for action in all_actions:
                        results.setdefault(action, False)
                    return results
                else:
                    logger.error(
                        "SimulatePrincipalPolicy error: %s - %s",
                        error_code,
                        exc,
                    )
                    raise

        return results

    def _save_permission_cache(self, db, account_id, user_arn, permissions, now):
        """Replace all ``permission_cache`` rows for this account/user."""
        for row in self._list_permission_cache(account_id, user_arn):
            _delete_storage_record("permission-cache", row)

        # Insert fresh rows
        for action, granted in permissions.items():
            _create_storage_payload(
                "permission-cache",
                {
                    "account_id": account_id,
                    "user_arn": user_arn,
                    "action": action,
                    "granted": granted,
                    "checked_at": now.isoformat(),
                },
            )

    def _save_permission_tier(
        self, db, account_id, user_arn, tier, features, checked_at, expires_at
    ):
        """Upsert a ``permission_tier`` row."""
        row = self._get_permission_tier(account_id, user_arn)

        payload = {
            "account_id": account_id,
            "user_arn": user_arn,
            "tier": tier,
            "features_json": features,
            "checked_at": checked_at.isoformat(),
            "expires_at": expires_at.isoformat(),
        }
        if row:
            _update_storage_payload("permission-tier", row, payload)
        else:
            _create_storage_payload("permission-tier", payload)

    def _get_permission_tier(self, account_id: str, user_arn: str) -> Optional[Dict[str, Any]]:
        rows = _list_storage_payloads(
            "permission-tier",
            filters=[("account_id", account_id), ("user_arn", user_arn)],
            limit=1,
        )
        return rows[0] if rows else None

    def _list_permission_cache(self, account_id: str, user_arn: str) -> List[Dict[str, Any]]:
        return _list_storage_payloads(
            "permission-cache",
            filters=[("account_id", account_id), ("user_arn", user_arn)],
            limit=10000,
        )


def _storage_path(collection: str, record_key: str | None = None) -> str:
    path = f"/api/v1/storage/core/{collection}"
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


def _delete_storage_record(collection: str, row: Dict[str, Any]) -> None:
    record_key = row.get("record_key") or row.get("id")
    if not record_key:
        raise RuntimeError(f"Cannot delete {collection} without a record key")
    request_core(
        "DELETE",
        _storage_path(collection, str(record_key)),
        service_token=True,
        timeout=10.0,
    )


def _parse_datetime(value: Any) -> Optional[datetime]:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str) and value:
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    else:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _format_datetime(value: Any) -> Optional[str]:
    parsed = _parse_datetime(value)
    return parsed.isoformat() if parsed else None


# Module-level singleton
permission_service = PermissionService()
