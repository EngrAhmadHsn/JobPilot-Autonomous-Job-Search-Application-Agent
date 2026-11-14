"""Countries, and the country a free-text location states (WS-25c).

Why this exists
---------------

The boards ask **country-qualified** questions, and the measurement says they
are common and required:

* "Are you authorized to work in the country for which you apply?" — asked on
  12 listings across 1 board, **required**.
* "Are you authorized to work in the location(s) you selected?" — 12 listings,
  required.
* "Please select the country or countries you anticipate working from" — 12
  listings, required.
* "Please select the country where you currently reside." — 12 listings,
  required.

A single ``legally_authorized: bool`` cannot answer the first two honestly. A
candidate may be authorized in the UK and not in the US, so a blanket "yes" is
a **fabricated legal statement** on every posting outside the countries they
can actually work in — and answering it wrongly is the kind of error that gets
an application rejected, or worse, misrepresents the candidate. The honest
answer is a *function of the job's country*, which means the profile has to
state countries and the answer path has to know where the job is.

That is what this module supplies: a canonical country set, and a
deterministic resolution from the strings the corpus actually stores.

Canonical form
--------------

**ISO 3166-1 alpha-2** (``US``, ``GB``, ``IN``). Two letters, stable, and
unambiguous in a way free text is not: the corpus holds ``US-SF-HQ``,
``Remote - USA``, ``United States of America`` and ``US`` for one country.

The hard rule
-------------

**A location that does not state a country yields ``None``, never a guess.**
"Remote", "Distributed", "Hybrid", "Anywhere" and "SF, NYC" (initials are
ambiguous — SF is San Francisco here, but the three-letter forms collide with
airport codes and company initials) are left unresolved, and an unresolved job
country means the country-qualified questions go to a human rather than being
answered. A wrong legal answer is worse than an unanswered one, because the
unanswered one is recoverable and the wrong one is already submitted.

Where a resolution *is* made it is a **lookup, not an inference**: San
Francisco is in the US, and that is a fact with a test, not a judgement.
"""

from __future__ import annotations

import re
from collections.abc import Iterable

__all__ = [
    "COUNTRIES",
    "canonicalize_countries",
    "countries_in",
    "country_name",
    "is_known_country",
    "normalize_country",
    "resolve_country",
]

#: ISO 3166-1 alpha-2 -> the country's common English name.
#:
#: Deliberately not the full 249-entry ISO list: this is the set a job board
#: plausibly posts in, and every entry is one an operator may have to read.
#: An unknown code is rejected by :func:`normalize_country` rather than
#: accepted as free text, so a typo cannot become a country.
COUNTRIES: dict[str, str] = {
    "AE": "United Arab Emirates",
    "AR": "Argentina",
    "AT": "Austria",
    "AU": "Australia",
    "BE": "Belgium",
    "BG": "Bulgaria",
    "BR": "Brazil",
    "CA": "Canada",
    "CH": "Switzerland",
    "CL": "Chile",
    "CN": "China",
    "CO": "Colombia",
    "CZ": "Czechia",
    "DE": "Germany",
    "DK": "Denmark",
    "EE": "Estonia",
    "EG": "Egypt",
    "ES": "Spain",
    "FI": "Finland",
    "FR": "France",
    "GB": "United Kingdom",
    "GR": "Greece",
    "HK": "Hong Kong",
    "HR": "Croatia",
    "HU": "Hungary",
    "ID": "Indonesia",
    "IE": "Ireland",
    "IL": "Israel",
    "IN": "India",
    "IT": "Italy",
    "JP": "Japan",
    "KE": "Kenya",
    "KR": "South Korea",
    "LT": "Lithuania",
    "LU": "Luxembourg",
    "LV": "Latvia",
    "MA": "Morocco",
    "MX": "Mexico",
    "MY": "Malaysia",
    "NG": "Nigeria",
    "NL": "Netherlands",
    "NO": "Norway",
    "NZ": "New Zealand",
    "PH": "Philippines",
    "PK": "Pakistan",
    "PL": "Poland",
    "PT": "Portugal",
    "RO": "Romania",
    "RS": "Serbia",
    "SA": "Saudi Arabia",
    "SE": "Sweden",
    "SG": "Singapore",
    "SI": "Slovenia",
    "SK": "Slovakia",
    "TH": "Thailand",
    "TR": "Turkey",
    "TW": "Taiwan",
    "UA": "Ukraine",
    "US": "United States",
    "VN": "Vietnam",
    "ZA": "South Africa",
}

