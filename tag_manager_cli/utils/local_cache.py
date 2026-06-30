"""Local file-based cache implementation using diskcache."""

import os
import time
from typing import Any, Optional, Dict, List
from functools import wraps

from diskcache import Cache
from rich.console import Console

from .env_config import settings

console = Console()


class LocalCacheManager:
    """Manages file-based caching using diskcache library."""

    def __init__(self, cache_dir: Optional[str] = None):
        """Initialize the local cache manager.

        Args:
            cache_dir: Directory for cache storage. Defaults to ~/.tag-manager/cache
        """
        if not cache_dir:
            cache_dir = os.path.expanduser('~/.tag-manager/cache')

        self._cache_dir = cache_dir
        self._cache = None  # Lazy initialization
        self._initialized = False

        # In-memory cache for hot data (frequently accessed items)
        self.memory_cache: Dict[str, tuple[Any, float]] = {}
        self.memory_cache_ttl = 60  # 1 minute for memory cache

        self.enabled = True
        self.stats = {
            'hits': 0,
            'misses': 0,
            'sets': 0,
            'deletes': 0
        }

        if settings.debug:
            console.print(f"[green]LocalCache configured for: {self._cache_dir}[/green]")

    @property
    def cache(self) -> Cache:
        """Lazy initialize the cache on first access."""
        if self._cache is None:
            # Create cache directory if it doesn't exist
            os.makedirs(self._cache_dir, mode=0o755, exist_ok=True)

            # Initialize diskcache with 500MB size limit
            self._cache = Cache(
                self._cache_dir,
                size_limit=500_000_000,  # 500MB
                eviction_policy='least-recently-used'
            )
            self._initialized = True

            if settings.debug:
                console.print(f"[green]LocalCache actually initialized at: {self._cache_dir}[/green]")

        return self._cache

    def get(self, key: str) -> Optional[Any]:
        """Get value from cache.

        Args:
            key: Cache key

        Returns:
            Cached value or None if not found/expired
        """
        if not self.enabled:
            return None

        try:
            # Check memory cache first
            if key in self.memory_cache:
                value, expiry = self.memory_cache[key]
                if time.time() < expiry:
                    self.stats['hits'] += 1
                    return value
                else:
                    # Expired in memory cache, remove it
                    del self.memory_cache[key]

            # Check disk cache
            value = self.cache.get(key, default=None)
            if value is not None:
                self.stats['hits'] += 1
                # Promote to memory cache for faster access
                self.memory_cache[key] = (value, time.time() + self.memory_cache_ttl)
                return value

            self.stats['misses'] += 1
            return None

        except Exception as e:
            if settings.debug:
                console.print(f"[yellow]Cache get error for {key}: {e}[/yellow]")
            return None

    def set(self, key: str, value: Any, ttl: int = 300) -> bool:
        """Set value in cache with TTL.

        Args:
            key: Cache key
            value: Value to cache
            ttl: Time to live in seconds (default 5 minutes)

        Returns:
            True if successful, False otherwise
        """
        if not self.enabled:
            return False

        try:
            # Store in disk cache with TTL
            self.cache.set(key, value, expire=ttl)

            # Also cache in memory for fast access (short-lived items only)
            if ttl <= 300:  # Only cache items with TTL <= 5 minutes in memory
                self.memory_cache[key] = (value, time.time() + min(ttl, self.memory_cache_ttl))

            self.stats['sets'] += 1
            return True

        except Exception as e:
            if settings.debug:
                console.print(f"[yellow]Cache set error for {key}: {e}[/yellow]")
            return False

    def delete(self, key: str) -> bool:
        """Delete key from cache.

        Args:
            key: Cache key to delete

        Returns:
            True if key was deleted, False otherwise
        """
        if not self.enabled:
            return False

        try:
            # Remove from memory cache
            if key in self.memory_cache:
                del self.memory_cache[key]

            # Remove from disk cache
            result = self.cache.delete(key)
            if result:
                self.stats['deletes'] += 1
            return result

        except Exception as e:
            if settings.debug:
                console.print(f"[yellow]Cache delete error for {key}: {e}[/yellow]")
            return False

    def clear(self, pattern: Optional[str] = None) -> int:
        """Clear cache entries.

        Args:
            pattern: Optional pattern to match keys (supports wildcards)

        Returns:
            Number of entries cleared
        """
        if not self.enabled:
            return 0

        try:
            if pattern:
                # Clear matching keys
                count = 0
                for key in list(self.cache):
                    if self._match_pattern(key, pattern):
                        self.delete(key)
                        count += 1
                return count
            else:
                # Clear all
                self.memory_cache.clear()
                size = len(self.cache)
                self.cache.clear()
                return size

        except Exception as e:
            if settings.debug:
                console.print(f"[yellow]Cache clear error: {e}[/yellow]")
            return 0

    def exists(self, key: str) -> bool:
        """Check if key exists in cache.

        Args:
            key: Cache key

        Returns:
            True if key exists and is not expired
        """
        return self.get(key) is not None

    def get_stats(self) -> Dict[str, Any]:
        """Get cache statistics.

        Returns:
            Dictionary with cache statistics
        """
        try:
            disk_stats = {
                'size': self.cache.volume(),
                'count': len(self.cache),
                'directory': self.cache.directory
            }
        except:
            disk_stats = {}

        return {
            'enabled': self.enabled,
            'hits': self.stats['hits'],
            'misses': self.stats['misses'],
            'sets': self.stats['sets'],
            'deletes': self.stats['deletes'],
            'hit_rate': self.stats['hits'] / (self.stats['hits'] + self.stats['misses'])
                        if (self.stats['hits'] + self.stats['misses']) > 0 else 0,
            'memory_cache_size': len(self.memory_cache),
            'disk_cache': disk_stats
        }

    def close(self):
        """Close cache connections."""
        try:
            self.cache.close()
            self.memory_cache.clear()
            if settings.debug:
                console.print("[yellow]LocalCache closed[/yellow]")
        except:
            pass

    def _match_pattern(self, key: str, pattern: str) -> bool:
        """Match key against pattern with wildcard support.

        Args:
            key: Key to match
            pattern: Pattern with optional wildcards (*)

        Returns:
            True if key matches pattern
        """
        import fnmatch
        return fnmatch.fnmatch(key, pattern)

    # Decorator for caching function results
    def cached(self, ttl: int = 300, key_prefix: Optional[str] = None):
        """Decorator to cache function results.

        Args:
            ttl: Time to live in seconds
            key_prefix: Optional prefix for cache keys

        Returns:
            Decorated function
        """
        def decorator(func):
            @wraps(func)
            def wrapper(*args, **kwargs):
                # Generate cache key
                if key_prefix:
                    cache_key = f"{key_prefix}:{func.__name__}:{args}:{kwargs}"
                else:
                    cache_key = f"{func.__module__}.{func.__name__}:{args}:{kwargs}"

                # Try to get from cache
                result = self.get(cache_key)
                if result is not None:
                    if settings.debug:
                        console.print(f"[dim]Cache hit: {func.__name__}[/dim]")
                    return result

                # Execute function and cache result
                result = func(*args, **kwargs)
                self.set(cache_key, result, ttl=ttl)
                return result

            return wrapper
        return decorator


# Global cache instance
cache_manager = LocalCacheManager()


def get_cache() -> LocalCacheManager:
    """Get the global cache manager instance.

    Returns:
        LocalCacheManager instance
    """
    return cache_manager


def cache_key(*parts) -> str:
    """Generate a cache key from parts.

    Args:
        *parts: Key components to join

    Returns:
        Cache key string
    """
    return ':'.join(str(p) for p in parts)


def invalidate_cache(pattern: Optional[str] = None) -> int:
    """Invalidate cache entries.

    Args:
        pattern: Optional pattern to match keys

    Returns:
        Number of entries invalidated
    """
    return cache_manager.clear(pattern)