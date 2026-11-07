"""The candidate **application profile** (WS-20).

A résumé is not an application form. Visa status, notice period, expected
salary, EEO selections and job-search preferences are not on a résumé, yet an
application form asks for every one of them. WS-08's form layer could only
answer from résumé-derived facts, so these questions were always
"unresolved" — correct, but useless.

This module is the missing half: a structured set of **user-confirmed** values,
kept logically separate from the résumé facts. The résumé lives in
``CandidateProfile`` / ``profile_json``; this lives beside it and is only ever
written by the user.

Three separated groups
----------------------

**Professional information** — what the résumé says, restated and *confirmed*:
total experience, seniority level, per-skill years, current title, portfolio
and LinkedIn URLs.

**Job-search preferences** — where and how the candidate wants to work.

**Application answers** — the values a form asks for that the résumé does not
carry. Work authorization, sponsorship and citizenship are **three distinct
fields**: a candidate may be legally authorized to work *and* still require
sponsorship for a future transfer, so conflating them would mis-answer a real
form.

Privacy
-------

EEO / voluntary self-identification data is **not here** — it lives in
:mod:`src.resume.eeo`, in its own table, and is never read by the matcher.
"""

from __future__ import annotations

from datetime import date

from pydantic import BaseModel, Field, field_validator

__all__ = [
    "PAY_PERIODS",
    "REMOTE_OPTIONS",
    "ApplicationAnswers",
    "ApplicationProfile",
    "Compensation",
    "JobSearchPreferences",
    "NoticePeriod",
    "ProfessionalInfo",
    "WorkAuthorizationInfo",
]

REMOTE_OPTIONS = ("remote", "hybrid", "onsite", "any")
PAY_PERIODS = ("annual", "monthly", "weekly", "daily", "hourly")


def _clean_str(value: str | None) -> str | None:
    """Strip a free-text field, mapping empty to None."""
    if value is None:
        return None
    cleaned = value.strip()
    return cleaned or None


def _bounded_years(value: float | None) -> float | None:
    if value is None:
        return None
    if value < 0:
        raise ValueError("years cannot be negative")
    if value > 60:
        raise ValueError("years is implausibly large (max 60)")
    return float(value)


class ProfessionalInfo(BaseModel):
    """Confirmed professional facts (supplement the résumé, never invent)."""

    total_experience_years: float | None = None
    seniority_level: str | None = None
    current_title: str | None = None
    #: Explicit per-skill years, e.g. {"python": 6}. Only what the user states.
    skill_experience_years: dict[str, float] = Field(default_factory=dict)
    portfolio_url: str | None = None
    linkedin_url: str | None = None

    @field_validator("total_experience_years")
    @classmethod
    def _check_total(cls, value: float | None) -> float | None:
        return _bounded_years(value)

    @field_validator("skill_experience_years")
    @classmethod
    def _check_skills(cls, value: dict[str, float]) -> dict[str, float]:
        if len(value) > 100:
            raise ValueError("too many skill experience entries (max 100)")
        cleaned: dict[str, float] = {}
        for skill, years in value.items():
            key = _clean_str(skill)
            if key is None:
                continue
            if years is None or years < 0 or years > 60:
                raise ValueError(f"implausible years for {key!r}")
            cleaned[key] = float(years)
        return cleaned

    @field_validator("current_title", "seniority_level", "portfolio_url", "linkedin_url")
    @classmethod
    def _clean(cls, value: str | None) -> str | None:
        return _clean_str(value)


class JobSearchPreferences(BaseModel):
    """Where and how the candidate wants to work (user-stated only)."""

    preferred_locations: list[str] = Field(default_factory=list)
    remote_preference: str | None = None  # remote | hybrid | onsite | any
    employment_types: list[str] = Field(default_factory=list)
    willing_to_relocate: bool | None = None

    @field_validator("remote_preference")
    @classmethod
    def _check_remote(cls, value: str | None) -> str | None:
        cleaned = _clean_str(value)
        if cleaned is None:
            return None
        cleaned = cleaned.casefold()
        if cleaned not in REMOTE_OPTIONS:
            raise ValueError(f"remote_preference must be one of {REMOTE_OPTIONS}")
        return cleaned

    @field_validator("preferred_locations", "employment_types")
    @classmethod
    def _check_lists(cls, value: list[str]) -> list[str]:
        if len(value) > 50:
            raise ValueError("too many entries (max 50)")
        out: list[str] = []
        for item in value:
            cleaned = _clean_str(item)
            if cleaned is not None and cleaned not in out:
                out.append(cleaned)
        return out


