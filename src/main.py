from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from src.api.routes.applications import router as applications_router
from src.api.routes.health import router as health_router
from src.api.routes.jobs import profiles_router as profiles_matches_router
from src.api.routes.jobs import router as jobs_router
from src.api.routes.resumes import router as resumes_router
from src.config.settings import get_settings
from src.core.logging import configure_logging

settings = get_settings()
configure_logging()

app = FastAPI(
    title=settings.app_name,
    version="0.1.0",
    description="Autonomous AI Job Application Agent",
    debug=settings.app_debug,
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


@app.get("/")
async def root() -> dict[str, str]:
    return {
        "service": settings.app_name,
        "status": "ok",
        "environment": settings.app_env,
    }
