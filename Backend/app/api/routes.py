"""FastAPI HTTP surface for sessions and the orchestrator."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel, Field
from starlette.datastructures import UploadFile

from app.agent.orchestrator import AgentTurn, run_turn
from app.config import get_settings
from app.llm.router import get_router
from app.llm.types import MediaPart
from app.memory.models import TripState
from app.storage import db

logger = logging.getLogger(__name__)

router = APIRouter()


class CreateSessionRequest(BaseModel):
    user_id: str | None = Field(default=None, max_length=200)
    title: str | None = Field(default=None, max_length=200)


class CreateSessionResponse(BaseModel):
    session_id: str


class JsonMessageRequest(BaseModel):
    text: str = Field(min_length=1, max_length=50_000)
    user_id: str | None = Field(default=None, max_length=200)


class PlanRequest(BaseModel):
    focus: str | None = Field(default=None, max_length=2_000)


class AgentResponse(BaseModel):
    session_id: str
    message: str
    trip_state: dict[str, Any]
    served_by: str | None = None
    tools_used: list[str] = Field(default_factory=list)
    rounds: int = 0


def _state_payload(state: TripState) -> dict[str, Any]:
    return state.model_dump(mode="json", exclude_none=True)


def _agent_payload(result: AgentTurn) -> AgentResponse:
    return AgentResponse(
        session_id=result.session_id,
        message=result.text,
        trip_state=_state_payload(result.state),
        served_by=result.served_by,
        tools_used=list(
            dict.fromkeys(item.source for item in result.tool_results)
        ),
        rounds=result.rounds,
    )


async def _read_uploads(files: list[UploadFile]) -> list[MediaPart]:
    settings = get_settings()
    if len(files) > settings.max_uploads_per_message:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"At most {settings.max_uploads_per_message} files may be attached.",
        )

    media: list[MediaPart] = []
    for upload in files:
        mime_type = (upload.content_type or "").lower()
        if not (mime_type.startswith("image/") or mime_type.startswith("video/")):
            raise HTTPException(
                status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
                detail=f"Unsupported attachment type: {mime_type or 'unknown'}.",
            )
        chunks: list[bytes] = []
        total = 0
        while True:
            chunk = await upload.read(1024 * 1024)
            if not chunk:
                break
            total += len(chunk)
            if total > settings.max_upload_bytes:
                raise HTTPException(
                    status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                    detail=f"Each attachment must be at most {settings.max_upload_bytes} bytes.",
                )
            chunks.append(chunk)
        media.append(MediaPart(mime_type=mime_type, data=b"".join(chunks)))
        await upload.close()
    return media


async def _parse_message_request(request: Request) -> tuple[str, str | None, list[MediaPart]]:
    content_type = request.headers.get("content-type", "").lower()
    if content_type.startswith("multipart/form-data"):
        form = await request.form()
        text = str(form.get("text") or "").strip()
        user_id_value = form.get("user_id")
        user_id = str(user_id_value).strip() if user_id_value else None
        files = [
            value
            for value in form.getlist("files")
            if isinstance(value, UploadFile)
        ]
        media = await _read_uploads(files)
    else:
        try:
            payload = JsonMessageRequest.model_validate(await request.json())
        except Exception as exc:
            raise HTTPException(status_code=400, detail=f"Invalid message body: {exc}") from exc
        text = payload.text.strip()
        user_id = payload.user_id
        media = []

    if not text:
        raise HTTPException(status_code=422, detail="Message text must not be empty.")
    return text, user_id, media


async def _run_agent_or_http_error(
    session_id: str,
    text: str,
    *,
    user_id: str | None = None,
    media: list[MediaPart] | None = None,
) -> AgentResponse:
    try:
        result = await run_turn(
            session_id,
            text,
            user_id=user_id,
            media=media,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        # Do not expose provider payloads or API keys through the HTTP surface.
        logger.exception("api.agent_failed session=%s", session_id)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="The travel assistant is temporarily unavailable. Please try again.",
        ) from exc
    return _agent_payload(result)


@router.post("/session", response_model=CreateSessionResponse, status_code=201)
async def create_session(payload: CreateSessionRequest | None = None) -> CreateSessionResponse:
    session_id = await db.create_session(
        user_id=payload.user_id if payload else None,
        title=payload.title if payload else None,
    )
    return CreateSessionResponse(session_id=session_id)


@router.post("/session/{session_id}/message", response_model=AgentResponse)
async def send_message(session_id: str, request: Request) -> AgentResponse:
    text, user_id, media = await _parse_message_request(request)
    return await _run_agent_or_http_error(
        session_id,
        text,
        user_id=user_id,
        media=media,
    )


@router.get("/session/{session_id}/state")
async def get_state(session_id: str) -> dict[str, Any]:
    state = await db.get_trip_state(session_id)
    if state is None:
        raise HTTPException(status_code=404, detail="Session not found.")
    return {"session_id": session_id, "trip_state": _state_payload(state)}


@router.post("/session/{session_id}/plan", response_model=AgentResponse)
async def generate_plan(session_id: str, payload: PlanRequest | None = None) -> AgentResponse:
    prompt = "Create the best possible travel plan from the confirmed trip details."
    if payload and payload.focus:
        prompt += f" Pay special attention to: {payload.focus}"
    return await _run_agent_or_http_error(session_id, prompt)


@router.get("/health")
async def health() -> dict[str, str]:
    try:
        await db.init_db()
    except Exception as exc:
        logger.exception("api.health_failed")
        raise HTTPException(status_code=503, detail="Storage is unavailable.") from exc
    return {"status": "ok", "service": get_settings().app_name}


@router.get("/health/models")
async def model_health() -> dict[str, Any]:
    return {"status": "ok", "roles": get_router().health()}
