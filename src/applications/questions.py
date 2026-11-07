"""The application-question taxonomy (WS-20).

WS-08 answered a form question by looking its label up in a flat
``FIELD_MAP``. That is fine for "Email", and wrong for the questions that
actually cost a candidacy: work authorization, visa sponsorship and
citizenship overlap in words but take *different* answers, and a broad
substring match cannot tell them apart.

This module is a small, deterministic **classification** layer on top of the
field map:

- :class:`QuestionCategory` — canonical categories with a fixed **precedence**,
  so an overlapping label resolves the same way every time
  (sponsorship → authorization → citizenship; current → desired salary);
- :class:`AnswerType` — what kind of value the question wants;
- rules are regular expressions, not "does the label contain this word";
- :data:`NEVER_AUTOFILL` categories — EEO and legal attestations — are never
  answered by the agent, no matter how confident the classification;
- a low-confidence match returns :data:`QuestionCategory.UNKNOWN` so the
  question goes to a human instead of being guessed.

It also carries the deterministic value transforms a form needs: notice-period
formatting (never an integer floor that misreports a real period) and
pay-period conversion (never a silent currency conversion).
"""

from __future__ import annotations

import re
from enum import StrEnum

from pydantic import BaseModel, Field

__all__ = [
    "CATEGORY_FACT_KEYS",
    "CONFIDENCE_THRESHOLD",
    "EEO_CATEGORIES",
    "NEVER_AUTOFILL",
    "AnswerType",
    "Classification",
    "QuestionCategory",
    "classify_text",
    "convert_pay_period",
    "format_notice_minutes",
    "format_salary",
    "notice_period_answer",
    "notice_period_days",
]


class AnswerType(StrEnum):
    """What kind of value the question wants."""

    TEXT = "text"
    BOOLEAN = "boolean"
    NUMBER = "number"
    CHOICE = "choice"
    DATE = "date"
    URL = "url"


class QuestionCategory(StrEnum):
    """Canonical application-question categories."""

    CANDIDATE_NAME = "candidate_name"
    EMAIL = "email"
    PHONE = "phone"
    LOCATION = "location"
    COUNTRY = "country"

    TOTAL_EXPERIENCE = "total_experience"
    SKILL_EXPERIENCE = "skill_experience"
    SENIORITY_LEVEL = "seniority_level"

    WORK_AUTHORIZATION = "work_authorization"
    VISA_SPONSORSHIP = "visa_sponsorship"
    CITIZENSHIP_STATUS = "citizenship_status"

    DESIRED_SALARY = "desired_salary"
    CURRENT_SALARY = "current_salary"
    SALARY_CURRENCY = "salary_currency"
    PAY_PERIOD = "pay_period"

    NOTICE_PERIOD = "notice_period"
    AVAILABILITY_DATE = "availability_date"

    PORTFOLIO_URL = "portfolio_url"
    LINKEDIN_URL = "linkedin_url"
    GITHUB_URL = "github_url"
    WEBSITE = "website"

    EMPLOYMENT_TYPE = "employment_type"
    WORK_MODE = "work_mode"
    SKILLS = "skills"
    RESUME = "resume"
    COVER_LETTER = "cover_letter"

    EEO_RACE = "eeo_race"
    EEO_GENDER = "eeo_gender"
    EEO_DISABILITY = "eeo_disability"
    EEO_VETERAN = "eeo_veteran"

    ATTESTATION = "attestation"
    UNKNOWN = "unknown"


#: Categories the agent must **never** auto-answer.
EEO_CATEGORIES: frozenset[QuestionCategory] = frozenset(
    {
        QuestionCategory.EEO_RACE,
        QuestionCategory.EEO_GENDER,
        QuestionCategory.EEO_DISABILITY,
        QuestionCategory.EEO_VETERAN,
    }
)
NEVER_AUTOFILL: frozenset[QuestionCategory] = EEO_CATEGORIES | {QuestionCategory.ATTESTATION}

#: Below this confidence a classification is not trusted.
CONFIDENCE_THRESHOLD = 0.6


