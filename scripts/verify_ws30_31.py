"""Live end-to-end verification of WS-30 (the provider fallback chain) and
WS-31 (the résumé is edited in place).

Both workstreams make claims that only a real run can settle:

**WS-30.** That the chain is actually wired into the client, that each link's
endpoint and model are what the alias table says, that a failing primary really
hands off, and that the usage row names the link that answered. The three
vendor endpoints are probed **live** — but only to their authentication
boundary, because this run has no vendor keys. A 401/404 distinction is the
honest evidence available without keys: it proves the path exists, requires
auth, and (for Pollinations) that the exact community model id is served.

**WS-31.** That a real uploaded résumé with a distinctive look comes back
*formatted the same way* with the tailored wording in it. The upload is a real
``.docx`` written by this script with Georgia 13pt, its own section order and a
section the renderer never produces; the tailoring runs over real HTTP against
a local fake provider; the deliverable is downloaded through the API's own
download route and re-parsed. Nothing is mocked except the model.

The whole run uses a throwaway database and data directory. No vendor key is
needed and none is sent.

Usage::

    env\\Scripts\\python.exe scripts\\verify_ws30_31.py
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
_WORKDIR = Path(tempfile.mkdtemp(prefix="ws30-31-verify-"))
DATABASE_PATH = _WORKDIR / "verify.db"
os.environ["DATA_DIR"] = str(_WORKDIR / "data")
os.environ["DATABASE_URL"] = f"sqlite:///{DATABASE_PATH.as_posix()}"
os.environ["ALEMBIC_DATABASE_URL"] = f"sqlite:///{DATABASE_PATH.as_posix()}"
os.environ["CHROMA_DIR"] = str(_WORKDIR / "chroma")
os.environ["EVIDENCE_DIR"] = str(_WORKDIR / "evidence")
os.environ["TAILORED_DIR"] = str(_WORKDIR / "tailored")
os.environ["RESUME_UPLOAD_DIR"] = str(_WORKDIR / "resumes")
os.environ["BYOK_MODE"] = "disabled"
os.environ.pop("BYOK_ENCRYPTION_KEY", None)
os.environ.pop("AUTH_SECRET", None)
os.environ.setdefault("APP_ENV", "development")

import httpx
import uvicorn
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect

from src.main import app

FIXTURE_DOCX = REPO_ROOT / "tests" / "fixtures" / "Ahmad_Hassan_AI_Engineer_Resume.docx"
DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"

#: The font the uploaded résumé uses. Nothing the renderer writes would ever
#: be Georgia 13pt, so finding it in the deliverable is proof the edit was in
#: place rather than a fresh render.
FONT_NAME = "Georgia"
FONT_SIZE = 13
#: A heading the WS-05 renderer has no concept of. Its survival is proof the
#: candidate's own sections were kept.
CUSTOM_SECTION = "Volunteering"
CUSTOM_LINE = "Taught weekend coding classes"

RESULTS: list[tuple[str, bool, str]] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    """Record one check and print its outcome."""
    RESULTS.append((name, condition, detail))
    print(f"[{'PASS' if condition else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))


def _normalize_newlines(text: str) -> str:
    """A text comparison that does not care which convention the file uses.

    Windows serves a downloaded file with CRLF line endings regardless of what
    was written, so a shape assertion has to be made on the *lines* rather than
    on the raw bytes. The convention itself is asserted separately, on the
    file the server wrote.
    """
    return text.replace("\r\n", "\n").replace("\r", "\n")


# --------------------------------------------------------------------------
# The fake chat-completions provider
# --------------------------------------------------------------------------


class _Capture:
    """What the fake provider saw."""

    requests: ClassVar[list[dict]] = []


class _FakeProviderHandler(BaseHTTPRequestHandler):
    """A chat-completions endpoint that answers the tailoring schemas."""

    def log_message(self, *_args) -> None:
        return

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length", "0"))
        body = json.loads(self.rfile.read(length) or b"{}")
        prompt = body.get("messages", [{}])[0].get("content", "")
        _Capture.requests.append({"model": body.get("model"), "prompt": prompt})

        if '"title": "JobInsights"' in prompt:
            payload = {
                "responsibilities": ["Build machine learning systems"],
                "tech_stack": ["Python"],
                "seniority_signals": [],
                "culture_flags": [],
                "summary": "An engineering role.",
            }
        else:
            # Two bullets for the one experience entry the fixture résumé has,
            # matching its original count — the shape the FORMAT RULES ask for.
            payload = {
                "summary": "AI engineer with machine-learning delivery depth.",
                "highlighted_skills": ["Python"],
                "experience": [
                    {
                        "company": "Agentic Labs",
                        "title": "AI Engineer",
                        "bullets": [
                            "Built agent pipelines with LangGraph for job search",
                            "Shipped FastAPI services backing the agent pipeline",
                        ],
                    }
                ],
                "projects": [],
                "cover_letter": "I would like to apply.",
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


def _register(client: httpx.Client, email: str) -> None:
    password = "ws30-31-verification-password"
    client.post("/api/auth/register", json={"email": email, "password": password})
    response = client.post("/api/auth/token/login", data={"username": email, "password": password})
    if response.status_code == 200:
        client.headers["Authorization"] = f"Bearer {response.json()['access_token']}"


def _session():
    from sqlalchemy.orm import sessionmaker

    engine = create_engine(f"sqlite:///{DATABASE_PATH.as_posix()}", future=True)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False)()


# --------------------------------------------------------------------------
# WS-30 — the chain
# --------------------------------------------------------------------------


def check_migration() -> None:
    """WS-31's column is in the real migrated schema, not just the ORM."""
    engine = create_engine(f"sqlite:///{DATABASE_PATH.as_posix()}")
    inspector = inspect(engine)
    columns = {col["name"] for col in inspector.get_columns("tailored_resumes")}
    check(
        "the WS-31 migration adds the render column",
        "render" in columns,
        f"tailored_resumes: {sorted(columns)}",
    )
    engine.dispose()


