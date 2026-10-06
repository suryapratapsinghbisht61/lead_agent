"""FastAPI dependencies: API-key auth and Redis-based rate limiting.

A "dependency" is a function FastAPI runs before your endpoint. Add
`key: ApiKey = Depends(require_api_key)` to an endpoint and it becomes protected.
"""

import time

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import APIKeyHeader

from app.core.config import get_settings
from app.db import repo
from app.db.models import ApiKey

api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False, description="Create one with scripts/api_keys.py")


def get_redis(request: Request):
    return request.app.state.redis


def require_api_key(raw_key: str | None = Depends(api_key_header)) -> ApiKey:
    if not raw_key:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Missing X-API-Key header")
    key = repo.find_api_key(raw_key)
    if key is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or revoked API key")
    return key


async def _hit(redis, bucket: str, limit: int, window_seconds: int) -> None:
    """Fixed-window counter: INCR a key that expires at the end of the window."""
    window = int(time.time() // window_seconds)
    key = f"ratelimit:{bucket}:{window}"
    count = await redis.incr(key)
    if count == 1:
        await redis.expire(key, window_seconds)
    if count > limit:
        retry_after = window_seconds - int(time.time() % window_seconds)
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, f"Rate limit exceeded ({limit} per {window_seconds}s)",
                            headers={"Retry-After": str(retry_after)})


async def rate_limited(request: Request, key: ApiKey = Depends(require_api_key)) -> ApiKey:
    """Auth + general per-key limit. Use this on every protected endpoint."""
    await _hit(get_redis(request), f"key:{key.id}", get_settings().rate_limit_per_minute, 60)
    return key


async def run_rate_limited(request: Request, key: ApiKey = Depends(rate_limited)) -> ApiKey:
    """Extra, stricter limit for starting runs (each run spends credits)."""
    await _hit(get_redis(request), f"runs:{key.id}", get_settings().runs_per_hour, 3600)
    return key
