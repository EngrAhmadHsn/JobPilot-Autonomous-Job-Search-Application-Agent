"""Salary normalization (WS-23).

``JobListing.salary`` was populated for 13 of 6,696 rows (Remotive only)
and ``JobListing.currency`` for **zero** rows, so the preference
component's salary half never ran against a listing that stated a pay
figure. The boards publish pay in three different shapes and one
unparseable one:

* **Greenhouse** — ``?pay_transparency=true`` adds ``pay_input_ranges[]``
  with ``min_cents`` / ``max_cents`` (integers), ``currency_type``,
  ``title`` and ``blurb``. This is the best shape: it is already
  structured, and no parsing is needed.
* **Lever** — ``salaryRange{min, max, currency, interval}``, plus
  ``salaryDescription`` prose.
* **Ashby** — ``compensation.compensationTiers[].components[]`` with
  ``minValue``, ``maxValue``, ``currencyCode`` and ``interval``.
* **Remotive** — a single free-text string. The observed values are
  ``"$25k - $35k"``, ``"$50-$75 /hour"``, ``"$14/hour"``, ``"$20k -$35k"``,
  ``"$3.5k–$5k/month"`` (an **en-dash**), ``"70K-80K"`` (no symbol),
  ``"$1000 per task"`` and ``"$35,3k- $52k"`` (a **European decimal
  comma**). This one is parsed tolerantly and the raw string is kept.

The rule throughout: a range that cannot be read confidently is **not**
guessed. The raw text is retained so the console can show what the board
actually said, and the numeric field stays ``None``.
"""

from __future__ import annotations

import re

__all__ = [
    "parse_salary_range",
    "salary_from_ashby_compensation",
    "salary_from_greenhouse_pay_ranges",
    "salary_from_lever_range",
]


#: A currency symbol or code at the start of a figure. The symbols are
#: ordered longest-first so ``C$`` is matched before ``$``.
_CURRENCY_SYMBOLS: tuple[tuple[str, str], ...] = (
    ("US$", "USD"),
    ("CA$", "CAD"),
    ("C$", "CAD"),
    ("A$", "AUD"),
    ("AU$", "AUD"),
    ("NZ$", "NZD"),
    ("£", "GBP"),
    ("€", "EUR"),
    ("$", "USD"),
    ("¥", "JPY"),
    ("₹", "INR"),
    ("R$", "BRL"),
)

#: ISO codes that may appear in the text.
_CURRENCY_CODES: frozenset[str] = frozenset(
    {"USD", "CAD", "AUD", "NZD", "GBP", "EUR", "JPY", "INR", "BRL", "CHF", "SEK", "NOK", "DKK"}
)

#: The periods a figure may be expressed in, and what one unit is worth in
#: a year. A figure is normalized to **annual** so two boards that quote
#: different periods can be compared.
_PERIOD_TO_ANNUAL: dict[str, float] = {
    "year": 1.0,
    "yearly": 1.0,
    "annually": 1.0,
    "annum": 1.0,
    "month": 12.0,
    "monthly": 12.0,
    "week": 52.0,
    "weekly": 52.0,
    "hour": 2080.0,
    "hourly": 2080.0,
    "day": 260.0,
    "daily": 260.0,
}

#: A number, optionally with a "k" suffix, tolerating a European decimal
#: comma. The comma form is only accepted when there is no dot, so
#: ``"35,3k"`` is 35.3k and ``"1,234"`` is 1234. The suffix is
#: case-insensitive: the observed values include both ``"70K-80K"`` and
#: ``"$3.5k–$5k/month"``.
_NUMBER_RE = re.compile(
    r"(?P<value>\d{1,3}(?:[.,]\d{3})*(?:[.,]\d{1,2})?|\d+(?:[.,]\d{1,2})?)\s*(?P<k>[kK])?"
)

#: The period words that may follow a figure.
_PERIOD_RE = re.compile(
    r"(?:/|per\s+|a\s+|an\s+)?\b(year|yearly|annum|month|monthly|week|weekly|hour|hourly|daily|day|task)\b",
    re.IGNORECASE,
)


def _parse_number(raw: str) -> float | None:
    """Parse one figure, tolerating a European decimal comma."""
    text = raw.strip()
    if not text:
        return None
    # "1,234" is a thousands separator; "35,3" is a decimal comma. The
    # distinction is the number of digits after the separator.
    if "," in text and "." in text:
        text = text.replace(",", "")
    elif "," in text:
        head, _, tail = text.partition(",")
        if len(tail) == 3 and len(head) <= 3 and head:
            text = text.replace(",", "")  # a thousands separator
        else:
            text = text.replace(",", ".")  # a decimal comma
    try:
        return float(text)
    except ValueError:
        return None


def _detect_currency(text: str) -> str | None:
    """The currency a salary string states, or None."""
    upper = text.upper()
    for code in _CURRENCY_CODES:
        if re.search(rf"\b{code}\b", upper):
            return code
    for symbol, code in _CURRENCY_SYMBOLS:
        if symbol in text:
            return code
    return None


def _detect_period(text: str) -> str | None:
    """The period a salary string states, or None (meaning "per year")."""
    match = _PERIOD_RE.search(text)
    if match is None:
        return None
    return match.group(1).casefold()


