"""Routing and map geometry.

Verified: `directions/v2:computeRoutes` works for DRIVE/WALK/BICYCLE on this key.
**TRANSIT returns HTTP 200 with an empty `routes` array** — the mode is not enabled.
That is handled explicitly rather than surfaced as a generic empty result, because
"no transit route exists between these two points" and "we cannot query transit" are
very different statements to make to a user planning a trip.

Legacy `maps/api/directions/json` is denied on this key and is not used.

openrouteservice is the primary route source when its new key can be used, with
LocationIQ next. Google remains the verified fallback, preserving the existing path if a
new provider is unavailable. Route results include a GeoJSON FeatureCollection so a
future MapLibre GL JS frontend can render the line directly with
`addSource(..., {type: "geojson", data})`.
"""

from __future__ import annotations

import logging
import math
from typing import Any

from app.config import get_settings
from app.tools.base import ToolResult, fetch_json, secret

logger = logging.getLogger(__name__)

ROUTES_URL = "https://routes.googleapis.com/directions/v2:computeRoutes"
ORS_BASE = "https://api.openrouteservice.org/v2/directions"
LOCATIONIQ_BASE = "https://us1.locationiq.com/v1"
SUPPORTED_MODES = {"DRIVE", "WALK", "BICYCLE"}
_FIELD_MASK = "routes.duration,routes.distanceMeters,routes.polyline.encodedPolyline"
_ORS_PROFILES = {
    "DRIVE": "driving-car",
    "WALK": "foot-walking",
    "BICYCLE": "cycling-regular",
}
_LOCATIONIQ_PROFILES = {
    "DRIVE": "driving",
    "WALK": "walking",
    "BICYCLE": "cycling",
}


def _waypoint(value: Any) -> dict[str, Any]:
    """Accept either 'Kyoto Station' or {'latitude': .., 'longitude': ..}."""
    if isinstance(value, dict) and "latitude" in value and "longitude" in value:
        return {
            "location": {
                "latLng": {
                    "latitude": float(value["latitude"]),
                    "longitude": float(value["longitude"]),
                }
            }
        }
    return {"address": str(value)}


def _seconds(raw: Any) -> int | None:
    """Routes returns durations as '1659s'."""
    if not raw:
        return None
    try:
        return int(str(raw).rstrip("s"))
    except ValueError:
        return None


def _coordinates(value: Any) -> tuple[float, float] | None:
    """Read a `{latitude, longitude}` waypoint as `(lon, lat)` for GeoJSON APIs."""
    if not isinstance(value, dict):
        return None
    try:
        return float(value["longitude"]), float(value["latitude"])
    except (KeyError, TypeError, ValueError):
        return None


def decode_polyline(encoded: str) -> list[list[float]]:
    """Decode Google's encoded polyline into GeoJSON `[longitude, latitude]` pairs."""
    coordinates: list[list[float]] = []
    index = lat = lon = 0
    while index < len(encoded):
        for axis in ("lat", "lon"):
            value = 0
            shift = 0
            while True:
                if index >= len(encoded):
                    return coordinates
                byte = ord(encoded[index]) - 63
                index += 1
                value |= (byte & 0x1F) << shift
                shift += 5
                if byte < 0x20:
                    break
            delta = ~(value >> 1) if value & 1 else value >> 1
            if axis == "lat":
                lat += delta
            else:
                lon += delta
        coordinates.append([lon / 1e5, lat / 1e5])
    return coordinates


def _route_geojson(
    coordinates: list[list[float]], *, properties: dict[str, Any] | None = None
) -> dict[str, Any]:
    """Build the GeoJSON shape consumed by MapLibre GL JS GeoJSONSource."""
    return {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "properties": properties or {},
                "geometry": {"type": "LineString", "coordinates": coordinates},
            }
        ],
    }


async def _locationiq_geocode(value: Any) -> tuple[float, float] | None:
    coords = _coordinates(value)
    if coords:
        return coords
    key = secret("locationiq_api_key")
    if not key:
        return None
    result = await fetch_json(
        "locationiq",
        "GET",
        f"{LOCATIONIQ_BASE}/search",
        params={"key": key, "q": str(value), "format": "json", "limit": 1},
        cache_ttl=get_settings().cache_ttl_places,
        cache_namespace="locationiq_search",
    )
    if not result.ok or not result.data:
        return None
    top = result.data[0]
    try:
        return float(top["lon"]), float(top["lat"])
    except (KeyError, TypeError, ValueError):
        return None


