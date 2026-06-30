"""Migration manager for the bluearch-core-owned database."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from .core_client import request_core

logger = logging.getLogger(__name__)


class MigrationManager:
    """Compatibility wrapper for old Tag Manager migration callers."""

    def __init__(self):
        self.docker_dir = Path.home() / ".tag-manager"
        self.compose_file = self.docker_dir / "docker-compose.yml"

    def is_docker_setup_available(self) -> bool:
        """Return whether an old Docker setup exists for diagnostic output."""
        return self.compose_file.exists()

    def is_docker_running(self) -> bool:
        """Docker is no longer part of product DB migrations."""
        return False

    def run_direct_sql_migration(self) -> bool:
        """Run the core-owned database migration/import flow."""
        try:
            request_core("POST", "/api/v1/core/db/migrate?import_legacy=true", service_token=True, timeout=120.0)
            return True
        except Exception as exc:
            logger.error("Core database migration failed: %s", exc)
            return False

    def run_migrations_via_docker(self) -> bool:
        """Compatibility method: delegate to bluearch-core."""
        return self.run_direct_sql_migration()

    def run_migrations_via_alembic(self) -> bool:
        """Compatibility method: delegate to bluearch-core."""
        return self.run_direct_sql_migration()

    def run_migrations_via_sql(self) -> bool:
        """Compatibility method: delegate to bluearch-core."""
        return self.run_direct_sql_migration()

    def run_post_update_migrations(self) -> dict[str, Any]:
        """Run migrations after an app update."""
        if self.run_direct_sql_migration():
            return {
                "success": True,
                "method": "bluearch-core",
                "message": "Core database migrations completed",
                "details": {},
            }
        return {
            "success": False,
            "method": "bluearch-core",
            "message": "Core database migration failed",
            "details": {},
        }

    def check_migration_status(self) -> dict[str, Any]:
        """Check core database status."""
        status = {
            "docker_available": self.is_docker_setup_available(),
            "docker_running": False,
            "system_executions_exists": False,
            "needs_migration": True,
        }
        try:
            response = request_core("GET", "/api/v1/core/db/status", service_token=True, timeout=10.0)
            table_names = set(response.get("tables") or response.get("table_names") or [])
            status.update(
                {
                    "system_executions_exists": "system_executions" in table_names,
                    "needs_migration": not response.get("ready", False),
                    "core_ready": response.get("ready", False),
                    "table_count": response.get("table_count", len(table_names)),
                }
            )
        except Exception as exc:
            logger.error("Error checking core migration status: %s", exc)
        return status


migration_manager = MigrationManager()


def run_post_update_migrations() -> bool:
    """Convenience function to run post-update migrations."""
    result = migration_manager.run_post_update_migrations()
    return result["success"]


def check_needs_migration() -> bool:
    """Check if migration is needed."""
    status = migration_manager.check_migration_status()
    return bool(status["needs_migration"])