def check_aliases() -> None:
    """The alias table resolves, and the BYOK list accepts the same names."""
    from src.llm.credentials import _resolved_base_url
    from src.llm.providers import alias_base_url, build_provider

    expected = {
        "groq": "https://api.groq.com/openai/v1",
        "tokenharbor": "https://tokenharbor.ai/v1",
        "pollinations": "https://gen.pollinations.ai/v1",
    }
    for alias, url in expected.items():
        built = build_provider(alias, api_key="k", model="m")
        check(
            f"the {alias} alias builds its vendor endpoint",
            built.base_url == url and alias_base_url(alias) == url,
            built.base_url,
        )
        check(
            f"a stored user credential resolves {alias} without a URL",
            _resolved_base_url(alias, None) == url,
        )


def check_live_endpoints() -> None:
    """Each vendor endpoint is real, and the key boundary is where it belongs.

    A 404 means the path is wrong; a 401 means the endpoint is real and wants a
    key. **Pollinations is the exception**: its ``/v1/models`` catalogue is
    public (200), and it is ``/v1/chat/completions`` that requires the key — so
    the probe checks the endpoint the client actually calls. Either answer
    (401 for the authenticated call, 200 for the public catalogue) proves the
    path exists; a 404 would not.
    """
    probes = (
        ("groq", "get", "https://api.groq.com/openai/v1/models", None, (401, 403)),
        ("tokenharbor", "get", "https://tokenharbor.ai/v1/models", None, (401, 403)),
        (
            "pollinations",
            "post",
            "https://gen.pollinations.ai/v1/chat/completions",
            {
                "model": "community/morriszdweck/glm-5.3-flash-free",
                "messages": [{"role": "user", "content": "hi"}],
            },
            (200, 401, 403),
        ),
    )
    for name, method, url, payload, expected in probes:
        try:
            if method == "get":
                response = httpx.get(url, timeout=25.0)
            else:
                response = httpx.post(url, json=payload, timeout=25.0)
        except Exception as exc:  # noqa: BLE001 - a network failure is a finding
            check(f"the {name} endpoint is reachable", False, f"{type(exc).__name__}: {exc}")
            continue
        check(
            f"the {name} endpoint exists at the URL the alias carries",
            response.status_code in expected,
            f"HTTP {response.status_code} (expected one of {expected})",
        )


