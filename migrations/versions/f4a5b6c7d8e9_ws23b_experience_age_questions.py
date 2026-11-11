"""WS-23b: the mined experience bar, the corpus's age, and the questions store

Revision ID: f4a5b6c7d8e9
Revises: e3f4a5b6c7d8
Create Date: 2026-11-11

Three additions, each closing a hole a later review found.

1. **``jobs.required_years``** — the experience bar, mined once at write
   time instead of re-mined on every search.

   ``experience_requirements`` is 0% populated: the boards publish
   ``employment_required`` / ``employment_optional`` on only some of
   them, and nothing wrote a value back. The *mining* already existed
   (``src/matching/experience.required_years``), it simply ran at read
   time — 9.5 s of the 32.56 s artifacts rebuild, the most expensive
   per-listing item.

   The column is **separate** from ``experience_requirements`` on
   purpose. That column is what the *board* stated; this one is what the
   system *inferred* from the description. Collapsing them would make an
   inference indistinguishable from a published fact, and the score
   states exist precisely to keep that distinction honest.

2. **``jobs.first_seen_at``** — when the system first saw a listing.

   The corpus can say "seen at" but not "seen since", so it cannot
   compute an age for the rows whose ``posted_at`` is missing
   (Remotive, some Lever postings). The expiry work needs both.

3. **``form_questions``** — the questions the boards actually ask.

   WS-25's schema work showed **310 distinct labels across 12 boards,
   with 10 of the 22 most-asked labels unclassified (51% of
   occurrences)**. The profile asks a *guessed* set of fields; this
   table is where the *measured* set lives.

   Shared, like ``jobs`` and ``job_boards``: the questions are a property
   of the boards, not of a user.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "f4a5b6c7d8e9"
down_revision: str | Sequence[str] | None = "e3f4a5b6c7d8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _has_column(table: str, column: str) -> bool:
    """Whether a column already exists (the upgrade is idempotent).

    SQLite has no transactional DDL, so a migration that fails half-way
    leaves its columns behind while the version table still records the
    old revision. An upgrade that cannot be re-run strands the schema.
    """
    bind = op.get_bind()
    if bind is None:
        return False
    try:
        inspector = sa.inspect(bind)
        return column in {col["name"] for col in inspector.get_columns(table)}
    except Exception:
        # The offline render (``--sql``) has no inspection system: answer
        # "not there", so the statement is emitted.
        return False


def _has_table(table: str) -> bool:
    """Whether a table already exists."""
    bind = op.get_bind()
    if bind is None:
        return False
    try:
        inspector = sa.inspect(bind)
        return table in set(inspector.get_table_names())
    except Exception:
        return False


def _has_index(table: str, index: str) -> bool:
    """Whether an index already exists."""
    bind = op.get_bind()
    if bind is None:
        return False
    try:
        inspector = sa.inspect(bind)
        return index in {ix["name"] for ix in inspector.get_indexes(table)}
    except Exception:
        return False


def upgrade() -> None:
    """Upgrade schema."""
    # -- 1. the mined experience bar --------------------------------------
    if not _has_column("jobs", "required_years"):
        op.add_column("jobs", sa.Column("required_years", sa.Float(), nullable=True))

    # -- 2. the first sighting --------------------------------------------
    if not _has_column("jobs", "first_seen_at"):
        op.add_column("jobs", sa.Column("first_seen_at", sa.DateTime(), nullable=True))
    if not _has_index("jobs", "ix_jobs_first_seen_at"):
        op.create_index(op.f("ix_jobs_first_seen_at"), "jobs", ["first_seen_at"], unique=False)

    # Backfill ``first_seen_at`` from ``last_seen_at`` where it is known.
    # The two are the same value for a row that has only been seen once,
    # and "seen at T" is the best available lower bound for "seen since".
    # A NULL ``last_seen_at`` stays NULL — the WS-23 backfill already
    # stamped those, so this matches.
    bind = op.get_bind()
    if bind is not None:
        result = bind.execute(
            sa.text(
                "UPDATE jobs SET first_seen_at = last_seen_at "
                "WHERE first_seen_at IS NULL AND last_seen_at IS NOT NULL"
            )
        )
        if result is None:
            return

    # -- 3. the observed questions ----------------------------------------
    if not _has_table("form_questions"):
        op.create_table(
            "form_questions",
            sa.Column("id", sa.String(length=200), primary_key=True),
            sa.Column("ats", sa.String(length=32), nullable=False, index=True),
            sa.Column("board", sa.String(length=128), nullable=False, index=True),
            sa.Column("label", sa.String(length=300), nullable=False),
            sa.Column("field_name", sa.String(length=200), nullable=True),
            sa.Column("field_type", sa.String(length=64), nullable=True),
            sa.Column("required", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("block", sa.String(length=32), nullable=False),
            sa.Column("category", sa.String(length=64), nullable=True),
            #: The numeric-friendly key: how many times the board asked it.
            sa.Column("times_seen", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("first_seen_at", sa.DateTime(), nullable=True),
            sa.Column("last_seen_at", sa.DateTime(), nullable=True),
        )
        op.create_index(
            "ix_form_questions_board_seen",
            "form_questions",
            ["board", "times_seen"],
            unique=False,
        )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("ix_form_questions_board_seen", table_name="form_questions")
    op.drop_table("form_questions")
    op.drop_index(op.f("ix_jobs_first_seen_at"), table_name="jobs")
    op.drop_column("jobs", "first_seen_at")
    op.drop_column("jobs", "required_years")