#: How a country's name is written in a location string -> its code.
#:
#: Every key is normalized with :func:`_key` (casefolded, punctuation gone),
#: so the table is readable as prose and the lookup is robust to the spelling
#: a board chooses. The abbreviations are here because the corpus uses them:
#: ``USA`` (227 listings write ``United States``, 208 write ``Remote - USA``).
_NAMES: dict[str, str] = {
    "united states": "US",
    "united states of america": "US",
    "usa": "US",
    "us": "US",
    "u s": "US",
    "u s a": "US",
    "america": "US",
    "united kingdom": "GB",
    "uk": "GB",
    "great britain": "GB",
    "britain": "GB",
    "england": "GB",
    "scotland": "GB",
    "wales": "GB",
    "northern ireland": "GB",
    "u k": "GB",
    "united arab emirates": "AE",
    "uae": "AE",
    "argentina": "AR",
    "austria": "AT",
    "australia": "AU",
    "belgium": "BE",
    "bulgaria": "BG",
    "brazil": "BR",
    "brasil": "BR",
    "canada": "CA",
    "switzerland": "CH",
    "chile": "CL",
    "china": "CN",
    "colombia": "CO",
    "czechia": "CZ",
    "czech republic": "CZ",
    "germany": "DE",
    "deutschland": "DE",
    "denmark": "DK",
    "estonia": "EE",
    "egypt": "EG",
    "spain": "ES",
    "espana": "ES",
    "finland": "FI",
    "france": "FR",
    "greece": "GR",
    "hong kong": "HK",
    "croatia": "HR",
    "hungary": "HU",
    "indonesia": "ID",
    "ireland": "IE",
    "israel": "IL",
    "india": "IN",
    "italy": "IT",
    "italia": "IT",
    "japan": "JP",
    "kenya": "KE",
    "south korea": "KR",
    "korea": "KR",
    "republic of korea": "KR",
    "lithuania": "LT",
    "luxembourg": "LU",
    "latvia": "LV",
    "morocco": "MA",
    "mexico": "MX",
    "malaysia": "MY",
    "nigeria": "NG",
    "netherlands": "NL",
    "holland": "NL",
    "norway": "NO",
    "new zealand": "NZ",
    "philippines": "PH",
    "pakistan": "PK",
    "poland": "PL",
    "portugal": "PT",
    "romania": "RO",
    "serbia": "RS",
    "saudi arabia": "SA",
    "sweden": "SE",
    "singapore": "SG",
    "slovenia": "SI",
    "slovakia": "SK",
    "thailand": "TH",
    "turkey": "TR",
    "turkiye": "TR",
    "taiwan": "TW",
    "ukraine": "UA",
    "vietnam": "VN",
    "viet nam": "VN",
    "south africa": "ZA",
}

