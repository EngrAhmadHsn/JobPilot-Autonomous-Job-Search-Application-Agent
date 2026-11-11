"""WS-25b · The form schema wired into prepare, and liveness into approve.

WS-25 built `fetch_form_schema` and `check_job_is_live` and left them
with **zero callers** — readable but not surfaced. This file tests the
wiring, and the properties that make the wiring safe:

* a required question the agent cannot answer **stops the flow** with a
  named reason;
* a consent/EEO question is **never** a blocker and is **never**
  answerable — it is surfaced to the human;
* a board that is slow or down **does not fail a prepare** (the route
  made no network call before this, and must not gain a new failure
  mode);
* a job that is **gone** blocks an approval, while a board that cannot
  be reached **does not** — a flaky board must not become a way to block
  every approval.
"""

from __future__ import annotations

from src.applications.form_plan import (
    VERDICT_ANSWERABLE,
    VERDICT_NEEDS_HUMAN,
    VERDICT_NEVER_AUTOFILL,
    VERDICT_OPTIONAL_UNANSWERED,
    blocking_questions,
    build_question_plan,
    plan_as_dicts,
)
from src.applications.greenhouse_forms import build_form_schema

PAYLOAD = {
    "id": 1,
    "questions": [
        {
            "label": "First Name",
            "required": True,
            "fields": [{"name": "first_name", "type": "input_text", "values": []}],
        },
        {
            "label": "Email",
            "required": True,
            "fields": [{"name": "email", "type": "input_text", "values": []}],
        },
        {
            "label": "Cover Letter",
            "required": False,
            "fields": [{"name": "cover_letter_text", "type": "textarea", "values": []}],
        },
        {
            "label": "Why do you want this role?",
            "required": True,
            "fields": [{"name": "question_1", "type": "textarea", "values": []}],
        },
        {
            "label": "Anything else we should know?",
            "required": False,
            "fields": [{"name": "question_2", "type": "textarea", "values": []}],
        },
        {
            "label": "Will you require sponsorship for a work permit?",
            "required": True,
            "fields": [
                {
                    "name": "question_3",
                    "type": "multi_value_single_select",
                    "values": [{"label": "Yes", "value": "1"}, {"label": "No", "value": "2"}],
                }
            ],
        },
    ],
    "location_questions": [],
    "compliance": [
        {
            "type": "eeoc",
            "description": "<p/>",
            "questions": [
                {
                    "required": False,
                    "label": "VeteranStatus",
                    "fields": [
                        {
                            "name": "veteran_status",
                            "type": "multi_value_single_select",
                            "values": [{"label": "I don't wish to answer", "value": "3"}],
                        }
                    ],
                },
            ],
        },
    ],
    "demographic_questions": None,
    "data_compliance": [],
}


def _facts(**overrides) -> dict[str, str]:
    facts = {
        "candidate_name": "Ahmad Hassan",
        "email": "a@example.com",
        "requires_sponsorship": "no",
    }
    facts.update(overrides)
    return facts


# --------------------------------------------------------- the plan


def test_an_answerable_question_is_marked_answerable():
    """A grounded fact makes a question answerable, and names the fact."""
    schema = build_form_schema(PAYLOAD)
    plans = build_question_plan(schema, _facts())

    email = next(plan for plan in plans if plan.label == "Email")
    assert email.verdict == VERDICT_ANSWERABLE
    assert email.answer_from == "email"


def test_a_required_unanswerable_question_blocks():
    """The case the whole wiring exists for.

    "Why do you want this role?" is required and no grounded fact answers
    it, so the flow must stop with a named reason instead of discovering
    the gap at submission time.
    """
    schema = build_form_schema(PAYLOAD)
    plans = build_question_plan(schema, _facts())

    question = next(plan for plan in plans if plan.label == "Why do you want this role?")
    assert question.verdict == VERDICT_NEEDS_HUMAN
    assert question.blocks_submission is True

    blockers = blocking_questions(plans)
    assert [plan.label for plan in blockers] == ["Why do you want this role?"]


