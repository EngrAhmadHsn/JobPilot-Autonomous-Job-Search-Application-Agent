"""WS-06 · Phase F — evidence capture for every submission (SEC-14).

A submission is only a success when it left artifacts behind: a screenshot of
the confirmation page and a trace of what the browser did. These tests pin the
capture, the storage, the persistence, and the two ways a submission can
fail to be a success: a challenge page, and missing artifacts.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from src.applications.contracts import (
    ApplicationRequest,
    ApplicationResult,
    PreparedApplication,
    SubmissionEvidence,
)
from src.applications.evidence import missing_evidence_files, resolve_evidence_path
from src.applications.fake_ats_adapter import FakeAtsPlaywrightAdapter
from src.config.settings import get_settings
from src.db.base import Base
from src.db.evidence import ApplicationEvidence
from src.graph.nodes import submit_node, verify_node
from src.graph.state import ApplicationWorkflowState
from src.security.allowlist import DisallowedDomainError


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
            # The real Playwright writes the trace archive here.
            Path(path).write_bytes(b"fake-trace")


class FakeContext:
    def __init__(self) -> None:
        self.tracing = FakeTracing()
        self.closed = False

    def close(self) -> None:
        self.closed = True


class FakeLocator:
    def __init__(self, page: FakePage, selector: str) -> None:
        self.page = page
        self.selector = selector

    def fill(self, value: str) -> None:
        self.page.filled[self.selector] = value

    def click(self) -> None:
        self.page.clicked.append(self.selector)

    def count(self) -> int:
        return 1

    def set_input_files(self, path: str) -> None:
        self.page.uploaded = path

    def inner_text(self) -> str:
        return self.page.body


class FakePage:
    """A page with the slice of the Playwright API the adapter uses."""

    def __init__(
        self,
        url: str = "http://localhost:8000/apply/confirm",
        body: str = "Application Submitted. Thanks for applying.",
        title: str = "Application received",
    ) -> None:
        self.context = FakeContext()
        self.url = url
        self.body = body
        self._title = title
        self.filled: dict[str, str] = {}
        self.clicked: list[str] = []
        self.uploaded: str | None = None
        self.screenshot_path: str | None = None
        self.screenshot_fails = False

    def title(self) -> str:
        return self._title

    def locator(self, selector: str) -> FakeLocator:
        return FakeLocator(self, selector)

    def wait_for_load_state(self, *args, **kwargs) -> None:
        return None

    def screenshot(self, path: str | None = None) -> None:
        if self.screenshot_fails:
            raise RuntimeError("screenshot failed")
        self.screenshot_path = path
        if path:
            Path(path).write_bytes(b"fake-png")

    def close(self) -> None:
        return None


@pytest.fixture
def evidence_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point the adapter's evidence directory at a temporary folder."""
    settings = get_settings()
    target = tmp_path / "evidence"
    target.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(settings, "evidence_dir", str(target))
    return target


@pytest.fixture
def sample_request() -> ApplicationRequest:
    return ApplicationRequest(
        job_title="Senior Python Engineer",
        company_name="Acme Labs",
        job_url="http://localhost:8000/jobs/123/apply",
        candidate_name="Ada Lovelace",
        email="ada@example.com",
        phone="+1 555 0101",
    )


def _prepared(request: ApplicationRequest) -> PreparedApplication:
    return PreparedApplication(
        request=request,
        prepared_fields={"candidate_name": "Ada Lovelace"},
        workflow_id="wf-evidence",
    )


class TestEvidenceCapture:
    """A submission produces a screenshot, an action trace, and a trace archive."""

    def test_submission_captures_the_artifacts(
        self, evidence_dir: Path, sample_request: ApplicationRequest, monkeypatch
    ) -> None:
        adapter = FakeAtsPlaywrightAdapter()
        page = FakePage()
        monkeypatch.setattr(adapter, "_open_page", lambda url: page)

        result = adapter.submit(_prepared(sample_request))

        assert result.success is True
        assert result.status == "verified"
        assert result.evidence is not None
        assert result.evidence.screenshot_path == "wf-evidence.png"
        assert result.evidence.trace_path == "wf-evidence.trace.json"
        assert (evidence_dir / "wf-evidence.png").exists()
        assert (evidence_dir / "wf-evidence.trace.json").exists()
        assert (evidence_dir / "wf-evidence.zip").exists()

    def test_the_action_trace_is_ordered_and_timestamped(
        self, evidence_dir: Path, sample_request: ApplicationRequest, monkeypatch
    ) -> None:
        adapter = FakeAtsPlaywrightAdapter()
        page = FakePage()
        monkeypatch.setattr(adapter, "_open_page", lambda url: page)

        adapter.submit(_prepared(sample_request))

        entries = json.loads((evidence_dir / "wf-evidence.trace.json").read_text(encoding="utf-8"))
        assert [entry["action"] for entry in entries] == [
            "click_submit",
            "confirmation_page",
        ]
        assert all(entry["url"] for entry in entries)
        assert all(entry["timestamp"] for entry in entries)

    def test_the_playwright_trace_was_started_with_screenshots(
        self, evidence_dir: Path, sample_request: ApplicationRequest, monkeypatch
    ) -> None:
        adapter = FakeAtsPlaywrightAdapter()
        page = FakePage()
        monkeypatch.setattr(adapter, "_open_page", lambda url: page)

        adapter.submit(_prepared(sample_request))

        assert page.context.tracing.started_with == {"screenshots": True, "sources": True}
        assert page.context.tracing.stopped_at is not None
        assert page.context.closed is True

    def test_missing_artifacts_are_never_a_success(
        self, evidence_dir: Path, sample_request: ApplicationRequest, monkeypatch
    ) -> None:
        adapter = FakeAtsPlaywrightAdapter()
        page = FakePage()
        page.screenshot_fails = True
        monkeypatch.setattr(adapter, "_open_page", lambda url: page)

        result = adapter.submit(_prepared(sample_request))

        assert result.success is False
        assert result.status == "evidence_incomplete"
        assert "screenshot" in result.message


