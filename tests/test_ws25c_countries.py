"""WS-25c · The country a job is in, and the countries a candidate may work in.

Why this exists: the boards ask **country-qualified** authorization questions
and the measurement says they are common and required — "Are you authorized to
work in the country for which you apply?" (12 listings, required), "Please
select the country or countries you anticipate working from" (12, required).
A single ``legally_authorized: bool`` cannot answer those honestly: a candidate
authorized in the UK and not in the US must not have a blanket "yes" filled in
for a US posting. So the answer has to be a function of the job's country,
which means resolving the country out of free-text locations.

The tests below are grouped by the failure each defends:

* **the collision** — ``"San Francisco, CA"`` is California, not Canada.
  A naive reader mis-resolved **1,004 listings** on the live corpus toward a
  country the posting is not in (measured 2026-11-13), and a wrong legal
  answer is the one error this must never make.
* **honest ``None``** — ``"Remote"``, ``"Hybrid"``, ``"N/A"`` and bare initials
  state no country, so nothing may be answered from them.
* **multi-country** — ``"Milan OR Madrid"`` is two countries, and a
  single-answer API is the wrong shape for it.
"""

from __future__ import annotations

import pytest

from src.applications.countries import (
    COUNTRIES,
    canonicalize_countries,
    countries_in,
    country_name,
    is_known_country,
    normalize_country,
    resolve_country,
)

# --------------------------------------------------------------------------
# The collision: a bare two-letter code is a US state inside a longer location
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("location", "expected"),
    [
        # Every one of these was read as the wrong COUNTRY by the naive
        # version: CA->Canada, IL->Israel, IN->India, DE->Germany, AR->
        # Argentina, CO->Colombia, ID->Indonesia, MA->Morocco.
        ("San Francisco, CA", "US"),
        ("Chicago, IL", "US"),
        ("Indianapolis, IN", "US"),
        ("Denver, CO", "US"),
        ("Wilmington, DE", "US"),
        ("Little Rock, AR", "US"),
        ("Boise, ID", "US"),
        ("Boston, MA", "US"),
        # The same codes DO mean a country when the fragment is the whole
        # location, or where the code is unambiguous.
        ("CA", "CA"),
        ("IN", "IN"),
        ("DE", "DE"),
        ("MA", "MA"),
    ],
)
def test_a_state_code_in_a_longer_location_is_not_a_country(location, expected):
    assert resolve_country(location) == expected


def test_a_state_name_states_the_united_states() -> None:
    for location in ("Seattle, Washington", "Dallas, Texas", "Portland, Oregon"):
        assert resolve_country(location) == "US", location


def test_a_plain_us_city_states_the_united_states() -> None:
    # 847 listings say "San Francisco" and nothing else — the corpus's most
    # common location, and unanswerable without the city table.
    for location in (
        "San Francisco",
        "New York",
        "Seattle",
        "Chicago",
        "Austin",
        "Mountain View",
        "Bengaluru",
        "London",
        "Dublin",
        "Amsterdam",
        "Tokyo",
        "Singapore",
        "Sydney",
        "Toronto",
    ):
        assert resolve_country(location) is not None, location


def test_a_city_that_names_two_countries_is_ambiguous() -> None:
    """A city table must not invent a country where the world is ambiguous.

    ``"Cambridge"`` is in both the UK and Massachusetts; ``"London"`` is in
    the UK and Ontario. The table's rule is one country per city or no entry,
    so these resolve by the *name* that accompanies them or not at all.
    """
    assert resolve_country("Cambridge, United Kingdom") == "GB"
    assert resolve_country("London, UK") == "GB"
    assert resolve_country("London, Ontario, Canada") == "CA"


# --------------------------------------------------------------------------
# Honest None: a working arrangement is not a place
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "location",
    [
        "Remote",
        "Hybrid",
        "Distributed",
        "Anywhere",
        "Remote/Hybrid",
        "Remote or Hybrid",
        "N/A",
        "na",
        "nn",
        "LOCATION",
        "",
        "   ",
        "Multiple Locations",
        "Various",
        "Work from home",
        None,
    ],
)
def test_an_arrangement_states_no_country(location) -> None:
    """ "Remote" is not "Remote in the US".

    Treating them alike answers a US-only question for a posting that never
    said US — which is a claim about the candidate's legal status, invented
    from a work arrangement.
    """
    assert resolve_country(location) is None


def test_a_region_or_continent_states_no_country() -> None:
    """EMEA is not a country, and neither is "Europe"."""
    for location in ("EMEA", "Europe", "APAC", "LATAM", "Remote - EMEA"):
        assert resolve_country(location) is None, location


# --------------------------------------------------------------------------
# Multi-country locations
# --------------------------------------------------------------------------