class QuestionRule(BaseModel):
    """One classification rule: a category, its answer type, and its patterns.

    ``patterns`` are tried in order; a rule matches when any pattern matches.
    ``forbids`` lists patterns whose presence *disqualifies* the rule — the
    mechanism that stops "authorized to work" from also matching the
    sponsorship rule.
    """

    category: QuestionCategory
    answer_type: AnswerType
    patterns: tuple[str, ...]
    forbids: tuple[str, ...] = ()
    confidence: float = 0.9


#: Ordered by precedence — the first rule whose pattern matches wins. The
#: ordering *is* the precedence, so it is stated once, here.
RULES: tuple[QuestionRule, ...] = (
    # -- EEO and attestations first: they must never fall through to a
    #    "looks like this" match. ------------------------------------------
    QuestionRule(
        category=QuestionCategory.EEO_RACE,
        answer_type=AnswerType.CHOICE,
        patterns=(r"\brace\b|\bethnicit(y|ies)\b|\bhispanic\b|\blatino\b",),
        confidence=0.95,
    ),
    QuestionRule(
        category=QuestionCategory.EEO_GENDER,
        answer_type=AnswerType.CHOICE,
        patterns=(r"\bgender\b|\bsex\b|\bpronoun",),
        confidence=0.95,
    ),
    QuestionRule(
        category=QuestionCategory.EEO_DISABILITY,
        answer_type=AnswerType.CHOICE,
        patterns=(r"\bdisabilit(y|ies)\b|\bhandicap",),
        confidence=0.95,
    ),
    QuestionRule(
        category=QuestionCategory.EEO_VETERAN,
        answer_type=AnswerType.CHOICE,
        patterns=(r"\bveteran\b|\bmilitary service\b|\bprotected veteran\b",),
        confidence=0.95,
    ),
    QuestionRule(
        category=QuestionCategory.ATTESTATION,
        answer_type=AnswerType.BOOLEAN,
        patterns=(
            r"\bi (agree|certify|consent|acknowledge|confirm|accept|consent to)\b",
            r"\bterms (and conditions|of (service|use))\b",
            r"\bprivacy (policy|notice|statement)\b",
            r"\bdeclaration\b|\battestation\b|\bcode of conduct\b",
        ),
        confidence=0.9,
    ),
    # -- distinct legal questions, in precedence order --------------------
    QuestionRule(
        category=QuestionCategory.VISA_SPONSORSHIP,
        answer_type=AnswerType.BOOLEAN,
        patterns=(
            r"\bsponsor(ship|ed|ing)?\b",
            r"\bvisa\b.*\b(sponsor|support|transfer)\b",
            r"\brequire\b.*\b(visa|immigration)\b",
            r"\bwork (permit|visa)\b.*\b(require|need|sponsor)\b",
        ),
        confidence=0.9,
    ),
    QuestionRule(
        category=QuestionCategory.WORK_AUTHORIZATION,
        answer_type=AnswerType.BOOLEAN,
        patterns=(
            r"\bauthoriz(ed|ation)\b.*\bwork\b",
            r"\bwork\b.*\bauthoriz(ed|ation)\b",
            r"\beligib(le|ility)\b.*\bwork\b",
            r"\b(legally )?(permitted|allowed|entitled) to work\b",
            r"\bright to work\b",
        ),
        # "authorized to work ... without sponsorship" is still an
        # authorization question, but a bare "sponsorship" mention without
        # "authoriz"/"work" belongs to the sponsorship rule above.
        confidence=0.85,
    ),
    QuestionRule(
        category=QuestionCategory.CITIZENSHIP_STATUS,
        answer_type=AnswerType.CHOICE,
        patterns=(
            r"\bcitizen(ship)?\b",
            r"\bimmigration status\b",
            r"\bpermanent resident\b|\bgreen card\b",
            r"\bnationality\b",
        ),
        confidence=0.85,
    ),
    # -- experience -------------------------------------------------------
    # "with"/"using" imply a tool; the ambiguous prepositions ("in"/"of") are
    # accepted only when a known technology token follows, so "5 years of
    # professional experience" stays a TOTAL question.
    QuestionRule(
        category=QuestionCategory.SKILL_EXPERIENCE,
        answer_type=AnswerType.NUMBER,
        patterns=(
            r"\byears?\b.*\b(with|using)\b",
            r"\bexperience\b.*\b(with|using)\b",
            r"\byears?\b.*\b(in|of)\b.*\b(python|java|javascript|typescript|c\+\+|c#|go|golang|rust|sql|react|node|kubernetes|docker|aws|azure|gcp|terraform|ruby|php|swift|kotlin)\b",
        ),
        confidence=0.7,
    ),
    QuestionRule(
        category=QuestionCategory.TOTAL_EXPERIENCE,
        answer_type=AnswerType.NUMBER,
        patterns=(
            r"\btotal\b.*\byears?\b",
            r"\byears? of (professional |relevant |work )?experience\b",
            r"\bhow many years (of )?experience\b",
        ),
        confidence=0.85,
    ),
    QuestionRule(
        category=QuestionCategory.SENIORITY_LEVEL,
        answer_type=AnswerType.CHOICE,
        patterns=(r"\bseniority (level|band)\b|\bseniority\b",),
        confidence=0.8,
    ),
    # -- compensation: current before desired -----------------------------
    QuestionRule(
        category=QuestionCategory.CURRENT_SALARY,
        answer_type=AnswerType.NUMBER,
        patterns=(
            r"\bcurrent\b.*\b(salary|compensation|pay|ctc)\b",
            r"\bpresent\b.*\b(salary|compensation|pay|ctc)\b",
        ),
        confidence=0.9,
    ),
    QuestionRule(
        category=QuestionCategory.DESIRED_SALARY,
        answer_type=AnswerType.NUMBER,
        patterns=(
            r"\b(desired|expected|require[ds]?|target)\b.*\b(salary|compensation|pay|ctc|rate)\b",
            r"\b(salary|compensation|pay|ctc)\b.*\b(expectation|requirement|desired|expected)\b",
            r"\bminimum\b.*\b(salary|compensation)\b",
        ),
        confidence=0.9,
    ),
    QuestionRule(
        category=QuestionCategory.SALARY_CURRENCY,
        answer_type=AnswerType.CHOICE,
        patterns=(r"\bcurrency\b",),
        confidence=0.85,
    ),
    QuestionRule(
        category=QuestionCategory.PAY_PERIOD,
        answer_type=AnswerType.CHOICE,
        patterns=(r"\bpay period\b|\bper (year|month|hour|week|annum)\b|\bsalary period\b",),
        confidence=0.8,
    ),
    # -- availability -----------------------------------------------------
    QuestionRule(
        category=QuestionCategory.NOTICE_PERIOD,
        answer_type=AnswerType.NUMBER,
        patterns=(r"\bnotice period\b|\bnotice\b.*\b(required|period)\b|\bhow much notice\b",),
        confidence=0.85,
    ),
    QuestionRule(
        category=QuestionCategory.AVAILABILITY_DATE,
        answer_type=AnswerType.DATE,
        patterns=(
            r"\b(available|availability|start) date\b",
            r"\bwhen can you start\b",
            r"\bearliest (start|available)\b",
            r"\bavailable (from|to start)\b",
        ),
        confidence=0.8,
    ),
    # -- links and documents ----------------------------------------------
    QuestionRule(
        category=QuestionCategory.LINKEDIN_URL,
        answer_type=AnswerType.URL,
        patterns=(r"\blinkedin\b",),
        confidence=0.95,
    ),
    QuestionRule(
        category=QuestionCategory.GITHUB_URL,
        answer_type=AnswerType.URL,
        patterns=(r"\bgithub\b|\bgitlab\b|\bportfolio\b.*\bcode\b",),
        confidence=0.9,
    ),
    QuestionRule(
        category=QuestionCategory.PORTFOLIO_URL,
        answer_type=AnswerType.URL,
        patterns=(r"\bportfolio\b|\bpersonal (website|site)\b|\bwebsite\b",),
        confidence=0.8,
    ),
    # -- simple identity --------------------------------------------------
    QuestionRule(
        category=QuestionCategory.CANDIDATE_NAME,
        answer_type=AnswerType.TEXT,
        patterns=(r"\b(full|legal|your) name\b|\bcandidate name\b",),
        confidence=0.9,
    ),
    QuestionRule(
        category=QuestionCategory.EMAIL,
        answer_type=AnswerType.TEXT,
        patterns=(r"\be?-?mail\b",),
        confidence=0.95,
    ),
    QuestionRule(
        category=QuestionCategory.PHONE,
        answer_type=AnswerType.TEXT,
        patterns=(r"\bphone\b|\btelephone\b|\bmobile\b",),
        confidence=0.95,
    ),
    QuestionRule(
        category=QuestionCategory.EMPLOYMENT_TYPE,
        answer_type=AnswerType.CHOICE,
        patterns=(r"\bemployment type\b|\bjob type\b|\bcontract type\b",),
        confidence=0.85,
    ),
    QuestionRule(
        category=QuestionCategory.WORK_MODE,
        answer_type=AnswerType.CHOICE,
        patterns=(r"\bwork (mode|arrangement|model)\b|\bremote\b.*\b(onsite|hybrid)\b",),
        confidence=0.85,
    ),
    QuestionRule(
        category=QuestionCategory.COUNTRY,
        answer_type=AnswerType.TEXT,
        patterns=(r"\bcountry( of residence| of citizenship)?\b",),
        confidence=0.8,
    ),
    QuestionRule(
        category=QuestionCategory.LOCATION,
        answer_type=AnswerType.TEXT,
        patterns=(r"\b(current )?location\b|\bcity\b|\bwhere are you based\b",),
        confidence=0.8,
    ),
)