#: A city that identifies its country without ambiguity -> the country code.
#:
#: Curated and **closed**: a city is here only when naming it identifies one
#: country, and the corpus's own frequency decided which cities earned a row
#: (measured 2026-11-13 — San Francisco appears 847 times, London 153,
#: Singapore 229, Tokyo 137). A city that names two countries is not here.
#:
#: This is what lets a job whose location is just ``"San Francisco"`` be
#: answered for at all. The alternative — no city table — would send the
#: authorization question to a human on the corpus's most common location.
_CITIES: dict[str, str] = {
    # United States
    "san francisco": "US",
    "sf": "US",
    "bay area": "US",
    "new york": "US",
    "new york city": "US",
    "nyc": "US",
    "seattle": "US",
    "chicago": "US",
    "washington": "US",
    "washington dc": "US",
    "dallas": "US",
    "san diego": "US",
    "boston": "US",
    "austin": "US",
    "denver": "US",
    "atlanta": "US",
    "los angeles": "US",
    "mountain view": "US",
    "palo alto": "US",
    "sunnyvale": "US",
    "bellevue": "US",
    "houston": "US",
    "philadelphia": "US",
    "miami": "US",
    "phoenix": "US",
    "portland": "US",
    "salt lake city": "US",
    "boulder": "US",
    "ann arbor": "US",
    "pittsburgh": "US",
    "nashville": "US",
    "raleigh": "US",
    "durham": "US",
    "irvine": "US",
    "san jose": "US",
    "oakland": "US",
    "berkeley": "US",
    "santa clara": "US",
    "cupertino": "US",
    "redwood city": "US",
    "san mateo": "US",
    "menlo park": "US",
    "columbus": "US",
    "minneapolis": "US",
    "detroit": "US",
    "st louis": "US",
    "charlotte": "US",
    "tampa": "US",
    "orlando": "US",
    "las vegas": "US",
    "indianapolis": "US",
    "cincinnati": "US",
    "cleveland": "US",
    "kansas city": "US",
    "milwaukee": "US",
    "sacramento": "US",
    "richardson": "US",
    "plano": "US",
    # Canada
    "toronto": "CA",
    "vancouver": "CA",
    "montreal": "CA",
    "ottawa": "CA",
    "calgary": "CA",
    "waterloo": "CA",
    "mississauga": "CA",
    "kitchener": "CA",
    "edmonton": "CA",
    "winnipeg": "CA",
    "halifax": "CA",
    "victoria": "CA",
    # United Kingdom
    "london": "GB",
    "manchester": "GB",
    "edinburgh": "GB",
    "cambridge": "GB",
    "bristol": "GB",
    "leeds": "GB",
    "glasgow": "GB",
    "birmingham": "GB",
    "oxford": "GB",
    "belfast": "GB",
    "cardiff": "GB",
    "sheffield": "GB",
    "nottingham": "GB",
    "reading": "GB",
    "bath": "GB",
    # Ireland
    "dublin": "IE",
    "cork": "IE",
    "galway": "IE",
    "limerick": "IE",
    # Netherlands
    "amsterdam": "NL",
    "rotterdam": "NL",
    "utrecht": "NL",
    "eindhoven": "NL",
    "the hague": "NL",
    "den haag": "NL",
    # Germany
    "berlin": "DE",
    "munich": "DE",
    "munchen": "DE",
    "hamburg": "DE",
    "frankfurt": "DE",
    "cologne": "DE",
    "stuttgart": "DE",
    "dusseldorf": "DE",
    "leipzig": "DE",
    "dresden": "DE",
    "nuremberg": "DE",
    "karlsruhe": "DE",
    "heidelberg": "DE",
    "bonn": "DE",
    # France
    "paris": "FR",
    "lyon": "FR",
    "toulouse": "FR",
    "bordeaux": "FR",
    "nantes": "FR",
    "lille": "FR",
    "marseille": "FR",
    "nice": "FR",
    # Spain / Portugal / Italy
    "madrid": "ES",
    "barcelona": "ES",
    "valencia": "ES",
    "seville": "ES",
    "malaga": "ES",
    "lisbon": "PT",
    "lisboa": "PT",
    "porto": "PT",
    "milan": "IT",
    "milano": "IT",
    "rome": "IT",
    "roma": "IT",
    "turin": "IT",
    "turin italy": "IT",
    "florence": "IT",
    # Northern Europe
    "stockholm": "SE",
    "gothenburg": "SE",
    "malmo": "SE",
    "copenhagen": "DK",
    "aarhus": "DK",
    "oslo": "NO",
    "helsinki": "FI",
    "espoo": "FI",
    "reykjavik": "IS",
    # Central / Eastern Europe
    "warsaw": "PL",
    "krakow": "PL",
    "wroclaw": "PL",
    "prague": "CZ",
    "brno": "CZ",
    "budapest": "HU",
    "vienna": "AT",
    "wien": "AT",
    "brussels": "BE",
    "antwerp": "BE",
    "ghent": "BE",
    "bucharest": "RO",
    "cluj": "RO",
    "sofia": "BG",
    "belgrade": "RS",
    "zagreb": "HR",
    "ljubljana": "SI",
    "bratislava": "SK",
    "tallinn": "EE",
    "riga": "LV",
    "vilnius": "LT",
    "athens": "GR",
    "kyiv": "UA",
    "kiev": "UA",
    "lviv": "UA",
    # Middle East / Africa
    "tel aviv": "IL",
    "jerusalem": "IL",
    "haifa": "IL",
    "dubai": "AE",
    "abu dhabi": "AE",
    "riyadh": "SA",
    "cairo": "EG",
    "lagos": "NG",
    "nairobi": "KE",
    "cape town": "ZA",
    "johannesburg": "ZA",
    "casablanca": "MA",
    # Asia-Pacific
    "singapore": "SG",
    "tokyo": "JP",
    "osaka": "JP",
    "kyoto": "JP",
    "seoul": "KR",
    "bengaluru": "IN",
    "bangalore": "IN",
    "mumbai": "IN",
    "bombay": "IN",
    "delhi": "IN",
    "new delhi": "IN",
    "gurgaon": "IN",
    "gurugram": "IN",
    "noida": "IN",
    "hyderabad": "IN",
    "pune": "IN",
    "chennai": "IN",
    "madras": "IN",
    "kolkata": "IN",
    "ahmedabad": "IN",
    "beijing": "CN",
    "shanghai": "CN",
    "shenzhen": "CN",
    "hangzhou": "CN",
    "guangzhou": "CN",
    "chengdu": "CN",
    "hong kong": "HK",
    "taipei": "TW",
    "bangkok": "TH",
    "jakarta": "ID",
    "manila": "PH",
    "kuala lumpur": "MY",
    "ho chi minh": "VN",
    "ho chi minh city": "VN",
    "hanoi": "VN",
    "sydney": "AU",
    "melbourne": "AU",
    "brisbane": "AU",
    "perth": "AU",
    "adelaide": "AU",
    "canberra": "AU",
    "auckland": "NZ",
    "wellington": "NZ",
    # Americas
    "sao paulo": "BR",
    "rio de janeiro": "BR",
    "belo horizonte": "BR",
    "brasilia": "BR",
    "mexico city": "MX",
    "guadalajara": "MX",
    "monterrey": "MX",
    "buenos aires": "AR",
    "santiago": "CL",
    "bogota": "CO",
    "medellin": "CO",
}

