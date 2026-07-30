"""Train lookup degradation path.

Both rail providers are intentionally disabled for this project.  Navitia has no
registered token and the RapidAPI IRCTC host is not subscribed; the application must
not make network calls, chase credentials, or invent schedules to compensate.
"""

from __future__ import annotations

from app.tools.base import ToolResult

_UNAVAILABLE_NOTE = (
    "Train data is not available right now. Check the official railway operator site "
    "for current schedules and fares."
)


async def train_lookup(
    origin: str,
    destination: str,
    departure_date: str,
    *,
    region: str = "auto",
    origin_coords: tuple[float, float] | None = None,
    destination_coords: tuple[float, float] | None = None,
) -> ToolResult:
    """Return a static, honest unavailable response; never contact a rail provider."""
    return ToolResult(
        source="trains",
        status="unavailable",
        error=_UNAVAILABLE_NOTE,
        meta={
            "origin": origin,
            "destination": destination,
            "date": departure_date,
            "region": region,
            "provider_calls": 0,
            "note": "Navitia and RapidAPI IRCTC are intentionally disabled.",
        },
    )