class WorkAuthorizationInfo(BaseModel):
    """Three **distinct** question families — never conflated.

    A candidate may be ``legally_authorized`` today *and* still
    ``requires_sponsorship`` for a future role or transfer. Filling one from
    the other would be a fabricated legal answer, so they are separate fields
    and each is only ever set by the user.
    """

    #: Permission to work in a given country, now.
    legally_authorized: bool | None = None
    #: Whether sponsorship is (or will be) required.
    requires_sponsorship: bool | None = None
    #: Countries the authorization applies to, when the user says so.
    authorized_countries: list[str] = Field(default_factory=list)
    #: The citizenship/immigration status the user chooses to disclose, verbatim.
    citizenship_status: str | None = None
    #: The status value the user chose for forms that ask for a category.
    status_category: str | None = None

    @field_validator("citizenship_status", "status_category")
    @classmethod
    def _clean(cls, value: str | None) -> str | None:
        return _clean_str(value)

    @field_validator("authorized_countries")
    @classmethod
    def _check_countries(cls, value: list[str]) -> list[str]:
        if len(value) > 50:
            raise ValueError("too many countries (max 50)")
        return [c for c in (_clean_str(item) for item in value) if c is not None]


class Compensation(BaseModel):
    """Expected **and** current compensation, each with currency and period.

    Expected salary is not current salary. Keeping them in separate fields is
    what stops "desired salary" from being answered with a past paycheque.
    """

    expected_salary: float | None = None
    expected_currency: str | None = None
    expected_period: str | None = None  # annual | monthly | weekly | daily | hourly
    current_salary: float | None = None
    current_currency: str | None = None
    current_period: str | None = None

    @field_validator("expected_period", "current_period")
    @classmethod
    def _check_period(cls, value: str | None) -> str | None:
        cleaned = _clean_str(value)
        if cleaned is None:
            return None
        cleaned = cleaned.casefold()
        if cleaned not in PAY_PERIODS:
            raise ValueError(f"pay period must be one of {PAY_PERIODS}")
        return cleaned

    @field_validator("expected_currency", "current_currency")
    @classmethod
    def _check_currency(cls, value: str | None) -> str | None:
        cleaned = _clean_str(value)
        if cleaned is None:
            return None
        if len(cleaned) > 8:
            raise ValueError("currency code is too long")
        return cleaned.upper()

    @field_validator("expected_salary", "current_salary")
    @classmethod
    def _check_amount(cls, value: float | None) -> float | None:
        if value is None:
            return None
        if value < 0:
            raise ValueError("salary cannot be negative")
        if value > 1_000_000_000:
            raise ValueError("salary is implausibly large")
        return float(value)


class NoticePeriod(BaseModel):
    """Notice period and availability, with zero meaning "immediate"."""

    notice_days: int | None = None
    available_from: date | None = None
    #: Distinguishes "no notice period" (0) from "not answered" (None).
    immediate: bool | None = None

    @field_validator("notice_days")
    @classmethod
    def _check_days(cls, value: int | None) -> int | None:
        if value is None:
            return None
        if value < 0:
            raise ValueError("notice_days cannot be negative")
        if value > 365:
            raise ValueError("notice_days is implausibly large (max 365)")
        return int(value)


class ApplicationAnswers(BaseModel):
    """The answers a form asks for, grounded in user-confirmed values."""

    work_authorization: WorkAuthorizationInfo = Field(default_factory=WorkAuthorizationInfo)
    compensation: Compensation = Field(default_factory=Compensation)
    notice: NoticePeriod = Field(default_factory=NoticePeriod)


class ApplicationProfile(BaseModel):
    """The user-confirmed application profile (kept separate from the résumé).

    ``confirmed_fields`` lists the dotted paths the user explicitly confirmed,
    so a caller can tell a *confirmed* value from an imported one and label a
    form answer's provenance honestly.
    """

    professional: ProfessionalInfo = Field(default_factory=ProfessionalInfo)
    preferences: JobSearchPreferences = Field(default_factory=JobSearchPreferences)
    answers: ApplicationAnswers = Field(default_factory=ApplicationAnswers)
    confirmed_fields: list[str] = Field(default_factory=list)

    @field_validator("confirmed_fields")
    @classmethod
    def _check_confirmed(cls, value: list[str]) -> list[str]:
        if len(value) > 200:
            raise ValueError("too many confirmed fields (max 200)")
        return [f for f in (_clean_str(item) for item in value) if f is not None]
