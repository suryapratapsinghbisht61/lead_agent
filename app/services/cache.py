"""Tiny disk cache for Bright Data responses.

Why: every Bright Data request costs credits. If we search the same query or
scrape the same page again within CACHE_TTL_HOURS, we reuse the saved copy.
diskcache stores data in a local SQLite file under .cache/, so it survives restarts.
(In the later web-app stage this can be swapped for Redis with the same functions.)
"""

import hashlib
import json
from functools import lru_cache
from typing import Any

from diskcache import Cache

from app.core.config import get_settings


@lru_cache
def _cache() -> Cache:
    return Cache(str(get_settings().cache_dir))


def make_key(kind: str, **parts: Any) -> str:
    """Build a stable key, e.g. make_key("serp", q="automate invoices") -> "serp:3f9a..."."""
    raw = json.dumps(parts, sort_keys=True, default=str)
    return f"{kind}:{hashlib.sha256(raw.encode()).hexdigest()[:32]}"


def cache_get(key: str) -> Any | None:
    return _cache().get(key)


def cache_set(key: str, value: Any, ttl_hours: int | None = None) -> None:
    hours = ttl_hours or get_settings().cache_ttl_hours
    _cache().set(key, value, expire=hours * 3600)


def cache_clear() -> None:
    _cache().clear()
