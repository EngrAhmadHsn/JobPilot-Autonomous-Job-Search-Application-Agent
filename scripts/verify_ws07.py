"""Live end-to-end verification of the WS-07 application tracking.

Runs the whole two-phase flow against a **real** HTTP server, a **real**
browser and a **real** database, and then checks that the lifecycle was
actually recorded:

1. a local fake ATS is served (a form and a confirmation page);
2. the database is migrated to the current schema and the API is started;
3. ``POST /api/applications/prepare`` records an approval request **and**
   creates a tracked application;
4. ``POST /api/applications/{id}/approve`` submits and verifies the
   application in Chromium;
5. the database is inspected directly: the application row, its events, and
   the evidence row that links to it;
6. the tracking API is exercised over HTTP (list, detail, status update);
7. the API is **restarted** and the history is read again — the point of
   tracking is that it survives.

Every check prints PASS/FAIL; the script exits non-zero when a check fails.

Usage::

    env\\Scripts\\python.exe scripts\\verify_ws07.py
"""

from __future__ import annotations

import os
import sys
import tempfile
import threading
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

# The verification runs against a throwaway database and evidence directory,
# so it never touches the developer's data. The environment must be set
# before the application modules are imported (the settings are read at
# import time).
_WORKDIR = Path(tempfile.mkdtemp(prefix="ws07-verify-"))
DATABASE_PATH = _WORKDIR / "verify.db"
EVIDENCE_DIR = _WORKDIR / "evidence"
os.environ["DATABASE_URL"] = f"sqlite:///{DATABASE_PATH.as_posix()}"
os.environ["EVIDENCE_DIR"] = str(EVIDENCE_DIR)
os.environ["ALEMBIC_DATABASE_URL"] = f"sqlite:///{DATABASE_PATH.as_posix()}"
os.environ.setdefault("APP_ENV", "development")

import httpx
import uvicorn
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from src.db.applications import ApplicationDB, ApplicationEventDB
from src.db.audit import AuditEventDB
from src.db.evidence import ApplicationEvidence
from src.db.jobs import JobDB
from src.main import app
from tests.fixtures.fake_ats import serve_fake_ats

