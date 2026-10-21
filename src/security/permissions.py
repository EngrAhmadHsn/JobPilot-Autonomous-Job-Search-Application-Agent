"""Least-privilege permission registry for application adapters (WS-06 · SEC-08).

The registry maps an adapter name to the capabilities it is allowed to
exercise. Nothing may submit, verify, or prepare an application unless the
adapter is registered with that capability — an unregistered adapter is
refused, and the refusal is a *result* (``status="permission_denied"``), never
an unhandled exception.

The registration table lives in one place (``src/security/registry_setup.py``)
so the capability matrix can be reviewed as a whole.
"""

from __future__ import annotations

from collections.abc import Iterable
from enum import Enum


class CapabilityLevel(str, Enum):
    """Capabilities an adapter may be granted."""

    READ = "read"
    SEARCH = "search"
    PREPARE = "prepare"
    SUBMIT = "submit"
    VERIFY = "verify"


class PermissionRegistry:
    """Maps adapter names to their allowed capability levels."""

    def __init__(self) -> None:
        self._permissions: dict[str, set[CapabilityLevel]] = {}

    def register(self, adapter_name: str, levels: Iterable[CapabilityLevel]) -> None:
        """Grant *levels* to *adapter_name* (replacing any previous grant)."""
        self._permissions[adapter_name] = set(levels)

    def capabilities(self, adapter_name: str) -> frozenset[CapabilityLevel]:
        """The capabilities granted to *adapter_name* (empty when unknown)."""
        return frozenset(self._permissions.get(adapter_name, set()))

    def can(self, adapter_name: str, capability: CapabilityLevel) -> bool:
        """True when *adapter_name* holds *capability*."""
        return capability in self._permissions.get(adapter_name, set())

    def can_read(self, adapter_name: str) -> bool:
        return self.can(adapter_name, CapabilityLevel.READ)

    def can_search(self, adapter_name: str) -> bool:
        return self.can(adapter_name, CapabilityLevel.SEARCH)

    def can_prepare(self, adapter_name: str) -> bool:
        return self.can(adapter_name, CapabilityLevel.PREPARE)

    def can_submit(self, adapter_name: str) -> bool:
        return self.can(adapter_name, CapabilityLevel.SUBMIT)

    def can_verify(self, adapter_name: str) -> bool:
        return self.can(adapter_name, CapabilityLevel.VERIFY)