#: Words that describe a **working arrangement**, not a place. A location made
#: only of these states no country, and must resolve to ``None``: "Remote" is
#: not "Remote in the US", and treating them alike would answer a US-only
#: question for a posting that never said US.
_NOT_A_PLACE: frozenset[str] = frozenset(
    {
        "remote",
        "distributed",
        "anywhere",
        "hybrid",
        "onsite",
        "on site",
        "in office",
        "flexible",
        "global",
        "worldwide",
        "work from home",
        "wfh",
        "telecommute",
        "multiple locations",
        "various",
        "unspecified",
        "other",
        "n a",
    }
)

#: The separators a board uses between several locations.
#:
#: The conjunction alternation is **case-insensitive** on purpose: the corpus
#: writes ``"London OR Dublin"`` and ``"Milan OR Madrid"`` in capitals as often
#: as lowercase, and a case-sensitive pattern silently failed to split them —
#: so ``"Milan OR Madrid"`` was read as one fragment that resolved to Madrid's
#: country only, losing Italy entirely.
_SEPARATOR_RE = re.compile(
    r"[,;|•/&()\[\]]|\s+(?:or|and)\s+|\s+-\s+",
    re.IGNORECASE,
)

#: The two-letter codes that are **both** a country and a US state.
#:
#: This is the trap that makes a naive country parser wrong in the worst
#: direction: ``"San Francisco, CA"`` is California, and ``"Chicago, IL"`` is
#: Illinois — reading either as Canada or Israel is a fabricated legal
#: answer about where someone may work. Measured on the live corpus, a naive
#: reading resolved 1,284 listings to the wrong country, and ``Chicago, IL``
#: to Israel.
#:
#: A bare fragment inside a **comma-separated** location is therefore never
#: read as a country by code alone: it is read as a country only when the
#: fragment *is* the whole location (``"US-CA"`` is a location whose only
#: content after the country prefix is the state).
_COUNTRY_STATE_COLLISIONS: frozenset[str] = frozenset(
    {"AR", "CA", "CO", "DE", "ID", "IL", "IN", "MA"}
)

