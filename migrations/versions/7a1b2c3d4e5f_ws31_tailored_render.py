"""WS-31: the tailoring result records how its deliverable was produced

Revision ID: 7a1b2c3d4e5f
Revises: 5cf9cea73955
Create Date: 2026-11-13

The deliverable used to be one thing: a document the WS-05 renderer wrote from
scratch. It is now the candidate's **own uploaded résumé, edited in place** —
their fonts, their section order, their extra sections — with the from-scratch
renderer becoming a fallback for the cases where the original cannot be edited
(a missing file, an unreadable one, an unsupported format).

The difference matters to the candidate, so it is stored rather than inferred:
a rewrite must never be presented as an edit of their own document. The column
is a JSON document (``RenderReport``) that carries the mode, the counts of what
changed, and the reasons for anything that could not be done.

Nullable, so every row written before this column existed stays valid. A NULL
reads back as the **regenerated** verdict, which is what those rows are: they
all came from the from-scratch renderer.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "7a1b2c3d4e5f"
down_revision: str | Sequence[str] | None = "5cf9cea73955"
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
    if not _has_column("tailored_resumes", "render"):
        op.add_column("tailored_resumes", sa.Column("render", sa.JSON(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("tailored_resumes", "render")