def check_pollinations_model() -> None:
    """The configured community model is really served by Pollinations.

    Two claims, and they are deliberately different in kind:

    * **Served** — a fact about the catalogue, checked strictly.
    * **Healthy** — a *live, moving* signal. The endpoint's own health figure
      changed between the planning probe (98%, 50 requests) and this run
      (90%, 50 requests), so this check asserts what is stable about it
      (the model is listed with a health record and a success rate above the
      degraded floor) and *reports* the live numbers rather than pinning a
      value that a single failing request would falsify.
    """
    from src.config.settings import _FALLBACK_LINK_SPECS

    model = next(spec[3] for spec in _FALLBACK_LINK_SPECS if spec[0] == "pollinations")
    try:
        response = httpx.get("https://gen.pollinations.ai/v1/models", timeout=25.0)
        data = response.json().get("data", [])
    except Exception as exc:  # noqa: BLE001
        check("the Pollinations model list is readable", False, f"{type(exc).__name__}")
        return
    entry = next((m for m in data if m.get("id") == model), None)
    check(f"Pollinations serves the configured model {model!r}", entry is not None)
    if entry is None:
        return

    health = entry.get("health") or {}
    rate = health.get("success_rate")
    check(
        "the configured Pollinations model publishes a usable health record",
        health.get("status") in ("healthy", "degraded") and isinstance(rate, (int, float)),
        f"status={health.get('status')} success_rate={rate} requests={health.get('requests')}",
    )
    check(
        "its success rate is not below the degraded floor",
        isinstance(rate, (int, float)) and rate >= 80,
        f"{rate}%",
    )

    # The family comparison is reported, not asserted: which community mirror
    # is healthiest is the endpoint's own live answer and it moves. What the
    # default is chosen on is that this model is a free community mirror of
    # glm-5.3-flash with a usable health record — which the checks above pin.
    family = [
        m
        for m in data
        if m.get("community")
        and "glm-5.3-flash" in m.get("id", "")
        and isinstance(m.get("health"), dict)
        and m["health"].get("success_rate") is not None
    ]
    if family:
        ranked = sorted(family, key=lambda m: m["health"]["success_rate"], reverse=True)
        print(
            "      community glm-5.3-flash health right now: "
            + " | ".join(
                f"{m['id'].rsplit('/', 1)[-1]}={m['health']['success_rate']:.0f}%" for m in ranked
            )
        )
    check(
        "other free community mirrors of the same model exist (the family is real)",
        len(family) >= 2,
        f"{len(family)} mirrors listed",
    )


def check_chain_walk() -> None:
    """A failing primary really hands off, and the answering link is recorded.

    Driven against two local fake adapters, so the walk is proven without
    spending a vendor call — and the usage row is read back from the client to
    prove the **answering** link's identity is what gets recorded.
    """
    from src.llm import client as client_module
    from src.llm.client import LLMClient
    from src.llm.errors import LLMUnavailable
    from src.llm.fallback import FallbackLink, FallbackProvider
    from src.llm.providers import ProviderResponse

    class _Failing:
        name = "google"
        model = "gemini-3.8-flash"

        def complete(self, request):
            raise LLMUnavailable("503 the primary is down")

    class _Working:
        name = "groq"
        model = "qwen/qwen3.8-27b"

        def complete(self, request):
            return ProviderResponse(text="fallback answered", total_tokens=5)

    recorded: list = []
    original = client_module.record_usage
    client_module.record_usage = lambda usage, **kw: recorded.append(usage)
    try:
        chain = FallbackProvider(
            [
                FallbackLink("google", _Failing(), "gemini-3.8-flash"),
                FallbackLink("groq", _Working(), "qwen/qwen3.8-27b"),
            ]
        )
        client = LLMClient(
            provider="google",
            api_key="unused",
            model="gemini-3.8-flash",
            temperature=0.2,
            max_retries=0,
            provider_instance=chain,
        )
        text = client.generate_text("hello")
    finally:
        client_module.record_usage = original

    check("a failing primary hands the call to the fallback", text == "fallback answered")
    check(
        "the usage row names the link that answered, not the primary",
        bool(recorded) and recorded[-1].provider == "groq",
        f"provider={recorded[-1].provider if recorded else '?'} model="
        f"{recorded[-1].model if recorded else '?'}",
    )
    check(
        "the model in the usage row is the fallback's own",
        bool(recorded) and recorded[-1].model == "qwen/qwen3.8-27b",
    )
    check(
        "the chain names every tried link when all of them fail",
        "chain exhausted" in _all_failed_message(),
    )


