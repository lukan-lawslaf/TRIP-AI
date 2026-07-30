"""Shared result envelope + HTTP plumbing for the deterministic tool layer.

Every tool returns a `ToolResult` rather than raising. §8's requirement is that a dead
provider degrades the itinerary instead of blocking it: the weather API being down should
produce "weather unavailable, planning without it", not a 500. Callers check `.ok` and the
orchestrator sees `.error` text it can relay honestly to the user.

`fetch_json` layers, in order: cache → circuit breaker → timeout → 1 retry → breaker
bookkeeping. The retry only fires for transient classes (timeout, 5xx, transport) — a 401
is retried zero times because the second attempt would fail identically.
"""

from __future__ import annotations

import asyncio
import logging
import random
from dataclasses import dataclass, field
from typing import Any, Literal

import httpx

from app.config import get_settings
from app.llm.breaker import get_api_breakers
from app.tools.cache import cache_key, get_cache

logger = logging.getLogger(__name__)

Status = Literal["ok", "error", "unavailable", "not_configured"]


@dataclass
class ToolResult:
    """Uniform envelope. `data` is only meaningful when `ok` is True."""

    source: str
    status: Status = "ok"
    data: Any = None
    error: str | None = None
    cached: bool = False
    latency_ms: float = 0.0
    meta: dict[str, Any] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return self.status == "ok"

    @classmethod
    def failure(
        cls, source: str, error: str, status: Status = "error"
    ) -> "ToolResult":
        return cls(source=source, status=status, error=error, data=None)

    @classmethod
    def missing_key(cls, source: str, env_name: str) -> "ToolResult":
        return cls(
            source=source,
            status="not_configured",
            error=f"{source} is not configured ({env_name} missing or invalid)",
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "status": self.status,
            "data": self.data,
            "error": self.error,
            "cached": self.cached,
            **({"meta": self.meta} if self.meta else {}),
        }


_client: httpx.AsyncClient | None = None


async def get_http_client() -> httpx.AsyncClient:
    """One shared connection pool for all external APIs."""
    global _client
    if _client is None:
        settings = get_settings()
        _client = httpx.AsyncClient(
            timeout=httpx.Timeout(settings.tool_timeout_seconds, connect=5.0),
            limits=httpx.Limits(max_connections=48, max_keepalive_connections=24),
            follow_redirects=True,
            headers={"User-Agent": "TripAI/1.0"},
        )
    return _client


async def close_http_client() -> None:
    global _client
    if _client is not None:
        await _client.aclose()
        _client = None


class RateLimiter:
    """Token-bucket-ish spacer for providers with hard per-second caps.

    liteAPI allows 5 req/s; exceeding it returns 429s that look like outages and would
    trip the circuit breaker for no good reason.
    """

    def __init__(self, per_second: float) -> None:
        self._min_interval = 1.0 / per_second if per_second > 0 else 0.0
        self._last = 0.0
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        if self._min_interval <= 0:
            return
        async with self._lock:
            loop = asyncio.get_running_loop()
            wait = self._min_interval - (loop.time() - self._last)
            if wait > 0:
                await asyncio.sleep(wait)
            self._last = loop.time()


_TRANSIENT = (httpx.TimeoutException, httpx.TransportError)


async def fetch_json(
    source: str,
    method: str,
    url: str,
    *,
    headers: dict[str, str] | None = None,
    params: dict[str, Any] | None = None,
    json_body: dict[str, Any] | None = None,
    cache_ttl: int | None = None,
    cache_namespace: str | None = None,
    limiter: RateLimiter | None = None,
    timeout: float | None = None,
    retries: int | None = None,
) -> ToolResult:
    """Cached, breaker-guarded, retrying JSON fetch. Never raises for network reasons."""
    settings = get_settings()
    retries = settings.tool_retries if retries is None else retries
    breakers = get_api_breakers()
    cache = await get_cache()

    key: str | None = None
    if cache_ttl:
        key = cache_key(
            cache_namespace or source,
            {"m": method, "u": url, "p": params or {}, "b": json_body or {}},
        )
        hit = await cache.get(key)
        if hit is not None:
            logger.debug("tool.cache_hit source=%s", source)
            return ToolResult(source=source, data=hit, cached=True)

    if not breakers.allows(source):
        status = breakers.status(source)
        return ToolResult.failure(
            source,
            f"{source} temporarily unavailable (circuit open, retry in "
            f"{status.seconds_until_retry:.0f}s)",
            status="unavailable",
        )

    client = await get_http_client()
    loop = asyncio.get_running_loop()
    started = loop.time()
    last_error = "unknown error"

    for attempt in range(retries + 1):
        if limiter:
            await limiter.acquire()
        try:
            resp = await client.request(
                method,
                url,
                headers=headers,
                params=params,
                json=json_body,
                timeout=timeout or settings.tool_timeout_seconds,
            )
        except _TRANSIENT as exc:
            last_error = f"{type(exc).__name__}: {exc}"
            if attempt < retries:
                await asyncio.sleep(0.4 * (attempt + 1) + random.uniform(0, 0.2))
                continue
            breakers.record_failure(source, last_error[:200])
            return ToolResult.failure(
                source, f"{source} unreachable: {last_error}", status="unavailable"
            )

        if resp.status_code < 400:
            try:
                data = resp.json()
            except ValueError:
                breakers.record_failure(source, "non-JSON response")
                return ToolResult.failure(
                    source, f"{source} returned a non-JSON response"
                )
            breakers.record_success(source)
            if key and cache_ttl:
                await cache.set(key, data, cache_ttl)
            return ToolResult(
                source=source,
                data=data,
                latency_ms=(loop.time() - started) * 1000,
            )

        body = resp.text[:300]
        last_error = f"HTTP {resp.status_code}: {body}"

        # 4xx other than 429 is a request problem — retrying changes nothing, and
        # counting it against the breaker would sideline a healthy provider.
        if 400 <= resp.status_code < 500 and resp.status_code != 429:
            logger.warning("tool.client_error source=%s %s", source, last_error[:200])
            return ToolResult.failure(source, last_error)

        if attempt < retries:
            await asyncio.sleep(0.5 * (attempt + 1) + random.uniform(0, 0.3))
            continue

        breakers.record_failure(source, last_error[:200])
        logger.warning("tool.failed source=%s %s", source, last_error[:200])
        return ToolResult.failure(
            source,
            f"{source} error: {last_error}",
            status="unavailable" if resp.status_code >= 500 else "error",
        )

    return ToolResult.failure(source, last_error)


def secret(name: str) -> str | None:
    """Read a key off Settings by attribute name, or None if unset/blank."""
    value = getattr(get_settings(), name, None)
    if value is None:
        return None
    raw = value.get_secret_value() if hasattr(value, "get_secret_value") else str(value)
    raw = raw.strip()
    return raw or None
