"""Assist mode: the agent fills the form and hands the browser to a human.

The pilot's whole design is one sentence: **the agent cannot press submit,
because it does not hold ``SUBMIT``.** That is enforced by the capability
matrix (``src/security/registry_setup.py`` grants ``assist-playwright``
``PREPARE`` and nothing else) rather than by this module remembering to stop,
and this module's ``submit`` asks the base class's ``require_capability`` for
``PREPARE`` — the capability it actually exercises — as its first statement.

Why the harness exists decides every choice here. The verified findings say the
safest form of a first real submission is **not** unattended: the human is
actively initiating the final submission. The purpose is **measurement, not
automation** — run one real posting and find out where it stops: which
questions it could not answer, which widgets it did not recognise, whether the
page's own validation complained. That measurement decides which board shape to
support first instead of guessing.

**The walk is the WS-08 walker, reused rather than forked.** This module is a
subclass of :class:`~src.applications.fake_ats_adapter.FakeAtsPlaywrightAdapter`
and overrides exactly these things:

``name`` / ``supports_url``
    The adapter's identity, and a URL gate that accepts any ``http``/``https``
    target. It is deliberately **not** a hostname pattern like the fake ATS's:
    the gate on *where* an assist run may go is the domain allowlist (checked
    by the pilot before anything else, and again by the inherited
    ``_drive_form`` on every page of the walk), not a per-adapter list of hosts.
``prepare``
    The provider's documented identity fields. ``ApplicationRequest`` carries a
    single ``candidate_name``, which cannot answer a board's "First Name"/"Last
    Name" questions, so the parts are emitted alongside the full name the
    walker's own field map asks for.
``_fill_and_submit``
    **The whole of the stop**, and the only place in this class that clicks —
    for a button it has just read as *not* a submit button. Everything else in
    the walk is inherited: the per-page allowlist check, the challenge stop,
    ``build_form_plan``, the unanswered-question stop, ``_fill_control``/
    ``_upload_resume``, ``_find_button``, ``_collect_errors`` and the
    traversal ceiling. The override fills the page, looks the page's button up,
    and stops there: a button that **submits** — or no button at all — returns
    the new outcome kind ``awaiting_human_submit`` **without a click**, while a
    button that only advances a wizard is clicked and the page's own validation
    read, retrying once on a rejected page exactly as the parent does. It does
    **not** delegate back to the parent's click path: that path looks the button
    up a second time and clicks whatever it finds, so a page whose button set
    changes between the fill and the lookup (a validation re-render, a step that
    reveals an ``Apply`` button) reached a submit click. The loop re-reads the
    button after every click instead, which is what makes the claim below true
    of the code rather than of the intent.
``submit`` / ``verify`` / ``capture_human_submission`` / ``close``
    ``submit`` keeps the parent's skeleton and its four outcome dispatches,
    with two differences: the ``finally`` that closes the context and shuts the
    browser down is **absent** (a form filled and then closed is an expensive
    no-op — the human has to be able to press the button on the page the agent
    filled), and the teardown is :meth:`close`, which only the operator calls.
    ``verify`` asks for ``PREPARE`` rather than ``VERIFY``, because the matrix
    grants this adapter ``PREPARE`` only; a verify that demanded ``VERIFY``
    could never run, and the human's own submission is the one thing the pilot
    exists to verify.

The dispatches on the other outcome kinds are delegated to the parent's
``_*_result`` methods unchanged, so a challenge, an unsafe redirect, an
unanswered question and a rejected form read exactly as they do on the fake-ATS
path. The human hand-over is for a **form** — filled, or partly filled, with a
question the agent could not answer — not for a page that is itself the problem:
a **challenge** and an **unsafe navigation** capture their evidence and then
close the browser, because a window sitting on a CAPTCHA is not a hand-over, and
**the agent never solves a challenge** (SEC-09): a challenge ends the agent's
part of the run.

**The evidence chain.** ``submit`` captures the stop point (a screenshot and
the trace so far) but deliberately does **not** stop the Playwright trace: the
trace stays live across the handover, so the human's own submit is inside the
archive written by :meth:`capture_human_submission` or :meth:`close`. The
capture is what makes the plan's property true — *the evidence comes from the
page the human submitted on, and it is what ``verify`` reads*. An assist run
with no evidence is not verifiable and must never be reported as submitted.
Nothing here clicks: the human's click is the human's.

**A resume file is a measurement, not a claim.** The contract accepts a résumé
as a *file* (``resume``) or as *text* (``resume_text``), and this adapter keeps
whatever the caller supplies: ``resume_path`` travels through when given, and a
résumé body in the profile facts is emitted verbatim. Uploading a **file** to a
real board's file input is a capability WS-32 · Task 1's PDF support enables
for the *local* flow — the local fake ATS accepts the upload and the tests
drive it — while whether a real board's file widget accepts what we send it is
one of the things this pilot exists to measure. Nothing here claims it already
works.

**The name split is the one transformation, and it refuses to guess.**
``PersonalInformation.name`` is a single string; the boards ask for two parts. A
two-part split on whitespace (first token, remainder) is the reading a human
makes of "Ada Lovelace", and it is used **only** when the stored name has at
least two tokens (:func:`split_candidate_name`). A single-token or empty name
leaves *both* fields absent — never a guessed surname, never a surname initial
invented from a first name — and the contract gate in
:mod:`src.applications.greenhouse_contract` then refuses the payload, which is
the correct fail-closed outcome: a human supplies the missing part.
"""

