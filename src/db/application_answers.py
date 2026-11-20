"""The per-application answers a human gave (WS-45).

A required employer question that the profile cannot answer stops the flow
(``needs_human``). WS-25b surfaced those questions; nothing could *record*
the answer, so the console had no path through the Review screen. This
table is where the answer lives: one row per (application, question), keyed
by the ``question_key`` the console saves under — which is the question's
normalized label or its taxonomy category.

The row carries what the human actually answered, and *when*: ``answered_at``
is refreshed on every upsert, so "5 of 6 answers confirmed" in the Review
design (``04 · Review · 1440``) reads off the data.

Two properties the design insists on:

- **The answer is the human's own.** The rows are owner-scoped like every
  user table, and the accessors in :mod:`src.db.access` grant even a
  superuser no cross-owner view: an answer to "are you authorized to work
  in this country" is personal data, not audit telemetry.
- **The taxonomy still governs.** EEO and attestation categories
  (:data:`src.applications.questions.NEVER_AUTOFILL`) are refused by the
  write path before they ever reach this table — the employer asks those
  on their own site, and storing them here would make the console look
  like a place that collects them.

No foreign keys, matching ``applications`` and ``application_events``: a
saved answer must outlive the rows it refers to. The columns are indexed
instead, and reads are fenced by the *application's* ownership first.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import DateTime, Index, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from src.db.base import Base
from src.db.users import LEGACY_OWNER_ID


class ApplicationAnswerDB(Base):
    """One answer a human saved for one question of one application."""

    __tablename__ = "application_answers"

    # The autoincrement id is the stable read order: answers are listed in
    # the order they were first saved, and a re-answer updates in place.
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True, index=True)
    #: The principal that owns this row (WS-13 · A0). NOT NULL and indexed:
    #: ownership is a column, not a convention a route has to remember.
    #: Every access goes through ``src.db.access``.
    owner_id: Mapped[str] = mapped_column(
        String,
        nullable=False,
        index=True,
        default=LEGACY_OWNER_ID,
        server_default=LEGACY_OWNER_ID,
    )
    application_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    #: The stable key the console saves under: the question's normalized
    #: label, or its taxonomy category. Matching at merge time is
    #: normalized (and also tries the stored label and the category), so a
    #: client that echoes the raw label still matches.
    question_key: Mapped[str] = mapped_column(String, nullable=False)
    #: The board's own wording, as the console displayed it. ``None`` when
    #: the client had only the key.
    label: Mapped[str | None] = mapped_column(String, nullable=True)
    #: The taxonomy category, when the client knew it. ``None`` is allowed:
    #: the merge classifies the label when it needs the category.
    category: Mapped[str | None] = mapped_column(String, nullable=True)
    #: What the human answered. Free text: the console sends "Yes"/"No"
    #: for booleans and the typed value otherwise, and the browser layer
    #: refuses to fill a checkbox with a token it cannot interpret.
    answer_text: Mapped[str] = mapped_column(String, nullable=False)
    #: When the human gave this answer — refreshed on every upsert.
    answered_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=lambda: datetime.now(UTC)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=lambda: datetime.now(UTC)
    )

    __table_args__ = (
        # One row per question per application. A re-answer updates the row;
        # it never creates a second one.
        UniqueConstraint(
            "owner_id",
            "application_id",
            "question_key",
            name="uq_application_answers_identity",
        ),
        Index("ix_application_answers_owner_application", "owner_id", "application_id"),
    )
