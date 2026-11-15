"""WS-32 · "The adapters themselves refuse" must be true of every adapter.

``src/security/registry_setup.py`` claims the adapter layer refuses a submit it
was not granted as a second layer. Only greenhouse and lever did; the fake ATS
— the adapter a new adapter is most likely to be written from — did not. A
docstring that overclaims is worse than a missing one, because a reader relies
on it instead of reading the code.

The adapter list is deliberately **not** re-declared here: it is derived from
``src.graph.executor.AVAILABLE_ADAPTERS``, the one list the API route and the
worker both resolve their adapters from (WS-32 moved it out of the route module
so the two could not drift). Parametrizing over it means a new adapter is
covered the day it is registered, rather than the day someone remembers.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest

from src.applications.contracts import (
    ApplicationAdapter,
    ApplicationRequest,
    ApplicationResult,
    PreparedApplication,
)
from src.security.permissions import CapabilityLevel, PermissionRegistry

ROOT = Path(__file__).resolve().parents[1]


def _registered_adapters() -> list[tuple[str, Callable[[], ApplicationAdapter]]]:
    """``(name, factory)`` for every adapter the process carries.

    Read from ``AVAILABLE_ADAPTERS`` at collection time. The factory is the
    adapter's own class, so every test drives a fresh instance — the fake ATS
    keeps browser handles on ``self``.
    """
    from src.graph.executor import AVAILABLE_ADAPTERS

    return [(adapter.name, type(adapter)) for adapter in AVAILABLE_ADAPTERS]


REGISTERED_ADAPTERS = _registered_adapters()
ADAPTER_IDS = [name for name, _ in REGISTERED_ADAPTERS]


def _prepared() -> PreparedApplication:
    """A minimal payload: the refusal must happen before anything is done with it."""
    return PreparedApplication(
        request=ApplicationRequest(
            job_title="Software Engineer",
            company_name="Acme Labs",
            job_url="http://localhost:8000/jobs/123/apply",
        )
    )


@pytest.mark.parametrize(("name", "factory"), REGISTERED_ADAPTERS, ids=ADAPTER_IDS)
def test_every_adapter_refuses_a_capability_it_does_not_hold(
    name: str, factory: Callable[[], ApplicationAdapter]
) -> None:
    """Parametrized over the registered adapters, so a new one is covered the
    day it is registered rather than the day someone remembers."""
    adapter = factory()
    assert adapter.name == name
    registry = PermissionRegistry()  # grants nothing

    with pytest.raises(PermissionError) as refusal:
        adapter.require_capability(CapabilityLevel.SUBMIT, registry=registry)

    # The refusal names the adapter and the capability, so an operator reading
    # the log knows which adapter refused and what it was refused.
    assert name in str(refusal.value)
    assert CapabilityLevel.SUBMIT.value in str(refusal.value)


def test_the_fake_ats_refuses_submit_when_the_registry_withholds_it() -> None:
    """The specific gap: the fake ATS holds SUBMIT today, so nothing exposes
    its missing check — and it is the adapter a new adapter is copied from."""
    from src.applications.fake_ats_adapter import FakeAtsPlaywrightAdapter

    empty = PermissionRegistry()
    with pytest.raises(PermissionError):
        FakeAtsPlaywrightAdapter().require_capability(CapabilityLevel.SUBMIT, registry=empty)


def test_the_helper_is_on_the_base_class_not_copied_per_adapter() -> None:
    """One implementation, or the next adapter forgets it — which is exactly
    how this gap opened."""
    assert hasattr(ApplicationAdapter, "require_capability")
    # And no adapter re-implements it locally.
    for path in (ROOT / "src" / "applications").glob("*_adapter.py"):
        assert "def require_capability" not in path.read_text("utf-8"), path


@pytest.mark.parametrize(("name", "factory"), REGISTERED_ADAPTERS, ids=ADAPTER_IDS)
def test_every_submit_asks_for_the_capability_before_it_acts(
    name: str,
    factory: Callable[[], ApplicationAdapter],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Each ``submit`` **calls** the helper — it does not merely have one.

    This is the test the original gap fails: a future adapter that forgets the
    call is caught here. The helper is replaced by a spy that records the call
    and then raises, so the submission must not begin — no browser, no
    navigation, no network — and the caller sees the refusal.
    """
    calls: list[tuple[str, CapabilityLevel]] = []

    def spy(
        self: ApplicationAdapter,
        level: CapabilityLevel,
        registry: PermissionRegistry | None = None,
    ) -> None:
        calls.append((self.name, level))
        raise PermissionError(f"{level.value} capability not granted for adapter {self.name!r}")

    monkeypatch.setattr(ApplicationAdapter, "require_capability", spy)
    adapter = factory()

    with pytest.raises(PermissionError):
        adapter.submit(_prepared())

    assert calls == [(name, CapabilityLevel.SUBMIT)]


@pytest.mark.parametrize(("name", "factory"), REGISTERED_ADAPTERS, ids=ADAPTER_IDS)
def test_every_verify_asks_for_the_capability_before_it_acts(
    name: str,
    factory: Callable[[], ApplicationAdapter],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The verify path self-checks too: it is a separate capability, and an
    adapter that holds SUBMIT does not automatically hold it."""
    calls: list[tuple[str, CapabilityLevel]] = []

    def spy(
        self: ApplicationAdapter,
        level: CapabilityLevel,
        registry: PermissionRegistry | None = None,
    ) -> None:
        calls.append((self.name, level))
        raise PermissionError(f"{level.value} capability not granted for adapter {self.name!r}")

    monkeypatch.setattr(ApplicationAdapter, "require_capability", spy)
    adapter = factory()

    with pytest.raises(PermissionError):
        adapter.verify(ApplicationResult(success=True, status="submitted", message="ok"))

    assert calls == [(name, CapabilityLevel.VERIFY)]
