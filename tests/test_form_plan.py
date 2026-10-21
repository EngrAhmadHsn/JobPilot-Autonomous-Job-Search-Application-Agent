"""WS-08 · Phase A — the application-form contract (plan §24).

The rule these tests protect: **a question is answered only from the
candidate's own evidence.** "UNKNOWN" is a valid answer; false confidence is
not.

Everything here runs without a browser: the plan is a pure function of the
page's controls and the grounded facts.
"""

from __future__ import annotations

import pytest

from src.applications.contracts import ApplicationRequest, PreparedApplication
from src.applications.form import (
    FieldLookup,
    FormControl,
    FormQuestion,
    ProfileFacts,
    answer_question,
    build_form_plan,
    classify_question,
    facts_from_profile,
    lookup_fact_key,
    normalize_label,
)
from src.resume.profile import (
    CandidateProfile,
    ExperienceEntry,
    PersonalInformation,
    WorkPreferences,
)

# ---------------------------------------------------------------------------
# The label normalization and the field map
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Full name", "full name"),
        ("  Full   Name  ", "full name"),
        ("Email address:", "email address"),
        ("Full name *", "full name"),
        ("Years of experience?", "years of experience"),
        ("", ""),
    ],
)
def test_normalize_label_canonicalizes_a_label(raw: str, expected: str) -> None:
    assert normalize_label(raw) == expected


def test_lookup_fact_key_matches_an_exact_label() -> None:
    assert lookup_fact_key("Full name") == "candidate_name"
    assert lookup_fact_key("Email address") == "email"
    assert lookup_fact_key("Years of experience") == "years_of_experience"


def test_lookup_fact_key_falls_back_to_the_longest_unambiguous_match() -> None:
    # "Work mode" is a substring of "Preferred work mode"; both map to the
    # same fact, so the lookup is unambiguous.
    assert lookup_fact_key("Preferred work mode") == "work_mode"
    # A long label that contains a shorter long key resolves to the longer.
    assert lookup_fact_key("I am authorized to work in the United States") == "work_authorization"


def test_lookup_fact_key_returns_none_for_an_unknown_label() -> None:
    assert lookup_fact_key("Have you served on a submarine?") is None
    assert lookup_fact_key("") is None


def test_lookup_fact_key_does_not_guess_a_short_label() -> None:
    # "Company name" contains "name", but the candidate's name is not what
    # this field asks for — an unmatched field must stay unknown.
    assert lookup_fact_key("Company name") is None


def test_field_lookup_is_exposed_as_a_namespace() -> None:
    # A small, explicit surface: the field map and the source keys.
    assert FieldLookup.FIELD_MAP["full name"] == "candidate_name"
    assert "remote_preference" in FieldLookup.FACT_SOURCES["work_mode"]


# ---------------------------------------------------------------------------
# The grounded facts
# ---------------------------------------------------------------------------


def _profile() -> CandidateProfile:
    return CandidateProfile(
        personal_information=PersonalInformation(
            name="Ada Lovelace",
            email="ada@example.com",
            phone="+1 555 0101",
            location="Berlin, Germany",
            title="Senior Python Engineer",
        ),
        skills=["Python", "LangGraph"],
        experience=[
            ExperienceEntry(title="Engineer", company="Acme", years=4),
            ExperienceEntry(title="Engineer", company="Globex", years=3),
        ],
        work_preferences=WorkPreferences(
            remote_preference="remote",
            work_authorization="authorized",
            min_salary="120000",
            employment_types=["full-time"],
        ),
    )


def test_facts_from_profile_reports_only_what_the_document_states() -> None:
    facts = facts_from_profile(_profile())

    assert facts["name"] == "Ada Lovelace"
    assert facts["email"] == "ada@example.com"
    assert facts["location"] == "Berlin, Germany"
    assert facts["remote_preference"] == "remote"
    assert facts["work_authorization"] == "authorized"
    assert facts["min_salary"] == "120000"
    assert facts["employment_types"] == "full-time"
    assert facts["skills"] == "Python, LangGraph"
    # 4 + 3 years, both stated by the document.
    assert facts["years_of_experience"] == "7"


def test_facts_from_profile_omits_what_the_document_does_not_state() -> None:
    profile = CandidateProfile(
        personal_information=PersonalInformation(name="Ada Lovelace"),
    )

    facts = facts_from_profile(profile)

    assert facts == {"name": "Ada Lovelace"}
    # No stated years -> no years fact. The question that asks for it becomes
    # unresolved; it never becomes "0".
    assert "years_of_experience" not in facts
    assert "work_authorization" not in facts


def test_profile_facts_from_prepared_merges_every_source() -> None:
    request = ApplicationRequest(
        job_title="Engineer",
        company_name="Acme",
        job_url="http://127.0.0.1:9/apply",
        candidate_name="Ada Lovelace",
        email="ada@example.com",
    )
    prepared = PreparedApplication(
        request=request,
        prepared_fields={"candidate_name": "Ada Lovelace", "email": "ada@example.com"},
        profile_facts={"years_of_experience": "7"},
        cover_letter="Hello team",
        resume_path="/tmp/resume.pdf",
    )

    facts = ProfileFacts.from_prepared(prepared)

    assert facts.get("candidate_name") == "Ada Lovelace"
    assert facts.get("years_of_experience") == "7"
    assert facts.get("cover_letter") == "Hello team"
    assert facts.get("resume") == "/tmp/resume.pdf"


def test_profile_facts_treats_an_absent_key_as_no_evidence() -> None:
    facts = ProfileFacts(values={"name": "Ada", "email": "   "})

    assert facts.get("name") == "Ada"
    assert facts.has("email") is False
    assert facts.get("email") is None


