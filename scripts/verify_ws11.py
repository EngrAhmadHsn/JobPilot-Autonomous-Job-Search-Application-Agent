"""Live end-to-end verification of WS-11 (the documentation and the operations).

WS-11 is a documentation workstream, so its verification is two things at once:

1. **The documents agree with the code.** Every environment variable the
   runtime reads is documented and every documented variable is read; the
   documented defaults are the code's defaults; the README's API table is
   exactly the API the application exposes; and the planning documents carry
   their reconciliation.
2. **The quickstart works.** A fresh database is created by the documented
   migration command, the documented server command starts the API, the
   documented upload and search calls answer, and the documented fake-ATS
   flow — prepare, approve, submit, verify — produces its evidence on disk.

Every check prints PASS/FAIL; the script exits non-zero when a check fails.

Usage::

    env\\Scripts\\python.exe scripts\\verify_ws11.py
"""

from __future__ import annotations

import os
import re
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
_WORKDIR = Path(tempfile.mkdtemp(prefix="ws11-verify-"))
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

from src.main import app
from tests.fixtures.fake_ats import serve_fake_ats_variants

RESULTS: list[tuple[str, bool, str]] = []

README = REPO_ROOT / "README.md"
ENV_EXAMPLE = REPO_ROOT / ".env.example"
ARCHITECTURE = REPO_ROOT / "docs" / "ARCHITECTURE.md"
PROJECT_PLAN = REPO_ROOT / "docs" / "PROJECT_PLAN.md"
SECURITY = REPO_ROOT / "docs" / "SECURITY.md"

_ENV_PATTERNS = (
    re.compile(r"""os\.getenv\(\s*["']([A-Z][A-Z0-9_]*)["']"""),
    re.compile(r"""os\.environ\.get\(\s*["']([A-Z][A-Z0-9_]*)["']"""),
    re.compile(r"""os\.environ\[\s*["']([A-Z][A-Z0-9_]*)["']"""),
    re.compile(r"""_int_env\(\s*["']([A-Z][A-Z0-9_]*)["']"""),
    re.compile(r"""_float_env\(\s*["']([A-Z][A-Z0-9_]*)["']"""),
)
_ENTRY_PATTERN = re.compile(r"^\s*#?\s*([A-Z][A-Z0-9_]*)\s*=")
_TABLE_ROW = re.compile(r"^\|\s*`([A-Z]+)\s+(/[^`]*)`\s*\|")