#: The US state and territory codes, so a state fragment can be recognized as
#: *belonging to* the United States rather than as a country.
_US_STATES: dict[str, str] = {
    "AL": "Alabama",
    "AK": "Alaska",
    "AZ": "Arizona",
    "AR": "Arkansas",
    "CA": "California",
    "CO": "Colorado",
    "CT": "Connecticut",
    "DE": "Delaware",
    "DC": "District of Columbia",
    "FL": "Florida",
    "GA": "Georgia",
    "HI": "Hawaii",
    "ID": "Idaho",
    "IL": "Illinois",
    "IN": "Indiana",
    "IA": "Iowa",
    "KS": "Kansas",
    "KY": "Kentucky",
    "LA": "Louisiana",
    "ME": "Maine",
    "MD": "Maryland",
    "MA": "Massachusetts",
    "MI": "Michigan",
    "MN": "Minnesota",
    "MS": "Mississippi",
    "MO": "Missouri",
    "MT": "Montana",
    "NE": "Nebraska",
    "NV": "Nevada",
    "NH": "New Hampshire",
    "NJ": "New Jersey",
    "NM": "New Mexico",
    "NY": "New York",
    "NC": "North Carolina",
    "ND": "North Dakota",
    "OH": "Ohio",
    "OK": "Oklahoma",
    "OR": "Oregon",
    "PA": "Pennsylvania",
    "RI": "Rhode Island",
    "SC": "South Carolina",
    "SD": "South Dakota",
    "TN": "Tennessee",
    "TX": "Texas",
    "UT": "Utah",
    "VT": "Vermont",
    "VA": "Virginia",
    "WA": "Washington",
    "WV": "West Virginia",
    "WI": "Wisconsin",
    "WY": "Wyoming",
    "PR": "Puerto Rico",
    "VI": "U.S. Virgin Islands",
    "GU": "Guam",
    "AS": "American Samoa",
    "MP": "Northern Mariana Islands",
}

#: A location that is a US state's **full name**, which states the country.
_US_STATE_NAMES: frozenset[str] = frozenset(
    name.casefold() for name in _US_STATES.values()
) | frozenset({"california", "texas", "washington state"})

#: Everything that is not a letter, a digit or a space.
_NON_WORD_RE = re.compile(r"[^a-z0-9 ]+")

_WHITESPACE_RE = re.compile(r"\s+")


def _key(value: str | None) -> str:
    """The comparison form of a location fragment.

    Casefolded, punctuation removed, whitespace collapsed. So ``"SÃO PAULO"``
    and ``"sao paulo"`` (the accents stripped by the punctuation pass are the
    same characters a board may or may not write) compare equal.
    """
    if not value:
        return ""
    text = _NON_WORD_RE.sub(" ", str(value).casefold())
    return _WHITESPACE_RE.sub(" ", text).strip()


