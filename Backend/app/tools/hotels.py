"""Hotels — liteAPI (§4.1).

Verified: `X-API-Key` header (not Bearer), `https://api.liteapi.travel/v3.0`, sandbox key.

Two constraints drove this module's shape:
  * `x-ratelimit-limit: 5` **per second** — hence the module-level RateLimiter. Blowing
    through it produces 429s that look like an outage and would trip the breaker.
  * `roomTypes` can carry ~200 entries per hotel. Sending that to an LLM would blow the
    context window for no benefit, so rooms are truncated to the cheapest few per hotel
    before the data ever leaves this layer.
"""

from __future__ import annotations

import logging
from typing import Any

from app.config import get_settings
from app.tools.base import RateLimiter, ToolResult, fetch_json, secret

logger = logging.getLogger(__name__)

BASE = "https://api.liteapi.travel/v3.0"
MAX_ROOMS_PER_HOTEL = 3
MAX_HOTELS = 10

# liteAPI caps at 5 rps; stay under it.
_limiter = RateLimiter(per_second=4.0)


async def hotel_lookup(
    city: str,
    *,
    country_code: str,
    checkin: str,
    checkout: str,
    adults: int = 2,
    currency: str = "USD",
    guest_nationality: str = "US",
    max_results: int = 6,
) -> ToolResult:
    """Hotel availability with live rates for a date range."""
    key = secret("hotel_api_key")
    if not key:
        return ToolResult.missing_key("liteapi", "HOTEL_API_KEY")

    body: dict[str, Any] = {
        "checkin": checkin,
        "checkout": checkout,
        "currency": currency,
        "guestNationality": guest_nationality,
        "occupancies": [{"adults": max(1, adults)}],
        "cityName": city,
        "countryCode": country_code.upper(),
        "limit": min(max_results, MAX_HOTELS),
    }

    result = await fetch_json(
        "liteapi",
        "POST",
        f"{BASE}/hotels/rates",
        headers={"X-API-Key": key, "Content-Type": "application/json"},
        json_body=body,
        cache_ttl=get_settings().cache_ttl_hotels,
        cache_namespace="hotel_rates",
        limiter=_limiter,
        timeout=30.0,
    )
    if not result.ok:
        return result

    payload = result.data or {}
    # Hotel metadata and rate data arrive in two parallel lists keyed by hotel id.
    meta_by_id = {h.get("id"): h for h in (payload.get("hotels") or []) if h.get("id")}
    rate_rows = payload.get("data") or []

    hotels: list[dict[str, Any]] = []
    for row in rate_rows[:max_results]:
        hotel_id = row.get("hotelId")
        meta = meta_by_id.get(hotel_id, {})
        rooms = _cheapest_rooms(row.get("roomTypes") or [])
        cheapest = rooms[0]["price"] if rooms and rooms[0].get("price") else None
        hotels.append(
            {
                "hotel_id": hotel_id,
                "name": meta.get("name"),
                "stars": meta.get("stars"),
                "rating": meta.get("rating"),
                "review_count": meta.get("reviewCount") or meta.get("review_count"),
                "address": meta.get("address"),
                "latitude": meta.get("latitude"),
                "longitude": meta.get("longitude"),
                "photo": meta.get("main_photo") or meta.get("mainPhoto"),
                "cheapest_price": cheapest,
                "currency": currency,
                "rooms": rooms,
            }
        )

    hotels.sort(key=lambda h: h.get("cheapest_price") or float("inf"))

    return ToolResult(
        source="liteapi",
        data={
            "city": city,
            "country_code": country_code.upper(),
            "checkin": checkin,
            "checkout": checkout,
            "adults": adults,
            "currency": currency,
            "hotel_count": len(rate_rows),
            "hotels": hotels,
            "sandbox": bool(payload.get("sandbox")),
        },
        cached=result.cached,
    )


def _cheapest_rooms(room_types: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Truncate a ~200-entry room list to the few cheapest, flattened."""
    rooms: list[dict[str, Any]] = []
    for rt in room_types:
        retail = rt.get("offerRetailRate") or {}
        price = retail.get("amount")
        name = None
        rates = rt.get("rates") or []
        if rates:
            name = rates[0].get("name") or (rates[0].get("roomType") or {}).get("name")
        rooms.append(
            {
                "offer_id": rt.get("offerId"),
                "name": name,
                "price": float(price) if price is not None else None,
                "currency": retail.get("currency"),
                "board": (rates[0].get("boardName") if rates else None),
                "refundable": (
                    (rates[0].get("cancellationPolicies") or {}).get("refundableTag")
                    if rates
                    else None
                ),
            }
        )
    rooms.sort(key=lambda r: r.get("price") or float("inf"))
    return rooms[:MAX_ROOMS_PER_HOTEL]


async def hotel_search_static(
    city: str, *, country_code: str, limit: int = 5
) -> ToolResult:
    """Static hotel directory lookup — no dates, no live rates.

    Useful when the user is still deciding *where* and pricing would be noise.
    """
    key = secret("hotel_api_key")
    if not key:
        return ToolResult.missing_key("liteapi", "HOTEL_API_KEY")

    result = await fetch_json(
        "liteapi",
        "GET",
        f"{BASE}/data/hotels",
        headers={"X-API-Key": key},
        params={
            "countryCode": country_code.upper(),
            "cityName": city,
            "limit": limit,
        },
        cache_ttl=get_settings().cache_ttl_places,
        cache_namespace="hotel_static",
        limiter=_limiter,
    )
    if not result.ok:
        return result

    rows = (result.data or {}).get("data") or []
    return ToolResult(
        source="liteapi",
        data={
            "city": city,
            "hotels": [
                {
                    "hotel_id": h.get("id"),
                    "name": h.get("name"),
                    "address": h.get("address"),
                    "latitude": h.get("latitude"),
                    "longitude": h.get("longitude"),
                    "photo": h.get("main_photo"),
                }
                for h in rows[:limit]
            ],
        },
        cached=result.cached,
    )