def test_a_location_naming_two_countries_returns_both() -> None:
    assert countries_in("Milan OR Madrid") == ["IT", "ES"]
    assert countries_in("London OR Dublin") == ["GB", "IE"]
    assert countries_in("Remote, Canada; Remote, United States") == ["CA", "US"]


def test_the_one_answer_form_returns_the_first_country_written() -> None:
    """``resolve_country`` is a convenience; ``countries_in`` is the honest call."""
    assert resolve_country("Milan OR Madrid") == "IT"
    assert resolve_country("Madrid OR Milan") == "ES"


def test_several_cities_in_one_country_collapse_to_one_country() -> None:
    assert countries_in("San Francisco, CA | New York City, NY") == ["US"]
    assert countries_in("San Francisco, CA; Chicago, IL") == ["US"]


def test_a_country_named_inside_a_compound_fragment_is_read() -> None:
    """ "Toronto Canada" and "Remote in US" state a country in their words."""
    assert resolve_country("Toronto Canada") == "CA"
    assert resolve_country("Remote in US") == "US"
    assert resolve_country("Germany (Berlin or Remote)") == "DE"


def test_a_leading_country_code_is_read() -> None:
    """The corpus stores "US-SF-HQ" and "US-New York" — the hyphen is not a split."""
    assert resolve_country("US-SF-HQ") == "US"
    assert resolve_country("US-San Francisco, US-New York") == "US"


def test_a_country_inside_a_long_us_location_is_read() -> None:
    assert resolve_country("Bay Area, CA, United States of America") == "US"


def test_a_two_letter_word_in_a_compound_fragment_invents_nothing() -> None:
    """ "in" is India's code and an English word; "us" is a code and a pronoun.

    A substring scan for bare codes would read "Remote in Berlin" as India and
    "Austin" as the United States-by-substring. Whole words only, and no
    two-letter code inside a longer fragment.
    """
    assert "IN" not in countries_in("Remote in Berlin")
    assert countries_in("Remote in Berlin") == ["DE"]
    assert resolve_country("Remote in Berlin") == "DE"


# --------------------------------------------------------------------------
# The canonical set
# --------------------------------------------------------------------------


def test_normalize_country_accepts_codes_and_names() -> None:
    assert normalize_country("US") == "US"
    assert normalize_country("us") == "US"
    assert normalize_country("United States") == "US"
    assert normalize_country("United States of America") == "US"
    assert normalize_country("USA") == "US"
    assert normalize_country("uk") == "GB"
    assert normalize_country("United Kingdom") == "GB"
    assert normalize_country("England") == "GB"
    assert normalize_country("  germany ") == "DE"


def test_normalize_country_rejects_what_is_not_a_country() -> None:
    """A closed set: a plausible-looking typo is not a country."""
    for value in ("XX", "ZZ", "Wakanda", "", None, "US and Canada"):
        assert normalize_country(value) is None, value


def test_canonicalize_discards_unknown_entries_and_deduplicates() -> None:
    assert canonicalize_countries(["US", "United Kingdom", "US"]) == ["US", "GB"]
    assert canonicalize_countries(["Wakanda", "US"]) == ["US"]
    assert canonicalize_countries([]) == []
    assert canonicalize_countries(None) == []


def test_canonicalize_preserves_the_order_given() -> None:
    assert canonicalize_countries(["GB", "US", "IN"]) == ["GB", "US", "IN"]


def test_is_known_country_and_country_name() -> None:
    assert is_known_country("US")
    assert is_known_country("us")
    assert not is_known_country("XX")
    assert not is_known_country(None)
    assert country_name("US") == "United States"
    assert country_name("us") == "United States"
    assert country_name("XX") is None


def test_every_canonical_code_has_a_name() -> None:
    """The two tables must agree: no code without a name, no name without a code."""
    for code, name in COUNTRIES.items():
        assert len(code) == 2 and code.isupper(), code
        assert name and name[0].isupper(), name


# --------------------------------------------------------------------------
# The corpus itself (the measurements this module was built against)
# --------------------------------------------------------------------------


def test_the_resolver_never_reads_a_state_code_as_its_country() -> None:
    """The regression that motivated the whole design, pinned directly.

    Measured on the live corpus: 1,004 listings whose location is
    "<US city>, <state code>" were resolved to the *country* that shares the
    state's two letters.
    """
    from src.applications.countries import _COUNTRY_STATE_COLLISIONS

    assert _COUNTRY_STATE_COLLISIONS == frozenset({"AR", "CA", "CO", "DE", "ID", "IL", "IN", "MA"})
    for state in _COUNTRY_STATE_COLLISIONS:
        location = f"Some City, {state}"
        code = resolve_country(location)
        # It is the US (the state's country) or nothing — never the colliding
        # country, which is the only wrong answer available.
        assert code in (None, "US"), f"{location} -> {code}"
