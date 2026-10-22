"""WS-15: the corpus's eviction clock

Revision ID: c3d4e5f6a7b8
Revises: b2c3d4e5f6a7
Create Date: 2026-10-22

Adds ``jobs.last_seen_at`` — the moment a listing was last served by a
board (docs/implementation/15-attack-surface-round-two.md, Phase B).

The corpus is capped, and the cap used to be a one-way door: once the
corpus was full, the admission control admitted **nothing** — from any
source, ever again — and nothing in the retention pass pruned the table.
A flood of fake listings could therefore end the application's life with
five refreshes and no way back.

Eviction needs to know which rows are stale, and "stale" is not the same
as "posted longest ago": a listing the boards keep serving is live however
old its posting is. So the column records the *sighting*, which the
refresh stamps on every listing it persists, and the eviction takes the
rows with the oldest sighting.

The column is nullable: a row that has never been seen has no sighting,
and a row with no sighting is evicted before a row that has one — there is
no evidence it is still live.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c3d4e5f6a7b8"
down_revision: str | Sequence[str] | None = "b2c3d4e5f6a7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column("jobs", sa.Column("last_seen_at", sa.DateTime(), nullable=True))
    op.create_index(op.f("ix_jobs_last_seen_at"), "jobs", ["last_seen_at"], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f("ix_jobs_last_seen_at"), table_name="jobs")
    op.drop_column("jobs", "last_seen_at")
