"""WS-32 · Assist mode is a capability, not a convention.

The agent fills the form and stops. It cannot press submit because it does not
hold ``SUBMIT`` — which is the point: the safety property is enforced by the
capability matrix, not by the code remembering to stop.

The adapter's logic is exercised against the **fake page**
(``tests/fixtures/fake_page.py`` — the seam ``tests/test_application_adapter.py``
drives), so the walk, the identity fields and the refusals run without a
browser. One test drives a **real Chromium** against the local fake ATS
(``@pytest.mark.browser``): the plan's property is that a *human's* submit is
what produces the evidence, and that is worth proving on a real page.

The pilot harness (``scripts/pilot_assist.py``) is covered here too: a
non-allowlisted target is refused by the real guard with no browser launched,
the localhost rule is pinned in both directions, and the harness end to end
(prepare → fill → hand over → capture the human's page → verify) is driven
with a stub adapter so the non-browser suite still covers the protocol.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from src.applications.assist_adapter import (
    AWAITING_HUMAN_SUBMIT,
    FORM_ERROR,
    FORM_WAITING_STATUSES,
    NEEDS_HUMAN,
    AssistAdapter,
    split_candidate_name,
)
from src.applications.contracts import (
    ApplicationAdapter,
    ApplicationRequest,
    ApplicationResult,
    PreparedApplication,
    SubmissionEvidence,
)
from src.config.settings import get_settings
from src.security.allowlist import (
    DisallowedDomainError,
    assert_job_url_allowed,
    assert_navigation_allowed,
    is_domain_allowed,
)
from src.security.permissions import CapabilityLevel, PermissionRegistry
from src.security.registry_setup import build_registry, get_registry
from tests.fixtures.fake_page import FakeControl, FakeLocator, FakePage


@pytest.fixture(autouse=True)
def isolated_evidence_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Keep the captured evidence out of the developer's data directory."""
    target = tmp_path / "evidence"
    target.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(get_settings(), "evidence_dir", str(target))
    return target


def _request(**overrides) -> ApplicationRequest:
    payload = {
        "job_title": "Backend Engineer",
        "company_name": "Acme Labs",
        "job_url": "https://boards.example.org/acme/jobs/1",
        "candidate_name": "Ada Lovelace",
        "email": "ada@example.com",
        "phone": "+1 555 0101",
        "resume_path": "/tmp/resume.pdf",
    }
    payload.update(overrides)
    return ApplicationRequest(**payload)


def _prepared(**overrides) -> PreparedApplication:
    """A payload that answers the provider's documented contract.

    The assist adapter's own gate refuses an incomplete payload before it opens
    a page (the provider would have accepted it as a blank), so every test that
    wants to reach the fill starts from a complete one.
    """
    payload = {
        "prepared_fields": {
            "candidate_name": "Ada Lovelace",
            "first_name": "Ada",
            "last_name": "Lovelace",
            "email": "ada@example.com",
            "phone": "+1 555 0101",
        },
        "resume_path": "/tmp/resume.pdf",
    }
    payload.update(overrides)
    payload.setdefault("request", _request())
    return PreparedApplication(**payload)


# --------------------------------------------------------------------------
# The capability is the safety property
# --------------------------------------------------------------------------


def test_the_assist_adapter_holds_prepare_and_not_submit() -> None:
    """The safety property is the capability, not a comment."""
    capabilities = build_registry().capabilities(AssistAdapter.name)

    assert CapabilityLevel.PREPARE in capabilities
    assert CapabilityLevel.SUBMIT not in capabilities
    # And nothing else either: the pilot's whole grant is PREPARE.
    assert capabilities == frozenset({CapabilityLevel.PREPARE})


def test_it_is_not_selectable_by_an_ordinary_prepare_flow() -> None:
    """R1: the pilot constructs the adapter; the registry flow must not.

    ``AVAILABLE_ADAPTERS`` is the list the API route and the worker resolve an
    adapter from, and Task 4 pinned that every adapter in it asks for ``SUBMIT``
    in its ``submit``. An assist-shaped adapter in that list would let an
    ordinary prepare flow select an adapter that never submits.
    """
    from src.graph.executor import AVAILABLE_ADAPTERS

    assert AssistAdapter.name not in [adapter.name for adapter in AVAILABLE_ADAPTERS]


def test_its_submit_asks_for_prepare_before_it_acts(monkeypatch: pytest.MonkeyPatch) -> None:
    """The check is a *call*, and it is for PREPARE — what filling a form is."""
    calls: list[tuple[str, CapabilityLevel]] = []

    def spy(
        self: ApplicationAdapter,
        level: CapabilityLevel,
        registry: PermissionRegistry | None = None,
    ) -> None:
        calls.append((self.name, level))
        raise PermissionError(f"{level.value} capability not granted for adapter {self.name!r}")

    monkeypatch.setattr(ApplicationAdapter, "require_capability", spy)

    with pytest.raises(PermissionError):
        AssistAdapter().submit(_prepared())

    assert calls == [(AssistAdapter.name, CapabilityLevel.PREPARE)]


