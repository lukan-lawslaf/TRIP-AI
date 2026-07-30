"""Web search — Serper (SERP) + Tavily (synthesized answer).

The two providers answer genuinely different questions, so `web_search` takes a `depth`
argument rather than treating one as a fallback for the other:

  depth="quick"  → Serper. Google-style organic results: title/link/snippet, plus
                   answerBox/knowledgeGraph when Google has one. Best for "what's the
                   official site", "is X open in 2026", current prices, news.
  depth="deep"   → Tavily. Returns a synthesized `answer` with supporting sources.
                   Best for open questions — etiquette, visa rules, "what should I know
                   before visiting X" — where reading five snippets is the alternative.

Both are exposed to the orchestrator through one tool (§4.2 caps the tool count), and
both attach source URLs so any claim in an itinerary stays traceable (§5).

If the requested provider is unconfigured or down, the other one serves the request —
degraded but useful, and the response says which provider actually answered.
"""

from __future__ import annotations

import logging
from typing import Any

from app.config import get_settings
from app.tools.base import ToolResult, fetch_json, secret

logger = logging.getLogger(__name__)

SERPER_BASE = "https://google.serper.dev"
TAVILY_URL = "https://api.tavily.com/search"

# Web results go stale faster than place metadata but not within a session.
_TTL = 60 * 60 * 6


async def web_search(
    query: str,
    *,
    depth: str = "quick",
    limit: int = 6,
    location: str | None = None,
) -> ToolResult:
    """Search the live web. `depth='deep'` returns a synthesized answer with sources."""
    if depth == "deep":
        primary, secondary = _tavily, _serper
    else:
        primary, secondary = _serper, _tavily

    result = await primary(query, limit=limit, location=location)
    if result.ok:
        return result

    logger.info("web_search.fallback from=%s reason=%s", result.source, result.status)
    fallback = await secondary(query, limit=limit, location=location)
    if fallback.ok:
        fallback.meta["degraded_from"] = result.source
        return fallback
    # Report the failure the caller asked for, not the backup's.
    return result


async def _serper(
    query: str, *, limit: int = 6, location: str | None = None
) -> ToolResult:
    key = secret("web_search_api_key")
    if not key:
        return ToolResult.missing_key("serper", "WEB_SEARCH_API_KEY")

    body: dict[str, Any] = {"q": query, "num": min(limit, 10)}
    if location:
        body["location"] = location

    result = await fetch_json(
        "serper",
        "POST",
        f"{SERPER_BASE}/search",
        headers={"X-API-KEY": key, "Content-Type": "application/json"},
        json_body=body,
        cache_ttl=_TTL,
        cache_namespace="serper",
    )
    if not result.ok:
        return result

    payload = result.data or {}
    results = [
        {
            "title": r.get("title"),
            "url": r.get("link"),
            "snippet": r.get("snippet"),
        }
        for r in (payload.get("organic") or [])[:limit]
    ]

    data: dict[str, Any] = {
        "query": query,
        "provider": "serper",
        "results": results,
        "sources": [r["url"] for r in results if r.get("url")],
    }

    # Google's direct answer, when it has one, is usually the whole answer.
    answer_box = payload.get("answerBox") or {}
    if answer_box:
        data["answer"] = (
            answer_box.get("answer")
            or answer_box.get("snippet")
            or answer_box.get("title")
        )
    kg = payload.get("knowledgeGraph") or {}
    if kg:
        data["knowledge_graph"] = {
            "title": kg.get("title"),
            "type": kg.get("type"),
            "description": kg.get("description"),
            "website": kg.get("website"),
        }
    if payload.get("peopleAlsoAsk"):
        data["related_questions"] = [
            q.get("question") for q in payload["peopleAlsoAsk"][:4] if q.get("question")
        ]

    return ToolResult(source="serper", data=data, cached=result.cached)


async def _tavily(
    query: str, *, limit: int = 6, location: str | None = None
) -> ToolResult:
    key = secret("web2_search_api_key")
    if not key:
        return ToolResult.missing_key("tavily", "WEB2_SEARCH_API_KEY")

    scoped = f"{query} {location}" if location else query
    result = await fetch_json(
        "tavily",
        "POST",
        TAVILY_URL,
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        json_body={
            "query": scoped,
            "max_results": min(limit, 10),
            "include_answer": "advanced",
            "search_depth": "basic",
        },
        cache_ttl=_TTL,
        cache_namespace="tavily",
        timeout=30.0,  # synthesis is slower than a SERP fetch
    )
    if not result.ok:
        return result

    payload = result.data or {}
    results = [
        {
            "title": r.get("title"),
            "url": r.get("url"),
            # `content` is Tavily's extracted passage; trim so a handful of results
            # can't dominate the orchestrator's context window.
            "snippet": (r.get("content") or "")[:600],
            "relevance": r.get("score"),
        }
        for r in (payload.get("results") or [])[:limit]
    ]

    return ToolResult(
        source="tavily",
        data={
            "query": query,
            "provider": "tavily",
            "answer": payload.get("answer"),
            "results": results,
            "sources": [r["url"] for r in results if r.get("url")],
        },
        cached=result.cached,
    )


async def maps_lookup(query: str, *, location: str | None = None) -> ToolResult:
    """Google-Maps-style place lookup via Serper's /places endpoint.

    Complements `travel_search`: this reflects Google Maps listings (ratings, price
    band, cid) rather than the Places API. Note it geo-biases to the caller unless
    `location` is given — "ramen in Kyoto" without it returned Florida results during
    verification, so the locality is appended to the query rather than trusted to
    the endpoint's own inference.
    """
    key = secret("web_search_api_key")
    if not key:
        return ToolResult.missing_key("serper", "WEB_SEARCH_API_KEY")

    body: dict[str, Any] = {"q": f"{query} {location}".strip() if location else query}
    if location:
        body["location"] = location

    result = await fetch_json(
        "serper",
        "POST",
        f"{SERPER_BASE}/places",
        headers={"X-API-KEY": key, "Content-Type": "application/json"},
        json_body=body,
        cache_ttl=get_settings().cache_ttl_places,
        cache_namespace="serper_places",
    )
    if not result.ok:
        return result

    places = [
        {
            "name": p.get("title"),
            "address": p.get("address"),
            "latitude": p.get("latitude"),
            "longitude": p.get("longitude"),
            "rating": p.get("rating"),
            "rating_count": p.get("ratingCount"),
            "price_level": p.get("priceLevel"),
            "category": p.get("category"),
            "website": p.get("website"),
        }
        for p in (result.data or {}).get("places") or []
    ]
    return ToolResult(
        source="serper",
        data={"query": query, "location": location, "places": places},
        cached=result.cached,
    )
