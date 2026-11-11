"""The questions the boards actually ask (WS-25b).

The profile asks the user a **guessed** set of fields. The boards' own
schemas state what they *actually* ask — Greenhouse publishes them at
``GET .../jobs/{id}?questions=true`` — and nothing recorded that.

Measured once as a probe (2026-11-11, 12 live boards, 12 jobs each):
**310 distinct labels, 1,455 occurrences**, and **10 of the 22
most-asked labels were unclassified by the taxonomy — 51% of all
occurrences**. That probe is why this table exists: a measurement that
lives in a chat log is not a measurement the product can use.

The table is **shared**, like ``jobs`` and ``job_boards``: the questions
are a property of the boards, not of a user. The per-user part is the
*gap* — which of these the profile already answers — and that is
computed at read time against the profile.

Design notes:

* **The label is kept verbatim.** "Resume/CV", "Please select the
  country where you currently reside.\\n" — the board's own wording is
  the evidence, and normalizing it away would destroy the thing being
  measured.
* **`times_seen` accumulates.** A question asked by 118 of the boards a
  user watches is worth asking about; one asked once is not. The count
  is the whole point.
* **The category is the taxonomy verdict at record time**, so a later
  taxonomy improvement does not silently rewrite history — a re-sweep
  updates it.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import Boolean, DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from src.db.base import Base

logger = logging.getLogger(__name__)

__all__ = [
    "FormQuestionDB",
    "ObservedQuestion",
    "QuestionGap",
    "question_gaps",
    "record_questions",
]


class FormQuestionDB(Base):
    """One question a board asks, and how often it was seen."""

    __tablename__ = "form_questions"

    #: ``"{ats}:{board}:{normalized label}"`` — one row per distinct
    #: question per board.
    id: Mapped[str] = mapped_column(String(length=200), primary_key=True)
    ats: Mapped[str] = mapped_column(String(length=32), nullable=False, index=True)
    board: Mapped[str] = mapped_column(String(length=128), nullable=False, index=True)
    #: The board's own wording, verbatim.
    label: Mapped[str] = mapped_column(String(length=300), nullable=False)
    #: The form field the answer is submitted as (``first_name``,
    #: ``question_69650990``).
    field_name: Mapped[str | None] = mapped_column(String(length=200), nullable=True)
    #: ``input_text``, ``multi_value_single_select``, …
    field_type: Mapped[str | None] = mapped_column(String(length=64), nullable=True)
    required: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    #: Which block the question came from: ``questions``,
    #: ``location_questions``, ``compliance``, ``demographic_questions``.
    block: Mapped[str] = mapped_column(String(length=32), nullable=False, default="questions")
    #: The taxonomy verdict at record time.
    category: Mapped[str | None] = mapped_column(String(length=64), nullable=True)
    #: How many times the board asked it (accumulated across sweeps).
    times_seen: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    first_seen_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


@dataclass
class ObservedQuestion:
    """One observation of a question, before it is stored."""

    label: str
    board: str
    ats: str = "greenhouse"
    field_name: str | None = None
    field_type: str | None = None
    required: bool = False
    block: str = "questions"
    category: str | None = None


@dataclass
class QuestionGap:
    """A question the boards ask, and whether the profile answers it."""

    label: str
    times_seen: int
    required: bool
    category: str
    block: str
    #: ``answered`` — the profile has it; ``unclassified`` — the taxonomy
    #: does not recognize the label; ``not_in_profile`` — recognized but
    #: the profile is empty; ``never_autofill`` — consent/EEO, always a
    #: human's.
    coverage: str
    boards: int = 1

    @property
    def is_actionable(self) -> bool:
        """Whether asking the user for this would improve the profile.

        A question the boards never ask is not worth asking; one the
        profile already answers needs nothing; and one that is consent or
        EEO is never the agent's to answer — so none of those is a gap the
        profile screen should prompt for.
        """
        return self.coverage in {"unclassified", "not_in_profile"}


_WHITESPACE_RE = re.compile(r"\s+")

#: How a label becomes part of a stable id. The *stored* label is the
#: verbatim one; only the id is normalized.
_ID_RE = re.compile(r"[^a-z0-9]+")


def _normalize_label(label: str) -> str:
    """The id-safe form of a label."""
    collapsed = _WHITESPACE_RE.sub(" ", (label or "").strip()).casefold()
    return _ID_RE.sub("_", collapsed).strip("_")[:120]


def question_id(ats: str, board: str, label: str) -> str:
    """The stable identity of one board's question."""
    return f"{ats}:{board}:{_normalize_label(label)}"


