"""The model router (§3.3).

Single entry point for every LLM call in the system:

    router = get_router()
    resp = await router.complete("orchestrator", messages, tools=TOOLS)

Callers name a *role*. The router walks that role's candidates in priority order,
skipping any whose circuit breaker is open, and returns the first success. It records
which candidate served the request (`resp.served_by`) and the full attempt trail
(`resp.attempts`) so quota pressure is visible before it becomes an outage.

Failover triggers on 429, 5xx, timeout, and transport errors — not just rate limits.
A candidate with no configured API key is skipped rather than attempted, so a partly
provisioned .env degrades to fewer candidates instead of failing every call.
"""

from __future__ import annotations

import logging
import time
from typing import Any

import httpx

from app.config import Settings, get_settings
from app.llm.adapters import get_adapter
from app.llm.breaker import BreakerState, CircuitBreakerRegistry, get_llm_breakers
from app.llm.roles import (
    ModelCandidate,
    all_roles,
    get_candidates,
    get_provider,
)
from app.llm.types import (
    AllCandidatesFailed,
    LLMError,
    LLMResponse,
    Message,
    RequestInvalid,
    ToolSpec,
)

logger = logging.getLogger(__name__)


class ModelRouter:
    def __init__(
        self,
        settings: Settings,
        breakers: CircuitBreakerRegistry,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._settings = settings
        self._breakers = breakers
        self._client = client
        self._owns_client = client is None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                timeout=self._settings.llm_timeout_seconds,
                limits=httpx.Limits(max_connections=32, max_keepalive_connections=16),
            )
        return self._client

    async def aclose(self) -> None:
        if self._client is not None and self._owns_client:
            await self._client.aclose()
            self._client = None

    def _api_key(self, candidate: ModelCandidate) -> str | None:
        provider = get_provider(candidate.provider)
        secret = getattr(self._settings, provider.api_key_setting, None)
        if secret is None:
            return None
        value = secret.get_secret_value() if hasattr(secret, "get_secret_value") else str(secret)
        return value or None

    def available_candidates(self, role: str) -> list[ModelCandidate]:
        """Candidates for a role that have a key configured — key presence only,
        breaker state excluded, so this is stable enough for health reporting."""
        return [c for c in get_candidates(role) if self._api_key(c)]

    async def complete(
        self,
        role: str,
        messages: list[Message],
        *,
        tools: list[ToolSpec] | None = None,
        json_schema: dict[str, Any] | None = None,
        schema_name: str = "response",
        temperature: float = 0.3,
        max_tokens: int | None = None,
        require_vision: bool = False,
        require_tools: bool = False,
    ) -> LLMResponse:
        """Run `role` against its candidates until one succeeds.

        `require_vision` / `require_tools` narrow the candidate set when the call
        genuinely needs that capability — a text-only fallback is worse than useless
        for reading an uploaded photo, so it's skipped rather than given a chance to
        confabulate.
        """
        candidates = get_candidates(role)
        if require_vision:
            candidates = [c for c in candidates if c.supports_vision]
        if require_tools:
            candidates = [c for c in candidates if c.supports_tools]

        client = await self._get_client()
        attempts: list[dict[str, Any]] = []
        started = time.perf_counter()

        for candidate in candidates:
            api_key = self._api_key(candidate)
            if not api_key:
                attempts.append(
                    {
                        "candidate": candidate.key,
                        "skipped": "no_api_key",
                        "error": "no API key configured",
                    }
                )
                continue

            if not self._breakers.allows(candidate.key):
                status = self._breakers.status(candidate.key)
                attempts.append(
                    {
                        "candidate": candidate.key,
                        "skipped": "circuit_open",
                        "error": f"circuit open, retry in "
                        f"{status.seconds_until_retry:.0f}s",
                    }
                )
                logger.info(
                    "router.skip_open role=%s candidate=%s", role, candidate.key
                )
                continue

            provider = get_provider(candidate.provider)
            adapter = get_adapter(provider.dialect)
            attempt_started = time.perf_counter()

            try:
                resp = await adapter.complete(
                    client,
                    provider=provider,
                    candidate=candidate,
                    api_key=api_key,
                    messages=messages,
                    tools=tools,
                    json_schema=json_schema,
                    schema_name=schema_name,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    timeout=self._settings.llm_timeout_seconds,
                )
            except LLMError as exc:
                elapsed = (time.perf_counter() - attempt_started) * 1000
                self._breakers.record_failure(candidate.key, str(exc)[:200])
                attempts.append(
                    {
                        "candidate": candidate.key,
                        "error": str(exc)[:300],
                        "status": exc.status,
                        "latency_ms": round(elapsed, 1),
                    }
                )
                logger.warning(
                    "router.candidate_failed role=%s candidate=%s status=%s error=%s",
                    role,
                    candidate.key,
                    exc.status,
                    str(exc)[:200],
                )
                continue
            except Exception as exc:  # unexpected — still fail over, but noisily
                elapsed = (time.perf_counter() - attempt_started) * 1000
                self._breakers.record_failure(candidate.key, repr(exc)[:200])
                attempts.append(
                    {
                        "candidate": candidate.key,
                        "error": f"unexpected: {exc!r}"[:300],
                        "latency_ms": round(elapsed, 1),
                    }
                )
                logger.exception(
                    "router.candidate_error role=%s candidate=%s", role, candidate.key
                )
                continue

            self._breakers.record_success(candidate.key)
            resp.latency_ms = (time.perf_counter() - started) * 1000
            resp.attempts = attempts
            # §3.3: log which candidate actually served the request.
            logger.info(
                "router.served role=%s candidate=%s failovers=%d latency_ms=%.0f "
                "tokens_in=%d tokens_out=%d",
                role,
                candidate.key,
                len(attempts),
                resp.latency_ms,
                resp.prompt_tokens,
                resp.completion_tokens,
            )
            return resp

        logger.error(
            "router.exhausted role=%s attempts=%s",
            role,
            [a.get("candidate") for a in attempts],
        )
        raise AllCandidatesFailed(role, attempts)

    # -- observability (§9 /health/models) ----------------------------------

    def health(self) -> dict[str, Any]:
        """Per-role view of which candidate would serve the next request."""
        roles: dict[str, Any] = {}
        for role in all_roles():
            entries = []
            serving: str | None = None
            for candidate in get_candidates(role):
                has_key = bool(self._api_key(candidate))
                status = self._breakers.status(candidate.key)
                usable = has_key and status.state is not BreakerState.OPEN
                if usable and serving is None:
                    serving = candidate.key
                entry = status.as_dict()
                entry.update(
                    {
                        "model": candidate.model,
                        "provider": candidate.provider,
                        "upstream": candidate.upstream,
                        "priority": candidate.priority,
                        "api_key_configured": has_key,
                        "usable": usable,
                    }
                )
                entries.append(entry)
            roles[role] = {
                "currently_serving": serving,
                "degraded": serving is not None
                and serving != get_candidates(role)[0].key,
                "available": serving is not None,
                "candidates": entries,
            }
        return roles


_router: ModelRouter | None = None


def get_router() -> ModelRouter:
    global _router
    if _router is None:
        _router = ModelRouter(get_settings(), get_llm_breakers())
    return _router


async def close_router() -> None:
    global _router
    if _router is not None:
        await _router.aclose()
        _router = None
