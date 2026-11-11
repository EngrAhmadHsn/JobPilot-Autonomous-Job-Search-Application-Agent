"""WS-25b · The measured questions, and the taxonomy gaps they exposed.

The profile asks the user a **guessed** set of fields. The boards state
what they actually ask, and nothing recorded that — so the guess was
never checked against the evidence.

A probe on 2026-11-11 (12 live Greenhouse boards, 12 jobs each) found
**310 distinct labels across 1,455 occurrences**, and **10 of the 22
most-asked labels were unclassified — 51% of all occurrences**.

What this file tests:

* the store accumulates `times_seen` (the frequency is the whole point);
* the gap read ranks by frequency and excludes what the profile answers;
* a consent/EEO question is never offered as a gap to fill;
* the taxonomy classifies the ten labels the probe found unclassified —
  including `VeteranStatus`, which must be recognized as EEO rather than
  merely unknown.
"""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.db.base import Base
from src.db.form_questions import (
    FormQuestionDB,
    ObservedQuestion,
    question_gaps,
    question_id,
    record_questions,
)


@pytest.fixture()
def session_factory(tmp_path):
    engine = create_engine(f"sqlite:///{(tmp_path / 'q.db').as_posix()}")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)


def _observe(label: str, *, board: str = "stripe", category: str = "unknown", **kwargs):
    return ObservedQuestion(label=label, board=board, category=category, **kwargs)


# ------------------------------------------------------------------ store


def test_a_question_is_recorded_once_and_counted(session_factory):
    """`times_seen` is the measurement — it must accumulate."""
    record_questions([_observe("Cover Letter")], session_factory=session_factory)
    record_questions([_observe("Cover Letter")], session_factory=session_factory)
    record_questions([_observe("Cover Letter")], session_factory=session_factory)

    with session_factory() as session:
        rows = session.query(FormQuestionDB).all()
    assert len(rows) == 1
    assert rows[0].times_seen == 3


def test_the_same_question_twice_in_one_batch_accumulates(session_factory):
    """One sweep sees the same question on many jobs.

    `session.get` does not see a row that has not been flushed, so the
    second occurrence would try to insert the same id again — the exact
    failure the first live run produced (`UNIQUE constraint failed`).
    """
    record_questions(
        [_observe("Cover Letter"), _observe("Cover Letter"), _observe("Cover Letter")],
        session_factory=session_factory,
    )

    with session_factory() as session:
        rows = session.query(FormQuestionDB).all()
    assert len(rows) == 1
    assert rows[0].times_seen == 3


def test_two_boards_are_two_rows(session_factory):
    """The count is per board: a board that asks it is one board."""
    record_questions(
        [_observe("Cover Letter", board="stripe"), _observe("Cover Letter", board="figma")],
        session_factory=session_factory,
    )

    with session_factory() as session:
        rows = session.query(FormQuestionDB).all()
    assert len(rows) == 2
    assert {row.board for row in rows} == {"stripe", "figma"}


def test_the_label_is_stored_verbatim(session_factory):
    """The board's own wording is the evidence; normalizing it destroys it."""
    label = "Please select the country where you currently reside.\n"
    record_questions([_observe(label)], session_factory=session_factory)

    with session_factory() as session:
        rows = session.query(FormQuestionDB).all()
    assert rows[0].label == label
    # ...while the id is normalized, so the identity is stable.
    assert "\n" not in rows[0].id


def test_the_question_id_is_stable_across_whitespace(session_factory):
    """A trailing newline must not create a second row."""
    assert question_id("greenhouse", "stripe", "Cover Letter") == question_id(
        "greenhouse", "stripe", "  cover   letter \n"
    )


def test_the_latest_category_wins(session_factory):
    """A taxonomy improvement must not be frozen out by history."""
    record_questions(
        [_observe("VeteranStatus", category="unknown")], session_factory=session_factory
    )
    record_questions(
        [_observe("VeteranStatus", category="eeo_veteran")], session_factory=session_factory
    )

    with session_factory() as session:
        rows = session.query(FormQuestionDB).all()
    assert rows[0].category == "eeo_veteran"


def test_required_accumulates(session_factory):
    """A question required by any board that asks it is marked required."""
    record_questions([_observe("Cover Letter", required=False)], session_factory=session_factory)
    record_questions([_observe("Cover Letter", required=True)], session_factory=session_factory)

    with session_factory() as session:
        rows = session.query(FormQuestionDB).all()
    assert rows[0].required is True


# ------------------------------------------------------------------ gaps


def test_the_gaps_are_ranked_by_frequency(session_factory):
    """The most-asked question is the one worth asking about."""
    record_questions(
        [_observe("Rare Question", category="unknown")] * 1
        + [_observe("Common Question", category="unknown")] * 5,
        session_factory=session_factory,
    )

    gaps = question_gaps(session_factory=session_factory)
    assert gaps[0].label == "Common Question"
    assert gaps[0].times_seen == 5


def test_an_answered_question_is_not_a_gap(session_factory):
    """A question the profile answers needs nothing from the user."""
    from src.resume.profile import CandidateProfile, PersonalInformation

    profile = CandidateProfile(personal_information=PersonalInformation(email="t@example.com"))
    record_questions([_observe("Email", category="email")], session_factory=session_factory)

    gaps = question_gaps(profile, session_factory=session_factory)
    assert gaps == [], "the profile answers Email, so it is not a gap"