def test_its_verify_does_not_ask_for_a_capability_it_does_not_hold(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """R2: ``verify`` asks for what it exercises, not for VERIFY.

    The matrix gives this adapter PREPARE only, so a ``verify`` that asked for
    VERIFY could never run — and the human's own submission could never be
    verified, which is the one thing the pilot is for.
    """
    calls: list[CapabilityLevel] = []

    def spy(
        self: ApplicationAdapter,
        level: CapabilityLevel,
        registry: PermissionRegistry | None = None,
    ) -> None:
        calls.append(level)
        raise PermissionError("refused")

    monkeypatch.setattr(ApplicationAdapter, "require_capability", spy)

    with pytest.raises(PermissionError):
        AssistAdapter().verify(
            ApplicationResult(success=False, status="human_submitted", message="x")
        )

    assert calls == [CapabilityLevel.PREPARE]


def test_a_direct_call_with_the_process_registry_is_allowed_to_fill() -> None:
    """The positive direction: with the real matrix, PREPARE is granted.

    Without this, the refusal tests above would pass for an adapter that is
    refused everything — a safety property that also disables the feature.
    """
    assert get_registry().can_prepare(AssistAdapter.name) is True
    assert get_registry().can_submit(AssistAdapter.name) is False
    assert get_registry().can_verify(AssistAdapter.name) is False


# --------------------------------------------------------------------------
# The fill, and the stop
# --------------------------------------------------------------------------


def test_its_submit_fills_the_form_and_returns_awaiting_human(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter = AssistAdapter()
    page = FakePage()
    monkeypatch.setattr(adapter, "_open_page", lambda url: page)

    result = adapter.submit(_prepared())

    assert result.success is False
    assert result.status == "awaiting_human_submit"
    # It must say what it did, so the operator knows the form is waiting.
    assert "filled" in result.message.lower()
    # The form was actually filled, from the candidate's own data.
    assert page.filled["Full name"] == "Ada Lovelace"
    assert page.filled["Email address"] == "ada@example.com"
    assert page.filled["Phone number"] == "+1 555 0101"


def test_it_never_presses_the_submit_button(monkeypatch: pytest.MonkeyPatch) -> None:
    """The stop is not a convention: the button is never clicked."""
    adapter = AssistAdapter()
    page = FakePage()
    monkeypatch.setattr(adapter, "_open_page", lambda url: page)

    result = adapter.submit(_prepared())

    assert page.clicked == []
    assert result.metadata["job_url"] == "https://boards.example.org/acme/jobs/1"
    # The evidence of the stop point is captured, so the operator can see the
    # page the agent left them on.
    assert result.evidence is not None
    assert result.evidence.screenshot_path
    assert result.evidence.trace_path
    assert result.evidence.status == "awaiting_human_submit"


def test_the_split_name_answers_a_boards_first_and_last_name_questions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The WS-08 walker can answer them once the payload carries both parts.

    The field map has no "first name" entry; the WS-20 taxonomy does, and it
    reads ``first_name``/``last_name`` off the payload — so emitting them is
    what makes the walker able to fill the most-asked labels on a real board.
    """
    adapter = AssistAdapter()
    page = FakePage(
        controls=[
            FakeControl(label="First Name", kind="text", required=True),
            FakeControl(label="Last Name", kind="text", required=True),
            FakeControl(label="Email address", kind="email", required=True),
        ]
    )
    monkeypatch.setattr(adapter, "_open_page", lambda url: page)

    result = adapter.submit(_prepared())

    assert result.status == "awaiting_human_submit"
    assert page.filled["First Name"] == "Ada"
    assert page.filled["Last Name"] == "Lovelace"
    assert page.filled["Email address"] == "ada@example.com"


def test_the_browser_is_left_open_for_the_human(monkeypatch: pytest.MonkeyPatch) -> None:
    """A form filled and then closed is an expensive no-op — the human has to
    be able to press the button on the page the agent filled."""
    adapter = AssistAdapter()
    page = FakePage()
    monkeypatch.setattr(adapter, "_open_page", lambda url: page)

    adapter.submit(_prepared())

    assert adapter.browser_open is True
    assert page.context.closed is False
    # And it is the operator (or the harness) that closes it, not the agent.
    adapter.close()
    assert adapter.browser_open is False
    assert page.context.closed is True
    adapter.close()  # idempotent


def test_a_question_it_cannot_answer_stops_the_run_and_keeps_the_page_open(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The measurement this pilot exists for: where it stopped, and why."""
    adapter = AssistAdapter()
    page = FakePage(
        controls=[
            FakeControl(label="Full name", kind="text", required=True),
            FakeControl(label="Have you served on a submarine?", kind="text"),
        ]
    )
    monkeypatch.setattr(adapter, "_open_page", lambda url: page)

    result = adapter.submit(_prepared())

    assert result.success is False
    assert result.status == NEEDS_HUMAN
    assert result.metadata["questions"] == ["Have you served on a submarine?"]
    assert adapter.questions_unanswered == ["Have you served on a submarine?"]
    # Nothing was typed and nothing was submitted, but the browser is the
    # human's to finish on: they can answer it there.
    assert page.filled == {}
    assert page.clicked == []
    assert adapter.browser_open is True


def test_the_three_form_waiting_stops_are_the_ones_that_keep_the_browser_open() -> None:
    """The one list the adapter and the pilot share, pinned as the contract.

    The pilot used to read ``awaiting_human_submit`` alone and orphan the
    window on the other two — and the likeliest stop on a real board is
    ``needs_human``. The constants are the single source both sites read, so a
    future stop added to the adapter is a stop the harness hands over for
    without a second literal set to forget.
    """
    assert FORM_WAITING_STATUSES == {AWAITING_HUMAN_SUBMIT, NEEDS_HUMAN, FORM_ERROR}
    # The two that are deliberately not, so the set is not "everything":
    # their evidence is captured and the browser closed by the adapter itself.
    assert "blocked_human_review" not in FORM_WAITING_STATUSES
    assert "unsafe_navigation" not in FORM_WAITING_STATUSES


def test_an_optional_question_it_cannot_answer_is_recorded_not_guessed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An optional question it cannot ground is *named*, never answered.

    The pilot's record has to carry the questions the agent did not answer —
    that is the measurement the workstream exists for. "Portfolio" is in the
    field map (it asks for the candidate's website), the stored profile states
    no website, and the field is not required, so the run continues and the
    question is left to the human.
    """
    adapter = AssistAdapter()
    page = FakePage(
        controls=[
            FakeControl(label="Full name", kind="text", required=True),
            FakeControl(label="Portfolio", kind="url"),
        ]
    )
    monkeypatch.setattr(adapter, "_open_page", lambda url: page)

    result = adapter.submit(_prepared())

    assert result.status == "awaiting_human_submit"
    assert page.filled == {"Full name": "Ada Lovelace"}
    assert result.metadata["questions_left_alone"] == ["Portfolio"]


def test_an_unsupported_widget_is_reported_rather_than_filled() -> None:
    """A control whose kind the filler has no branch for is named, not typed.

    Every kind ``read_controls`` can produce today is fillable, so this is
    exercised on the reporting helper directly: the report the pilot prints
    must be able to say "I did not recognise this widget" on a board that
    publishes one the field map has never seen.
    """
    from src.applications.form import FormPlan, FormQuestion

    plan = FormPlan(
        questions=[
            FormQuestion(label="Full name", kind="text"),
            FormQuestion(label="Signature", kind="signature-pad"),
        ]
    )

    assert AssistAdapter.unsupported_widgets_in(plan) == ["Signature"]


def test_a_twizard_step_is_advanced_and_only_the_last_page_is_left_alone(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The WS-08 walk is preserved: only the *final* step stops.

    The override changes one thing — the page whose button submits is filled
    and not clicked. An intermediate page's *next* button is clicked exactly as
    the base class does, which is what keeps a multi-step form working.
    """
    adapter = AssistAdapter()
    page = _WizardPage()
    monkeypatch.setattr(adapter, "_open_page", lambda url: page)

    result = adapter.submit(_prepared())

    assert page.clicked == ["Continue"]  # the wizard advanced ...
    assert page.filled["Full name"] == "Ada Lovelace"  # ... and the last page was filled
    assert result.status == "awaiting_human_submit"
    # The submit button on the final page was never clicked.
    assert "Submit application" not in page.clicked


def test_a_page_whose_button_changes_between_lookups_is_never_submitted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The window the two-lookup delegation opened, closed.

    ``AssistAdapter._fill_and_submit`` used to look the page's button up once and,
    when it was not a submit button, hand the walk to the parent's implementation
    — which looks the button up **again** and clicks whatever it finds. A page
    whose button set changes between those two lookups therefore reached a
    ``click()`` on a submit button, which is the one thing this adapter must never
    do: ``SUBMIT_BUTTON`` matches ``submit|apply|send``, so a validation re-render
    or a wizard step that reveals an *Apply* button is not a contrived shape.

    This fake models exactly that: the first button lookup sees ``Continue``
    (a *next* button), and every lookup after the fill sees ``Apply now`` — a
    submit button. The adapter must stop before it, not click it.
    """
    adapter = AssistAdapter()
    page = _RerenderedButtonPage()
    monkeypatch.setattr(adapter, "_open_page", lambda url: page)

    result = adapter.submit(_prepared())

    # The assertion the window fails: no submit button was ever clicked.
    for label in page.clicked:
        assert not re.search(r"submit|apply|send", label, re.IGNORECASE), (
            f"the agent clicked the submit button {label!r}"
        )
    assert result.status == "awaiting_human_submit"
    assert "filled" in result.message.lower()
    # And the page was still filled: the stop is a hand-over, not a no-op.
    assert page.filled["Full name"] == "Ada Lovelace"
    assert adapter.browser_open is True


def test_an_incomplete_payload_is_refused_before_the_browser_opens(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Task 2's carry: the provider does not validate, so this adapter does.

    The pilot's target is a real board, where a required field left blank is
    accepted and the employer receives a blank. The gate fails closed: nothing
    is opened, nothing is typed.
    """
    adapter = AssistAdapter()
    opened: list[str] = []
    monkeypatch.setattr(adapter, "_open_page", lambda url: opened.append(url))

    prepared = _prepared(
        prepared_fields={
            "candidate_name": "Ada",
            "email": "ada@example.com",
            "phone": "+1 555 0101",
        }
    )
    result = adapter.submit(prepared)

    assert result.success is False
    assert result.status == "incomplete_payload"
    assert "first_name" in result.message and "last_name" in result.message
    assert opened == []
    assert adapter.browser_open is False


def test_a_run_that_could_not_open_the_page_says_so(monkeypatch: pytest.MonkeyPatch) -> None:
    """The allowlist is checked by the adapter too, not only by the pilot."""
    adapter = AssistAdapter()

    def refuse(url: str):
        raise DisallowedDomainError("Host 'boards.example.org' is not on the domain allowlist")

    monkeypatch.setattr(adapter, "_open_page", refuse)

    result = adapter.submit(_prepared())

    assert result.success is False
    assert result.status == "unsafe_navigation"
    assert "boards.example.org" in result.message
    assert adapter.browser_open is False


def test_a_challenge_is_not_handed_over_and_the_agent_never_clicks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """SEC-09 survives being helpful.

    A challenge ends the agent's run, and the window is **closed** rather than
    handed to the operator: a browser sitting on a CAPTCHA page is a system
    putting a human in front of a challenge it fetched for them, which is not
    what assist mode is for. The agent clicks nothing and types nothing on the
    way out.
    """
    adapter = AssistAdapter()
    page = FakePage(
        url="http://localhost:8901/captcha",
        title="Just a moment...",
        body="Please complete the CAPTCHA to continue.",
        buttons=["Verify"],
    )
    monkeypatch.setattr(adapter, "_open_page", lambda url: page)

    result = adapter.submit(_prepared())

    assert result.status == "blocked_human_review"
    assert result.metadata["challenge"]
    assert page.clicked == []
    assert page.filled == {}
    assert adapter.browser_open is False
    assert page.context.closed is True


def test_a_redirect_off_the_allowlist_is_not_handed_over(monkeypatch: pytest.MonkeyPatch) -> None:
    """A host the allowlist refused is a control failure, not a handover."""
    adapter = AssistAdapter()
    page = FakePage(url="https://evil.example.net/apply")
    monkeypatch.setattr(adapter, "_open_page", lambda url: page)

    result = adapter.submit(_prepared())

    assert result.status == "unsafe_navigation"
    assert adapter.browser_open is False
    assert page.context.closed is True


# --------------------------------------------------------------------------
# The identity fields (R4)
# --------------------------------------------------------------------------


class TestSplitCandidateName:
    """A two-part reading of one stored name string, or nothing at all."""

    def test_two_tokens_split_into_first_and_last(self) -> None:
        assert split_candidate_name("Ada Lovelace") == ("Ada", "Lovelace")

    def test_three_tokens_are_first_and_the_remainder(self) -> None:
        assert split_candidate_name("Ada Byron Lovelace") == ("Ada", "Byron Lovelace")

    def test_one_token_is_none_rather_than_a_guess(self) -> None:
        assert split_candidate_name("Ada") is None

    def test_an_empty_or_blank_name_is_none(self) -> None:
        assert split_candidate_name("") is None
        assert split_candidate_name("   ") is None
        assert split_candidate_name(None) is None

    def test_extra_inner_whitespace_collapses(self) -> None:
        assert split_candidate_name("  Ada \t  Lovelace  ") == ("Ada", "Lovelace")


def test_prepare_emits_the_documented_identity_fields() -> None:
    """The provider's names, built from the candidate's own data."""
    adapter = AssistAdapter()

    prepared = adapter.prepare(_request())

    assert prepared.prepared_fields["first_name"] == "Ada"
    assert prepared.prepared_fields["last_name"] == "Lovelace"
    assert prepared.prepared_fields["email"] == "ada@example.com"
    assert prepared.prepared_fields["phone"] == "+1 555 0101"
    # The walker's own field map still gets what it asks for.
    assert prepared.prepared_fields["candidate_name"] == "Ada Lovelace"
    assert prepared.resume_path == "/tmp/resume.pdf"


def test_prepare_does_not_raise_for_a_real_boards_url() -> None:
    """Unlike the fake-ATS adapter, this one is for boards it cannot recognise.

    The allowlist is the gate on *where* it may go (the pilot checks it before
    anything else); an adapter that only accepted ``localhost`` could not run
    the pilot at all.
    """
    adapter = AssistAdapter()

    assert adapter.supports_url("https://boards.example.org/acme/jobs/1") is True
    assert adapter.supports_url("https://jobs.lever.co/acme/1") is True
    assert adapter.supports_url("ftp://boards.example.org/acme/1") is False


def test_a_single_token_name_leaves_both_name_fields_absent() -> None:
    """Never guessed, never an initial — and the gate refuses the result."""
    from src.applications.greenhouse_contract import validate_against_contract

    adapter = AssistAdapter()

    prepared = adapter.prepare(_request(candidate_name="Ada"))

    assert "first_name" not in prepared.prepared_fields
    assert "last_name" not in prepared.prepared_fields
    report = validate_against_contract(prepared)
    assert not report.is_complete
    assert set(report.missing) == {"first_name", "last_name"}


def test_the_models_placeholder_defaults_never_reach_a_board() -> None:
    """``ApplicationRequest``'s own defaults are placeholders, not answers.

    ``candidate@example.com`` on a real board is the kind of silent wrong
    answer this workstream is against, so the model's documented default values
    read as *not supplied* and the stored profile's own values are used
    instead.
    """
    adapter = AssistAdapter()

    prepared = adapter.prepare(
        _request(
            candidate_name="Candidate",
            email="candidate@example.com",
            phone="+1 555 000 0000",
            profile_facts={
                "name": "Ada Lovelace",
                "email": "ada@lovelace.example",
                "phone": "+44 20 7946 0000",
            },
        )
    )

    assert prepared.prepared_fields["email"] == "ada@lovelace.example"
    assert prepared.prepared_fields["phone"] == "+44 20 7946 0000"
    assert prepared.prepared_fields["first_name"] == "Ada"
    assert prepared.prepared_fields["last_name"] == "Lovelace"


def test_a_resume_text_in_the_profile_facts_reaches_the_payload() -> None:
    """The contract accepts a file **or** text; the text travels verbatim."""
    adapter = AssistAdapter()

    prepared = adapter.prepare(
        _request(resume_path=None, profile_facts={"resume_text": "Ada Lovelace — Engineer"})
    )

    assert prepared.prepared_fields["resume_text"] == "Ada Lovelace — Engineer"
    assert prepared.resume_path is None


def test_an_explicit_request_value_beats_the_profile_fact() -> None:
    """The request is where the operator's own input arrives; it wins."""
    adapter = AssistAdapter()

    prepared = adapter.prepare(_request(email="ada@work.example", profile_facts={"email": "a@b.c"}))

    assert prepared.prepared_fields["email"] == "ada@work.example"


# --------------------------------------------------------------------------
# The pilot's guard (R5)
# --------------------------------------------------------------------------


def test_the_pilot_refuses_a_target_outside_the_allowlist(monkeypatch: pytest.MonkeyPatch) -> None:
    """The pilot must not silently reach a board the config did not intend."""
    from scripts import pilot_assist
    from src.applications import fake_ats_adapter

    def no_browser(*args, **kwargs):  # pragma: no cover - it must never run
        raise AssertionError("the pilot launched a browser for a refused target")

    monkeypatch.setattr(fake_ats_adapter, "sync_playwright", no_browser)

    with pytest.raises(DisallowedDomainError) as refusal:
        pilot_assist.run_pilot("https://boards.example.org/acme/jobs/1", profile_id="p1")

    message = str(refusal.value)
    assert "boards.example.org" in message
    assert "ALLOWED_DOMAINS" in message


def test_the_local_fake_ats_passes_the_guard_in_development_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """What the localhost check found, pinned in both directions.

    ``assert_navigation_allowed`` admits a loopback host only when the caller
    passes ``allow_localhost=True``, and the API-boundary wrapper
    (``assert_job_url_allowed``) grants that only when ``APP_ENV=development``.
    The local fake ATS therefore passes the pilot's guard in development —
    which is what makes the free rehearsal possible — and is refused outside
    it, like any other host. It is also never a *domain* match: an IP literal
    cannot be on ``ALLOWED_DOMAINS``, so the local exception is the only way a
    loopback URL is ever admitted.
    """
    settings = get_settings()
    local = "http://127.0.0.1:8901/basic"

    assert is_domain_allowed(local) is False  # an IP literal never matches a domain

    monkeypatch.setattr(settings, "app_env", "development")
    assert_job_url_allowed(local)  # the pilot's rehearsal passes
    assert_navigation_allowed(local, allow_localhost=True)
    with pytest.raises(DisallowedDomainError):
        assert_navigation_allowed(local)  # and only with the flag

    monkeypatch.setattr(settings, "app_env", "production")
    with pytest.raises(DisallowedDomainError):
        assert_job_url_allowed(local)  # a production deployment cannot submit locally


# --------------------------------------------------------------------------
# The pilot's facts: the posting's country is read, not lost
# --------------------------------------------------------------------------


@pytest.fixture()
def corpus_db():
    """A throwaway corpus the pilot's country lookup reads from.

    The pilot resolves the posting's location from the **stored listing** by
    its application URL (WS-25c), so the test needs the real ``jobs`` table.
    ``Base`` already carries every model (``tests/conftest.py`` imports them),
    and the in-memory engine keeps the test off any real database.
    """
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from src.db.base import Base

    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    yield sessionmaker(autocommit=False, autoflush=False, bind=engine)
    engine.dispose()


def _uk_only_profile():
    """The WS-25c candidate: authorized in the UK, and only the UK."""
    from src.resume.application_profile import ApplicationProfile
    from src.resume.profile import CandidateProfile, PersonalInformation

    return CandidateProfile(
        personal_information=PersonalInformation(name="Ada Lovelace"),
        application_profile=ApplicationProfile.model_validate(
            {
                "answers": {
                    "work_authorization": {
                        "legally_authorized": True,
                        "requires_sponsorship": False,
                        "authorized_countries": ["GB"],
                    }
                }
            }
        ),
    )


def test_the_pilot_reads_the_postings_country_before_it_answers(corpus_db) -> None:
    """The country lookup must reach the corpus — it used to die on an Engine.

    ``pilot_assist._facts_for`` resolves the posting's location by application
    URL and the country from it (WS-25c). The lookup takes a **sessionmaker**
    (``location_for_application_url`` opens its own session with it), and the
    pilot used to hand it ``session.get_bind()`` — an ``Engine``. ``Engine()``
    is not callable, the lookup's broad ``except`` swallowed the ``TypeError``,
    and the country came back ``None`` on every run: the country-qualified
    authorization fact was silently withheld from every application, and the
    question went to a human who should never have seen it.

    With ``Toronto, Canada`` stored for the target, a UK-only candidate must
    get the **country-qualified** answer — ``"no"`` for Canada is the
    profile's own statement, and its presence is the proof the country was
    read. When the lookup fails, ``job_country`` is ``None`` and a narrowed
    profile emits no fact at all, which is the defect this test pins.
    """
    from scripts import pilot_assist
    from src.db.jobs import JobDB

    url = "https://boards.greenhouse.io/acme/jobs/ca-1"
    with corpus_db() as session:
        session.add(
            JobDB(
                id=f"greenhouse:{url}",
                source="greenhouse",
                source_job_id=url,
                title="Backend Engineer",
                company="Acme",
                location="Toronto, Canada",
                application_url=url,
            )
        )
        session.commit()

    facts = pilot_assist._facts_for(_uk_only_profile(), url, corpus_db)

    assert facts.get("legally_authorized") == "no"


def test_a_posting_it_cannot_read_withholds_the_answer(corpus_db) -> None:
    """The safe direction, pinned: a posting it cannot find states no country.

    "No row" and "the read failed" are the same outcome by design — the
    authorization fact is withheld — so the fix above must not turn a missing
    listing into a fabricated "yes" for a narrowed profile.
    """
    from scripts import pilot_assist

    facts = pilot_assist._facts_for(
        _uk_only_profile(), "https://boards.greenhouse.io/acme/jobs/never-seen", corpus_db
    )

    assert "legally_authorized" not in facts


# --------------------------------------------------------------------------
# The harness, with a stub adapter (no browser)
# --------------------------------------------------------------------------


class _StubAssistAdapter(ApplicationAdapter):
    """A stand-in for the browser step, so the protocol is covered here.

    It carries the real adapter's ``name``, so the matrix grants it PREPARE and
    ``prepare_application`` accepts it: the harness code under test is the code
    a real run executes, minus the browser.

    ``status`` is what the stop reports, so the same stub covers the three
    form-waiting stops the adapter hands over for — ``awaiting_human_submit``
    (filled, ready to submit), ``needs_human`` (a question the agent could not
    ground) and ``form_error`` (the page's own validation complained) — and the
    stops it does not hand over for.
    """

    name = "assist-playwright"

    def __init__(self, *, complete: bool = True, status: str = AWAITING_HUMAN_SUBMIT) -> None:
        self.complete = complete
        self.status = status
        self.browser_open = False
        self.closed = False
        self.page = None
        #: How many times the human's page was captured, so a test can tell
        #: "the capture was attempted" from "the capture was skipped".
        self.capture_calls = 0

    def supports_url(self, url: str) -> bool:
        return True

    def prepare(self, request: ApplicationRequest) -> PreparedApplication:
        facts = dict(request.profile_facts)
        fields = {"candidate_name": request.candidate_name, "email": request.email}
        if self.complete:
            fields.update(
                {
                    "first_name": split_candidate_name(request.candidate_name)[0],
                    "last_name": split_candidate_name(request.candidate_name)[1],
                    "phone": request.phone,
                }
            )
        return PreparedApplication(
            request=request,
            prepared_fields={**fields, **facts},
            resume_path=request.resume_path,
        )

    def submit(self, prepared: PreparedApplication) -> ApplicationResult:
        self.browser_open = True
        return ApplicationResult(
            success=False,
            status=self.status,
            message=f"The form is waiting on a person ({self.status}).",
            metadata={
                "job_url": prepared.request.job_url,
                "questions": ["Have you served on a submarine?"]
                if self.status == NEEDS_HUMAN
                else [],
                "questions_left_alone": [],
            },
        )

    def capture_human_submission(self) -> ApplicationResult:
        self.capture_calls += 1
        return ApplicationResult(
            success=True,
            status="human_submitted",
            message="The human pressed submit; the page confirms it.",
            evidence=SubmissionEvidence(
                url="http://127.0.0.1:8901/basic",
                confirmation_text="Application Submitted. Thanks for applying.",
                screenshot_path="/tmp/human.png",
                status="human_submitted",
            ),
        )

    def verify(self, result: ApplicationResult) -> ApplicationResult:
        return ApplicationResult(
            success=True,
            status="verified",
            message="Application submission verified by confirmation page content.",
            evidence=result.evidence,
        )

    def close(self) -> None:
        self.closed = True
        self.browser_open = False


def test_the_pilot_waits_for_the_human_and_verifies_what_they_submitted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The harness: prepare, fill, hand over, capture the human's page, verify."""
    from scripts import pilot_assist

    monkeypatch.setattr(get_settings(), "app_env", "development")
    adapter = _StubAssistAdapter()
    waited: list[str] = []

    report = pilot_assist.run_pilot(
        "http://127.0.0.1:8901/basic",
        profile_id=None,
        job_title="Backend Engineer",
        company_name="Acme Labs",
        candidate_name="Ada Lovelace",
        email="ada@example.com",
        phone="+1 555 0101",
        resume_path="/tmp/resume.pdf",
        adapter=adapter,
        human=lambda handed_over: waited.append(handed_over),
    )

    assert waited == [adapter]
    assert report.result.status == "awaiting_human_submit"
    assert report.evidence is not None
    assert report.evidence.confirmation_text
    assert report.evidence.screenshot_path
    assert report.verified is not None
    assert report.verified.status == "verified"
    assert report.elapsed_seconds >= 0.0
    # The harness never closes a browser out from under the human.
    assert adapter.closed is False


def test_the_pilot_refuses_an_incomplete_payload_before_the_browser(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The contract gate is a refusal, not a warning (R4).

    The **real** adapter is used here: its ``prepare`` leaves both name fields
    absent for a one-token name, and the pilot must refuse rather than reach a
    board with a blank in a required field.
    """
    from scripts import pilot_assist

    monkeypatch.setattr(get_settings(), "app_env", "development")

    with pytest.raises(pilot_assist.PilotRefused) as refusal:
        pilot_assist.run_pilot(
            "http://127.0.0.1:8901/basic",
            profile_id=None,
            job_title="Backend Engineer",
            company_name="Acme Labs",
            candidate_name="Ada",  # one token: never split
            email="ada@example.com",
            phone="+1 555 0101",
            adapter=AssistAdapter(),
            human=lambda handed_over: None,
        )

    assert "first_name" in str(refusal.value)
    assert "last_name" in str(refusal.value)


def test_a_run_with_no_human_returns_the_stop_and_claims_nothing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No human step means no evidence and no verification — not a pass."""
    from scripts import pilot_assist

    monkeypatch.setattr(get_settings(), "app_env", "development")

    report = pilot_assist.run_pilot(
        "http://127.0.0.1:8901/basic",
        profile_id=None,
        job_title="Backend Engineer",
        company_name="Acme Labs",
        candidate_name="Ada Lovelace",
        email="ada@example.com",
        phone="+1 555 0101",
        adapter=_StubAssistAdapter(),
        human=None,
    )

    assert report.result.status == "awaiting_human_submit"
    assert report.evidence is None
    assert report.verified is None


def test_the_pilot_hands_over_on_needs_human_too(monkeypatch: pytest.MonkeyPatch) -> None:
    """The likeliest stop on a real board is a question the profile cannot ground.

    ``AssistAdapter`` deliberately leaves the browser open on three
    form-waiting statuses, and ``needs_human`` is one of them. The pilot used
    to hand over on ``awaiting_human_submit`` alone, so a ``needs_human`` run
    skipped the human step, the capture and the verify, never reached
    ``--close-when-done``, and exited with the page orphaned and a report
    reading ``evidence: none`` — the pilot's whole purpose (measuring where it
    stopped *and what the human did about it*) defeated on the stop most likely
    to happen.
    """
    from scripts import pilot_assist

    monkeypatch.setattr(get_settings(), "app_env", "development")
    adapter = _StubAssistAdapter(status=NEEDS_HUMAN)
    waited: list[object] = []

    report = pilot_assist.run_pilot(
        "http://127.0.0.1:8901/basic",
        profile_id=None,
        job_title="Backend Engineer",
        company_name="Acme Labs",
        candidate_name="Ada Lovelace",
        email="ada@example.com",
        phone="+1 555 0101",
        adapter=adapter,
        human=lambda handed_over: waited.append(handed_over),
        close_when_done=True,
    )

    assert waited == [adapter], "the human step was skipped on a form the agent left open"
    assert adapter.capture_calls == 1, "the capture was skipped"
    assert report.evidence is not None
    assert report.verified is not None
    assert report.verified.status == "verified"
    # The record says which status was handed over, so the operator can tell
    # "filled and ready to submit" from "stopped on a question you must answer".
    assert report.result.status == NEEDS_HUMAN
    assert report.as_dict()["status"] == NEEDS_HUMAN
    assert report.as_dict()["handover_status"] == NEEDS_HUMAN
    # And the close the operator asked for is reached.
    assert adapter.closed is True


def test_the_pilot_hands_over_on_form_error_too(monkeypatch: pytest.MonkeyPatch) -> None:
    """``form_error`` is the third form-waiting stop, and it is a hand-over.

    The page's own validation complained, so the human sees why and finishes
    it in the window the adapter left open. The pilot must take the same path:
    human step, capture, verify.
    """
    from scripts import pilot_assist

    monkeypatch.setattr(get_settings(), "app_env", "development")
    adapter = _StubAssistAdapter(status=FORM_ERROR)
    waited: list[object] = []

    report = pilot_assist.run_pilot(
        "http://127.0.0.1:8901/basic",
        profile_id=None,
        job_title="Backend Engineer",
        company_name="Acme Labs",
        candidate_name="Ada Lovelace",
        email="ada@example.com",
        phone="+1 555 0101",
        adapter=adapter,
        human=lambda handed_over: waited.append(handed_over),
        close_when_done=True,
    )

    assert waited == [adapter]
    assert adapter.capture_calls == 1
    assert report.evidence is not None
    assert report.verified is not None
    assert report.result.status == FORM_ERROR
    assert report.as_dict()["handover_status"] == FORM_ERROR
    assert adapter.closed is True


def test_a_stop_that_is_not_a_form_is_not_handed_over(monkeypatch: pytest.MonkeyPatch) -> None:
    """Pin the negative: the fix must not become "hand over on everything".

    A challenge (``blocked_human_review``: SEC-09) and an unsafe navigation are
    the stops where the *page* is the problem. The adapter captures their
    evidence and closes the browser itself, so there is no window to hand to a
    human and the pilot must not invent one.
    """
    from scripts import pilot_assist

    monkeypatch.setattr(get_settings(), "app_env", "development")

    for status in ("blocked_human_review", "unsafe_navigation"):
        adapter = _StubAssistAdapter(status=status)
        waited: list[object] = []

        # The closure takes ``waited`` as a default argument so it binds THIS
        # iteration's list: a bare closure would read the loop variable late and
        # every iteration's append would land in the last list built.
        def record_handover(handed_over: object, seen: list[object] = waited) -> None:
            seen.append(handed_over)

        report = pilot_assist.run_pilot(
            "http://127.0.0.1:8901/basic",
            profile_id=None,
            job_title="Backend Engineer",
            company_name="Acme Labs",
            candidate_name="Ada Lovelace",
            email="ada@example.com",
            phone="+1 555 0101",
            adapter=adapter,
            human=record_handover,
            close_when_done=True,
        )

        assert waited == [], f"{status} must not be handed to a human"
        assert adapter.capture_calls == 0
        assert report.evidence is None
        assert report.verified is None
        assert report.result.status == status
        assert report.as_dict()["handover_status"] is None


def test_the_handover_status_names_what_the_human_was_handed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The existing stop is unchanged, and its record names its status too."""
    from scripts import pilot_assist

    monkeypatch.setattr(get_settings(), "app_env", "development")
    adapter = _StubAssistAdapter()  # the default: awaiting_human_submit

    report = pilot_assist.run_pilot(
        "http://127.0.0.1:8901/basic",
        profile_id=None,
        job_title="Backend Engineer",
        company_name="Acme Labs",
        candidate_name="Ada Lovelace",
        email="ada@example.com",
        phone="+1 555 0101",
        adapter=adapter,
        human=lambda handed_over: None,
    )

    assert report.result.status == AWAITING_HUMAN_SUBMIT
    assert report.as_dict()["handover_status"] == AWAITING_HUMAN_SUBMIT


# --------------------------------------------------------------------------
# End to end: the human's submit is what produces the evidence (R7)
# --------------------------------------------------------------------------


@pytest.mark.browser
def test_a_human_submit_after_the_run_produces_verifiable_evidence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The plan's property, on a real browser against the local fake ATS.

    ``run_pilot`` drives the form to the last page and hands the browser over.
    The "human" here is a callable that presses the button on the page the
    agent filled — what an operator does in the visible window. The evidence
    then comes from **that** page, and ``verify`` reads it.
    """
    from scripts import pilot_assist
    from src.db.profiles import build_profile_row
    from src.db.session import SessionLocal
    from src.db.users import LEGACY_OWNER_ID
    from src.resume.profile import CandidateProfile, PersonalInformation
    from src.storage.paths import KIND_RESUMES, user_dir
    from tests.fixtures.fake_ats import serve_fake_ats_variants

    settings = get_settings()
    monkeypatch.setattr(settings, "app_env", "development")
    monkeypatch.setattr(settings, "data_dir", str(tmp_path / "data"))
    monkeypatch.setattr(settings, "evidence_dir", str(tmp_path / "data" / "evidence"))

    resume_dir = user_dir(LEGACY_OWNER_ID, KIND_RESUMES)
    resume_dir.mkdir(parents=True, exist_ok=True)
    resume = resume_dir / "resume.txt"
    resume.write_text("Ada Lovelace — Backend Engineer\n", encoding="utf-8")

    # The stored profile the pilot reads its identity facts from.
    with SessionLocal() as session:
        row = build_profile_row(
            CandidateProfile(
                personal_information=PersonalInformation(
                    name="Ada Lovelace", email="ada@example.com", phone="+1 555 0101"
                )
            ),
            file_path=str(resume),
            owner_id=LEGACY_OWNER_ID,
        )
        session.add(row)
        session.commit()
        profile_id = row.id

    with serve_fake_ats_variants() as base_url:
        import httpx

        adapter = AssistAdapter()
        handed_over: list[str] = []
        before: list[dict] = []

        def operator(assist: AssistAdapter) -> None:
            """What the human does in the window the agent left open.

            The first thing it does is ask the server what it has received: the
            agent's part of the run must have produced **no submission at all**.
            That assertion is the property under test — the click below is the
            only thing that can make the server answer with a confirmation.
            """
            handed_over.append(assist.page.url)
            before.extend(httpx.get(f"{base_url}/_submissions").json())
            assist.page.get_by_role("button", name="Submit application").click()
            assist.page.wait_for_load_state("domcontentloaded")

        report = pilot_assist.run_pilot(
            f"{base_url}/basic",
            profile_id=profile_id,
            job_title="Backend Engineer",
            company_name="Acme Labs",
            resume_path=str(resume),
            adapter=adapter,
            human=operator,
        )

        assert before == [], "the agent submitted the form itself"
        assert handed_over == [f"{base_url}/basic"]
        # The agent stopped and told the human what it had done.
        assert report.result.status == "awaiting_human_submit"
        assert "filled" in report.result.message.lower()
        assert adapter.browser_open is True

        # The evidence comes from the page the human submitted on.
        assert report.evidence is not None
        assert report.evidence.confirmation_text
        assert "Thanks for applying" in report.evidence.confirmation_text
        assert report.evidence.screenshot_path
        assert report.evidence.trace_path

        # And it is what `verify` reads — an assist run with no evidence is not
        # verifiable and must not be reported as submitted.
        verified = adapter.verify(
            ApplicationResult(
                success=False,
                status="human_submitted",
                message="the human submitted the form",
                evidence=report.evidence,
            )
        )
        assert verified.status in {"verified", "verification_failed"}
        assert verified.status == "verified"
        assert verified.success is True

        # The page the human submitted carried the agent's own answers: the
        # form it filled is the form that was sent.
        submissions = httpx.get(f"{base_url}/_submissions").json()
        assert submissions
        assert submissions[0]["candidate_name"] == "Ada Lovelace"
        assert submissions[0]["email"] == "ada@example.com"

        # The harness never closes a browser out from under the human.
        assert adapter.browser_open is True
        adapter.close()
        assert adapter.browser_open is False


class _RerenderedButtonPage(FakePage):
    """A page whose button set changes once its form has been filled.

    The real shape this models: a form that renders a *next* button until the
    fields are answered — or that re-renders after a validation error — and then
    reveals the button that submits. The adapter looks the button up more than
    once on such a page, and every lookup after the fill sees ``Apply now``.

    ``_find_button`` narrows the locator with ``.first``, so the locator
    subclass here keeps its identity through ``first``/``nth`` the same way
    :class:`_AdvancingLocator` does, and reports the current button set.
    """

    def __init__(self) -> None:
        super().__init__(
            url="http://localhost:8901/reveal",
            body="Answer the questions to continue",
            controls=[FakeControl(label="Full name", kind="text", required=True)],
            buttons=["Continue"],
        )

    def _revealed(self) -> bool:
        """Whether the form has been filled and the submit button shown."""
        return bool(self.filled)

    def get_by_role(self, role: str, name=None) -> FakeLocator:
        if role != "button":
            return super().get_by_role(role, name)
        pattern = name if isinstance(name, re.Pattern) else None
        buttons = ["Apply now"] if self._revealed() else ["Continue"]
        names = [button for button in buttons if pattern is None or pattern.search(button)]
        return _RerenderedLocator(self, [{"name": button} for button in names], pattern)


class _RerenderedLocator(FakeLocator):
    """A button locator that keeps its page's button set live across lookups."""

    def __init__(self, page: FakePage, targets: list[dict], pattern: re.Pattern | None) -> None:
        super().__init__(page, targets)
        self.pattern = pattern

    def nth(self, index: int) -> FakeLocator:
        if index >= len(self.targets):
            return _RerenderedLocator(self.page, [], self.pattern)
        return _RerenderedLocator(self.page, [self.targets[index]], self.pattern)

    @property
    def first(self) -> FakeLocator:
        return self.nth(0)


class _WizardPage(FakePage):
    """A two-step fake: ``Continue`` advances to the page that submits.

    The shared ``FakePage`` deliberately ignores the accessible-name pattern in
    a button lookup — the walker's own tests only need "a button was found".
    A wizard step needs the distinction the real locator makes (a *next* button
    advances the walk, a *submit* button ends it), so this subclass applies the
    pattern and turns the page into its final step when ``Continue`` is clicked.
    """

    def __init__(self) -> None:
        super().__init__(
            url="http://localhost:8901/step1",
            body="Step 1 of 3",
            controls=[FakeControl(label="Full name", kind="text")],
            buttons=["Continue"],
        )
        self.on_submit_page = False

    def advance(self) -> None:
        """The page the next button lookup sees: the final step."""
        self.on_submit_page = True
        self.url = "http://localhost:8901/step3"
        self.body = "Review your application"
        self.buttons = ["Submit application"]

    def get_by_role(self, role: str, name=None) -> FakeLocator:
        if role != "button":
            return super().get_by_role(role, name)
        pattern = name if isinstance(name, re.Pattern) else None
        names = [button for button in self.buttons if pattern is None or pattern.search(button)]
        return _AdvancingLocator(self, [{"name": button} for button in names], pattern)


class _AdvancingLocator(FakeLocator):
    """A button locator whose ``Continue`` click advances the fake page.

    ``first`` and ``nth`` are overridden to keep the subclass, because the
    adapter's ``_find_button`` narrows the locator with ``.first`` — a plain
    ``FakeLocator`` returned there would lose the advancing behaviour and the
    walk would never leave the first page.
    """

    def __init__(self, page: FakePage, targets: list[dict], pattern: re.Pattern | None) -> None:
        super().__init__(page, targets)
        self.pattern = pattern

    def nth(self, index: int) -> FakeLocator:
        if index >= len(self.targets):
            return _AdvancingLocator(self.page, [], self.pattern)
        return _AdvancingLocator(self.page, [self.targets[index]], self.pattern)

    @property
    def first(self) -> FakeLocator:
        return self.nth(0)

    def click(self) -> None:
        super().click()
        names = " ".join(target.get("name", "") for target in self.targets)
        is_next = re.search(r"next|continue|proceed", names, re.IGNORECASE) is not None
        if is_next and not self.page.on_submit_page:
            self.page.advance()
