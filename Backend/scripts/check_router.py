"""Exercise the router against live providers.

Run: PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe scripts/check_router.py
Prints which candidate served each role and the failover trail. No key material.
"""
from __future__ import annotations

import asyncio
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

logging.basicConfig(
    level=logging.INFO, format="%(levelname)-7s %(name)s | %(message)s"
)

from app.llm.breaker import CircuitBreakerRegistry  # noqa: E402
from app.llm.router import get_router  # noqa: E402
from app.llm.structured import complete_json  # noqa: E402
from app.llm.types import AllCandidatesFailed, Message, ToolSpec  # noqa: E402

FLIGHT_TOOL = ToolSpec(
    name="flight_lookup",
    description="Search flights between two locations on given dates",
    parameters={
        "type": "object",
        "properties": {
            "origin": {"type": "string", "description": "IATA airport/city code"},
            "destination": {"type": "string", "description": "IATA airport/city code"},
            "departure_date": {"type": "string", "format": "date"},
            "passengers": {"type": "integer", "default": 1},
        },
        "required": ["origin", "destination", "departure_date"],
    },
)

TRIP_SCHEMA = {
    "type": "object",
    "properties": {
        "destination": {"type": "string"},
        "nights": {"type": "integer"},
        "budget_usd": {"type": "integer"},
        "party_size": {"type": "integer"},
    },
    "required": ["destination", "nights"],
    "additionalProperties": False,
}


def show(label: str, resp) -> None:
    print(f"\n--- {label} ---")
    print(f"  served_by   : {resp.served_by}")
    print(f"  latency_ms  : {resp.latency_ms:.0f}")
    print(f"  tokens      : in={resp.prompt_tokens} out={resp.completion_tokens}")
    if resp.attempts:
        print(f"  failovers   : {len(resp.attempts)}")
        for a in resp.attempts:
            print(f"     x {a.get('candidate')}: {str(a.get('error'))[:90]}")
    if resp.tool_calls:
        for tc in resp.tool_calls:
            print(f"  tool_call   : {tc.name}({tc.arguments})")
    if resp.text:
        print(f"  text        : {resp.text[:160]!r}")


async def main() -> int:
    router = get_router()
    failures = 0

    # 1. plain completion through the orchestrator chain
    try:
        show(
            "orchestrator / plain",
            await router.complete(
                "orchestrator",
                [Message.user("Reply with exactly: ok")],
                max_tokens=20,
            ),
        )
    except AllCandidatesFailed as exc:
        print(f"\nFAIL orchestrator/plain: {exc}")
        failures += 1

    # 2. tool calling — the orchestrator's core job
    try:
        resp = await router.complete(
            "orchestrator",
            [
                Message.system("You plan trips. Call tools when the user asks for data."),
                Message.user("Find flights from San Francisco to New York on 2026-08-20."),
            ],
            tools=[FLIGHT_TOOL],
            require_tools=True,
            max_tokens=500,
        )
        show("orchestrator / tool_call", resp)
        if not resp.tool_calls:
            print("  !! expected a tool call, got none")
            failures += 1
    except AllCandidatesFailed as exc:
        print(f"\nFAIL orchestrator/tool: {exc}")
        failures += 1

    # 3. structured output on a candidate WITHOUT strict schema support (Groq 8b)
    try:
        data = await complete_json(
            router,
            "field_extractor",
            [Message.user("We want 4 nights in Lisbon for 2 people, about $1800.")],
            schema=TRIP_SCHEMA,
            schema_name="trip_fields",
        )
        print(f"\n--- field_extractor / json ---\n  parsed      : {data}")
        if "destination" not in data:
            print("  !! missing required key")
            failures += 1
    except Exception as exc:
        print(f"\nFAIL field_extractor: {exc!r}")
        failures += 1

    # 4. synthesis (NIM strict json_schema)
    try:
        data = await complete_json(
            router,
            "synthesis",
            [
                Message.user(
                    "Trip: Lisbon, 4 nights, 2 travellers, $1800 budget. "
                    "Echo the trip fields back."
                )
            ],
            schema=TRIP_SCHEMA,
            schema_name="trip_fields",
        )
        print(f"\n--- synthesis / json ---\n  parsed      : {data}")
    except Exception as exc:
        print(f"\nFAIL synthesis: {exc!r}")
        failures += 1

    # 5. failover proof: poison the priority-1 candidate's breaker, confirm the
    #    router silently moves to priority 2.
    print("\n--- failover (breaker forced open on priority-1) ---")
    from app.llm.roles import get_candidates

    top = get_candidates("orchestrator")[0]
    breakers: CircuitBreakerRegistry = router._breakers
    for _ in range(breakers.failure_threshold):
        breakers.record_failure(top.key, "forced for test")
    print(f"  forced open : {top.key} -> {breakers.state(top.key).value}")
    try:
        resp = await router.complete(
            "orchestrator", [Message.user("Reply with exactly: ok")], max_tokens=20
        )
        show("orchestrator / after forced failover", resp)
        if resp.served_by.endswith(top.model):
            print("  !! still served by the open candidate")
            failures += 1
        else:
            print("  OK: routed around the open breaker")
    except AllCandidatesFailed as exc:
        print(f"  FAIL: {exc}")
        failures += 1
    finally:
        breakers.reset(top.key)

    # 6. health snapshot
    print("\n--- health/models ---")
    for role, info in router.health().items():
        print(
            f"  {role:16s} serving={info['currently_serving']} "
            f"degraded={info['degraded']} available={info['available']}"
        )
        for c in info["candidates"]:
            print(
                f"      p{c['priority']} {c['provider']}:{c['model']} "
                f"state={c['state']} key={c['api_key_configured']} usable={c['usable']}"
            )

    await router.aclose()
    print(f"\n{'ALL CHECKS PASSED' if failures == 0 else f'{failures} CHECK(S) FAILED'}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
