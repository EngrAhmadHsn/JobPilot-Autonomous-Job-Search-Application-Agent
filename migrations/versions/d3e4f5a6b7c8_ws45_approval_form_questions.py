"""WS-45: the approval keeps the board's question plan

Revision ID: d3e4f5a6b7c8
Revises: c2d3e4f5a6b7
Create Date: 2026-11-21

Adds ``approval_requests.form_questions`` — the question plan
(``label``, ``verdict``, ``category``, ``answer_from``, ``required``,
``block``) as it stood when the packet was prepared.

Before this column the plan existed only in the prepare response: a
per-application questions page had nothing durable to read, and rebuilding
it would have meant re-fetching the employer's live form — so the page
would show whatever the board publishes today, not the questions the
reviewed packet was built around. Storing the plan makes the questions
page answer for the packet that actually exists.

Nullable and additive: rows prepared before this revision carry no plan,
and the questions endpoint reports ``plan_available=false`` for them rather
than inventing one.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d3e4f5a6b7c8"
down_revision: str | Sequence[str] | None = "c2d3e4f5a6b7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _has_column(table: str, column: str) -> bool:
    """Whether a column already exists on a table.

    SQLite has no transactional DDL, so a failed half-way migration leaves
    the column in place while the version table still records the old
    revision. The upgrade is therefore idempotent: it adds what is missing
    and skips what is already there.
    """
    bind = op.get_bind()
    if bind is None:
        return False
    try:
        inspector = sa.inspect(bind)
        existing = {col["name"] for col in inspector.get_columns(table)}
    except Exception:
        # The offline render hands the migration a MockConnection, which has
        # no inspection system — answer "missing" so the statement is emitted.
        return False
    return column in existing


def upgrade() -> None:
    """Upgrade schema."""
    if not _has_column("approval_requests", "form_questions"):
        op.add_column(
            "approval_requests",
            sa.Column("form_questions", sa.JSON(), nullable=True),
        )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("approval_requests", "form_questions")