def is_known_country(code: str | None) -> bool:
    """Whether *code* is one of the canonical countries."""
    return bool(code) and str(code).upper() in COUNTRIES


def country_name(code: str | None) -> str | None:
    """The English name of a canonical code, or ``None`` if it is not one."""
    if not code:
        return None
    return COUNTRIES.get(str(code).upper())


def normalize_country(value: str | None) -> str | None:
    """``"United States"``, ``"usa"``, ``"US"`` -> ``"US"``.

    Accepts a canonical code or a recognized name/alias. Returns ``None`` for
    anything else — including a plausible-looking typo — because a country
    list is a closed set and an unrecognized entry is not a country.

    A **code-shaped** string is not enough on its own: ``"XX"`` is two letters
    and is not a country, so it is rejected rather than stored.
    """
    key = _key(value)
    if not key:
        return None
    if key.upper() in COUNTRIES:
        return key.upper()
    return _NAMES.get(key)


def resolve_country(text: str | None) -> str | None:
    """The one country a location string states, or ``None``.

    The single-answer form of :func:`countries_in`, for a location that names
    one place (``"London, United Kingdom"``, ``"San Francisco"``). When a
    string names several countries, this returns the **first** one in the
    order written and :func:`countries_in` is the honest call — a single
    country is the wrong shape for ``"London OR Paris"``.

    Returns ``None`` when nothing resolves. Never guesses: an unrecognized
    fragment is not a country, and a working-arrangement word is explicitly
    not a place.
    """
    found = countries_in(text)
    return found[0] if found else None


def countries_in(text: str | None) -> list[str]:
    """Every country a location string states, in the order written.

    A board's location field is free text and often lists several places:
    ``"Milan OR Madrid"`` is two countries, ``"Remote, Canada; Remote, United
    States"`` is two, ``"San Francisco, CA | New York City, NY"`` is one
    country named twice (San Francisco and New York are both in the US, and
    the duplicate collapses).

    Empty when nothing resolves — see :func:`resolve_country` on why that is
    the honest answer rather than a default.
    """
    if not text or not str(text).strip():
        return []

    raw = str(text)
    fragments = [f for f in _SEPARATOR_RE.split(raw)]
    alone = len(fragments) == 1

    # Two passes, because a **stated** country must beat an **inferred** one.
    #
    # "London, Ontario, Canada" names Canada outright, and its first fragment
    # is also a city in the UK. Answering GB there would fabricate the
    # posting's country out of a city guess, while Canada is something the
    # board actually wrote down. So the explicit readings are collected first
    # — a country name or code the fragment consists of, plus any country
    # named inside a compound fragment — and the city table is consulted only
    # when they produce nothing.
    explicit: list[str] = []
    for fragment in fragments:
        code = _resolve_fragment(fragment, alone=alone, cities=False)
        if code is not None:
            if code not in explicit:
                explicit.append(code)
            continue
        for embedded in _countries_named_in(fragment):
            if embedded not in explicit:
                explicit.append(embedded)

    if explicit:
        return explicit

    # Nothing named a country. A city is the last resort — and it is still a
    # lookup rather than a guess: "San Francisco" is in the US, and the corpus
    # writes it that way 847 times.
    found: list[str] = []
    for fragment in fragments:
        code = _resolve_fragment(fragment, alone=alone, cities=True)
        if code is not None and code not in found:
            found.append(code)

    if found:
        return found

    # Two shapes are left that the fragment split cannot see:
    #
    #   "US-San Francisco" / "US-SF-HQ" — the country is a leading code and
    #   the hyphen is not a separator (the city follows it).
    #   "Bay Area CA United States of America" — the whole string is one
    #   place with the country spelled out inside it.
    #
    # Both are matched against the whole string, so a country named anywhere
    # in an otherwise unparseable location is still read rather than dropped.
    return _resolve_whole(raw)


