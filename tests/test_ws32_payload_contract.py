"""WS-32 · We validate the payload because the provider does not.

Greenhouse's documentation says it plainly: "Greenhouse will not reject
applications that are missing required fields." So an incomplete submission
SUCCEEDS and is silently incomplete — the candidate believes they applied and
the employer receives a blank. The contract below is Greenhouse's own published
field list, recovered from its documentation source; it is the only part of the
researched material that survived verification against the live API.

The module docstring is part of what is pinned here: consent reporting is
built and tested but **inert** — no production caller supplies a schema — and
a docstring that promises a caller is exactly the repo's named defect class
(a reader relies on the prose instead of the code). The last block asserts the
docstring's claim and trips if a caller ever appears.
"""

from __future__ import annotations

import re
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from src.applications import greenhouse_contract
from src.applications.contracts import (
    ApplicationRequest,
    ApplicationResult,
    PreparedApplication,
)
from src.applications.greenhouse_contract import (
    CONSENT_FIELDS,
    CONTRACT_ADAPTERS,
    REQUIRED_FIELDS,
    custom_question_fields,
    validate_against_contract,
)
from src.applications.greenhouse_forms import FormQuestion, FormSchema
from src.graph.nodes import submit_node
from src.graph.state import ApplicationWorkflowState
from src.security.audit import ACTION_SUBMIT, OUTCOME_BLOCKED
from src.security.permissions import CapabilityLevel, PermissionRegistry


def _prepared(**fields) -> PreparedApplication:
    return PreparedApplication(
        request=ApplicationRequest(
            job_title="Backend Engineer",
            company_name="Acme",
            job_url="https://boards.greenhouse.io/acme/jobs/1",
        ),
        prepared_fields=fields,
    )


def test_a_complete_payload_is_complete() -> None:
    report = validate_against_contract(
        _prepared(
            first_name="Ada",
            last_name="Lovelace",
            email="ada@example.com",
            phone="+44 20 7946 0000",
            # The brief's snippet omitted the resume here while asserting
            # completeness, which contradicts its own next test (no resume at
            # all is incomplete). The resume requirement is the contract's
            # documented document field, so the *complete* fixture carries
            # one and the contradiction is resolved in favour of the rule.
            resume_text="Experience: ...",
        )
    )
    assert report.is_complete
    assert report.missing == []


def test_a_missing_identity_field_is_reported_by_name() -> None:
    report = validate_against_contract(_prepared(first_name="Ada", email="ada@example.com"))
    assert not report.is_complete
    assert "last_name" in report.missing
    assert "phone" in report.missing


def test_a_text_resume_satisfies_the_resume_requirement() -> None:
    """`resume` is a file OR `resume_text` — the contract accepts either."""
    assert validate_against_contract(
        _prepared(
            first_name="Ada", last_name="Lovelace",
            email="ada@example.com", phone="+1",
            resume_text="Experience: ...",
        )
    ).is_complete


def test_an_uploaded_file_satisfies_the_resume_requirement() -> None:
    prepared = _prepared(
        first_name="Ada", last_name="Lovelace", email="ada@example.com", phone="+1"
    )
    prepared.resume_path = "data/resumes/profile-1.pdf"
    assert validate_against_contract(prepared).is_complete


def test_a_payload_with_no_resume_at_all_is_incomplete() -> None:
    report = validate_against_contract(
        _prepared(first_name="Ada", last_name="Lovelace", email="ada@example.com", phone="+1")
    )
    assert not report.is_complete
    assert "resume" in report.missing


def test_a_consent_field_left_unanswered_is_reported_separately() -> None:
    """Consent is not "missing" — it is a human's to give, and the distinction
    is what stops a missing consent from reading as a bug the agent should fix."""
    report = validate_against_contract(
        _prepared(
            first_name="Ada", last_name="Lovelace",
            email="ada@example.com", phone="+1", resume_text="x",
        ),
        consent_required=("data_compliance[gdpr_processing_consent_given]",),
    )
    assert report.is_complete
    assert report.consent_unanswered == [
        "data_compliance[gdpr_processing_consent_given]"
    ]


def test_the_required_field_list_is_the_documented_one() -> None:
    assert set(REQUIRED_FIELDS) == {"first_name", "last_name", "email", "phone"}


# -- the documented names and the report's own shape ---------------------------


def test_a_file_field_named_resume_satisfies_the_requirement() -> None:
    """`resume` is the contract's own name for the uploaded file.

    The payload may carry it either as the model's ``resume_path`` or under
    the contract's name in ``prepared_fields``; both are the same document.
    """
    report = validate_against_contract(
        _prepared(
            first_name="Ada",
            last_name="Lovelace",
            email="ada@example.com",
            phone="+1",
            resume="data/resumes/profile-1.pdf",
        )
    )
    assert report.is_complete


