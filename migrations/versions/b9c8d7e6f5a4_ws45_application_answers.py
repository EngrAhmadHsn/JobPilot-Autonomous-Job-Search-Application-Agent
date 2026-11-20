"""WS-45: the per-application answers a human saved

Revision ID: b9c8d7e6f5a4
Revises: 7a1b2c3d4e5f
Create Date: 2026-11-21

Adds ``application_answers`` — one row per (owner, application, question)
for the answers a human gave on the Review screen to the required employer
questions the profile cannot ground (``src/db/application_answers.py``).

No foreign keys, matching ``applications`` and ``application_events``: a
saved answer must outlive the rows it refers to, so the trail survives the
deletion of the object it describes. The referenced columns are indexed
instead, and reads are fenced by the *application's* ownership plus the
row's own owner (the answers table grants even a superuser no cross-owner
view — an answer to a work-authorization question is personal data).

The unique constraint is what makes the write an **upsert**: a re-answered
question updates its row in place and refreshes ``answered_at``, never
creating a second one.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b9c8d7e6f5a4"
down_revision: str | Sequence[str] | None = "7a1b2c3d4e5f"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _has_table(table: str) -> bool:
    """Whether a table already exists (the upgrade is idempotent).

    SQLite has no transactional DDL, so a migration that fails half-way
    leaves its tables behind while the version table still records the old
    revision. An upgrade that cannot be re-run strands the schema.
    """
    bind = op.get_bind()
    if bind is None:
        return False
    try:
        inspector = sa.inspect(bind)
        return table in set(inspector.get_table_names())
    except Exception:
        # The offline render (``--sql``) has no inspection system: answer
        # "not there", so the statement is emitted.
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
    if not _has_table("application_answers"):
        op.create_table(
            "application_answers",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("owner_id", sa.String(), nullable=False),
            sa.Column("application_id", sa.String(), nullable=False),
            sa.Column("question_key", sa.String(), nullable=False),
            sa.Column("label", sa.String(), nullable=True),
            sa.Column("category", sa.String(), nullable=True),
            sa.Column("answer_text", sa.String(), nullable=False),
            sa.Column("answered_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint(
                "owner_id",
                "application_id",
                "question_key",
                name="uq_application_answers_identity",
            ),
        )

    if not _has_index("application_answers", "ix_application_answers_id"):
        op.create_index(op.f("ix_application_answers_id"), "application_answers", ["id"])
    if not _has_index("application_answers", "ix_application_answers_owner_id"):
        op.create_index(
            op.f("ix_application_answers_owner_id"), "application_answers", ["owner_id"]
        )
    if not _has_index("application_answers", "ix_application_answers_application_id"):
        op.create_index(
            op.f("ix_application_answers_application_id"),
            "application_answers",
            ["application_id"],
        )
    # The read the merge performs: one application's answers, in save order.
    if not _has_index("application_answers", "ix_application_answers_owner_application"):
        op.create_index(
            "ix_application_answers_owner_application",
            "application_answers",
            ["owner_id", "application_id"],
        )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("ix_application_answers_owner_application", table_name="application_answers")
    op.drop_index(op.f("ix_application_answers_application_id"), table_name="application_answers")
    op.drop_index(op.f("ix_application_answers_owner_id"), table_name="application_answers")
    op.drop_index(op.f("ix_application_answers_id"), table_name="application_answers")
    op.drop_table("application_answers")
