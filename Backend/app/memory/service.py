"""Session-memory orchestration.

This module is the boundary between persistence and the LLM roles.  The rest of the
application should not need to know how a rolling trip state is extracted or how much
conversation can fit in an orchestrator prompt.

Memory is intentionally best-effort: a failed memory call must not turn a usable user
turn into a 500.  The raw turn is still persisted and the previous structured state is
kept intact.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any

from app.config import get_settings
from app.llm.router import ModelRouter, get_router
from app.llm.structured import complete_json
from app.llm.types import Message
from app.memory.models import ConversationTurn, TripState, TurnRole
from app.storage import db

logger = logging.getLogger(__name__)


# The model returns a partial object.  Every property is optional because omission
# means "unchanged" and explicit null is also ignored by TripState.merge().
MEMORY_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "origin": {"type": ["string", "null"]},
        "destinations": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "city": {"type": "string"},
                    "country": {"type": ["string", "null"]},
                    "country_code": {"type": ["string", "null"]},
                    "arrival_date": {"type": ["string", "null"]},
                    "departure_date": {"type": ["string", "null"]},
                    "nights": {"type": ["integer", "null"]},
                },
                "required": ["city"],
                "additionalProperties": False,
            },
        },
        "start_date": {"type": ["string", "null"]},
        "end_date": {"type": ["string", "null"]},
        "duration_nights": {"type": ["integer", "null"]},
        "party_size": {"type": ["integer", "null"]},
        "party_composition": {"type": ["string", "null"]},
        "budget_total": {"type": ["number", "null"]},
        "budget_currency": {"type": ["string", "null"]},
        "budget_level": {"type": ["string", "null"]},
        "preferences": {
            "type": "object",
            "properties": {
                "pace": {"type": ["string", "null"]},
                "interests": {"type": "array", "items": {"type": "string"}},
                "dietary": {"type": "array", "items": {"type": "string"}},
                "accessibility": {"type": "array", "items": {"type": "string"}},
                "accommodation_style": {"type": ["string", "null"]},
                "avoid": {"type": "array", "items": {"type": "string"}},
                "language": {"type": ["string", "null"]},
            },
            "additionalProperties": False,
        },
        "plan_items": {
            "type": "array",
            "items": {"type": "object"},
        },
        "open_questions": {"type": "array", "items": {"type": "string"}},
        "summary": {"type": ["string", "null"]},
    },
    "additionalProperties": False,
}


@dataclass
class MemoryContext:
    """The persisted state and prompt-ready recent history for one session."""

    state: TripState
    turns: list[ConversationTurn]
    prior_sessions: list[dict[str, Any]]

    def system_context(self) -> str:
        """Serialize only bounded, non-secret context for the orchestrator."""
        payload: dict[str, Any] = {"trip_state": self.state.compact()}
        if self.prior_sessions:
            payload["prior_sessions"] = [
                {
                    k: v
                    for k, v in item.items()
                    if k in {"id", "title", "created_at", "updated_at", "summary"}
                    and v is not None
                }
                for item in self.prior_sessions
            ]
        return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def _memory_prompt(state: TripState, recent_turns: list[ConversationTurn], user_text: str) -> str:
    history = "\n".join(
        f"{turn.role.value}: {turn.content}" for turn in recent_turns[-6:]
    )
    return (
        "Extract only facts explicitly stated or clearly corrected by the user. "
        "Return a partial TripState JSON object. Do not guess dates, prices, locations, "
        "party details, or preferences. Omit unchanged fields. Keep destinations and "
        "plan_items concise. If the user contradicts an earlier fact, return the new "
        "value.\n\n"
        f"Current state:\n{json.dumps(state.compact(), ensure_ascii=False)}\n\n"
        f"Recent conversation:\n{history or '(none)'}\n\n"
        f"Latest user message:\n{user_text}"
    )


async def extract_update(
    state: TripState,
    recent_turns: list[ConversationTurn],
    user_text: str,
    *,
    router: ModelRouter | None = None,
) -> dict[str, Any]:
    """Ask the cheap memory role for a partial update; return ``{}`` on failure."""
    if not user_text.strip():
        return {}
    router = router or get_router()
    try:
        return await complete_json(
            router,
            "memory",
            [Message.system(_memory_prompt(state, recent_turns, user_text))],
            schema=MEMORY_SCHEMA,
            schema_name="trip_state_update",
            temperature=0.0,
            max_tokens=2048,
            default={},
        )
    except Exception:
        logger.exception("memory.extract_failed")
        return {}


async def update_from_user_turn(
    session_id: str,
    user_text: str,
    *,
    router: ModelRouter | None = None,
) -> TripState:
    """Extract and persist a state update after a user message is stored."""
    state = await db.get_trip_state(session_id)
    if state is None:
        raise ValueError(f"Unknown session {session_id!r}")
    recent = await db.get_turns(
        session_id, limit=get_settings().raw_turns_in_context
    )
    partial = await extract_update(state, recent, user_text, router=router)
    try:
        merged = state.merge(partial)
    except Exception:
        # A provider can return a syntactically valid but semantically invalid object.
        # Preserve the last known-good state and let the next turn try again.
        logger.exception("memory.merge_failed session=%s", session_id)
        merged = state
    await db.save_trip_state(session_id, merged)
    return merged


async def build_context(
    session_id: str,
    *,
    user_id: str | None = None,
    router: ModelRouter | None = None,
) -> MemoryContext:
    """Load bounded context for an orchestrator turn.

    ``user_id`` is optional because anonymous sessions are valid.  For a returning
    identified user, prior sessions provide continuity without injecting their full
    transcripts into the prompt.
    """
    state = await db.get_trip_state(session_id)
    if state is None:
        raise ValueError(f"Unknown session {session_id!r}")
    settings = get_settings()
    turns = await db.get_turns(session_id, limit=settings.raw_turns_in_context)
    prior = []
    if user_id:
        prior = [
            item
            for item in await db.get_user_sessions(user_id, limit=5)
            if item.get("id") != session_id
        ]
    return MemoryContext(state=state, turns=turns, prior_sessions=prior)


async def maybe_summarize(
    session_id: str,
    *,
    router: ModelRouter | None = None,
) -> TripState | None:
    """Refresh the rolling summary once a session exceeds the configured threshold."""
    count = await db.turn_count(session_id)
    settings = get_settings()
    if count < settings.summarize_after_turns:
        return await db.get_trip_state(session_id)

    state = await db.get_trip_state(session_id)
    if state is None:
        return None
    # Keep the prompt bounded even if a caller has a very large configured threshold.
    turns = await db.get_turns(session_id, limit=min(count, 20))
    prompt = (
        "Summarize the conversation for a travel-planning assistant in 5 short bullets. "
        "Keep only confirmed constraints, user preferences, decisions, unresolved "
        "questions, and important tool-backed facts. Do not invent anything.\n\n"
        f"Existing trip state:\n{json.dumps(state.compact(), ensure_ascii=False)}\n\n"
        "Conversation:\n"
        + "\n".join(f"{t.role.value}: {t.content}" for t in turns)
    )
    router = router or get_router()
    try:
        response = await router.complete(
            "memory",
            [Message.system(prompt)],
            temperature=0.0,
            max_tokens=600,
        )
    except Exception:
        logger.exception("memory.summary_failed session=%s", session_id)
        return state
    summary = response.text.strip()
    if not summary:
        return state
    state.summary = summary[:4000]
    await db.save_trip_state(session_id, state)
    return state


def turn_from_user(text: str, *, media_count: int = 0) -> ConversationTurn:
    return ConversationTurn(
        role=TurnRole.USER,
        content=text,
        media_count=max(0, media_count),
    )


def turn_from_assistant(
    text: str,
    *,
    tools_used: list[str] | None = None,
    served_by: str | None = None,
) -> ConversationTurn:
    return ConversationTurn(
        role=TurnRole.ASSISTANT,
        content=text,
        tools_used=tools_used or [],
        served_by=served_by,
    )
