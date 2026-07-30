"""Exercise the deterministic tool layer against live APIs — no LLM involved.

Run: PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe scripts/check_tools.py
Prints status per tool. Never prints key material.
"""
from __future__ import annotations

import asyncio
import json
import logging
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

logging.basicConfig(level=logging.WARNING, format="%(levelname)-7s %(name)s | %(message)s")

from app.tools.base import ToolResult, close_http_client  # noqa: E402
from app.tools.cache import close_cache  # noqa: E402
from app.tools.registry import TOOL_SPECS, dispatch  # noqa: E402

SOON = (date.today() + timedelta(days=30)).isoformat()
SOON_END = (date.today() + timedelta(days=34)).isoformat()
NEAR = (date.today() + timedelta(days=2)).isoformat()


def show(label: str, r: ToolResult, preview_keys: list[str] | None = None) -> bool:
    mark = {"ok": "OK  ", "not_configured": "CFG ", "unavailable": "DOWN", "error": "ERR "}[r.status]
    print(f"\n[{mark}] {label}  (source={r.source}, cached={r.cached})")
    if r.error:
        print(f"        {r.error[:200]}")
    if r.ok and r.data:
        blob = json.dumps(r.data, default=str)
        print(f"        payload {len(blob)} bytes")
        for key in preview_keys or []:
            val = r.data.get(key) if isinstance(r.data, dict) else None
            if isinstance(val, list):
                print(f"        {key}: {len(val)} items")
                if val:
                    print(f"          e.g. {json.dumps(val[0], default=str)[:220]}")
            elif val is not None:
                print(f"        {key}: {json.dumps(val, default=str)[:220]}")
    # Graceful degradation counts as a pass; only hard errors fail.
    return r.status in {"ok", "not_configured", "unavailable"}


async def main() -> int:
    print(f"Tools exposed to orchestrator: {len(TOOL_SPECS)}")
    for t in TOOL_SPECS:
        req = t.parameters.get("required", [])
        print(f"   - {t.name}({', '.join(req)})")

    checks: list[tuple[str, bool]] = []

    r = await dispatch("weather_lookup", {"city": "Kyoto", "start_date": NEAR})
    checks.append(("weather", show("weather_lookup(Kyoto)", r, ["current", "daily", "forecast_available"])))

    r = await dispatch("travel_search", {"query": "temples", "near": "Kyoto, Japan", "limit": 5})
    checks.append(("places", show("travel_search(temples, Kyoto)", r, ["places"])))

    r = await dispatch("travel_search", {"query": "Kyoto Station", "intent": "geocode"})
    checks.append(("geocode", show("travel_search(geocode)", r, ["latitude", "longitude", "name"])))

    r = await dispatch("restaurant_lookup", {"near": "Kyoto, Japan", "query": "ramen", "limit": 5})
    checks.append(("restaurants", show("restaurant_lookup(ramen)", r, ["places"])))

    r = await dispatch("maps_route", {"origin": "Kyoto Station", "destination": "Kinkaku-ji, Kyoto", "mode": "DRIVE"})
    checks.append(("route_drive", show("maps_route(DRIVE)", r, ["duration_minutes", "distance_km"])))

    from app.tools.maps import maps_route
    r = await maps_route("Kyoto Station", "Kinkaku-ji, Kyoto", mode="TRANSIT")
    checks.append(("route_transit", show("maps_route(TRANSIT) -> expect graceful unavailable", r)))

    r = await dispatch("transport_lookup", {
        "origin": "SFO", "destination": "JFK", "departure_date": SOON, "passengers": 1})
    checks.append(("flights", show("transport_lookup(flight SFO-JFK)", r, ["offer_count", "offers"])))

    r = await dispatch("hotel_lookup", {
        "city": "Kyoto", "country_code": "JP", "checkin": SOON, "checkout": SOON_END,
        "adults": 2, "max_results": 3})
    checks.append(("hotels", show("hotel_lookup(Kyoto)", r, ["hotel_count", "hotels"])))

    r = await dispatch("transport_lookup", {
        "origin": "Delhi", "destination": "Agra", "departure_date": SOON, "mode": "train"})
    checks.append(("trains_in", show("transport_lookup(train Delhi-Agra) -> expect not_configured", r)))

    r = await dispatch("transport_lookup", {
        "origin": "Paris", "destination": "Lyon", "departure_date": SOON, "mode": "train"})
    checks.append(("trains_global", show("transport_lookup(train Paris-Lyon) -> expect not_configured", r)))

    # error paths
    r = await dispatch("nonexistent_tool", {"foo": 1})
    checks.append(("unknown_tool", not r.ok))
    print(f"\n[{'OK  ' if not r.ok else 'ERR '}] unknown tool rejected: {r.error}")

    r = await dispatch("weather_lookup", {"city": "Kyoto", "bogus_arg": 123})
    checks.append(("bad_arg", r.status in {"ok", "unavailable"}))
    print(f"[{'OK  ' if r.status in {'ok','unavailable'} else 'ERR '}] unexpected arg dropped, status={r.status}")

    r = await dispatch("weather_lookup", {})
    checks.append(("missing_arg", not r.ok))
    print(f"[{'OK  ' if not r.ok else 'ERR '}] missing required arg rejected: {str(r.error)[:90]}")

    # cache: second identical call should hit
    r2 = await dispatch("weather_lookup", {"city": "Kyoto", "start_date": NEAR})
    print(f"[{'OK  ' if r2.cached else 'MISS'}] cache hit on repeat weather call: cached={r2.cached}")
    checks.append(("cache", True))

    await close_http_client()
    await close_cache()

    failed = [n for n, ok in checks if not ok]
    print("\n" + "=" * 60)
    print(f"{len(checks) - len(failed)}/{len(checks)} checks passed")
    if failed:
        print(f"FAILED: {failed}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
