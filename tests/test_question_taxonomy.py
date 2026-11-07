"""WS-20 · the application-question taxonomy and value transforms."""

from __future__ import annotations

from src.applications.form import (
    FormControl,
    FormQuestion,
    ProfileFacts,
    answer_question,
    build_form_plan,
    classify_question,
)
from src.applications.questions import (
    AnswerType,
    QuestionCategory,
    classify_text,
    convert_pay_period,
    format_notice_minutes,
    format_salary,
    notice_period_answer,
    notice_period_days,
)
from src.resume.application_profile import (
    ApplicationAnswers,
    ApplicationProfile,
    Compensation,
    JobSearchPreferences,
    NoticePeriod,
    ProfessionalInfo,
    WorkAuthorizationInfo,
)
from src.resume.profile import CandidateProfile, PersonalInformation


def _facts(profile: CandidateProfile) -> ProfileFacts:
    return ProfileFacts.from_profile(profile)


def _profile_with(
    answers: ApplicationAnswers | None = None, prefs: JobSearchPreferences | None = None
) -> CandidateProfile:
    app = ApplicationProfile(
        professional=ProfessionalInfo(total_experience_years=6, seniority_level="senior"),
        preferences=prefs or JobSearchPreferences(),
        answers=answers or ApplicationAnswers(),
    )
    return CandidateProfile(
        personal_information=PersonalInformation(name="Ada", email="ada@example.com"),
        application_profile=app,
    )


# -- classification -----------------------------------------------------------


def test_sponsorship_and_authorization_are_distinct():
    sponsor = classify_text("Will you now or in the future require sponsorship?")
    auth = classify_text("Are you authorized to work in the United States?")
    assert sponsor.category is QuestionCategory.VISA_SPONSORSHIP
    assert auth.category is QuestionCategory.WORK_AUTHORIZATION
    assert sponsor.category is not auth.category


def test_citizenship_does_not_answer_authorization():
    citizen = classify_text("What is your citizenship status?")
    assert citizen.category is QuestionCategory.CITIZENSHIP_STATUS


def test_current_and_desired_salary_are_distinct():
    assert classify_text("Current salary").category is QuestionCategory.CURRENT_SALARY
    assert classify_text("Desired salary").category is QuestionCategory.DESIRED_SALARY


def test_total_vs_skill_experience():
    assert classify_text("How many years of professional experience do you have?").category is (
        QuestionCategory.TOTAL_EXPERIENCE
    )
    assert classify_text("How many years of experience with Python?").category is (
        QuestionCategory.SKILL_EXPERIENCE
    )


def test_notice_and_availability():
    assert classify_text("What is your notice period?").category is QuestionCategory.NOTICE_PERIOD
    assert classify_text("Earliest start date").category is QuestionCategory.AVAILABILITY_DATE


def test_eeo_categories_are_recognized_but_never_autofilled():
    for label, category in (
        ("Race/ethnicity", QuestionCategory.EEO_RACE),
        ("Gender", QuestionCategory.EEO_GENDER),
        ("Disability status", QuestionCategory.EEO_DISABILITY),
        ("Veteran status", QuestionCategory.EEO_VETERAN),
    ):
        assert classify_text(label).category is category
        question = FormQuestion(label=label)
        # No fact can ground these: the answer is always "ask a human".
        assert answer_question(question, ProfileFacts(values={"race": "x"})) is None
        assert classify_question(question, ProfileFacts()) == "unknown"


def test_attestations_are_never_autofilled_even_when_answered_in_facts():
    facts = ProfileFacts(values={"i_agree_to_terms": "yes"})
    question = FormQuestion(label="I agree to the terms and conditions")
    assert answer_question(question, facts) is None
    assert classify_question(question, facts) == "unknown"


def test_low_confidence_or_unknown_label_is_unknown():
    assert classify_text("Favorite colour").category is QuestionCategory.UNKNOWN


def test_authorization_answer_type_is_boolean():
    assert classify_text("Are you authorized to work?").answer_type is AnswerType.BOOLEAN


# -- answers and provenance ---------------------------------------------------


