"""Flights — Duffel search (§4.1) + aviationstack status.

Two genuinely different operations, deliberately kept apart:

  flight_lookup()  → Duffel offer requests. The planning path.
  flight_status()  → aviationstack. **100 calls per MONTH** on this key, so it is only
                     for an explicit "is flight X on time" question, never speculative
                     enrichment of an itinerary.

Duffel notes verified live: `Duffel-Version: v2` is mandatory (v1/beta are rejected),
the key is test-mode, and prices return in AUD (the account's default currency) rather
than the requested currency. Offers carry `expires_at` ~1h out, so the cache TTL is
deliberately short — a cached offer id that has expired is worse than a cache miss.
"""

from __future__ import annotations

import logging
import re
from typing import Any

from app.config import get_settings
from app.tools.base import ToolResult, fetch_json, secret

logger = logging.getLogger(__name__)

DUFFEL_BASE = "https://api.duffel.com"
AVIATIONSTACK_BASE = "https://api.aviationstack.com/v1"
MAX_OFFERS = 12

_ISO_DUR = re.compile(
    r"P(?:(?P<days>\d+)D)?T?(?:(?P<hours>\d+)H)?(?:(?P<minutes>\d+)M)?"
)


def _duration_minutes(iso: str | None) -> int | None:
    """Duffel returns ISO-8601 durations like 'PT10H19M'."""
    if not iso:
        return None
    m = _ISO_DUR.fullmatch(iso)
    if not m:
        return None
    days = int(m.group("days") or 0)
    hours = int(m.group("hours") or 0)
    minutes = int(m.group("minutes") or 0)
    total = days * 1440 + hours * 60 + minutes
    return total or None


async def flight_lookup(
    origin: str,
    destination: str,
    departure_date: str,
    *,
    return_date: str | None = None,
    passengers: int = 1,
    cabin_class: str = "economy",
    max_results: int = MAX_OFFERS,
) -> ToolResult:
    """Search flight offers. `origin`/`destination` are IATA codes."""
    key = secret("flight_api_key")
    if not key:
        return ToolResult.missing_key("duffel", "FLIGHT_API_KEY")

    slices: list[dict[str, str]] = [
        {
            "origin": origin.upper(),
            "destination": destination.upper(),
            "departure_date": departure_date,
        }
    ]
    if return_date:
        slices.append(
            {
                "origin": destination.upper(),
                "destination": origin.upper(),
                "departure_date": return_date,
            }
        )

    body = {
        "data": {
            "slices": slices,
            "passengers": [{"type": "adult"} for _ in range(max(1, passengers))],
            "cabin_class": cabin_class,
        }
    }

    result = await fetch_json(
        "duffel",
        "POST",
        f"{DUFFEL_BASE}/air/offer_requests",
        headers={
            "Authorization": f"Bearer {key}",
            "Duffel-Version": "v2",
            "Accept": "application/json",
            "Content-Type": "application/json",
        },
        params={"return_offers": "true"},
        json_body=body,
        cache_ttl=get_settings().cache_ttl_flights,
        cache_namespace="flights",
        timeout=45.0,  # offer search is genuinely slow
    )
    if not result.ok:
        return result

    payload = (result.data or {}).get("data") or {}
    offers = payload.get("offers") or []
    parsed = [_parse_offer(o) for o in offers[:max_results]]
    parsed = [p for p in parsed if p]
    parsed.sort(key=lambda o: o.get("price_amount") or float("inf"))

    return ToolResult(
        source="duffel",
        data={
            "origin": origin.upper(),
            "destination": destination.upper(),
            "departure_date": departure_date,
            "return_date": return_date,
            "passengers": passengers,
            "cabin_class": cabin_class,
            "offer_count": len(offers),
            "offers": parsed,
            "live_mode": payload.get("live_mode", False),
            "note": (
                "Test-mode Duffel data; prices are indicative and returned in the "
                "account's default currency. Offers expire about an hour after search."
            ),
        },
        cached=result.cached,
    )


