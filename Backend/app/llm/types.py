"""Provider-agnostic chat types.

The router speaks these; adapters translate to each vendor's wire format. Business
logic never constructs a vendor-specific payload.
"""

from __future__ import annotations

import base64
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Literal


class Role(str, Enum):
    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"


@dataclass
class MediaPart:
    """An image or short video attached to a user message."""

    mime_type: str
    data: bytes

    @property
    def is_video(self) -> bool:
        return self.mime_type.startswith("video/")

    def to_base64(self) -> str:
        return base64.b64encode(self.data).decode("ascii")

    def to_data_url(self) -> str:
        return f"data:{self.mime_type};base64,{self.to_base64()}"


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict[str, Any]


@dataclass
class Message:
    role: Role
    content: str = ""
    media: list[MediaPart] = field(default_factory=list)
    # assistant turns that requested tools
    tool_calls: list[ToolCall] = field(default_factory=list)
    # tool-result turns
    tool_call_id: str | None = None
    name: str | None = None

    @classmethod
    def system(cls, content: str) -> "Message":
        return cls(role=Role.SYSTEM, content=content)

    @classmethod
    def user(cls, content: str, media: list[MediaPart] | None = None) -> "Message":
        return cls(role=Role.USER, content=content, media=media or [])

    @classmethod
    def assistant(
        cls, content: str = "", tool_calls: list[ToolCall] | None = None
    ) -> "Message":
        return cls(role=Role.ASSISTANT, content=content, tool_calls=tool_calls or [])

    @classmethod
    def tool_result(cls, tool_call_id: str, name: str, content: str) -> "Message":
        return cls(
            role=Role.TOOL, content=content, tool_call_id=tool_call_id, name=name
        )


@dataclass
class ToolSpec:
    """A tool contract exposed to an LLM. `parameters` is a real JSON Schema (§4.2)."""

    name: str
    description: str
    parameters: dict[str, Any]


@dataclass
class LLMResponse:
    text: str
    tool_calls: list[ToolCall] = field(default_factory=list)
    # Which candidate actually served this — the observability requirement in §3.3.
    model: str = ""
    provider: str = ""
    finish_reason: str = ""
    prompt_tokens: int = 0
    completion_tokens: int = 0
    latency_ms: float = 0.0
    attempts: list[dict[str, Any]] = field(default_factory=list)

    @property
    def served_by(self) -> str:
        return f"{self.provider}:{self.model}"


ResponseFormat = Literal["text", "json_object", "json_schema"]


# --- error taxonomy: decides retry vs. failover vs. give up --------------------


class LLMError(RuntimeError):
    """Base for router failures."""

    retryable = False

    def __init__(self, message: str, *, candidate: str = "", status: int | None = None):
        super().__init__(message)
        self.candidate = candidate
        self.status = status


class RateLimited(LLMError):
    """429. Fail over immediately — waiting out a quota is worse than switching."""

    retryable = True


class ProviderUnavailable(LLMError):
    """5xx, connection error, or timeout. Fail over (§3.3: not just rate limits)."""

    retryable = True


class RequestInvalid(LLMError):
    """4xx that isn't 429 — bad payload or auth. Failover won't help this candidate,
    but a *different* candidate may still work (e.g. missing key for one provider)."""

    retryable = False


class AllCandidatesFailed(LLMError):
    def __init__(self, role: str, attempts: list[dict[str, Any]]):
        detail = "; ".join(
            f"{a.get('candidate')}: {a.get('error')}" for a in attempts
        ) or "no candidates available"
        super().__init__(f"All candidates failed for role {role!r}: {detail}")
        self.role = role
        self.attempts = attempts
