"""Lever API adapter for job application submission."""

from __future__ import annotations

import logging

from src.applications.contracts import (
    ApplicationAdapter,
    ApplicationRequest,
    ApplicationResult,
    PreparedApplication,
)
from src.security.allowlist import host_matches_domain
from src.security.permissions import CapabilityLevel

logger = logging.getLogger(__name__)


class LeverAdapter(ApplicationAdapter):
    """Adapter for Lever-hosted job applications."""

    name = "lever"

    def supports_url(self, url: str) -> bool:
        # Exact host matching (WS-06 · SEC-06): a substring test would let
        # "notlever.co.attacker.com" select this adapter.
        return host_matches_domain(url, "lever.co")

    def prepare(self, request: ApplicationRequest) -> PreparedApplication:
        fields = {
            "candidate_name": request.candidate_name,
            "email": request.email,
            "phone": request.phone,
            "resume_path": request.resume_path or "",
            "cover_letter": request.cover_letter or "",
            **request.custom_fields,
        }
        return PreparedApplication(
            request=request,
            prepared_fields=fields,
            resume_path=request.resume_path,
            cover_letter=request.cover_letter,
        )

    def submit(self, prepared: PreparedApplication) -> ApplicationResult:
        # WS-32: the adapter's own second layer, from the one implementation on
        # the base class. The registry refuses the call before it arrives; an
        # adapter called directly (a script, a test, a future caller) refuses
        # it here.
        self.require_capability(CapabilityLevel.SUBMIT)
        # WS-06 · SEC-08 / plan §35: a real Lever submission is not
        # implemented. The old placeholder returned an unconditional success,
        # which was a false claim of an application that never happened. It now
        # fails loudly. This raise is unreachable while the documented matrix
        # grants Lever PREPARE only; it is the refusal a caller sees if SUBMIT
        # is ever granted here without a submission being implemented.
        logger.warning("Lever submit refused: submit capability not granted")
        raise PermissionError("submit capability not granted for this adapter")

    def verify(self, result: ApplicationResult) -> ApplicationResult:
        # The verify capability is granted separately from submit (WS-06 ·
        # SEC-08), so it is checked separately — the adapter refuses what it
        # was not granted even when the node's gate is bypassed (WS-32).
        self.require_capability(CapabilityLevel.VERIFY)
        return ApplicationResult(
            success=result.success,
            status="verified" if result.success else result.status,
            message=result.message,
            evidence=result.evidence,
        )