def record_questions(
    observations: list[ObservedQuestion],
    *,
    session_factory=None,
) -> int:
    """Upsert a batch of observations, accumulating ``times_seen``.

    The count is per (board, question) pair: a board that asks "Cover
    Letter" on 40 of its listings has asked it 40 times, and that is what
    makes the frequency meaningful.

    Returns:
        The number of rows written.
    """
    from src.db.session import SessionLocal

    if not observations:
        return 0
    factory = session_factory or SessionLocal
    now = datetime.now(UTC)
    written = 0
    with factory() as session:
        # A single sweep sees the same question on many jobs, so the same
        # id arrives several times in one batch. A dict of the rows this
        # call created-or-loaded is what makes the accumulation correct —
        # ``session.get`` does not see a row that has not been flushed,
        # so the second occurrence would try to insert the same id again.
        seen: dict[str, FormQuestionDB] = {}
        for observation in observations:
            row_id = question_id(observation.ats, observation.board, observation.label)
            row = seen.get(row_id)
            if row is None:
                row = session.get(FormQuestionDB, row_id)
                if row is None:
                    row = FormQuestionDB(
                        id=row_id,
                        ats=observation.ats,
                        board=observation.board,
                        label=observation.label[:300],
                        field_name=(observation.field_name or None),
                        field_type=(observation.field_type or None),
                        required=observation.required,
                        block=observation.block,
                        category=observation.category,
                        times_seen=0,
                        first_seen_at=now,
                        last_seen_at=now,
                    )
                    session.add(row)
                seen[row_id] = row
            row.times_seen = int(row.times_seen or 0) + 1
            row.last_seen_at = now
            # The latest sweep's classification wins: a taxonomy
            # improvement should not be frozen out by history.
            if observation.category is not None:
                row.category = observation.category
            if observation.field_name:
                row.field_name = observation.field_name
            if observation.field_type:
                row.field_type = observation.field_type
            # Required is **monotonic**: a question required by any board
            # that asks it is a required question, so a later optional
            # sighting must not downgrade it.
            row.required = bool(row.required or observation.required)
            written += 1
        session.commit()
    return written


def question_gaps(
    profile=None,
    *,
    session_factory=None,
    limit: int = 50,
    include_answered: bool = False,
) -> list[QuestionGap]:
    """The questions the boards ask, ranked, with the profile's coverage.

    Args:
        profile: A ``CandidateProfile`` (or an ``ApplicationProfile``) to
            check coverage against. ``None`` means every question is
            unanswerable, which is the honest answer for a user who has
            not filled anything in.
        limit: How many to return.
        include_answered: Include the questions the profile already
            covers — useful for the console's "already handled" section,
            not for prompting.

    Returns:
        The gaps, most-asked first.
    """
    from src.db.session import SessionLocal

    factory = session_factory or SessionLocal
    with factory() as session:
        rows = session.query(FormQuestionDB).all()

    if not rows:
        return []

    # The labels the profile currently answers, by taxonomy category.
    answered_categories = _answered_categories(profile)

    # Aggregate by label: "asked by 118 of the boards you watch" is the
    # number the console shows, and it is per label, not per board row.
    aggregated: dict[str, QuestionGap] = {}
    for row in rows:
        category = row.category or "unknown"
        label_key = _normalize_label(row.label)
        if not label_key:
            continue
        existing = aggregated.get(label_key)
        boards = 1
        if existing is None:
            gap = QuestionGap(
                label=row.label,
                times_seen=int(row.times_seen or 0),
                required=bool(row.required),
                category=category,
                block=row.block or "questions",
                coverage=_coverage_for(category, answered_categories),
                boards=boards,
            )
        else:
            gap = existing
            gap.times_seen += int(row.times_seen or 0)
            gap.required = gap.required or bool(row.required)
            gap.boards += 1
        aggregated[label_key] = gap

    gaps = list(aggregated.values())
    if not include_answered:
        gaps = [gap for gap in gaps if gap.is_actionable]
    gaps.sort(key=lambda gap: (-gap.times_seen, -gap.boards, gap.label.casefold()))
    return gaps[: max(1, limit)]


