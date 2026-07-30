"""SQLite persistence for sessions, turns, and trip state (§6).

SQLite keeps the project runnable with zero external services. The schema is plain
enough to port to Postgres later: swap the driver and the `?` placeholders, and add the
pgvector table if the RAG store moves off Chroma.

`aiosqlite` isn't a dependency — writes are short and infrequent (one per turn), so they
run in a thread via `asyncio.to_thread` rather than pulling in another async driver.

Long-term memory (§6): trip state is stored per user *and* per session, so a returning
user's prior trips can be recovered by `user_id` across sessions.
"""

from __future__ import annotations

import asyncio
import json
import logging
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.config import get_settings
from app.memory.models import ConversationTurn, TripState, TurnRole

logger = logging.getLogger(__name__)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    id            TEXT PRIMARY KEY,
    user_id       TEXT,
    title         TEXT,
    created_at    TEXT NOT NULL,
    updated_at    TEXT NOT NULL,
    trip_state    TEXT NOT NULL,
    turn_count    INTEGER NOT NULL DEFAULT 0,
    summary       TEXT
);
CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions(user_id, updated_at DESC);

CREATE TABLE IF NOT EXISTS turns (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id    TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    role          TEXT NOT NULL,
    content       TEXT NOT NULL,
    created_at    TEXT NOT NULL,
    media_count   INTEGER NOT NULL DEFAULT 0,
    tools_used    TEXT,
    served_by     TEXT
);
CREATE INDEX IF NOT EXISTS idx_turns_session ON turns(session_id, id);

CREATE TABLE IF NOT EXISTS itineraries (
    id            TEXT PRIMARY KEY,
    session_id    TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    created_at    TEXT NOT NULL,
    payload       TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_itineraries_session ON itineraries(session_id, created_at DESC);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _db_path() -> Path:
    url = get_settings().database_url
    if url.startswith("sqlite:///"):
        return Path(url.replace("sqlite:///", "", 1))
    raise ValueError(
        f"Only sqlite:// URLs are supported by this storage layer; got {url!r}. "
        "Port storage/db.py to asyncpg to use Postgres."
    )


def _connect() -> sqlite3.Connection:
    path = _db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=15.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    # WAL lets reads proceed during a write — the API is read-heavy per turn.
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


def _init_sync() -> None:
    with _connect() as conn:
        conn.executescript(_SCHEMA)


_initialized = False


async def init_db() -> None:
    global _initialized
    if _initialized:
        return
    await asyncio.to_thread(_init_sync)
    _initialized = True
    logger.info("storage.ready path=%s", _db_path())


# --- sessions ---------------------------------------------------------------


def _create_session_sync(user_id: str | None, title: str | None) -> str:
    session_id = uuid.uuid4().hex
    now = _now()
    with _connect() as conn:
        conn.execute(
            "INSERT INTO sessions (id, user_id, title, created_at, updated_at, "
            "trip_state, turn_count) VALUES (?, ?, ?, ?, ?, ?, 0)",
            (
                session_id,
                user_id,
                title,
                now,
                now,
                TripState().model_dump_json(),
            ),
        )
    return session_id


async def create_session(
    user_id: str | None = None, title: str | None = None
) -> str:
    await init_db()
    return await asyncio.to_thread(_create_session_sync, user_id, title)


def _get_session_sync(session_id: str) -> dict[str, Any] | None:
    with _connect() as conn:
        row = conn.execute(
            "SELECT * FROM sessions WHERE id = ?", (session_id,)
        ).fetchone()
    return dict(row) if row else None


async def get_session(session_id: str) -> dict[str, Any] | None:
    await init_db()
    return await asyncio.to_thread(_get_session_sync, session_id)


async def session_exists(session_id: str) -> bool:
    return await get_session(session_id) is not None


# --- trip state -------------------------------------------------------------


def _get_state_sync(session_id: str) -> TripState | None:
    with _connect() as conn:
        row = conn.execute(
            "SELECT trip_state FROM sessions WHERE id = ?", (session_id,)
        ).fetchone()
    if row is None:
        return None
    try:
        return TripState.model_validate_json(row["trip_state"])
    except Exception:
        # A malformed blob shouldn't brick the session; start clean and log it.
        logger.exception("storage.bad_trip_state session=%s", session_id)
        return TripState()


async def get_trip_state(session_id: str) -> TripState | None:
    await init_db()
    return await asyncio.to_thread(_get_state_sync, session_id)


def _save_state_sync(session_id: str, state: TripState) -> None:
    with _connect() as conn:
        conn.execute(
            "UPDATE sessions SET trip_state = ?, summary = ?, updated_at = ? WHERE id = ?",
            (state.model_dump_json(), state.summary, _now(), session_id),
        )


async def save_trip_state(session_id: str, state: TripState) -> None:
    await init_db()
    await asyncio.to_thread(_save_state_sync, session_id, state)


# --- turns ------------------------------------------------------------------


def _add_turn_sync(session_id: str, turn: ConversationTurn) -> None:
    with _connect() as conn:
        conn.execute(
            "INSERT INTO turns (session_id, role, content, created_at, media_count, "
            "tools_used, served_by) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                session_id,
                turn.role.value,
                turn.content,
                turn.created_at,
                turn.media_count,
                json.dumps(turn.tools_used),
                turn.served_by,
            ),
        )
        conn.execute(
            "UPDATE sessions SET turn_count = turn_count + 1, updated_at = ? WHERE id = ?",
            (_now(), session_id),
        )


