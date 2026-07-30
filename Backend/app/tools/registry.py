"""Tool registry: JSON-schema contracts exposed to the orchestrator (§4.2).

Two rules from the spec shape this file.

**Explicit JSON schemas, not prose.** Each entry carries a real schema; that's what
actually drives structured-output reliability.

**Cap at 6-8 semantic groups.** Tool-selection accuracy degrades past that, so raw
endpoints are grouped rather than exposed individually. `travel_search` covers
attractions/POIs/geocoding; `transport_lookup` fans out to flights *or* trains on a
`mode` argument instead of burning two slots. Eight groups total — at the cap:

    1. travel_search      places, attractions, geocoding
    2. transport_lookup   flights or trains
    3. hotel_lookup       accommodation with live rates
    4. restaurant_lookup  dining
    5. weather_lookup     conditions + forecast
    6. maps_route         travel time between two points
    7. knowledge_lookup   RAG over curated guides
    8. web_search         live web (Serper quick / Tavily deep)

Handlers are plain async functions returning `ToolResult`. **No LLM is involved in
executing any of them** (§4.1) — the orchestrator decides *that* a tool should run;
the backend runs it in plain code.
"""

from __future__ import annotations

import inspect
import logging
from typing import Any, Awaitable, Callable

from app.llm.types import ToolSpec
from app.tools.base import ToolResult
from app.tools.flights import flight_lookup, flight_status
from app.tools.hotels import hotel_lookup, hotel_search_static
from app.tools.maps import maps_route
from app.tools.places import geocode, places_nearby, places_search, restaurant_lookup
from app.tools.trains import train_lookup
from app.tools.weather import weather_lookup
from app.tools.websearch import maps_lookup, web_search

logger = logging.getLogger(__name__)

Handler = Callable[..., Awaitable[ToolResult]]


# --- 1. travel_search ---------------------------------------------------------

async def travel_search(
    query: str,
    *,
    near: str | None = None,
    intent: str = "attractions",
    limit: int = 8,
) -> ToolResult:
    """Places, attractions, and geocoding behind one semantic entry point."""
    if intent == "geocode":
        return await geocode(query)

    text = f"{query} in {near}" if near and near.lower() not in query.lower() else query
    return await places_search(text, limit=limit)


# --- 2. transport_lookup ------------------------------------------------------

async def transport_lookup(
    origin: str,
    destination: str,
    departure_date: str,
    *,
    mode: str = "flight",
    return_date: str | None = None,
    passengers: int = 1,
    cabin_class: str = "economy",
) -> ToolResult:
    """Flights or trains between two places."""
    if mode == "train":
        return await train_lookup(origin, destination, departure_date)
    return await flight_lookup(
        origin,
        destination,
        departure_date,
        return_date=return_date,
        passengers=passengers,
        cabin_class=cabin_class,
    )


# --- 7. knowledge_lookup (RAG) ------------------------------------------------

async def knowledge_lookup(query: str, *, destination: str | None = None, limit: int = 5) -> ToolResult:
    """Curated travel-guide lookup. Delegates to the RAG layer."""
    try:
        from app.rag.retrieval import rag_query
    except ImportError:
        return ToolResult(
            source="rag",
            status="not_configured",
            error="Knowledge base is not available.",
        )
    return await rag_query(query, destination=destination, limit=limit)


