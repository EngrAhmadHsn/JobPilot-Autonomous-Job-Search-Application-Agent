"""WS-21: the preference merge — a confirmed value wins, a cleared one stays cleared.

The defect these tests pin down: the engine overrode only *truthy* confirmed
values, so clearing a preference (remote → null, a list → []) silently
resurrected the résumé's value, and the résumé's verbatim ``min_salary`` beat
the user's confirmed expected salary — the opposite of the merge's own
docstring.
"""

from __future__ import annotations

from src.matching.engine import _effective_preferences
from src.resume.application_profile import (
    ApplicationAnswers,
    ApplicationProfile,
    Compensation,
    JobSearchPreferences,
)
from src.resume.profile import CandidateProfile, WorkPreferences


def make_profile(
    *,
    resume: WorkPreferences | None = None,
    application: ApplicationProfile | None = None,
) -> CandidateProfile:
    return CandidateProfile(
        work_preferences=resume or WorkPreferences(),
        application_profile=application or ApplicationProfile(),
    )


def test_missing_application_profile_returns_the_resume():
    resume = WorkPreferences(remote_preference="hybrid", preferred_locations=["Berlin"])
    merged = _effective_preferences(make_profile(resume=resume))
    assert merged.remote_preference == "hybrid"
    assert merged.preferred_locations == ["Berlin"]


def test_a_confirmed_clear_is_not_resurrected():
    """The user removed their preferences; the résumé must not put them back."""
    profile = make_profile(
        resume=WorkPreferences(
            remote_preference="remote",
            preferred_locations=["Berlin"],
            employment_types=["full-time"],
        ),
        application=ApplicationProfile(
            preferences=JobSearchPreferences(),  # all cleared
            confirmed_fields=["preferences"],
        ),
    )
    merged = _effective_preferences(profile)
    assert merged.remote_preference is None
    assert merged.preferred_locations == []
    assert merged.employment_types == []


def test_a_confirmed_value_wins_over_the_resume():
    profile = make_profile(
        resume=WorkPreferences(remote_preference="onsite", preferred_locations=["Berlin"]),
        application=ApplicationProfile(
            preferences=JobSearchPreferences(
                remote_preference="remote", preferred_locations=["Remote"]
            ),
            confirmed_fields=["preferences"],
        ),
    )
    merged = _effective_preferences(profile)
    assert merged.remote_preference == "remote"
    assert merged.preferred_locations == ["Remote"]


def test_legacy_saves_keep_the_ws20_semantics():
    """A pre-WS-21 save has no group marker: truthy wins, empty does not clear."""
    profile = make_profile(
        resume=WorkPreferences(remote_preference="remote", preferred_locations=["Berlin"]),
        application=ApplicationProfile(
            preferences=JobSearchPreferences(remote_preference=None, preferred_locations=["Oslo"]),
            confirmed_fields=[],  # no marker
        ),
    )
    merged = _effective_preferences(profile)
    # The empty confirmed remote does NOT clear the résumé's value…
    assert merged.remote_preference == "remote"
    # …and the truthy confirmed location does override.
    assert merged.preferred_locations == ["Oslo"]


def test_a_confirmed_salary_beats_the_resume_min_salary():
    profile = make_profile(
        resume=WorkPreferences(min_salary="$80,000"),
        application=ApplicationProfile(
            answers=ApplicationAnswers(
                compensation=Compensation(expected_salary=120000, expected_currency="USD")
            ),
            confirmed_fields=["answers.compensation"],
        ),
    )
    merged = _effective_preferences(profile)
    assert merged.min_salary == "USD 120000"


def test_a_confirmed_empty_salary_is_no_floor_not_the_old_one():
    profile = make_profile(
        resume=WorkPreferences(min_salary="$80,000"),
        application=ApplicationProfile(
            answers=ApplicationAnswers(compensation=Compensation()),
            confirmed_fields=["answers.compensation"],
        ),
    )
    assert _effective_preferences(profile).min_salary is None


def test_without_the_marker_the_ws20_salary_rule_applies():
    """Pre-WS-21 parity: the résumé's verbatim floor outranks an unmarked expectation."""
    profile = make_profile(
        resume=WorkPreferences(min_salary="$80,000"),
        application=ApplicationProfile(
            answers=ApplicationAnswers(
                compensation=Compensation(expected_salary=120000, expected_currency="USD")
            ),
            confirmed_fields=[],
        ),
    )
    assert _effective_preferences(profile).min_salary == "$80,000"