from __future__ import annotations

import logging
import uuid
from pathlib import Path

from src.applications.contracts import (
    ApplicationRequest,
    ApplicationResult,
    PreparedApplication,
    SubmissionEvidence,
)
from src.applications.fake_ats_adapter import (
    MAX_SUBMIT_ATTEMPTS,
    FakeAtsPlaywrightAdapter,
    NavigationTrace,
    _StepOutcome,
)
from src.applications.form import FormPlan, build_form_plan, read_controls
from src.applications.greenhouse_contract import validate_against_contract
from src.config.settings import ensure_dir, get_settings
from src.security.allowlist import DisallowedDomainError, has_allowed_scheme
from src.security.permissions import CapabilityLevel

logger = logging.getLogger(__name__)

#: The status of a run that filled the form and stopped.
AWAITING_HUMAN_SUBMIT = "awaiting_human_submit"

#: The status of the payload gate: a documented field the payload does not
#: answer. The provider accepts such a payload as blank, so this adapter
#: refuses it before a page is opened.
INCOMPLETE_PAYLOAD = "incomplete_payload"

#: The control kinds the walker can fill: the typed controls, the three choice
#: widgets, and the file input (uploaded rather than typed). Anything else is
#: reported to the operator as a widget the agent did not recognise — the
#: measurement this pilot exists to take — and is left alone.
SUPPORTED_KINDS: frozenset[str] = frozenset(
    {
        "text",
        "textarea",
        "email",
        "tel",
        "number",
        "url",
        "password",
        "search",
        "date",
        "select",
        "radio",
        "checkbox",
        "file",
    }
)

#: The values :class:`~src.applications.contracts.ApplicationRequest` carries as
#: their own **placeholders**. They are the model's documented defaults, not an
#: operator's input: a request that still holds them was not given a value, and
#: putting ``candidate@example.com`` on a real board is exactly the kind of
#: silent wrong answer this workstream exists to prevent. They read as "not
#: supplied", so the stored profile's own value is used instead — and when
#: neither exists, the contract gate reports the field missing.
REQUEST_PLACEHOLDERS: dict[str, str] = {
    "candidate_name": "Candidate",
    "email": "candidate@example.com",
    "phone": "+1 555 000 0000",
}

#: The fact keys a stored profile's facts carry each identity value in.
_NAME_FACTS: tuple[str, ...] = ("name", "candidate_name")
_FIRST_NAME_FACTS: tuple[str, ...] = ("first_name",)
_LAST_NAME_FACTS: tuple[str, ...] = ("last_name",)
_EMAIL_FACTS: tuple[str, ...] = ("email",)
_PHONE_FACTS: tuple[str, ...] = ("phone",)
_RESUME_TEXT_FACTS: tuple[str, ...] = ("resume_text",)


