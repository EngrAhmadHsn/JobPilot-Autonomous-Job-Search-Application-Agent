"""Live end-to-end verification of the WS-06 security controls.

Runs the whole two-phase flow against a **real** HTTP server and a **real**
browser:

1. a local fake ATS is served (a form, a confirmation page, and a CAPTCHA
   page);
2. the API is started with uvicorn against a throwaway database;
3. ``POST /api/applications/prepare`` records an approval request;
4. ``POST /api/applications/{id}/approve`` executes the submission in
   Chromium, capturing the evidence artifacts;
5. the negative paths are exercised: a non-allowlisted host, a CAPTCHA page,
   and an adapter without the submit capability.

Every check prints PASS/FAIL; the script exits non-zero when a check fails.

Usage::

    env\\Scripts\\python.exe scripts\\verify_ws06.py
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
_WORKDIR = Path(tempfile.mkdtemp(prefix="ws06-verify-"))
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

from src.db.approval import ApprovalRequestDB
from src.db.audit import AuditEventDB
from src.db.evidence import ApplicationEvidence
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
        try:
            with httpx.Client(base_url=api, timeout=60) as client:
                # 1. A non-allowlisted host is refused before anything else.
                response = client.post(
                    "/api/applications/prepare",
                    json=_application_payload("https://evil-greenhouse.io.attacker.com/jobs/1"),
                )
                check(
                    "a non-allowlisted host is refused with 400",
                    response.status_code == 400,
                    f"status={response.status_code}",
                )

                # 2. The happy path: prepare -> approve -> submit -> verify.
                response = client.post(
                    "/api/applications/prepare", json=_application_payload(f"{ats}/apply")
                )
                check(
                    "prepare records an approval request",
                    response.status_code == 200
                    and response.json()["status"] == "awaiting_approval",
                    f"status={response.status_code}",
                )
                approval_id = response.json()["approval_id"]

                response = client.get(f"/api/applications/{approval_id}")
                check(
                    "the approval request is pending before the decision",
                    response.status_code == 200 and response.json()["status"] == "pending",
                    response.json().get("status", "?"),
                )

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
                check(
                    "the evidence carries a screenshot and a trace",
                    bool(body.get("evidence", {}).get("screenshot_path"))
                    and bool(body.get("evidence", {}).get("trace_path")),
                    str(body.get("evidence")),
                )

                screenshot = EVIDENCE_DIR / Path(body["evidence"]["screenshot_path"]).name
                trace = EVIDENCE_DIR / Path(body["evidence"]["trace_path"]).name
                archive = EVIDENCE_DIR / f"{response.json()['workflow_id']}.zip"
                check(
                    "the evidence artifacts are on disk",
                    screenshot.exists() and trace.exists() and archive.exists(),
                    f"{sorted(p.name for p in EVIDENCE_DIR.glob('*'))}",
                )

                # 3. The old single-call submit route cannot submit.
                response = client.post(
                    "/api/applications/submit", json=_application_payload(f"{ats}/apply")
                )
                check(
                    "the old POST /submit route cannot submit",
                    response.status_code in (404, 405),
                    f"status={response.status_code}",
                )

                # 4. A CAPTCHA page stops the flow.
                response = client.post(
                    "/api/applications/prepare", json=_application_payload(f"{ats}/challenge")
                )
                challenge_id = response.json()["approval_id"]
                response = client.post(
                    f"/api/applications/{challenge_id}/approve", json={"approver": "operator"}
                )
                body = response.json()
                check(
                    "a CAPTCHA page stops the flow (blocked_human_review)",
                    body.get("status") == "blocked_human_review" and body.get("success") is False,
                    f"status={body.get('status')}",
                )

                # 5. An adapter without the submit capability is denied.
                response = client.post(
                    "/api/applications/prepare",
                    json=_application_payload("https://boards.greenhouse.io/acme/jobs/1"),
                )
                greenhouse_id = response.json()["approval_id"]
                response = client.post(
                    f"/api/applications/{greenhouse_id}/approve", json={"approver": "operator"}
                )
                body = response.json()
                check(
                    "an adapter without the submit capability is denied",
                    body.get("status") == "permission_denied" and body.get("success") is False,
                    f"status={body.get('status')}",
                )

                # 6. The audit trail and the evidence row exist.
                engine = create_engine(f"sqlite:///{DATABASE_PATH.as_posix()}")
                with Session(engine) as session:
                    events = session.scalars(select(AuditEventDB)).all()
                    actions = sorted({event.action for event in events})
                    check(
                        "the audit trail recorded the whole flow",
                        {
                            "application.prepare",
                            "application.approve",
                            "application.submit",
                            "application.verify",
                        }
                        <= set(actions),
                        str(actions),
                    )
                    approvals = session.scalars(select(ApprovalRequestDB)).all()
                    decided = [row for row in approvals if row.approver]
                    check(
                        "every executed application has an approver on record",
                        len(decided) == len(approaches_executed(approvals)),
                        f"{len(decided)} decided of {len(approvals)}",
                    )
                    evidence_rows = session.scalars(select(ApplicationEvidence)).all()
                    check(
                        "the evidence row carries the artifact paths",
                        bool(evidence_rows) and bool(evidence_rows[0].screenshot_path),
                        f"{len(evidence_rows)} row(s)",
                    )
                engine.dispose()
        finally:
            server.should_exit = True
            thread.join(timeout=10)

    failed = [name for name, ok, _ in RESULTS if not ok]
    print()
    print(f"{len(RESULTS) - len(failed)}/{len(RESULTS)} checks passed")
    if failed:
        print("failed checks: " + ", ".join(failed))
    print(f"workdir: {_WORKDIR}")
    return 1 if failed else 0


def approaches_executed(approvals: list) -> list:
    """The approval records that were executed (not rejected)."""
    return [row for row in approvals if row.status in ("executed", "failed")]


if __name__ == "__main__":
    raise SystemExit(main())
