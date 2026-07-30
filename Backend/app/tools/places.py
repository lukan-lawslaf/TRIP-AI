"""Places — Foursquare restaurants + Google Places (New) attractions/geocoding (§4.1).

Verified constraints baked in here:
  * Foursquare's legacy `api.foursquare.com/v3` host 401s. Current host is
    `places-api.foursquare.com` with `Authorization: Bearer` and a mandatory
    `X-Places-Api-Version` header — and `2025-06-17` is the *only* value that
    validates (every other date string tested returned 400).
  * Google's Geocoding API is denied on this key (billing not enabled), as is every
    legacy Places/Directions endpoint. Places API (New) works, so geocoding is done
    via `places:searchText` — see `geocode()`.
  * Google's `X-Goog-FieldMask` header is mandatory, not optional. Omitting it 400s.
"""

from __future__ import annotations

import logging
from typing import Any

from app.config import get_settings
from app.tools.base import ToolResult, fetch_json, secret

logger = logging.getLogger(__name__)

FSQ_BASE = "https://places-api.foursquare.com"
FSQ_API_VERSION = "2025-06-17"  # only accepted value; do not "update" without testing
GOOGLE_PLACES_BASE = "https://places.googleapis.com/v1"

_PLACE_FIELDS = ",".join(
    [
        "places.displayName",
        "places.formattedAddress",
        "places.rating",
        "places.userRatingCount",
        "places.priceLevel",
        "places.location",
        "places.regularOpeningHours.openNow",
        "places.primaryTypeDisplayName",
    ]
)


async def restaurant_lookup(
    near: str,
    *,
    query: str = "restaurant",
    limit: int = 10,
    latitude: float | None = None,
    longitude: float | None = None,
) -> ToolResult:
    """Restaurants near a place. `near` is a free-text locality ("Kyoto, Japan")."""
    key = secret("restaurant_api_key")
    if not key:
        return ToolResult.missing_key("foursquare", "RESTAURANT_API_KEY")

    params: dict[str, Any] = {"query": query, "limit": min(limit, 25)}
    # Coordinates beat a locality string when we have them — "Kyoto" is ambiguous
    # in a way that 35.0116,135.7681 is not.
    if latitude is not None and longitude is not None:
        params["ll"] = f"{latitude},{longitude}"
        params["radius"] = 8000
    else:
        params["near"] = near

    result = await fetch_json(
        "foursquare",
        "GET",
        f"{FSQ_BASE}/places/search",
        headers={
            "Authorization": f"Bearer {key}",
            "X-Places-Api-Version": FSQ_API_VERSION,
            "Accept": "application/json",
        },
        params=params,
        cache_ttl=get_settings().cache_ttl_places,
        cache_namespace="fsq_places",
    )
    if not result.ok:
        return result

    rows = (result.data or {}).get("results") or []
    places = [
        {
            "place_id": r.get("fsq_place_id"),
            "name": r.get("name"),
            "address": (r.get("location") or {}).get("formatted_address"),
            "categories": [c.get("name") for c in (r.get("categories") or []) if c.get("name")],
            "latitude": r.get("latitude"),
            "longitude": r.get("longitude"),
            "distance_meters": r.get("distance"),
        }
        for r in rows
    ]
    return ToolResult(
        source="foursquare",
        data={"near": near, "query": query, "places": places},
        cached=result.cached,
    )


async def places_search(
    text_query: str, *, limit: int = 10, open_now: bool | None = None
) -> ToolResult:
    """Attractions/POIs via Google Places (New) text search.

    Richer than Foursquare for sightseeing — carries rating counts and price level.
    """
    key = secret("google_maps_demo_api_key")
    if not key:
        return ToolResult.missing_key("google_places", "GOOGLE_MAPS_DEMO_API_KEY")

    body: dict[str, Any] = {"textQuery": text_query, "maxResultCount": min(limit, 20)}
    if open_now is not None:
        body["openNow"] = open_now

    result = await fetch_json(
        "google_places",
        "POST",
        f"{GOOGLE_PLACES_BASE}/places:searchText",
        headers={
            "X-Goog-Api-Key": key,
            "X-Goog-FieldMask": _PLACE_FIELDS,  # mandatory
            "Content-Type": "application/json",
        },
        json_body=body,
        cache_ttl=get_settings().cache_ttl_places,
        cache_namespace="gplaces_text",
    )
    if not result.ok:
        return result

    return ToolResult(
        source="google_places",
        data={"query": text_query, "places": _parse_google_places(result.data)},
        cached=result.cached,
    )


async def places_nearby(
    latitude: float,
    longitude: float,
    *,
    radius_meters: int = 3000,
    included_types: list[str] | None = None,
    limit: int = 10,
) -> ToolResult:
    """POIs within a radius — used to keep a day's activities geographically tight."""
    key = secret("google_maps_demo_api_key")
    if not key:
        return ToolResult.missing_key("google_places", "GOOGLE_MAPS_DEMO_API_KEY")

    body: dict[str, Any] = {
        "maxResultCount": min(limit, 20),
        "locationRestriction": {
            "circle": {
                "center": {"latitude": latitude, "longitude": longitude},
                "radius": float(radius_meters),
            }
        },
    }
    if included_types:
        body["includedTypes"] = included_types

    result = await fetch_json(
        "google_places",
        "POST",
        f"{GOOGLE_PLACES_BASE}/places:searchNearby",
        headers={
            "X-Goog-Api-Key": key,
            "X-Goog-FieldMask": _PLACE_FIELDS,
            "Content-Type": "application/json",
        },
        json_body=body,
        cache_ttl=get_settings().cache_ttl_places,
        cache_namespace="gplaces_nearby",
    )
    if not result.ok:
        return result

    return ToolResult(
        source="google_places",
        data={
            "center": {"latitude": latitude, "longitude": longitude},
            "radius_meters": radius_meters,
            "places": _parse_google_places(result.data),
        },
        cached=result.cached,
    )


async def geocode(place: str) -> ToolResult:
    """Resolve a place name to coordinates.

    Goes through Places (New) text search rather than the Geocoding API, which is
    denied on this key (billing not enabled on the project).
    """
    result = await places_search(place, limit=1)
    if not result.ok:
        return result

    places = (result.data or {}).get("places") or []
    if not places:
        return ToolResult.failure("google_places", f"No location found for {place!r}")

    top = places[0]
    return ToolResult(
        source="google_places",
        data={
            "query": place,
            "name": top.get("name"),
            "address": top.get("address"),
            "latitude": top.get("latitude"),
            "longitude": top.get("longitude"),
        },
        cached=result.cached,
    )


def _parse_google_places(payload: Any) -> list[dict[str, Any]]:
    rows = (payload or {}).get("places") or []
    out = []
    for p in rows:
        loc = p.get("location") or {}
        out.append(
            {
                "name": (p.get("displayName") or {}).get("text"),
                "address": p.get("formattedAddress"),
                "rating": p.get("rating"),
                "rating_count": p.get("userRatingCount"),
                "price_level": p.get("priceLevel"),
                "category": (p.get("primaryTypeDisplayName") or {}).get("text"),
                "latitude": loc.get("latitude"),
                "longitude": loc.get("longitude"),
                "open_now": (p.get("regularOpeningHours") or {}).get("openNow"),
            }
        )
    return out