def _parse_offer(offer: dict[str, Any]) -> dict[str, Any] | None:
    try:
        slices = []
        for sl in offer.get("slices") or []:
            segments = []
            for seg in sl.get("segments") or []:
                segments.append(
                    {
                        "flight_number": seg.get("operating_carrier_flight_number"),
                        "carrier": (seg.get("operating_carrier") or {}).get("name"),
                        "origin": (seg.get("origin") or {}).get("iata_code"),
                        "destination": (seg.get("destination") or {}).get("iata_code"),
                        "departing_at": seg.get("departing_at"),
                        "arriving_at": seg.get("arriving_at"),
                        "duration_minutes": _duration_minutes(seg.get("duration")),
                        "aircraft": (seg.get("aircraft") or {}).get("name"),
                    }
                )
            slices.append(
                {
                    "origin": (sl.get("origin") or {}).get("iata_code"),
                    "destination": (sl.get("destination") or {}).get("iata_code"),
                    "duration_minutes": _duration_minutes(sl.get("duration")),
                    "fare_brand": sl.get("fare_brand_name"),
                    # stops == connections, which is what a traveller actually cares about
                    "stops": max(0, len(segments) - 1),
                    "segments": segments,
                }
            )

        amount = offer.get("total_amount")
        return {
            "offer_id": offer.get("id"),
            "airline": (offer.get("owner") or {}).get("name"),
            "price_amount": float(amount) if amount is not None else None,
            "price_currency": offer.get("total_currency"),
            "expires_at": offer.get("expires_at"),
            "total_duration_minutes": sum(
                s["duration_minutes"] or 0 for s in slices
            )
            or None,
            "total_stops": sum(s["stops"] for s in slices),
            "slices": slices,
        }
    except (TypeError, ValueError, AttributeError) as exc:
        logger.warning("duffel.parse_failed offer=%s error=%s", offer.get("id"), exc)
        return None


async def flight_status(flight_iata: str, *, flight_date: str | None = None) -> ToolResult:
    """Live status for a specific flight number.

    Quota-critical: the provisioned aviationstack key allows 100 calls per month.
    Cached for a day and intended only for direct user questions about a flight.
    """
    key = secret("flight_data_api_key")
    if not key:
        return ToolResult.missing_key("aviationstack", "FLIGHT_DATA_API_KEY")

    params: dict[str, Any] = {"access_key": key, "flight_iata": flight_iata, "limit": 3}
    if flight_date:
        params["flight_date"] = flight_date

    result = await fetch_json(
        "aviationstack",
        "GET",
        f"{AVIATIONSTACK_BASE}/flights",
        params=params,
        cache_ttl=60 * 60 * 24,
        cache_namespace="flight_status",
    )
    if not result.ok:
        return result

    rows = (result.data or {}).get("data") or []
    flights = [
        {
            "flight_date": r.get("flight_date"),
            "status": r.get("flight_status"),
            "airline": (r.get("airline") or {}).get("name"),
            "flight_number": (r.get("flight") or {}).get("iata"),
            "departure": {
                "airport": (r.get("departure") or {}).get("airport"),
                "iata": (r.get("departure") or {}).get("iata"),
                "terminal": (r.get("departure") or {}).get("terminal"),
                "scheduled": (r.get("departure") or {}).get("scheduled"),
                "delay_minutes": (r.get("departure") or {}).get("delay"),
            },
            "arrival": {
                "airport": (r.get("arrival") or {}).get("airport"),
                "iata": (r.get("arrival") or {}).get("iata"),
                "terminal": (r.get("arrival") or {}).get("terminal"),
                "scheduled": (r.get("arrival") or {}).get("scheduled"),
                "delay_minutes": (r.get("arrival") or {}).get("delay"),
            },
        }
        for r in rows
    ]
    return ToolResult(
        source="aviationstack",
        data={"flight_iata": flight_iata, "flights": flights},
        cached=result.cached,
    )
