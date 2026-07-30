"""Weather — OpenWeatherMap (§4.1).

Verified: the provisioned key works on the 2.5 endpoints. One Call 3.0 returns 401
("requires a separate subscription"), so it is deliberately not used. Forecast is
5-day/3-hour — dates beyond that window return `available: False` rather than a
fabricated outlook, because a made-up forecast is worse than no forecast.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from typing import Any

from app.config import get_settings
from app.tools.base import ToolResult, fetch_json, secret

logger = logging.getLogger(__name__)

BASE = "https://api.openweathermap.org/data/2.5"
FORECAST_HORIZON_DAYS = 5


async def weather_lookup(
    city: str,
    *,
    start_date: str | None = None,
    end_date: str | None = None,
    units: str = "metric",
) -> ToolResult:
    """Current conditions plus a per-day forecast for `city`.

    Returns whatever it can: if the trip is further out than the 5-day window, the
    caller still gets climate-free current conditions and an explicit note that the
    forecast doesn't reach those dates.
    """
    key = secret("weather_api_key")
    if not key:
        return ToolResult.missing_key("openweathermap", "WEATHER_API_KEY")

    settings = get_settings()
    ttl = settings.cache_ttl_weather

    current = await fetch_json(
        "openweathermap",
        "GET",
        f"{BASE}/weather",
        params={"q": city, "units": units, "appid": key},
        cache_ttl=ttl,
        cache_namespace="weather_current",
    )
    if not current.ok:
        return current

    forecast = await fetch_json(
        "openweathermap",
        "GET",
        f"{BASE}/forecast",
        params={"q": city, "units": units, "appid": key},
        cache_ttl=ttl,
        cache_namespace="weather_forecast",
    )

    cur = current.data or {}
    out: dict[str, Any] = {
        "city": cur.get("name") or city,
        "country": (cur.get("sys") or {}).get("country"),
        "units": units,
        "current": {
            "temp_c": (cur.get("main") or {}).get("temp"),
            "feels_like_c": (cur.get("main") or {}).get("feels_like"),
            "humidity_pct": (cur.get("main") or {}).get("humidity"),
            "conditions": (cur.get("weather") or [{}])[0].get("description"),
            "wind_speed": (cur.get("wind") or {}).get("speed"),
        },
        "daily": [],
        "forecast_horizon_days": FORECAST_HORIZON_DAYS,
    }

    if forecast.ok:
        out["daily"] = _daily_from_3h(
            (forecast.data or {}).get("list") or [], start_date, end_date
        )
    else:
        out["forecast_error"] = forecast.error

    # Be explicit when the trip is outside the forecastable window.
    if start_date:
        try:
            trip_start = date.fromisoformat(start_date)
            horizon = datetime.now(timezone.utc).date() + timedelta(
                days=FORECAST_HORIZON_DAYS
            )
            if trip_start > horizon:
                out["forecast_available"] = False
                out["note"] = (
                    f"Trip starts {start_date}, beyond the {FORECAST_HORIZON_DAYS}-day "
                    "forecast window. Only seasonal expectations can be discussed — "
                    "do not state a specific forecast for those dates."
                )
            else:
                out["forecast_available"] = bool(out["daily"])
        except ValueError:
            out["forecast_available"] = bool(out["daily"])
    else:
        out["forecast_available"] = bool(out["daily"])

    return ToolResult(source="openweathermap", data=out, cached=current.cached)


def _daily_from_3h(
    entries: list[dict[str, Any]], start_date: str | None, end_date: str | None
) -> list[dict[str, Any]]:
    """Collapse 3-hourly rows into per-day min/max + modal conditions."""
    buckets: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for e in entries:
        stamp = e.get("dt_txt") or ""
        if stamp:
            buckets[stamp.split(" ")[0]].append(e)

    days: list[dict[str, Any]] = []
    for day in sorted(buckets):
        if start_date and day < start_date:
            continue
        if end_date and day > end_date:
            continue
        rows = buckets[day]
        temps = [
            (r.get("main") or {}).get("temp")
            for r in rows
            if (r.get("main") or {}).get("temp") is not None
        ]
        conditions = [
            (r.get("weather") or [{}])[0].get("description") for r in rows
        ]
        conditions = [c for c in conditions if c]
        pops = [r.get("pop") or 0 for r in rows]
        days.append(
            {
                "date": day,
                "temp_min_c": round(min(temps), 1) if temps else None,
                "temp_max_c": round(max(temps), 1) if temps else None,
                "conditions": max(set(conditions), key=conditions.count)
                if conditions
                else None,
                "precipitation_chance_pct": round(max(pops) * 100) if pops else None,
            }
        )
    return days
