"""Playwright adapter for the local fake ATS, with the WS-06 security controls
and the WS-08 form understanding.

The adapter is the only component that actually drives a browser in this
version, so it is where the browser-side controls live:

* **Domain allowlist** — the target is checked before the navigation, and the
  URL after the navigation is checked again (an unexpected redirect is a
  failure, not a detail). Every page of a multi-step form is checked too.
* **Challenge stop** — a CAPTCHA or multi-factor prompt ends the flow with
  ``status="blocked_human_review"``. The adapter never tries to solve one.
* **Evidence capture** — a screenshot of the outcome page, an ordered trace of
  the navigation and the actions, and the Playwright trace archive.
  A submission that cannot produce its artifacts is never a success.
* **Form understanding (WS-08)** — the page is *walked* through its
  accessibility tree, the questions are classified, and only the questions
  the candidate's evidence covers are answered. An unknown question stops the
  run with ``status="needs_human"``; the agent never guesses (plan §24).
* **Semantic locators** — a labelled field is found by its label or its role.
  The only CSS in this module is the documented file-input exception and the
  validation-error sweep.
* **Session isolation (SEC-07)** — every run gets a fresh browser *and* a
  fresh context, so no cookie or storage survives a run.
"""

from __future__ import annotations

import json
import logging
import os
import re
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
from src.applications.form import (
    FormPlan,
    ProfileFacts,
    build_form_plan,
    checkbox_truth,
    read_controls,
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

# The button that submits the form. The pattern is matched against the
# button's *accessible name*, never against its position on the page.
SUBMIT_BUTTON = re.compile(r"submit|apply|send", re.IGNORECASE)

# The button that advances a wizard to its next step.
NEXT_BUTTON = re.compile(r"next|continue|proceed", re.IGNORECASE)

# How many pages a single form may have. A form that never reaches a submit
# button is stopped rather than followed forever.
MAX_PAGES = 10

# How many times a rejected submission is retried with the prepared data.
MAX_SUBMIT_ATTEMPTS = 2

# The controls whose answer is typed into a field.
_TYPED_KINDS = frozenset(
    {"text", "textarea", "email", "tel", "number", "url", "password", "search", "date"}
)


def launch_options() -> dict[str, bool]:
    """The Chromium launch options, read from the environment.

    ``PLAYWRIGHT_HEADLESS`` decides whether the browser runs with a window.
    The default is headless, which is what a server wants; setting it to
    ``false`` on a workstation lets an operator watch the form being filled,
    which is the fastest way to understand a browser-layer failure.

    The flag is deliberately *only* about the window. Every security control
    around the browser — the allowlist, the fresh context per run, the
    challenge stop, the evidence capture — is independent of it, so a
    visible browser is not a weaker one.
    """
    raw = os.getenv("PLAYWRIGHT_HEADLESS", "true").strip().lower()
    return {"headless": raw not in {"false", "0", "no", "off"}}


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


@dataclass
class _StepOutcome:
    """What one page of the form produced."""

    kind: str = "form_error"
    errors: list[str] = field(default_factory=list)
    questions: list[str] = field(default_factory=list)
    challenge: str | None = None


class FakeAtsPlaywrightAdapter(ApplicationAdapter):
    """Playwright-backed adapter for a local fake ATS used for integration testing.

    The adapter understands the *form*, not just the page: it walks the
    controls through the accessibility tree, answers only what the candidate's
    evidence covers, and stops — loudly and with evidence — when it cannot
    answer.
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
            # WS-08: the grounded profile facts travel with the payload, so
            # the browser step can answer a question from the candidate's own
            # document.
            profile_facts=dict(request.profile_facts),
        )

    # ------------------------------------------------------------------
    # The submission
    # ------------------------------------------------------------------

    def submit(self, prepared: PreparedApplication) -> ApplicationResult:
        """Submit the application and capture the evidence of the outcome.

        Returns:
            The result of the submission. Any of the failure modes is a
            *result* with a specific status — never an exception and never a
            success without evidence.
        """
        workflow_id = prepared.workflow_id or uuid.uuid4().hex[:8]
        # WS-14 · Phase B: the evidence belongs to the account the run
        # was made for, so it is written into that account's own
        # directory. Without an owner (the evaluation harness, a script
        # that predates the multi-user work) the shared directory is
        # used.
        if prepared.owner_id:
            from src.storage.paths import KIND_EVIDENCE, user_dir

            evidence_dir = ensure_dir(user_dir(prepared.owner_id, KIND_EVIDENCE))
        else:
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

            outcome = self._drive_form(page, prepared, trace, evidence_dir, workflow_id)

            if outcome.kind == "blocked":
                return self._blocked_result(
                    page, outcome, trace, context, evidence_dir, workflow_id, prepared
                )
            if outcome.kind == "unsafe_navigation":
                return self._unsafe_navigation_result(
                    page, outcome, trace, context, evidence_dir, workflow_id, prepared
                )
            if outcome.kind == "needs_human":
                return self._needs_human_result(
                    page, outcome, trace, context, evidence_dir, workflow_id, prepared
                )
            if outcome.kind == "form_error":
                return self._form_error_result(
                    page, outcome, trace, context, evidence_dir, workflow_id, prepared
                )

            return self._submitted_result(page, trace, context, evidence_dir, workflow_id, prepared)
        except Exception as exc:  # an unexpected failure is a result, not a crash
            logger.exception("[%s] The submission failed", workflow_id)
            return ApplicationResult(
                success=False,
                status="submission_failed",
                message=f"The submission could not be completed: {exc}",
                metadata={"job_url": prepared.request.job_url, "error": str(exc)},
            )
        finally:
            try:
                page.context.close()
            finally:
                self._shutdown_browser()

    # ------------------------------------------------------------------
    # The form
    # ------------------------------------------------------------------

    def _drive_form(
        self,
        page: Page,
        prepared: PreparedApplication,
        trace: NavigationTrace,
        evidence_dir: Path,
        workflow_id: str,
    ) -> _StepOutcome:
        """Walk the pages of the form until one of them settles the run."""
        facts = ProfileFacts.from_prepared(prepared)

        for page_index in range(MAX_PAGES):
            # SEC-06: every page the browser reaches is checked, not only the
            # first one.
            try:
                assert_navigation_allowed(page.url, allow_localhost=self._allow_localhost())
            except DisallowedDomainError as exc:
                logger.warning(
                    "[%s] Navigation refused on page %d: %s", workflow_id, page_index, exc
                )
                return _StepOutcome(kind="unsafe_navigation", errors=[str(exc)])

            # SEC-09: a challenge stops the flow before any form interaction.
            challenge = inspect_page(page)
            if challenge:
                logger.warning("[%s] Blocked by a page challenge: %s", workflow_id, challenge)
                return _StepOutcome(kind="blocked", challenge=challenge)

            plan = build_form_plan(read_controls(page), facts)
            if plan.unresolved:
                # Plan §24: a question we cannot ground is not answered. The
                # run stops *before* anything is typed and *before* anything
                # is submitted.
                logger.warning(
                    "[%s] %d question(s) could not be answered: %s",
                    workflow_id,
                    len(plan.unresolved),
                    ", ".join(plan.unresolved),
                )
                return _StepOutcome(kind="needs_human", questions=list(plan.unresolved))

            outcome = self._fill_and_submit(page, plan, facts, prepared, trace)
            if outcome.kind != "next":
                return outcome

            logger.info("[%s] Advanced to the next page of the form", workflow_id)

        return _StepOutcome(
            kind="form_error",
            errors=[f"The form did not reach a submission after {MAX_PAGES} pages."],
        )

    def _fill_and_submit(
        self,
        page: Page,
        plan: FormPlan,
        facts: ProfileFacts,
        prepared: PreparedApplication,
        trace: NavigationTrace,
    ) -> _StepOutcome:
        """Fill the page and submit it, retrying once on a rejected form."""
        current_plan = plan

        for attempt in range(MAX_SUBMIT_ATTEMPTS):
            self._fill_plan(page, current_plan, prepared, trace)

            button, is_submit = self._find_button(page)
            if button is None:
                return _StepOutcome(
                    kind="form_error",
                    errors=["No submit or next button was found on the page."],
                )

            trace.record(f"click_{'submit' if is_submit else 'next'}", page.url)
            url_before = page.url
            button.click()
            self._wait_for_page(page)

            errors = self._collect_errors(page)
            if not errors and is_submit:
                # A submit that neither moved the page nor confirmed anything
                # was never sent — the browser refused it.
                text = self._page_text(page)
                if page.url == url_before and not self._looks_submitted(text):
                    errors = [
                        "The browser did not send the form; a field failed the page's own validation."
                    ]
            if not errors:
                return _StepOutcome(kind="submitted" if is_submit else "next")

            if attempt + 1 < MAX_SUBMIT_ATTEMPTS:
                # One remediation retry: the server rejected the form, so the
                # prepared data is applied to the re-rendered page and
                # submitted again.
                logger.info("The form was rejected (%s); retrying once", "; ".join(errors))
                current_plan = build_form_plan(read_controls(page), facts)
                if current_plan.unresolved:
                    return _StepOutcome(kind="needs_human", questions=list(current_plan.unresolved))
                continue

            return _StepOutcome(kind="form_error", errors=errors)

        return _StepOutcome(kind="form_error", errors=["The form was not submitted."])

    def _fill_plan(
        self,
        page: Page,
        plan: FormPlan,
        prepared: PreparedApplication,
        trace: NavigationTrace,
    ) -> None:
        """Type the answers of a plan into the page."""
        for question in plan.questions:
            value = plan.answers.get(question.label)
            if value is None:
                continue
            if question.kind == "file":
                # The file is uploaded, not typed.
                continue
            self._fill_control(page, question, value, trace)

        self._upload_resume(page, prepared, trace)

    def _fill_control(
        self,
        page: Page,
        question,
        value: str,
        trace: NavigationTrace,
    ) -> None:
        """Fill one control with its grounded value."""
        kind = question.kind

        if kind in _TYPED_KINDS:
            self._label_locator(page, question.label).fill(value)
        elif kind == "select":
            self._label_locator(page, question.label).select_option(label=value)
        elif kind == "radio":
            page.get_by_role("radio", name=value).check()
        elif kind == "checkbox":
            if question.options:
                page.get_by_role("checkbox", name=value).check()
            else:
                locator = self._label_locator(page, question.label)
                if checkbox_truth(value):
                    locator.check()
                else:
                    locator.uncheck()
        else:
            logger.warning("The control kind %r is not supported; it was left alone", kind)
            return

        trace.record(f"fill:{question.label}", page.url)

    def _upload_resume(
        self,
        page: Page,
        prepared: PreparedApplication,
        trace: NavigationTrace,
    ) -> None:
        """Attach the resume to the file input, when there is one.

        The file input is the one documented CSS exception: a file control has
        no accessible name that a form can be addressed by, and the input
        itself is the only handle the browser offers.
        """
        if not prepared.resume_path:
            return
        try:
            file_input = page.locator("input[type='file']").first
            if file_input.count() == 0:
                return
            file_input.set_input_files(prepared.resume_path)
        except Exception as exc:  # noqa: BLE001 - an upload failure is not fatal on its own
            logger.warning("The resume could not be attached: %s", exc)
            return
        trace.record("upload_resume", page.url)

    # ------------------------------------------------------------------
    # The locators
    # ------------------------------------------------------------------

    @staticmethod
    def _label_locator(page: Page, label: str):
        """The control a label names.

        The exact match is tried first. When the page words the label a little
        differently, the fallback is a **regular expression on the same
        label** — never a CSS selector, and never an id.
        """
        locator = page.get_by_label(label, exact=True)
        try:
            if locator.count() == 0:
                locator = page.get_by_label(re.compile(re.escape(label), re.IGNORECASE))
        except Exception as exc:  # noqa: BLE001 - the caller reports the failure
            logger.debug("The label %r could not be resolved: %s", label, exc)
        return locator

    @staticmethod
    def _find_button(page: Page) -> tuple[object | None, bool]:
        """The button that submits the form, or the one that advances it.

        Returns:
            The button and whether it is a submit button.
        """
        for pattern, is_submit in ((SUBMIT_BUTTON, True), (NEXT_BUTTON, False)):
            try:
                buttons = page.get_by_role("button", name=pattern)
                if buttons.count() == 0:
                    continue
                return buttons.first, is_submit
            except Exception as exc:  # noqa: BLE001 - a missing button is handled by the caller
                logger.debug("No %s button was found: %s", pattern.pattern, exc)
        return None, False

    @staticmethod
    def _collect_errors(page: Page) -> list[str]:
        """The validation errors the page is showing.

        The accessible role is the primary source. The class-based sweep is
        the documented second source: a form that marks its error box with a
        class and no role still has to be noticed. The browser's **own**
        validation is the third: a field the page itself refuses never reaches
        the server, and the message the browser holds is the honest reason.
        """
        messages: list[str] = []

        try:
            alerts = page.get_by_role("alert")
            for index in range(alerts.count()):
                text = alerts.nth(index).inner_text().strip()
                if text:
                    messages.append(text)
        except Exception as exc:  # noqa: BLE001 - a page without alerts is the normal case
            logger.debug("The alerts could not be read: %s", exc)

        if not messages:
            try:
                errors = page.locator(".error, [aria-invalid='true']")
                for index in range(errors.count()):
                    text = errors.nth(index).inner_text().strip()
                    if text:
                        messages.append(text)
            except Exception as exc:  # noqa: BLE001 - a page without errors is the normal case
                logger.debug("The error elements could not be read: %s", exc)

        if not messages:
            messages.extend(FakeAtsPlaywrightAdapter._native_validation_messages(page))

        return messages

    @staticmethod
    def _native_validation_messages(page: Page) -> list[str]:
        """The messages the browser itself holds for the invalid fields.

        A page that marks a field ``required`` refuses the submission before
        it is ever sent. The bubble the browser draws is not part of the DOM,
        but the reason is: it is read from the control's own validity state.
        """
        try:
            controls = page.locator("input, select, textarea")
            messages = controls.evaluate_all(
                "els => els.filter(el => el.willValidate && !el.validity.valid)"
                " .map(el => el.validationMessage || 'This field is required.')"
            )
        except Exception as exc:  # noqa: BLE001 - a page without invalid fields is the normal case
            logger.debug("The native validation messages could not be read: %s", exc)
            return []
        return [str(message).strip() for message in messages or [] if str(message).strip()]

    @staticmethod
    def _wait_for_page(page: Page) -> None:
        """Wait for the page that a click led to."""
        try:
            page.wait_for_load_state("domcontentloaded")
        except Exception as exc:  # noqa: BLE001 - the page may already be there
            logger.debug("The page did not report a load state: %s", exc)

    # ------------------------------------------------------------------
    # The results
    # ------------------------------------------------------------------

    def _capture_outcome(
        self,
        page: Page,
        trace: NavigationTrace,
        context,
        evidence_dir: Path,
        workflow_id: str,
        status: str,
    ) -> SubmissionEvidence:
        """The evidence of a run that did not submit."""
        screenshot = self._capture_screenshot(page, evidence_dir, workflow_id)
        trace_path = trace.write(evidence_dir / f"{workflow_id}.trace.json")
        self._stop_tracing(context, evidence_dir, workflow_id)
        return SubmissionEvidence(
            url=page.url,
            confirmation_text=None,
            screenshot_path=screenshot,
            trace_path=trace_path.name if trace_path else None,
            status=status,
        )

    def _blocked_result(
        self,
        page: Page,
        outcome: _StepOutcome,
        trace: NavigationTrace,
        context,
        evidence_dir: Path,
        workflow_id: str,
        prepared: PreparedApplication,
    ) -> ApplicationResult:
        """The result of a run that met a challenge (or an unsafe URL)."""
        challenge = outcome.challenge or "unsafe navigation"
        evidence = self._capture_outcome(
            page, trace, context, evidence_dir, workflow_id, "blocked_human_review"
        )
        return ApplicationResult(
            success=False,
            status="blocked_human_review",
            message=(
                "The page presented a CAPTCHA or multi-factor challenge "
                f"({challenge!r}). The flow was stopped; no attempt was made "
                "to solve it."
            ),
            evidence=evidence,
            metadata={"job_url": prepared.request.job_url, "challenge": challenge},
        )

    def _unsafe_navigation_result(
        self,
        page: Page,
        outcome: _StepOutcome,
        trace: NavigationTrace,
        context,
        evidence_dir: Path,
        workflow_id: str,
        prepared: PreparedApplication,
    ) -> ApplicationResult:
        """The result of a run that reached a URL the allowlist refuses."""
        evidence = self._capture_outcome(
            page, trace, context, evidence_dir, workflow_id, "unsafe_navigation"
        )
        return ApplicationResult(
            success=False,
            status="unsafe_navigation",
            message="; ".join(outcome.errors),
            evidence=evidence,
            metadata={"job_url": prepared.request.job_url},
        )

    def _needs_human_result(
        self,
        page: Page,
        outcome: _StepOutcome,
        trace: NavigationTrace,
        context,
        evidence_dir: Path,
        workflow_id: str,
        prepared: PreparedApplication,
    ) -> ApplicationResult:
        """The result of a run that met a question it could not answer."""
        evidence = self._capture_outcome(
            page, trace, context, evidence_dir, workflow_id, "needs_human"
        )
        questions = list(outcome.questions)
        return ApplicationResult(
            success=False,
            status="needs_human",
            message=(
                "The form asks "
                f"{len(questions)} question(s) the candidate's evidence does not answer: "
                f"{'; '.join(questions)}. Nothing was submitted; a human has to answer them."
            ),
            evidence=evidence,
            metadata={
                "job_url": prepared.request.job_url,
                "questions": questions,
            },
        )

    def _form_error_result(
        self,
        page: Page,
        outcome: _StepOutcome,
        trace: NavigationTrace,
        context,
        evidence_dir: Path,
        workflow_id: str,
        prepared: PreparedApplication,
    ) -> ApplicationResult:
        """The result of a run the server rejected."""
        errors = list(outcome.errors)
        evidence = self._capture_outcome(
            page, trace, context, evidence_dir, workflow_id, "form_error"
        )
        return ApplicationResult(
            success=False,
            status="form_error",
            message=(
                f"The form was rejected by the server after {MAX_SUBMIT_ATTEMPTS} attempts: "
                f"{'; '.join(errors)}"
            ),
            evidence=evidence,
            metadata={
                "job_url": prepared.request.job_url,
                "errors": errors,
            },
        )

    def _submitted_result(
        self,
        page: Page,
        trace: NavigationTrace,
        context,
        evidence_dir: Path,
        workflow_id: str,
        prepared: PreparedApplication,
    ) -> ApplicationResult:
        """The result of a run that reached a confirmation page."""
        trace.record("confirmation_page", page.url)

        confirmation_text = self._page_text(page)
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

        confirmed = self._looks_submitted(confirmation_text)
        result = ApplicationResult(
            success=confirmed,
            status="submitted" if confirmed else "unknown",
            message="Application submitted via fake ATS flow"
            if confirmed
            else "Submission status could not be confirmed",
            evidence=evidence,
            metadata={
                "job_url": prepared.request.job_url,
                "playwright_trace_path": archive_path.name if archive_path else None,
            },
        )
        return self.verify(result)

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

    # ------------------------------------------------------------------
    # The browser
    # ------------------------------------------------------------------

    def _open_page(self, job_url: str) -> Page:
        """Open the target page, refusing a URL the allowlist does not accept.

        The URL is checked **before** the navigation, and the URL the browser
        ended up on is checked **after** it: a redirect to a host that is not
        on the allowlist is a failure, not a detail (SECURITY.md §6.5).

        Every run gets a fresh browser **and** a fresh context (SEC-07), so
        no cookie or storage survives from one submission to the next.

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
            browser: Browser = playwright.chromium.launch(**launch_options())
        except Exception:
            self._stop_playwright(playwright)
            raise
        try:
            # SEC-07: an explicit, fresh context per run.
            context = browser.new_context()
            page = context.new_page()
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
        """Capture the page; returns the stored file name."""
        screenshot = evidence_dir / f"{workflow_id}.png"
        try:
            page.screenshot(path=str(screenshot))
        except Exception as exc:  # noqa: BLE001 - evidence, not the flow
            logger.warning("Screenshot could not be captured: %s", exc)
            return None
        return screenshot.name

    @staticmethod
    def _page_text(page) -> str:
        """The visible text of the page."""
        try:
            body = page.locator("body")
            inner_text = getattr(body, "inner_text", None)
            if callable(inner_text):
                return str(inner_text() or "")
        except Exception as exc:  # noqa: BLE001 - an unreadable page is not a confirmation
            logger.debug("The page text could not be read: %s", exc)
        return ""

    @staticmethod
    def _looks_submitted(text: str) -> bool:
        lowered = (text or "").lower()
        return any(token in lowered for token in CONFIRMATION_MARKERS)