def _resolve_fragment(fragment: str, *, alone: bool, cities: bool) -> str | None:
    """The country one location fragment states, or ``None``.

    ``alone`` says the fragment is the whole location (no separator was
    found), and it is the *only* situation in which a **bare two-letter code**
    is read as a country. See :data:`_COUNTRY_STATE_COLLISIONS`: inside a
    comma-separated location ``"CA"`` is California, and reading it as Canada
    would answer "are you authorized to work in Canada?" wrongly. Measured on
    the live corpus, the naive reading mis-resolved 1,004 listings — every one
    of them toward a country the posting is not in.

    ``cities`` gates the city table, because a city is an **inference** and a
    country name is a **statement**: the caller runs this with ``cities=False``
    first, so a stated country always wins (``"London, Ontario, Canada"`` is
    Canada, not the UK).
    """
    key = _key(fragment)
    if not key or key in _NOT_A_PLACE:
        return None

    upper = key.upper()

    # A recognized country **name** ("United States", "usa") is never
    # ambiguous, so it is read wherever it appears.
    named = _NAMES.get(key)
    if named is not None:
        return named

    if len(upper) == 2 and upper.isalpha():
        if (alone or upper not in _COUNTRY_STATE_COLLISIONS) and upper in COUNTRIES:
            return upper
        # A US state code states the United States: "Chicago, IL" is in the
        # US, and that is the useful fact — not that "IL" is not a country.
        if upper in _US_STATES:
            return "US"
        return COUNTRIES.get(upper)

    # A US state's full name states the country ("Seattle, Washington").
    # Checked before the city table, because a state name is the more
    # specific reading of the fragment.
    if key in _US_STATE_NAMES:
        return "US"

    if not cities:
        return None
    return _CITIES.get(key)


def _countries_named_in(fragment: str) -> list[str]:
    """Countries whose name is stated **inside** this fragment, or ``[]``.

    A fragment can carry a country it does not consist of: ``"Toronto
    Canada"``, ``"Remote in US"``, ``"Bay Area CA"``. The fragment-level
    lookup cannot see those (the fragment as a whole is not a country), so
    this pass scans for names present as whole words.

    Three guards, because free text is where a country parser goes wrong:

    * **whole words only**, so "Indianapolis" does not match "India";
    * **longest name first**, so ``"United States of America"`` is read once
      rather than shadowed by a shorter key it contains;
    * **no two-letter codes unscanned** — the substring "in" (India's code)
      appears in "Remote in Berlin" and "us" inside "Austin", so a bare-code
      scan over free text would invent countries. A code counts only through
      :func:`_codes_after_prepositions`, where a preposition precedes it.

    **This is the explicit pass and it never consults the city table.**
    ``_cities_named_in`` is a separate function for that reason: a city is an
    inference, and the caller must be able to run inference-free first so a
    stated country wins (``"London, Ontario, Canada"``).
    """
    key = _key(fragment)
    if not key:
        return []
    padded = f" {key} "
    found: list[str] = []

    for name, code in sorted(_NAMES.items(), key=lambda item: -len(item[0])):
        if len(name) <= 2:
            continue
        if f" {name} " in padded and code not in found:
            found.append(code)

    if found:
        return found
    return _codes_after_prepositions(padded)


