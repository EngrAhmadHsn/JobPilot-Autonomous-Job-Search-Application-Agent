"""WS-22: model credentials, sponsor registers and the style report column

Revision ID: b3c4d5e6f7a8
Revises: f1e2d3c4b5a6
Create Date: 2026-11-08

Three additive, reversible changes:

- ``llm_credentials`` — one row per user, holding their own encrypted model
  key (bring-your-own-key). ``owner_id`` is the primary key: the owner *is*
  the credential, so there is no second identifier to guess. The key column
  stores a Fernet token, never the plaintext.
- ``visa_sponsors`` — imported rows from the official USCIS H-1B Employer
  Data Hub and the UK Home Office sponsor register. Shared reference data,
  deliberately not owner-scoped, with an index on the normalized company
  name the lookup uses.
- ``tailored_resumes.style`` — a **nullable** JSON column holding the
  deterministic style report (banned phrases, weak phrases, quantified
  bullets). Nullable so every existing row stays valid and reads back as an
  empty report.

Portable DDL: plain ``String``/``Integer``/``DateTime`` columns, no
dialect-specific types.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b3c4d5e6f7a8"
down_revision: str | Sequence[str] | None = "f1e2d3c4b5a6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create the two tables and add the style column."""
    op.create_table(
        "llm_credentials",
        sa.Column("owner_id", sa.String(), nullable=False),
        sa.Column("provider", sa.String(), nullable=False),
        sa.Column("model", sa.String(), nullable=False),
        sa.Column("base_url", sa.String(), nullable=True),
        sa.Column("encrypted_key", sa.String(), nullable=False),
        sa.Column("hint", sa.String(), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.Column("last_used_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("owner_id"),
    )
    op.create_table(
        "visa_sponsors",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("name_normalized", sa.String(), nullable=False),
        sa.Column("name_raw", sa.String(), nullable=False),
        sa.Column("source", sa.String(), nullable=False),
        sa.Column("country", sa.String(), nullable=False),
        sa.Column("year", sa.Integer(), nullable=True),
        sa.Column("approvals", sa.Integer(), nullable=True),
        sa.Column("denials", sa.Integer(), nullable=True),
        sa.Column("detail", sa.String(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_visa_sponsors_name_normalized", "visa_sponsors", ["name_normalized"])
    op.create_index("ix_visa_sponsors_source_year", "visa_sponsors", ["source", "year"])
    op.add_column("tailored_resumes", sa.Column("style", sa.JSON(), nullable=True))


def downgrade() -> None:
    """Drop the column and both tables (indexes go with them)."""
    op.drop_column("tailored_resumes", "style")
    op.drop_index("ix_visa_sponsors_source_year", table_name="visa_sponsors")
    op.drop_index("ix_visa_sponsors_name_normalized", table_name="visa_sponsors")
    op.drop_table("visa_sponsors")
    op.drop_table("llm_credentials")
