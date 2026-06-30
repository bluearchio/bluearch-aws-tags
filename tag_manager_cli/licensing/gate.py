"""Open-source compatibility helpers for former feature gates."""

import functools


def is_feature_allowed(feature: str) -> bool:
    return True


def requires_tier(feature: str):
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            return func(*args, **kwargs)

        return wrapper

    return decorator


def check_feature(feature: str) -> None:
    return None


def get_available_collectors() -> dict:
    from ..modules.collection.collectors import COLLECTORS

    return dict(COLLECTORS)
