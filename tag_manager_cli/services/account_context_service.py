"""Account context service for multi-account data isolation.

Manages registered AWS account contexts, allowing users to switch between
accounts while keeping resources, policies, and other data scoped to the
active account.  Provides a startup gate (ensure_context) that determines
whether the CLI can proceed or needs the user to register / switch accounts.
"""

import logging
import os
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any, Dict, List, Optional

from ..utils.core_client import request_core

logger = logging.getLogger(__name__)


class AccountContextService:
    """CRUD and startup-gate logic for AWS account contexts."""

    # ------------------------------------------------------------------
    # Read helpers
    # ------------------------------------------------------------------

    def get_current_context(self, db=None) -> Optional[Any]:
        """Return the context marked as is_current=True, or None."""
        rows = _list_context_records(filters=[("is_current", "true")], limit=1)
        return _objectify(rows[0]) if rows else None

    def get_all_contexts(self, db=None) -> List[Any]:
        """Return every registered context, ordered by creation time."""
        return [_objectify(row) for row in _list_context_records(limit=1000)]

    def get_context_by_account_id(
        self, db, account_id: str
    ) -> Optional[Any]:
        """Find a context by its 12-digit AWS account ID."""
        rows = _list_context_records(filters=[("account_id", account_id)], limit=1)
        return _objectify(rows[0]) if rows else None

    # ------------------------------------------------------------------
    # Write helpers
    # ------------------------------------------------------------------

    def add_context(
        self,
        db,
        account_id: str,
        user_arn: str,
        alias: Optional[str] = None,
        region: Optional[str] = None,
        set_current: bool = False,
    ) -> Any:
        """Register a new account context.

        Args:
            db: Deprecated compatibility parameter; ignored.
            account_id: 12-digit AWS account ID.
            user_arn: Caller ARN from STS.
            alias: Optional human-readable account alias.
            region: Optional AWS region override.
            set_current: If True, mark this context as the active one.

        Returns:
            The newly created account context payload.

        Raises:
            ValueError: If account_id is already registered.
        """
        existing = self.get_context_by_account_id(db, account_id)
        if existing:
            raise ValueError(
                f"Account {account_id} is already registered"
                + (
                    f" (alias: {existing.account_alias})"
                    if existing.account_alias
                    else ""
                )
            )

        now = datetime.now(timezone.utc)
        aws_profile = os.environ.get("AWS_PROFILE", "default")

        if set_current:
            # Clear any existing current flag first
            self._clear_current(db)

        ctx = _create_context_record(
            {
                "account_id": account_id,
                "account_alias": alias,
                "aws_profile": aws_profile,
                "region": region,
                "user_arn": user_arn,
                "is_current": set_current,
                "created_at": now,
                "last_used_at": now if set_current else None,
            }
        )

        logger.info(
            "Registered account context %s (alias=%s, current=%s)",
            account_id,
            alias,
            set_current,
        )
        return _objectify(ctx)

    def switch_context(self, db, account_id: str) -> Any:
        """Make *account_id* the active context.

        Sets is_current=True on the target and False on all others.
        Updates last_used_at on the target.

        Args:
            db: Deprecated compatibility parameter; ignored.
            account_id: The account to switch to.

        Returns:
            The now-current account context payload.

        Raises:
            ValueError: If account_id is not registered.
        """
        target = self.get_context_by_account_id(db, account_id)
        if not target:
            raise ValueError(
                f"Account {account_id} is not registered. "
                "Use add_context() to register it first."
            )

        self._clear_current(db)

        payload = _namespace_to_payload(target)
        payload["is_current"] = True
        payload["last_used_at"] = datetime.now(timezone.utc)
        target = _objectify(_update_context_record(target.id, payload))

        logger.info("Switched current context to account %s", account_id)
        return target

    def remove_context(self, db, account_id: str) -> bool:
        """Remove a registered account context.

        If the removed context was the current one, the earliest remaining
        context is promoted to current.

        Args:
            db: Deprecated compatibility parameter; ignored.
            account_id: The account to remove.

        Returns:
            True if a context was deleted, False if it was not found.
        """
        target = self.get_context_by_account_id(db, account_id)
        if not target:
            return False

        was_current = target.is_current
        _delete_context_record(target.id)

        logger.info("Removed account context %s", account_id)

        # Promote the first remaining context if we just deleted the current one
        if was_current:
            contexts = self.get_all_contexts(db)
            first = contexts[0] if contexts else None
            if first:
                payload = _namespace_to_payload(first)
                payload["is_current"] = True
                payload["last_used_at"] = datetime.now(timezone.utc)
                _update_context_record(first.id, payload)
                logger.info(
                    "Promoted account %s as new current context",
                    first.account_id,
                )

        return True

    # ------------------------------------------------------------------
    # Startup gate
    # ------------------------------------------------------------------

    def ensure_context(
        self,
        db,
        account_id: str,
        user_arn: str,
        region: Optional[str] = None,
    ) -> Dict:
        """Startup gate -- ensure the CLI has a valid current context.

        Call this early in CLI / web startup after STS get-caller-identity
        returns the active account_id and user_arn.

        Returns a dict with keys:
            status   -- "first_run" | "ok" | "switch_required" | "add_required"
            context  -- the relevant account context payload (or the newly created one)
            message  -- human-readable explanation
        """
        all_contexts = self.get_all_contexts(db)

        # ---- No contexts exist: first-run auto-registration ----
        if not all_contexts:
            ctx = self.add_context(
                db,
                account_id=account_id,
                user_arn=user_arn,
                region=region,
                set_current=True,
            )
            return {
                "status": "first_run",
                "context": ctx,
                "message": (
                    f"Registered account {account_id} as the first context."
                ),
            }

        current = self.get_current_context(db)

        # ---- Current context matches caller ----
        if current and current.account_id == account_id:
            payload = _namespace_to_payload(current)
            payload["last_used_at"] = datetime.now(timezone.utc)
            current = _objectify(_update_context_record(current.id, payload))
            return {
                "status": "ok",
                "context": current,
                "message": f"Using account {account_id}.",
            }

        # ---- Account is registered but not current ----
        registered = self.get_context_by_account_id(db, account_id)
        if registered:
            current_label = (
                current.account_id if current else "none"
            )
            return {
                "status": "switch_required",
                "context": registered,
                "message": (
                    f"AWS credentials point to account {account_id}, "
                    f"but the current context is {current_label}. "
                    "Run 'context switch' to change."
                ),
            }

        # ---- Account not registered at all ----
        current_label = current.account_id if current else "none"
        return {
            "status": "add_required",
            "context": None,
            "message": (
                f"AWS credentials point to account {account_id}, "
                f"which is not registered. Current context is {current_label}. "
                "Run 'context add' to register this account."
            ),
        }

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _clear_current(self, db) -> None:
        """Set is_current=False on all contexts."""
        for ctx in self.get_all_contexts(db):
            if ctx.is_current:
                payload = _namespace_to_payload(ctx)
                payload["is_current"] = False
                _update_context_record(ctx.id, payload)