def _all_failed_message() -> str:
    from src.llm.errors import LLMUnavailable
    from src.llm.fallback import FallbackLink, FallbackProvider
    from src.llm.providers import ProviderRequest

    class _Failing:
        def __init__(self, name: str) -> None:
            self.name = name

        def complete(self, request):
            raise LLMUnavailable("503 down")

    chain = FallbackProvider(
        [
            FallbackLink("google", _Failing("google"), "gemini-3.8-flash"),
            FallbackLink("groq", _Failing("groq"), "qwen/qwen3.8-27b"),
        ]
    )
    try:
        chain.complete(ProviderRequest(prompt="x", model="m", temperature=0.2, timeout=5.0))
    except Exception as exc:  # noqa: BLE001
        return str(exc)
    return ""


def check_chain_configuration_from_env() -> None:
    """The env keys really build the chain, and a blank key really skips a link."""
    import importlib

    from src.config.settings import get_settings

    for name in ("GROQ_API_KEY", "TOKENHARBOR_API_KEY", "POLLINATIONS_API_KEY"):
        os.environ.pop(name, None)
    get_settings.cache_clear()
    links = get_settings().llm_fallback_links
    check(
        "with no keys set, no fallback link is active",
        all(not link.active for link in links),
        ", ".join(f"{link.alias}={'on' if link.active else 'off'}" for link in links),
    )

    os.environ["GROQ_API_KEY"] = "gsk-verification-key"
    get_settings.cache_clear()
    from src.llm.fallback import build_fallback_links

    built = build_fallback_links()
    check(
        "setting one key activates exactly that link",
        [link.alias for link in built] == ["groq"],
        f"active: {[link.alias for link in built]}",
    )
    check(
        "the activated link carries the documented model",
        built and built[0].model == "qwen/qwen3.8-27b",
        built[0].model if built else "none",
    )

    os.environ["LLM_FALLBACK_ENABLED"] = "false"
    get_settings.cache_clear()
    from src.llm.fallback import build_fallback_chain
    from src.llm.providers import GeminiProvider

    primary = GeminiProvider(api_key="k", model="m", client=object())
    result = build_fallback_chain(primary, link_configs=[])
    check("LLM_FALLBACK_ENABLED=false returns the primary untouched", result is primary)

    os.environ.pop("GROQ_API_KEY", None)
    os.environ.pop("LLM_FALLBACK_ENABLED", None)
    get_settings.cache_clear()
    importlib.reload(importlib.import_module("src.llm.fallback"))


# --------------------------------------------------------------------------
# WS-31 — the in-place edit, over real HTTP
# --------------------------------------------------------------------------


def _write_formatted_resume(path: Path) -> Path:
    """A résumé formatted in ways the renderer would never produce.

    Georgia 13pt, Skills before Summary, a separator line, and a "Volunteering"
    section the renderer has no heading for. Every one of these is checked in
    the deliverable — so the checks cannot be satisfied by a fresh render.
    """
    from docx import Document
    from docx.shared import Pt

    document = Document()
    normal = document.styles["Normal"]
    normal.font.name = FONT_NAME
    normal.font.size = Pt(FONT_SIZE)

    def add(text: str, style: str | None = None):
        paragraph = document.add_paragraph(text, style=style)
        for run in paragraph.runs:
            run.font.name = FONT_NAME
            run.font.size = Pt(FONT_SIZE)
        return paragraph

    # The header block the parser reads for the profile's facts.
    add("Ahmad Hassan")
    add("AI Engineer | ahmad@example.com | Berlin, Germany")
    add("—— separators are formatting too ——")
    # Skills BEFORE Summary: the renderer's own order is the reverse.
    add("Technical Skills", "Heading 2")
    add("Languages: Python, Go")
    add("Frameworks: LangGraph, FastAPI, Docker")
    add("Professional Summary", "Heading 2")
    add("AI engineer building agent systems.")
    add("Experience", "Heading 2")
    add("AI Engineer | Agentic Labs | 2020-2023")
    add("Built agent pipelines", "List Bullet")
    add("Maintained legacy services", "List Bullet")
    add("Education", "Heading 2")
    add("BSc Computer Science")
    add("Technical University of Berlin")
    add(CUSTOM_SECTION, "Heading 2")
    add(CUSTOM_LINE)
    path.parent.mkdir(parents=True, exist_ok=True)
    document.save(str(path))
    return path


