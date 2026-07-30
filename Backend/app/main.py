"""TripAI FastAPI application."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import router
from app.config import get_settings
from app.storage import db
from app.tools.base import close_http_client
from app.llm.router import close_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    logging.basicConfig(level=getattr(logging, settings.log_level.upper(), logging.INFO))
    await db.init_db()
    try:
        yield
    finally:
        await close_router()
        await close_http_client()


app = FastAPI(
    title="TripAI Backend",
    version="0.1.0",
    description="Model-agnostic AI travel planner backend.",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router)
