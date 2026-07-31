"""The bounded tool-using orchestrator loop.

The orchestrator decides which semantic tools to call.  Tools themselves remain
deterministic and are dispatched by the registry; this module only coordinates the
conversation with the role-based model router.
"""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass, field
from typing import Any, Sequence

from app.llm.router import ModelRouter, get_router
from app.llm.structured import complete_json
from app.llm.types import LLMResponse, MediaPart, Message, ToolCall
from app.memory import service as memory
from app.storage import db
from app.tools.base import ToolResult
from app.tools.registry import dispatch, tool_specs_for_orchestrator

logger = logging.getLogger(__name__)

MAX_TOOL_ROUNDS = 4

_SYNTHESIS_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "message": {"type": "string"},
        "plan_items": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "kind": {"type": "string", "enum": ["flight", "train", "hotel", "restaurant", "activity", "transfer", "note"]},
                    "title": {"type": "string"},
                    "day": {"type": ["integer", "null"]},
                    "date": {"type": ["string", "null"]},
                    "start_time": {"type": ["string", "null"]},
                    "end_time": {"type": ["string", "null"]},
                    "location": {"type": ["string", "null"]},
                    "price_amount": {"type": ["number", "null"]},
                    "price_currency": {"type": ["string", "null"]},
                    "notes": {"type": ["string", "null"]},
                    "source": {"type": ["string", "null"]},
                },
                "required": ["kind", "title", "day", "date", "start_time", "end_time", "location", "price_amount", "price_currency", "notes", "source"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["message", "plan_items"],
    "additionalProperties": False,
}

_SYSTEM_PROMPT = """You are TripAI, a careful travel-planning assistant.

Use tools for live facts: flights, hotels, restaurants, weather, routes, attractions,
knowledge-base guidance, and current web information. Never invent schedules, prices,
opening hours, visa rules, or weather. If a tool is unavailable, say so plainly and
continue with what is still supported.

Ask a concise clarification question when a required detail is missing. Once enough
information is available, give the user a useful plan. Distinguish confirmed choices
from suggestions, cite URLs returned by web_search, and answer in the user's language
when it is clear from the conversation.

The current structured trip memory is included below. It may contain tentative values;
do not present tentative values as booked or confirmed.
"""


@dataclass
class AgentTurn:
    """Result returned to an API layer or CLI caller after one user turn."""

    text: str
    session_id: str
    state: Any
    tool_results: list[ToolResult] = field(default_factory=list)
    served_by: str | None = None
    attempts: list[dict[str, Any]] = field(default_factory=list)
    rounds: int = 0


def _history_messages(
    turns: Sequence[Any],
    *,
    latest_user_text: str,
    media: list[MediaPart],
) -> list[Message]:
    """Turn persisted text history into router messages.

    Media bytes are deliberately not persisted in SQLite.  They are attached only to
    the current user message, which is the only turn the model needs to inspect again.
    """
    messages: list[Message] = []
    for index, turn in enumerate(turns):
        is_current = index == len(turns) - 1
        if is_current and turn.role.value == "user" and turn.content == latest_user_text:
            messages.append(Message.user(turn.content, media=media))
        elif turn.role.value == "user":
            messages.append(Message.user(turn.content))
        else:
            messages.append(Message.assistant(turn.content))
    if not messages or messages[-1].role.value != "user":
        messages.append(Message.user(latest_user_text, media=media))
    return messages


def _tool_message(call: ToolCall, result: ToolResult) -> Message:
    # Keep tool payloads bounded. Hotel-rate responses in particular can be very large.
    body = json.dumps(result.as_dict(), ensure_ascii=False, default=str)
    return Message.tool_result(call.id, call.name, body[:30_000])


def _synthesis_messages(
    state: Any,
    user_text: str,
    tool_results: list[ToolResult],
) -> list[Message]:
    """Build a bounded, fetch-free prompt for the synthesis role."""
    raw_results = [result.as_dict() for result in tool_results]
    payload = {
        "user_request": user_text,
        "trip_state": state.compact() if hasattr(state, "compact") else state,
        "tool_results": raw_results,
    }
    return [
        Message.system(
            "You are TripAI's synthesis and ranking layer. The deterministic tools have "
            "already fetched the facts below. Do not call tools, invent missing values, "
            "or present unavailable trains as real. Rank useful options, resolve conflicts "
            "using source quality and the user's constraints, and write a clear final "
            "answer in the user's language. Return selected concrete items separately "
            "so the session memory can retain them."
        ),
        Message.user(json.dumps(payload, ensure_ascii=False, default=str)[:60_000]),
    ]


# Tool name -> the dashboard bucket its payload belongs in. Tools absent from this
# map (web_search, knowledge_lookup, maps_route) feed the model's reasoning but have
# no view of their own to render into.
_LIVE_BUCKETS: dict[str, str] = {
    "hotel_lookup": "hotels",
    "restaurant_lookup": "restaurants",
    "weather_lookup": "weather",
    "travel_search": "places",
}


def _bucket_for(call: ToolCall) -> str | None:
    if call.name == "transport_lookup":
        mode = (call.arguments or {}).get("mode")
        return "trains" if mode == "train" else "flights"
    return _LIVE_BUCKETS.get(call.name)


def _live_data(pairs: list[tuple[ToolCall, ToolResult]]) -> dict[str, Any]:
    """Latest successful payload per dashboard bucket.

    Without this the tool results reach synthesis and are then dropped, leaving the
    frontend nothing to render but its own fixtures — every trip looks identical.
    """
    live: dict[str, Any] = {}
    for call, result in pairs:
        bucket = _bucket_for(call)
        if bucket is None or not result.ok or not isinstance(result.data, dict):
            continue
        live[bucket] = {
            **result.data,
            "_source": result.source,
            "_query": call.arguments or {},
        }
    return live


