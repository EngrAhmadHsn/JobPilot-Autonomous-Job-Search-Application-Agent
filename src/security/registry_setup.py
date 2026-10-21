"""The application adapter capability matrix (WS-06 · SEC-08).

One table, one place. It is the reviewed statement of what each adapter is
allowed to do:

============ ========================= ==================================
Adapter      Capabilities              Why
============ ========================= ==================================
fake-ats     prepare, submit, verify   The local fake ATS is the only
                                          submission target in this version.
greenhouse   prepare                   Preparing a Greenhouse payload is
                                          harmless; submitting is not
                                          implemented and must not be
                                          claimed.
lever        prepare                   Same as Greenhouse.
============ ========================= ==================================

An adapter that is not listed here holds **no** capability, so an
unregistered adapter can neither prepare nor submit. The registry is consulted
in the submit and verify nodes; the adapters themselves refuse a submit they
were not granted as a second layer.
"""

from __future__ import annotations

from src.security.permissions import CapabilityLevel, PermissionRegistry

ADAPTER_PERMISSIONS: dict[str, list[CapabilityLevel]] = {
    "fake-ats-playwright": [
        CapabilityLevel.PREPARE,
        CapabilityLevel.SUBMIT,
        CapabilityLevel.VERIFY,
    ],
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
