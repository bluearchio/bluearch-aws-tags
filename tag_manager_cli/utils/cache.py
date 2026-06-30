"""Caching utilities for Tag Manager CLI using local file-based cache."""

import os
import sys
from typing import Any, Optional

from .local_cache import LocalCacheManager, cache_key
from .env_config import settings
from rich.console import Console

# Create console with proper UTF-8 handling
if hasattr(sys.stdout, 'reconfigure'):
    try:
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
    except Exception:
        pass

console = Console()


class CacheManager:
    """Manages caching for AWS API responses using local file-based cache."""

    def __init__(self):
        """Initialize the cache manager."""
        self.cache = LocalCacheManager()
        self.enabled = self.cache.enabled
        self.redis_client = None  # Backward compatibility

        # Show initialization message
        try:
            from .startup_messages import startup_messages
            if startup_messages.should_show_message('cache'):
                console.print(f"[green]OK Local cache initialized[/green]")
        except ImportError:
            if settings.debug:
                console.print(f"[green]OK Local cache initialized[/green]")

    def get(self, key: str) -> Optional[Any]:
        """Get value from cache.

        Args:
            key: Cache key

        Returns:
            Cached value or None
        """
        if not self.enabled:
            return None

        return self.cache.get(key)

    def set(self, key: str, value: Any, ttl: int = None) -> bool:
        """Set value in cache.

        Args:
            key: Cache key
            value: Value to cache
            ttl: Time to live in seconds

        Returns:
            True if successful
        """
        if not self.enabled:
            return False

        # Use default TTL from settings if not specified
        if ttl is None:
            ttl = settings.cache_ttl_resources

        return self.cache.set(key, value, ttl=ttl)

    def setex(self, key: str, ttl: int, value: Any) -> bool:
        """Set value with expiration (Redis compatibility).

        Args:
            key: Cache key
            ttl: Time to live in seconds
            value: Value to cache

        Returns:
            True if successful
        """
        return self.set(key, value, ttl=ttl)

    def delete(self, key: str) -> bool:
        """Delete key from cache.

        Args:
            key: Cache key

        Returns:
            True if deleted
        """
        if not self.enabled:
            return False

        return self.cache.delete(key)

    def exists(self, key: str) -> bool:
        """Check if key exists in cache.

        Args:
            key: Cache key

        Returns:
            True if exists
        """
        if not self.enabled:
            return False

        return self.cache.exists(key)

    def clear_pattern(self, pattern: str) -> int:
        """Clear cache entries matching pattern.

        Args:
            pattern: Pattern to match (supports wildcards)

        Returns:
            Number of entries cleared
        """
        if not self.enabled:
            return 0

        return self.cache.clear(pattern)

    def get_stats(self) -> dict:
        """Get cache statistics.

        Returns:
            Dictionary with cache statistics
        """
        if not self.enabled:
            return {'enabled': False}

        return self.cache.get_stats()

    def generate_key(self, service: str, operation: str, **kwargs) -> str:
        """Generate a cache key from service, operation, and parameters.

        This method creates consistent cache keys for AWS operations by combining
        the service name, operation name, and any additional parameters.

        Args:
            service: AWS service name (e.g., 'ec2', 's3', 'lambda')
            operation: API operation name (e.g., 'describe_instances', 'list_buckets')
            **kwargs: Additional parameters to include in the key (e.g., region='us-east-1')

        Returns:
            Generated cache key string

        Example:
            >>> cache.generate_key('ec2', 'describe_instances', region='us-east-1')
            'aws:ec2:describe_instances:region=us-east-1'
        """
        import json

        # Convert kwargs to consistent string representation
        if kwargs:
            # Sort for consistency and convert to JSON
            params_str = json.dumps(kwargs, sort_keys=True)
            return cache_key('aws', service, operation, params_str)
        else:
            return cache_key('aws', service, operation)

    # Helper methods for specific cache operations
    def cache_aws_response(self, service: str, operation: str, params: dict, response: Any, ttl: int = None) -> bool:
        """Cache an AWS API response.

        Args:
            service: AWS service name
            operation: API operation name
            params: Request parameters
            response: API response
            ttl: Time to live in seconds

        Returns:
            True if cached successfully
        """
        if not self.enabled:
            return False

        # Generate cache key
        import json
        params_str = json.dumps(params, sort_keys=True)
        key = cache_key('aws', service, operation, params_str)

        # Use service-specific TTL if not specified
        if ttl is None:
            if 'cloudtrail' in service.lower():
                ttl = settings.cache_ttl_cloudtrail
            elif 'tagging' in operation.lower():
                ttl = settings.cache_ttl_tagging_rules
            else:
                ttl = settings.cache_ttl_resources

        return self.set(key, response, ttl=ttl)

    def get_aws_response(self, service: str, operation: str, params: dict) -> Optional[Any]:
        """Get cached AWS API response.

        Args:
            service: AWS service name
            operation: API operation name
            params: Request parameters

        Returns:
            Cached response or None
        """
        if not self.enabled:
            return None

        # Generate cache key
        import json
        params_str = json.dumps(params, sort_keys=True)
        key = cache_key('aws', service, operation, params_str)

        return self.get(key)

    def invalidate_service_cache(self, service: str) -> int:
        """Invalidate all cache entries for a service.

        Args:
            service: AWS service name

        Returns:
            Number of entries invalidated
        """
        if not self.enabled:
            return 0

        pattern = f"aws:{service}:*"
        return self.clear_pattern(pattern)


# Global cache instance
cache = CacheManager()


def get_cache() -> CacheManager:
    """Get the global cache manager instance.

    Returns:
        CacheManager instance
    """
    return cache


def invalidate_cache(pattern: Optional[str] = None) -> int:
    """Invalidate cache entries.

    Args:
        pattern: Optional pattern to match keys

    Returns:
        Number of entries invalidated
    """
    if pattern:
        return cache.clear_pattern(pattern)
    else:
        return cache.cache.clear()