class TestEvidencePersistence:
    """The evidence reaches the database row."""

    def test_the_submit_node_records_the_paths(
        self, evidence_dir: Path, tmp_path: Path, sample_request, monkeypatch
    ) -> None:
        engine = create_engine(f"sqlite:///{(tmp_path / 'evidence.db').as_posix()}")
        Base.metadata.create_all(engine, tables=[ApplicationEvidence.__table__])
        factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)
        monkeypatch.setattr("src.db.session.SessionLocal", factory)

        adapter = FakeAtsPlaywrightAdapter()
        page = FakePage()
        monkeypatch.setattr(adapter, "_open_page", lambda url: page)

        state = ApplicationWorkflowState(
            request=sample_request,
            workflow_id="wf-evidence",
            adapter_name=adapter.name,
            prepared_application=_prepared(sample_request),
        )
        submit_node(state, adapter)

        with Session(engine) as session:
            row = session.scalars(select(ApplicationEvidence)).one()
            assert row.workflow_id == "wf-evidence"
            assert row.screenshot_path == "wf-evidence.png"
            assert row.trace_path == "wf-evidence.trace.json"
            assert row.confirmation_text is not None
        engine.dispose()


class TestVerifyNodeEvidenceCheck:
    """A result whose artifacts are gone is not verified."""

    def test_missing_artifacts_fail_verification(self, sample_request) -> None:
        adapter = FakeAtsPlaywrightAdapter()
        state = ApplicationWorkflowState(
            request=sample_request,
            workflow_id="wf-evidence",
            adapter_name=adapter.name,
            submission_result=ApplicationResult(
                success=True,
                status="submitted",
                message="submitted",
                evidence=SubmissionEvidence(
                    url="http://localhost:8000/apply/confirm",
                    confirmation_text="Application submitted",
                    screenshot_path="does-not-exist.png",
                    trace_path="does-not-exist.trace.json",
                    status="submitted",
                ),
            ),
        )

        result_state = verify_node(state, adapter)

        assert result_state.final_result is not None
        assert result_state.final_result.success is False
        assert result_state.final_result.status == "verification_failed"
        assert "screenshot" in result_state.final_result.message
        assert "trace" in result_state.final_result.message

    def test_present_artifacts_pass_verification(
        self, evidence_dir: Path, sample_request, monkeypatch
    ) -> None:
        (evidence_dir / "present.png").write_bytes(b"png")
        (evidence_dir / "present.trace.json").write_text("[]", encoding="utf-8")

        adapter = FakeAtsPlaywrightAdapter()
        state = ApplicationWorkflowState(
            request=sample_request,
            workflow_id="wf-evidence",
            adapter_name=adapter.name,
            submission_result=ApplicationResult(
                success=True,
                status="submitted",
                message="submitted",
                evidence=SubmissionEvidence(
                    url="http://localhost:8000/apply/confirm",
                    confirmation_text="Application submitted",
                    screenshot_path="present.png",
                    trace_path="present.trace.json",
                    status="submitted",
                ),
            ),
        )

        result_state = verify_node(state, adapter)

        assert result_state.final_result.success is True
        assert result_state.final_result.status == "verified"


class TestEvidenceHelpers:
    def test_missing_evidence_files_ignores_unclaimed_artifacts(self) -> None:
        assert missing_evidence_files(SubmissionEvidence(url="u")) == []

    def test_missing_evidence_files_reports_absent_files(self) -> None:
        evidence = SubmissionEvidence(url="u", screenshot_path="nope.png")
        assert missing_evidence_files(evidence) == ["screenshot"]

    def test_resolve_evidence_path_handles_absolute_paths(self) -> None:
        resolved = resolve_evidence_path(str(Path("C:/evidence/x.png")))
        assert resolved is not None
        assert resolved.is_absolute()

    def test_resolve_evidence_path_handles_none(self) -> None:
        assert resolve_evidence_path(None) is None


class TestNavigationGuard:
    """The adapter refuses a URL the allowlist does not accept."""

    def test_a_disallowed_url_is_refused_before_the_browser_starts(self) -> None:
        adapter = FakeAtsPlaywrightAdapter()

        with pytest.raises(DisallowedDomainError):
            adapter._open_page("https://evil-greenhouse.io.attacker.com/apply")

    def test_a_disallowed_url_yields_an_unsafe_navigation_result(
        self, evidence_dir: Path, sample_request, monkeypatch
    ) -> None:
        adapter = FakeAtsPlaywrightAdapter()

        def _refuse(url: str):
            raise DisallowedDomainError(f"Host of {url!r} is not on the domain allowlist")

        monkeypatch.setattr(adapter, "_open_page", _refuse)

        result = adapter.submit(_prepared(sample_request))

        assert result.success is False
        assert result.status == "unsafe_navigation"
