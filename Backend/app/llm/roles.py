"""Role → model candidate mapping (§3).

Business logic asks for a *role* ("orchestrator", "synthesis", ...). It never names
a model. Swapping a model — free tier to paid, or one vendor to another — is an edit
to this file and nothing else.

Two layers:
  PROVIDERS   — how to talk to a vendor (base URL, auth env, API dialect)
  MODEL_ROLES — ordered fallback candidates per role, lowest `priority` tried first

Every model id and provider tag below was verified live against the provider APIs on
2026-07-25 (see Projectmemeory.md → "Verified provider facts"). Notes on the spec's
original draft config:
  * `google/gemma-4-26b-a4b:free` does not exist; the real id has an `-it` suffix:
    `google/gemma-4-26b-a4b-it:free`.
  * `google-ai-studio` and `darkbloom` are OpenRouter *upstream* tags, not separate
    vendors. They are pinned via `provider.order`, not by changing base URL.
  * `nvidia/nemotron-3-super` resolves to `nvidia/nemotron-3-super-120b-a12b` on NIM.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class Dialect(str, Enum):
    """Wire format, not vendor. Every provider we use speaks OpenAI chat-completions."""

    OPENAI = "openai"
    GOOGLE = "google"  # generativelanguage.googleapis.com native REST


@dataclass(frozen=True)
class ProviderSpec:
    name: str
    base_url: str
    api_key_setting: str       # attribute name on Settings, never the raw value
    dialect: Dialect = Dialect.OPENAI
    # OpenRouter can pin which upstream actually serves a request.
    supports_upstream_routing: bool = False
    extra_headers: dict[str, str] = field(default_factory=dict)


PROVIDERS: dict[str, ProviderSpec] = {
    "openrouter": ProviderSpec(
        name="openrouter",
        base_url="https://openrouter.ai/api/v1",
        api_key_setting="open_router_api_key",
        supports_upstream_routing=True,
        extra_headers={
            "HTTP-Referer": "https://github.com/local/tripai",
            "X-Title": "TripAI Backend",
        },
    ),
    "groq": ProviderSpec(
        name="groq",
        base_url="https://api.groq.com/openai/v1",
        api_key_setting="groq_api_key",
    ),
    "nvidia-nim": ProviderSpec(
        name="nvidia-nim",
        base_url="https://integrate.api.nvidia.com/v1",
        api_key_setting="nvidia_nim_api_key",
    ),
    # Only reachable if a Google AI Studio key is added to .env. Not currently
    # provisioned — Gemma is served through OpenRouter's google-ai-studio upstream
    # instead, which needs no extra key. Kept so adding one is a config change.
    "google-ai-studio": ProviderSpec(
        name="google-ai-studio",
        base_url="https://generativelanguage.googleapis.com/v1beta/openai",
        api_key_setting="google_ai_studio_key",
    ),
}

GOOGLE_NATIVE_BASE = "https://generativelanguage.googleapis.com/v1beta"


@dataclass(frozen=True)
class ModelCandidate:
    model: str
    provider: str
    priority: int = 1
    # OpenRouter-only: pin the upstream that serves this model, so we know which
    # quota pool we're drawing from rather than silently drifting between them.
    upstream: str | None = None
    supports_vision: bool = False
    supports_video: bool = False
    supports_tools: bool = True
    # True only where the provider enforces a real JSON *schema*. Where False we
    # fall back to json_object mode + a schema description in the prompt.
    supports_json_schema: bool = True
    supports_json_object: bool = True
    max_output_tokens: int = 4096

    @property
    def key(self) -> str:
        """Circuit-breaker identity: one breaker per (model, provider) pair."""
        tag = f"@{self.upstream}" if self.upstream else ""
        return f"{self.provider}:{self.model}{tag}"


# ---------------------------------------------------------------------------
# Roles. Order within a list is the failover order.
# ---------------------------------------------------------------------------
MODEL_ROLES: dict[str, list[ModelCandidate]] = {
    # Reads the user's natural language + images/video, plans itinerary structure,
    # decides which tools to call. Needs vision + tool calling.
    #
    # p1 is Gemma via the *direct* Google AI Studio key — the same model as p2 but on
    # its own quota, so it isn't competing with all of OpenRouter's free tier. The
    # OpenRouter routes remain as p2/p3: the `:free` tier of gemma-4-31b returned
    # persistent upstream 429s during verification, so those failovers are
    # load-bearing, not decorative. All were verified to emit correct tool_calls.
    "orchestrator": [
        ModelCandidate(
            model="gemma-4-31b-it",
            provider="google-ai-studio",
            priority=1,
            supports_vision=True,
            supports_video=True,
            supports_json_schema=False,
            max_output_tokens=8192,
        ),
        ModelCandidate(
            model="google/gemma-4-31b-it:free",
            provider="openrouter",
            priority=2,
            upstream="google-ai-studio",
            supports_vision=True,
            supports_video=True,
            supports_json_schema=False,  # response_format yes, strict schema no
            max_output_tokens=8192,
        ),
        ModelCandidate(
            model="google/gemma-4-26b-a4b-it:free",
            provider="openrouter",
            priority=3,
            upstream="darkbloom",
            supports_vision=True,
            supports_video=True,
            supports_json_schema=True,  # advertises structured_outputs
            max_output_tokens=8192,
        ),
        # Text-only last resort: keeps a degraded conversation alive when every
        # multimodal route is down. Media is dropped with a warning, not silently.
        ModelCandidate(
            model="meta-llama/llama-4-scout-17b-16e-instruct",
            provider="groq",
            priority=4,
            supports_vision=True,
            max_output_tokens=8192,
        ),
    ],
    # Ranks/selects/resolves conflicts over already-fetched tool results.
    # Reasoning job — no tool calling needed, but must honour a JSON schema.
    "synthesis": [
        ModelCandidate(
            model="nvidia/nemotron-3-super-120b-a12b",
            provider="nvidia-nim",
            priority=1,
            supports_tools=False,
            supports_json_schema=True,  # verified live
            max_output_tokens=8192,
        ),
        ModelCandidate(
            model="nvidia/nemotron-3-ultra-550b-a55b:free",
            provider="openrouter",
            priority=2,
            supports_tools=False,
            # This id advertises neither response_format nor structured_outputs.
            supports_json_schema=False,
            supports_json_object=False,
            max_output_tokens=8192,
        ),
        ModelCandidate(
            model="llama-3.3-70b-versatile",
            provider="groq",
            priority=3,
            supports_tools=False,
            supports_json_schema=False,
            max_output_tokens=8192,
        ),
    ],
    # Fires every turn → must be cheap and fast, not deep.
    # Groq's 8b-instant rejects json_schema but honours json_object (verified).
    "memory": [
        ModelCandidate(
            model="llama-3.1-8b-instant",
            provider="groq",
            priority=1,
            supports_tools=False,
            supports_json_schema=False,
            max_output_tokens=2048,
        ),
        ModelCandidate(
            model="meta-llama/llama-3.1-8b-instruct",
            provider="openrouter",
            priority=2,
            supports_tools=False,
            supports_json_schema=True,
            max_output_tokens=2048,
        ),
    ],
    # Free-text → typed fields. Same cheap/fast profile as memory.
    "field_extractor": [
        ModelCandidate(
            model="llama-3.1-8b-instant",
            provider="groq",
            priority=1,
            supports_tools=False,
            supports_json_schema=False,
            max_output_tokens=2048,
        ),
        ModelCandidate(
            model="meta-llama/llama-3.1-8b-instruct",
            provider="openrouter",
            priority=2,
            supports_tools=False,
            supports_json_schema=True,
            max_output_tokens=2048,
        ),
    ],
}


def get_candidates(role: str) -> list[ModelCandidate]:
    """Ordered fallback candidates for a role. Raises on unknown role."""
    try:
        candidates = MODEL_ROLES[role]
    except KeyError:
        raise ValueError(
            f"Unknown model role {role!r}. Known roles: {sorted(MODEL_ROLES)}"
        ) from None
    return sorted(candidates, key=lambda c: c.priority)


def get_provider(name: str) -> ProviderSpec:
    try:
        return PROVIDERS[name]
    except KeyError:
        raise ValueError(
            f"Unknown provider {name!r}. Known providers: {sorted(PROVIDERS)}"
        ) from None


def all_roles() -> list[str]:
    return sorted(MODEL_ROLES)
