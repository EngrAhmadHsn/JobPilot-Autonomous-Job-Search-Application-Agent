from __future__ import annotations

from src.applications import ApplicationRequest, FakeAtsPlaywrightAdapter


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


class FakePage:
    def __init__(self) -> None:
        self.context = self
        self.url = "http://localhost:8000/apply/confirm"
        self._body = "Application Submitted. Thanks for applying."
        self._locators = {
            "#candidate-name": FakeLocator(),
            "#email": FakeLocator(),
            "#phone": FakeLocator(),
            "#cover-letter": FakeLocator(),
            "button[type='submit'], input[type='submit']": FakeLocator(),
            "input[type='file']": FakeLocator(),
            "body": FakeLocator(self._body),
        }

    def locator(self, selector: str):
        return self._locators.get(selector, FakeLocator())

    def wait_for_load_state(self, *args, **kwargs) -> None:
        return None

    def close(self) -> None:
        return None


def test_application_adapter_supports_local_fake_ats_url() -> None:
    adapter = FakeAtsPlaywrightAdapter()

    assert adapter.supports_url("http://localhost:8000/jobs/123/apply") is True
    assert adapter.supports_url("https://example.com/jobs/123") is False


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
    monkeypatch.setattr(adapter, "_open_page", lambda url: FakePage())

    result = adapter.submit(prepared)

    assert result.success is True
    assert result.status == "verified"
    assert "Application submission verified" in result.message