def _place_key(state: Any) -> str | None:
    """Primary destination city, normalized for comparison across turns."""
    destination = getattr(state, "primary_destination", None)
    city = getattr(destination, "city", None)
    return city.strip().lower() if isinstance(city, str) and city.strip() else None


def _latest_route(tool_results: list[ToolResult]) -> dict[str, Any] | None:
    """Keep the latest successful MapLibre-ready route in session state."""
    for result in reversed(tool_results):
        if not result.ok or not isinstance(result.data, dict):
            continue
        geojson = result.data.get("geojson")
        if isinstance(geojson, dict) and geojson.get("type") == "FeatureCollection":
            return geojson
    return None


async def _dispatch_calls(calls: list[ToolCall]) -> list[ToolResult]:
    """Run independent tools concurrently while retaining model call order."""
    return await asyncio.gather(
        *(dispatch(call.name, call.arguments) for call in calls)
    )


async def run_turn(
    session_id: str,
    user_text: str,
    *,
    user_id: str | None = None,
    media: list[MediaPart] | None = None,
    router: ModelRouter | None = None,
    max_tool_rounds: int = MAX_TOOL_ROUNDS,
) -> AgentTurn:
    """Run one user turn through memory, orchestrator, and deterministic tools."""
    if not user_text.strip():
        raise ValueError("user_text must not be empty")
    if not await db.session_exists(session_id):
        raise ValueError(f"Unknown session {session_id!r}")

    media = media or []
    router = router or get_router()

    await db.add_turn(
        session_id,
        memory.turn_from_user(user_text, media_count=len(media)),
    )
    prior_place = _place_key(await db.get_trip_state(session_id))
    state = await memory.update_from_user_turn(
        session_id, user_text, router=router
    )

    # A new destination invalidates everything fetched for the old one. Without this
    # the dashboard keeps rendering the previous city's flights and hotels for any
    # domain the model doesn't happen to re-query this turn.
    place = _place_key(state)
    if prior_place and place and prior_place != place:
        logger.info(
            "agent.destination_changed session=%s %s -> %s",
            session_id,
            prior_place,
            place,
        )
        state = state.model_copy(update={"live_data": {}, "route": None})
        await db.save_trip_state(session_id, state)

    context = await memory.build_context(session_id, user_id=user_id)

    messages: list[Message] = [
        Message.system(f"{_SYSTEM_PROMPT}\n\nSession memory:\n{context.system_context()}")
    ]
    messages.extend(
        _history_messages(
            context.turns,
            latest_user_text=user_text,
            media=media,
        )
    )

    tool_specs = tool_specs_for_orchestrator()
    tool_results: list[ToolResult] = []
    call_results: list[tuple[ToolCall, ToolResult]] = []
    used_tools: list[str] = []
    response: LLMResponse | None = None

    for round_number in range(1, max(1, max_tool_rounds) + 1):
        response = await router.complete(
            "orchestrator",
            messages,
            tools=tool_specs,
            require_tools=True,
            require_vision=bool(media),
        )
        if not response.tool_calls:
            break

        messages.append(Message.assistant(response.text, response.tool_calls))
        used_tools.extend(call.name for call in response.tool_calls)
        results = await _dispatch_calls(response.tool_calls)
        tool_results.extend(results)
        call_results.extend(zip(response.tool_calls, results))
        messages.extend(
            _tool_message(call, result)
            for call, result in zip(response.tool_calls, results)
        )
    else:
        logger.warning(
            "agent.tool_round_limit session=%s rounds=%d", session_id, max_tool_rounds
        )

    if response is None:
        raise RuntimeError("orchestrator returned no response")
    text = response.text.strip()
    if not text:
        text = "I gathered the available information, but could not form a final answer."

    # Tool calls are deterministic facts; synthesis ranks and reconciles them before
    # the response is persisted. If the synthesis role is unavailable, preserve the
    # orchestrator answer rather than turning a provider outage into a failed turn.
    route = _latest_route(tool_results)
    if route is not None:
        state = state.merge({"route": route})

    if tool_results:
        try:
            synthesized = await complete_json(
                router,
                "synthesis",
                _synthesis_messages(state, user_text, tool_results),
                schema=_SYNTHESIS_SCHEMA,
                schema_name="tripai_synthesis",
                max_tokens=8192,
                default={"message": text, "plan_items": []},
            )
        except Exception:
            logger.exception("agent.synthesis_failed session=%s", session_id)
            synthesized = {"message": text, "plan_items": []}
        synthesized_text = synthesized.get("message")
        if isinstance(synthesized_text, str) and synthesized_text.strip():
            text = synthesized_text.strip()
        selected_items = synthesized.get("plan_items")
        state_update: dict[str, Any] = {}
        if isinstance(selected_items, list) and selected_items:
            state_update["plan_items"] = selected_items
        if route is not None:
            state_update["route"] = route
        live = _live_data(call_results)
        if live:
            state_update["live_data"] = live
        if state_update:
            state = state.merge(state_update)
            await db.save_trip_state(session_id, state)

    used_tools = list(dict.fromkeys(used_tools))
    await db.add_turn(
        session_id,
        memory.turn_from_assistant(
            text,
            tools_used=used_tools,
            served_by=response.served_by,
        ),
    )
    await memory.maybe_summarize(session_id, router=router)

    return AgentTurn(
        text=text,
        session_id=session_id,
        state=state,
        tool_results=tool_results,
        served_by=response.served_by,
        attempts=response.attempts,
        rounds=round_number,
    )