def test_an_empty_field_is_missing_not_answered() -> None:
    """A blank answer is exactly the silent-incompleteness the provider allows.

    Greenhouse does not reject a submission whose `first_name` is an empty
    string, so an empty value must read as *missing* here — otherwise the
    gate would pass the payload the provider would accept and the employer
    would receive a blank.
    """
    report = validate_against_contract(
        _prepared(
            first_name="   ",
            last_name="Lovelace",
            email="ada@example.com",
            phone="+1",
            resume_text="",
        )
    )
    assert not report.is_complete
    assert report.missing == ["first_name", "resume"]
    # And neither a blank value nor an absent one is counted as answered.
    assert report.consent_unanswered == []


def test_the_documented_consent_fields_are_named() -> None:
    """The consent group is the documented one, so a caller need not retype it."""
    assert set(CONSENT_FIELDS) == {
        "data_compliance[gdpr_processing_consent_given]",
        "data_compliance[gdpr_retention_consent_given]",
        "data_compliance[gdpr_demographic_data_consent_given]",
    }


def test_a_schema_derives_the_consent_fields_from_its_own_questions() -> None:
    """With a schema, the consent list comes from the schema's own questions.

    A consent question's fields are the ones a human fills in at approval
    time; the report says which of them are still unanswered. The agent's
    payload answering nothing does not make the report incomplete.
    """
    schema = FormSchema(
        questions=[FormQuestion(label="First Name", required=True, field_names=["first_name"])],
        compliance=[
            FormQuestion(
                label="VeteranStatus",
                required=False,
                field_names=["veteran_status"],
                block="compliance",
            )
        ],
    )
    report = validate_against_contract(
        _prepared(
            first_name="Ada",
            last_name="Lovelace",
            email="ada@example.com",
            phone="+1",
            resume_text="Experience: ...",
        ),
        schema=schema,
    )
    assert report.is_complete
    assert report.consent_unanswered == ["veteran_status"]


def test_an_answered_consent_field_is_not_reported() -> None:
    answered = "data_compliance[gdpr_processing_consent_given]"
    report = validate_against_contract(
        _prepared(
            first_name="Ada",
            last_name="Lovelace",
            email="ada@example.com",
            phone="+1",
            resume_text="x",
            **{answered: "true"},
        ),
        consent_required=(answered,),
    )
    assert report.is_complete
    assert report.consent_unanswered == []


# -- custom_question_fields -----------------------------------------------------


def test_custom_question_fields_names_the_contract_field_of_each_question() -> None:
    """A custom question is submitted under `question_{id}` (WS-25, documented).

    The multi-value form the board publishes carries the multipart bracket
    suffix (`question_69650991[]`), and that suffix is part of the name the
    contract documents, so it is preserved rather than stripped.
    """
    schema = FormSchema(
        questions=[
            FormQuestion(
                label="Please select the country where you currently reside.",
                required=True,
                field_names=["question_69650990"],
                field_types=["multi_value_single_select"],
            ),
            FormQuestion(
                label="Which teams may we share this with?",
                required=False,
                field_names=["question_69650991[]"],
                field_types=["multi_value_multi_select"],
            ),
        ],
        location_questions=[
            FormQuestion(label="Location", required=True, field_names=["location"])
        ],
    )

    mapping = custom_question_fields(schema)

    assert mapping == {
        "question_69650990": "question_69650990",
        "question_69650991[]": "question_69650991[]",
    }
    # A documented field of its own is not a custom question.
    assert "location" not in mapping


def test_custom_question_fields_is_empty_without_a_schema() -> None:
    assert custom_question_fields(None) == {}


# -- the submit node's gate -----------------------------------------------------


def _adapter(name: str, result: ApplicationResult | None = None) -> MagicMock:
    adapter = MagicMock()
    adapter.name = name
    if result is not None:
        adapter.submit.return_value = result
    return adapter


def _state(prepared: PreparedApplication, adapter_name: str) -> ApplicationWorkflowState:
    return ApplicationWorkflowState(
        request=prepared.request,
        workflow_id="wf-ws32",
        adapter_name=adapter_name,
        prepared_application=prepared,
    )


def _spec_with_submit(adapter_name: str) -> PermissionRegistry:
    """A registry that grants *adapter_name* the submit capability.

    The documented matrix grants Greenhouse **prepare only**, so without this
    the permission gate would refuse the adapter first and the contract gate
    would never be reached — and it is the contract gate these tests are
    about. The capacity to submit is granted here so the refusal that follows
    can only be the contract's.
    """
    registry = PermissionRegistry()
    registry.register(
        adapter_name,
        [CapabilityLevel.PREPARE, CapabilityLevel.SUBMIT, CapabilityLevel.VERIFY],
    )
    return registry


