"""WS-25c · A country-qualified authorization answer, never a blanket one.

This is the whole point of the workstream. The boards ask:

* "Are you authorized to work **in the country for which you apply**?"
  (required, 12 live listings)
* "Are you authorized to work **in the location(s) you selected**?"
  (required, 12 live listings)
* "Please select the **country or countries** you anticipate working from"
  (required, 12 live listings)

Before this, the fact map emitted ``legally_authorized: "yes"`` from the
profile's single boolean **without knowing the job**. So a candidate who
stated "authorized in the UK" had a blanket "yes" filled into a US posting's
authorization question — a fabricated statement about their legal right to
work, on a form a human then submits. These tests pin that it cannot happen:
the answer is derived from the **job's country**, and where the job's country
or the candidate's eligibility is unknown, the question goes to a human.

The three-valued outcome is what makes this honest:

* known eligible -> answer ``yes``
* known not eligible -> answer ``no``
* not stated (either side) -> **no answer**, and the question blocks
"""

from __future__ import annotations

import pytest

from src.applications.form import facts_from_profile
from src.resume.application_profile import ApplicationProfile
from src.resume.profile import CandidateProfile, PersonalInformation


def _profile(
    *,
    countries: list[str] | None = None,
    legally_authorized: bool | None = None,
    requires_sponsorship: bool | None = None,
) -> CandidateProfile:
    return CandidateProfile(
        personal_information=PersonalInformation(name="Ada Lovelace", email="ada@example.com"),
        application_profile=ApplicationProfile.model_validate(
            {
                "answers": {
                    "work_authorization": {
                        "legally_authorized": legally_authorized,
                        "requires_sponsorship": requires_sponsorship,
                        "authorized_countries": countries or [],
                    }
                }
            }
        ),
    )


# --------------------------------------------------------------------------
# The country-qualified fact
# --------------------------------------------------------------------------


def test_eligibility_in_the_jobs_country_is_emitted_when_known() -> None:
    profile = _profile(countries=["US", "GB"])
    facts = facts_from_profile(profile, job_country="US")
    assert facts.get("legally_authorized") == "yes"


def test_ineligibility_in_the_jobs_country_is_emitted_as_no() -> None:
    """An explicit "no" is an answer, and it is the candidate's own.

    Answering "no" is not a fabrication: the candidate stated the countries
    they may work in, and this one is not among them. Saying so lets the form
    be filled and the application proceed or stop on its merits, which is
    better than a wrong "yes".
    """
    profile = _profile(countries=["GB"])
    facts = facts_from_profile(profile, job_country="US")
    assert facts.get("legally_authorized") == "no"


def test_a_us_posting_is_not_answered_yes_from_a_uk_only_profile() -> None:
    """The exact fabrication this workstream exists to prevent."""
    profile = _profile(countries=["GB"], legally_authorized=True)
    us_facts = facts_from_profile(profile, job_country="US")
    assert us_facts.get("legally_authorized") != "yes"

    uk_facts = facts_from_profile(profile, job_country="GB")
    assert uk_facts.get("legally_authorized") == "yes"


def test_an_unknown_job_country_yields_no_eligibility_fact() -> None:
    """No country on the posting means no country-qualified answer.

    The alternative — falling back to the blanket boolean — is precisely the
    fabrication, so the fact is withheld and the question becomes a human's.
    """
    profile = _profile(countries=["GB"], legally_authorized=True)
    facts = facts_from_profile(profile, job_country=None)
    assert "legally_authorized" not in facts


def test_an_unknown_job_country_still_allows_a_blanket_statement_to_stand() -> None:
    """A blanket answer is the user's own sentence about anywhere.

    When the profile states permission *without* narrowing it to countries,
    there is no narrower fact to contradict, and withholding it would make
    the answer path ask a question the candidate already answered.
    """
    profile = _profile(legally_authorized=True)
    facts = facts_from_profile(profile, job_country=None)
    assert facts.get("legally_authorized") == "yes"


def test_nothing_stated_yields_no_fact_for_a_known_country() -> None:
    profile = _profile()
    facts = facts_from_profile(profile, job_country="US")
    assert "legally_authorized" not in facts


# --------------------------------------------------------------------------
# Sponsorship stays its own question
# --------------------------------------------------------------------------


def test_sponsorship_is_emitted_independently_of_eligibility() -> None:
    profile = _profile(countries=["GB"], requires_sponsorship=True)
    facts = facts_from_profile(profile, job_country="GB")
    assert facts.get("legally_authorized") == "yes"
    assert facts.get("requires_sponsorship") == "yes"


def test_a_sponsorship_answer_is_never_inferred() -> None:
    """Not from the country list, not from eligibility."""
    profile = _profile(countries=["GB"])
    facts = facts_from_profile(profile, job_country="GB")
    assert "requires_sponsorship" not in facts


# --------------------------------------------------------------------------
# The job's country is resolved from the listing
# --------------------------------------------------------------------------


def test_the_job_country_is_resolved_from_a_location_string() -> None:
    """The prepare path knows a job's location, not its country."""
    from src.applications.form import resolve_job_country

    assert resolve_job_country("San Francisco, CA") == "US"
    assert resolve_job_country("London, United Kingdom") == "GB"
    assert resolve_job_country("Remote") is None
    assert resolve_job_country(None) is None


def test_a_call_with_no_job_country_still_emits_the_resume_derived_facts() -> None:
    """Backwards compatibility: the caller that has no job keeps working.

    ``facts_from_profile(profile)`` is the WS-08 signature and other callers
    use it. It must still return the facts it returned before — the
    résumé-derived ones and a **blanket** authorization statement, which needs
    no country to apply.

    Note the profile here states a blanket flag and *no* country list. A
    narrowed profile is deliberately different: with no job country its
    authorization fact is withheld (see the test above), because a list
    cannot be applied to a country nobody named.
    """
    facts = facts_from_profile(_profile(legally_authorized=True))
    assert facts.get("name") == "Ada Lovelace"
    assert facts.get("email") == "ada@example.com"
    assert facts.get("legally_authorized") == "yes"


@pytest.mark.parametrize(
    ("location", "expected"),
    [
        ("Berlin, Germany", "DE"),
        ("Bengaluru, India", "IN"),
        ("Toronto, Canada", "CA"),
        ("Singapore", "SG"),
        ("Remote - USA", "US"),
        ("Dublin, Ireland", "IE"),
    ],
)
def test_country_resolution_over_real_corpus_shapes(location, expected) -> None:
    from src.applications.form import resolve_job_country

    assert resolve_job_country(location) == expected