async def add_turn(session_id: str, turn: ConversationTurn) -> None:
    await init_db()
    await asyncio.to_thread(_add_turn_sync, session_id, turn)


def _get_turns_sync(session_id: str, limit: int | None) -> list[ConversationTurn]:
    with _connect() as conn:
        if limit:
            # Newest N, then flip back to chronological for the prompt.
            rows = conn.execute(
                "SELECT * FROM (SELECT * FROM turns WHERE session_id = ? "
                "ORDER BY id DESC LIMIT ?) ORDER BY id ASC",
                (session_id, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM turns WHERE session_id = ? ORDER BY id ASC",
                (session_id,),
            ).fetchall()

    turns = []
    for r in rows:
        try:
            tools = json.loads(r["tools_used"] or "[]")
        except (json.JSONDecodeError, TypeError):
            tools = []
        turns.append(
            ConversationTurn(
                role=TurnRole(r["role"]),
                content=r["content"],
                created_at=r["created_at"],
                media_count=r["media_count"] or 0,
                tools_used=tools,
                served_by=r["served_by"],
            )
        )
    return turns


async def get_turns(
    session_id: str, limit: int | None = None
) -> list[ConversationTurn]:
    await init_db()
    return await asyncio.to_thread(_get_turns_sync, session_id, limit)


def _turn_count_sync(session_id: str) -> int:
    with _connect() as conn:
        row = conn.execute(
            "SELECT turn_count FROM sessions WHERE id = ?", (session_id,)
        ).fetchone()
    return int(row["turn_count"]) if row else 0


async def turn_count(session_id: str) -> int:
    await init_db()
    return await asyncio.to_thread(_turn_count_sync, session_id)


# --- itineraries ------------------------------------------------------------


def _save_itinerary_sync(session_id: str, payload: dict[str, Any]) -> str:
    itinerary_id = uuid.uuid4().hex
    with _connect() as conn:
        conn.execute(
            "INSERT INTO itineraries (id, session_id, created_at, payload) "
            "VALUES (?, ?, ?, ?)",
            (itinerary_id, session_id, _now(), json.dumps(payload, default=str)),
        )
    return itinerary_id


async def save_itinerary(session_id: str, payload: dict[str, Any]) -> str:
    await init_db()
    return await asyncio.to_thread(_save_itinerary_sync, session_id, payload)


def _latest_itinerary_sync(session_id: str) -> dict[str, Any] | None:
    with _connect() as conn:
        row = conn.execute(
            "SELECT payload FROM itineraries WHERE session_id = ? "
            "ORDER BY created_at DESC LIMIT 1",
            (session_id,),
        ).fetchone()
    if not row:
        return None
    try:
        return json.loads(row["payload"])
    except json.JSONDecodeError:
        return None


async def get_latest_itinerary(session_id: str) -> dict[str, Any] | None:
    await init_db()
    return await asyncio.to_thread(_latest_itinerary_sync, session_id)


# --- long-term memory (§6): prior trips for a returning user ---------------


def _user_sessions_sync(user_id: str, limit: int) -> list[dict[str, Any]]:
    with _connect() as conn:
        rows = conn.execute(
            "SELECT id, title, created_at, updated_at, summary FROM sessions "
            "WHERE user_id = ? ORDER BY updated_at DESC LIMIT ?",
            (user_id, limit),
        ).fetchall()
    return [dict(r) for r in rows]


async def get_user_sessions(user_id: str, limit: int = 5) -> list[dict[str, Any]]:
    await init_db()
    return await asyncio.to_thread(_user_sessions_sync, user_id, limit)