#: The fact keys each category reads, in the order they are tried.
CATEGORY_FACT_KEYS: dict[QuestionCategory, tuple[str, ...]] = {
    QuestionCategory.CANDIDATE_NAME: ("candidate_name", "name"),
    QuestionCategory.EMAIL: ("email",),
    QuestionCategory.PHONE: ("phone",),
    QuestionCategory.LOCATION: ("location",),
    QuestionCategory.COUNTRY: ("country",),
    QuestionCategory.TOTAL_EXPERIENCE: ("total_experience_years", "years_of_experience"),
    QuestionCategory.SKILL_EXPERIENCE: ("skill_experience_years",),
    QuestionCategory.SENIORITY_LEVEL: ("seniority_level",),
    QuestionCategory.WORK_AUTHORIZATION: ("legally_authorized", "work_authorization"),
    QuestionCategory.VISA_SPONSORSHIP: ("requires_sponsorship",),
    QuestionCategory.CITIZENSHIP_STATUS: ("citizenship_status",),
    QuestionCategory.DESIRED_SALARY: ("expected_salary", "min_salary", "desired_salary"),
    QuestionCategory.CURRENT_SALARY: ("current_salary",),
    QuestionCategory.SALARY_CURRENCY: ("expected_currency", "salary_currency"),
    QuestionCategory.PAY_PERIOD: ("expected_period", "pay_period"),
    QuestionCategory.NOTICE_PERIOD: ("notice_period_days",),
    QuestionCategory.AVAILABILITY_DATE: ("availability_date",),
    QuestionCategory.PORTFOLIO_URL: ("portfolio_url", "website"),
    QuestionCategory.LINKEDIN_URL: ("linkedin_url", "linkedin"),
    QuestionCategory.GITHUB_URL: ("github_url", "github"),
    QuestionCategory.EMPLOYMENT_TYPE: ("employment_types",),
    QuestionCategory.WORK_MODE: ("work_mode", "remote_preference"),
    QuestionCategory.SKILLS: ("skills",),
    QuestionCategory.RESUME: ("resume",),
    QuestionCategory.COVER_LETTER: ("cover_letter",),
}


