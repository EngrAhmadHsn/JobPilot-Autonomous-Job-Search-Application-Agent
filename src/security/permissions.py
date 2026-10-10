"""Permission registry enforcing least-privilege for adapters."""

from __future__ import annotations

from src.security.allowlist import CapabilityLevel


class PermissionRegistry:
    """Maps adapter names to allowed capability levels."""

    def __init__(self):
        self._permissions: dict[str, set[CapabilityLevel]] = {}

    def register(self, adapter_name: str, levels: list[CapabilityLevel]):
        self._permissions[adapter_name] = set(levels)

    def can_submit(self, adapter_name: str) -> bool:
        return CapabilityLevel.SUBMIT in self._permissions.get(adapter_name, set())

    def can_read(self, adapter_name: str) -> bool:
        return CapabilityLevel.READ in self._permissions.get(adapter_name, set())