#: The profile fields that answer each taxonomy category.
#:
#: This is the join between "what the boards ask" and "what we have". It
#: is deliberately explicit: a category is answered only when the profile
#: has a field for it, so the gap read cannot claim coverage it does not
#: have.
_CATEGORY_PROFILE_FIELDS: dict[str, tuple[str, ...]] = {
    "email": ("email",),
    "phone": ("phone",),
    "location": ("location",),
    "country": ("country",),
    "linkedin_url": ("linkedin_url",),
    "github_url": ("github_url",),
    "portfolio_url": ("portfolio_url", "website"),
    "work_authorization": ("legally_authorized",),
    "visa_sponsorship": ("requires_sponsorship",),
    "citizenship_status": ("citizenship_status",),
    "desired_salary": ("expected_salary", "min_salary"),
    "current_salary": ("current_salary",),
    "salary_currency": ("expected_currency", "salary_currency"),
    "notice_period": ("notice_period_days",),
    "seniority_level": ("seniority_level",),
    "total_experience": ("total_experience_years",),
    "resume": ("resume",),
    "cover_letter": ("cover_letter",),
}


def _answered_categories(profile) -> set[str]:
    """The taxonomy categories the given profile can answer."""
    if profile is None:
        return set()
    answered: set[str] = set()
    for category, field_names in _CATEGORY_PROFILE_FIELDS.items():
        for name in field_names:
            if _profile_has(profile, name):
                answered.add(category)
                break
    return answered


def _profile_has(profile, field_name: str, depth: int = 0) -> bool:
    """Whether a profile carries a non-empty value for a field name.

    Walks the nested application profile, so a caller passes the whole
    ``CandidateProfile`` and this finds ``answers.compensation.
    expected_currency`` without each caller knowing the nesting.
    """
    if profile is None or depth > 6:
        return False
    if isinstance(profile, dict):
        value = profile.get(field_name)
        if _is_meaningful(value):
            return True
        for nested in profile.values():
            if isinstance(nested, (dict, list)) and _profile_has(nested, field_name, depth + 1):
                return True
        return False
    value = getattr(profile, field_name, None)
    if _is_meaningful(value):
        return True
    for attribute in (
        "application_profile",
        "answers",
        "compensation",
        "notice",
        "preferences",
        "professional",
        "personal_information",
    ):
        nested = getattr(profile, attribute, None)
        if nested is not None and _profile_has(nested, field_name, depth + 1):
            return True
    return False


def _is_meaningful(value) -> bool:
    """Whether a value is a real answer rather than an empty default."""
    if value is None or value is False:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, (list, tuple, set, dict)):
        return bool(value)
    return True


def _coverage_for(category: str, answered_categories: set[str]) -> str:
    """Classify a question against the profile."""
    from src.applications.questions import NEVER_AUTOFILL, QuestionCategory

    try:
        resolved = QuestionCategory(category)
    except ValueError:
        return "unclassified"
    if resolved in NEVER_AUTOFILL:
        return "never_autofill"
    if resolved.value == "unknown":
        return "unclassified"
    if resolved.value in answered_categories:
        return "answered"
    return "not_in_profile"
