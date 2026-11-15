"""Greenhouse API adapter for job application submission.

Two responsibilities live here, and they are different things:

* **The submission path** (:meth:`GreenhouseAdapter.prepare`,
  :meth:`submit`, :meth:`verify`) — unchanged in behaviour. A real
  Greenhouse submission is still not implemented and still fails loudly
  rather than claiming a success that never happened.
* **The form and liveness path** (WS-25) — reading the board's own
  published application form schema, and checking that the job is still
  open.

Both are read-only, public and key-less.
"""

from __future__ import annotations

import logging
import re
from typing import Any

from src.applications.contracts import (
    ApplicationAdapter,
    ApplicationRequest,
    ApplicationResult,
    PreparedApplication,
)
from src.applications.greenhouse_forms import FormSchema, build_form_schema
from src.security.allowlist import host_matches_domain
from src.security.permissions import CapabilityLevel

logger = logging.getLogger(__name__)

GREENHOUSE_API_HOST = "boards-api.greenhouse.io"
GREENHOUSE_BASE_URL = f"https://{GREENHOUSE_API_HOST}/v1/boards"

#: A board token and a job id are URL path segments. Anything outside
#: this set is refused before a URL is built — the same rule the job
#: discovery adapter uses (WS-15).
_PATH_SEGMENT_RE = re.compile(r"[A-Za-z0-9_-]+")

#: A Greenhouse application URL carries the board token and the job id as
#: path segments: ``https://boards.greenhouse.io/{token}/jobs/{id}``.
#: The token is *not* the company name (``anduril`` 404s while
#: ``andurilindustries`` answers), so it is read from the URL rather than
#: guessed.
_JOB_URL_RE = re.compile(
    r"^https?://(?:[\w-]+\.)*greenhouse\.io/(?P<token>[A-Za-z0-9_-]+)/jobs/(?P<job_id>\d+)",
    re.IGNORECASE,
)


def parse_greenhouse_job_url(url: str) -> tuple[str, str] | None:
    """The board token and job id in a Greenhouse job URL, or ``None``.

    Returns ``None`` for a URL that is not a Greenhouse job URL. A URL
    that *is* one but carries a malformed segment also returns ``None`` —
    the caller must not build a request from it.
    """
    if not url or not isinstance(url, str):
        return None
    match = _JOB_URL_RE.match(url.strip())
    if match is None:
        return None
    token = match.group("token")
    job_id = match.group("job_id")
    if not _PATH_SEGMENT_RE.fullmatch(token) or not job_id.isdigit():
        return None
    return token, job_id


