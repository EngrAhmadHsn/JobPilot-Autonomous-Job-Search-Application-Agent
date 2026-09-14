from __future__ import annotations

from urllib.parse import urlparse

from playwright.sync_api import Browser, Page, Playwright, sync_playwright

from src.applications.contracts import (
    ApplicationAdapter,
    ApplicationRequest,
    ApplicationResult,
    PreparedApplication,
    SubmissionEvidence,
)


class FakeAtsPlaywrightAdapter(ApplicationAdapter):
    """Playwright-backed adapter for a local fake ATS used for integration testing.

    This adapter is intentionally narrow: it supports localhost-based fake ATS pages,
    fills visible form fields, optionally uploads a resume file, and verifies the
    returned confirmation page before claiming success.
    """

    name = "fake-ats-playwright"

    def supports_url(self, url: str) -> bool:
        parsed = urlparse(url)
        host = (parsed.hostname or "").lower()
        return "fake-ats" in host or host in {"localhost", "127.0.0.1", "::1"}

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
        page = self._open_page(prepared.request.job_url)
        try:
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
                submit_button_obj.click()
            else:
                raise RuntimeError("Submit button is not clickable")
            page.wait_for_load_state("networkidle")

            confirmation_target = page.locator("body")
            confirmation_text = getattr(confirmation_target, "inner_text", None)
            if callable(confirmation_text):
                confirmation_text = confirmation_text()
            elif hasattr(confirmation_target, "value"):
                confirmation_text = confirmation_target.value
            else:
                confirmation_text = ""

            evidence = SubmissionEvidence(
                url=page.url,
                confirmation_text=confirmation_text,
                status="submitted",
            )
            result = ApplicationResult(
                success=self._looks_submitted(confirmation_text),
                status="submitted" if self._looks_submitted(confirmation_text) else "unknown",
                message="Application submitted via fake ATS flow"
                if self._looks_submitted(confirmation_text)
                else "Submission status could not be confirmed",
                evidence=evidence,
                metadata={"job_url": prepared.request.job_url},
            )
            return self.verify(result)
        finally:
            page.context.close()

    def verify(self, result: ApplicationResult) -> ApplicationResult:
        if result.evidence is None:
            return ApplicationResult(
                success=False,
                status="verification_failed",
                message="No evidence was captured for verification",
                metadata=result.metadata,
            )

        text = (result.evidence.confirmation_text or "").lower()
        if (
            "application submitted" in text
            or "thanks for applying" in text
            or "application received" in text
        ):
            return ApplicationResult(
                success=True,
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
        playwright: Playwright = sync_playwright().start()
        browser: Browser = playwright.chromium.launch(headless=True)
        page: Page = browser.new_page()
        page.goto(job_url, wait_until="domcontentloaded")
        return page

    @staticmethod
    def _looks_submitted(text: str) -> bool:
        lowered = text.lower()
        return any(
            token in lowered
            for token in ("application submitted", "thanks for applying", "application received")
        )
