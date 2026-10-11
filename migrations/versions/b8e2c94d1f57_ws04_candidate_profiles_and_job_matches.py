"""WS-04: candidate_profiles and job_matches tables

Revision ID: b8e2c94d1f57
Revises: 171f645abf1a
Create Date: 2026-10-11

Adds the WS-04 persistence layer (docs/implementation/04-pipeline-and-api.md):

- ``candidate_profiles`` <- src.db.profiles.CandidateProfileDB
- ``job_matches``        <- src.db.matches.JobMatchDB

JSON columns are emitted as portable ``sa.JSON()`` (valid on SQLite and
PostgreSQL). ``job_matches`` carries no foreign keys by design: match history
may outlive the referenced profile or job rows.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b8e2c94d1f57"
down_revision: str | Sequence[str] | None = "171f645abf1a"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "candidate_profiles",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=True),
        sa.Column("email", sa.String(), nullable=True),
        sa.Column("phone", sa.String(), nullable=True),
        sa.Column("location", sa.String(), nullable=True),
        sa.Column("title", sa.String(), nullable=True),
        sa.Column("profile_json", sa.JSON(), nullable=False),
        sa.Column("file_path", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "job_matches",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("profile_id", sa.String(), nullable=False),
        sa.Column("job_id", sa.String(), nullable=False),
        sa.Column("scores", sa.JSON(), nullable=False),
        sa.Column("explanation", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_job_matches_profile_id"), "job_matches", ["profile_id"], unique=False)
    op.create_index(op.f("ix_job_matches_job_id"), "job_matches", ["job_id"], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f("ix_job_matches_job_id"), table_name="job_matches")
    op.drop_index(op.f("ix_job_matches_profile_id"), table_name="job_matches")
    op.drop_table("job_matches")
    op.drop_table("candidate_profiles")