RESULTS: list[tuple[str, bool, str]] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    """Record one check and print its outcome."""
    RESULTS.append((name, condition, detail))
    print(f"[{'PASS' if condition else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))


def _upgrade_database() -> None:
    """Bring the throwaway database to the current schema."""
    config = Config(str(REPO_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(REPO_ROOT / "migrations"))
    command.upgrade(config, "head")


def _serve_api() -> tuple[uvicorn.Server, threading.Thread, str]:
    """Start the API on a free localhost port and return its base URL."""
    config = uvicorn.Config(app, host="127.0.0.1", port=0, log_level="warning")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.time() + 30
    while not server.started and time.time() < deadline:
        time.sleep(0.1)
    if not server.started:
        raise RuntimeError("The API server did not start in time")
    port = server.servers[0].sockets[0].getsockname()[1]
    return server, thread, f"http://127.0.0.1:{port}"


def _stop_api(server: uvicorn.Server, thread: threading.Thread) -> None:
    """Stop the API server and wait for the thread to finish."""
    server.should_exit = True
    thread.join(timeout=15)


def _application_payload(job_url: str) -> dict:
    return {
        "job_title": "Backend Engineer",
        "company_name": "Acme Labs",
        "job_url": job_url,
        "candidate_name": "Ada Lovelace",
        "email": "ada@example.com",
        "phone": "+1 555 0101",
    }


def main() -> int:
    _upgrade_database()

    with serve_fake_ats() as ats:
        server, thread, api = _serve_api()
        application_id = ""
        try:
            with httpx.Client(base_url=api, timeout=120) as client:
                # 1. Prepare: an approval request *and* a tracked application.
                response = client.post(
                    "/api/applications/prepare", json=_application_payload(f"{ats}/apply")
                )
                check(
                    "prepare records an approval request",
                    response.status_code == 200
                    and response.json()["status"] == "awaiting_approval",
                    f"status={response.status_code}",
                )
                body = response.json()
                approval_id = body["approval_id"]
                application_id = body.get("application_id") or ""
                check(
                    "prepare creates a tracked application",
                    bool(application_id),
                    f"application_id={application_id or 'missing'}",
                )

                # 2. The tracked application awaits the approval.
                engine = create_engine(f"sqlite:///{DATABASE_PATH.as_posix()}")
                with Session(engine) as session:
                    row = session.get(ApplicationDB, application_id)
                    check(
                        "the application is awaiting approval",
                        row is not None and row.status == "awaiting_approval",
                        f"status={row.status if row else 'missing'}",
                    )
                    check(
                        "the application points at a real listing row",
                        row is not None and session.get(JobDB, row.job_id) is not None,
                        f"job_id={row.job_id if row else '?'}",
                    )
                engine.dispose()

                # 3. Approve: the agent submits and verifies in a real browser.
                response = client.post(
                    f"/api/applications/{approval_id}/approve",
                    json={"approver": "verification-operator", "reason": "live check"},
                )
                body = response.json()
                check(
                    "the approved application is submitted and verified",
                    response.status_code == 200 and body.get("success") is True,
                    f"status={body.get('status')}",
                )

                # 4. The database holds the whole lifecycle.
                engine = create_engine(f"sqlite:///{DATABASE_PATH.as_posix()}")
                with Session(engine) as session:
                    row = session.get(ApplicationDB, application_id)
                    check(
                        "the application is verified",
                        row is not None and row.status == "verified",
                        f"status={row.status if row else 'missing'}",
                    )
                    check(
                        "the submission and verification timestamps are set",
                        row is not None
                        and row.submitted_at is not None
                        and row.verified_at is not None,
                        f"submitted={row.submitted_at}, verified={row.verified_at}" if row else "",
                    )

                    events = list(
                        session.scalars(
                            select(ApplicationEventDB)
                            .where(ApplicationEventDB.application_id == application_id)
                            .order_by(ApplicationEventDB.id)
                        )
                    )
                    moves = [event.to_status for event in events if event.to_status is not None]
                    check(
                        "one event per state change, in order",
                        moves == ["prepared", "awaiting_approval", "submitted", "verified"],
                        str(moves),
                    )
                    check(
                        "the event ids are ordered",
                        [event.id for event in events] == sorted(event.id for event in events),
                        str([event.id for event in events]),
                    )
                    check(
                        "the decision and the evidence are recorded",
                        any(event.event_type == "approval_granted" for event in events)
                        and any(event.event_type == "evidence_recorded" for event in events),
                        str([event.event_type for event in events]),
                    )

                    evidence_rows = list(
                        session.scalars(
                            select(ApplicationEvidence).where(
                                ApplicationEvidence.application_id == application_id
                            )
                        )
                    )
                    check(
                        "the evidence row is linked to the application",
                        len(evidence_rows) == 1 and bool(evidence_rows[0].screenshot_path),
                        f"{len(evidence_rows)} linked row(s)",
                    )

                    orphans = [
                        row_.id
                        for row_ in session.scalars(select(ApplicationEvidence)).all()
                        if row_.application_id is None
                    ]
                    check(
                        "no evidence row is left unlinked",
                        not orphans,
                        f"orphans={orphans}",
                    )

                    audits = session.scalars(
                        select(AuditEventDB).where(
                            AuditEventDB.action.in_(("application.transition", "application.event"))
                        )
                    ).all()
                    check(
                        "the audit trail recorded the transitions",
                        len(audits) >= 4,
                        f"{len(audits)} audit row(s)",
                    )
                engine.dispose()

                # 5. The tracking API over HTTP.
                response = client.get("/api/applications")
                listed = response.json()
                check(
                    "the application is listed",
                    response.status_code == 200
                    and any(item["id"] == application_id for item in listed["items"]),
                    f"total={listed.get('total')}",
                )

                response = client.get("/api/applications?status=verified")
                listed = response.json()
                check(
                    "the status filter works",
                    response.status_code == 200
                    and all(item["status"] == "verified" for item in listed["items"]),
                    f"total={listed.get('total')}",
                )

                response = client.get(f"/api/applications/{application_id}")
                detail = response.json()
                check(
                    "the detail carries the ordered history",
                    response.status_code == 200
                    and [event["id"] for event in detail["events"]]
                    == sorted(event["id"] for event in detail["events"]),
                    f"{len(detail.get('events', []))} event(s)",
                )

                # 6. The actor rule: the agent cannot record an outcome.
                response = client.patch(
                    f"/api/applications/{application_id}/status",
                    json={"status": "offer", "actor": "agent"},
                )
                check(
                    "the agent cannot record a human outcome (403)",
                    response.status_code == 403,
                    f"status={response.status_code}",
                )

                # 7. An illegal transition is refused.
                response = client.patch(
                    f"/api/applications/{application_id}/status",
                    json={"status": "prepared", "actor": "human:operator"},
                )
                check(
                    "an illegal transition is refused (409)",
                    response.status_code == 409,
                    f"status={response.status_code}",
                )

                # 8. A human records a real outcome.
                response = client.patch(
                    f"/api/applications/{application_id}/status",
                    json={
                        "status": "interview",
                        "actor": "human:operator",
                        "notes": "first round scheduled",
                    },
                )
                detail = response.json()
                check(
                    "a human records the interview",
                    response.status_code == 200 and detail.get("status") == "interview",
                    f"status={response.status_code}",
                )
                check(
                    "the outcome is attributed to the human",
                    detail.get("events", [{}])[-1].get("actor") == "human:operator",
                    str(detail.get("events", [{}])[-1].get("actor")),
                )
        finally:
            _stop_api(server, thread)

        # 9. The history survives a restart — the point of tracking.
        server, thread, api = _serve_api()
        try:
            with httpx.Client(base_url=api, timeout=60) as client:
                response = client.get(f"/api/applications/{application_id}")
                detail = response.json()
                check(
                    "the history survives a restart of the server",
                    response.status_code == 200
                    and detail.get("status") == "interview"
                    and len(detail.get("events", [])) >= 5,
                    f"status={detail.get('status')}, {len(detail.get('events', []))} event(s)",
                )
        finally:
            _stop_api(server, thread)

    failed = [name for name, ok, _ in RESULTS if not ok]
    print()
    print(f"{len(RESULTS) - len(failed)}/{len(RESULTS)} checks passed")
    if failed:
        print("failed checks: " + ", ".join(failed))
    print(f"workdir: {_WORKDIR}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
