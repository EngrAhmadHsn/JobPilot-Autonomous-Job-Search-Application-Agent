"""WS-08 · the fake-ATS adapter: the URL gate, the payload, the form fill.

These are unit tests: they drive the adapter against a fake page that models
the same accessibility surface the real browser exposes. The real browser is
exercised in ``tests/test_browser_variants.py``.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from src.applications import ApplicationRequest, FakeAtsPlaywrightAdapter
from src.config.settings import get_settings
from tests.fixtures.fake_page import FakeControl, FakePage


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


def test_prepare_carries_the_profile_facts() -> None:
    adapter = FakeAtsPlaywrightAdapter()
    request = ApplicationRequest(
        job_title="Senior Python Engineer",
        company_name="Acme Labs",
        job_url="http://localhost:8000/jobs/123/apply",
        candidate_name="Ada Lovelace",
        profile_facts={"years_of_experience": "7"},
    )

    prepared = adapter.prepare(request)

    assert prepared.profile_facts == {"years_of_experience": "7"}


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


def test_the_form_is_filled_through_its_labels(monkeypatch) -> None:
    adapter = FakeAtsPlaywrightAdapter()
    request = ApplicationRequest(
        job_title="Senior Python Engineer",
        company_name="Acme Labs",
        job_url="http://localhost:8000/jobs/123/apply",
        candidate_name="Ada Lovelace",
        email="ada@example.com",
        phone="+1 555 0101",
        cover_letter="Hello team",
    )
    prepared = adapter.prepare(request)
    page = FakePage()
    monkeypatch.setattr(adapter, "_open_page", lambda url: page)

    adapter.submit(prepared)

    assert page.filled["Full name"] == "Ada Lovelace"
    assert page.filled["Email address"] == "ada@example.com"
    assert page.filled["Phone number"] == "+1 555 0101"
    assert page.filled["Cover letter"] == "Hello team"
    assert page.clicked == ["Submit application"]


def test_the_resume_is_attached_to_the_file_input(monkeypatch) -> None:
    adapter = FakeAtsPlaywrightAdapter()
    request = ApplicationRequest(
        job_title="Senior Python Engineer",
        company_name="Acme Labs",
        job_url="http://localhost:8000/jobs/123/apply",
        candidate_name="Ada Lovelace",
        email="ada@example.com",
        resume_path="/tmp/resume.pdf",
    )
    prepared = adapter.prepare(request)
    page = FakePage()
    monkeypatch.setattr(adapter, "_open_page", lambda url: page)

    adapter.submit(prepared)

    assert page.uploaded == "/tmp/resume.pdf"


def test_an_unknown_question_stops_the_run(monkeypatch) -> None:
    adapter = FakeAtsPlaywrightAdapter()
    request = ApplicationRequest(
        job_title="Senior Python Engineer",
        company_name="Acme Labs",
        job_url="http://localhost:8000/jobs/123/apply",
        candidate_name="Ada Lovelace",
        email="ada@example.com",
    )
    prepared = adapter.prepare(request)
    page = FakePage(
        controls=[
            FakeControl(label="Full name", kind="text", required=True),
            FakeControl(label="Have you served on a submarine?", kind="text"),
        ]
    )
    monkeypatch.setattr(adapter, "_open_page", lambda url: page)

    result = adapter.submit(prepared)

    assert result.success is False
    assert result.status == "needs_human"
    assert result.metadata["questions"] == ["Have you served on a submarine?"]
    # Nothing was typed and nothing was submitted.
    assert page.filled == {}
    assert page.clicked == []


def test_a_select_is_filled_with_the_matching_option(monkeypatch) -> None:
    adapter = FakeAtsPlaywrightAdapter()
    request = ApplicationRequest(
        job_title="Senior Python Engineer",
        company_name="Acme Labs",
        job_url="http://localhost:8000/jobs/123/apply",
        candidate_name="Ada Lovelace",
        custom_fields={"country": "Germany"},
    )
    prepared = adapter.prepare(request)
    page = FakePage(
        controls=[
            FakeControl(label="Full name", kind="text", required=True),
            FakeControl(
                label="Country",
                kind="select",
                options=["Select a country", "Germany", "Canada"],
            ),
        ]
    )
    monkeypatch.setattr(adapter, "_open_page", lambda url: page)

    result = adapter.submit(prepared)

    assert result.success is True
    assert page.selected["Country"] == "Germany"


def test_a_checkbox_is_ticked_only_for_a_recognized_yes(monkeypatch) -> None:
    adapter = FakeAtsPlaywrightAdapter()
    request = ApplicationRequest(
        job_title="Senior Python Engineer",
        company_name="Acme Labs",
        job_url="http://localhost:8000/jobs/123/apply",
        candidate_name="Ada Lovelace",
        custom_fields={"work_authorization": "yes"},
    )
    prepared = adapter.prepare(request)
    page = FakePage(
        controls=[
            FakeControl(label="Full name", kind="text", required=True),
            FakeControl(label="I am authorized to work", kind="checkbox"),
        ]
    )
    monkeypatch.setattr(adapter, "_open_page", lambda url: page)

    adapter.submit(prepared)

    assert page.checked == ["I am authorized to work"]
    assert page.unchecked == []


def test_a_rejected_form_is_retried_once_and_then_fails(monkeypatch) -> None:
    adapter = FakeAtsPlaywrightAdapter()
    request = ApplicationRequest(
        job_title="Senior Python Engineer",
        company_name="Acme Labs",
        job_url="http://localhost:8000/jobs/123/apply",
        candidate_name="Ada Lovelace",
    )
    prepared = adapter.prepare(request)
    page = FakePage(alerts=["We could not verify your email address."])
    monkeypatch.setattr(adapter, "_open_page", lambda url: page)

    result = adapter.submit(prepared)

    assert result.success is False
    assert result.status == "form_error"
    assert result.metadata["errors"] == ["We could not verify your email address."]
    # Two attempts: the original and the one remediation retry.
    assert page.clicked == ["Submit application", "Submit application"]
