"""Structured-output helper.

Native JSON mode (§8) is used wherever the provider offers it, but coverage is uneven
across the candidate pool: Groq's 8b-instant rejects `json_schema`, and
nemotron-3-ultra:free advertises no `response_format` at all. When the router fails
over to one of those, the response may arrive as prose-wrapped JSON.

`complete_json` handles both cases: it asks for the strongest native mode the
candidate supports, then parses defensively — a fenced code block or a JSON object
embedded in prose still yields a dict rather than an exception.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from app.llm.router import ModelRouter
from app.llm.types import Message

logger = logging.getLogger(__name__)

_FENCE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL)


def extract_json(text: str) -> dict[str, Any] | None:
    """Best-effort JSON object out of a model response."""
    if not text:
        return None

    candidates: list[str] = []
    stripped = text.strip()
    candidates.append(stripped)

    for match in _FENCE.finditer(text):
        candidates.append(match.group(1).strip())

    # Widest brace span — handles "Here is the plan: {...} Hope that helps!"
    start, end = stripped.find("{"), stripped.rfind("}")
    if start != -1 and end > start:
        candidates.append(stripped[start : end + 1])

    for candidate in candidates:
        try:
            parsed = json.loads(candidate)
        except (json.JSONDecodeError, ValueError):
            continue
        if isinstance(parsed, dict):
            return parsed
        if isinstance(parsed, list):
            return {"items": parsed}
    return None


def _schema_hint(schema: dict[str, Any]) -> str:
    return (
        "Respond with a single JSON object matching this JSON Schema exactly. "
        "No prose, no markdown fences, no explanation before or after.\n\n"
        f"{json.dumps(schema, indent=2)}"
    )


async def complete_json(
    router: ModelRouter,
    role: str,
    messages: list[Message],
    *,
    schema: dict[str, Any],
    schema_name: str = "response",
    temperature: float = 0.2,
    max_tokens: int | None = None,
    default: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Run a role and return parsed JSON.

    The schema is *also* appended to the system prompt. That's belt-and-braces on
    purpose: the native mode does the real work where available, and the prompt hint
    carries the weaker candidates that lack schema enforcement.

    If `default` is provided, an unparseable response returns it instead of raising —
    for non-critical paths (memory summarization) that shouldn't fail a user turn.
    """
    hinted = list(messages)
    hint = _schema_hint(schema)
    if hinted and hinted[0].role.value == "system":
        hinted[0] = Message.system(f"{hinted[0].content}\n\n{hint}")
    else:
        hinted.insert(0, Message.system(hint))

    resp = await router.complete(
        role,
        hinted,
        json_schema=schema,
        schema_name=schema_name,
        temperature=temperature,
        max_tokens=max_tokens,
    )

    parsed = extract_json(resp.text)
    if parsed is not None:
        return parsed

    logger.warning(
        "json.parse_failed role=%s served_by=%s text=%r",
        role,
        resp.served_by,
        resp.text[:300],
    )
    if default is not None:
        return default
    raise ValueError(
        f"Role {role!r} (served by {resp.served_by}) returned unparseable JSON: "
        f"{resp.text[:200]!r}"
    )
