"""WS-14: the audit actor becomes a principal

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-10-22

Adds ``actor_kind`` and ``actor_id`` to ``audit_events``
(docs/implementation/14-appsec-hardening.md, Phase C).

The ``actor`` column was a free string, and a free string is not a
principal: anyone who can write to the audit store can say they were
somebody else. The two new columns split the label into its parts:

- ``actor_kind`` — ``user``, ``agent`` or ``system``;
- ``actor_id`` — the principal's id (the account id for a user, the
  adapter's name for an agent, empty for the system).

The old ``actor`` column stays as the human-readable label, because the
label is what an operator reads. It is now **derived** from the two new
columns rather than supplied, so the three can never disagree.

``actor_kind`` is ``NOT NULL`` with a server default of ``system``, which
is the fail-closed direction: a row written by an older code path is
attributed to the system rather than to nobody, and the system is
honest about being the system.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b2c3d4e5f6a7"
down_revision: str | Sequence[str] | None = "a1b2c3d4e5f6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "audit_events",
        sa.Column(
            "actor_kind",
            sa.String(),
            nullable=False,
            server_default="system",
        ),
    )
    op.add_column(
        "audit_events",
        sa.Column("actor_id", sa.String(), nullable=True),
    )
    op.create_index(
        op.f("ix_audit_events_actor_kind"), "audit_events", ["actor_kind"], unique=False
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f("ix_audit_events_actor_kind"), table_name="audit_events")
    op.drop_column("audit_events", "actor_id")
    op.drop_column("audit_events", "actor_kind")
