"""WS-08 · Phase F — session isolation between two runs (SEC-07).

Two submissions must not share a session. A cookie set by the first run must
not be sent by the second, and the browser's storage must not carry over
either.

The fake ATS has a probe page for this: it sets a cookie, it reports the
cookie it was given, and it reports what the browser's storage held when the
page loaded. The adapter's own confirmation text carries the answer back, so
the assertions are made on what the agent actually saw.
"""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest

from src.applications.contracts import ApplicationRequest
from src.applications.fake_ats_adapter import FakeAtsPlaywrightAdapter

#: These tests drive a **real Chromium** through the fake ATS. They are
#: marked so that CI can run them in their own job, with the browser
#: binary installed. The marker is a wall-clock optimisation: both CI
#: jobs install Chromium, so an unmarked browser test would still pass.
pytestmark = pytest.mark.browser
from src.config.settings import get_settings
from tests.fixtures.fake_ats import serve_fake_ats_variants


@pytest.fixture
def evidence_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """An isolated evidence directory, and a development environment."""
    settings = get_settings()
    target = tmp_path / "evidence"
    target.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(settings, "evidence_dir", str(target))
    monkeypatch.setattr(settings, "app_env", "development")
    return target


@pytest.fixture(scope="module")
def ats():
    """The fake ATS, running for the whole module."""
    with serve_fake_ats_variants() as base_url:
        yield base_url


def _submit(base_url: str, workflow_id: str):
    """One submission against the session probe."""
    adapter = FakeAtsPlaywrightAdapter()
    request = ApplicationRequest(
        job_title="Senior Python Engineer",
        company_name="Acme Labs",
        job_url=f"{base_url}/session",
        candidate_name="Ada Lovelace",
        email="ada@example.com",
        phone="+1 555 0101",
    )
    prepared = adapter.prepare(request)
    prepared.workflow_id = workflow_id
    return adapter.submit(prepared)


def test_two_consecutive_runs_share_no_cookie_or_storage(evidence_dir, ats) -> None:
    first = _submit(ats, "iso-first")
    second = _submit(ats, "iso-second")

    assert first.success is True, first.message
    assert second.success is True, second.message

    # The browser's storage was empty on both runs: the second run did not
    # see what the first one wrote.
    assert "Marker: none" in (first.evidence.confirmation_text or "")
    assert "Marker: none" in (second.evidence.confirmation_text or "")

    # The cookie the first run was given was not sent by the second run.
    requests = httpx.get(f"{ats}/_requests", timeout=10).json()
    session_requests = [record for record in requests if record["path"] == "/session"]
    assert len(session_requests) >= 4

    first_get = session_requests[0]
    first_post = session_requests[1]
    second_get = session_requests[2]
    second_post = session_requests[3]

    assert first_get["cookie"] == ""
    assert first_post["cookie"] != "", "the first run should have received a cookie"
    # The second run started with nothing.
    assert second_get["cookie"] == ""
    # And it received a cookie of its own, not the first run's.
    assert second_post["cookie"] != ""
    assert second_post["cookie"] != first_post["cookie"]


def test_the_storage_probe_really_would_notice_a_leak(ats) -> None:
    """The control: the probe *does* see a storage value inside one context.

    Without this, the isolation test could pass because the probe never
    reports anything at all.
    """
    pytest.importorskip("playwright.sync_api")
    from playwright.sync_api import sync_playwright

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            context = browser.new_context()
            page = context.new_page()
            page.goto(f"{ats}/session", wait_until="domcontentloaded")
            page.get_by_role("button", name="Submit application").click()
            page.wait_for_load_state("domcontentloaded")
            first_marker = _marker_of(page)

            # The same context, a second time: the storage value is there.
            page.goto(f"{ats}/session", wait_until="domcontentloaded")
            page.get_by_role("button", name="Submit application").click()
            page.wait_for_load_state("domcontentloaded")
            second_marker = _marker_of(page)

            context.close()
        finally:
            browser.close()

    assert first_marker == "none"
    assert second_marker == "set-by-this-run"


def _marker_of(page) -> str:
    """The storage marker the page reported."""
    text = page.locator("body").inner_text()
    for line in text.splitlines():
        if line.startswith("Marker:"):
            return line.split(":", 1)[1].strip()
    return ""