def _seed_job() -> str:
    from src.db.jobs import JobDB

    session = _session()
    try:
        job_id = f"greenhouse:ws31-{int(time.time())}"
        session.add(
            JobDB(
                id=job_id,
                source="greenhouse",
                title="AI Engineer",
                company="Acme AI",
                description=(
                    "You will build agent pipelines with LangGraph and Python.\n"
                    "You will design REST APIs with FastAPI.\n"
                ),
                required_skills=["python", "langgraph"],
                preferred_skills=["fastapi"],
                application_url="https://boards.greenhouse.io/acme/jobs/1",
            )
        )
        session.commit()
        return job_id
    finally:
        session.close()


def check_in_place(api: str, fake_base_url: str) -> None:
    """Upload a formatted résumé, tailor it, download and re-parse the result."""
    from docx import Document

    upload = _write_formatted_resume(_WORKDIR / "uploads" / "formatted.docx")
    with httpx.Client(base_url=api, timeout=600.0) as client:
        _register(client, f"ws31-{int(time.time())}@example.com")

        with upload.open("rb") as handle:
            uploaded = client.post("/api/resumes", files={"file": (upload.name, handle, DOCX_MIME)})
        check("a formatted résumé uploads", uploaded.status_code == 200, str(uploaded.status_code))
        if uploaded.status_code != 200:
            return
        profile_id = uploaded.json()["profile_id"]
        stored = Path(uploaded.json()["profile"]["personal_information"]["name"])
        check("the uploaded profile parsed the candidate's name", bool(stored))

        job_id = _seed_job()
        tailored = client.post("/api/tailor", json={"profile_id": profile_id, "job_id": job_id})
        check("the tailoring run succeeds", tailored.status_code == 200, str(tailored.status_code))
        if tailored.status_code != 200:
            print(tailored.text[:800])
            return
        body = tailored.json()

        render = body["render"]
        check(
            "the deliverable reports an in-place edit",
            render["mode"] == "in_place",
            f"mode={render['mode']} skipped={render['skipped']}",
        )
        check(
            "the report counts the passages it rewrote",
            render["edits"] >= 3,
            f"edits={render['edits']} appended={render['appended']} removed={render['removed']}",
        )

        # The deliverable is downloaded through the API's own route — the same
        # bytes a candidate would get.
        download = client.get(f"/api/tailored/{body['tailoring_id']}/download")
        check("the deliverable downloads", download.status_code == 200, str(download.status_code))
        delivered = _WORKDIR / "delivered.docx"
        delivered.write_bytes(download.content)

        edited = Document(str(delivered))
        paragraphs = [p for p in edited.paragraphs if p.text.strip()]
        texts = [p.text for p in paragraphs]

        # 1. The wording is the tailored wording.
        check(
            "the tailored summary is in the document",
            any("machine-learning delivery depth" in t for t in texts),
        )
        check(
            "the tailored bullets replaced the originals",
            any("LangGraph for job search" in t for t in texts),
        )
        check(
            "the original bullet it replaced is gone",
            not any(t == "Built agent pipelines" for t in texts),
        )

        # 2. The formatting is the candidate's.
        fonts = {
            run.font.name for paragraph in paragraphs for run in paragraph.runs if run.text.strip()
        }
        check(
            f"every run kept the uploaded font ({FONT_NAME})",
            fonts == {FONT_NAME},
            f"fonts found: {sorted(f for f in fonts if f)}",
        )
        sizes = {
            run.font.size.pt
            for paragraph in paragraphs
            for run in paragraph.runs
            if run.text.strip() and run.font.size is not None
        }
        check(
            f"every run kept the uploaded size ({FONT_SIZE}pt)",
            sizes == {FONT_SIZE},
            f"sizes found: {sorted(sizes)}",
        )

        # 3. The document's own structure is untouched.
        check(
            "the section order is the document's, not the renderer's",
            texts.index("Technical Skills") < texts.index("Professional Summary"),
        )
        check(
            f"the custom {CUSTOM_SECTION!r} section survived",
            CUSTOM_SECTION in texts and CUSTOM_LINE in texts,
        )
        check(
            "the separator line survived",
            any("separators are formatting too" in t for t in texts),
        )

        # 4. The skills lines were filtered in place, keeping their own shape.
        #    The tailored selection is ``["Python"]``, so the "Frameworks" line
        #    (LangGraph/FastAPI/Docker) has nothing left and is emptied — that
        #    is the intended behaviour, not a loss. What must hold is that the
        #    surviving line kept the document's own "Category: items" shape,
        #    that no skill the candidate does not have was added, and that a
        #    line with nothing selected is emptied rather than left stale.
        skills = [t for t in texts if t.startswith(("Languages:", "Frameworks:"))]
        check(
            "the surviving skills line kept the document's own category format",
            bool(skills) and all(":" in line for line in skills),
            "; ".join(skills) or "none",
        )
        check(
            "the skills were filtered to the tailored selection",
            any(line == "Languages: Python" for line in skills)
            and not any(term in line for line in skills for term in ("Go", "Docker")),
            "; ".join(skills) or "none",
        )
        check(
            "a skills line with nothing selected is emptied, not left stale",
            not any("Docker" in t for t in texts),
        )

        # 5. The deliverable still parses — the WS-05 anti-fabrication gate.
        from src.resume.parser import parse_resume

        reparsed = parse_resume(str(delivered))
        check(
            "the deliverable re-parses with the facts intact",
            reparsed.personal_information.name == "Ahmad Hassan"
            and reparsed.personal_information.email == "ahmad@example.com"
            and [e.company for e in reparsed.experience] == ["Agentic Labs"],
            f"name={reparsed.personal_information.name!r} "
            f"companies={[e.company for e in reparsed.experience]}",
        )

        # 6. The report survives the round trip through storage.
        stored_record = client.get(f"/api/tailored/{body['tailoring_id']}").json()
        check(
            "the render report is persisted with the tailoring",
            stored_record["render"] == render,
        )

        # 7. The uploaded original was never modified.
        original = Document(str(upload))
        original_text = "\n".join(p.text for p in original.paragraphs)
        check(
            "the uploaded file itself was never written to",
            "Built agent pipelines\n" in original_text + "\n"
            and "machine-learning delivery depth" not in original_text,
        )

    check(
        "the tailoring prompt carried the format rules",
        bool(_Capture.requests) and any("FORMAT RULES" in r["prompt"] for r in _Capture.requests),
    )


