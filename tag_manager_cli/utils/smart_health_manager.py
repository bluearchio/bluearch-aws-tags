"""Smart health check manager with intelligent scheduling and caching."""

import os
import time
import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, Optional, Any
from dataclasses import dataclass, asdict

from .health_manager import health_manager, HealthCheckResult
from .migration_manager import migration_manager
from .display_utils import print_safe


@dataclass
class HealthCacheEntry:
    """Cached health check result with timing information."""
    timestamp: float
    is_healthy: bool
    last_action: Optional[str]
    check_interval: int  # seconds until next check needed
    consecutive_healthy: int = 0
    consecutive_unhealthy: int = 0


class SmartHealthManager:
    """Intelligent health check manager that reduces unnecessary checks."""

    def __init__(self):
        self.cache_file = Path.home() / ".tag-manager" / "health_cache.json"
        self.cache_file.parent.mkdir(exist_ok=True)

        # Health check intervals (in seconds)
        self.intervals = {
            'slack_worker': {
                'healthy': 300,      # 5 minutes when healthy
                'unhealthy': 30,     # 30 seconds when unhealthy
                'critical': 10       # 10 seconds if critical issues
            },
            'worker_discovery': {
                'healthy': 1800,     # 30 minutes when healthy
                'unhealthy': 600,    # 10 minutes when unhealthy
                'critical': 300      # 5 minutes if critical
            },
            'database_migration': {
                'healthy': 1800,     # 30 minutes when healthy
                'unhealthy': 120,    # 2 minutes when unhealthy
                'critical': 60       # 1 minute if critical
            }
        }

        # Commands that should skip health checks entirely
        self.skip_commands = {
            '--version', '-V', '--help', '-h', 'dev', 'database',
            'onboarding', 'setup'  # Add onboarding commands
        }

        # Commands that need only lightweight checks
        self.lightweight_commands = {
            'tags', 'slack', 'workers', 'interactive', 'cost'
        }

    def _load_cache(self) -> Dict[str, HealthCacheEntry]:
        """Load health check cache from disk."""
        try:
            if self.cache_file.exists():
                with open(self.cache_file, 'r') as f:
                    data = json.load(f)
                    return {
                        k: HealthCacheEntry(**v)
                        for k, v in data.items()
                    }
        except Exception:
            pass
        return {}

    def _save_cache(self, cache: Dict[str, HealthCacheEntry]):
        """Save health check cache to disk."""
        try:
            with open(self.cache_file, 'w') as f:
                json.dump({k: asdict(v) for k, v in cache.items()}, f)
        except Exception:
            pass

    def _should_skip_checks(self) -> bool:
        """Check if we should skip health checks based on command context."""
        import sys

        # Skip if environment variable is set
        if os.environ.get('TAG_MANAGER_NO_HEALTH_CHECK') == '1':
            return True

        # Skip for certain commands
        if any(cmd in sys.argv for cmd in self.skip_commands):
            return True

        return False

    def _is_lightweight_context(self) -> bool:
        """Check if we're in a lightweight command context."""
        import sys

        # Force full check if explicitly requested
        if os.environ.get('TAG_MANAGER_FORCE_FULL_CHECK') == '1':
            return False

        return any(cmd in sys.argv for cmd in self.lightweight_commands)

    def _should_check_service(self, service_name: str, cache: Dict[str, HealthCacheEntry]) -> bool:
        """Determine if a service needs to be checked based on cache and intervals."""
        if service_name not in cache:
            return True

        entry = cache[service_name]
        now = time.time()
        elapsed = now - entry.timestamp

        # Determine which interval to use based on health status
        intervals = self.intervals.get(service_name, {'healthy': 300, 'unhealthy': 60, 'critical': 30})

        if entry.consecutive_unhealthy > 3:
            check_interval = intervals['critical']
        elif not entry.is_healthy:
            check_interval = intervals['unhealthy']
        else:
            check_interval = intervals['healthy']

        return elapsed >= check_interval

    def _update_cache_entry(self, service_name: str, is_healthy: bool, action: Optional[str],
                          cache: Dict[str, HealthCacheEntry]) -> HealthCacheEntry:
        """Update cache entry with new health check result."""
        now = time.time()

        if service_name in cache:
            entry = cache[service_name]
            if is_healthy:
                entry.consecutive_healthy += 1
                entry.consecutive_unhealthy = 0
            else:
                entry.consecutive_healthy = 0
                entry.consecutive_unhealthy += 1
        else:
            entry = HealthCacheEntry(
                timestamp=now,
                is_healthy=is_healthy,
                last_action=action,
                check_interval=300,
                consecutive_healthy=1 if is_healthy else 0,
                consecutive_unhealthy=0 if is_healthy else 1
            )

        entry.timestamp = now
        entry.is_healthy = is_healthy
        entry.last_action = action

        return entry

    def run_smart_health_checks(self) -> Dict[str, Any]:
        """Run intelligent health checks with caching and scheduling."""
        if self._should_skip_checks():
            return {'skipped': True, 'reason': 'command_context'}

        cache = self._load_cache()
        results = {}
        checks_performed = 0
        lightweight = self._is_lightweight_context()

        try:
            # 1. Database Migration Check (highest priority)
            if self._should_check_service('database_migration', cache):
                try:
                    status = migration_manager.check_migration_status()
                    needs_migration = status.get("needs_migration", False)
                    action = None

                    if needs_migration and not lightweight:
                        # Try to run migrations automatically
                        result = migration_manager.run_post_update_migrations()
                        action = f"migration_{result['method']}" if result["success"] else None

                        if result["success"]:
                            print_safe(f"[green]Database migrations completed automatically ({result['method']})[/green]")

                        cache['database_migration'] = self._update_cache_entry(
                            'database_migration', result["success"], action, cache
                        )
                    else:
                        cache['database_migration'] = self._update_cache_entry(
                            'database_migration', not needs_migration, None, cache
                        )

                    results['database_migration'] = {
                        'checked': True,
                        'healthy': not needs_migration,
                        'action': action
                    }
                    checks_performed += 1

                except Exception as e:
                    cache['database_migration'] = self._update_cache_entry(
                        'database_migration', False, None, cache
                    )
                    results['database_migration'] = {'checked': True, 'healthy': False, 'error': str(e)}
            else:
                results['database_migration'] = {'checked': False, 'reason': 'cached'}

            # 2. Slack Worker Check (medium priority, skip in lightweight)
            if not lightweight and self._should_check_service('slack_worker', cache):
                try:
                    slack_result = health_manager.ensure_slack_worker_running()
                    action = slack_result.action_taken if hasattr(slack_result, 'action_taken') else None

                    cache['slack_worker'] = self._update_cache_entry(
                        'slack_worker', slack_result.is_healthy, action, cache
                    )

                    results['slack_worker'] = {
                        'checked': True,
                        'healthy': slack_result.is_healthy,
                        'action': action
                    }
                    checks_performed += 1

                except Exception as e:
                    cache['slack_worker'] = self._update_cache_entry(
                        'slack_worker', False, None, cache
                    )
                    results['slack_worker'] = {'checked': True, 'healthy': False, 'error': str(e)}
            else:
                results['slack_worker'] = {'checked': False, 'reason': 'lightweight_or_cached'}

            # 3. Worker Discovery Check (lowest priority, skip in lightweight)
            if not lightweight and self._should_check_service('worker_discovery', cache):
                try:
                    discovery_result = health_manager.ensure_worker_discovery_current()
                    action = discovery_result.action_taken if hasattr(discovery_result, 'action_taken') else None

                    cache['worker_discovery'] = self._update_cache_entry(
                        'worker_discovery', discovery_result.is_healthy, action, cache
                    )

                    results['worker_discovery'] = {
                        'checked': True,
                        'healthy': discovery_result.is_healthy,
                        'action': action
                    }
                    checks_performed += 1

                except Exception as e:
                    cache['worker_discovery'] = self._update_cache_entry(
                        'worker_discovery', False, None, cache
                    )
                    results['worker_discovery'] = {'checked': True, 'healthy': False, 'error': str(e)}
            else:
                results['worker_discovery'] = {'checked': False, 'reason': 'lightweight_or_cached'}

        except Exception as e:
            results['error'] = str(e)
        finally:
            # Always save cache
            self._save_cache(cache)

        results['summary'] = {
            'checks_performed': checks_performed,
            'lightweight_mode': lightweight,
            'cache_entries': len(cache)
        }

        return results

    def force_check_all(self) -> Dict[str, Any]:
        """Force a complete health check of all services (bypass cache)."""
        # Clear cache to force all checks
        if self.cache_file.exists():
            self.cache_file.unlink()

        # Temporarily disable lightweight mode
        os.environ['TAG_MANAGER_FORCE_FULL_CHECK'] = '1'
        try:
            return self.run_smart_health_checks()
        finally:
            os.environ.pop('TAG_MANAGER_FORCE_FULL_CHECK', None)

    def get_health_summary(self) -> Dict[str, Any]:
        """Get current health status from cache without running new checks."""
        cache = self._load_cache()
        summary = {}

        for service, entry in cache.items():
            age_minutes = (time.time() - entry.timestamp) / 60
            summary[service] = {
                'healthy': entry.is_healthy,
                'last_check_minutes_ago': round(age_minutes, 1),
                'consecutive_healthy': entry.consecutive_healthy,
                'consecutive_unhealthy': entry.consecutive_unhealthy,
                'last_action': entry.last_action
            }

        return summary


# Global instance
smart_health_manager = SmartHealthManager()