async def _openrouteservice_route(
    origin: Any,
    destination: Any,
    mode: str,
    *,
    alternatives: bool = False,
    include_steps: bool = False,
    avoid_features: list[str] | None = None,
    extra_info: list[str] | None = None,
) -> ToolResult | None:
    key = secret("openrouteservice_api_key")
    if not key:
        return None
    start = await _locationiq_geocode(origin)
    end = await _locationiq_geocode(destination)
    if not start or not end:
        return None
    body: dict[str, Any] = {
        "coordinates": [list(start), list(end)],
        "instructions": include_steps,
        "geometry_simplify": False,
        "units": "m",
    }
    if alternatives:
        body["alternative_routes"] = {
            "target_count": 2,
            "weight_factor": 1.4,
            "share_factor": 0.6,
        }
    options: dict[str, Any] = {}
    if avoid_features:
        options["avoid_features"] = avoid_features
    if options:
        body["options"] = options
    if extra_info:
        body["extra_info"] = extra_info

    result = await fetch_json(
        "openrouteservice",
        "POST",
        f"{ORS_BASE}/{_ORS_PROFILES[mode]}/geojson",
        headers={"Authorization": key, "Content-Type": "application/json"},
        json_body=body,
        cache_ttl=get_settings().cache_ttl_maps,
        cache_namespace="openrouteservice_routes",
    )
    if not result.ok:
        return result
    geojson = result.data or {}
    feature = (geojson.get("features") or [{}])[0]
    summary = (feature.get("properties") or {}).get("summary") or {}
    geometry = feature.get("geometry") or {}
    return ToolResult(
        source="openrouteservice",
        data={
            "provider": "openrouteservice",
            "mode": mode,
            "duration_seconds": round(summary.get("duration")) if summary.get("duration") is not None else None,
            "duration_minutes": round(summary["duration"] / 60) if summary.get("duration") is not None else None,
            "distance_meters": round(summary["distance"]) if summary.get("distance") is not None else None,
            "distance_km": round(summary["distance"] / 1000, 1) if summary.get("distance") is not None else None,
            "geometry": geometry,
            "geojson": geojson,
            "route_count": len(geojson.get("features") or []),
            "segments": (feature.get("properties") or {}).get("segments") or [],
        },
        cached=result.cached,
    )


async def _locationiq_route(origin: Any, destination: Any, mode: str) -> ToolResult | None:
    key = secret("locationiq_api_key")
    if not key:
        return None
    start = await _locationiq_geocode(origin)
    end = await _locationiq_geocode(destination)
    if not start or not end:
        return None
    # LocationIQ currently documents driving and walking profiles. Cycling and
    # advanced alternatives remain openrouteservice-only in the primary path.
    if mode not in {"DRIVE", "WALK"}:
        return None
    coordinates = f"{start[0]},{start[1]};{end[0]},{end[1]}"
    result = await fetch_json(
        "locationiq",
        "GET",
        f"{LOCATIONIQ_BASE}/directions/{_LOCATIONIQ_PROFILES[mode]}/{coordinates}",
        params={
            "key": key,
            "overview": "full",
            "geometries": "geojson",
            "steps": "false",
        },
        cache_ttl=get_settings().cache_ttl_maps,
        cache_namespace="locationiq_routes",
    )
    if not result.ok:
        return result
    route = ((result.data or {}).get("routes") or [{}])[0]
    geometry = route.get("geometry") or {}
    geojson = _route_geojson(
        geometry.get("coordinates") or [],
        properties={"provider": "locationiq", "mode": mode},
    )
    distance = route.get("distance")
    duration = route.get("duration")
    return ToolResult(
        source="locationiq",
        data={
            "provider": "locationiq",
            "mode": mode,
            "duration_seconds": round(duration) if duration is not None else None,
            "duration_minutes": round(duration / 60) if duration is not None else None,
            "distance_meters": round(distance) if distance is not None else None,
            "distance_km": round(distance / 1000, 1) if distance is not None else None,
            "geometry": geometry,
            "geojson": geojson,
        },
        cached=result.cached,
    )