def test_the_node_refuses_an_incomplete_greenhouse_payload(
    monkeypatch,
) -> None:
    """An incomplete payload is not submitted, and it does not raise.

    This is the whole point of the task: the provider would accept this
    payload and the employer would receive a blank. The application stops
    with the missing field names instead.
    """
    monkeypatch.setattr(
        "src.graph.nodes.get_registry", lambda: _spec_with_submit("greenhouse")
    )
    adapter = _adapter("greenhouse")
    prepared = _prepared(
        candidate_name="Ada Lovelace", email="ada@example.com", phone="+1 555 0101"
    )

    result_state = submit_node(_state(prepared, "greenhouse"), adapter)

    assert result_state.submission_result is not None
    assert result_state.submission_result.success is False
    assert result_state.submission_result.status == "incomplete_payload"
    assert "first_name" in result_state.submission_result.message
    assert "last_name" in result_state.submission_result.message
    assert "resume" in result_state.submission_result.message
    assert result_state.error is not None
    # Fail-closed: the adapter was never asked to submit.
    adapter.submit.assert_not_called()


def test_the_node_admits_a_complete_greenhouse_payload(monkeypatch) -> None:
    """The gate is not a blanket refusal: a complete payload still submits."""
    monkeypatch.setattr(
        "src.graph.nodes.get_registry", lambda: _spec_with_submit("greenhouse")
    )
    expected = ApplicationResult(success=True, status="submitted", message="ok")
    adapter = _adapter("greenhouse", expected)
    prepared = _prepared(
        first_name="Ada",
        last_name="Lovelace",
        email="ada@example.com",
        phone="+1 555 0101",
        resume_text="Experience: ...",
    )

    result_state = submit_node(_state(prepared, "greenhouse"), adapter)

    assert result_state.submission_result is expected
    adapter.submit.assert_called_once()


def test_the_gate_does_not_touch_an_adapter_outside_the_contract() -> None:
    """The fake ATS is excluded by design (WS-32 · Task 2).

    Its payload is a form-walk summary — `candidate_name`, not
    `first_name`/`last_name` — and its completeness protection is its own
    WS-08 walker, which stops on an unanswered required question. An
    unconditional gate here would refuse the only live submission path.
    """
    assert "fake-ats-playwright" not in CONTRACT_ADAPTERS
    expected = ApplicationResult(success=True, status="submitted", message="ok")
    adapter = _adapter("fake-ats-playwright", expected)
    prepared = _prepared(candidate_name="Ada Lovelace")

    result_state = submit_node(_state(prepared, "fake-ats-playwright"), adapter)

    assert result_state.submission_result is expected
    adapter.submit.assert_called_once()


