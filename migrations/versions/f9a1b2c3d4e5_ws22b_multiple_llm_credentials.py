"""WS-22 follow-up: more than one model connection per account

Revision ID: f9a1b2c3d4e5
Revises: e4f5a6b7c8d9
Create Date: 2026-11-22

**What changes.** ``llm_credentials`` used to be keyed by ``owner_id`` — the
owner *was* the credential, so a second provider overwrote the first. The
table is rebuilt with:

- ``id`` as the primary key (a stable string, ``migrated:<owner>`` for rows
  that already existed, so no ciphertext is touched and every row keeps its
  own material);
- ``owner_id`` as an indexed non-unique column, so one account owns many
  connections;
- ``activation_rank``, defaulting to 0, which picks the connection in use
  (highest rank; ties by ``created_at``, then ``id``).

**Why the upgrade needs no decision.** Every existing row keeps rank 0, and
rank 0 is what a newly added connection also gets, with ``created_at`` (older
wins) breaking the tie. An account that had one credential therefore still
has exactly one row, in use, behaving as before — the only difference is that
adding a second one no longer destroys it.

**The downgrade refuses rather than loses data.** The earlier schema can hold
one row per account, so a downgrade would have to delete connections. It
checks first and raises with the affected accounts named instead of dropping
anyone's key.

The table is rebuilt (create, copy, drop, rename) rather than altered in
place: the primary key itself changes, and that is the portable spelling of
the change on SQLite and PostgreSQL alike.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "f9a1b2c3d4e5"
down_revision: str | Sequence[str] | None = "e4f5a6b7c8d9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "llm_credentials"
_REBUILT = "llm_credentials_rebuild"

_COLUMNS = (
    "id",
    "owner_id",
    "provider",
    "model",
    "base_url",
    "encrypted_key",
    "hint",
    "activation_rank",
    "created_at",
    "updated_at",
    "last_used_at",
)


def upgrade() -> None:
    """Rebuild the table with ``id`` as the key and ``activation_rank`` added."""
    op.create_table(
        _REBUILT,
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("owner_id", sa.String(), nullable=False),
        sa.Column("provider", sa.String(), nullable=False),
        sa.Column("model", sa.String(), nullable=False),
        sa.Column("base_url", sa.String(), nullable=True),
        sa.Column("encrypted_key", sa.String(), nullable=False),
        sa.Column("hint", sa.String(), nullable=False, server_default=""),
        sa.Column("activation_rank", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.Column("last_used_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    # The id is derived from the old primary key, so it is unique by
    # construction and the copy needs no generated value. The ciphertext and
    # every timestamp move across untouched.
    op.execute(
        f"INSERT INTO {_REBUILT} ({', '.join(_COLUMNS)}) "
        f"SELECT 'migrated:' || owner_id, owner_id, provider, model, base_url, "
        f"encrypted_key, hint, 0, created_at, updated_at, last_used_at "
        f"FROM {_TABLE}"
    )
    op.drop_table(_TABLE)
    op.rename_table(_REBUILT, _TABLE)
    op.create_index(f"ix_{_TABLE}_owner_id", _TABLE, ["owner_id"])


def downgrade() -> None:
    """Return to one row per account, refusing when that would delete a key."""
    bind = op.get_bind()
    duplicated = bind.execute(
        sa.text(f"SELECT owner_id FROM {_TABLE} GROUP BY owner_id HAVING COUNT(*) > 1")
    ).fetchall()
    if duplicated:
        accounts = ", ".join(sorted(str(row[0]) for row in duplicated))
        raise RuntimeError(
            "Refusing to downgrade: these accounts hold more than one model "
            f"connection ({accounts}). The previous schema allows one per "
            "account, so downgrading would delete credentials. Remove the "
            "extra connections first."
        )

    op.create_table(
        _REBUILT,
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
    op.execute(
        f"INSERT INTO {_REBUILT} "
        "(owner_id, provider, model, base_url, encrypted_key, hint, "
        " created_at, updated_at, last_used_at) "
        f"SELECT owner_id, provider, model, base_url, encrypted_key, hint, "
        f"created_at, updated_at, last_used_at FROM {_TABLE}"
    )
    op.drop_index(f"ix_{_TABLE}_owner_id", table_name=_TABLE)
    op.drop_table(_TABLE)
    op.rename_table(_REBUILT, _TABLE)
