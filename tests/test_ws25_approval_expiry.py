"""WS-25 · The approval expiry and the form-schema tests.

An approval used to have no clock. ``ApprovalStatus`` was ``PENDING /
APPROVED / REJECTED / EXECUTED / FAILED`` — there was no ``EXPIRED``
state and no expiry timestamp — so an approval granted on Monday would
still authorize a submission on Friday, against a résumé tailored with
Monday's profile, for a job that may have closed in between.

The Greenhouse form schema is the other half of WS-25: it is the only
public application-form schema of the four providers, and it is what
lets the prepare step show the operator the **exact** form and stop on
a question the agent cannot answer.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from src.applications.contracts import ApplicationRequest, PreparedApplication
from src.db.approval import (
    ApprovalStatus,
    approval_expiry,
    approval_ttl_hours,
    build_approval_row,
    profile_version_for,
)


def _prepared() -> PreparedApplication:
    request = ApplicationRequest(
        job_title="Engineer",
        company_name="Acme",
        job_url="https://job-boards.greenhouse.io/acme/jobs/1",
        candidate_name="Tester",
        email="t@example.com",
    )
    return PreparedApplication(request=request, prepared_fields={"email": "t@example.com"})


# ------------------------------------------------------------ the expiry


def test_an_approval_carries_an_expiry():
    """Every new approval is bounded in time."""
    row = build_approval_row(workflow_id="wf-1", adapter_name="greenhouse", prepared=_prepared())
    assert row.expires_at is not None
    assert row.status == ApprovalStatus.PENDING


def test_the_window_is_measured_from_creation_not_from_approval():
    """A request that sat pending for six days gets one day, not a week.

    The decision was made about a payload that is six days old, so a
    fresh week on approval would be measuring the wrong thing.
    """
    created = datetime.now(UTC) - timedelta(days=6)
    expiry = approval_expiry(created)
    remaining = expiry - created
    assert remaining == timedelta(hours=approval_ttl_hours())


def test_the_ttl_is_configurable():
    """The window is a knob, and a bad value falls back to the default."""
    import os

    previous = os.environ.get("APPROVAL_TTL_HOURS")
    try:
        os.environ["APPROVAL_TTL_HOURS"] = "24"
        assert approval_ttl_hours() == 24
        created = datetime.now(UTC)
        assert approval_expiry(created) - created == timedelta(hours=24)

        os.environ["APPROVAL_TTL_HOURS"] = "not-a-number"
        assert approval_ttl_hours() == 168

        os.environ["APPROVAL_TTL_HOURS"] = "0"
        assert approval_ttl_hours() == 168
    finally:
        if previous is None:
            os.environ.pop("APPROVAL_TTL_HOURS", None)
        else:
            os.environ["APPROVAL_TTL_HOURS"] = previous


def test_an_expired_approval_is_not_executable():
    """The state is ``expired``, not ``rejected`` and not ``pending``.

    A decision *was* made — it is simply no longer valid. Collapsing it
    into ``rejected`` would misreport what happened; leaving it
    ``pending`` would suggest nobody had looked at it.
    """
    from src.db.approval import approval_from_row

    row = build_approval_row(workflow_id="wf-1", adapter_name="greenhouse", prepared=_prepared())
    row.expires_at = datetime.now(UTC) - timedelta(minutes=1)

    stored = approval_from_row(row)
    assert stored.is_expired() is True


def test_an_approval_without_an_expiry_is_not_expired():
    """A row created before WS-25 has no expiry, and must still work.

    The column is nullable because an approval created before this
    workstream has none; refusing to execute it on that basis would
    strand every existing approval.
    """
    from src.db.approval import approval_from_row

    row = build_approval_row(workflow_id="wf-1", adapter_name="greenhouse", prepared=_prepared())
    row.expires_at = None

    stored = approval_from_row(row)
    assert stored.is_expired() is False


# ---------------------------------------------------- the profile binding


def test_the_profile_version_changes_when_the_facts_change():
    """An approval is bound to the profile it was built from."""
    first = profile_version_for({"email": "t@example.com", "skills": "python"})
    same = profile_version_for({"skills": "python", "email": "t@example.com"})
    different = profile_version_for({"email": "t@example.com", "skills": "rust"})

    assert first == same, "the digest must not depend on the dict order"
    assert first != different


def test_no_facts_means_no_version():
    """An approval with no grounded facts has nothing to bind to."""
    assert profile_version_for(None) is None
    assert profile_version_for({}) is None


# --------------------------------------------------------- the form schema


GREENHOUSE_QUESTIONS_PAYLOAD = {
    "id": 8172510,
    "title": "Software Engineer",
    "questions": [
        {
            "description": None,
            "label": "First Name",
            "required": True,
            "fields": [{"name": "first_name", "type": "input_text", "values": []}],
        },
        {
            "description": None,
            "label": "Resume/CV",
            "required": True,
            "fields": [
                {"name": "resume", "type": "input_file", "values": []},
                {"name": "resume_text", "type": "textarea", "values": []},
            ],
        },
        {
            "description": None,
            "label": "Please select the country where you currently reside.",
            "required": True,
            "fields": [
                {
                    "name": "question_69650990",
                    "type": "multi_value_single_select",
                    "values": [
                        {"label": "Germany", "value": "1"},
                        {"label": "Spain", "value": "2"},
                    ],
                }
            ],
        },
        {
            "description": None,
            "label": "Please select the country or countries you anticipate working in.",
            "required": True,
            "fields": [
                {
                    "name": "question_69650991[]",
                    "type": "multi_value_multi_select",
                    "values": [{"label": "Germany", "value": "1"}],
                }
            ],
        },
    ],
    "location_questions": [
        {
            "description": None,
            "label": "Latitude",
            "required": True,
            "fields": [{"name": "latitude", "type": "input_hidden", "values": []}],
        },
        {
            "description": None,
            "label": "Longitude",
            "required": True,
            "fields": [{"name": "longitude", "type": "input_hidden", "values": []}],
        },
        {
            "description": None,
            "label": "Location",
            "required": True,
            "fields": [{"name": "location", "type": "input_text", "values": []}],
        },
    ],
    "compliance": [
        {
            "type": "eeoc",
            "description": "<p>Voluntary</p>",
            "questions": [
                {
                    "required": False,
                    "label": "VeteranStatus",
                    "fields": [
                        {
                            "name": "veteran_status",
                            "type": "multi_value_single_select",
                            "values": [
                                {"label": "I don't wish to answer", "value": "3"},
                                {"label": "I am not a protected veteran", "value": "1"},
                            ],
                        }
                    ],
                }
            ],
        }
    ],
    "demographic_questions": None,
    "data_compliance": [
        {
            "type": "gdpr",
            "requires_consent": False,
            "requires_processing_consent": False,
            "requires_retention_consent": False,
            "retention_period": None,
            "demographic_data_consent_applies": False,
        }
    ],
}


def test_the_form_schema_is_read_from_the_boards_payload():
    """Greenhouse is the only provider that publishes its form."""
    from src.applications.greenhouse_forms import build_form_schema

    schema = build_form_schema(GREENHOUSE_QUESTIONS_PAYLOAD)

    assert len(schema.questions) == 4
    assert len(schema.location_questions) == 3
    assert len(schema.compliance) == 1
    assert schema.requires_gdpr_consent is False


def test_the_consent_and_demographic_questions_are_never_answered():
    """They are surfaced to the human, and nothing else.

    A consent box is an assertion the agent cannot make, and the
    demographic questions are voluntary by design.
    """
    from src.applications.greenhouse_forms import build_form_schema

    schema = build_form_schema(GREENHOUSE_QUESTIONS_PAYLOAD)

    consent = schema.unanswered_by_policy
    assert len(consent) == 1
    assert consent[0].block == "compliance"
    assert consent[0].label == "VeteranStatus"

    # The ordinary questions remain answerable.
    ordinary = [q for q in schema.questions if not q.needs_consent]
    assert len(ordinary) == 4


def test_the_location_questions_are_recognized():
    """Greenhouse needs the coordinates; without them the location is ignored."""
    from src.applications.greenhouse_forms import build_form_schema

    schema = build_form_schema(GREENHOUSE_QUESTIONS_PAYLOAD)

    assert all(question.is_location for question in schema.location_questions)
    names = {name for question in schema.location_questions for name in question.field_names}
    assert names == {"latitude", "longitude", "location"}


def test_a_multi_select_option_value_is_a_string():
    """Greenhouse returns the option value as a string, not an integer.

    The documentation's example shows integers, so a caller that assumed
    integers would silently fail to match the board's own value.
    """
    from src.applications.greenhouse_forms import build_form_schema

    schema = build_form_schema(GREENHOUSE_QUESTIONS_PAYLOAD)
    options = schema.questions[2].options
    assert {option["value"] for option in options} == {"1", "2"}
    assert all(isinstance(option["value"], str) for option in options)


def test_a_payload_with_no_questions_is_not_an_error():
    """A board that publishes no schema is a fact, not a failure."""
    from src.applications.greenhouse_forms import build_form_schema

    schema = build_form_schema({"id": 1, "title": "Engineer"})
    assert schema.questions == []
    assert schema.all_questions == []


# ------------------------------------------------------------ the liveness


def test_a_greenhouse_job_url_is_parsed_into_its_parts():
    """The board token is read from the URL, never guessed.

    A Greenhouse board token is *not* the company name: ``anduril``
    404s while ``andurilindustries`` answers.
    """
    from src.applications.greenhouse_adapter import parse_greenhouse_job_url

    assert parse_greenhouse_job_url("https://job-boards.greenhouse.io/stripe/jobs/8172510") == (
        "stripe",
        "8172510",
    )
    assert parse_greenhouse_job_url("https://boards.greenhouse.io/acme/jobs/42") == (
        "acme",
        "42",
    )
    # Not a Greenhouse URL at all.
    assert parse_greenhouse_job_url("https://example.com/jobs/1") is None
    # A malformed segment is refused.
    assert parse_greenhouse_job_url("https://job-boards.greenhouse.io/stripe/jobs/abc") is None


def test_a_past_deadline_makes_the_job_not_live():
    """A posting whose deadline has passed must not be applied to."""
    from src.applications.greenhouse_adapter import _deadline_has_passed

    past = (datetime.now(UTC) - timedelta(days=1)).isoformat()
    future = (datetime.now(UTC) + timedelta(days=1)).isoformat()
    assert _deadline_has_passed(past) is True
    assert _deadline_has_passed(future) is False
    # An unparsable deadline is not treated as passed: refusing to apply
    # on a date nobody can read would be a guess.
    assert _deadline_has_passed("not a date") is False