async def maps_route(
    origin: Any,
    destination: Any,
    *,
    mode: str = "DRIVE",
    departure_time: str | None = None,
    provider: str = "auto",
    alternatives: bool = False,
    include_steps: bool = False,
    avoid_features: list[str] | None = None,
    extra_info: list[str] | None = None,
) -> ToolResult:
    """Travel time and distance between two points."""
    mode = mode.upper()
    if mode == "TRANSIT":
        # Don't spend a call on a mode we've verified returns nothing.
        return ToolResult(
            source="google_routes",
            status="unavailable",
            error=(
                "Public-transit routing is not enabled for this API key. Use DRIVE or "
                "WALK for an estimate, and tell the user transit times are unverified."
            ),
        )
    if mode not in SUPPORTED_MODES:
        return ToolResult.failure(
            "google_routes",
            f"Unsupported travel mode {mode!r}; expected one of {sorted(SUPPORTED_MODES)}",
        )

    if provider == "openrouteservice":
        return (
            await _openrouteservice_route(
                origin,
                destination,
                mode,
                alternatives=alternatives,
                include_steps=include_steps,
                avoid_features=avoid_features,
                extra_info=extra_info,
            )
            or ToolResult.missing_key("openrouteservice", "openrouteservice_API_KEY")
        )
    if provider == "locationiq":
        return (
            await _locationiq_route(origin, destination, mode)
            or ToolResult.missing_key("locationiq", "LocationIQ_API_KEY")
        )
    if provider not in {"google", "auto"}:
        return ToolResult.failure(
            "maps_route", "provider must be google, openrouteservice, or locationiq"
        )

    key = secret("google_maps_demo_api_key")
    if not key:
        if provider == "auto":
            primary = await _openrouteservice_route(
                origin,
                destination,
                mode,
                alternatives=alternatives,
                include_steps=include_steps,
                avoid_features=avoid_features,
                extra_info=extra_info,
            )
            if primary is not None and primary.ok:
                return primary
            secondary = await _locationiq_route(origin, destination, mode)
            if secondary is not None and secondary.ok:
                return secondary
        return ToolResult.missing_key("google_routes", "GOOGLE_MAPS_DEMO_API_KEY")

    body: dict[str, Any] = {
        "origin": _waypoint(origin),
        "destination": _waypoint(destination),
        "travelMode": mode,
    }
    if mode == "DRIVE":
        body["routingPreference"] = "TRAFFIC_AWARE"
        if departure_time:
            body["departureTime"] = departure_time

    result = await fetch_json(
        "google_routes",
        "POST",
        ROUTES_URL,
        headers={
            "X-Goog-Api-Key": key,
            "X-Goog-FieldMask": _FIELD_MASK,  # mandatory
            "Content-Type": "application/json",
        },
        json_body=body,
        cache_ttl=get_settings().cache_ttl_maps,
        cache_namespace="routes",
    )
    if not result.ok:
        if provider == "auto":
            primary = await _openrouteservice_route(
                origin,
                destination,
                mode,
                alternatives=alternatives,
                include_steps=include_steps,
                avoid_features=avoid_features,
                extra_info=extra_info,
            )
            if primary is not None and primary.ok:
                return primary
            secondary = await _locationiq_route(origin, destination, mode)
            if secondary is not None and secondary.ok:
                return secondary
        return result

    routes = (result.data or {}).get("routes") or []
    if not routes:
        if provider == "auto":
            primary = await _openrouteservice_route(
                origin,
                destination,
                mode,
                alternatives=alternatives,
                include_steps=include_steps,
                avoid_features=avoid_features,
                extra_info=extra_info,
            )
            if primary is not None and primary.ok:
                return primary
            secondary = await _locationiq_route(origin, destination, mode)
            if secondary is not None and secondary.ok:
                return secondary
        return ToolResult(
            source="google_routes",
            status="unavailable",
            error=f"No {mode} route found between the given points.",
        )

    top = routes[0]
    seconds = _seconds(top.get("duration"))
    meters = top.get("distanceMeters")
    encoded = (top.get("polyline") or {}).get("encodedPolyline")
    coordinates = decode_polyline(encoded) if encoded else []
    return ToolResult(
        source="google_routes",
        data={
            "provider": "google",
            "mode": mode,
            "duration_seconds": seconds,
            "duration_minutes": round(seconds / 60) if seconds else None,
            "distance_meters": meters,
            "distance_km": round(meters / 1000, 1) if meters else None,
            "polyline": encoded,
            "geometry": {"type": "LineString", "coordinates": coordinates},
            "geojson": _route_geojson(
                coordinates, properties={"provider": "google", "mode": mode}
            ),
        },
        cached=result.cached,
    )


def haversine_km(
    lat1: float, lon1: float, lat2: float, lon2: float
) -> float:
    """Straight-line distance. Zero API cost.

    Used for proximity *screening* — e.g. flagging a hotel that sits far from the
    evening's planned dinner — before spending a Routes call on the few pairs that
    actually matter. Never presented to the user as a travel time.
    """
    radius_km = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (
        math.sin(dlat / 2) ** 2
        + math.cos(math.radians(lat1))
        * math.cos(math.radians(lat2))
        * math.sin(dlon / 2) ** 2
    )
    return radius_km * 2 * math.asin(math.sqrt(a))
