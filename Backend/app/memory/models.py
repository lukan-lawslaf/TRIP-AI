"""Trip state and conversation models (§6).

`TripState` is the structured session object — the thing the orchestrator actually reads
each turn, in place of a growing raw transcript. It separates **confirmed** from
**tentative** plan items, because "we're definitely flying on the 20th" and "maybe Kyoto,
maybe Osaka" must not be conflated when the model reasons about what's still open.

`merge()` is deliberately conservative: the `memory` role returns a partial state each
turn, and a field absent from that partial means "unchanged", not "cleared". Without
that rule a model that forgets to echo the budget silently wipes it.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class ItemStatus(str, Enum):
    TENTATIVE = "tentative"
    CONFIRMED = "confirmed"
    REJECTED = "rejected"


class Destination(BaseModel):
    city: str
    country: str | None = None
    country_code: str | None = None
    arrival_date: str | None = None
    departure_date: str | None = None
    nights: int | None = None
    latitude: float | None = None
    longitude: float | None = None


class PlanItem(BaseModel):
    """One concrete thing in the itinerary — a flight, hotel, meal, activity."""

    kind: Literal["flight", "train", "hotel", "restaurant", "activity", "transfer", "note"]
    title: str
    status: ItemStatus = ItemStatus.TENTATIVE
    day: int | None = None
    date: str | None = None
    start_time: str | None = None
    end_time: str | None = None
    location: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    price_amount: float | None = None
    price_currency: str | None = None
    booking_ref: str | None = None
    notes: str | None = None
    # Provenance: which tool or guide produced this (§5 traceability).
    source: str | None = None
    source_refs: list[str] = Field(default_factory=list)


class Preferences(BaseModel):
    pace: str | None = None                      # relaxed / moderate / packed
    interests: list[str] = Field(default_factory=list)
    dietary: list[str] = Field(default_factory=list)
    accessibility: list[str] = Field(default_factory=list)
    accommodation_style: str | None = None
    avoid: list[str] = Field(default_factory=list)
    language: str | None = None                  # user's language, for replies


class TripState(BaseModel):
    """The rolling structured summary the orchestrator sees each turn."""

    origin: str | None = None
    destinations: list[Destination] = Field(default_factory=list)
    start_date: str | None = None
    end_date: str | None = None
    duration_nights: int | None = None
    party_size: int | None = None
    party_composition: str | None = None          # "2 adults, 1 child (7)"
    budget_total: float | None = None
    budget_currency: str | None = None
    budget_level: str | None = None               # budget / mid-range / luxury
    preferences: Preferences = Field(default_factory=Preferences)
    plan_items: list[PlanItem] = Field(default_factory=list)
    open_questions: list[str] = Field(default_factory=list)
    summary: str | None = None
    # Latest backend route as MapLibre-ready GeoJSON. Kept out of the LLM compact
    # context because coordinates are for the frontend renderer, not model reasoning.
    route: dict[str, Any] | None = None
    updated_at: str = Field(default_factory=_now)

    # -- derived views ---------------------------------------------------

    @property
    def confirmed_items(self) -> list[PlanItem]:
        return [i for i in self.plan_items if i.status is ItemStatus.CONFIRMED]

    @property
    def tentative_items(self) -> list[PlanItem]:
        return [i for i in self.plan_items if i.status is ItemStatus.TENTATIVE]

    @property
    def primary_destination(self) -> Destination | None:
        return self.destinations[0] if self.destinations else None

    def is_plannable(self) -> tuple[bool, list[str]]:
        """Whether there's enough to attempt a full itinerary, and what's missing."""
        missing: list[str] = []
        if not self.destinations:
            missing.append("destination")
        if not self.start_date and not self.duration_nights:
            missing.append("travel dates or trip length")
        if not self.party_size:
            missing.append("number of travellers")
        return (not missing, missing)

    def merge(self, partial: dict[str, Any]) -> "TripState":
        """Fold a partial update from the `memory` role into a new state.

        Absent field == unchanged. Explicit null == unchanged too: models emit nulls
        for fields they simply didn't discuss, and treating that as a deletion loses
        information the user already gave us.
        """
        data = self.model_dump()

        for key, value in (partial or {}).items():
            if key in {"plan_items", "preferences", "updated_at"} or value is None:
                continue
            if key in data:
                # Don't let an empty list clobber a populated one.
                if isinstance(value, list) and not value:
                    continue
                data[key] = value

        prefs = (partial or {}).get("preferences")
        if isinstance(prefs, dict):
            merged_prefs = data.get("preferences") or {}
            for key, value in prefs.items():
                if value is None:
                    continue
                if isinstance(value, list):
                    if not value:
                        continue
                    # Union, preserving order — interests accumulate across turns.
                    existing = merged_prefs.get(key) or []
                    seen = {str(x).lower() for x in existing}
                    merged_prefs[key] = existing + [
                        v for v in value if str(v).lower() not in seen
                    ]
                else:
                    merged_prefs[key] = value
            data["preferences"] = merged_prefs

        items = (partial or {}).get("plan_items")
        if isinstance(items, list) and items:
            data["plan_items"] = _merge_items(data.get("plan_items") or [], items)

        data["updated_at"] = _now()
        return TripState.model_validate(data)

    def compact(self) -> dict[str, Any]:
        """Token-lean view for the orchestrator prompt. Drops nulls and empties."""
        raw = self.model_dump(exclude_none=True)
        raw.pop("updated_at", None)
        raw.pop("route", None)
        prefs = {k: v for k, v in (raw.get("preferences") or {}).items() if v}
        if prefs:
            raw["preferences"] = prefs
        else:
            raw.pop("preferences", None)
        items = raw.get("plan_items") or []
        if items:
            raw["plan_items"] = [
                {k: v for k, v in i.items() if v not in (None, [], "")} for i in items
            ]
        else:
            raw.pop("plan_items", None)
        return {k: v for k, v in raw.items() if v not in (None, [], {}, "")}


def _merge_items(
    existing: list[dict[str, Any]], incoming: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Upsert plan items keyed by (kind, day, normalized title)."""

    def key(item: dict[str, Any]) -> tuple:
        return (
            item.get("kind"),
            item.get("day"),
            str(item.get("title") or "").strip().lower(),
        )

    merged = {key(i): dict(i) for i in existing}
    for item in incoming:
        if not isinstance(item, dict) or not item.get("title"):
            continue
        k = key(item)
        if k in merged:
            merged[k].update({kk: vv for kk, vv in item.items() if vv is not None})
        else:
            merged[k] = dict(item)
    return list(merged.values())


class TurnRole(str, Enum):
    USER = "user"
    ASSISTANT = "assistant"


class ConversationTurn(BaseModel):
    role: TurnRole
    content: str
    created_at: str = Field(default_factory=_now)
    media_count: int = 0
    tools_used: list[str] = Field(default_factory=list)
    served_by: str | None = None
