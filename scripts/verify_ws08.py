"""Live end-to-end verification of the WS-08 browser-automation depth.

Runs the whole two-phase flow against a **real** HTTP server, a **real**
Chromium browser and a **real** database, for every fake-ATS variant:

1. the variant server is served (a single-page form, a three-step wizard, the
   widget page, the unknown question, the rejected form, the challenge, the
   upload);
2. the API is started with uvicorn against a throwaway database;
3. for each variant: ``POST /api/applications/prepare`` records an approval
   request and ``POST /api/applications/{id}/approve`` executes the
   submission in Chromium;
4. the negative facts are asserted: the challenge page was never posted to,
   the unknown question was never answered, the rejected form carries the
   server's own message;
5. two consecutive runs are checked for session bleed;
6. the evidence artifacts and the database rows are inspected directly.

Every check prints PASS/FAIL; the script exits non-zero when a check fails.

Usage::

    env\\Scripts\\python.exe scripts\\verify_ws08.py
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
_WORKDIR = Path(tempfile.mkdtemp(prefix="ws08-verify-"))
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

from src.db.applications import ApplicationDB
from src.db.audit import AuditEventDB
from src.db.evidence import ApplicationEvidence
from src.main import app
from tests.fixtures.fake_ats import serve_fake_ats_variants

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


def _payload(job_url: str, **extra) -> dict:
    payload = {
        "job_title": "Backend Engineer",
        "company_name": "Acme Labs",
        "job_url": job_url,
        "candidate_name": "Ada Lovelace",
        "email": "ada@example.com",
        "phone": "+1 555 0101",
    }
    payload.update(extra)
    return payload


def _run(client: httpx.Client, job_url: str, **extra) -> dict:
    """The whole flow: prepare, then approve (which executes the submission)."""
    prepared = client.post("/api/applications/prepare", json=_payload(job_url, **extra))
    if prepared.status_code != 200:
        return {"status": f"prepare failed ({prepared.status_code})", "success": False}
    approval_id = prepared.json()["approval_id"]
    approved = client.post(
        f"/api/applications/{approval_id}/approve",
        json={"approver": "human:ada", "reason": "live verification"},
        timeout=180,
    )
    if approved.status_code != 200:
        return {"status": f"approve failed ({approved.status_code})", "success": False}
    return approved.json()


def main() -> int:
    _upgrade_database()

    with serve_fake_ats_variants() as ats:
        server, thread, api = _serve_api()
        try:
            with httpx.Client(base_url=api, timeout=180) as client:
                # -- the variants that must succeed ----------------------
                successful = [
                    ("/basic", {}),
                    (
                        "/multipage",
                        {
                            "custom_fields": {
                                "years_of_experience": "7",
                                "work_authorization": "yes",
                            }
                        },
                    ),
                    (
                        "/widgets",
                        {
                            "custom_fields": {
                                "country": "Germany",
                                "years_of_experience": "7",
                                "work_authorization": "yes",
                                "work_mode": "remote",
                            }
                        },
                    ),
                    ("/validation-recoverable", {}),
                ]
                for path, extra in successful:
                    result = _run(client, f"{ats}{path}", **extra)
                    check(
                        f"{path} is submitted and verified",
                        result.get("success") is True and result.get("status") == "verified",
                        f"status={result.get('status')}",
                    )
                    evidence = result.get("evidence") or {}
                    screenshot = evidence.get("screenshot_path")
                    check(
                        f"{path} left its evidence on disk",
                        bool(screenshot) and (EVIDENCE_DIR / screenshot).exists(),
                        f"screenshot={screenshot}",
                    )

                # the widget values really reached the server
                submissions = httpx.get(f"{ats}/_submissions", timeout=30).json()
                widget = next((s for s in submissions if s.get("country")), {})
                check(
                    "the widget values reached the server",
                    widget.get("country") == "Germany"
                    and widget.get("work_mode") == "remote"
                    and widget.get("work_authorization") == "yes",
                    f"country={widget.get('country')} work_mode={widget.get('work_mode')}",
                )

                # -- the unknown question ---------------------------------
                result = _run(client, f"{ats}/unknown")
                check(
                    "the unknown question stops the run with needs_human",
                    result.get("status") == "needs_human" and result.get("success") is False,
                    f"status={result.get('status')}",
                )
                questions = (result.get("metadata") or {}).get("questions") or []
                check(
                    "the question text is surfaced",
                    questions == ["Have you served on a submarine?"],
                    f"questions={questions}",
                )
                last = httpx.get(f"{ats}/_last", timeout=30).json()
                check(
                    "nothing was submitted for the unknown question",
                    last.get("method") == "GET" and last.get("path") == "/unknown",
                    f"last={last.get('method')} {last.get('path')}",
                )

                # -- the challenge ---------------------------------------
                result = _run(client, f"{ats}/captcha")
                check(
                    "the challenge stops the run with blocked_human_review",
                    result.get("status") == "blocked_human_review",
                    f"status={result.get('status')}",
                )
                last = httpx.get(f"{ats}/_last", timeout=30).json()
                check(
                    "the challenge was never posted to",
                    last.get("method") == "GET" and last.get("path") == "/captcha",
                    f"last={last.get('method')} {last.get('path')}",
                )

                # -- the rejected form -----------------------------------
                result = _run(client, f"{ats}/validation")
                check(
                    "the rejected form ends with form_error",
                    result.get("status") == "form_error",
                    f"status={result.get('status')}",
                )
                errors = (result.get("metadata") or {}).get("errors") or []
                check(
                    "the server's own message is captured",
                    bool(errors) and "could not verify" in errors[0],
                    f"errors={errors}",
                )

                # -- the required upload ----------------------------------
                resume = _WORKDIR / "resume.txt"
                resume.write_text("Ada Lovelace — Senior Python Engineer\n", encoding="utf-8")
                result = _run(client, f"{ats}/upload-required", resume_path=str(resume))
                check(
                    "the upload variant is submitted and verified",
                    result.get("success") is True and result.get("status") == "verified",
                    f"status={result.get('status')}",
                )
                last = httpx.get(f"{ats}/_last", timeout=30).json()
                check(
                    "the resume really was uploaded",
                    last.get("files") == ["resume.txt"],
                    f"files={last.get('files')}",
                )

                # -- session isolation -----------------------------------
                first = _run(client, f"{ats}/session")
                second = _run(client, f"{ats}/session")
                check(
                    "both isolation runs succeeded",
                    first.get("success") is True and second.get("success") is True,
                    f"first={first.get('status')} second={second.get('status')}",
                )
                markers = [
                    ((r.get("evidence") or {}).get("confirmation_text") or "")
                    for r in (first, second)
                ]
                check(
                    "the second run inherited no browser storage",
                    all("Marker: none" in marker for marker in markers),
                    f"markers={['Marker: none' in m for m in markers]}",
                )
                requests = httpx.get(f"{ats}/_requests", timeout=30).json()
                session_gets = [
                    record
                    for record in requests
                    if record.get("path") == "/session" and record.get("method") == "GET"
                ]
                check(
                    "the second run inherited no cookie",
                    len(session_gets) >= 2 and session_gets[-1].get("cookie") == "",
                    f"cookies={[r.get('cookie') for r in session_gets]}",
                )

            # -- the database rows ----------------------------------------
            engine = create_engine(f"sqlite:///{DATABASE_PATH.as_posix()}")
            with Session(engine) as session:
                applications = session.scalars(select(ApplicationDB)).all()
                verified = [a for a in applications if a.status == "verified"]
                check(
                    "the verified applications are tracked",
                    len(verified) >= 5,
                    f"verified={len(verified)} of {len(applications)}",
                )

                evidence_rows = session.scalars(select(ApplicationEvidence)).all()
                statuses = sorted({row.status for row in evidence_rows})
                check(
                    "every outcome left an evidence row",
                    {"verified", "needs_human", "blocked_human_review", "form_error"}
                    <= set(statuses),
                    f"statuses={statuses}",
                )
                with_files = [
                    row
                    for row in evidence_rows
                    if row.screenshot_path and (EVIDENCE_DIR / row.screenshot_path).exists()
                ]
                check(
                    "every evidence row points at a screenshot on disk",
                    len(with_files) == len(evidence_rows),
                    f"{len(with_files)} of {len(evidence_rows)}",
                )

                audit_rows = session.scalars(select(AuditEventDB)).all()
                check(
                    "the audit trail recorded the submissions",
                    len(audit_rows) > 0,
                    f"rows={len(audit_rows)}",
                )
            engine.dispose()
        finally:
            _stop_api(server, thread)

    passed = sum(1 for _, ok, _ in RESULTS if ok)
    total = len(RESULTS)
    print(f"\n{passed}/{total} checks passed.")
    return 0 if passed == total else 1


if __name__ == "__main__":
    raise SystemExit(main())
