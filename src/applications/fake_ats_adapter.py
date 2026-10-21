"""Playwright adapter for the local fake ATS, with the WS-06 security controls.

The adapter is the only component that actually drives a browser in this
version, so it is where the browser-side controls live:

* **Domain allowlist** — the target is checked before the navigation, and the
  URL after the navigation is checked again (an unexpected redirect is a
  failure, not a detail).
* **Challenge stop** — a CAPTCHA or multi-factor prompt ends the flow with
  ``status="blocked_human_review"``. The adapter never tries to solve one.
* **Evidence capture** — a screenshot of the confirmation page, an ordered
  trace of the navigation and the clicks, and the Playwright trace archive.
  A submission that cannot produce its artifacts is never a success.
"""

from __future__ import annotations

import json
import logging
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlparse

from playwright.sync_api import Browser, Page, Playwright, sync_playwright

from src.applications.contracts import (
    ApplicationAdapter,
    ApplicationRequest,
    ApplicationResult,
    PreparedApplication,
    SubmissionEvidence,
)
from src.config.settings import ensure_dir, get_settings
from src.security.allowlist import DisallowedDomainError, assert_navigation_allowed
from src.security.page_guards import inspect_page

logger = logging.getLogger(__name__)

# The confirmation phrases the fake ATS (and a real one) uses to confirm a
# submission. A page without one of them is not a confirmed submission.
CONFIRMATION_MARKERS = (
    "application submitted",
    "thanks for applying",
    "application received",
)


@dataclass
class NavigationTrace:
    """An ordered record of what the browser did.

    The trace is **evidence**: it records the URLs the browser actually
    visited and the actions it performed. It is never interpreted as an
    instruction.
    """

    entries: list[dict] = field(default_factory=list)

    def record(self, action: str, url: str) -> None:
        """Append one action to the trace."""
        self.entries.append(
            {
                "action": action,
                "url": url,
                "timestamp": datetime.now(UTC).isoformat(),
            }
        )

    def write(self, path: Path) -> Path:
        """Write the trace as JSON and return the path."""
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.entries, indent=2), encoding="utf-8")
        return path


