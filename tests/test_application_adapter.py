from __future__ import annotations

from pathlib import Path

import pytest

from src.applications import ApplicationRequest, FakeAtsPlaywrightAdapter
from src.config.settings import get_settings


class FakeLocator:
    def __init__(self, value: str | None = None):
        self.value = value

    def fill(self, value: str) -> None:
        self.value = value

    def click(self) -> None:
        return None

    def count(self) -> int:
        return 1

    def set_input_files(self, path: str) -> None:
        self.value = path

    def inner_text(self) -> str:
        return self.value or ""

    def __call__(self):
        return self


class FakeTracing:
    """The Playwright tracing API, reduced to what the adapter uses."""

    def __init__(self) -> None:
        self.started_with: dict | None = None
        self.stopped_at: str | None = None

    def start(self, **kwargs) -> None:
        self.started_with = kwargs

    def stop(self, path: str | None = None) -> None:
        self.stopped_at = path
        if path:
            Path(path).write_bytes(b"fake-trace")


class FakePage:
    def __init__(self):
        self.context = self
        self.tracing = FakeTracing()
        self.url = "http://localhost:8000/apply/confirm"
        self._body = "Application Submitted. Thanks for applying."
        self.screenshot_path: str | None = None
        self._locators = {
            "#candidate-name": FakeLocator(),
            "#email": FakeLocator(),
            "#phone": FakeLocator(),
            "#cover-letter": FakeLocator(),
            "button[type='submit'], input[type='submit']": FakeLocator(),
            "input[type='file']": FakeLocator(),
            "body": FakeLocator(self._body),
        }

    def title(self) -> str:
        return "Application received"

    def locator(self, selector: str):
        return self._locators.get(selector, FakeLocator())

    def wait_for_load_state(self, *args, **kwargs) -> None:
        return None

    def screenshot(self, path: str | None = None) -> None:
        self.screenshot_path = path
        if path:
            Path(path).write_bytes(b"fake-png")

    def close(self) -> None:
        return None


@pytest.fixture(autouse=True)
def isolated_evidence_dir(tmp_path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Keep the captured evidence out of the developer's data directory."""
    target = tmp_path / "evidence"
    target.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(get_settings(), "evidence_dir", str(target))
    return target


def test_application_adapter_supports_local_fake_ats_url() -> None:
    adapter = FakeAtsPlaywrightAdapter()

    assert adapter.supports_url("http://localhost:8000/jobs/123/apply") is True
    assert adapter.supports_url("https://example.com/jobs/123") is False


def test_application_adapter_rejects_a_spoofed_host() -> None:
    adapter = FakeAtsPlaywrightAdapter()

    assert adapter.supports_url("http://not-fake-ats.example.com/apply") is False


def test_prepare_builds_payload_for_fake_ats() -> None:
    adapter = FakeAtsPlaywrightAdapter()
    request = ApplicationRequest(
        job_title="Senior Python Engineer",
        company_name="Acme Labs",
        job_url="http://localhost:8000/jobs/123/apply",
        candidate_name="Ada Lovelace",
        email="ada@example.com",
        phone="+1 555 0101",
        cover_letter="Hello team",
        custom_fields={"portfolio": "https://example.com"},
    )

    prepared = adapter.prepare(request)

    assert prepared.request.job_url == request.job_url
    assert prepared.prepared_fields["candidate_name"] == "Ada Lovelace"
    assert prepared.prepared_fields["portfolio"] == "https://example.com"
    assert prepared.cover_letter == "Hello team"


def test_submit_and_verify_fake_ats_application(monkeypatch) -> None:
    adapter = FakeAtsPlaywrightAdapter()
    request = ApplicationRequest(
        job_title="Senior Python Engineer",
        company_name="Acme Labs",
        job_url="http://localhost:8000/jobs/123/apply",
        candidate_name="Ada Lovelace",
        email="ada@example.com",
        phone="+1 555 0101",
        resume_path="/tmp/resume.pdf",
        cover_letter="Hello team",
    )
    prepared = adapter.prepare(request)
    page = FakePage()
    monkeypatch.setattr(adapter, "_open_page", lambda url: page)

    result = adapter.submit(prepared)

    assert result.success is True
    assert result.status == "verified"
    assert "Application submission verified" in result.message
    # The evidence was captured (WS-06 · SEC-14).
    assert result.evidence is not None
    assert result.evidence.screenshot_path
    assert result.evidence.trace_path
