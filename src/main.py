from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from src.api.middleware import (
    BodySizeLimitMiddleware,
    ConcurrencyLimitMiddleware,
    RateLimitMiddleware,
    SecurityHeadersMiddleware,
)
from src.api.routes.applications import router as applications_router
from src.api.routes.artifacts import router as artifacts_router
from src.api.routes.audit import router as audit_router
from src.api.routes.documents import router as documents_router
from src.api.routes.health import router as health_router
from src.api.routes.jobs import profiles_router as profiles_matches_router
from src.api.routes.jobs import router as jobs_router
from src.api.routes.resumes import router as resumes_router
from src.api.routes.tailoring import router as tailoring_router
from src.api.routes.tracking import router as tracking_router
from src.auth.csrf import CSRFProtectionMiddleware
from src.auth.routes import router as auth_router
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
    # WS-12: the interactive API docs are an HTML surface that renders the
    # OpenAPI schema, and they are enabled by default. They are a
    # development convenience, not a production feature: outside
    # development the routes are removed entirely rather than protected by
    # a password, so there is no second factor to forget.
    docs_url="/docs" if settings.app_env == "development" else None,
    redoc_url="/redoc" if settings.app_env == "development" else None,
    openapi_url="/openapi.json" if settings.app_env == "development" else None,
)

# WS-12: the middleware order matters.
#
# CORS is added first, so it is the **outermost** layer: a request that the
# rate limiter refuses still gets the CORS headers the browser needs to
# read the error, and the security headers are applied to the CORS
# preflight response too.
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH"],
    allow_headers=["*"],
)
# The body cap is inside the rate limiter: a request that is over the rate
# limit is refused without its body ever being read, so a flood costs the
# server a header parse rather than a body read.
app.add_middleware(BodySizeLimitMiddleware)
app.add_middleware(RateLimitMiddleware)
app.add_middleware(ConcurrencyLimitMiddleware)
app.add_middleware(SecurityHeadersMiddleware)
# WS-14 · A1: the double-submit CSRF check. It sits **inside** the
# security headers, so a refused request still carries them, and outside
# the routers, so it applies to every unsafe request that authenticates
# with the session cookie — including the ones a future route adds.
app.add_middleware(CSRFProtectionMiddleware)

app.include_router(health_router)
# WS-14 · A1: the identity API. It is mounted before the data routes so
# that a request without a credential is refused by the auth dependency
# rather than by a data route's own check.
app.include_router(auth_router)
# WS-14 · Phase C: the caller's own audit trail.
app.include_router(audit_router)
app.include_router(documents_router)
app.include_router(applications_router)
app.include_router(resumes_router)
app.include_router(jobs_router)
app.include_router(profiles_matches_router)
app.include_router(tailoring_router)
app.include_router(tracking_router)
# WS-13: the two artifact downloads the operator console needs (BA-1, BA-2).
app.include_router(artifacts_router)


@app.get("/")
async def root() -> dict[str, str]:
    return {
        "service": settings.app_name,
        "status": "ok",
        "environment": settings.app_env,
    }