class FakeAtsPlaywrightAdapter(ApplicationAdapter):
    """Playwright-backed adapter for a local fake ATS used for integration testing.

    This adapter is intentionally narrow: it supports localhost-based fake ATS pages,
    fills visible form fields, optionally uploads a resume file, and verifies the
    returned confirmation page before claiming success.
    """

    name = "fake-ats-playwright"

    def __init__(self) -> None:
        # The browser session opened for the current submission. It is closed
        # (and Playwright stopped) when the submission ends.
        self._browser: Browser | None = None
        self._playwright: Playwright | None = None

    def supports_url(self, url: str) -> bool:
        parsed = urlparse(url)
        host = (parsed.hostname or "").lower()
        # Exact matching (WS-06 · SEC-06): "fake-ats" must be the host or a
        # label of it, not a substring of an unrelated domain.
        return (
            host in {"localhost", "127.0.0.1", "::1"}
            or host == "fake-ats"
            or host.endswith(".fake-ats")
        )

    def prepare(self, request: ApplicationRequest) -> PreparedApplication:
        if not self.supports_url(request.job_url):
            raise ValueError(f"This adapter only supports fake ATS URLs, got: {request.job_url}")

        fields = {
            "candidate_name": request.candidate_name,
            "email": request.email,
            "phone": request.phone,
        }
        for key, value in request.custom_fields.items():
            fields[key] = value

        return PreparedApplication(
            request=request,
            prepared_fields=fields,
            resume_path=request.resume_path,
            cover_letter=request.cover_letter,
            requires_manual_review=False,
        )

    def submit(self, prepared: PreparedApplication) -> ApplicationResult:
        """Submit the application and capture the evidence of the outcome.

        Returns:
            The result of the submission. Any of the failure modes is a
            *result* with a specific status — never an exception and never a
            success without evidence.
        """
        workflow_id = prepared.workflow_id or uuid.uuid4().hex[:8]
        evidence_dir = ensure_dir(get_settings().evidence_dir)
        trace = NavigationTrace()

        try:
            page = self._open_page(prepared.request.job_url)
        except DisallowedDomainError as exc:
            logger.warning("[%s] Navigation refused: %s", workflow_id, exc)
            return ApplicationResult(
                success=False,
                status="unsafe_navigation",
                message=str(exc),
                metadata={"job_url": prepared.request.job_url},
            )

        try:
            context = page.context
            self._start_tracing(context)

            # SEC-09: a challenge stops the flow before any form interaction.
            challenge = inspect_page(page)
            if challenge:
                logger.warning("[%s] Blocked by a page challenge: %s", workflow_id, challenge)
                screenshot = self._capture_screenshot(page, evidence_dir, workflow_id)
                return ApplicationResult(
                    success=False,
                    status="blocked_human_review",
                    message=(
                        "The page presented a CAPTCHA or multi-factor challenge "
                        f"({challenge!r}). The flow was stopped; no attempt was made "
                        "to solve it."
                    ),
                    evidence=SubmissionEvidence(
                        url=page.url,
                        confirmation_text=None,
                        screenshot_path=screenshot,
                        status="blocked_human_review",
                    ),
                    metadata={"job_url": prepared.request.job_url, "challenge": challenge},
                )

            page.locator("#candidate-name").fill(prepared.request.candidate_name)
            page.locator("#email").fill(prepared.request.email)
            page.locator("#phone").fill(prepared.request.phone)

            if prepared.cover_letter:
                page.locator("#cover-letter").fill(prepared.cover_letter)

            if prepared.resume_path:
                file_input = page.locator("input[type='file']")
                file_input_obj = getattr(file_input, "first", file_input)
                if hasattr(file_input_obj, "count") and file_input_obj.count() == 0:
                    file_input_obj = None
                if file_input_obj is not None and hasattr(file_input_obj, "set_input_files"):
                    file_input_obj.set_input_files(prepared.resume_path)

            submit_button = page.locator("button[type='submit'], input[type='submit']")
            submit_button_obj = getattr(submit_button, "first", submit_button)
            if hasattr(submit_button_obj, "count") and submit_button_obj.count() == 0:
                raise RuntimeError("No submit button found on fake ATS form")
            if hasattr(submit_button_obj, "click"):
                trace.record("click_submit", page.url)
                submit_button_obj.click()
            else:
                raise RuntimeError("Submit button is not clickable")
            page.wait_for_load_state("networkidle")
            trace.record("confirmation_page", page.url)

            confirmation_target = page.locator("body")
            confirmation_text = getattr(confirmation_target, "inner_text", None)
            if callable(confirmation_text):
                confirmation_text = confirmation_text()
            elif hasattr(confirmation_target, "value"):
                confirmation_text = confirmation_target.value
            else:
                confirmation_text = ""

            screenshot_path = self._capture_screenshot(page, evidence_dir, workflow_id)
            trace_path = trace.write(evidence_dir / f"{workflow_id}.trace.json")
            archive_path = self._stop_tracing(context, evidence_dir, workflow_id)

            evidence = SubmissionEvidence(
                url=page.url,
                confirmation_text=confirmation_text,
                screenshot_path=screenshot_path,
                trace_path=trace_path.name if trace_path else None,
                status="submitted",
            )

            missing = [
                name
                for name, value in (
                    ("screenshot", screenshot_path),
                    ("trace", trace_path),
                )
                if not value
            ]
            if missing:
                # SEC-14: a submission without its artifacts is never a success.
                logger.warning("[%s] Evidence incomplete: %s", workflow_id, ", ".join(missing))
                return ApplicationResult(
                    success=False,
                    status="evidence_incomplete",
                    message=(
                        "The form was submitted but the evidence could not be captured: "
                        f"{', '.join(missing)}."
                    ),
                    evidence=evidence,
                    metadata={"job_url": prepared.request.job_url},
                )

            result = ApplicationResult(
                success=self._looks_submitted(confirmation_text),
                status="submitted" if self._looks_submitted(confirmation_text) else "unknown",
                message="Application submitted via fake ATS flow"
                if self._looks_submitted(confirmation_text)
                else "Submission status could not be confirmed",
                evidence=evidence,
                metadata={
                    "job_url": prepared.request.job_url,
                    "playwright_trace_path": archive_path.name if archive_path else None,
                },
            )
            return self.verify(result)
        finally:
            try:
                page.context.close()
            finally:
                self._shutdown_browser()

    def verify(self, result: ApplicationResult) -> ApplicationResult:
        if result.evidence is None:
            return ApplicationResult(
                success=False,
                status="verification_failed",
                message="No evidence was captured for verification",
                metadata=result.metadata,
            )

        text = (result.evidence.confirmation_text or "").lower()
        confirmed = self._looks_submitted(text)
        if confirmed:
            return ApplicationResult(
                success=confirmed,
                status="verified",
                message="Application submission verified by confirmation page content.",
                evidence=result.evidence,
                metadata=result.metadata,
            )

        return ApplicationResult(
            success=False,
            status="verification_failed",
            message="Submission was attempted but confirmation could not be verified.",
            evidence=result.evidence,
            metadata=result.metadata,
        )

    def _open_page(self, job_url: str) -> Page:
        """Open the target page, refusing a URL the allowlist does not accept.

        The URL is checked **before** the navigation, and the URL the browser
        ended up on is checked **after** it: a redirect to a host that is not
        on the allowlist is a failure, not a detail (SECURITY.md §6.5).

        The Playwright instance and the browser are kept on the adapter so
        that :meth:`submit` can shut them down. They must be stopped: the
        sync API runs its dispatcher in a greenlet *in this thread*, so a
        leaked instance leaves a running event loop behind and the next
        browser use in the same thread fails with "Sync API inside the
        asyncio loop".
        """
        assert_navigation_allowed(job_url, allow_localhost=self._allow_localhost())

        playwright: Playwright = sync_playwright().start()
        try:
            browser: Browser = playwright.chromium.launch(headless=True)
        except Exception:
            self._stop_playwright(playwright)
            raise
        page: Page = browser.new_page()
        try:
            page.goto(job_url, wait_until="domcontentloaded")
            assert_navigation_allowed(page.url, allow_localhost=self._allow_localhost())
        except Exception:
            self._close_browser(browser, playwright)
            raise
        self._playwright = playwright
        self._browser = browser
        return page

    @staticmethod
    def _stop_playwright(playwright: Playwright) -> None:
        """Stop a Playwright instance, ignoring teardown errors."""
        try:
            playwright.stop()
        except Exception as exc:  # noqa: BLE001 - teardown must not mask the outcome
            logger.warning("Playwright could not be stopped cleanly: %s", exc)

    def _close_browser(self, browser: Browser | None, playwright: Playwright | None) -> None:
        """Close the browser and stop Playwright."""
        if browser is not None:
            try:
                browser.close()
            except Exception as exc:  # noqa: BLE001 - teardown must not mask the outcome
                logger.warning("The browser could not be closed cleanly: %s", exc)
        if playwright is not None:
            self._stop_playwright(playwright)

    def _shutdown_browser(self) -> None:
        """Close whatever this adapter opened."""
        self._close_browser(self._browser, self._playwright)
        self._browser = None
        self._playwright = None

    @staticmethod
    def _allow_localhost() -> bool:
        """The local fake ATS is reachable only outside production."""
        return get_settings().app_env == "development"

    @staticmethod
    def _start_tracing(context) -> None:
        """Start the Playwright trace; a failure only costs the archive."""
        tracing = getattr(context, "tracing", None)
        if tracing is None:
            return
        try:
            tracing.start(screenshots=True, sources=True)
        except Exception as exc:  # noqa: BLE001 - tracing is evidence, not the flow
            logger.warning("Playwright tracing could not be started: %s", exc)

    @staticmethod
    def _stop_tracing(context, evidence_dir: Path, workflow_id: str) -> Path | None:
        """Stop the Playwright trace and store the archive."""
        tracing = getattr(context, "tracing", None)
        if tracing is None:
            return None
        archive = evidence_dir / f"{workflow_id}.zip"
        try:
            tracing.stop(path=str(archive))
        except Exception as exc:  # noqa: BLE001 - tracing is evidence, not the flow
            logger.warning("Playwright trace could not be written: %s", exc)
            return None
        return archive

    @staticmethod
    def _capture_screenshot(page, evidence_dir: Path, workflow_id: str) -> str | None:
        """Capture the confirmation page; returns the stored file name."""
        screenshot = evidence_dir / f"{workflow_id}.png"
        try:
            page.screenshot(path=str(screenshot))
        except Exception as exc:  # noqa: BLE001 - evidence, not the flow
            logger.warning("Screenshot could not be captured: %s", exc)
            return None
        return screenshot.name

    @staticmethod
    def _looks_submitted(text: str) -> bool:
        lowered = (text or "").lower()
        return any(token in lowered for token in CONFIRMATION_MARKERS)