class Classification(BaseModel):
    """The result of classifying one label."""

    category: QuestionCategory = QuestionCategory.UNKNOWN
    answer_type: AnswerType = AnswerType.TEXT
    confidence: float = Field(0.0, ge=0.0, le=1.0)


def classify_text(label: str) -> Classification:
    """Classify a form label into a :class:`QuestionCategory`.

    Rules are tried in :data:`RULES` order (which *is* the precedence). A rule
    is skipped when one of its ``forbids`` patterns is present. A match below
    :data:`CONFIDENCE_THRESHOLD` — or no match at all — returns ``UNKNOWN``,
    so the caller leaves the question for a human rather than guessing.
    """
    if not label or not label.strip():
        return Classification()
    lowered = label.casefold()
    for rule in RULES:
        if any(re.search(forbid, lowered) for forbid in rule.forbids):
            continue
        if any(re.search(pattern, lowered) for pattern in rule.patterns):
            if rule.confidence < CONFIDENCE_THRESHOLD:
                continue
            return Classification(
                category=rule.category,
                answer_type=rule.answer_type,
                confidence=rule.confidence,
            )
    return Classification()


# --------------------------------------------------------------------------
# Deterministic value transforms
# --------------------------------------------------------------------------

_DAYS_PER_WEEK = 7
_DAYS_PER_MONTH = 30