TOOL_SPECS: list[ToolSpec] = [
    ToolSpec(
        name="travel_search",
        description=(
            "Search for attractions, landmarks, neighbourhoods, or points of interest "
            "in a destination, or resolve a place name to coordinates. Use this to "
            "find things to do and to disambiguate vague place names."
        ),
        parameters={
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "What to look for, e.g. 'temples', 'art museums', 'Shibuya Crossing'",
                },
                "near": {
                    "type": "string",
                    "description": "City or area to search within, e.g. 'Kyoto, Japan'",
                },
                "intent": {
                    "type": "string",
                    "enum": ["attractions", "geocode"],
                    "description": "'geocode' resolves one specific place to coordinates",
                    "default": "attractions",
                },
                "limit": {"type": "integer", "default": 8, "minimum": 1, "maximum": 20},
            },
            "required": ["query"],
        },
    ),
    ToolSpec(
        name="transport_lookup",
        description=(
            "Search flights between two locations. Use mode='flight' with IATA "
            "airport/city codes (SFO, JFK, NRT). mode='train' is accepted for honest "
            "degradation only: train data is currently unavailable, so never invent "
            "a schedule."
        ),
        parameters={
            "type": "object",
            "properties": {
                "origin": {
                    "type": "string",
                    "description": "IATA code for flights, station/city name for trains",
                },
                "destination": {
                    "type": "string",
                    "description": "IATA code for flights, station/city name for trains",
                },
                "departure_date": {
                    "type": "string",
                    "format": "date",
                    "description": "YYYY-MM-DD",
                },
                "mode": {
                    "type": "string",
                    "enum": ["flight", "train"],
                    "default": "flight",
                },
                "return_date": {
                    "type": "string",
                    "format": "date",
                    "description": "YYYY-MM-DD for a round trip; omit for one-way",
                },
                "passengers": {"type": "integer", "default": 1, "minimum": 1, "maximum": 9},
                "cabin_class": {
                    "type": "string",
                    "enum": ["economy", "premium_economy", "business", "first"],
                    "default": "economy",
                },
            },
            "required": ["origin", "destination", "departure_date"],
        },
    ),
    ToolSpec(
        name="hotel_lookup",
        description=(
            "Find hotels with live nightly rates for a date range. Requires a "
            "two-letter country code alongside the city."
        ),
        parameters={
            "type": "object",
            "properties": {
                "city": {"type": "string", "description": "City name, e.g. 'Kyoto'"},
                "country_code": {
                    "type": "string",
                    "description": "ISO 3166-1 alpha-2, e.g. 'JP'",
                    "minLength": 2,
                    "maxLength": 2,
                },
                "checkin": {"type": "string", "format": "date"},
                "checkout": {"type": "string", "format": "date"},
                "adults": {"type": "integer", "default": 2, "minimum": 1, "maximum": 8},
                "currency": {"type": "string", "default": "USD"},
                "max_results": {"type": "integer", "default": 6, "minimum": 1, "maximum": 10},
            },
            "required": ["city", "country_code", "checkin", "checkout"],
        },
    ),
    ToolSpec(
        name="restaurant_lookup",
        description="Find restaurants, cafes, bars, or food markets near a location.",
        parameters={
            "type": "object",
            "properties": {
                "near": {
                    "type": "string",
                    "description": "City or area, e.g. 'Kyoto, Japan'",
                },
                "query": {
                    "type": "string",
                    "description": "Cuisine or venue type, e.g. 'ramen', 'vegetarian'",
                    "default": "restaurant",
                },
                "limit": {"type": "integer", "default": 10, "minimum": 1, "maximum": 25},
                "latitude": {"type": "number", "description": "Optional, more precise than 'near'"},
                "longitude": {"type": "number", "description": "Optional, more precise than 'near'"},
            },
            "required": ["near"],
        },
    ),
    ToolSpec(
        name="weather_lookup",
        description=(
            "Current conditions and 5-day forecast for a city. Dates beyond 5 days "
            "return no forecast — do not invent one."
        ),
        parameters={
            "type": "object",
            "properties": {
                "city": {"type": "string"},
                "start_date": {"type": "string", "format": "date"},
                "end_date": {"type": "string", "format": "date"},
            },
            "required": ["city"],
        },
    ),
    ToolSpec(
        name="maps_route",
        description=(
            "Travel time and distance between two places. Supports DRIVE, WALK, and "
            "BICYCLE. Public transit is NOT available. Routes include map-ready GeoJSON. "
            "For detailed navigation, request include_steps; for route choice, request "
            "alternatives or avoid_features."
        ),
        parameters={
            "type": "object",
            "properties": {
                "origin": {"type": "string", "description": "Place name or address"},
                "destination": {"type": "string", "description": "Place name or address"},
                "mode": {
                    "type": "string",
                    "enum": ["DRIVE", "WALK", "BICYCLE"],
                    "default": "DRIVE",
                },
                "include_steps": {
                    "type": "boolean",
                    "default": False,
                    "description": "Include turn-by-turn route steps when available",
                },
                "alternatives": {
                    "type": "boolean",
                    "default": False,
                    "description": "Request up to two alternative routes when available",
                },
                "avoid_features": {
                    "type": "array",
                    "items": {
                        "type": "string",
                        "enum": ["highways", "tollways", "ferries", "fords", "steps"],
                    },
                    "description": "Road features to avoid when supported",
                },
                "extra_info": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Optional route metadata such as steepness or waytype",
                },
            },
            "required": ["origin", "destination"],
        },
    ),
    ToolSpec(
        name="knowledge_lookup",
        description=(
            "Search curated travel guides and FAQs for local customs, visa notes, "
            "transit passes, etiquette, and destination background. Prefer this over "
            "guessing; results carry source references."
        ),
        parameters={
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "destination": {
                    "type": "string",
                    "description": "Narrow results to one destination",
                },
                "limit": {"type": "integer", "default": 5, "minimum": 1, "maximum": 10},
            },
            "required": ["query"],
        },
    ),
    ToolSpec(
        name="web_search",
        description=(
            "Search the live web for anything the other tools don't cover: current "
            "events, festival dates, visa rules, opening hours, prices, closures, or "
            "recent changes. Use depth='deep' for open-ended questions needing a "
            "synthesized answer, depth='quick' for a specific fact or official link. "
            "Results include source URLs — cite them."
        ),
        parameters={
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "The search query"},
                "depth": {
                    "type": "string",
                    "enum": ["quick", "deep"],
                    "default": "quick",
                    "description": "'deep' returns a synthesized answer with sources",
                },
                "limit": {"type": "integer", "default": 6, "minimum": 1, "maximum": 10},
                "location": {
                    "type": "string",
                    "description": "Bias results to a locality, e.g. 'Kyoto, Japan'",
                },
            },
            "required": ["query"],
        },
    ),
]

