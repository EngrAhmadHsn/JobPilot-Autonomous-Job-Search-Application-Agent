"""WS-05: tailored_resumes table

Revision ID: c9a4f1e2d3b7
Revises: b8e2c94d1f57
Create Date: 2026-10-21

Adds the WS-05 persistence layer (docs/implementation/05-tailoring-and-research.md):

- ``tailored_resumes`` <- src.db.tailored.TailoredResumeDB

JSON columns are emitted as portable ``sa.JSON()`` (valid on SQLite and
PostgreSQL). The table carries no foreign keys by design: a tailoring record
may outlive the profile or job rows it refers to (same reasoning as
``job_matches``).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c9a4f1e2d3b7"
down_revision: str | Sequence[str] | None = "b8e2c94d1f57"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "tailored_resumes",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("profile_id", sa.String(), nullable=False),
        sa.Column("job_id", sa.String(), nullable=False),
        sa.Column("tailored", sa.JSON(), nullable=False),
        sa.Column("factuality", sa.JSON(), nullable=False),
        sa.Column("ats_report", sa.JSON(), nullable=False),
        sa.Column("insights", sa.JSON(), nullable=True),
        sa.Column("docx_path", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_tailored_resumes_profile_id"), "tailored_resumes", ["profile_id"], unique=False
    )
    op.create_index(
        op.f("ix_tailored_resumes_job_id"), "tailored_resumes", ["job_id"], unique=False
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f("ix_tailored_resumes_job_id"), table_name="tailored_resumes")
    op.drop_index(op.f("ix_tailored_resumes_profile_id"), table_name="tailored_resumes")
    op.drop_table("tailored_resumes")
