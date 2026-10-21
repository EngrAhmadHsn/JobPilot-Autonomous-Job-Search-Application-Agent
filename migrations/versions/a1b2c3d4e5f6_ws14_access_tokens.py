"""WS-14: the server-side session store

Revision ID: a1b2c3d4e5f6
Revises: f6a7b8c9d0e1
Create Date: 2026-10-22

Adds ``access_tokens``, the table that holds the platform's live sessions
(docs/implementation/14-appsec-hardening.md, Phase A1).

The sessions are **server-side rows** rather than signed tokens. That is a
deliberate trade: a signed token cannot be revoked before it expires, and
"log me out everywhere" has to work *now*, not in twenty-four hours. The
cost is this table and one lookup per request.

The table is minimal: the token is the primary key and it is a secret, the
owner is an indexed column (because "revoke every session of this user"
is a query on it), and the creation time is what the lifetime is measured
from.

The ``user_id`` column carries **no** foreign key, matching the
convention of the other user-scoped tables (``approval_requests``,
``audit_events``, ``job_matches``, ``tailored_resumes``): a session must
be able to outlive the account it belongs to, so the trail survives the
deletion of the thing it describes. The rows are removed by the account
deletion path, not by the database.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a1b2c3d4e5f6"
down_revision: str | Sequence[str] | None = "f6a7b8c9d0e1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "access_tokens",
        sa.Column("token", sa.String(length=64), nullable=False),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("token"),
    )
    op.create_index(op.f("ix_access_tokens_user_id"), "access_tokens", ["user_id"], unique=False)
    op.create_index(op.f("ix_access_tokens_created_at"), "access_tokens", ["created_at"], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f("ix_access_tokens_created_at"), table_name="access_tokens")
    op.drop_index(op.f("ix_access_tokens_user_id"), table_name="access_tokens")
    op.drop_table("access_tokens")
