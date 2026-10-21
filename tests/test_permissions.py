"""WS-06 · Phase B — least privilege for application adapters (SEC-08).

The permission registry is what stops an adapter from submitting an
application it was never granted the right to submit. These tests pin three
properties: the capability matrix itself, the refusal of an unregistered
adapter (as a *result*, not an exception), and the removal of the
``success=True`` placeholders that used to claim a submission had happened.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from src.applications.contracts import (
    ApplicationRequest,
    ApplicationResult,
    PreparedApplication,
)
from src.applications.greenhouse_adapter import GreenhouseAdapter
from src.applications.lever_adapter import LeverAdapter
from src.graph.nodes import submit_node, verify_node
from src.graph.state import ApplicationWorkflowState
from src.security.permissions import CapabilityLevel, PermissionRegistry
from src.security.registry_setup import (
    ADAPTER_PERMISSIONS,
    build_registry,
    get_registry,
    reset_registry,
)


@pytest.fixture
def sample_request() -> ApplicationRequest:
    return ApplicationRequest(
        job_title="Software Engineer",
        company_name="Acme Labs",
        job_url="https://boards.greenhouse.io/acme/jobs/1",
        candidate_name="Ada Lovelace",
        email="ada@example.com",
        phone="+1 555 0101",
    )


def _adapter(name: str) -> MagicMock:
    adapter = MagicMock()
    adapter.name = name
    return adapter


class TestCapabilityMatrix:
    """The documented matrix is the one the registry serves."""

    def test_fake_ats_may_submit_and_verify(self) -> None:
        registry = get_registry()
        assert registry.can_submit("fake-ats-playwright") is True
        assert registry.can_verify("fake-ats-playwright") is True
        assert registry.can_prepare("fake-ats-playwright") is True

    def test_greenhouse_and_lever_may_only_prepare(self) -> None:
        registry = get_registry()
        for name in ("greenhouse", "lever"):
            assert registry.can_prepare(name) is True
            assert registry.can_submit(name) is False
            assert registry.can_verify(name) is False

    def test_unregistered_adapter_holds_no_capability(self) -> None:
        registry = get_registry()
        assert registry.can_prepare("rogue-adapter") is False
        assert registry.can_submit("rogue-adapter") is False
        assert registry.can_verify("rogue-adapter") is False
        assert registry.capabilities("rogue-adapter") == frozenset()

    def test_matrix_is_declared_in_one_place(self) -> None:
        assert set(ADAPTER_PERMISSIONS) == {"fake-ats-playwright", "greenhouse", "lever"}
        assert CapabilityLevel.SUBMIT in ADAPTER_PERMISSIONS["fake-ats-playwright"]

    def test_registry_can_be_rebuilt(self) -> None:
        reset_registry()
        registry = get_registry()
        assert registry.can_submit("fake-ats-playwright") is True
        assert build_registry().capabilities("lever") == frozenset({CapabilityLevel.PREPARE})

    def test_register_replaces_previous_grant(self) -> None:
        registry = PermissionRegistry()
        registry.register("x", [CapabilityLevel.SUBMIT])
        assert registry.can_submit("x") is True
        registry.register("x", [CapabilityLevel.PREPARE])
        assert registry.can_submit("x") is False
        assert registry.can_prepare("x") is True


class TestSubmitNodeEnforcement:
    """The submit node refuses an adapter without the submit capability."""

    def test_unregistered_adapter_is_denied_without_raising(
        self, sample_request: ApplicationRequest
    ) -> None:
        adapter = _adapter("rogue-adapter")
        state = ApplicationWorkflowState(
            request=sample_request,
            workflow_id="wf-1",
            adapter_name="rogue-adapter",
            prepared_application=PreparedApplication(request=sample_request),
        )

        result_state = submit_node(state, adapter)

        assert result_state.submission_result is not None
        assert result_state.submission_result.success is False
        assert result_state.submission_result.status == "permission_denied"
        # The adapter was never called.
        adapter.submit.assert_not_called()

    def test_adapter_without_submit_capability_is_denied(
        self, sample_request: ApplicationRequest
    ) -> None:
        adapter = _adapter("greenhouse")
        state = ApplicationWorkflowState(
            request=sample_request,
            workflow_id="wf-2",
            adapter_name="greenhouse",
            prepared_application=PreparedApplication(request=sample_request),
        )

        result_state = submit_node(state, adapter)

        assert result_state.submission_result.status == "permission_denied"
        assert result_state.error is not None
        adapter.submit.assert_not_called()

    def test_permitted_adapter_still_submits(self, sample_request: ApplicationRequest) -> None:
        adapter = _adapter("fake-ats-playwright")
        expected = ApplicationResult(success=True, status="submitted", message="ok")
        adapter.submit.return_value = expected
        state = ApplicationWorkflowState(
            request=sample_request,
            workflow_id="wf-3",
            adapter_name="fake-ats-playwright",
            prepared_application=PreparedApplication(request=sample_request),
        )

        result_state = submit_node(state, adapter)

        assert result_state.submission_result is expected
        assert result_state.error is None
        adapter.submit.assert_called_once()


class TestVerifyNodeEnforcement:
    """The verify capability is granted separately from submit."""

    def test_verify_is_denied_for_an_adapter_without_the_capability(
        self, sample_request: ApplicationRequest
    ) -> None:
        adapter = _adapter("greenhouse")
        state = ApplicationWorkflowState(
            request=sample_request,
            workflow_id="wf-4",
            adapter_name="greenhouse",
            submission_result=ApplicationResult(success=True, status="submitted", message="ok"),
        )

        result_state = verify_node(state, adapter)

        assert result_state.final_result is not None
        assert result_state.final_result.status == "permission_denied"
        assert result_state.final_result.success is False
        adapter.verify.assert_not_called()


class TestNoPlaceholderSuccess:
    """The false-claim placeholders are gone (plan §35)."""

    def test_greenhouse_submit_raises_instead_of_claiming_success(
        self, sample_request: ApplicationRequest
    ) -> None:
        adapter = GreenhouseAdapter()
        prepared = adapter.prepare(sample_request)

        with pytest.raises(PermissionError):
            adapter.submit(prepared)

    def test_lever_submit_raises_instead_of_claiming_success(
        self, sample_request: ApplicationRequest
    ) -> None:
        adapter = LeverAdapter()
        prepared = adapter.prepare(sample_request)

        with pytest.raises(PermissionError):
            adapter.submit(prepared)

    def test_no_adapter_submit_returns_a_hard_coded_success(self) -> None:
        """No adapter's ``submit()`` may return a literal unconditional success.

        Checked on the parsed AST rather than with a text grep: the property
        that matters is "a ``submit()`` never returns ``success=True``", not
        "the string does not appear somewhere in the file".
        """
        import ast
        from pathlib import Path

        package = Path(__file__).resolve().parents[1] / "src" / "applications"
        offenders: list[str] = []
        for path in sorted(package.glob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if not isinstance(node, ast.ClassDef):
                    continue
                for item in node.body:
                    if not isinstance(item, ast.FunctionDef) or item.name != "submit":
                        continue
                    for inner in ast.walk(item):
                        if not isinstance(inner, ast.Return) or inner.value is None:
                            continue
                        for call in ast.walk(inner.value):
                            if not (
                                isinstance(call, ast.Call)
                                and isinstance(call.func, ast.Name)
                                and call.func.id == "ApplicationResult"
                            ):
                                continue
                            if any(
                                kw.arg == "success"
                                and isinstance(kw.value, ast.Constant)
                                and kw.value.value is True
                                for kw in call.keywords
                            ):
                                offenders.append(f"{path.name}:{node.name}.submit")
        assert offenders == []

    def test_the_documented_grep_finds_no_placeholder_success(self) -> None:
        """``grep -rn "success=True" src/applications/`` must be empty."""
        from pathlib import Path

        package = Path(__file__).resolve().parents[1] / "src" / "applications"
        offenders = [
            path.name
            for path in package.glob("*.py")
            if "success=True" in path.read_text(encoding="utf-8")
        ]
        assert offenders == []

    def test_fake_ats_only_reports_success_when_the_page_confirms(self) -> None:
        """A confirmation page without the expected text is not a success."""
        from src.applications.contracts import SubmissionEvidence
        from src.applications.fake_ats_adapter import FakeAtsPlaywrightAdapter

        adapter = FakeAtsPlaywrightAdapter()
        result = adapter.verify(
            ApplicationResult(
                success=True,
                status="submitted",
                message="submitted",
                evidence=SubmissionEvidence(
                    url="http://localhost/x", confirmation_text="Nothing here", status="submitted"
                ),
            )
        )
        assert result.success is False
        assert result.status == "verification_failed"
