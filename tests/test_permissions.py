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