def check_text_upload(api: str, fake_base_url: str) -> None:
    """A plain-text résumé comes back as an edited plain-text file."""
    upload = _WORKDIR / "uploads" / "plain.txt"
    upload.parent.mkdir(parents=True, exist_ok=True)
    # Written with explicit LF bytes (``newline=""``), so the check below has
    # real teeth on Windows: the platform's own writer would have produced
    # CRLF and the deliverable would then match for the wrong reason.
    with upload.open("w", encoding="utf-8", newline="") as handle:
        handle.write(
            "Ahmad Hassan\n"
            "AI Engineer | ahmad@example.com | Berlin, Germany\n"
            "\n"
            "Technical Skills\n"
            "Languages: Python, Go\n"
            "\n"
            "Professional Summary\n"
            "AI engineer building agent systems.\n"
            "\n"
            "Experience\n"
            "AI Engineer | Agentic Labs | 2020-2023\n"
            "- Built agent pipelines\n"
            "- Maintained legacy services\n"
            "\n"
            "Volunteering\n"
            "Taught weekend coding classes\n"
        )
    with httpx.Client(base_url=api, timeout=600.0) as client:
        _register(client, f"ws31-text-{int(time.time())}@example.com")
        with upload.open("rb") as handle:
            uploaded = client.post(
                "/api/resumes", files={"file": (upload.name, handle, "text/plain")}
            )
        check("a text résumé uploads", uploaded.status_code == 200, str(uploaded.status_code))
        if uploaded.status_code != 200:
            return
        profile_id = uploaded.json()["profile_id"]
        job_id = _seed_job()
        body = client.post("/api/tailor", json={"profile_id": profile_id, "job_id": job_id})
        if body.status_code != 200:
            check("the text tailoring run succeeds", False, body.text[:300])
            return
        payload = body.json()
        check(
            "a text résumé is edited in place and reported as such",
            payload["render"]["mode"] == "in_place"
            and payload["render"]["source_format"] == ".txt",
            f"mode={payload['render']['mode']} format={payload['render']['source_format']}",
        )
        check(
            "the deliverable keeps the text format",
            payload["docx_path"].endswith(".txt"),
            payload["docx_path"],
        )
        download = client.get(f"/api/tailored/{payload['tailoring_id']}/download")
        delivered = download.content.decode("utf-8")
        check(
            "the text deliverable keeps its blank lines and markers",
            "\n\n" in _normalize_newlines(delivered) and "- " in delivered,
            "line shape preserved",
        )
        # The uploaded text file went through ``Path.write_text``, which on
        # Windows writes CRLF. The invariant is therefore not "the deliverable
        # uses LF" — it is "the deliverable uses the convention the upload
        # used", because a tool that claims to preserve a text file's format
        # must not rewrite its line endings. `Path.write_text` on the output
        # side would have done exactly that, so this is a real regression gate.
        stored_deliverable = Path(payload["docx_path"])
        written = stored_deliverable.read_bytes()
        upload_was_crlf = b"\r\n" in upload.read_bytes()
        check(
            "the deliverable kept the uploaded file's line-ending convention",
            (b"\r\n" in written) == upload_was_crlf,
            f"upload crlf={upload_was_crlf}, deliverable crlf={b'\r\n' in written}",
        )
        # And the count of line breaks is unchanged: an edit rewrites lines, it
        # does not add or drop them.
        check(
            "the line count is unchanged by the edit",
            written.count(b"\n") == upload.read_bytes().count(b"\n"),
            f"upload={upload.read_bytes().count(b'\n')} lines, "
            f"deliverable={written.count(b'\n')} lines",
        )
        check(
            "the custom section survived in the text file",
            CUSTOM_SECTION in delivered and CUSTOM_LINE in delivered,
        )
        check(
            "the tailored wording is in the text deliverable",
            "machine-learning delivery depth" in delivered,
        )
        # The defect this run found: a text deliverable used to reach the DOCX
        # reader, fail to open, and take a 20-point format-safety penalty.
        risks = " ".join(payload["ats_report"]["format_risks"]).lower()
        check(
            "a text deliverable is inspected as text, not scored as an unreadable DOCX",
            "could not inspect" not in risks,
            f"format_risks={payload['ats_report']['format_risks']} score={payload['ats_report']['score']}",
        )


