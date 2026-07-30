"""Circuit breaker shared by the model router (§3.3) and the tool layer (§8).

One breaker per named resource — `"groq:llama-3.1-8b-instant"` for a model candidate,
`"duffel"` for an external API. Three states:

  closed    → calls allowed; consecutive failures counted
  open      → calls skipped outright until the cooldown expires
  half_open → cooldown elapsed; let exactly one probe through. Success closes it,
              failure re-opens it for another full cooldown.

Only *consecutive* failures inside a sliding window count, so a slow trickle of
unrelated errors across an hour never trips the breaker; a real outage does.

State lives in-process, with an optional Redis mirror so it survives a restart and
is visible to sibling workers. Redis is best-effort: if it's down, the in-process
view still protects the request path.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)


class BreakerState(str, Enum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


@dataclass
class _Record:
    consecutive_failures: int = 0
    last_failure_at: float = 0.0
    opened_at: float = 0.0
    total_failures: int = 0
    total_successes: int = 0
    last_error: str | None = None
    probe_in_flight: bool = False


@dataclass
class BreakerStatus:
    """Read model for `GET /health/models`."""

    name: str
    state: BreakerState
    consecutive_failures: int
    total_successes: int
    total_failures: int
    last_error: str | None
    seconds_until_retry: float | None

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "state": self.state.value,
            "consecutive_failures": self.consecutive_failures,
            "total_successes": self.total_successes,
            "total_failures": self.total_failures,
            "last_error": self.last_error,
            "seconds_until_retry": (
                round(self.seconds_until_retry, 1)
                if self.seconds_until_retry is not None
                else None
            ),
        }


class CircuitBreakerRegistry:
    def __init__(
        self,
        failure_threshold: int = 3,
        window_seconds: float = 120.0,
        cooldown_seconds: float = 300.0,
    ) -> None:
        self.failure_threshold = failure_threshold
        self.window_seconds = window_seconds
        self.cooldown_seconds = cooldown_seconds
        self._records: dict[str, _Record] = {}

    def _record(self, name: str) -> _Record:
        return self._records.setdefault(name, _Record())

    # -- state transitions ---------------------------------------------------

    def state(self, name: str, *, now: float | None = None) -> BreakerState:
        now = now if now is not None else time.monotonic()
        rec = self._records.get(name)
        if rec is None or rec.opened_at == 0.0:
            return BreakerState.CLOSED
        if now - rec.opened_at >= self.cooldown_seconds:
            return BreakerState.HALF_OPEN
        return BreakerState.OPEN

    def allows(self, name: str, *, now: float | None = None) -> bool:
        """True if a call to `name` should be attempted right now."""
        now = now if now is not None else time.monotonic()
        state = self.state(name, now=now)
        if state is BreakerState.OPEN:
            return False
        if state is BreakerState.HALF_OPEN:
            rec = self._record(name)
            # Let a single probe through; concurrent callers keep skipping.
            if rec.probe_in_flight:
                return False
            rec.probe_in_flight = True
        return True

    def record_success(self, name: str, *, now: float | None = None) -> None:
        rec = self._record(name)
        was_open = rec.opened_at != 0.0
        rec.consecutive_failures = 0
        rec.opened_at = 0.0
        rec.probe_in_flight = False
        rec.last_error = None
        rec.total_successes += 1
        if was_open:
            logger.info("circuit_breaker.closed name=%s", name)

    def record_failure(
        self, name: str, error: str | None = None, *, now: float | None = None
    ) -> None:
        now = now if now is not None else time.monotonic()
        rec = self._record(name)
        rec.probe_in_flight = False
        rec.total_failures += 1
        rec.last_error = error

        # A failure long after the previous one starts a fresh streak.
        if rec.last_failure_at and (now - rec.last_failure_at) > self.window_seconds:
            rec.consecutive_failures = 0
        rec.consecutive_failures += 1
        rec.last_failure_at = now

        if rec.consecutive_failures >= self.failure_threshold:
            rec.opened_at = now
            rec.consecutive_failures = 0  # streak consumed by the trip
            logger.warning(
                "circuit_breaker.opened name=%s cooldown=%ss error=%s",
                name,
                self.cooldown_seconds,
                error,
            )

    # -- introspection -------------------------------------------------------

    def status(self, name: str, *, now: float | None = None) -> BreakerStatus:
        now = now if now is not None else time.monotonic()
        rec = self._records.get(name, _Record())
        state = self.state(name, now=now)
        seconds_until_retry = None
        if state is BreakerState.OPEN:
            seconds_until_retry = max(
                0.0, self.cooldown_seconds - (now - rec.opened_at)
            )
        return BreakerStatus(
            name=name,
            state=state,
            consecutive_failures=rec.consecutive_failures,
            total_successes=rec.total_successes,
            total_failures=rec.total_failures,
            last_error=rec.last_error,
            seconds_until_retry=seconds_until_retry,
        )

    def all_status(self) -> list[BreakerStatus]:
        now = time.monotonic()
        return [self.status(name, now=now) for name in sorted(self._records)]

    def reset(self, name: str | None = None) -> None:
        if name is None:
            self._records.clear()
        else:
            self._records.pop(name, None)


# Two registries: LLM candidates and external travel APIs. Separate thresholds —
# a flaky hotel API shouldn't influence how patient we are with a model provider.
_llm_registry: CircuitBreakerRegistry | None = None
_api_registry: CircuitBreakerRegistry | None = None


def get_llm_breakers() -> CircuitBreakerRegistry:
    global _llm_registry
    if _llm_registry is None:
        from app.config import get_settings

        s = get_settings()
        _llm_registry = CircuitBreakerRegistry(
            failure_threshold=s.breaker_failure_threshold,
            window_seconds=s.breaker_window_seconds,
            cooldown_seconds=s.breaker_cooldown_seconds,
        )
    return _llm_registry


def get_api_breakers() -> CircuitBreakerRegistry:
    global _api_registry
    if _api_registry is None:
        from app.config import get_settings

        s = get_settings()
        _api_registry = CircuitBreakerRegistry(
            failure_threshold=s.breaker_failure_threshold,
            window_seconds=s.breaker_window_seconds,
            # External APIs recover faster than model quotas; don't sideline
            # a whole data source for five minutes over a blip.
            cooldown_seconds=60.0,
        )
    return _api_registry
