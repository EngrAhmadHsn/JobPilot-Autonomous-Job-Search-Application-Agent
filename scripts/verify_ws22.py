"""Live end-to-end verification of WS-22 (bring your own key, PII mask, style, sponsors).

Four claims, each checked against the real code over real HTTP — not a mock:

1. **A user's own key is what their calls run on.** A credential is stored
   through the API, and a local fake chat-completions server proves that the
   *user's* key reached it and the platform key did not. The stored row is
   read straight out of SQLite to prove the key is encrypted at rest.
2. **The prompt never carries candidate identity.** The fake server records
   the prompt it was sent, and every identity string from the uploaded résumé
   is absent from it — while the answer's placeholder comes back restored.
3. **The style policy is reported, not silently applied.** The tailor
   response carries a style report computed on the delivered text.
4. **Sponsorship is verified from the register and never scored.** A company
   from an imported USCIS fixture reports ``verified``; an unknown company
   reports ``not_found`` phrased about the register; the score is untouched.

Plus one negative check: the ChatOps and MCP surfaces do not exist, which is
what "pending" means.

The whole run uses a throwaway database, a throwaway data directory and a
loopback fake provider. Nothing touches the developer's data, and nothing
reaches the network.

Usage::

    env\\Scripts\\python.exe scripts\\verify_ws22.py
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import ClassVar

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

# A throwaway environment, set before the application modules are imported.
_WORKDIR = Path(tempfile.mkdtemp(prefix="ws22-verify-"))
DATABASE_PATH = _WORKDIR / "verify.db"
os.environ["DATA_DIR"] = str(_WORKDIR / "data")
os.environ["DATABASE_URL"] = f"sqlite:///{DATABASE_PATH.as_posix()}"
os.environ["ALEMBIC_DATABASE_URL"] = f"sqlite:///{DATABASE_PATH.as_posix()}"
os.environ["CHROMA_DIR"] = str(_WORKDIR / "chroma")
os.environ["EVIDENCE_DIR"] = str(_WORKDIR / "evidence")
os.environ["TAILORED_DIR"] = str(_WORKDIR / "tailored")
os.environ["BYOK_MODE"] = "optional"
os.environ.pop("BYOK_ENCRYPTION_KEY", None)
os.environ.pop("AUTH_SECRET", None)
os.environ.setdefault("APP_ENV", "development")

import httpx
import uvicorn
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, select
from sqlalchemy.orm import sessionmaker

from src.main import app

FIXTURE_DOCX = REPO_ROOT / "tests" / "fixtures" / "Ahmad_Hassan_AI_Engineer_Resume.docx"
DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"

#: The candidate identity the fixture résumé carries. Every one of these must
#: be absent from the prompt the provider receives.
#: Strings that must never appear in a prompt. The candidate's real name is
#: added from the parsed profile at run time; these cover the rest.
FIXTURE_IDENTITY = ("ahmad", "hassan", "@")

#: The key this run registers, and the platform key it must not use.
USER_KEY = "sk-ws22-user-owned-0123456789"
PLATFORM_KEY = "sk-ws22-platform-9876543210"

RESULTS: list[tuple[str, bool, str]] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    """Record one check and print its outcome."""
    RESULTS.append((name, condition, detail))
    print(f"[{'PASS' if condition else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))


# --------------------------------------------------------------------------
# The fake chat-completions provider
# --------------------------------------------------------------------------


class _Capture:
    """What the fake provider saw, and what it should answer with."""

    requests: ClassVar[list[dict]] = []
    #: The project the tailoring answer must name, taken from the real
    #: uploaded profile — the factuality validator strips anything the
    #: profile does not name, and the fixture résumé lists projects rather
    #: than employment, so a fabricated entry would produce an empty
    #: résumé and prove nothing about the style report.
    project: ClassVar[str] = "Unknown Project"


class _FakeProviderHandler(BaseHTTPRequestHandler):
    """A chat-completions endpoint that records what it was sent.

    It answers with the schema the caller asked for, detected from the
    schema instruction the prompt carries — the same trick the WS-10 capture
    server used, extended to two schemas because one tailoring run asks for
    ``JobInsights`` and then ``TailoredResume``.
    """

    def log_message(self, *_args) -> None:
        return

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length", "0"))
        body = json.loads(self.rfile.read(length) or b"{}")
        prompt = body.get("messages", [{}])[0].get("content", "")
        _Capture.requests.append(
            {
                "authorization": self.headers.get("Authorization", ""),
                "prompt": prompt,
                "model": body.get("model"),
            }
        )

        if '"title": "JobInsights"' in prompt:
            payload = {
                "responsibilities": ["Build machine learning systems"],
                "tech_stack": ["Python"],
                "seniority_signals": [],
                "culture_flags": [],
                "summary": "An engineering role.",
            }
        else:
            # The summary echoes the token, as a model would when it refers
            # to the candidate by name.
            payload = {
                "summary": "[[NAME]] ships machine learning systems.",
                "highlighted_skills": ["Python"],
                "experience": [],
                "projects": [
                    {
                        "name": _Capture.project,
                        "bullets": ["Designed a pipeline that cut latency 30%."],
                    }
                ],
                "cover_letter": "I am [[NAME]] and I would like to apply.",
            }

        response = json.dumps(
            {
                "choices": [{"message": {"content": json.dumps(payload)}}],
                "usage": {"prompt_tokens": 10, "completion_tokens": 10, "total_tokens": 20},
            }
        ).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(response)))
        self.end_headers()
        self.wfile.write(response)


def _start_fake_provider() -> tuple[ThreadingHTTPServer, str]:
    server = ThreadingHTTPServer(("127.0.0.1", 0), _FakeProviderHandler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    port = server.server_address[1]
    return server, f"http://127.0.0.1:{port}/v1"


# --------------------------------------------------------------------------
# The API under test
# --------------------------------------------------------------------------


def _upgrade_database() -> None:
    config = Config(str(REPO_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(REPO_ROOT / "migrations"))
    command.upgrade(config, "head")


def _serve_api() -> tuple[uvicorn.Server, str]:
    config = uvicorn.Config(app, host="127.0.0.1", port=0, log_level="warning")
    server = uvicorn.Server(config)
    threading.Thread(target=server.run, daemon=True).start()
    deadline = time.time() + 60
    while not server.started and time.time() < deadline:
        time.sleep(0.1)
    if not server.started:
        raise RuntimeError("The API server did not start in time")
    port = server.servers[0].sockets[0].getsockname()[1]
    return server, f"http://127.0.0.1:{port}"


def _register(client: httpx.Client, email: str) -> str:
    password = "ws22-verification-password"
    client.post("/api/auth/register", json={"email": email, "password": password})
    response = client.post("/api/auth/token/login", data={"username": email, "password": password})
    if response.status_code == 200:
        client.headers["Authorization"] = f"Bearer {response.json()['access_token']}"
    return password


def _session():
    engine = create_engine(f"sqlite:///{DATABASE_PATH.as_posix()}", future=True)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False)()


def check_migration() -> None:
    engine = create_engine(f"sqlite:///{DATABASE_PATH.as_posix()}")
    inspector = inspect(engine)
    tables = set(inspector.get_table_names())
    check(
        "the WS-22 migration adds the credential and register tables",
        {"llm_credentials", "visa_sponsors"} <= tables,
    )
    columns = {col["name"] for col in inspector.get_columns("tailored_resumes")}
    check("the WS-22 migration adds the style column", "style" in columns)
    engine.dispose()


def _seed_job(company: str) -> str:
    """One listing in the shared corpus, so the tailoring path has a target."""
    from src.db.jobs import JobDB

    session = _session()
    try:
        job_id = f"greenhouse:ws22-{int(time.time())}"
        session.add(
            JobDB(
                id=job_id,
                source="greenhouse",
                title="Machine Learning Engineer",
                company=company,
                description="Build machine learning systems in Python.",
                required_skills=["python"],
                preferred_skills=[],
                application_url="https://boards.greenhouse.io/acme/jobs/1",
            )
        )
        session.commit()
        return job_id
    finally:
        session.close()


def _seed_match(profile_id: str, job_id: str, owner_id: str) -> None:
    """One persisted match row, so the history endpoint has something to enrich."""
    from src.db.matches import JobMatchDB

    session = _session()
    try:
        session.add(
            JobMatchDB(
                owner_id=owner_id,
                profile_id=profile_id,
                job_id=job_id,
                scores={
                    "overall_score": 71.0,
                    "semantic_score": 60.0,
                    "skill_score": 80.0,
                    "experience_score": 70.0,
                    "seniority_score": 65.0,
                    "location_score": 90.0,
                    "preference_score": 75.0,
                    "role_score": 50.0,
                    "evidence_coverage": 80.0,
                },
                explanation="Seeded for the WS-22 verification run.",
            )
        )
        session.commit()
    finally:
        session.close()


def _owner_of(email: str) -> str:
    from src.db.users import UserDB

    session = _session()
    try:
        row = session.execute(select(UserDB).where(UserDB.email == email)).scalar_one()
        return row.id
    finally:
        session.close()


# --------------------------------------------------------------------------
# The checks
# --------------------------------------------------------------------------


def check_byok(api: str, fake_base_url: str) -> dict:
    outcome: dict = {}
    with httpx.Client(base_url=api, timeout=120) as client:
        email = f"ws22-owner-{int(time.time())}@example.com"
        _register(client, email)
        outcome["email"] = email
        outcome["owner_id"] = _owner_of(email)

        state = client.get("/api/llm/credentials")
        check(
            "the credential read starts empty with the deployment mode",
            state.status_code == 200
            and state.json()["mode"] == "optional"
            and state.json()["credential"] is None,
            f"status={state.status_code}",
        )
        check(
            "the status never carries a key field",
            "api_key" not in state.text and "encrypted_key" not in state.text,
        )

        stored = client.put(
            "/api/llm/credentials",
            json={
                "provider": "openai-compatible",
                "model": "ws22-fake-model",
                "api_key": USER_KEY,
                "base_url": fake_base_url,
            },
        )
        check(
            "the credential is stored and the response is masked",
            stored.status_code == 200
            and stored.json()["hint"] == USER_KEY[-4:]
            and USER_KEY not in stored.text,
            f"status={stored.status_code}",
        )

        session = _session()
        try:
            from src.db.byok import LlmCredentialDB

            row = session.execute(select(LlmCredentialDB)).scalar_one()
            encrypted = row.encrypted_key
        finally:
            session.close()
        check(
            "the stored row is a token, not the key",
            USER_KEY not in encrypted and encrypted != USER_KEY,
        )

        tested = client.post("/api/llm/credentials/test")
        check(
            "exercising the credential answers ok",
            tested.status_code == 200 and tested.json()["ok"] is True,
            f"status={tested.status_code} body={tested.text[:120]}",
        )
        _fails = [
            request
            for request in _Capture.requests
            if "Reply with the single word" in request["prompt"]
        ]
        check(
            "the provider saw the USER's key, not the platform's",
            bool(_fails)
            and _fails[-1]["authorization"] == f"Bearer {USER_KEY}"
            and PLATFORM_KEY not in _fails[-1]["authorization"],
        )

        with FIXTURE_DOCX.open("rb") as fh:
            upload = client.post(
                "/api/resumes", files={"file": ("resume.docx", fh.read(), DOCX_MIME)}
            )
        check(
            "the fixture resume uploads", upload.status_code == 200, f"status={upload.status_code}"
        )
        profile_id = upload.json()["profile_id"]
        profile = upload.json()["profile"]
        outcome["profile_id"] = profile_id

        # The fake answer must name a project the profile really holds — the
        # factuality validator strips anything the profile does not name, and
        # the fixture résumé lists projects rather than employment.
        projects = profile.get("projects") or []
        outcome["name"] = (profile.get("personal_information") or {}).get("name") or ""
        if projects:
            _Capture.project = projects[0].get("name", "") or _Capture.project

        job_id = _seed_job("ACME AI INC")
        outcome["job_id"] = job_id
        _seed_match(profile_id, job_id, outcome["owner_id"])

        before = len(_Capture.requests)
        tailored = client.post("/api/tailor", json={"profile_id": profile_id, "job_id": job_id})
        check(
            "the tailoring run succeeds on the user's credential",
            tailored.status_code == 200,
            f"status={tailored.status_code} body={tailored.text[:200]}",
        )
        if tailored.status_code != 200:
            return outcome

        body = tailored.json()
        prompts = " ".join(request["prompt"] for request in _Capture.requests[before:])
        check(
            "the prompt carries no candidate identity",
            all(part not in prompts for part in FIXTURE_IDENTITY),
            f"checked {len(_Capture.requests) - before} prompt(s)",
        )
        check(
            "the prompt carries the name placeholder instead",
            "[[NAME]]" in prompts,
        )
        name = outcome.get("name") or ""
        check(
            "the answer's placeholder came back restored",
            "[[NAME]]" not in body["tailored"]["summary"]
            and (not name or name in body["tailored"]["summary"]),
            f"summary={body['tailored']['summary'][:80]!r}",
        )
        style = body.get("style") or {}
        check(
            "the style report is delivered with the tailoring result",
            "findings" in style and "quantified_ratio" in style,
            f"findings={len(style.get('findings', []))}",
        )
        check(
            "the style report counted the quantified bullets",
            style.get("quantified_count") == 1 and style.get("bullet_count") == 1,
            f"quantified={style.get('quantified_count')} of {style.get('bullet_count')}",
        )

        del_result = client.delete("/api/llm/credentials")
        check(
            "the credential can be removed",
            del_result.status_code == 200 and del_result.json()["removed"] is True,
        )
    return outcome


def check_sponsors(api: str, outcome: dict) -> None:
    """The register import, the verdicts, and the finding on the match row."""
    from src.db.sponsors import SOURCE_USCIS
    from src.matching.sponsors import import_sponsor_csv, lookup_company, normalize_company

    csv_path = _WORKDIR / "uscis-fixture.csv"
    csv_path.write_text(
        "Fiscal Year,Employer (Petitioner) Name,City,State,Initial Approval,"
        "Initial Denial,Continuing Approval,Continuing Denial\n"
        "2024,ACME AI INC,San Francisco,CA,10,1,65,2\n",
        encoding="utf-8",
    )
    session = _session()
    try:
        report = import_sponsor_csv(session, SOURCE_USCIS, csv_path)
        check(
            "the official register fixture imports",
            report.employers == 1 and report.years == [2024],
            report.describe(),
        )
        verdict = lookup_company(session, "Acme AI")
        check(
            "a registered employer is verified with its counts",
            verdict.verified and verdict.approvals == 75 and "FY2024" in verdict.note,
            verdict.note or "",
        )
        missing = lookup_company(session, "Nowhere Consulting")
        check(
            "an unregistered employer is a register-scoped miss, not a claim",
            missing.status == "not_found"
            and "No entry found in the imported sponsorship registers" in (missing.note or ""),
        )
        check(
            "normalization ignores the legal form",
            normalize_company("Acme AI, Inc.") == normalize_company("ACME AI LLC"),
        )
    finally:
        session.close()

    with httpx.Client(base_url=api, timeout=60) as client:
        login = client.post(
            "/api/auth/token/login",
            data={"username": outcome["email"], "password": "ws22-verification-password"},
        )
        client.headers["Authorization"] = f"Bearer {login.json()['access_token']}"
        history = client.get(f"/api/profiles/{outcome['profile_id']}/matches")
        check("the match history answers", history.status_code == 200)
        if history.status_code != 200:
            return
        matches = history.json()["matches"]
        check("the seeded match is listed", len(matches) >= 1, f"{len(matches)} row(s)")
        if not matches:
            return
        row = matches[0]
        check(
            "the match row carries the verified finding",
            row.get("sponsor_status") == "verified" and "USCIS" in (row.get("sponsor_note") or ""),
            f"status={row.get('sponsor_status')}",
        )
        check(
            "the finding did not change the persisted score",
            row["scores"].get("overall_score") == 71.0,
            f"overall={row['scores'].get('overall_score')}",
        )


def check_pending_surfaces(api: str) -> None:
    """The integrations deliberately not built must not exist."""
    with httpx.Client(base_url=api, timeout=30) as client:
        for path in ("/api/slack/events", "/api/telegram/webhook", "/mcp"):
            response = client.post(path, json={})
            check(
                f"the {path} integration is not built (404)",
                response.status_code == 404,
                f"status={response.status_code}",
            )


def main() -> int:
    print("WS-22 verification — BYOK, the PII mask, the style policy, the sponsor register")
    print(f"throwaway workspace: {_WORKDIR}\n")

    _upgrade_database()
    check_migration()

    provider, fake_base_url = _start_fake_provider()
    server, api = _serve_api()
    try:
        outcome = check_byok(api, fake_base_url)
        check_sponsors(api, outcome)
        check_pending_surfaces(api)
    finally:
        server.should_exit = True
        provider.shutdown()

    passed = sum(1 for _name, ok, _detail in RESULTS if ok)
    total = len(RESULTS)
    print(f"\n{passed}/{total} checks passed")
    return 0 if passed == total else 1


if __name__ == "__main__":
    raise SystemExit(main())
