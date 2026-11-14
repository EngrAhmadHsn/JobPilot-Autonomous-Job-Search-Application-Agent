"""WS-25c · The posting's country reaches the answer, end to end.

The pieces are individually tested; this file pins that they are **connected**
— because the whole defect was a disconnected piece. ``authorized_countries``
existed in the model since WS-20 and nothing ever read it, so the profile could
state "authorized in the UK" and the prepare path still emitted a blanket
"yes" for a US posting.

The chain: the prepare route is given a ``job_url``; the corpus stores that
listing's location; the location resolves to a country; the country qualifies
the authorization fact; and the form plan turns that into a verdict. Every link
is exercised here over a real in-memory database, and the failure that matters
is pinned directly: **a UK-only candidate must not be answered "yes" for a US
posting, and must not be answered at all when the posting's country is
unknown.**
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.applications.form import facts_from_profile
from src.db.base import Base
from src.db.jobs import JobDB, location_for_application_url
from src.resume.application_profile import ApplicationProfile, WorkAuthorizationInfo
from src.resume.profile import CandidateProfile, PersonalInformation


@pytest.fixture()
def factory():
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    yield sessionmaker(autocommit=False, autoflush=False, bind=engine)
    engine.dispose()


def _store_listing(factory, *, url: str, location: str) -> None:
    with factory() as session:
        session.add(
            JobDB(
                id=f"greenhouse:{url}",
                source="greenhouse",
                source_job_id=url,
                title="Backend Engineer",
                company="Acme",
                location=location,
                application_url=url,
            )
        )
        session.commit()


def _uk_only_profile() -> CandidateProfile:
    return CandidateProfile(
        personal_information=PersonalInformation(name="Ada Lovelace"),
        application_profile=ApplicationProfile.model_validate(
            {
                "answers": {
                    "work_authorization": {
                        "legally_authorized": True,
                        "requires_sponsorship": False,
                        "authorized_countries": ["GB"],
                    }
                }
            }
        ),
    )


# --------------------------------------------------------------------------
# The corpus lookup
# --------------------------------------------------------------------------


def test_the_listing_location_is_read_by_application_url(factory) -> None:
    _store_listing(factory, url="https://boards.greenhouse.io/acme/jobs/1", location="London, UK")
    location = location_for_application_url(
        "https://boards.greenhouse.io/acme/jobs/1", session_factory=factory
    )
    assert location == "London, UK"


def test_an_unknown_url_yields_no_location(factory) -> None:
    """A posting we never ingested has no stored country — and says so.

    Returning a default here would let an authorization answer be derived from
    nothing, so the absence is propagated and the caller withholds the answer.
    """
    _store_listing(factory, url="https://boards.greenhouse.io/acme/jobs/1", location="London, UK")
    assert (
        location_for_application_url("https://example.invalid/never-seen", session_factory=factory)
        is None
    )
    assert location_for_application_url(None, session_factory=factory) is None
    assert location_for_application_url("", session_factory=factory) is None


def test_a_listing_with_no_location_yields_none(factory) -> None:
    _store_listing(factory, url="https://boards.greenhouse.io/acme/jobs/2", location="")
    assert (
        location_for_application_url(
            "https://boards.greenhouse.io/acme/jobs/2", session_factory=factory
        )
        is None
    )


# --------------------------------------------------------------------------
# The chain, end to end
# --------------------------------------------------------------------------


def test_a_us_posting_is_not_answered_yes_for_a_uk_only_candidate(factory) -> None:
    """The defect, over the real chain, with the real tables.

    This is the assertion the whole workstream exists for. Before WS-25c the
    fact map never saw the job, so this scenario produced
    ``legally_authorized="yes"`` on a US authorization question.
    """
    url = "https://boards.greenhouse.io/acme/jobs/us-1"
    _store_listing(factory, url=url, location="San Francisco, CA")

    location = location_for_application_url(url, session_factory=factory)
    from src.applications.form import resolve_job_country

    country = resolve_job_country(location)
    assert country == "US"

    facts = facts_from_profile(_uk_only_profile(), job_country=country)
    assert facts.get("legally_authorized") == "no"
    assert facts.get("legally_authorized") != "yes"


def test_the_same_candidate_is_answered_yes_for_a_uk_posting(factory) -> None:
    """The other half: the answer follows the posting, not the candidate."""
    url = "https://boards.greenhouse.io/acme/jobs/gb-1"
    _store_listing(factory, url=url, location="London, United Kingdom")

    from src.applications.form import resolve_job_country

    location = location_for_application_url(url, session_factory=factory)
    country = resolve_job_country(location)
    assert country == "GB"

    facts = facts_from_profile(_uk_only_profile(), job_country=country)
    assert facts.get("legally_authorized") == "yes"


def test_an_ambiguous_location_withholds_the_answer(factory) -> None:
    """ "Remote" is not a country, so no country-qualified answer is given.

    The corpus stores "Remote" 84 times and "N/A" more than that. Each one is
    a posting whose authorization question must reach a human.
    """
    url = "https://boards.greenhouse.io/acme/jobs/remote-1"
    _store_listing(factory, url=url, location="Remote")

    from src.applications.form import resolve_job_country

    location = location_for_application_url(url, session_factory=factory)
    assert resolve_job_country(location) is None

    facts = facts_from_profile(_uk_only_profile(), job_country=None)
    assert "legally_authorized" not in facts


# --------------------------------------------------------------------------
# The verdict the plan produces
# --------------------------------------------------------------------------

#: The exact label the measurement found on the live corpus, required on 12
#: listings across 1 board. The plan is asked about **this** wording, because
#: a label that does not classify would make the test pass for the wrong
#: reason (an unclassified question is a gap, not an answer).
_AUTHORIZATION_LABEL = "Are you authorized to work in the country for which you apply?"


@dataclass
class _Question:
    """The shape ``build_question_plan`` reads off a board's question."""

    label: str = _AUTHORIZATION_LABEL
    required: bool = True
    block: str = "questions"
    kind: str = "checkbox"
    options: tuple[str, ...] = ()
    field_names: tuple[str, ...] = ("question_1",)
    needs_consent: bool = False


