"""WS-25c · Work eligibility **by country**, not one boolean.

The boards ask country-qualified authorization questions — measured on the
live corpus, "Are you authorized to work in the country for which you apply?"
is required on 12 listings across 1 board, and "Please select the country or
countries you anticipate working from" on 12 more. A single
``legally_authorized: bool`` cannot answer those: a candidate authorized in
the UK and not in the US must not have a blanket "yes" filled in for a US
posting, and filling it would be a **fabricated statement about their legal
status** on a form a human then submits.

So the model states eligibility **per country**, and this file pins the rules
that make it honest:

* a country is stored canonically or not at all (no free text, no typo);
* ``legally_authorized`` keeps meaning what it meant — the user's own blanket
  statement — and is never *derived* from the country list, because a
  candidate may state one without stating the other;
* an empty ``authorized_countries`` means "not stated", which is different
  from "stated, and the answer is none".
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from src.resume.application_profile import (
    ApplicationProfile,
    WorkAuthorizationInfo,
)


def test_a_country_list_is_stored_canonically() -> None:
    wa = WorkAuthorizationInfo(authorized_countries=["United States", "gb", "India"])
    assert wa.authorized_countries == ["US", "GB", "IN"]


def test_a_country_code_is_normalized_to_upper_case() -> None:
    assert WorkAuthorizationInfo(authorized_countries=["us"]).authorized_countries == ["US"]


def test_duplicate_countries_collapse_and_order_is_preserved() -> None:
    wa = WorkAuthorizationInfo(authorized_countries=["GB", "United Kingdom", "US"])
    assert wa.authorized_countries == ["GB", "US"]


def test_an_unrecognized_country_is_rejected_not_stored_as_free_text() -> None:
    """A closed set: "Wakanda" cannot become a country, or a form answer.

    A profile that stores free text in a country field cannot be reasoned
    about — the answer path compares codes — so the value is refused at the
    boundary rather than stored and silently never matching.
    """
    with pytest.raises(ValidationError):
        WorkAuthorizationInfo(authorized_countries=["Wakanda"])


def test_a_two_letter_typo_is_rejected() -> None:
    with pytest.raises(ValidationError):
        WorkAuthorizationInfo(authorized_countries=["XX"])


def test_eligibility_is_never_conflated_with_sponsorship() -> None:
    """Three distinct facts stay distinct (the WS-20 rule, kept).

    A candidate may be authorized today *and* need sponsorship for a future
    transfer, so setting one must not move the others.
    """
    wa = WorkAuthorizationInfo(
        legally_authorized=True,
        requires_sponsorship=True,
        authorized_countries=["GB"],
    )
    assert wa.legally_authorized is True
    assert wa.requires_sponsorship is True
    assert wa.authorized_countries == ["GB"]


def test_the_blanket_statement_is_never_derived_from_the_country_list() -> None:
    """Stating countries does not assert a blanket yes.

    ``legally_authorized`` is the user's own sentence about *anywhere*. If
    filling the list set it to ``True``, a form asking a plain "are you
    authorized to work?" would be answered "yes" from a list that says nothing
    about the country the form is for.
    """
    wa = WorkAuthorizationInfo(authorized_countries=["GB"])
    assert wa.legally_authorized is None


def test_no_countries_stated_is_not_the_same_as_none_authorized() -> None:
    """An empty list is "not stated"; False is "stated, and the answer is no"."""
    not_stated = WorkAuthorizationInfo()
    assert not_stated.authorized_countries == []
    assert not_stated.legally_authorized is None

    stated_no = WorkAuthorizationInfo(legally_authorized=False)
    assert stated_no.authorized_countries == []
    assert stated_no.legally_authorized is False


def test_the_country_list_is_bounded() -> None:
    with pytest.raises(ValidationError):
        WorkAuthorizationInfo(authorized_countries=["US"] * 60)


def test_the_application_profile_round_trips_the_country_list() -> None:
    profile = ApplicationProfile.model_validate(
        {
            "answers": {
                "work_authorization": {
                    "legally_authorized": True,
                    "authorized_countries": ["United States", "UK"],
                }
            }
        }
    )
    assert profile.answers.work_authorization.authorized_countries == ["US", "GB"]
    # The serialized form is the canonical one, so a stored profile reads back
    # the same way it was written.
    dumped = profile.model_dump()
    assert dumped["answers"]["work_authorization"]["authorized_countries"] == ["US", "GB"]


def test_eligibility_helper_answers_for_one_job_country() -> None:
    """The question the answer path asks: may this candidate work *here*?

    Three-valued on purpose. ``None`` is "the profile does not say", which is
    a different outcome from ``False`` ("says no") — the first must send the
    question to a human, the second may answer it.
    """
    wa = WorkAuthorizationInfo(authorized_countries=["US", "GB"])
    assert wa.may_work_in("US") is True
    assert wa.may_work_in("gb") is True
    assert wa.may_work_in("DE") is False
    # Nothing stated for that country at all.
    assert WorkAuthorizationInfo().may_work_in("US") is None
    # A country that is not a country states nothing.
    assert wa.may_work_in("XX") is None
    assert wa.may_work_in(None) is None


def test_the_blanket_yes_answers_a_country_with_no_country_list() -> None:
    """``legally_authorized=True`` with no list is a statement about *anywhere*.

    The user confirmed permission to work without narrowing it, so it answers
    a country-qualified question — and that is the only case in which a
    blanket value stands in for a per-country one.
    """
    wa = WorkAuthorizationInfo(legally_authorized=True)
    assert wa.may_work_in("US") is True
    # But an explicit list overrides the blanket value for a country it omits.
    narrowed = WorkAuthorizationInfo(legally_authorized=True, authorized_countries=["GB"])
    assert narrowed.may_work_in("GB") is True
    assert narrowed.may_work_in("US") is False


def test_the_blanket_no_answers_every_country() -> None:
    wa = WorkAuthorizationInfo(legally_authorized=False)
    assert wa.may_work_in("US") is False
    assert wa.may_work_in("DE") is False


def test_sponsorship_is_reported_for_a_country_the_candidate_cannot_work_in() -> None:
    """The companion question, and it stays separate.

    ``requires_sponsorship`` is the user's own answer; this helper only says
    whether it is *known*, never infers it from the country list.
    """
    wa = WorkAuthorizationInfo(authorized_countries=["GB"], requires_sponsorship=True)
    assert wa.sponsorship_stated() is True
    assert WorkAuthorizationInfo(authorized_countries=["GB"]).sponsorship_stated() is False