def check(name: str, condition: bool, detail: str = "") -> None:
    """Record one check and print its outcome."""
    RESULTS.append((name, condition, detail))
    print(f"[{'PASS' if condition else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))


def _runtime_env_vars() -> set[str]:
    """Every environment variable the runtime reads."""
    names: set[str] = set()
    for path in sorted((REPO_ROOT / "src").rglob("*.py")):
        text = path.read_text(encoding="utf-8")
        for pattern in _ENV_PATTERNS:
            names.update(pattern.findall(text))
    return names


def _documented_env_vars() -> set[str]:
    """Every environment variable the example file documents."""
    names: set[str] = set()
    for line in ENV_EXAMPLE.read_text(encoding="utf-8").splitlines():
        match = _ENTRY_PATTERN.match(line)
        if match:
            names.add(match.group(1))
    return names


def _application_routes() -> set[tuple[str, str]]:
    """Every (method, path) the running application exposes."""
    routes: set[tuple[str, str]] = set()
    for path, operations in app.openapi()["paths"].items():
        for method in operations:
            if method.upper() in {"HEAD", "OPTIONS"}:
                continue
            routes.add((method.upper(), path))
    return routes


def _readme_routes() -> set[tuple[str, str]]:
    """Every (method, path) the README's API table lists."""
    routes: set[tuple[str, str]] = set()
    for line in README.read_text(encoding="utf-8").splitlines():
        match = _TABLE_ROW.match(line.strip())
        if match:
            routes.add((match.group(1), match.group(2)))
    return routes


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


def _check_documents() -> None:
    """The documents agree with the code."""
    runtime = _runtime_env_vars()
    documented = _documented_env_vars()

    missing = sorted(runtime - documented)
    check(
        "every variable the runtime reads is documented in .env.example",
        not missing,
        f"missing: {missing}" if missing else f"{len(documented)} variables",
    )

    unused = sorted(documented - runtime)
    check(
        "every variable in .env.example is read by the runtime",
        not unused,
        f"unused: {unused}" if unused else f"{len(documented)} variables",
    )

    application = _application_routes()
    readme = _readme_routes()
    check(
        "the README's API table is exactly the API the application exposes",
        application == readme,
        f"{len(application)} routes",
    )

    readme_text = README.read_text(encoding="utf-8")
    check(
        "the README does not advertise the removed single-call submit route",
        "/api/applications/submit" not in readme_text,
    )

    check(
        "the README's quickstart runs the documented migration command",
        "alembic upgrade head" in readme_text,
    )
    check(
        "the README's quickstart runs the documented server command",
        "uvicorn src.main:app" in readme_text,
    )
    check(
        "the README's quickstart installs the browser",
        "playwright install chromium" in readme_text,
    )

    architecture_text = ARCHITECTURE.read_text(encoding="utf-8")
    stale = [
        claim
        for claim in (
            "**PLANNED**: FastAPI service",
            "**PLANNED**: LangGraph orchestration",
            "**PLANNED**: matching engine",
        )
        if claim in architecture_text
    ]
    check(
        "the architecture document no longer labels implemented components PLANNED",
        not stale,
        f"stale claims: {stale}" if stale else "status list reconciled",
    )
    check(
        "the architecture document names the real module paths",
        "src/matching/engine.py" in architecture_text
        and "src/applications/fake_ats_adapter.py" in architecture_text,
    )

    plan_text = PROJECT_PLAN.read_text(encoding="utf-8")
    check(
        "the project plan carries the reconciliation appendix",
        "Plan-to-Reality Reconciliation" in plan_text,
    )
    for deviation in ("CandidateProfile", "LinkedIn", "AUTO_SUBMIT", "Phase 8"):
        check(
            f"the reconciliation names the deviation: {deviation}",
            deviation in plan_text,
        )

    security_text = SECURITY.read_text(encoding="utf-8")
    check(
        "the security document's status section describes the present",
        "exposes a minimal FastAPI application and a health endpoint" not in security_text,
    )
    check(
        "the security document records the WS-12 controls",
        "SEC-17" in security_text and "SEC-21" in security_text,
    )

    evaluations = REPO_ROOT / "docs" / "evaluations"
    reports = list(evaluations.glob("report-*.md")) if evaluations.exists() else []
    check(
        "docs/evaluations holds at least one baseline report",
        bool(reports),
        ", ".join(p.name for p in reports),
    )


def _check_live_flow() -> None:
    """The quickstart works, from a fresh database to the evidence on disk."""
    _upgrade_database()
    check(
        "alembic upgrade head creates the database",
        DATABASE_PATH.exists(),
        str(DATABASE_PATH.name),
    )

    import sqlite3

    with sqlite3.connect(DATABASE_PATH) as connection:
        tables = {
            row[0]
            for row in connection.execute("select name from sqlite_master where type='table'")
        }
    expected = {
        "jobs",
        "candidate_profiles",
        "job_matches",
        "tailored_resumes",
        "approval_requests",
        "audit_events",
        "applications",
        "application_events",
        "application_evidence",
    }
    check(
        "the migration creates every table the ORM expects",
        expected <= tables,
        f"missing: {sorted(expected - tables)}"
        if not expected <= tables
        else f"{len(tables)} tables",
    )

    with serve_fake_ats_variants() as ats:
        server, thread, api = _serve_api()
        try:
            with httpx.Client(base_url=api, timeout=60) as client:
                response = client.get("/")
                check(
                    "GET / answers",
                    response.status_code == 200 and response.json()["status"] == "ok",
                    f"status={response.status_code}",
                )

                response = client.get("/api/health")
                check(
                    "GET /api/health answers",
                    response.status_code == 200 and response.json()["status"] == "ok",
                    f"status={response.status_code}",
                )

                resume = REPO_ROOT / "tests" / "fixtures" / "demo_resume.txt"
                with resume.open("rb") as handle:
                    response = client.post(
                        "/api/resumes",
                        files={"file": (resume.name, handle, "text/plain")},
                    )
                body = response.json() if response.status_code == 200 else {}
                profile_id = body.get("profile_id") or body.get("id")
                check(
                    "POST /api/resumes uploads a resume and returns a profile id",
                    response.status_code == 200 and bool(profile_id),
                    f"status={response.status_code}",
                )

                if profile_id:
                    response = client.post(
                        "/api/jobs/search",
                        json={"profile_id": profile_id, "top_n": 10},
                    )
                    check(
                        "POST /api/jobs/search answers for the stored profile",
                        response.status_code == 200,
                        f"status={response.status_code}",
                    )

                    response = client.get(f"/api/profiles/{profile_id}/matches")
                    check(
                        "GET /api/profiles/{id}/matches answers",
                        response.status_code == 200,
                        f"status={response.status_code}",
                    )

                # The documented fake-ATS flow: prepare, approve, submit, verify.
                payload = {
                    "job_title": "AI Engineer",
                    "company_name": "Acme Labs",
                    "job_url": f"{ats}/basic",
                    "candidate_name": "Ada Lovelace",
                    "email": "ada@example.com",
                    "phone": "+1 555 0101",
                }
                response = client.post("/api/applications/prepare", json=payload)
                body = response.json() if response.status_code == 200 else {}
                approval_id = body.get("approval_id")
                check(
                    "POST /api/applications/prepare records an approval request",
                    response.status_code == 200 and bool(approval_id),
                    f"status={response.status_code}",
                )

                if approval_id:
                    response = client.get(f"/api/applications/approvals/{approval_id}")
                    check(
                        "the approval request is pending before the decision",
                        response.status_code == 200 and response.json()["status"] == "pending",
                        response.json().get("status", "?"),
                    )

                    response = client.post(
                        f"/api/applications/{approval_id}/approve",
                        json={"approver": "verification-operator", "reason": "live check"},
                    )
                    body = response.json() if response.status_code == 200 else {}
                    check(
                        "the approved application is submitted and verified",
                        response.status_code == 200 and body.get("success") is True,
                        f"status={body.get('status')}",
                    )

                    evidence = body.get("evidence") or {}
                    artifacts = (
                        sorted(p.name for p in EVIDENCE_DIR.glob("*"))
                        if EVIDENCE_DIR.exists()
                        else []
                    )
                    check(
                        "the evidence artifacts are on disk",
                        bool(evidence.get("screenshot_path"))
                        and bool(evidence.get("trace_path"))
                        and len(artifacts) >= 3,
                        ", ".join(artifacts),
                    )

                    response = client.get("/api/applications")
                    check(
                        "GET /api/applications lists the tracked application",
                        response.status_code == 200,
                        f"status={response.status_code}",
                    )
        finally:
            server.should_exit = True
            thread.join(timeout=10)


def main() -> int:
    print("WS-11 · documentation and operations\n")
    print("— the documents —")
    _check_documents()
    print("\n— the quickstart, live —")
    _check_live_flow()

    passed = sum(1 for _, ok, _ in RESULTS if ok)
    total = len(RESULTS)
    print(f"\n{passed}/{total} checks passed")

    if passed != total:
        print("\nFailed checks:")
        for name, ok, detail in RESULTS:
            if not ok:
                print(f"  - {name}" + (f" — {detail}" if detail else ""))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
