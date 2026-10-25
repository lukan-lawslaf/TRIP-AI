import asyncio

import httpx
import pytest
from fastapi import FastAPI, HTTPException

from app.api import routes


@pytest.mark.asyncio
async def test_planning_job_can_be_polled_without_repeating_generation(monkeypatch):
    app = FastAPI()
    app.include_router(routes.router)
    ready = asyncio.Event()
    calls = []

    async def exists(session_id):
        return session_id == "test-session"

    async def generate(session_id, text, **kwargs):
        calls.append(text)
        await ready.wait()
        return routes.AgentResponse(session_id=session_id, message="Kyoto itinerary", trip_state={})

    monkeypatch.setattr(routes.db, "session_exists", exists)
    monkeypatch.setattr(routes, "_run_agent_or_http_error", generate)
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            started = await client.post("/session/test-session/message/start", json={"text": "Kyoto"})
            assert started.status_code == 202
            path = f"/session/test-session/message/status/{started.json()['job_id']}"
            assert (await client.get(path)).json() == {"status": "pending"}
            assert (await client.get(path.replace("test-session", "other-session"))).status_code == 404
            ready.set()
            await asyncio.sleep(0)
            result = (await client.get(path)).json()
            assert result["result"]["message"] == "Kyoto itinerary"
            assert (await client.get(path)).json() == result
            assert calls == ["Kyoto"]
            assert (await client.post("/session/missing/message/start", json={"text": "Kyoto"})).status_code == 404
    finally:
        await routes.close_message_jobs()


@pytest.mark.asyncio
async def test_failed_job_returns_a_terminal_error():
    async def fail():
        raise HTTPException(503, "Assistant unavailable")

    task = asyncio.create_task(fail())
    await asyncio.sleep(0)
    routes._message_jobs["failed"] = routes._MessageJob("session", task)
    try:
        assert await routes.message_status("session", "failed") == {
            "status": "failed", "message": "Assistant unavailable",
        }
    finally:
        await routes.close_message_jobs()
