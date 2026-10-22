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
from src.applications.evidence import evidence_dir as shared_evidence_dir
from src.applications.evidence import missing_evidence_files, resolve_evidence_path
from src.applications.fake_ats_adapter import FakeAtsPlaywrightAdapter
from src.config.settings import get_settings
from src.db.base import Base
from src.db.evidence import ApplicationEvidence
from src.graph.nodes import submit_node, verify_node
from src.graph.state import ApplicationWorkflowState
from src.security.allowlist import DisallowedDomainError
from src.security.paths import is_absolute_path, is_foreign_absolute_path
from tests.fixtures.fake_page import FakePage


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
        prepared_fields={
            "candidate_name": "Ada Lovelace",
            "email": "ada@example.com",
            "phone": "+1 555 0101",
        },
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
        actions = [entry["action"] for entry in entries]
        # The trace is the ordered record of what the browser did: the fields
        # it filled, the button it clicked, and the page it landed on.
        assert "fill:Full name" in actions
        assert "click_submit" in actions
        assert actions[-1] == "confirmation_page"
        assert actions.index("fill:Full name") < actions.index("click_submit")
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

    def test_resolve_evidence_path_handles_absolute_paths(self, tmp_path) -> None:
        """An absolute path is returned as it is.

        The property is "it is not joined onto the evidence directory",
        so the assertion is about the **value**, not about
        ``pathlib``'s notion of absolute — which follows the host and
        is therefore not the same question on Linux and on Windows.
        """
        absolute = tmp_path / "x.png"
        resolved = resolve_evidence_path(str(absolute))
        assert resolved is not None
        assert resolved == absolute
        assert str(shared_evidence_dir()) not in str(resolved)

    def test_a_path_from_another_host_is_not_joined_onto_the_evidence_directory(
        self,
    ) -> None:
        """A Windows drive path is absolute on Windows and relative on
        Linux, and ``pathlib`` follows the host.

        A stored path may have been written on a Windows host and read
        on a Linux one, so joining it onto the evidence directory
        produced the nonsense "data/evidence/C:/evidence/x.png" — a
        path that looks plausible and points at nothing. The convention
        has to be recognised, not only the host's own notion of
        absolute.
        """
        resolved = resolve_evidence_path("C:/evidence/x.png")
        assert resolved is not None
        assert str(resolved).replace("\\", "/") == "C:/evidence/x.png"

    def test_resolve_evidence_path_handles_none(self) -> None:
        assert resolve_evidence_path(None) is None


class TestTheAbsolutePathRules:
    """What "absolute" means when the host might not share the convention.

    ``pathlib`` judges absoluteness with the rules of the **host**, and a
    stored path may have been written on a different one. These are the
    cases that broke: a Windows drive path read on Linux is *relative*
    there, so joining it onto the evidence directory produced
    ``data/evidence/C:/evidence/x.png`` — a path that looks plausible
    and points at nothing.
    """

    def test_a_windows_drive_path_is_absolute(self) -> None:
        """Absolute on every host, which is the whole point."""
        assert is_absolute_path("C:/evidence/x.png")

    def test_a_windows_unc_path_is_absolute(self) -> None:
        assert is_absolute_path("//server/share/x.png")

    def test_a_posix_rooted_path_is_absolute(self) -> None:
        assert is_absolute_path("/evidence/x.png")

    def test_a_relative_path_is_not_absolute(self) -> None:
        assert not is_absolute_path("evidence/x.png")
        assert not is_foreign_absolute_path("evidence/x.png")

    def test_the_foreign_convention_is_the_other_hosts(self) -> None:
        """Which convention is *foreign* depends on the host, and only on
        the host."""
        import os

        if os.name == "nt":
            # On Windows the foreign convention is the POSIX one.
            assert is_foreign_absolute_path("/evidence/x.png")
            assert not is_foreign_absolute_path("C:/evidence/x.png")
        else:
            # On POSIX the foreign convention is the Windows one.
            assert is_foreign_absolute_path("C:/evidence/x.png")
            assert is_foreign_absolute_path("//server/share/x.png")
            assert not is_foreign_absolute_path("/evidence/x.png")

    def test_a_windows_path_is_refused_by_the_containment_check(self) -> None:
        """A path in a foreign convention cannot be inside this host's
        directory, so it is refused outright rather than resolved against
        the working directory."""
        from src.storage.paths import UserPathNotAllowedError, assert_within_user_root

        with pytest.raises(UserPathNotAllowedError):
            assert_within_user_root("C:/evidence/x.png", "alice", what="evidence file")


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