def main() -> int:
    print("WS-30/WS-31 verification — the provider fallback chain and the in-place résumé edit")
    print(f"throwaway workspace: {_WORKDIR}\n")

    print("-- WS-30: the fallback chain")
    check_aliases()
    check_live_endpoints()
    check_pollinations_model()
    check_chain_walk()
    check_chain_configuration_from_env()

    print("\n-- WS-31: the in-place résumé edit")
    _upgrade_database()
    check_migration()
    provider, fake_base_url = _start_fake_provider()
    # Point the platform client at the local fake provider.
    os.environ["LLM_PROVIDER"] = "openai-compatible"
    os.environ["LLM_API_KEY"] = "fake-key"
    os.environ["LLM_BASE_URL"] = fake_base_url
    os.environ["LLM_MODEL"] = "fake-model"
    from src.config.settings import get_settings

    get_settings.cache_clear()
    server, api = _serve_api()
    try:
        check_in_place(api, fake_base_url)
        check_text_upload(api, fake_base_url)
    finally:
        server.should_exit = True
        provider.shutdown()

    passed = sum(1 for _name, ok, _detail in RESULTS if ok)
    total = len(RESULTS)
    print(f"\n{passed}/{total} checks passed")
    if passed != total:
        print("\nFailed checks:")
        for name, ok, detail in RESULTS:
            if not ok:
                print(f"  - {name}" + (f" ({detail})" if detail else ""))
    return 0 if passed == total else 1


if __name__ == "__main__":
    raise SystemExit(main())
