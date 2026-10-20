from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from src.api.routes.applications import router as applications_router
from src.api.routes.health import router as health_router
from src.api.routes.jobs import profiles_router as profiles_matches_router
from src.api.routes.jobs import router as jobs_router
from src.api.routes.resumes import router as resumes_router
from src.api.routes.tailoring import router as tailoring_router
from src.config.settings import get_settings
from src.core.logging import configure_logging

logger = logging.getLogger(__name__)

settings = get_settings()
configure_logging()


def _warm_local_embeddings() -> None:
    """FU-7: pre-load the local embedder so the first search pays no load latency.

    Skipped when the provider is not fastembed or the model weights are not
    downloaded yet — a fresh install or an offline test run must never trigger
    the ~300 MiB download from app startup. Any failure is logged, never
    raised: an unloadable model degrades search (WS-03), it must not take the
    app down.
    """
    if settings.embedding_provider != "fastembed":
        return
    from src.llm.embeddings import build_embedding_fn, fastembed_cache_dir

    cache_dir = Path(fastembed_cache_dir(settings))
    if not cache_dir.exists() or not any(cache_dir.iterdir()):
        logger.info("Local embedding model not downloaded yet; skipping warm-up")
        return
    try:
        build_embedding_fn().embed_query("warmup")
        logger.info("Local embedding model warmed up")
    except Exception:
        logger.exception("Local embedding warm-up failed; first search will load the model")


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    _warm_local_embeddings()
    yield


app = FastAPI(
    title=settings.app_name,
    version="0.1.0",
    description="Autonomous AI Job Application Agent",
    debug=settings.app_debug,
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH"],
    allow_headers=["*"],
)

app.include_router(health_router)
app.include_router(applications_router)
app.include_router(resumes_router)
app.include_router(jobs_router)
app.include_router(profiles_matches_router)
app.include_router(tailoring_router)


@app.get("/")
async def root() -> dict[str, str]:
    return {
        "service": settings.app_name,
        "status": "ok",
        "environment": settings.app_env,
    }