HANDLERS: dict[str, Handler] = {
    "travel_search": travel_search,
    "transport_lookup": transport_lookup,
    "hotel_lookup": hotel_lookup,
    "restaurant_lookup": restaurant_lookup,
    "weather_lookup": weather_lookup,
    "maps_route": maps_route,
    "knowledge_lookup": knowledge_lookup,
    "web_search": web_search,
}

# Reachable by the backend but not exposed to the orchestrator — keeps the tool
# count inside the accuracy budget while leaving them callable from plan code.
INTERNAL_HANDLERS: dict[str, Handler] = {
    "flight_status": flight_status,
    "hotel_search_static": hotel_search_static,
    "places_nearby": places_nearby,
    "geocode": geocode,
    "maps_lookup": maps_lookup,
}


async def dispatch(name: str, arguments: dict[str, Any]) -> ToolResult:
    """Run a tool by name. Never raises — argument and runtime errors come back as
    `ToolResult` failures so the agent loop can report them to the model and continue."""
    handler = HANDLERS.get(name) or INTERNAL_HANDLERS.get(name)
    if handler is None:
        return ToolResult.failure(name, f"Unknown tool {name!r}")

    args = dict(arguments or {})
    args.pop("__parse_error__", None)

    # Drop unexpected keys rather than TypeError-ing; models occasionally invent one.
    sig = inspect.signature(handler)
    accepts_kwargs = any(
        p.kind is inspect.Parameter.VAR_KEYWORD for p in sig.parameters.values()
    )
    if not accepts_kwargs:
        unknown = set(args) - set(sig.parameters)
        if unknown:
            logger.info("tool.dropped_args tool=%s args=%s", name, sorted(unknown))
            args = {k: v for k, v in args.items() if k in sig.parameters}

    try:
        bound = sig.bind(**args)
    except TypeError as exc:
        return ToolResult.failure(name, f"Invalid arguments for {name}: {exc}")

    try:
        return await handler(*bound.args, **bound.kwargs)
    except Exception as exc:
        logger.exception("tool.handler_error tool=%s", name)
        return ToolResult.failure(name, f"{name} failed: {exc!r}"[:300])


def tool_specs_for_orchestrator() -> list[ToolSpec]:
    return list(TOOL_SPECS)