def test_an_optional_unanswerable_question_does_not_block():
    """An optional gap is not a reason to stop."""
    schema = build_form_schema(PAYLOAD)
    plans = build_question_plan(schema, _facts())

    question = next(plan for plan in plans if plan.label == "Anything else we should know?")
    assert question.verdict == VERDICT_OPTIONAL_UNANSWERED
    assert question.blocks_submission is False


def test_a_consent_question_is_never_autofilled_and_never_blocks():
    """A consent/EEO question is the human's, and is not a blocker.

    Two separate properties, both required: the agent must not answer it,
    and its presence must not stop the flow — because the human answers
    it at the approval step by design.
    """
    schema = build_form_schema(PAYLOAD)
    plans = build_question_plan(schema, _facts())

    veteran = next(plan for plan in plans if plan.label == "VeteranStatus")
    assert veteran.verdict == VERDICT_NEVER_AUTOFILL
    assert veteran.blocks_submission is False
    assert veteran.answer_from is None


def test_a_consent_question_is_never_autofilled_even_with_a_fact():
    """The verdict is not overridable by supplying the fact.

    Even if a caller passed a `veteran_status` fact, the agent must not
    answer the question: the prohibition is on the *question*, not on the
    availability of a value.
    """
    schema = build_form_schema(PAYLOAD)
    plans = build_question_plan(schema, _facts(veteran_status="I am not a protected veteran"))

    veteran = next(plan for plan in plans if plan.label == "VeteranStatus")
    assert veteran.verdict == VERDICT_NEVER_AUTOFILL


def test_a_sponsorship_question_is_answerable_when_the_fact_exists():
    """A sponsorship question is not EEO — it is answerable from the profile."""
    schema = build_form_schema(PAYLOAD)
    plans = build_question_plan(schema, _facts())

    sponsorship = next(plan for plan in plans if "sponsorship" in plan.label.casefold())
    assert sponsorship.verdict == VERDICT_ANSWERABLE
    assert sponsorship.answer_from == "requires_sponsorship"


def test_no_facts_means_every_non_consent_question_is_a_gap():
    """An empty profile answers nothing, which is the honest state."""
    schema = build_form_schema(PAYLOAD)
    plans = build_question_plan(schema, {})

    answerable = [plan for plan in plans if plan.verdict == VERDICT_ANSWERABLE]
    assert answerable == []


def test_the_plan_is_serializable_for_the_response():
    """The plan travels in the prepare response and the approval row."""
    schema = build_form_schema(PAYLOAD)
    plans = build_question_plan(schema, _facts())

    rows = plan_as_dicts(plans)
    assert len(rows) == len(plans)
    assert {"label", "required", "block", "verdict", "category", "answer_from", "fields"} <= set(
        rows[0]
    )


def test_a_schema_with_no_questions_yields_no_plans():
    """A board that publishes no form is not an error."""
    schema = build_form_schema({"id": 1, "title": "Engineer"})
    assert build_question_plan(schema, _facts()) == []


# ------------------------------------------------- the prepare route wiring


def test_the_prepare_route_fetches_the_form_schema():
    """The route calls the adapter's schema fetch.

    Before this workstream the function had **zero callers**, so the
    board's own form was never read.
    """
    from src.api.routes.applications import _build_form_plans

    calls: list[str] = []

    class Adapter:
        async def fetch_form_schema(self, url):
            calls.append(url)
            return build_form_schema(PAYLOAD)

    plans = _build_form_plans(Adapter(), "https://job-boards.greenhouse.io/x/jobs/1", _facts())

    assert calls, "the route never asked for the schema"
    assert len(plans) == len(build_form_schema(PAYLOAD).all_questions)


def test_a_schema_failure_does_not_fail_the_prepare():
    """A board that cannot be read degrades to the fixed field map.

    The prepare route made no network call before this workstream, and
    adding one must not add a failure mode: a slow or broken board must
    not stop an operator from preparing an application.
    """

    class Adapter:
        async def fetch_form_schema(self, url):
            raise TimeoutError("the board did not answer")

    from src.api.routes.applications import _build_form_plans

    assert _build_form_plans(Adapter(), "https://x/1", _facts()) == []


