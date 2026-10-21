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
        # WS-06 · SEC-08 / plan §35: a real Lever submission is not
        # implemented. The old placeholder returned an unconditional success,
        # which was a false claim of an application that never happened. It now
        # fails loudly; the permission registry refuses the call before it
        # arrives.
        logger.warning("Lever submit refused: submit capability not granted")
        raise PermissionError("submit capability not granted for this adapter")

    def verify(self, result: ApplicationResult) -> ApplicationResult:
        return ApplicationResult(
            success=result.success,
            status="verified" if result.success else result.status,
            message=result.message,
            evidence=result.evidence,
        )