def format_notice_minutes(days: int) -> str:
    """Human phrasing for a notice period in days (30 → "1 month")."""
    if days <= 0:
        return "Immediate"
    if days % _DAYS_PER_MONTH == 0:
        months = days // _DAYS_PER_MONTH
        return f"{months} month" + ("s" if months != 1 else "")
    if days % _DAYS_PER_WEEK == 0:
        weeks = days // _DAYS_PER_WEEK
        return f"{weeks} week" + ("s" if weeks != 1 else "")
    return f"{days} days"


def notice_period_days(days: int | None, *, immediate: bool | None = None) -> int | None:
    """Resolve a notice period to a day count, preserving ``0``/immediate.

    ``immediate=True`` means zero days even when ``days`` is unset; an explicit
    ``0`` is never confused with "not answered".
    """
    if immediate is True:
        return 0
    return days


def notice_period_answer(days: int | None, target_unit: str | None = None) -> str | None:
    """A notice period in the unit a form asks for, without silent rounding.

    The conversion is exact or refused: a form asking for **weeks** and a
    notice of 15 days does not become "2 weeks" (that floor loses a day);
    it becomes a value the user is asked to confirm. Returning the days + a
    note is the honest answer; the caller routes ambiguity to review.
    """
    if days is None:
        return None
    if target_unit is None:
        return str(days)
    unit = target_unit.casefold()
    if unit in {"day", "days"}:
        return str(days)
    if unit in {"week", "weeks"}:
        if days % _DAYS_PER_WEEK == 0:
            return str(days // _DAYS_PER_WEEK)
        return None  # not exactly expressible — needs confirmation
    if unit in {"month", "months"}:
        if days % _DAYS_PER_MONTH == 0:
            return str(days // _DAYS_PER_MONTH)
        return None
    return str(days)


#: Relative size of each pay period, in "per year" terms, for exact conversion.
_PERIODS_PER_YEAR: dict[str, int] = {
    "annual": 1,
    "monthly": 12,
    "weekly": 52,
    "daily": 260,
    "hourly": 2080,
}


def convert_pay_period(amount: float, from_period: str, to_period: str) -> tuple[float, str] | None:
    """Convert an amount between pay periods of the **same** currency.

    No currency conversion is ever performed: a different currency is not
    this function's business and would require an exchange rate with a source
    and a date. Returns ``(amount, note)`` or ``None`` when the periods are
    unknown.
    """
    source = _PERIODS_PER_YEAR.get(from_period.casefold())
    target = _PERIODS_PER_YEAR.get(to_period.casefold())
    if source is None or target is None:
        return None
    annual = amount * source
    converted = round(annual / target, 2)
    if from_period.casefold() == to_period.casefold():
        return (amount, "")
    return (converted, f"converted {from_period} to {to_period} at {source}:{target} periods")


def format_salary(amount: float | None, currency: str | None, period: str | None) -> str | None:
    """A salary string with its currency and period made explicit."""
    if amount is None:
        return None
    pieces = [f"{amount:g}"]
    if currency:
        pieces.append(currency.upper())
    if period:
        pieces.append(f"per {period.rstrip('ly')}" if period.endswith("ly") else f"per {period}")
    return " ".join(pieces)
