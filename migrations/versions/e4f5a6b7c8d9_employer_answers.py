"""Account-owned answers for one stored posting and employer question revision.

Revision ID: e4f5a6b7c8d9
Revises: d3e4f5a6b7c8
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "e4f5a6b7c8d9"
down_revision: str | Sequence[str] | None = "d3e4f5a6b7c8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "employer_answers",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("owner_id", sa.String(), nullable=False),
        sa.Column("job_id", sa.String(), nullable=False),
        sa.Column("company_name", sa.String(), nullable=False),
        sa.Column("job_title", sa.String(), nullable=False),
        sa.Column("question_key", sa.String(length=64), nullable=False),
        sa.Column("question", sa.JSON(), nullable=False),
        sa.Column("answer", sa.JSON(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "owner_id", "job_id", "question_key", name="uq_employer_answers_question"
        ),
    )
    op.create_index(
        "ix_employer_answers_owner_updated", "employer_answers", ["owner_id", "updated_at"]
    )
    op.create_table(
        "local_fill_grants",
        sa.Column("application_id", sa.String(), primary_key=True),
        sa.Column("owner_id", sa.String(), nullable=False),
        sa.Column("code_digest", sa.String(64), nullable=False, unique=True),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("used_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_local_fill_grants_owner_id", "local_fill_grants", ["owner_id"])


def downgrade() -> None:
    op.drop_index("ix_local_fill_grants_owner_id", table_name="local_fill_grants")
    op.drop_table("local_fill_grants")
    op.drop_index("ix_employer_answers_owner_updated", table_name="employer_answers")
    op.drop_table("employer_answers")
