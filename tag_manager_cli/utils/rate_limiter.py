"""Rate limiting utilities for AWS API calls."""

import time
import asyncio
from datetime import datetime, timedelta
from typing import Dict, Any, Optional, Callable
from collections import defaultdict, deque
from threading import Lock
from contextlib import contextmanager

from .cache import cache
from .env_config import settings


class RateLimiter:
    """Rate limiter for AWS API calls with per-service limits."""
    
    def __init__(self):
        self._call_history: Dict[str, deque] = defaultdict(deque)
        self._locks: Dict[str, Lock] = defaultdict(Lock)
        
        # AWS API rate limits per service (requests per second)
        self._service_limits = {
            'ec2': settings.aws_api_rate_limit_per_second,
            's3': settings.aws_api_rate_limit_per_second,
            'lambda': settings.aws_api_rate_limit_per_second,
            'cloudtrail': settings.cloudtrail_api_rate_limit_per_second,
            'resource-groups': 20,  # AWS Resource Groups Tagging API limit
            'sts': 50,  # STS has higher limits
            'default': 10  # Conservative default
        }
        
        # Burst allowance (can exceed rate for short periods)
        self._burst_allowance = {
            'ec2': 50,
            's3': 100,
            'lambda': 30,
            'cloudtrail': 20,
            'resource-groups': 40,
            'default': 20
        }
    
    def get_service_limit(self, service: str) -> int:
        """Get rate limit for a service."""
        return self._service_limits.get(service, self._service_limits['default'])
    
    def get_burst_allowance(self, service: str) -> int:
        """Get burst allowance for a service."""
        return self._burst_allowance.get(service, self._burst_allowance['default'])
    
    @contextmanager
    def throttle(self, service: str, operation: str = 'default', region: str = 'default'):
        """Context manager that enforces rate limiting."""
        key = f"{service}:{region}:{operation}"
        
        with self._locks[key]:
            self._enforce_rate_limit(key, service)
            
            start_time = time.time()
            try:
                yield
                # Record successful call
                self._record_call(key, success=True)
            except Exception as e:
                # Record failed call
                self._record_call(key, success=False)
                
                # If it's a throttling error, add extra delay
                if self._is_throttling_error(e):
                    self._handle_throttling_error(key, service)
                
                raise
            finally:
                duration = time.time() - start_time
                self._record_call_duration(key, duration)
    
    def _enforce_rate_limit(self, key: str, service: str):
        """Enforce rate limit for a service."""
        now = time.time()
        limit = self.get_service_limit(service)
        burst_allowance = self.get_burst_allowance(service)
        
        # Clean old entries (older than 1 second)
        call_times = self._call_history[key]
        while call_times and call_times[0] < now - 1.0:
            call_times.popleft()
        
        # Check if we're within limits
        current_rate = len(call_times)
        
        if current_rate >= burst_allowance:
            # Hard limit reached, must wait
            sleep_time = 1.0 - (now - call_times[0])
            if sleep_time > 0:
                time.sleep(sleep_time)
        elif current_rate >= limit:
            # Soft limit reached, small delay
            time.sleep(0.1)
    
    def _record_call(self, key: str, success: bool = True):
        """Record an API call."""
        now = time.time()
        self._call_history[key].append(now)
        
        # Store call statistics in cache
        stats_key = f"rate_limit_stats:{key}"
        stats = cache.get(stats_key) or {'total_calls': 0, 'failed_calls': 0, 'last_call': None}
        
        stats['total_calls'] += 1
        if not success:
            stats['failed_calls'] += 1
        stats['last_call'] = now
        
        cache.set(stats_key, stats, ttl=3600)  # Keep stats for 1 hour
    
    def _record_call_duration(self, key: str, duration: float):
        """Record call duration for performance monitoring."""
        duration_key = f"call_duration:{key}"
        durations = cache.get(duration_key) or []
        
        durations.append(duration)
        # Keep only last 100 durations
        durations = durations[-100:]
        
        cache.set(duration_key, durations, ttl=3600)
    
    def _is_throttling_error(self, exception: Exception) -> bool:
        """Check if exception is a throttling error."""
        error_message = str(exception).lower()
        throttling_indicators = [
            'throttling', 'rate exceeded', 'request rate limit',
            'too many requests', 'slow down', 'rate limit exceeded'
        ]
        
        return any(indicator in error_message for indicator in throttling_indicators)
    
    def _handle_throttling_error(self, key: str, service: str):
        """Handle throttling error with exponential backoff."""
        # Get current throttle count
        throttle_key = f"throttle_count:{key}"
        throttle_count = cache.get(throttle_key) or 0
        throttle_count += 1
        
        # Exponential backoff: 1s, 2s, 4s, 8s, max 30s
        delay = min(2 ** throttle_count, 30)
        
        cache.set(throttle_key, throttle_count, ttl=300)  # Reset after 5 minutes
        
        from rich.console import Console
        console = Console()
        console.print(f"[yellow]Rate limit hit for {service}, waiting {delay}s (attempt {throttle_count})[/yellow]")
        
        time.sleep(delay)
    
    def get_rate_limit_stats(self, service: str = None, region: str = None) -> Dict[str, Any]:
        """Get rate limiting statistics."""
        stats = {}
        
        for key in self._call_history.keys():
            key_parts = key.split(':')
            if len(key_parts) >= 3:
                key_service, key_region, key_operation = key_parts[0], key_parts[1], key_parts[2]
                
                # Filter by service and region if specified
                if service and key_service != service:
                    continue
                if region and key_region != region:
                    continue
                
                # Get cached stats
                stats_key = f"rate_limit_stats:{key}"
                call_stats = cache.get(stats_key) or {}
                
                # Get call durations
                duration_key = f"call_duration:{key}"
                durations = cache.get(duration_key) or []
                
                stats[key] = {
                    'service': key_service,
                    'region': key_region,
                    'operation': key_operation,
                    'total_calls': call_stats.get('total_calls', 0),
                    'failed_calls': call_stats.get('failed_calls', 0),
                    'last_call': call_stats.get('last_call'),
                    'current_rate': len(self._call_history[key]),
                    'avg_duration_ms': sum(durations) / len(durations) * 1000 if durations else 0,
                    'max_duration_ms': max(durations, default=0) * 1000,
                    'min_duration_ms': min(durations, default=0) * 1000
                }
        
        return stats
    
    def reset_rate_limits(self, service: str = None):
        """Reset rate limiting counters."""
        if service:
            # Reset for specific service
            keys_to_reset = [key for key in self._call_history.keys() if key.startswith(f"{service}:")]
        else:
            # Reset all
            keys_to_reset = list(self._call_history.keys())
        
        for key in keys_to_reset:
            self._call_history[key].clear()
            
            # Clear cached stats
            cache.delete(f"rate_limit_stats:{key}")
            cache.delete(f"call_duration:{key}")
            cache.delete(f"throttle_count:{key}")