def test_the_refusal_is_recorded_in_the_audit_trail(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    """WS-32 · R4: the refusal writes an audit row, on the documented action.

    The row uses the existing ``ACTION_SUBMIT`` constant with the
    ``blocked`` outcome — no new action name is invented — so the refusal is
    queryable next to every other submission outcome.
    """
    from sqlalchemy import create_engine, select
    from sqlalchemy.orm import Session, sessionmaker

    from src.db.audit import AuditEventDB
    from src.db.base import Base

    engine = create_engine(f"sqlite:///{(tmp_path / 'contract.db').as_posix()}")
    Base.metadata.create_all(engine, tables=[AuditEventDB.__table__])
    factory = sessionmaker(bind=engine, autoflush=False)
    # The audit writer opens its own session when none is handed over.
    monkeypatch.setattr("src.db.session.SessionLocal", factory)
    monkeypatch.setattr(
        "src.graph.nodes.get_registry", lambda: _spec_with_submit("greenhouse")
    )
    adapter = _adapter("greenhouse")
    prepared = _prepared(email="ada@example.com", phone="+1 555 0101")
    prepared.owner_id = "account-1"

    submit_node(_state(prepared, "greenhouse"), adapter)

    with Session(engine) as session:
        events = list(session.scalars(select(AuditEventDB)))
    assert len(events) == 1
    row = events[0]
    assert row.action == ACTION_SUBMIT
    assert row.outcome == OUTCOME_BLOCKED
    assert row.owner_id == "account-1"
    assert row.actor == "agent:greenhouse"
    assert row.extra_metadata["status"] == "incomplete_payload"
    assert set(row.extra_metadata["missing_fields"]) == {
        "first_name",
        "last_name",
        "resume",
    }
    engine.dispose()


# -- the docstring's claim, and the caller it must not promise -----------------
#
# The module docstring said consent reporting "belongs to callers that hold a
# schema (the WS-32 assist pilot fetches one)". No caller fetches one: the
# pilot passes neither ``schema=`` nor ``consent_required=``, so
# ``consent_fields_from_schema`` and ``custom_question_fields`` have no caller
# outside this file. A docstring a reader relies on instead of the code is the
# repo's named defect class, and a maintainer reading it would believe consent
# reporting is live on the one path that reaches a real board.


def _sentences(text: str) -> list[str]:
    """The docstring's sentences, with whitespace collapsed."""
    return [part for part in re.split(r"(?<=[.!?])\s+", " ".join(text.split())) if part]


#: The verb a docstring would use to claim a schema is being obtained.
_FETCH = re.compile(r"(?i)\bfetch\w*")

#: The words that turn a schema fetch into a statement of the truth.
_NEGATIONS = ("no ", "not ", "never", "neither", "nothing", "without", "cannot")


def _claims_a_schema_fetch(sentence: str) -> bool:
    """Whether a sentence claims a schema is fetched, rather than denies it."""
    lowered = sentence.lower()
    for match in _FETCH.finditer(lowered):
        window = lowered[max(0, match.start() - 50) : match.end() + 50]
        if "schema" not in window:
            continue
        before = lowered[max(0, match.start() - 70) : match.start()]
        if any(negation in before for negation in _NEGATIONS):
            continue
        return True
    return False


def test_the_docstring_does_not_promise_a_caller_that_fetches_a_schema() -> None:
    """The claim is gone: no caller supplies a schema, so nothing is fetched.

    This is the RED the docstring fix answers. A corrected docstring may say
    "no caller supplies a schema" or that a future caller would make the
    helpers live; what it may not do is keep the false claim.
    """
    claimed = [
        sentence
        for sentence in _sentences(greenhouse_contract.__doc__ or "")
        if _claims_a_schema_fetch(sentence)
    ]
    assert claimed == [], (
        "The module docstring claims a schema fetch no code performs: "
        f"{claimed!r}. No caller supplies a schema today — the WS-32 assist pilot "
        "fetches none and passes neither schema= nor consent_required= — so say "
        "that consent reporting is built but inert."
    )


def test_the_docstring_says_consent_reporting_is_built_but_inert() -> None:
    """The fix names the functions and what would make them live.

    Deleting the paragraph would not do: the docstring has to carry the truth
    a reader needs — the two helpers, that nothing supplies a schema today,
    and that a caller passing one (or naming ``consent_required``) is what
    would make consent reporting live.
    """
    doc = " ".join((greenhouse_contract.__doc__ or "").split())

    assert "consent_fields_from_schema" in doc
    assert "custom_question_fields" in doc
    assert "consent_required" in doc
    assert "no caller" in doc.lower()
    # The accurate half survives: a missing consent is never reported as a
    # *missing* field — it is a human's to give.
    assert "a human's to give" in doc


def test_consent_reporting_has_no_production_caller() -> None:
    """A tripwire, not a proof: if this fails, the docstring is now wrong.

    ``consent_fields_from_schema`` and ``custom_question_fields`` are built and
    tested, and inert: the submit node hands over no schema and the pilot
    fetches none, so no production code calls them. This scans ``src/`` and
    ``scripts/`` for either name, skipping the module that defines them (whose
    own ``validate_against_contract`` is the plumbing, not a caller with a
    schema) and skipping the test tree — ``src`` and ``scripts`` are the only
    trees scanned at all.

    It is a text scan and therefore a tripwire rather than a proof: an
    aliased import or a string-built name would evade it. When it trips, the
    module docstring's "no caller supplies a schema today" is what to update.
    """
    root = Path(__file__).resolve().parents[1]
    defining_module = Path(greenhouse_contract.__file__).resolve()
    names = ("consent_fields_from_schema", "custom_question_fields")

    offenders: list[str] = []
    for package in ("src", "scripts"):
        for path in sorted((root / package).rglob("*.py")):
            if path.resolve() == defining_module:
                continue
            text = path.read_text(encoding="utf-8")
            for line_number, line in enumerate(text.splitlines(), start=1):
                if any(name in line for name in names):
                    offenders.append(
                        f"{path.relative_to(root).as_posix()}:{line_number}: {line.strip()}"
                    )

    assert offenders == [], (
        "A caller of the contract's consent helpers appeared, so consent reporting "
        "is no longer inert and the module docstring's claim must be updated: "
        + "; ".join(offenders)
    )