def _list_context_records(
    *,
    filters: list[tuple[str, str]] | None = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    params: list[tuple[str, str | int]] = [
        ("limit", limit),
        ("order_by", "created_at"),
        ("descending", "false"),
    ]
    for field, value in filters or []:
        params.append(("filter", f"{field}={value}"))
    rows = request_core(
        "GET",
        "/api/v1/storage/core/account-context",
        service_token=True,
        params=params,
        timeout=10.0,
    )
    return [row.get("payload", row) for row in rows or []]


def _create_context_record(payload: dict[str, Any]) -> dict[str, Any]:
    record = request_core(
        "POST",
        "/api/v1/storage/core/account-context",
        service_token=True,
        json={"payload": _jsonable(payload)},
        timeout=10.0,
    )
    return record.get("payload", record)


def _update_context_record(record_key: str, payload: dict[str, Any]) -> dict[str, Any]:
    record = request_core(
        "PUT",
        f"/api/v1/storage/core/account-context/{record_key}",
        service_token=True,
        json={"payload": _jsonable(payload)},
        timeout=10.0,
    )
    return record.get("payload", record)


def _delete_context_record(record_key: str) -> None:
    request_core(
        "DELETE",
        f"/api/v1/storage/core/account-context/{record_key}",
        service_token=True,
        timeout=10.0,
    )


def _objectify(payload: dict[str, Any]) -> Any:
    normalized = dict(payload)
    for key in ("created_at", "last_used_at"):
        if isinstance(normalized.get(key), str):
            try:
                parsed = datetime.fromisoformat(normalized[key].replace("Z", "+00:00"))
                normalized[key] = parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
            except ValueError:
                pass
    return SimpleNamespace(**normalized)


def _namespace_to_payload(ctx: Any) -> dict[str, Any]:
    payload = vars(ctx).copy() if not isinstance(ctx, dict) else dict(ctx)
    return {
        key: payload.get(key)
        for key in (
            "id",
            "account_id",
            "account_alias",
            "aws_profile",
            "region",
            "user_arn",
            "is_current",
            "created_at",
            "last_used_at",
        )
        if key in payload
    }


def _jsonable(value):
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {key: _jsonable(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_jsonable(item) for item in value]
    return value


# Module-level singleton
account_context_service = AccountContextService()
