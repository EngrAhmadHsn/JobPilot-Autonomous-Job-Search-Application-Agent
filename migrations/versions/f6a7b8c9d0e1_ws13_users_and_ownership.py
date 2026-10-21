"""WS-13: the users table and per-row ownership

Revision ID: f6a7b8c9d0e1
Revises: e5f6a7b8c9d0
Create Date: 2026-10-21

Adds the **ownership spine** of WS-13 (docs/implementation/13-appsec-hardening.md,
Phase A0). The threat model changed: the caller is no longer assumed to be
the operator, so every row that belongs to a person needs a *principal* that
owns it, and every read of it has to be filtered by that principal.

What this migration does:

- creates ``users`` <- src.db.users.UserDB, the principal that owns data
  and acts;
- inserts the single ``legacy`` account that owns the rows that predate
  WS-13 — the existing data has no owner, and inventing a per-row owner
  would be a claim the data cannot support;
- adds a NOT NULL, indexed ``owner_id`` to every user-scoped table:
  ``candidate_profiles``, ``job_matches``, ``tailored_resumes``,
  ``applications``, ``application_events``, ``application_evidence``,
  ``approval_requests`` and ``audit_events``.

``jobs`` is deliberately **not** touched: it holds public board data and
is the one table that should be shared — it is what makes the matching
worth running.

The NOT NULL change is done in three steps (add nullable, backfill, then
constrain) because SQLite cannot alter a column's nullability in place.
Alembic's batch mode recreates the table for the last step, which is
portable to PostgreSQL.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "f6a7b8c9d0e1"
down_revision: str | Sequence[str] | None = "e5f6a7b8c9d0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


#: The user-scoped tables, with the column that identifies their owner.
OWNED_TABLES: tuple[str, ...] = (
    "candidate_profiles",
    "job_matches",
    "tailored_resumes",
    "applications",
    "application_events",
    "application_evidence",
    "approval_requests",
    "audit_events",
)

#: The account that owns every row that predates this migration.
LEGACY_OWNER_ID = "legacy"


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "users",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("email", sa.String(), nullable=False),
        sa.Column("hashed_password", sa.String(), nullable=False),
        sa.Column("full_name", sa.String(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("is_superuser", sa.Boolean(), nullable=False),
        sa.Column("is_verified", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_users_email"), "users", ["email"], unique=True)

    # The legacy account. It is inactive and its password is unusable, so
    # it can never authenticate; it exists so the pre-WS-13 rows keep a
    # coherent owner until the operator claims them (A1) or purges them (D).
    op.execute(
        sa.text(
            "INSERT INTO users (id, email, hashed_password, full_name, "
            "is_active, is_superuser, is_verified, created_at, updated_at) "
            "VALUES (:id, :email, :password, :name, 0, 0, 0, "
            "CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
        ).bindparams(
            id=LEGACY_OWNER_ID,
            email="legacy@localhost.invalid",
            # A value no password hash can produce, so the account can
            # never be unlocked by guessing.
            password="!",
            name="Legacy (pre-WS-13 data)",
        )
    )

    for table in OWNED_TABLES:
        # One statement, no batch mode. A NOT NULL column may only be added
        # with a default, and the default **is** the backfill: every
        # existing row takes it. Batch mode would have to recreate the
        # table (SQLite cannot alter nullability in place), which needs
        # table reflection and therefore cannot render in Alembic's
        # offline --sql mode.
        #
        # The server default stays: a write that forgets its owner becomes
        # owned by the legacy account, which no real user owns — so the row
        # is invisible rather than leaked. That is the fail-closed
        # direction, and the write paths all pass the owner explicitly.
        op.add_column(
            table,
            sa.Column(
                "owner_id",
                sa.String(),
                nullable=False,
                server_default=LEGACY_OWNER_ID,
            ),
        )
        op.create_index(op.f(f"ix_{table}_owner_id"), table, ["owner_id"], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    for table in reversed(OWNED_TABLES):
        op.drop_index(op.f(f"ix_{table}_owner_id"), table_name=table)
        op.drop_column(table, "owner_id")

    op.drop_index(op.f("ix_users_email"), table_name="users")
    op.drop_table("users")
