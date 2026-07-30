"""Cache with graceful Redis degradation (§8).

Redis is the intended backend, but the app must run without it — a dev machine with no
Redis should still work, just with a smaller, process-local cache. `get_cache()` probes
Redis once and silently falls back to an in-process TTL dict if it's unreachable.

TTLs are per-domain and set by the caller (see Settings): places/maps in days, weather in
hours, flight offers in minutes because Duffel offers expire in ~1h.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import time
from typing import Any

logger = logging.getLogger(__name__)


def cache_key(namespace: str, payload: dict[str, Any]) -> str:
    """Stable key from a request payload. Sorted keys so argument order can't
    produce two entries for the same logical query."""
    blob = json.dumps(payload, sort_keys=True, default=str)
    digest = hashlib.sha256(blob.encode()).hexdigest()[:24]
    return f"tripai:{namespace}:{digest}"


class _MemoryCache:
    """Process-local TTL cache. Bounded so a long-running server can't grow forever."""

    def __init__(self, max_entries: int = 2000) -> None:
        self._data: dict[str, tuple[float, Any]] = {}
        self._max = max_entries
        self._lock = asyncio.Lock()

    async def get(self, key: str) -> Any | None:
        async with self._lock:
            entry = self._data.get(key)
            if entry is None:
                return None
            expires_at, value = entry
            if expires_at < time.time():
                self._data.pop(key, None)
                return None
            return value

    async def set(self, key: str, value: Any, ttl: int) -> None:
        async with self._lock:
            if len(self._data) >= self._max:
                # Drop the soonest-to-expire entries rather than clearing wholesale.
                for stale in sorted(self._data, key=lambda k: self._data[k][0])[
                    : self._max // 4
                ]:
                    self._data.pop(stale, None)
            self._data[key] = (time.time() + ttl, value)

    async def delete(self, key: str) -> None:
        async with self._lock:
            self._data.pop(key, None)

    async def close(self) -> None:
        self._data.clear()

    @property
    def backend(self) -> str:
        return "memory"


class _RedisCache:
    def __init__(self, client: Any) -> None:
        self._client = client

    async def get(self, key: str) -> Any | None:
        try:
            raw = await self._client.get(key)
        except Exception as exc:
            logger.warning("cache.redis_get_failed key=%s error=%s", key, exc)
            return None
        if raw is None:
            return None
        try:
            return json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return None

    async def set(self, key: str, value: Any, ttl: int) -> None:
        try:
            await self._client.set(key, json.dumps(value, default=str), ex=ttl)
        except Exception as exc:
            # A cache write failure must never fail the request it belongs to.
            logger.warning("cache.redis_set_failed key=%s error=%s", key, exc)

    async def delete(self, key: str) -> None:
        try:
            await self._client.delete(key)
        except Exception as exc:
            logger.warning("cache.redis_del_failed key=%s error=%s", key, exc)

    async def close(self) -> None:
        try:
            await self._client.aclose()
        except Exception:
            pass

    @property
    def backend(self) -> str:
        return "redis"


Cache = _RedisCache | _MemoryCache
_cache: Cache | None = None


async def get_cache() -> Cache:
    global _cache
    if _cache is not None:
        return _cache

    from app.config import get_settings

    settings = get_settings()
    if not settings.cache_enabled or not settings.redis_url:
        _cache = _MemoryCache()
        return _cache

    try:
        import redis.asyncio as aioredis

        client = aioredis.from_url(
            settings.redis_url, decode_responses=True, socket_connect_timeout=2
        )
        await asyncio.wait_for(client.ping(), timeout=2.0)
        _cache = _RedisCache(client)
        logger.info("cache.backend=redis url=%s", settings.redis_url.split("@")[-1])
    except Exception as exc:
        logger.info(
            "cache.redis_unavailable falling back to in-process cache (%s)",
            type(exc).__name__,
        )
        _cache = _MemoryCache()
    return _cache


async def close_cache() -> None:
    global _cache
    if _cache is not None:
        await _cache.close()
        _cache = None
