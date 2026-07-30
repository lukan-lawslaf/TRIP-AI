"""Small local seed corpus for the zero-service development path.

The corpus is intentionally modest and factual. It gives the RAG tool useful behavior
before a larger curated guide bundle is added, without introducing another API or
subscription into development.
"""

from __future__ import annotations

from typing import TypedDict


class GuideDocument(TypedDict):
    id: str
    title: str
    destination: str
    text: str
    source: str


DEFAULT_DOCUMENTS: list[GuideDocument] = [
    {
        "id": "japan-kyoto-pace",
        "title": "A gentle pace in Kyoto",
        "destination": "Kyoto, Japan",
        "text": (
            "Kyoto works well at a relaxed pace. Group nearby areas together: eastern "
            "Higashiyama and Gion can fill a morning and evening, while Arashiyama is "
            "best treated as a half day. Start popular temple walks early, keep one "
            "unplanned hour for a small cafe, and avoid stacking distant neighborhoods "
            "on the same day."
        ),
        "source": "tripai-curated-guide",
    },
    {
        "id": "japan-kyoto-etiquette",
        "title": "Temple and neighborhood etiquette in Kyoto",
        "destination": "Kyoto, Japan",
        "text": (
            "Keep voices low near temples and residential lanes, ask before taking a "
            "person's photograph, and do not block narrow streets for photos. Remove "
            "shoes where a sign asks you to, follow the marked walking direction at busy "
            "shrines, and carry small rubbish with you until you find a bin."
        ),
        "source": "tripai-curated-guide",
    },
    {
        "id": "japan-tokyo-food",
        "title": "Finding memorable food in Tokyo",
        "destination": "Tokyo, Japan",
        "text": (
            "For a food-focused Tokyo day, choose one neighborhood cluster rather than "
            "crossing the city for every meal. Tiny counters may have limited seating, "
            "cash-only payment, or a ticket machine. Department-store food halls are a "
            "reliable option for variety, while a local coffee shop is often easier to "
            "fit between major sights than a famous destination cafe."
        ),
        "source": "tripai-curated-guide",
    },
    {
        "id": "japan-autumn-layering",
        "title": "Packing for Japan in autumn",
        "destination": "Japan",
        "text": (
            "Autumn days can change from cool mornings to mild afternoons. Pack layers, "
            "comfortable walking shoes, and a light rain shell. Crowded scenic areas are "
            "usually calmer early in the day. Check the current weather forecast for the "
            "exact dates because a guide cannot replace live weather data."
        ),
        "source": "tripai-curated-guide",
    },
    {
        "id": "japan-first-day",
        "title": "A low-stress first day after arrival",
        "destination": "Japan",
        "text": (
            "After a long flight, keep the first day close to the hotel. Plan one easy "
            "walk, an early meal, and a flexible evening. Save reservations and the most "
            "crowded landmarks for a later day when everyone has recovered."
        ),
        "source": "tripai-curated-guide",
    },
]