@dataclass
class _Schema:
    all_questions: list[_Question]


def test_the_question_becomes_answerable_for_a_country_the_candidate_can_work_in() -> None:
    from src.applications.form_plan import VERDICT_ANSWERABLE, build_question_plan

    facts = facts_from_profile(_uk_only_profile(), job_country="GB")
    plans = build_question_plan(_Schema([_Question()]), facts)
    assert plans[0].verdict == VERDICT_ANSWERABLE
    assert plans[0].answer_from == "legally_authorized"


def test_the_question_blocks_when_the_country_is_unknown() -> None:
    """The honest outcome: a required question nobody can answer stops the flow.

    It does not get a fabricated answer, and it does not get silently filled
    from the blanket boolean.
    """
    from src.applications.form_plan import VERDICT_NEEDS_HUMAN, build_question_plan

    facts = facts_from_profile(_uk_only_profile(), job_country=None)
    plans = build_question_plan(_Schema([_Question()]), facts)
    assert plans[0].verdict == VERDICT_NEEDS_HUMAN
    assert plans[0].answer_from is None


def test_the_question_is_answerable_no_for_a_country_the_candidate_cannot_work_in() -> None:
    """A stated "no" is answerable — it is the candidate's own answer.

    The agent fills "no" rather than blocking, because the candidate did state
    which countries they may work in and this one is not among them. Blocking
    here would ask a human for an answer the profile already holds.
    """
    from src.applications.form_plan import VERDICT_ANSWERABLE, build_question_plan

    facts = facts_from_profile(_uk_only_profile(), job_country="US")
    plans = build_question_plan(_Schema([_Question()]), facts)
    assert plans[0].verdict == VERDICT_ANSWERABLE
    assert facts.get("legally_authorized") == "no"


# --------------------------------------------------------------------------
# Nothing else regressed
# --------------------------------------------------------------------------


def test_a_profile_with_no_application_profile_still_yields_resume_facts() -> None:
    profile = CandidateProfile(
        personal_information=PersonalInformation(name="Ada Lovelace", email="ada@example.com"),
    )
    facts = facts_from_profile(profile, job_country="US")
    assert facts.get("name") == "Ada Lovelace"
    assert facts.get("email") == "ada@example.com"
    assert "legally_authorized" not in facts


def test_the_model_accepts_an_already_canonical_list_unchanged() -> None:
    wa = WorkAuthorizationInfo(authorized_countries=["US", "GB"])
    assert wa.authorized_countries == ["US", "GB"]
