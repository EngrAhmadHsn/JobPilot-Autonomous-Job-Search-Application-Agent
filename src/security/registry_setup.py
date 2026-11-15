"""The application adapter capability matrix (WS-06 · SEC-08).

One table, one place. It is the reviewed statement of what each adapter is
allowed to do:

============ ========================= ==================================
Adapter      Capabilities              Why
============ ========================= ==================================
fake-ats     prepare, submit, verify   The local fake ATS is the only
                                          submission target in this version.
assist       prepare                   The WS-32 assist-mode pilot. The
                                          agent fills the form and stops;
                                          the **human** presses submit, so
                                          this adapter must never hold
                                          SUBMIT. Constructed directly by
                                          ``scripts/pilot_assist.py``, not
                                          selectable by an ordinary prepare
                                          flow.
greenhouse   prepare                   Preparing a Greenhouse payload is
                                          harmless; submitting is not
                                          implemented and must not be
                                          claimed.
lever        prepare                   Same as Greenhouse.
============ ========================= ==================================

An adapter that is not listed here holds **no** capability, so an
unregistered adapter can neither prepare nor submit. The registry is consulted
in the submit and verify nodes; the adapters themselves refuse a submit or a
verify they were not granted as a second layer. That refusal is
:meth:`~src.applications.contracts.ApplicationAdapter.require_capability`, one
implementation on the adapter base class, called first by every adapter's
``submit`` and ``verify``. Every adapter in this matrix — including the fake
ATS, which holds ``SUBMIT`` — calls it, so the layer is uniform rather than a
property of the two adapters that happen to fail without it.

The capability each adapter asks for is the one it actually exercises, which is
why the assist row reads the way it does: its ``submit`` fills a form and stops,
so it asks for ``PREPARE`` (not ``SUBMIT``, which it must never hold), and its
``verify`` reads the evidence of the human's own submission, so it asks for
``PREPARE`` too — asking for ``VERIFY`` would make the one thing the pilot
exists to verify unreachable.
"""

from __future__ import annotations

from src.security.permissions import CapabilityLevel, PermissionRegistry

ADAPTER_PERMISSIONS: dict[str, list[CapabilityLevel]] = {
    "fake-ats-playwright": [
        CapabilityLevel.PREPARE,
        CapabilityLevel.SUBMIT,
        CapabilityLevel.VERIFY,
    ],
    # WS-32 · Task 5: the assist-mode pilot fills the form and hands the browser
    # to a human. PREPARE is the whole of its grant, and holding no SUBMIT is
    # what makes the stop a capability rather than a convention.
    "assist-playwright": [CapabilityLevel.PREPARE],
    "greenhouse": [CapabilityLevel.PREPARE],
    "lever": [CapabilityLevel.PREPARE],
}

_registry: PermissionRegistry | None = None


def build_registry() -> PermissionRegistry:
    """A fresh registry carrying the documented capability matrix."""
    registry = PermissionRegistry()
    for adapter_name, capabilities in ADAPTER_PERMISSIONS.items():
        registry.register(adapter_name, capabilities)
    return registry


def get_registry() -> PermissionRegistry:
    """The process-wide registry (rebuilt on demand after a reset)."""
    global _registry
    if _registry is None:
        _registry = build_registry()
    return _registry


def reset_registry() -> None:
    """Drop the cached registry (the next call rebuilds it)."""
    global _registry
    _registry = None
