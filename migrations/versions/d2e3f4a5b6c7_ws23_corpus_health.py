"""WS-23: the corpus health registry, a content version, and an honest backfill

Revision ID: d2e3f4a5b6c7
Revises: b3c4d5e6f7a8
Create Date: 2026-11-10

Three changes, all measured against the live corpus (2026-11-09):

1. **``jobs.content_version``** — a per-listing hash of the fields the
   search artifacts are derived from (title, description, the two skill
   lists, and the two requirement strings).

   The corpus cache fingerprint used to include ``max(last_seen_at)``, a
   *sighting* time. A refresh that re-sees unchanged listings moves it, so
   every refresh invalidated the whole artifacts cache and the first
   search after each morning's refresh paid a 32.56 s rebuild (measured on
   6,696 listings; ~4 minutes projected at the 50,000 cap). The
   fingerprint now hashes content, and a per-row hash makes that cheap:
   hashing 6,696 rows of full description text in Python cost ~1 s per
   search, while hashing the stored 64-character digests costs
   milliseconds and scales with the corpus rather than with its total
   text.

   The digest is computed **once, at write time** — in ``merge_jobs``, the
   same place the row is written — so the search path never pays for it.

2. **``job_boards``** — a registry of the boards the refresh watches, with
   per-board health.

   The three environment lists (``GREENHOUSE_BOARDS``, ``LEVER_COMPANIES``,
   ``ASHBY_ORGS``) cannot record whether a board is healthy. That is what
   makes source-scoped eviction impossible: a board that starts returning
   403 ages out its own coverage, because eviction is global and orders by
   sighting time. The registry records the last success, the last error
   and the consecutive-failure streak, so a failing source can be
   excluded from eviction while it is failing.

   The table is **shared**, like ``jobs``: the board list is the same for
   every operator and the listings it produces are the same too.

3. **The ``last_seen_at`` backfill** — the rows that predate the WS-15
   column carry NULL, and SQLite sorts NULL first in ``ORDER BY
   last_seen_at ASC``, so the eviction queue was selecting exactly the
   rows that had never been successfully re-fetched. 3,042 of 6,696 rows
   (45.4%) were in that state, and the first 5,000 eviction candidates
   included **all 1,069 Ashby rows** and 3,864 Greenhouse rows.

   The backfill stamps them with the migration time. That is deliberately
   conservative: it makes them *recently seen*, so they are not immediate
   eviction candidates, and the WS-23 delta refresh re-sees them properly.
   The alternative — backfilling from ``posted_at`` — would date a row by
   when the job was posted rather than when the system last saw it, which
   is a different fact and the wrong one for eviction.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d2e3f4a5b6c7"
down_revision: str | Sequence[str] | None = "b3c4d5e6f7a8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _content_version(
    title: str | None,
    description: str | None,
    required_skills: str | None,
    preferred_skills: str | None,
    experience_requirements: str | None,
    education_requirements: str | None,
) -> str:
    """The digest of the fields the search artifacts depend on.

    This mirrors ``src.db.jobs.content_version_for`` exactly, so a row
    written after the migration and a row backfilled by it carry the same
    digest for the same content.
    """
    parts = [
        title or "",
        description or "",
        required_skills or "",
        preferred_skills or "",
        experience_requirements or "",
        education_requirements or "",
    ]
    return hashlib.sha256("\x1f".join(parts).encode("utf-8", errors="replace")).hexdigest()


def upgrade() -> None:
    """Upgrade schema."""
    # -- 1. the per-listing content version -------------------------------
    op.add_column("jobs", sa.Column("content_version", sa.String(length=64), nullable=True))
    op.create_index(op.f("ix_jobs_content_version"), "jobs", ["content_version"], unique=False)

    # -- 2. the board registry --------------------------------------------
    op.create_table(
        "job_boards",
        sa.Column("id", sa.String(length=128), primary_key=True),
        sa.Column("ats", sa.String(length=32), nullable=False, index=True),
        sa.Column("slug", sa.String(length=128), nullable=False, index=True),
        sa.Column("company_name", sa.String(length=200), nullable=True),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("last_ok_at", sa.DateTime(), nullable=True),
        sa.Column("last_error", sa.String(length=500), nullable=True),
        sa.Column("consecutive_failures", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("listings_seen", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("first_seen_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_job_boards_enabled_ats", "job_boards", ["enabled", "ats"], unique=False)

    # -- 3. the honest backfill -------------------------------------------
    # Stamp the rows that predate the sighting column, so the eviction
    # queue stops selecting them. The value is the migration time, not the
    # posting time: this records "we last had evidence of this row around
    # now", and the delta refresh replaces it with a real sighting.
    op.execute("UPDATE jobs SET last_seen_at = CURRENT_TIMESTAMP WHERE last_seen_at IS NULL")

    # -- 4. backfill the content version ----------------------------------
    # Computed here rather than left NULL, because the fingerprint reads
    # this column: a NULL would make a changed description invisible to the
    # cache, which is the bug this column exists to remove.
    #
    # The migration must also render **offline** (the ``--sql`` mode the
    # Postgres compatibility test uses), where there is no connection to
    # read from and the statement returns nothing. In that mode the
    # column stays NULL and the first refresh fills it — the write path
    # computes the digest for every row it touches, so the column
    # converges either way.
    bind = op.get_bind()
    if bind is None:
        return
    result = bind.execute(
        sa.text(
            "SELECT id, title, description, required_skills, preferred_skills, "
            "experience_requirements, education_requirements FROM jobs "
            "WHERE content_version IS NULL"
        )
    )
    if result is None:
        return
    rows = result.fetchall()
    updates = []
    for row in rows:
        skills = row.required_skills
        preferred = row.preferred_skills
        # The skill columns are JSON arrays; the digest must not depend on
        # how the driver happened to deserialize them.
        skills_text = (
            skills if isinstance(skills, str) else json.dumps(skills or [], sort_keys=True)
        )
        preferred_text = (
            preferred if isinstance(preferred, str) else json.dumps(preferred or [], sort_keys=True)
        )
        digest = _content_version(
            row.title,
            row.description,
            skills_text,
            preferred_text,
            row.experience_requirements,
            row.education_requirements,
        )
        updates.append({"id": row.id, "content_version": digest})
    if updates:
        bind.execute(
            sa.text("UPDATE jobs SET content_version = :content_version WHERE id = :id"),
            updates,
        )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table("job_boards")
    op.drop_index(op.f("ix_jobs_content_version"), table_name="jobs")
    op.drop_column("jobs", "content_version")