def split_candidate_name(name: str | None) -> tuple[str, str] | None:
    """Split a stored full name into ``(first_name, last_name)``, or ``None``.

    The rule is the reading a human makes of "Ada Lovelace": the first
    whitespace-separated token is the given name, and the remainder — every
    remaining token, joined by single spaces — is the family name. Extra inner
    whitespace collapses, so ``"  Ada \\t Lovelace  "`` yields the same pair as
    ``"Ada Lovelace"``, and a three-token name is the first token plus the two
    that follow it.

    A name with **fewer than two tokens is not split at all**: ``None``. There
    is no honest way to read a family name out of ``"Ada"``, and an invented
    one (a duplicated token, a surname initial) would be fabricated candidate
    data submitted to an employer. A caller is expected to treat ``None`` as
    "no split available": both ``first_name`` and ``last_name`` stay absent from
    the payload, and the provider's contract gate refuses it — the correct
    fail-closed outcome, with a human supplying the missing part.

    Args:
        name: The stored full name, as the profile states it.

    Returns:
        ``(first_name, last_name)`` when the name has at least two tokens, and
        ``None`` for a single-token, empty, blank or ``None`` name.
    """
    if not name:
        return None
    tokens = str(name).split()
    if len(tokens) < 2:
        return None
    return tokens[0], " ".join(tokens[1:])


