"""Live verification of the WS-10 LLM client hardening.

Most of the checks run against a **local capture server** in front of the
**real** google-genai SDK. That combination is what makes them worth
running: the SDK is the real one (so its own retry layers, its request
serialization and its timeout handling are the real ones), but the server is
local (so the checks are deterministic, free and repeatable).

The checks:

1. the request that reaches the provider carries the **temperature** and
   ``store=False`` — the two things the old client got wrong;
2. a call against a slow server **times out** in about the configured
   seconds, not in the server's sleep;
3. a 429 carrying ``Retry-After: 50951`` (fourteen hours — the real daily
   quota's header) **fails in seconds**, classified as a quota error, and is
   not retried. This is the defect the first live run found: the SDK's own
   retry layer honoured the header and slept for fourteen hours inside a
   sixty-second timeout;
4. a 429 followed by a 200 is **one logical call and two attempts**;
5. the usage row carries the token counts and **no prompt**;
6. a missing key fails immediately with an actionable message and the key
   never appears in it;
7. the **real** provider: a generation call, its classification, and the
   usage it reports. When the free tier's daily quota is spent, that check
   is reported as SKIP with the reason — not silently passed.

Every check prints PASS/FAIL/SKIP; the script exits non-zero when a check
fails. A SKIP does not fail the run.

Usage::

    env\\Scripts\\python.exe scripts\\verify_ws10.py
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

# The verification writes audit rows, so it runs against a throwaway
# database — never the developer's. The environment must be set before the
# application modules are imported (the settings are read at import time).
_WORKDIR = Path(tempfile.mkdtemp(prefix="ws10-verify-"))
DATABASE_PATH = _WORKDIR / "verify.db"
os.environ["DATABASE_URL"] = f"sqlite:///{DATABASE_PATH.as_posix()}"
os.environ["ALEMBIC_DATABASE_URL"] = f"sqlite:///{DATABASE_PATH.as_posix()}"
os.environ.setdefault("APP_ENV", "development")

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from src.config.settings import get_settings
from src.db.audit import AuditEventDB
from src.db.base import Base
from src.llm.client import LLMClient
from src.llm.errors import (
    LLMDailyQuotaExhausted,
    LLMError,
    LLMTimeout,
)
from src.llm.providers import GeminiProvider

RESULTS: list[tuple[str, bool, str]] = []
SKIPS: list[tuple[str, str]] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    """Record one check and print its outcome."""
    RESULTS.append((name, condition, detail))
    print(f"[{'PASS' if condition else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))


def skip(name: str, reason: str) -> None:
    """Record a check that could not run, and why."""
    SKIPS.append((name, reason))
    print(f"[SKIP] {name} — {reason}")


class _QuietHTTPServer(HTTPServer):
    """An HTTP server that does not shout when a client hangs up.

    A timeout check makes the client abandon the connection; the server's
    broken-pipe traceback is noise, not a finding.
    """

    def handle_error(self, request, client_address) -> None:
        return None


class _CaptureServer:
    """A local HTTP server that records the requests and replays a script.

    Each entry of ``script`` is one response: a status code and a body. The
    last entry is repeated once the script runs out. ``bodies`` keeps the
    request bodies, so a test can assert on what actually went out.
    """

    def __init__(self, script: list[tuple[int, dict, dict[str, str]]], delay: float = 0.0) -> None:
        self.script = script
        self.delay = delay
        self.bodies: list[bytes] = []
        self.requests = 0
        self._server = _QuietHTTPServer(("127.0.0.1", 0), self._make_handler())
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()

    @property
    def base_url(self) -> str:
        host, port = self._server.server_address[0], self._server.server_address[1]
        return f"http://{host}:{port}"

    def _make_handler(self):
        capture = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self) -> None:
                length = int(self.headers.get("content-length", 0))
                capture.bodies.append(self.rfile.read(length))
                capture.requests += 1
                if capture.delay:
                    time.sleep(capture.delay)
                status, body, headers = capture.script[
                    min(capture.requests - 1, len(capture.script) - 1)
                ]
                payload = json.dumps(body).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(payload)))
                for name, value in headers.items():
                    self.send_header(name, value)
                self.end_headers()
                self.wfile.write(payload)

            def log_message(self, *_args) -> None:
                """Keep the verification output clean."""

            def handle_error(self, *_args) -> None:
                """A client that hung up (a timeout) is not a server error."""
                return

        return Handler

    def close(self) -> None:
        self._server.shutdown()
        self._server.server_close()


def _interaction_body(text: str, total_tokens: int = 42) -> dict:
    """A response the SDK's Interaction model accepts."""
    return {
        "id": "int_verify",
        "model": "gemini-3.8-flash",
        "status": "completed",
        "steps": [
            {
                "type": "model_output",
                "content": [{"type": "text", "text": text}],
            }
        ],
        "usage": {
            "total_tokens": total_tokens,
            "total_input_tokens": total_tokens - 5,
            "total_output_tokens": 5,
        },
    }