def _cities_named_in(padded_key: str) -> list[str]:
    """Cities present as whole words in an already-normalized, padded key.

    **Not called by** :func:`_countries_named_in`. The two answer different
    questions — "is a country named here?" and "is a city named here?" — and
    keeping them apart is what lets the caller run the explicit pass first, so
    ``"London, Ontario, Canada"`` resolves to Canada rather than to a city
    guess. :func:`countries_in` calls this only after the explicit pass found
    nothing.

    Two-character keys are skipped **here but not in the exact-fragment
    lookup**, and the difference is deliberate. ``"SF"`` as a location's own
    value is San Francisco (847 listings say ``"San Francisco"``, and the
    boards' shorthand is ``"SF"``), so :func:`_resolve_fragment` reads it.
    Scanning for ``"sf"`` *inside* a longer string is a different question —
    it is two letters that occur in other words — so the substring pass does
    not, and neither does it read ``"sea"`` (the word) as Seattle.
    """
    found: list[str] = []
    for city, code in sorted(_CITIES.items(), key=lambda item: -len(item[0])):
        if len(city) <= 2:
            continue
        if f" {city} " in padded_key and code not in found:
            found.append(code)
    return found


#: The words that introduce a place: "Remote **in** US", "Based **in** the UK".
#: A two-letter country code directly after one of these is a country, because
#: the word before it establishes that what follows is a location.
_PLACE_PREPOSITIONS: tuple[str, ...] = (
    "in",
    "from",
    "across",
    "within",
    "to",
    "based in",
    "working in",
)

#: A two-letter code preceded by a preposition ("in us", "within de").
_CODE_AFTER_PREPOSITION_RE = re.compile(r"\b(?:in|from|across|within|to)\s+(?:the\s+)?([a-z]{2})\b")


def _codes_after_prepositions(padded_key: str) -> list[str]:
    """Two-letter country codes that follow a place preposition.

    ``"Remote in US"`` and ``"Remote in the UK"`` state a country, but the
    fragment's own words do not name one, and a bare-code substring scan is
    unsafe ("in" is India's code, "us" is a pronoun). The preposition is what
    makes the code unambiguous: "in US" is a place, "Remote in Berlin" has no
    code after its preposition at all.
    """
    found: list[str] = []
    for match in _CODE_AFTER_PREPOSITION_RE.finditer(padded_key):
        code = match.group(1).upper()
        if code in COUNTRIES and code not in found:
            found.append(code)
    return found


def _resolve_whole(raw: str) -> list[str]:
    """Resolve a location the fragment pass could not read at all.

    Two shapes arrive here:

    * a **leading country code** — ``"US-SF-HQ"``, ``"UK-London"`` — where the
      hyphen is not a separator (the city follows it), so the code is only
      visible when the string is read as a whole;
    * a location whose country is **spelled out inside it** — ``"Bay Area,
      CA, United States of America"``.

    The city table is consulted last and only for multi-word cities, for the
    reason given on :func:`_countries_named_in`.
    """
    found: list[str] = []

    # A leading two-letter code: "US-SF-HQ", "UK-London".
    prefix = re.match(r"\s*([A-Za-z]{2})\s*[-–]\s*\S", raw)
    if prefix is not None:
        code = prefix.group(1).upper()
        if code in COUNTRIES:
            found.append(code)

    # A country name anywhere in the string, longest first so "United States
    # of America" is not shadowed by a shorter key it contains.
    key = f" {_key(raw)} "
    for name, code in sorted(_NAMES.items(), key=lambda item: -len(item[0])):
        if len(name) <= 2:
            continue
        if f" {name} " in key and code not in found:
            found.append(code)

    if found:
        return found

    return _cities_named_in(key)


def canonicalize_countries(values: Iterable[str] | None) -> list[str]:
    """Normalize a user-supplied country list, dropping what is not a country.

    Preserves the order given, removes duplicates, and **discards** an
    unrecognized entry rather than storing free text. A profile that stores
    "US and also sort of Canada" cannot be reasoned about; one that stores
    two codes can.
    """
    if not values:
        return []
    out: list[str] = []
    for value in values:
        code = normalize_country(_country_code_of(value))
        if code is not None and code not in out:
            out.append(code)
    return out


def _country_code_of(value: str) -> str | None:
    """The code for a value that may be a code or a full name."""
    text = str(value or "").strip()
    return text if text else None
