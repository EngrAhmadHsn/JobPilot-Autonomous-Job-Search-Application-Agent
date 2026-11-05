"""Health endpoints: liveness, readiness and the worker's own health (WS-18).

The old ``GET /api/health`` answered ``ok`` from a literal. That is a
**liveness** answer — is the process alive? — and it was doing three jobs at
once:

- liveness: the process is running;
- readiness: the process can serve its required operations;
- worker health: the background work is actually being executed.

They are different questions with different failure modes, and conflating
them makes both useless. An API that answers ``ok`` while its database is
gone is not ready; an API that answers ``ok`` while every worker is dead is
not executing the work it accepted. So there are three answers now, and the
old route stays for compatibility.

The readiness check is deliberately **essential-functionality only**. A
Gemini outage, an open board circuit or a queued retry backlog does not make
the API unable to serve searches and reads; it makes a feature degraded, and
the metrics endpoint says so. Failing readiness for a provider that is
optional would take a healthy API out of a load balancer for a non-essential
reason.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from sqlalchemy import text

from src.config.settings import get_settings

router = APIRouter(prefix="/api", tags=["health"])
settings = get_settings()

logger = logging.getLogger(__name__)


@router.get("/health")
async def health_check() -> dict[str, str]:
    """The original liveness answer, kept for compatibility."""
    return {
        "status": "ok",
        "service": settings.app_name,
        "environment": settings.app_env,
    }


@router.get("/health/live")
async def liveness() -> dict[str, str]:
    """Is the API process alive? The cheapest possible answer."""
    return {"status": "ok", "check": "liveness", "service": settings.app_name}


@router.get("/health/ready")
def readiness() -> JSONResponse:
    """Can the API serve its essential operations right now?

    ``essential`` means: the database answers. The worker's heartbeat is
    reported next to it, and an unhealthy worker is flagged — but it does
    not make the *API* unready, because reads and searches still work while
    a worker is being restarted. The administration endpoint
    (``GET /api/admin/health/workers``) is where worker liveness is an
    alert.
    """
    checks: dict[str, object] = {}
    ok = True
    try:
        from src.db.session import SessionLocal

        with SessionLocal() as session:
            session.execute(text("SELECT 1"))
        checks["database"] = "ok"
    except Exception as exc:  # noqa: BLE001 - readiness reports, never raises
        ok = False
        checks["database"] = f"error: {type(exc).__name__}"

    worker_summary: dict[str, object] = {"healthy": 0, "total": 0, "stale": 0}
    try:
        from src.db.session import SessionLocal
        from src.runs import queue as run_queue

        with SessionLocal() as session:
            health = run_queue.worker_health(session)
        worker_summary = {
            "healthy": health["healthy"],
            "total": health["total"],
            "stale": max(0, int(health["total"]) - int(health["healthy"])),
            "stale_after_seconds": health["stale_after_seconds"],
        }
    except Exception:  # noqa: BLE001 - a worker check must not fail readiness
        worker_summary = {"healthy": 0, "total": 0, "stale": 0, "error": "unavailable"}

    body = {
        "status": "ok" if ok else "unavailable",
        "check": "readiness",
        "service": settings.app_name,
        "checks": checks,
        "workers": worker_summary,
        # Explicitly not part of readiness: these degrade features, they do
        # not stop the API serving. See GET /api/admin/jobs/metrics.
        "optional_providers": "see /api/admin/jobs/metrics",
    }
    return JSONResponse(status_code=200 if ok else 503, content=body)