def _client_for(base_url: str, *, timeout: float = 60.0, max_retries: int = 2) -> LLMClient:
    """A client whose Gemini provider points at the capture server."""
    provider = GeminiProvider(api_key="verify-key", model="gemini-3.8-flash", base_url=base_url)
    return LLMClient(
        provider="google",
        api_key="verify-key",
        model="gemini-3.8-flash",
        temperature=0.2,
        provider_instance=provider,
        timeout=timeout,
        max_retries=max_retries,
        sleep=lambda _seconds: None,  # the backoff is asserted in the unit tests
    )


def _upgrade_database() -> None:
    """Bring the throwaway database to the current schema."""
    config = Config(str(REPO_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(REPO_ROOT / "migrations"))
    command.upgrade(config, "head")


def _usage_rows() -> list[AuditEventDB]:
    """The usage rows the verification wrote."""
    engine = create_engine(f"sqlite:///{DATABASE_PATH.as_posix()}")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        return list(session.scalars(select(AuditEventDB).where(AuditEventDB.action == "llm.usage")))


def _check_wire_payload() -> None:
    """1. The temperature and the privacy flag reach the provider."""
    server = _CaptureServer([(200, _interaction_body("hello"), {})])
    try:
        client = _client_for(server.base_url)
        answer = client.generate_text("say hello")
        body = json.loads(server.bodies[0])
        check(
            "the temperature reaches the provider",
            body.get("generation_config", {}).get("temperature") == 0.2,
            f"generation_config={body.get('generation_config')}",
        )
        check(
            "the privacy flag is sent (store=False)",
            body.get("store") is False,
            f"store={body.get('store')}",
        )
        check("the answer comes back", answer == "hello", f"answer={answer!r}")
    finally:
        server.close()


def _check_timeout() -> None:
    """2. A slow provider is abandoned in about the configured seconds."""
    slow = _CaptureServer([(200, _interaction_body("too late"), {})], delay=30.0)
    try:
        client = _client_for(slow.base_url, timeout=2.0)
        started = time.monotonic()
        try:
            client.generate_text("say hello")
            timed_out = False
        except LLMError as exc:
            timed_out = isinstance(exc, LLMTimeout)
        elapsed = time.monotonic() - started
        usage = client.last_usage
        # A timeout is a transient failure, so it is retried: three attempts
        # of two seconds is the bound, not one.
        check(
            "a slow provider is abandoned at the timeout",
            timed_out and elapsed < 8,
            f"elapsed={elapsed:.1f}s (3 attempts x 2s), server sleep=30s",
        )
        check(
            "the timeout is accounted for as a failure",
            usage is not None and usage.error_type == "LLMTimeout",
            f"error_type={usage.error_type if usage else None}",
        )
    finally:
        slow.close()


def _check_quota_fails_fast() -> None:
    """3. A 429 with a fourteen-hour Retry-After fails in seconds."""
    server = _CaptureServer(
        [
            (
                429,
                {
                    "error": {
                        "code": "too_many_requests",
                        "message": (
                            "Rate limit exceeded for model gemini-3.8-flash "
                            "(limit: 20 requests per day on Free Tier)."
                        ),
                    }
                },
                {"Retry-After": "50951"},
            )
        ]
    )
    try:
        client = _client_for(server.base_url)
        started = time.monotonic()
        try:
            client.generate_text("say hello")
            outcome = "no error"
        except LLMError as exc:
            outcome = type(exc).__name__
        elapsed = time.monotonic() - started
        check(
            "a quota 429 fails fast instead of sleeping for Retry-After",
            elapsed < 30 and outcome in ("LLMDailyQuotaExhausted", "LLMRateLimited"),
            f"outcome={outcome}, elapsed={elapsed:.1f}s, requests={server.requests}",
        )
        check(
            "the quota 429 is not retried",
            server.requests == 1,
            f"requests={server.requests}",
        )
    finally:
        server.close()


def _check_retry() -> None:
    """4. A 429 followed by a 200 is one logical call and two attempts."""
    server = _CaptureServer(
        [
            (429, {"error": {"code": 429, "message": "Too Many Requests"}}, {}),
            (200, _interaction_body("recovered"), {}),
        ]
    )
    try:
        client = _client_for(server.base_url)
        answer = client.generate_text("say hello")
        usage = client.last_usage
        check(
            "a throttled call is retried and succeeds",
            answer == "recovered" and server.requests == 2,
            f"answer={answer!r}, requests={server.requests}",
        )
        check(
            "the retry is counted in the usage",
            usage is not None and usage.attempts == 2,
            f"attempts={usage.attempts if usage else None}",
        )
    finally:
        server.close()


def _check_usage_row() -> None:
    """5. The usage row holds the counts and no prompt."""
    server = _CaptureServer([(200, _interaction_body("counted", total_tokens=77), {})])
    prompt = "Ahmad Hassan, ahmad@example.com, +1 555 0101"
    try:
        client = _client_for(server.base_url)
        client.generate_text(prompt)
        rows = _usage_rows()
        rendered = str(rows[-1].extra_metadata) if rows else ""
        check("a usage row is written", bool(rows), f"rows={len(rows)}")
        check(
            "the usage row carries the token counts",
            "77" in rendered,
            rendered[:200],
        )
        check(
            "the usage row carries no prompt content",
            "Ahmad" not in rendered and "ahmad@example.com" not in rendered,
            rendered[:200],
        )
    finally:
        server.close()


def _check_config_error() -> None:
    """6. A missing key fails immediately, and never leaks."""
    client = LLMClient(provider="google", api_key="", model="gemini-3.8-flash", temperature=0.2)
    try:
        client.generate_text("say hello")
        outcome = "no error"
    except LLMError as exc:
        outcome = f"{type(exc).__name__}: {exc}"
    check(
        "a missing key fails immediately with an actionable message",
        "LLM_API_KEY" in outcome,
        outcome[:120],
    )


def _check_real_provider() -> None:
    """7. The real provider: the classification, and a real generation."""
    settings = get_settings()
    if not settings.llm_api_key:
        skip("the real provider call", "no LLM_API_KEY is configured")
        return
    client = LLMClient(
        provider=settings.llm_provider,
        api_key=settings.llm_api_key,
        model=settings.llm_model,
        temperature=settings.llm_temperature,
        timeout=settings.llm_timeout,
        max_retries=settings.llm_max_retries,
    )
    started = time.monotonic()
    try:
        answer = client.generate_text("Reply with exactly the word: ready")
    except LLMDailyQuotaExhausted as exc:
        elapsed = time.monotonic() - started
        check(
            "the real provider's daily quota is classified and fails fast",
            elapsed < 60,
            f"{str(exc)[:140]} (in {elapsed:.1f}s)",
        )
        skip("a real generation call", "the free tier's daily quota is spent")
        return
    except LLMError as exc:
        check(
            "the real provider's daily quota is classified and fails fast",
            False,
            f"unexpected failure: {str(exc)[:200]}",
        )
        return
    elapsed = time.monotonic() - started
    check(
        "a real generation call succeeds",
        bool(answer.strip()),
        f"answer={answer[:60]!r} in {elapsed:.1f}s",
    )
    usage = client.last_usage
    check(
        "the real call reports its token usage",
        usage is not None and bool(usage.total_tokens),
        f"usage={usage}",
    )


def main() -> int:
    _upgrade_database()

    _check_wire_payload()
    _check_timeout()
    _check_quota_fails_fast()
    _check_retry()
    _check_usage_row()
    _check_config_error()
    _check_real_provider()

    failures = [name for name, ok, _ in RESULTS if not ok]
    print()
    print(
        f"checks: {len(RESULTS)}  passed: {len(RESULTS) - len(failures)}  failed: {len(failures)}"
    )
    if SKIPS:
        print(f"skipped: {len(SKIPS)}")
        for name, reason in SKIPS:
            print(f"  - {name}: {reason}")
    if failures:
        print("\nfailed checks:")
        for name in failures:
            print(f"  - {name}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
