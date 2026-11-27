"""The real native controls run in Chromium; every request ends in this fixture."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from playwright.sync_api import sync_playwright

from src.applications.posting_form import PostingForm, PostingQuestion

URL = "https://job-boards.greenhouse.io/fixture/jobs/42"


def question(label, kind, *, key=None, **kwargs):
    return PostingQuestion(
        question_key=key or label, label=label, kind=kind, required=False, **kwargs
    )


def grant(*questions, **overrides):
    return SimpleNamespace(
        **{
            "owner_id": "fixture-owner",
            "application_id": "fixture-review",
            "job_url": URL,
            "full_name": "Example Test Person",
            "email": "candidate@example.invalid",
            "phone": "555-0100",
            "resume_name": "private-name.txt",
            "resume_bytes": b"fixture resume only",
            "form": PostingForm(state="available", questions=list(questions)),
            **overrides,
        }
    )


@pytest.fixture(scope="module")
def chromium():
    with sync_playwright() as playwright, playwright.chromium.launch() as browser:
        yield browser


@pytest.fixture
def fixture_page(chromium):
    with chromium.new_context(service_workers="block") as context:
        page = context.new_page()
        page.set_default_timeout(1500)

        def load(html, url=URL):
            def serve(route):
                if route.request.url == url and route.request.resource_type == "document":
                    route.fulfill(content_type="text/html; charset=utf-8", body=html)
                else:
                    route.abort()

            context.route("**/*", serve)
            page.goto(url)
            return page

        yield load


@pytest.mark.browser
def test_fill_only_exact_native_fields_from_review_without_pressing_any_buttons(fixture_page):
    from src.applications.review_fill import fill_review_page

    page = fixture_page("""<form id="application-form">
        <label>First Name <span aria-hidden="true">*</span><input id="first" required></label>
        <input id="last" aria-label="Last Name"><label for="email">Email</label>
        <input id="email" type="email"><label>Phone<input id="phone" type="tel"></label>
        <label for="why">Why this role?</label><textarea id="why"></textarea>
        <label>Portfolio<input id="portfolio"></label>
        <label>Cover letter<input id="cover" type="file"></label>
        <label for="resume">Resume/CV</label><input id="resume" type="file">
        <label for="shift">Preferred shift?</label><select id="shift">
          <option value="">Choose</option><option value="local-1">Morning</option>
          <option value="local-2">Afternoon</option></select>
        <label for="days">Available days?</label><select id="days" multiple>
          <option value="a">Monday</option><option value="b">Friday</option></select>
        <label>I agree to the terms<input id="terms" type="checkbox"></label>
        <button type="button">Next</button><button>Apply</button></form>
        <script>window.clicks=window.submits=0; document.onclick=()=>window.clicks++;
        document.onsubmit=e=>{e.preventDefault(); window.submits++}</script>""")
    review = grant(
        question("First Name", "contact", field_name="first_name"),
        question("Last Name", "contact", field_name="last_name"),
        question("Email", "contact", field_name="email"),
        question("Phone", "contact", field_name="phone"),
        question("Why this role?", "textarea", answer="A prepared answer."),
        question("Portfolio", "text", answer="My prepared reference"),
        question("Resume/CV", "resume"),
        question("Preferred shift?", "select", answer="2", options=[
            {"value": "1", "label": "Morning"}, {"value": "2", "label": "Afternoon"}]),
        question("Available days?", "multiselect", answer=["1", "2"], options=[
            {"value": "1", "label": "Monday"}, {"value": "2", "label": "Friday"}]),
        question("I agree to the terms", "employer"),
    )

    outcome = fill_review_page(page, review, confirmed=True)

    assert (outcome.status, outcome.filled, outcome.skipped) == ("handoff", 9, 1)
    assert page.locator("#first").input_value() == "Example"
    assert page.locator("#last").input_value() == "Test Person"
    assert page.locator("#email").input_value() == review.email
    assert page.locator("#phone").input_value() == review.phone
    assert page.locator("#why").input_value() == "A prepared answer."
    assert page.locator("#portfolio").input_value() == "My prepared reference"
    assert page.locator("#resume").evaluate("e => e.files[0].text()") == "fixture resume only"
    assert page.locator("#cover").evaluate("e => e.files.length") == 0
    assert page.locator("#shift").input_value() == "local-2"
    assert page.locator("#days").evaluate("e => [...e.selectedOptions].map(o => o.value)") == ["a", "b"]
    assert not page.locator("#terms").is_checked()
    assert page.evaluate("[clicks, submits]") == [0, 0]
