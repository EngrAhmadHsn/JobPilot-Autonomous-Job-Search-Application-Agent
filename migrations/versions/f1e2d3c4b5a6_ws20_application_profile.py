"""WS-20: the candidate application profile and the isolated EEO table

Revision ID: f1e2d3c4b5a6
Revises: a7b8c9d0e1f2
Create Date: 2026-11-07

Two additions, both additive and reversible:

- ``candidate_profiles.application_json`` — a **nullable** JSON column holding
  the user-confirmed application profile (job-search preferences and the
  answers a résumé does not carry). Nullable so every existing row stays valid
  and reads back as an empty profile.
- ``candidate_eeo`` — voluntary self-identification data in its own table,
  owner-scoped, never joined into the résumé read or the matcher. One row per
  profile (``profile_id`` is the primary key).

Portable DDL: plain ``JSON``/``String``/``DateTime`` columns, no
dialect-specific types.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "f1e2d3c4b5a6"
down_revision: str | Sequence[str] | None = "a7b8c9d0e1f2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add the application-profile column and the EEO table."""
    op.add_column(
        "candidate_profiles",
        sa.Column("application_json", sa.JSON(), nullable=True),
    )
    op.create_table(
        "candidate_eeo",
        sa.Column("profile_id", sa.String(), nullable=False),
        sa.Column("owner_id", sa.String(), nullable=False, server_default="legacy"),
        sa.Column("data", sa.JSON(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("profile_id"),
    )
    op.create_index("ix_candidate_eeo_owner_id", "candidate_eeo", ["owner_id"])


def downgrade() -> None:
    """Drop the EEO table and the application-profile column."""
    op.drop_index("ix_candidate_eeo_owner_id", table_name="candidate_eeo")
    op.drop_table("candidate_eeo")
    op.drop_column("candidate_profiles", "application_json")
