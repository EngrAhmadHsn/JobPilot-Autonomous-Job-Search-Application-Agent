"""WS-25b · The coverage map must know every category the taxonomy classifies.

``CATEGORY_FACT_KEYS`` (src/applications/questions.py) says which fact answers
each category; ``_CATEGORY_PROFILE_FIELDS`` (src/db/form_questions.py) says
which profile field proves the profile has it. They drifted: the split name
and the coordinates were added to the taxonomy in WS-25b and to the first
map only. A profile carrying "Ada Lovelace" therefore read First Name as
``not_in_profile`` — the state the console renders as "you should answer
this" — and would have prompted for a name the profile holds.

Measured on the live corpus: First Name is asked 30 times across 3 boards,
Last Name 30, and near the top of the ranked gaps. A profile that answers
both was shown both as gaps.
"""

from __future__ import annotations

import pytest

from src.applications.questions import CATEGORY_FACT_KEYS, QuestionCategory
from src.db.form_questions import _answered_categories, _coverage_for
from src.resume.profile import CandidateProfile


def _profile(**personal) -> CandidateProfile:
    return CandidateProfile.model_validate(
        {
            "personal_information": {"name": "Ada Lovelace", **personal},
            "summary": "Engineer.",
            "skills": ["Python", "FastAPI"],
            "experience": [],
            "education": [],
        }
    )


def test_a_named_profile_answers_the_split_name() -> None:
    """The split name is answered by the stored full name.

    ``CATEGORY_FACT_KEYS`` already reads ``candidate_name``/``name`` for both
    halves — the split happens in the answer, not in the fact lookup — so a
    profile with only a full name answers both questions. The coverage map
    has to agree, or the gap read contradicts the answer path.
    """
    answered = _answered_categories(_profile(email="ada@example.com"))
    for category in ("candidate_name", "candidate_first_name", "candidate_last_name"):
        assert _coverage_for(category, answered) == "answered", category


def test_a_profile_with_skills_answers_the_skills_question() -> None:
    answered = _answered_categories(_profile())
    assert _coverage_for("skills", answered) == "answered"


def test_a_profile_with_an_employment_type_answers_that_question() -> None:
    profile = CandidateProfile.model_validate(
        {
            "personal_information": {"name": "Ada Lovelace"},
            "work_preferences": {"employment_types": ["full-time"]},
            "experience": [],
        }
    )
    answered = _answered_categories(profile)
    assert _coverage_for("employment_type", answered) == "answered"


def test_coordinates_stay_a_gap_because_no_profile_field_holds_them() -> None:
    """Honest, not fixed: the profile has a location string, no coordinates.

    The engine cannot invent a latitude, so the question stays a real gap —
    this test pins that the coverage map does not claim otherwise.
    """
    answered = _answered_categories(_profile(location="London"))
    assert _coverage_for("location", answered) == "answered"
    assert _coverage_for("location_latitude", answered) == "not_in_profile"
    assert _coverage_for("location_longitude", answered) == "not_in_profile"


@pytest.mark.parametrize("category", [c.value for c in QuestionCategory])
def test_every_resolvable_category_has_a_coverage_verdict(category: str) -> None:
    """A category the taxonomy can resolve must not silently fall through.

    ``_coverage_for`` has three real verdicts — ``answered``,
    ``not_in_profile`` and ``never_autofill`` — plus ``unclassified`` for a
    category the taxonomy does not know. A category with fact keys and no
    coverage entry is not "unknown"; it is a category the map forgot, and
    the console reads it as a prompt.
    """
    resolved = QuestionCategory(category)
    if category == "unknown" or not CATEGORY_FACT_KEYS.get(resolved):
        pytest.skip(f"{category} has no fact-key mapping")
    answered = _answered_categories(_profile(email="ada@example.com", phone="+1"))
    verdict = _coverage_for(category, answered)
    assert verdict != "unclassified", f"{category} has fact keys but no coverage entry"