def parse_salary_range(raw: str | None) -> tuple[str | None, str | None]:
    """Parse a free-text salary string into ``(salary, currency)``.

    The salary is the **annualized** range as a human-readable string
    (``"25000 - 35000"``), and the currency is the ISO code the text
    states. Both are ``None`` when the text states neither a figure nor a
    currency — an unparsed salary is not a guessed one.
    """
    if not raw or not isinstance(raw, str) or not raw.strip():
        return None, None

    text = raw.strip()
    currency = _detect_currency(text)
    period = _detect_period(text)
    annual_factor = _PERIOD_TO_ANNUAL.get(period or "year", 1.0)

    figures: list[float] = []
    for match in _NUMBER_RE.finditer(text):
        # Skip the "k" of a thousands-separated number being read twice.
        value = _parse_number(match.group("value"))
        if value is None:
            continue
        if match.group("k"):
            value *= 1000
        figures.append(value)

    if not figures:
        return (None, currency) if currency else (None, None)

    figures = [f * annual_factor for f in figures]
    low = min(figures)
    high = max(figures)
    if abs(high - low) < 0.5:
        return f"{low:.0f}", currency
    return f"{low:.0f} - {high:.0f}", currency


def salary_from_greenhouse_pay_ranges(ranges: object) -> tuple[str | None, str | None]:
    """The salary and currency from Greenhouse ``pay_input_ranges[]``.

    The ranges are already structured — ``min_cents`` and ``max_cents``
    are integer cents and ``currency_type`` is the ISO code — so this is
    a projection, not a parse. A board that publishes no range returns
    ``(None, None)``, which is a fact about the board, not a failure.
    """
    if not isinstance(ranges, list) or not ranges:
        return None, None
    lows: list[int] = []
    highs: list[int] = []
    currency: str | None = None
    for entry in ranges:
        if not isinstance(entry, dict):
            continue
        low = entry.get("min_cents")
        high = entry.get("max_cents")
        if isinstance(low, (int, float)):
            lows.append(int(low))
        if isinstance(high, (int, float)):
            highs.append(int(high))
        if currency is None:
            code = entry.get("currency_type")
            if isinstance(code, str) and code.strip():
                currency = code.strip().upper()
    if not lows and not highs:
        return None, None
    low = min(lows) if lows else None
    high = max(highs) if highs else None
    if low is None and high is None:
        return None, currency
    low_text = f"{low / 100:.0f}" if low is not None else ""
    high_text = f"{high / 100:.0f}" if high is not None else ""
    if low_text and high_text and low_text != high_text:
        return f"{low_text} - {high_text}", currency
    return (low_text or high_text), currency


def salary_from_lever_range(
    salary_range: object, salary_description: object = None
) -> tuple[str | None, str | None]:
    """The salary and currency from Lever's ``salaryRange``.

    Lever states the interval (``per-year-salary`` and friends). The
    figure is annualized the same way the free-text parser does, so a
    board quoting hourly and a board quoting annual are comparable.
    """
    if not isinstance(salary_range, dict):
        return None, None
    low = salary_range.get("min")
    high = salary_range.get("max")
    currency = salary_range.get("currency")
    interval = salary_range.get("interval")
    if not isinstance(currency, str) or not currency.strip():
        currency = None
    else:
        currency = currency.strip().upper()

    factor = 1.0
    if isinstance(interval, str):
        normalized = interval.casefold().replace("per-", "").replace("per ", "").strip()
        factor = _PERIOD_TO_ANNUAL.get(normalized, 1.0)

    values = [float(v) for v in (low, high) if isinstance(v, (int, float))]
    if not values:
        return None, currency
    scaled = [v * factor for v in values]
    low_text = f"{min(scaled):.0f}"
    high_text = f"{max(scaled):.0f}"
    if low_text == high_text:
        return low_text, currency
    return f"{low_text} - {high_text}", currency


def salary_from_ashby_compensation(compensation: object) -> tuple[str | None, str | None]:
    """The salary and currency from Ashby's ``compensation`` object.

    The shape is nested: ``compensationTiers[]`` each holding
    ``components[]`` with a ``compensationType`` of ``Salary``, ``Bonus``
    or ``EquityPercentage``. Only the **salary** components are read: a
    bonus or an equity percentage is not a salary, and mixing them would
    produce a number that means nothing.
    """
    if not isinstance(compensation, dict):
        return None, None
    tiers = compensation.get("compensationTiers")
    if not isinstance(tiers, list):
        return None, None

    lows: list[float] = []
    highs: list[float] = []
    currency: str | None = None
    for tier in tiers:
        if not isinstance(tier, dict):
            continue
        components = tier.get("components")
        if not isinstance(components, list):
            continue
        for component in components:
            if not isinstance(component, dict):
                continue
            kind = component.get("compensationType")
            if isinstance(kind, str) and kind.casefold() not in {"salary"}:
                continue
            low = component.get("minValue")
            high = component.get("maxValue")
            if currency is None:
                code = component.get("currencyCode")
                if isinstance(code, str) and code.strip():
                    currency = code.strip().upper()
            interval = component.get("interval")
            factor = 1.0
            if isinstance(interval, str):
                factor = _PERIOD_TO_ANNUAL.get(interval.casefold().strip(), 1.0)
            if isinstance(low, (int, float)):
                lows.append(float(low) * factor)
            if isinstance(high, (int, float)):
                highs.append(float(high) * factor)

    if not lows and not highs:
        return None, currency
    low_text = f"{min(lows):.0f}" if lows else ""
    high_text = f"{max(highs):.0f}" if highs else ""
    if low_text and high_text and low_text != high_text:
        return f"{low_text} - {high_text}", currency
    return (low_text or high_text), currency