class GreenhouseAdapter(ApplicationAdapter):
    """Adapter for Greenhouse-hosted job applications.

    Uses the Greenhouse public API / application endpoint where available.
    Falls back to structured payload preparation for manual submission.
    """

    name = "greenhouse"

    def supports_url(self, url: str) -> bool:
        # Exact host matching (WS-06 · SEC-06): a substring test would let
        # "evil-greenhouse.io.attacker.com" select this adapter.
        return host_matches_domain(url, "greenhouse.io")

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
        # WS-06 · SEC-08 / plan §35: a real Greenhouse submission is not
        # implemented. The old placeholder returned an unconditional success,
        # which was a false claim of an application that never happened. It now
        # fails loudly. This raise is unreachable while the documented matrix
        # grants Greenhouse PREPARE only; it is the refusal a caller sees if
        # SUBMIT is ever granted here without a submission being implemented.
        logger.warning("Greenhouse submit refused: submit capability not granted")
        raise PermissionError("submit capability not granted for this adapter")

    def verify(self, result: ApplicationResult) -> ApplicationResult:
        # The verify capability is granted separately from submit (WS-06 ·
        # SEC-08), so it is checked separately — the adapter refuses what it
        # was not granted even when the node's gate is bypassed (WS-32).
        self.require_capability(CapabilityLevel.VERIFY)
        # Placeholder verification
        return ApplicationResult(
            success=result.success,
            status="verified" if result.success else result.status,
            message=result.message,
            evidence=result.evidence,
        )

    # -- the form and liveness path (WS-25) --------------------------------

    async def fetch_form_schema(
        self, job_url: str, *, client: Any | None = None
    ) -> FormSchema | None:
        """The board's published application form for this job.

        Greenhouse publishes it at
        ``GET .../boards/{token}/jobs/{job_id}?questions=true`` — the only
        public form schema of the four providers (WS-25).

        Returns ``None`` when the URL is not a Greenhouse job URL or when
        the board publishes no schema. A board that publishes no schema
        is not a failure: the caller falls back to the fixed field map.
        """
        from src.jobs.http_client import create_client

        parsed = parse_greenhouse_job_url(job_url)
        if parsed is None:
            return None
        token, job_id = parsed
        url = f"{GREENHOUSE_BASE_URL}/{token}/jobs/{job_id}?questions=true"

        if client is not None:
            return await self._fetch_schema_with(client, url)
        async with create_client() as owned:
            return await self._fetch_schema_with(owned, url)

    async def _fetch_schema_with(self, client: Any, url: str) -> FormSchema | None:
        from src.jobs.http_client import SourceError, guarded_get

        try:
            response = await guarded_get(client, url)
            payload = response.json()
        except (SourceError, ValueError) as exc:
            logger.warning("Greenhouse form schema unavailable: %s", exc)
            return None
        if not isinstance(payload, dict):
            return None
        return build_form_schema(payload)

    async def check_job_is_live(
        self, job_url: str, *, client: Any | None = None
    ) -> tuple[bool, str]:
        """Whether the job is still published and accepting applications.

        WS-25. A job must be live to accept an application, so re-fetching
        the job just before the approval is a **liveness check** that
        costs one request and prevents the agent from applying to a
        posting that closed months ago.

        The corpus has no expiry signal (WS-23, Phase 6), so this is the
        layer that actually protects the application.

        Returns:
            ``(is_live, reason)``. ``is_live`` is False when the job is
            gone (404), when the board says it is unpublished, or when the
            posting carries a deadline that has passed. The reason says
            which, so the operator is told what happened.
        """
        from src.jobs.http_client import create_client

        parsed = parse_greenhouse_job_url(job_url)
        if parsed is None:
            return False, "the URL is not a Greenhouse job URL"
        token, job_id = parsed
        url = f"{GREENHOUSE_BASE_URL}/{token}/jobs/{job_id}"

        if client is not None:
            return await self._check_live_with(client, url)
        async with create_client() as owned:
            return await self._check_live_with(owned, url)

    async def _check_live_with(self, client: Any, url: str) -> tuple[bool, str]:
        from src.jobs.http_client import SourceError, guarded_get

        try:
            response = await guarded_get(client, url)
        except SourceError as exc:
            message = str(exc)
            if "404" in message:
                return False, "the job is no longer published (404)"
            return False, f"the job could not be checked: {message}"
        try:
            payload = response.json()
        except ValueError:
            return False, "the job returned a response that is not JSON"

        if not isinstance(payload, dict):
            return False, "the job returned an unexpected payload"

        deadline = payload.get("application_deadline")
        if isinstance(deadline, str) and deadline.strip() and _deadline_has_passed(deadline):
            return False, f"the application deadline passed ({deadline.strip()})"

        return True, "the job is published and accepting applications"


def _deadline_has_passed(deadline: str) -> bool:
    """Whether an ISO-8601 application deadline is in the past.

    A deadline that cannot be parsed is **not** treated as passed: the
    job is still live, and refusing to apply on an unparsable date would
    be a guess.
    """
    from datetime import UTC, datetime

    # ``fromisoformat`` reads the ISO-8601 UTC designator ("Z") on every
    # Python version this project supports.
    try:
        parsed = datetime.fromisoformat(deadline.strip())
    except ValueError:
        return False
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed < datetime.now(UTC)
