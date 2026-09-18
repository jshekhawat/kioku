"""FastAPI application entrypoint."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app import deps
from app.api.routes import router

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    await deps.startup()
    logger.info("kioku api ready")
    try:
        yield
    finally:
        await deps.shutdown()


app = FastAPI(
    title="kioku",
    version="0.1.0",
    description="Locally hosted long-term memory for AI agents.",
    lifespan=lifespan,
)
app.include_router(router)


@app.get("/", tags=["system"])
async def root() -> dict[str, str]:
    return {"name": "kioku", "docs": "/docs", "health": "/v1/health"}
