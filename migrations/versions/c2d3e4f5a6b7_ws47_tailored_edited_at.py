"""WS-47: the tailored resume records when the candidate last edited it

Revision ID: c2d3e4f5a6b7
Revises: b9c8d7e6f5a4
Create Date: 2026-11-21

The Resume Studio can now save an edit to a stored tailoring
(``PUT /api/tailored/{id}``): the edited sections are revalidated against the
profile, the ATS report is re-run, and the deliverable is re-produced through
the WS-31 in-place path, all persisted onto the same row.

Every content column on that row is *replaced* by an edit, so nothing in the
row itself would distinguish the candidate's own words from the agent's
original proposal. ``edited_at`` is that distinction: ``NULL`` is the honest
"never edited — this is the tailoring run's output", a timestamp says the
candidate saved wording of their own, and the console's status chip reads it
("Diff review · proposed" vs "Diff review · edited by you").

Nullable, like every column added to this table after the first release: the
rows that predate the studio were never edited, which is exactly what ``NULL``
here asserts.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c2d3e4f5a6b7"
down_revision: str | Sequence[str] | None = "b9c8d7e6f5a4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _has_column(table: str, column: str) -> bool:
    """Whether a column already exists on a table.

    SQLite has no transactional DDL, so a migration that fails half-way leaves
    its columns in place while the version table still records the old
    revision. The upgrade is therefore **idempotent**: it adds what is missing
    and skips what is already there, so re-running it cannot strand the schema.
    """
    bind = op.get_bind()
    if bind is None:
        return False
    try:
        inspector = sa.inspect(bind)
        existing = {col["name"] for col in inspector.get_columns(table)}
    except Exception:
        # The offline render (``alembic upgrade --sql``) has no inspection
        # system; there is nothing to inspect, so the statement is emitted.
        return False
    return column in existing


def upgrade() -> None:
    """Upgrade schema."""
    if not _has_column("tailored_resumes", "edited_at"):
        op.add_column("tailored_resumes", sa.Column("edited_at", sa.DateTime(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("tailored_resumes", "edited_at")