class TestBrowserLifecycle:
    """The browser session must be closed, or the next one fails.

    A leaked Playwright instance leaves a running event loop in the thread
    (its dispatcher runs in a greenlet there), and the *next* browser use in
    that thread dies with "Sync API inside the asyncio loop". The live
    verification run found exactly that; this test is the regression guard.
    """

    def test_two_consecutive_submissions_both_succeed(self, evidence_dir: Path) -> None:
        pytest.importorskip("playwright.sync_api")
        from tests.fixtures.fake_ats import serve_fake_ats

        try:
            from playwright.sync_api import sync_playwright

            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(headless=True)
                browser.close()
        except Exception as exc:  # noqa: BLE001 - the browser is an optional dev dependency
            pytest.skip(f"The Playwright browser is not installed: {exc}")

        adapter = FakeAtsPlaywrightAdapter()
        with serve_fake_ats() as base:
            first = adapter.submit(_prepared_for(f"{base}/apply", "wf-first"))
            second = adapter.submit(_prepared_for(f"{base}/apply", "wf-second"))

        assert first.success is True
        assert first.status == "verified"
        assert second.success is True
        assert second.status == "verified"

    def test_the_browser_is_closed_after_a_submission(
        self, evidence_dir: Path, sample_request: ApplicationRequest, monkeypatch
    ) -> None:
        adapter = FakeAtsPlaywrightAdapter()
        page = FakePage()
        monkeypatch.setattr(adapter, "_open_page", lambda url: page)

        adapter.submit(_prepared(sample_request))

        assert page.context.closed is True
        assert adapter._browser is None
        assert adapter._playwright is None


def _prepared_for(job_url: str, workflow_id: str) -> PreparedApplication:
    """A prepared application for a given URL and workflow."""
    request = ApplicationRequest(
        job_title="Senior Python Engineer",
        company_name="Acme Labs",
        job_url=job_url,
        candidate_name="Ada Lovelace",
        email="ada@example.com",
        phone="+1 555 0101",
    )
    return PreparedApplication(
        request=request,
        prepared_fields={"candidate_name": "Ada Lovelace"},
        workflow_id=workflow_id,
    )


class TestFailureStatusPreservation:
    """A failed submission keeps its own reason instead of a generic failure.

    The live verification run found that a blocked challenge came out as
    ``verification_failed``: the graph re-verified a submission that never
    happened, and the reason was flattened. The status now survives.
    """

    def test_a_blocked_submission_ends_as_blocked_human_review(
        self, sample_request: ApplicationRequest
    ) -> None:
        from src.graph.application_workflow import build_application_workflow
        from src.graph.state import ApplicationWorkflowState

        class _BlockedAdapter(FakeAtsPlaywrightAdapter):
            def submit(self, prepared: PreparedApplication) -> ApplicationResult:
                return ApplicationResult(
                    success=False,
                    status="blocked_human_review",
                    message="The page presented a CAPTCHA; the flow was stopped.",
                    evidence=SubmissionEvidence(
                        url=prepared.request.job_url, status="blocked_human_review"
                    ),
                )

        adapter = _BlockedAdapter()
        graph = build_application_workflow(adapter)
        state = ApplicationWorkflowState(
            request=sample_request,
            prepared_application=_prepared(sample_request),
            approval_status=True,
            workflow_id="wf-blocked",
            adapter_name=adapter.name,
        )

        raw = graph.invoke(state, config={"configurable": {"thread_id": "wf-blocked"}})
        final_state = (
            raw if isinstance(raw, ApplicationWorkflowState) else ApplicationWorkflowState(**raw)
        )

        assert final_state.final_result is not None
        assert final_state.final_result.success is False
        assert final_state.final_result.status == "blocked_human_review"
        assert "CAPTCHA" in final_state.final_result.message