class AssistAdapter(FakeAtsPlaywrightAdapter):
    """Fills an application form and stops before the submit, browser open.

    Constructed directly by the pilot (``scripts/pilot_assist.py``) and
    deliberately **not** in ``src.graph.executor.AVAILABLE_ADAPTERS``: it holds
    ``PREPARE`` only, so an ordinary prepare flow must not be able to select it
    (the registry would refuse its submission anyway, and a selectable
    submit-less adapter in the general list would be a product change the plan
    did not ask for).
    """

    name = "assist-playwright"

    def __init__(self) -> None:
        super().__init__()
        #: True between a run that stopped and :meth:`close`. The pilot reads
        #: it to tell the operator where the browser is.
        self.browser_open = False
        #: The page the agent left for the human (``None`` between runs).
        self.page = None
        #: The questions the walker could not answer on the pages it filled.
        self.questions_left_alone: list[str] = []
        #: The questions that stopped the run (``status="needs_human"``).
        self.questions_unanswered: list[str] = []
        #: The controls whose kind the walker has no branch for.
        self.unrecognised_widgets: list[str] = []
        self._workflow_id = ""
        self._evidence_dir: Path | None = None
        self._trace: NavigationTrace | None = None
        self._tracing_open = False

    # ------------------------------------------------------------------
    # The URL gate
    # ------------------------------------------------------------------

    def supports_url(self, url: str) -> bool:
        """True for any ``http``/``https`` URL.

        Unlike the fake-ATS adapter's hostname check, this is not the security
        boundary: the target *host* is decided by the domain allowlist, which
        the pilot checks before it does anything
        (:func:`src.security.allowlist.assert_job_url_allowed`) and which the
        inherited walk checks again before every navigation. This method only
        refuses a URL that is not a page at all (``javascript:``, ``data:``, a
        bare relative path).
        """
        if not url or not url.strip():
            return False
        return has_allowed_scheme(url)

    # ------------------------------------------------------------------
    # The payload
    # ------------------------------------------------------------------

    def prepare(self, request: ApplicationRequest) -> PreparedApplication:
        """Build the payload the walker answers from, in the documented names.

        The identity values come from the candidate's own data, in this order of
        preference:

        1. a value the **request** carries — it is where the operator's own
           input arrives — unless it is still the model's placeholder default
           (:data:`REQUEST_PLACEHOLDERS`), which reads as "not supplied";
        2. the stored profile's fact (``ApplicationRequest.profile_facts``,
           derived from the uploaded document by
           :func:`src.applications.form.facts_from_profile`).

        Nothing is invented. ``first_name``/``last_name`` come only from
        :func:`split_candidate_name` (or, when a profile states them directly,
        from its own facts), and are omitted entirely when the name has fewer
        than two tokens.

        Args:
            request: The application request.

        Returns:
            The prepared payload: the walker's own fields (``candidate_name``,
            ``email``, ``phone``) plus the provider's documented ones
            (``first_name``, ``last_name``, and ``resume_text`` when the facts
            carry a résumé body), so the WS-08 form walk and the provider's own
            field names are both answered from one payload.
        """
        facts = dict(request.profile_facts)

        name = self._supplied(request.candidate_name, "candidate_name") or self._first_fact(
            facts, _NAME_FACTS
        )

        fields: dict[str, str] = {}
        if name:
            fields["candidate_name"] = name

        split = split_candidate_name(name)
        if split is not None:
            # Facts that state the parts win over a split of the full name: a
            # profile carrying them was read more precisely than a whitespace
            # split reads it.
            fields["first_name"] = self._first_fact(facts, _FIRST_NAME_FACTS) or split[0]
            fields["last_name"] = self._first_fact(facts, _LAST_NAME_FACTS) or split[1]

        email = self._supplied(request.email, "email") or self._first_fact(facts, _EMAIL_FACTS)
        if email:
            fields["email"] = email

        phone = self._supplied(request.phone, "phone") or self._first_fact(facts, _PHONE_FACTS)
        if phone:
            fields["phone"] = phone

        # The contract accepts a résumé as a file **or** as text. The caller's
        # file is kept as it is (``resume_path``, where every adapter in this
        # repo puts the upload); a body the facts carry travels verbatim, and
        # nothing is ever derived from either.
        resume_text = self._first_fact(facts, _RESUME_TEXT_FACTS)
        if resume_text:
            fields["resume_text"] = resume_text

        for key, value in request.custom_fields.items():
            fields[key] = value

        return PreparedApplication(
            request=request,
            prepared_fields=fields,
            resume_path=request.resume_path,
            cover_letter=request.cover_letter,
            requires_manual_review=False,
            # WS-08: the grounded facts travel with the payload so the browser
            # step can answer a question from the candidate's own document.
            profile_facts=facts,
        )

    @staticmethod
    def _supplied(value: str | None, key: str) -> str:
        """A request value that is a real answer rather than a placeholder."""
        text = (value or "").strip()
        if not text or text == REQUEST_PLACEHOLDERS.get(key):
            return ""
        return text

    @staticmethod
    def _first_fact(facts: dict[str, str], keys: tuple[str, ...]) -> str:
        """The first non-blank fact among *keys*."""
        for key in keys:
            value = str(facts.get(key) or "").strip()
            if value:
                return value
        return ""

    # ------------------------------------------------------------------
    # The submission that stops
    # ------------------------------------------------------------------

    def submit(self, prepared: PreparedApplication) -> ApplicationResult:
        """Fill the form, stop before the submit, and leave the browser open.

        WS-32: the first statement is the capability this run actually
        exercises. Filling a form is ``PREPARE``; this adapter does not hold
        ``SUBMIT``, and the registry would refuse the call before it arrived
        anyway — this is the second layer, and it is the one a caller that
        bypasses the registry (the pilot) still gets.

        The payload is then checked against the provider's documented contract
        (:data:`src.applications.greenhouse_contract.CONTRACT_ADAPTERS` names
        ``assist-playwright``): the provider does **not** reject an application
        missing required fields, so a blank it would accept as complete is
        refused here, before a page is opened.

        Returns:
            A result whose ``status`` is ``awaiting_human_submit`` on the happy
            path — ``success=False`` on purpose: nothing was submitted. A
            challenge, an unsafe redirect, an unanswered question and a
            rejected form keep the statuses the fake-ATS adapter reports.

            Which stops are **handed over** is deliberate. The browser is left
            open on the three where a *form* is waiting for a person:
            ``awaiting_human_submit``, ``needs_human`` (the question the agent
            could not answer is on the page for the human to answer there) and
            ``form_error`` (the page's own validation complained; the human sees
            why and finishes it). It is **closed** on the two where the *page*
            is the problem — a challenge (``blocked_human_review``: SEC-09, the
            agent never cooperates with one, and a window sitting on a CAPTCHA
            is not a hand-over) and an unsafe navigation (``unsafe_navigation``:
            the host is not the one the operator allowlisted). Both capture
            their evidence first. Only an unexpected failure closes as well,
            because a broken run has no coherent page to hand over.
        """
        self.require_capability(CapabilityLevel.PREPARE)

        report = validate_against_contract(prepared)
        if not report.is_complete:
            logger.warning(
                "[assist] The payload does not answer the provider's contract: %s",
                ", ".join(report.missing),
            )
            return ApplicationResult(
                success=False,
                status=INCOMPLETE_PAYLOAD,
                message=(
                    "The prepared payload does not answer the fields the provider's "
                    f"application contract requires ({', '.join(report.missing)}); "
                    "the provider would accept it as a blank, so no page was opened."
                ),
                metadata={
                    "job_url": prepared.request.job_url,
                    "missing_fields": list(report.missing),
                },
            )

        workflow_id = prepared.workflow_id or uuid.uuid4().hex[:8]
        self._workflow_id = workflow_id
        self.questions_left_alone = []
        self.questions_unanswered = []
        self.unrecognised_widgets = []
        evidence_dir = self._evidence_directory(prepared)
        self._evidence_dir = evidence_dir
        trace = NavigationTrace()
        self._trace = trace
        self._tracing_open = False

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

        self.page = page
        # R6: the browser is left open. It is the whole point of assist mode —
        # the human has to be able to press the button on the page the agent
        # filled — so the teardown the fake-ATS adapter runs in its ``finally``
        # is not run here; :meth:`close` is the operator's call instead.
        #
        # The two stops where it does **not** stay open are the two where the
        # *page* is the problem rather than the form: a challenge (SEC-09 — the
        # agent never clicks, types into or attempts one, and a window sitting
        # on a CAPTCHA is not a handover) and a host the allowlist refused. Both
        # are captured first, then closed.
        self.browser_open = True
        context = page.context
        self._start_tracing(context)
        self._tracing_open = True

        try:
            outcome = self._drive_form(page, prepared, trace, evidence_dir, workflow_id)

            if outcome.kind == "blocked":
                result = self._blocked_result(
                    page, outcome, trace, context, evidence_dir, workflow_id, prepared
                )
                self.close()
                return result
            if outcome.kind == "unsafe_navigation":
                result = self._unsafe_navigation_result(
                    page, outcome, trace, context, evidence_dir, workflow_id, prepared
                )
                self.close()
                return result
            if outcome.kind == "needs_human":
                # The measurement the pilot exists for: the questions the
                # candidate's evidence does not cover, as the walker found them.
                # The page is the allowlisted target the operator chose and a
                # person is sitting in front of it, so it is handed over — they
                # answer there, and the answer is theirs, not the agent's.
                self.questions_unanswered = list(outcome.questions)
                return self._needs_human_result(
                    page, outcome, trace, context, evidence_dir, workflow_id, prepared
                )
            if outcome.kind == "form_error":
                return self._form_error_result(
                    page, outcome, trace, context, evidence_dir, workflow_id, prepared
                )
            if outcome.kind == AWAITING_HUMAN_SUBMIT:
                return self._awaiting_human_result(
                    page, trace, context, evidence_dir, workflow_id, prepared
                )

            # Unreachable: ``_fill_and_submit`` never reports "submitted" here,
            # because the submit button is never clicked. Fail closed rather
            # than treat an unknown outcome as a stop the human can finish.
            return ApplicationResult(
                success=False,
                status="submission_failed",
                message=f"The assist run produced an unexpected outcome: {outcome.kind!r}",
                metadata={"job_url": prepared.request.job_url, "outcome": outcome.kind},
            )
        except Exception as exc:  # an unexpected failure is a result, not a crash
            logger.exception("[%s] The assist run failed", workflow_id)
            # The one path that closes what it opened: an unexpected failure
            # has no coherent page for a human to finish on.
            self.close()
            return ApplicationResult(
                success=False,
                status="submission_failed",
                message=f"The assist run could not be completed: {exc}",
                metadata={"job_url": prepared.request.job_url, "error": str(exc)},
            )

    # ------------------------------------------------------------------
    # The stop
    # ------------------------------------------------------------------

    def _fill_and_submit(
        self,
        page,
        plan: FormPlan,
        facts,
        prepared: PreparedApplication,
        trace: NavigationTrace,
    ) -> _StepOutcome:
        """Fill the page and advance it, but **never** click a submit button.

        This is the entire behavioural difference from the WS-08 walker, and it
        is a loop rather than a delegation on purpose. The earlier shape looked
        the page's button up once and handed a non-submit page to the parent's
        implementation — which looks the button up **again** and clicks what it
        finds. A page whose button set changes between the two lookups (a
        validation re-render, a step that reveals an ``Apply``/``Submit``/
        ``Send`` button once the fields are answered) therefore reached
        ``click()`` on a submit button. That is the one thing this adapter must
        never do, so the loop below is the only code path the assist walk has,
        and its click is guarded by the same ``is_submit`` flag it re-reads
        after every click:

        * fill the page, then look the button up — the same two patterns
          (:data:`SUBMIT_BUTTON` / :data:`NEXT_BUTTON`), the same semantic
          locator, no CSS;
        * **a submit button, or no button at all** → the walk stops:
          :data:`AWAITING_HUMAN_SUBMIT` is returned without a ``click``. The
          human presses the page's own button, and the page's own validation is
          what they find out about — which is exactly what the pilot measures;
        * **a next button** → click, wait for the page that led to, collect the
          page's own validation errors, and keep the parent's one-remediation
          retry (a rejected page is re-planned and filled once more). The
          re-look-up happens at the top of the next iteration, so a page that
          reveals a submit button after the click stops there.

        The parent's ``submitted`` outcome is unreachable here — nothing in this
        method can produce it — and the traversal ceiling is the parent's
        :data:`~src.applications.fake_ats_adapter.MAX_PAGES`.

        The optional questions it could not ground and the widgets it does not
        support, on the pages it filled, are accumulated on the adapter: they
        are the pilot's finding and the operator has to read them.
        """
        current_plan = plan

        for attempt in range(MAX_SUBMIT_ATTEMPTS):
            self._fill_plan(page, current_plan, prepared, trace)
            self._record_what_was_left_alone(current_plan)

            button, is_submit = self._find_button(page)
            if button is None or is_submit:
                # The whole of the stop. ``is_submit`` is read at the moment of
                # the decision, so a page that changed between the fill and the
                # lookup stops here rather than being handed to a click path.
                trace.record("filled_form_stopped_before_submit", page.url)
                logger.info(
                    "[%s] The form is filled and the submit button (%s) was not pressed; the "
                    "browser is left open for the human.",
                    self._workflow_id,
                    "present" if is_submit else "absent",
                )
                return _StepOutcome(kind=AWAITING_HUMAN_SUBMIT)

            # A non-submit button only: this is the sole ``click`` in the assist
            # walk, and ``is_submit`` is False on the path that reaches it.
            trace.record("click_next", page.url)
            button.click()
            self._wait_for_page(page)

            errors = self._collect_errors(page)
            if not errors:
                logger.info("[%s] Advanced to the next page of the form", self._workflow_id)
                return _StepOutcome(kind="next")

            if attempt + 1 < MAX_SUBMIT_ATTEMPTS:
                # The parent's one-remediation retry: the server rejected the
                # page, so the prepared data is applied to the re-rendered page.
                logger.info("The form was rejected (%s); retrying once", "; ".join(errors))
                current_plan = build_form_plan(read_controls(page), facts)
                if current_plan.unresolved:
                    return _StepOutcome(kind="needs_human", questions=list(current_plan.unresolved))
                continue

            return _StepOutcome(kind="form_error", errors=errors)

        return _StepOutcome(kind="form_error", errors=["The form was not advanced."])

    def _record_what_was_left_alone(self, plan: FormPlan) -> None:
        """Remember the questions and widgets this page's fill did not answer."""
        for label in plan.skipped:
            if label not in self.questions_left_alone:
                self.questions_left_alone.append(label)
        for label in self.unsupported_widgets_in(plan):
            if label not in self.unrecognised_widgets:
                self.unrecognised_widgets.append(label)

    @staticmethod
    def unsupported_widgets_in(plan: FormPlan) -> list[str]:
        """The controls of *plan* whose kind the filler has no branch for.

        The measurement the pilot exists for includes the widgets the agent did
        not recognise, so a kind outside :data:`SUPPORTED_KINDS` is named
        rather than skipped silently. Today every kind
        :func:`src.applications.form.read_controls` can produce is supported; a
        board that publishes something else is how this list stops being empty.
        """
        return [
            question.label for question in plan.questions if question.kind not in SUPPORTED_KINDS
        ]

    def _awaiting_human_result(
        self,
        page,
        trace: NavigationTrace,
        context,
        evidence_dir: Path,
        workflow_id: str,
        prepared: PreparedApplication,
    ) -> ApplicationResult:
        """The result of a run that stopped at the submit button.

        The stop point is captured — a screenshot and the trace so far — but the
        Playwright trace is deliberately **not** stopped: it stays live across
        the handover so the human's own submit lands in the archive
        :meth:`capture_human_submission` writes.
        """
        screenshot = self._capture_screenshot(page, evidence_dir, workflow_id)
        trace_path = trace.write(evidence_dir / f"{workflow_id}.trace.json")
        evidence = SubmissionEvidence(
            url=page.url,
            confirmation_text=None,
            screenshot_path=screenshot,
            trace_path=trace_path.name if trace_path else None,
            status=AWAITING_HUMAN_SUBMIT,
        )
        return ApplicationResult(
            success=False,
            status=AWAITING_HUMAN_SUBMIT,
            message=(
                "The form was filled and the browser is left open: the agent does not hold "
                "the submit capability, so a human must press the form's own submit button. "
                "The stop point was captured as evidence."
            ),
            evidence=evidence,
            metadata={
                "job_url": prepared.request.job_url,
                "workflow_id": workflow_id,
                "questions_left_alone": list(self.questions_left_alone),
                "unrecognised_widgets": list(self.unrecognised_widgets),
                "human_submit_required": True,
            },
        )

    # ------------------------------------------------------------------
    # The human's submit
    # ------------------------------------------------------------------

    def capture_human_submission(self) -> ApplicationResult:
        """Capture the page the human submitted on, as evidence.

        Called after the human has pressed the form's own submit button in the
        window the agent left open. The agent clicks nothing here: it reads the
        page, captures a screenshot, stops the still-running trace and returns
        the evidence. "Submitted" is then the *page's* claim — the confirmation
        text is read from the page the human submitted on — and :meth:`verify`
        is what turns that into a verified status.

        Returns:
            ``status="human_submitted"`` when the page carries one of the
            confirmation markers, and ``status="unknown"`` when it does not.
            Never an exception: a capture that fails is reported, because an
            assist run without evidence must not read as a submission.
        """
        self.require_capability(CapabilityLevel.PREPARE)
        if self.page is None or self._evidence_dir is None:
            return ApplicationResult(
                success=False,
                status="no_open_page",
                message=(
                    "There is no open page to capture: the run either has not stopped yet or "
                    "the browser was already closed."
                ),
            )

        page = self.page
        workflow_id = self._workflow_id or "assist"
        text = self._page_text(page)
        screenshot = self._capture_screenshot(page, self._evidence_dir, workflow_id)
        trace_path = None
        if self._trace is not None:
            trace_path = self._trace.write(self._evidence_dir / f"{workflow_id}.trace.json")
        archive = self._stop_tracing_once()

        evidence = SubmissionEvidence(
            url=page.url,
            confirmation_text=text,
            screenshot_path=screenshot,
            trace_path=trace_path.name if trace_path else None,
            status="human_submitted",
        )
        confirmed = self._looks_submitted(text)
        return ApplicationResult(
            success=confirmed,
            status="human_submitted" if confirmed else "unknown",
            message=(
                "The page the human submitted on confirms the submission."
                if confirmed
                else "The page the human submitted on does not carry a confirmation marker."
            ),
            evidence=evidence,
            metadata={
                "job_url": self.page_url,
                "workflow_id": workflow_id,
                "playwright_trace_path": archive.name if archive else None,
            },
        )

    def verify(self, result: ApplicationResult) -> ApplicationResult:
        # WS-32: this adapter holds PREPARE and is not granted VERIFY, so it
        # asks for the capability it exercises — reading the evidence the run
        # captured. Asking for VERIFY would make verification unreachable, and
        # the human's own submission unverifiable.
        self.require_capability(CapabilityLevel.PREPARE)

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
            message="The page the run captured does not confirm a submission.",
            evidence=result.evidence,
            metadata=result.metadata,
        )

    # ------------------------------------------------------------------
    # The browser the human owns
    # ------------------------------------------------------------------

    @property
    def page_url(self) -> str:
        """The URL of the page the run stopped on ('' when there is none)."""
        page = self.page
        if page is None:
            return ""
        return str(getattr(page, "url", "") or "")

    def close(self) -> None:
        """Close the browser the run left open for the human.

        This is the operator's call, never the agent's: the whole point of
        assist mode is that the window stays open until the human has pressed
        its submit button. Idempotent — the pilot closes whatever it opened
        when the operator says the run is over, and a second call is a no-op.
        """
        if self._tracing_open:
            self._stop_tracing_once()
        page = self.page
        self.page = None
        self.browser_open = False
        if page is None:
            self._shutdown_browser()
            return
        try:
            context = page.context
        except Exception:  # noqa: BLE001 - a page without a context is already gone
            context = None
        try:
            if context is not None:
                context.close()
        except Exception as exc:  # noqa: BLE001 - teardown must not mask the outcome
            logger.warning("The browser context could not be closed cleanly: %s", exc)
        finally:
            self._shutdown_browser()

    def _evidence_directory(self, prepared: PreparedApplication) -> Path:
        """Where this run's evidence is written.

        The rule the fake-ATS adapter uses: the evidence belongs to the account
        the run was made for, so it lands in that account's own directory;
        without an owner (a direct call from a test or a script) the shared
        evidence directory is used.
        """
        if prepared.owner_id:
            from src.storage.paths import KIND_EVIDENCE, user_dir

            return ensure_dir(user_dir(prepared.owner_id, KIND_EVIDENCE))
        return ensure_dir(get_settings().evidence_dir)

    def _stop_tracing_once(self) -> Path | None:
        """Stop the Playwright trace, once, and store the archive.

        The trace stays live across the handover so the human's submit is inside
        it; whoever ends the run first — the capture, or :meth:`close` — writes
        the archive.
        """
        if not self._tracing_open or self._trace is None or self._evidence_dir is None:
            return None
        self._tracing_open = False
        page = self.page
        context = getattr(page, "context", None) if page is not None else None
        if context is None:
            return None
        return self._stop_tracing(context, self._evidence_dir, self._workflow_id or "assist")

    @staticmethod
    def _allow_localhost() -> bool:
        """The local fake ATS is reachable only outside production (SEC-06).

        The same rule as the parent's: a loopback target is admitted only when
        ``APP_ENV=development``. An assist run against a real board is on the
        operator's allowlist; the local rehearsal is the one loopback case.
        """
        return get_settings().app_env == "development"


__all__ = [
    "AWAITING_HUMAN_SUBMIT",
    "INCOMPLETE_PAYLOAD",
    "REQUEST_PLACEHOLDERS",
    "SUPPORTED_KINDS",
    "AssistAdapter",
    "split_candidate_name",
]