def test_an_unanswered_question_is_a_gap(session_factory):
    """A question the profile does not answer is what to ask about."""
    from src.resume.profile import CandidateProfile, PersonalInformation

    profile = CandidateProfile(personal_information=PersonalInformation(email="t@example.com"))
    record_questions(
        [_observe("Cover Letter", category="cover_letter")], session_factory=session_factory
    )

    gaps = question_gaps(profile, session_factory=session_factory)
    assert len(gaps) == 1
    assert gaps[0].coverage == "not_in_profile"


def test_a_consent_or_eeo_question_is_never_a_gap_to_fill(session_factory):
    """It is surfaced to a human, never asked of the profile as a field.

    Its `coverage` is `never_autofill`, which is not actionable, so it
    never reaches the profile screen as a prompt.
    """
    record_questions(
        [_observe("Gender", category="eeo_gender"), _observe("Race", category="eeo_race")],
        session_factory=session_factory,
    )

    gaps = question_gaps(session_factory=session_factory)
    assert gaps == []

    everything = question_gaps(session_factory=session_factory, include_answered=True)
    assert {gap.coverage for gap in everything} == {"never_autofill"}


def test_an_unclassified_question_is_actionable(session_factory):
    """An unrecognized label is a taxonomy gap worth surfacing.

    It is not silently dropped: it is the evidence that the taxonomy is
    incomplete, which is exactly what the measurement exists to show.
    """
    record_questions(
        [_observe("How did you hear about this job?", category="unknown")],
        session_factory=session_factory,
    )

    gaps = question_gaps(session_factory=session_factory)
    assert len(gaps) == 1
    assert gaps[0].coverage == "unclassified"
    assert gaps[0].is_actionable is True


def test_an_empty_store_yields_no_gaps(session_factory):
    """A fresh database is not an error."""
    assert question_gaps(session_factory=session_factory) == []


def test_the_board_count_is_reported(session_factory):
    """\"Asked by 2 of the boards you watch\" is the number the console shows."""
    record_questions(
        [
            _observe("Cover Letter", board="stripe", category="cover_letter"),
            _observe("Cover Letter", board="figma", category="cover_letter"),
        ],
        session_factory=session_factory,
    )

    gaps = question_gaps(session_factory=session_factory)
    assert len(gaps) == 1
    assert gaps[0].boards == 2


def test_the_limit_is_respected(session_factory):
    """The read is bounded, because it is a screen."""
    record_questions(
        [_observe(f"Question {i}", category="unknown") for i in range(30)],
        session_factory=session_factory,
    )

    assert len(question_gaps(session_factory=session_factory, limit=5)) == 5


# ------------------------------------------------- the taxonomy gaps (WS-25b)


@pytest.mark.parametrize(
    ("label", "expected"),
    [
        # The ten labels the live probe found unclassified.
        ("First Name", "candidate_first_name"),
        ("Last Name", "candidate_last_name"),
        ("Resume/CV", "resume"),
        ("Cover Letter", "cover_letter"),
        ("VeteranStatus", "eeo_veteran"),
        ("Preferred First Name", "candidate_first_name"),
        ("Latitude", "location_latitude"),
        ("Longitude", "location_longitude"),
        # Already classified before this workstream — a regression guard.
        ("Email", "email"),
        ("Phone", "phone"),
        ("Location", "location"),
        ("Gender", "eeo_gender"),
        ("Race", "eeo_race"),
        ("LinkedIn Profile", "linkedin_url"),
    ],
)
def test_the_measured_labels_now_classify(label, expected):
    """Every label the probe found mis-classified now resolves."""
    from src.applications.questions import classify_text

    assert classify_text(label).category.value == expected


def test_veteran_status_is_recognized_as_eeo():
    """The *reason* matters, not just the outcome.

    Before this fix "VeteranStatus" was `unknown`, which also leaves the
    question to a human — but the console could not tell "we must not
    answer this" from "we do not know what this is".
    """
    from src.applications.questions import NEVER_AUTOFILL, classify_text

    classification = classify_text("VeteranStatus")
    assert classification.category in NEVER_AUTOFILL


def test_a_split_name_has_an_answer_source():
    """The profile stores one name; both questions must find it."""
    from src.applications.questions import CATEGORY_FACT_KEYS, QuestionCategory

    first = CATEGORY_FACT_KEYS[QuestionCategory.CANDIDATE_FIRST_NAME]
    last = CATEGORY_FACT_KEYS[QuestionCategory.CANDIDATE_LAST_NAME]

    assert first, "First Name has no answer source"
    assert last, "Last Name has no answer source"
    assert "candidate_name" in first or "name" in first
    assert "candidate_name" in last or "name" in last


def test_the_generic_name_rule_does_not_swallow_the_split_name():
    """ "First Name" must not classify as CANDIDATE_NAME.

    The split categories were added *before* the generic rule in the
    precedence order for exactly this reason: the generic rule matches
    "your name", and "First Name" contains "name".
    """
    from src.applications.questions import classify_text

    assert classify_text("First Name").category.value != "candidate_name"
    assert classify_text("Last Name").category.value != "candidate_name"
    # ...while a genuine full-name question still resolves to it.
    assert classify_text("Full Name").category.value == "candidate_name"


def test_the_location_coordinates_are_separate_from_the_location():
    """Greenhouse needs all three; they are different questions."""
    from src.applications.questions import classify_text

    assert classify_text("Latitude").category.value == "location_latitude"
    assert classify_text("Longitude").category.value == "location_longitude"
    assert classify_text("Location").category.value == "location"
