"""ws28 required years mined

Revision ID: 5cf9cea73955
Revises: f4a5b6c7d8e9
Create Date: 2026-11-12 17:24:38.277867

WS-28. ``jobs.required_years`` is NULL both for a row written before WS-23b
(never mined) and for a row that was mined and states no bar. The read path
treated both as "never mined" and re-mined them — 20.6 s of every cold start
across 6,741 rows, for an answer that could not change.

This migration adds the marker that tells the two apart. Existing rows that
already carry a value are obviously decided; rows with a NULL keep the marker
false, so they are mined once more (with the corrected miner) and are never
mined again.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "5cf9cea73955"
down_revision: str | Sequence[str] | None = "f4a5b6c7d8e9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add the marker that distinguishes 'never mined' from 'no bar'."""
    op.add_column(
        "jobs",
        sa.Column(
            "required_years_mined",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    # A row that carries a value has plainly been decided. A NULL keeps the
    # default (false) and will be mined once, then marked.
    op.execute("UPDATE jobs SET required_years_mined = true WHERE required_years IS NOT NULL")


def downgrade() -> None:
    """Drop the marker; ``required_years`` keeps every value it holds."""
    op.drop_column("jobs", "required_years_mined")