def test_an_adapter_with_no_schema_is_skipped():
    """Lever, Ashby and Remotive publish no schema; that is not an error."""

    class Adapter:
        pass

    from src.api.routes.applications import _build_form_plans

    assert _build_form_plans(Adapter(), "https://x/1", _facts()) == []


def test_a_none_schema_is_skipped():
    """A board that answers but publishes nothing is handled."""

    class Adapter:
        async def fetch_form_schema(self, url):
            return None

    from src.api.routes.applications import _build_form_plans

    assert _build_form_plans(Adapter(), "https://x/1", _facts()) == []


# -------------------------------------------------- the approve route wiring


def _approval_row(job_url: str):
    """A minimal approval row, enough for the liveness check."""
    from src.db.approval import ApprovalRequestDB

    return ApprovalRequestDB(
        id="a1",
        workflow_id="wf-1",
        adapter_name="greenhouse",
        job_url=job_url,
        job_title="Engineer",
        company_name="Acme",
        payload={},
        status="pending",
    )


def test_a_gone_job_blocks_the_approval(monkeypatch):
    """A 404 from the board is a definitive answer: the job is closed."""
    from src.api.routes import applications as routes

    class Adapter:
        async def check_job_is_live(self, url):
            return False, "the job is no longer published (404)"

    monkeypatch.setattr(routes, "_adapter_for_url", lambda url: Adapter())

    gone, reason = routes._job_liveness(_approval_row("https://job-boards.greenhouse.io/x/jobs/1"))
    assert gone is True
    assert "404" in reason


def test_an_unreachable_board_does_not_block_the_approval(monkeypatch):
    """A transport failure is not evidence that a job closed.

    This is the distinction that keeps one flaky board from blocking
    every approval.
    """
    from src.api.routes import applications as routes

    class Adapter:
        async def check_job_is_live(self, url):
            raise TimeoutError("no answer")

    monkeypatch.setattr(routes, "_adapter_for_url", lambda url: Adapter())

    gone, reason = routes._job_liveness(_approval_row("https://job-boards.greenhouse.io/x/jobs/1"))
    assert gone is False
    assert "could not verify" in reason


def test_a_live_job_does_not_block(monkeypatch):
    """The happy path."""
    from src.api.routes import applications as routes

    class Adapter:
        async def check_job_is_live(self, url):
            return True, "the job is published and accepting applications"

    monkeypatch.setattr(routes, "_adapter_for_url", lambda url: Adapter())

    gone, _reason = routes._job_liveness(_approval_row("https://job-boards.greenhouse.io/x/jobs/1"))
    assert gone is False


def test_a_provider_with_no_liveness_check_does_not_block(monkeypatch):
    """The absence of a check is not a reason to block.

    Lever, Ashby and Remotive publish no liveness endpoint; refusing to
    approve their applications would be worse than not checking.
    """
    from src.api.routes import applications as routes

    class Adapter:
        pass

    monkeypatch.setattr(routes, "_adapter_for_url", lambda url: Adapter())

    gone, reason = routes._job_liveness(_approval_row("https://jobs.lever.co/x/1"))
    assert gone is False
    assert "no liveness check" in reason


def test_no_adapter_does_not_block(monkeypatch):
    """A URL no adapter claims is not a closed job."""
    from src.api.routes import applications as routes

    monkeypatch.setattr(routes, "_adapter_for_url", lambda url: None)

    gone, reason = routes._job_liveness(_approval_row("https://unknown.example/1"))
    assert gone is False
    assert "no liveness check" in reason


def test_a_past_deadline_blocks(monkeypatch):
    """A deadline that has passed is a definitive answer too."""
    from src.api.routes import applications as routes

    class Adapter:
        async def check_job_is_live(self, url):
            return False, "the application deadline passed (2026-01-01T00:00:00Z)"

    monkeypatch.setattr(routes, "_adapter_for_url", lambda url: Adapter())

    gone, reason = routes._job_liveness(_approval_row("https://job-boards.greenhouse.io/x/jobs/1"))
    assert gone is True
    assert "deadline" in reason