class AsyncRateLimiter:
    """Async version of rate limiter for concurrent operations."""
    
    def __init__(self, rate_limiter: RateLimiter):
        self.rate_limiter = rate_limiter
        self._semaphores: Dict[str, asyncio.Semaphore] = {}
    
    async def throttle(self, service: str, operation: str = 'default', region: str = 'default'):
        """Async rate limiting context manager."""
        key = f"{service}:{region}:{operation}"
        
        # Get or create semaphore for this service
        if key not in self._semaphores:
            limit = self.rate_limiter.get_service_limit(service)
            self._semaphores[key] = asyncio.Semaphore(limit)
        
        semaphore = self._semaphores[key]
        
        async with semaphore:
            # Use the sync rate limiter's logic
            with self.rate_limiter.throttle(service, operation, region):
                yield


# Global rate limiter instance
rate_limiter = RateLimiter()
async_rate_limiter = AsyncRateLimiter(rate_limiter)


def throttled_aws_call(service: str, operation: str = 'default', region: str = 'default'):
    """Decorator for rate-limited AWS API calls."""
    def decorator(func: Callable):
        def wrapper(*args, **kwargs):
            with rate_limiter.throttle(service, operation, region):
                return func(*args, **kwargs)
        return wrapper
    return decorator


async def async_throttled_aws_call(service: str, operation: str = 'default', region: str = 'default'):
    """Async decorator for rate-limited AWS API calls."""
    def decorator(func: Callable):
        async def wrapper(*args, **kwargs):
            async with async_rate_limiter.throttle(service, operation, region):
                return await func(*args, **kwargs)
        return wrapper
    return decorator