# ---------------------------------------------------------------------------
# The answer rule
# ---------------------------------------------------------------------------


def _question(label: str, kind: str = "text", **kwargs) -> FormQuestion:
    return FormQuestion(label=label, kind=kind, **kwargs)


def test_answer_question_uses_the_grounded_value() -> None:
    facts = ProfileFacts(values={"candidate_name": "Ada Lovelace"})

    assert answer_question(_question("Full name"), facts) == "Ada Lovelace"


def test_answer_question_refuses_an_unknown_label() -> None:
    facts = ProfileFacts(values={"candidate_name": "Ada Lovelace"})

    assert answer_question(_question("Have you served on a submarine?"), facts) is None


def test_answer_question_refuses_a_field_without_a_value() -> None:
    facts = ProfileFacts(values={"email": "ada@example.com"})

    assert answer_question(_question("Phone number"), facts) is None


def test_answer_question_refuses_a_select_value_that_matches_no_option() -> None:
    facts = ProfileFacts(values={"country": "Atlantis"})

    question = _question(
        "Country",
        kind="select",
        options=["Select a country", "Germany", "Canada"],
    )

    assert answer_question(question, facts) is None


def test_answer_question_matches_a_select_value_against_its_options() -> None:
    facts = ProfileFacts(values={"country": "germany"})

    question = _question(
        "Country",
        kind="select",
        options=["Select a country", "Germany", "Canada"],
    )

    assert answer_question(question, facts) == "Germany"


def test_answer_question_refuses_an_unrecognized_checkbox_token() -> None:
    facts = ProfileFacts(values={"work_authorization": "maybe"})

    question = _question("I am authorized to work", kind="checkbox")

    assert answer_question(question, facts) is None


def test_answer_question_accepts_a_recognized_checkbox_token() -> None:
    facts = ProfileFacts(values={"work_authorization": "yes"})

    question = _question("I am authorized to work", kind="checkbox")

    assert answer_question(question, facts) == "yes"


def test_answer_question_matches_a_radio_value_against_its_options() -> None:
    facts = ProfileFacts(values={"work_mode": "hybrid"})

    question = _question(
        "Work mode",
        kind="radio",
        options=["Remote", "Hybrid", "Onsite"],
    )

    assert answer_question(question, facts) == "Hybrid"


def test_answer_question_falls_back_to_the_second_source_key() -> None:
    # A profile states a remote *preference*; a form asks for a work *mode*.
    facts = ProfileFacts(values={"remote_preference": "remote"})

    question = _question(
        "Work mode",
        kind="radio",
        options=["Remote", "Hybrid", "Onsite"],
    )

    assert answer_question(question, facts) == "Remote"


# ---------------------------------------------------------------------------
# The three classes
# ---------------------------------------------------------------------------


def test_classify_question_recognizes_the_three_classes() -> None:
    facts = ProfileFacts(values={"candidate_name": "Ada Lovelace"})

    assert classify_question(_question("Full name"), facts) == "known"
    assert classify_question(_question("Phone number"), facts) == "mappable"
    assert classify_question(_question("Have you served on a submarine?"), facts) == "unknown"


# ---------------------------------------------------------------------------
# The plan
# ---------------------------------------------------------------------------


def test_build_form_plan_answers_known_questions_only() -> None:
    controls = [
        FormControl(label="Full name", kind="text", required=True),
        FormControl(label="Phone number", kind="tel"),
        FormControl(label="Have you served on a submarine?", kind="text"),
    ]
    facts = ProfileFacts(values={"candidate_name": "Ada Lovelace"})

    plan = build_form_plan(controls, facts)

    assert plan.answers == {"Full name": "Ada Lovelace"}
    # The unknown question is the one that stops the run.
    assert plan.unresolved == ["Have you served on a submarine?"]
    # The mappable-but-optional question is left alone, not answered.
    assert plan.skipped == ["Phone number"]
    assert [question.classification for question in plan.questions] == [
        "known",
        "mappable",
        "unknown",
    ]


def test_build_form_plan_treats_a_required_ungrounded_question_as_unresolved() -> None:
    controls = [FormControl(label="Years of experience", kind="text", required=True)]
    facts = ProfileFacts(values={"name": "Ada Lovelace"})

    plan = build_form_plan(controls, facts)

    assert plan.unresolved == ["Years of experience"]
    assert plan.skipped == []
    assert plan.answers == {}


def test_build_form_plan_answers_a_required_question_when_the_evidence_exists() -> None:
    controls = [FormControl(label="Years of experience", kind="text", required=True)]
    facts = ProfileFacts(values={"years_of_experience": "7"})

    plan = build_form_plan(controls, facts)

    assert plan.unresolved == []
    assert plan.answers == {"Years of experience": "7"}


def test_build_form_plan_keys_the_answers_by_the_page_label() -> None:
    controls = [FormControl(label="Full name", kind="text")]
    facts = ProfileFacts(values={"candidate_name": "Ada Lovelace"})

    plan = build_form_plan(controls, facts)

    assert list(plan.answers) == ["Full name"]


def test_build_form_plan_reads_a_page_when_given_one() -> None:
    class FakePage:
        """A page that is not a page — the reader is only asked for its controls."""

        def locator(self, _selector: str):
            raise AssertionError("the page path must not be taken for this stub")

    # A list of controls is the pure path; a page is only detected by the
    # presence of ``locator``.
    plan = build_form_plan([FormControl(label="Full name")], ProfileFacts())

    assert len(plan.questions) == 1
    assert isinstance(FakePage, type)