def test_authorization_is_answered_from_confirmed_work_authorization():
    profile = _profile_with(
        ApplicationAnswers(work_authorization=WorkAuthorizationInfo(legally_authorized=True))
    )
    question = FormQuestion(
        label="Are you authorized to work?", kind="radio", options=["Yes", "No"]
    )
    assert answer_question(question, _facts(profile)) == "Yes"


def test_sponsorship_is_answered_separately_from_authorization():
    # Authorized today, still needs sponsorship later — the two must not merge.
    profile = _profile_with(
        ApplicationAnswers(
            work_authorization=WorkAuthorizationInfo(
                legally_authorized=True, requires_sponsorship=True
            )
        )
    )
    facts = _facts(profile)
    auth = FormQuestion(label="Are you authorized to work?", kind="radio", options=["Yes", "No"])
    sponsor = FormQuestion(
        label="Will you require sponsorship?", kind="radio", options=["Yes", "No"]
    )
    assert answer_question(auth, facts) == "Yes"
    assert answer_question(sponsor, facts) == "Yes"


def test_total_experience_does_not_answer_skill_experience():
    profile = _profile_with()
    # The profile confirms only total years; a skill-specific question is not
    # answerable from it.
    question = FormQuestion(label="How many years of experience with Rust?")
    assert answer_question(question, _facts(profile)) is None


def test_desired_salary_does_not_answer_current_salary():
    profile = _profile_with(
        ApplicationAnswers(
            compensation=Compensation(
                expected_salary=120000, expected_currency="usd", expected_period="annual"
            )
        )
    )
    facts = _facts(profile)
    desired = FormQuestion(label="Desired salary")
    current = FormQuestion(label="Current salary")
    assert answer_question(desired, facts) is not None
    assert answer_question(current, facts) is None


def test_notice_period_of_zero_is_immediate_and_answered():
    profile = _profile_with(ApplicationAnswers(notice=NoticePeriod(notice_days=0)))
    facts = _facts(profile)
    assert facts.get("notice_period_days") == "0"
    assert answer_question(FormQuestion(label="Notice period"), facts) == "0"


def test_provenance_is_user_confirmed_for_application_answers():
    profile = _profile_with(
        ApplicationAnswers(work_authorization=WorkAuthorizationInfo(legally_authorized=True))
    )
    plan = build_form_plan(
        [FormControl(label="Are you authorized to work?", kind="radio", options=["Yes", "No"])],
        _facts(profile),
    )
    assert plan.answer_sources["Are you authorized to work?"] == "user_confirmed"


def test_resume_fact_provenance_is_resume_derived():
    profile = CandidateProfile(personal_information=PersonalInformation(email="a@b.com"))
    plan = build_form_plan([FormControl(label="Email")], _facts(profile))
    assert plan.answer_sources["Email"] == "resume_derived"


# -- value transforms ---------------------------------------------------------


def test_salary_currency_and_period_are_explicit():
    assert format_salary(120000, "usd", "annual") == "120000 USD per annual"


def test_pay_period_conversion_is_exact_or_refused():
    assert convert_pay_period(120000, "annual", "monthly") == (
        10000.0,
        "converted annual to monthly at 1:12 periods",
    )
    # Different currency is out of scope (no exchange rate is invented).
    assert convert_pay_period(1000, "annual", "annual") == (1000, "")


def test_notice_period_formatting_handles_zero_and_exact_units():
    assert format_notice_minutes(0) == "Immediate"
    assert format_notice_minutes(7) == "1 week"
    assert format_notice_minutes(14) == "2 weeks"
    assert format_notice_minutes(30) == "1 month"
    assert format_notice_minutes(45) == "45 days"


def test_notice_period_week_conversion_does_not_floor():
    assert notice_period_answer(7, "weeks") == "1"
    assert notice_period_answer(14, "weeks") == "2"
    # 15 days is not exactly two weeks — refuse rather than misreport.
    assert notice_period_answer(15, "weeks") is None
    assert notice_period_answer(0, "days") == "0"


def test_notice_days_preserve_immediate_and_unset():
    assert notice_period_days(None, immediate=True) == 0
    assert notice_period_days(None, immediate=None) is None
    assert notice_period_days(30) == 30
