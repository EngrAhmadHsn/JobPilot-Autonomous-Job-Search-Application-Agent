"""WS-25: approvals expire, and they are bound to what they approved

Revision ID: e3f4a5b6c7d8
Revises: d2e3f4a5b6c7
Create Date: 2026-11-10

An approval was a decision with no clock. ``ApprovalStatus`` was
``PENDING / APPROVED / REJECTED / EXECUTED / FAILED`` — there was no
``EXPIRED`` state and no expiry timestamp — so an approval granted on
Monday would still authorize a submission on Friday, against a résumé
tailored with Monday's profile, for a job that may have closed in
between.

Two columns close that:

* ``expires_at`` — when the approval stops being valid. An approval
  past its expiry is not executed; it is **expired**, which is a
  distinct state from "rejected" (a human said no) and from "pending"
  (nobody said anything).
* ``profile_version`` — the digest of the profile the payload was built
  from. An approval is bound to the profile it was approved against: if
  the candidate edits their profile afterwards, the approval no longer
  matches what it authorized, and the operator is asked again.

The default expiry is seven days, and it is configurable
(``APPROVAL_TTL_HOURS``). The expiry is measured from the moment the
approval was **created**, not from the moment it was approved, so a
request that sat pending for a week does not get a fresh week on
approval.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e3f4a5b6c7d8"
down_revision: str | Sequence[str] | None = "d2e3f4a5b6c7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: Seven days, the default an approval stays valid.
_DEFAULT_TTL_HOURS = 168


def _has_column(table: str, column: str) -> bool:
    """Whether a column already exists on a table.

    SQLite does not have transactional DDL: alembic's own log says so,
    and it means a migration that fails half-way leaves the columns it
    added in place while the version table still records the old
    revision. Re-running that migration would then fail with "duplicate
    column name".

    So the upgrade is **idempotent**: it adds what is missing and skips
    what is already there. A migration that can be re-run after a
    failure is a migration that cannot strand the schema.
    """
    bind = op.get_bind()
    if bind is None:
        return False
    try:
        inspector = sa.inspect(bind)
        existing = {col["name"] for col in inspector.get_columns(table)}
    except Exception:
        # The offline render (``alembic upgrade --sql``) hands the
        # migration a MockConnection, which has no inspection system.
        # There is nothing to inspect offline, so the answer is "the
        # column is not there" and the statement is emitted.
        return False
    return column in existing


def _has_index(table: str, index: str) -> bool:
    """Whether an index already exists on a table.

    The offline render cannot answer this either, and answers "no", so
    the index statement is emitted — which is what the render needs.
    """
    bind = op.get_bind()
    if bind is None:
        return False
    try:
        inspector = sa.inspect(bind)
        return index in {ix["name"] for ix in inspector.get_indexes(table)}
    except Exception:
        return False


def upgrade() -> None:
    """Upgrade schema."""
    if not _has_column("approval_requests", "expires_at"):
        op.add_column("approval_requests", sa.Column("expires_at", sa.DateTime(), nullable=True))
    if not _has_column("approval_requests", "profile_version"):
        op.add_column(
            "approval_requests", sa.Column("profile_version", sa.String(length=64), nullable=True)
        )
    if not _has_index("approval_requests", "ix_approval_requests_expires_at"):
        op.create_index(
            op.f("ix_approval_requests_expires_at"),
            "approval_requests",
            ["expires_at"],
            unique=False,
        )

    # Give the existing pending approvals an expiry, so none of them is
    # executable forever. The window is measured from their creation, so
    # an approval created long ago expires at the right moment.
    #
    # The modifier is inlined rather than bound: SQLite's ``datetime``
    # takes it as a plain string argument, and the offline render must
    # produce the same statement without a parameter list.
    bind = op.get_bind()
    if bind is None:
        return
    result = bind.execute(
        sa.text(
            "UPDATE approval_requests "
            f"SET expires_at = datetime(created_at, '+{_DEFAULT_TTL_HOURS} hours') "
            "WHERE expires_at IS NULL"
        )
    )
    if result is None:
        return


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f("ix_approval_requests_expires_at"), table_name="approval_requests")
    op.drop_column("approval_requests", "profile_version")
    op.drop_column("approval_requests", "expires_at")
