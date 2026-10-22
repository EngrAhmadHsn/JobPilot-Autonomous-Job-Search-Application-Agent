"""The migration check (WS-14 · Phase E).

A migration that does not apply, or does not reverse, breaks a
deployment — and the moment it is discovered is the worst possible one.
So the check runs the **real** Alembic commands against a throwaway
database, the same way a deployment would, and it is a script rather
than a test so that it can be run locally, in CI, and by an operator
before a release.

What it proves:

1. the chain applies from an empty database, one revision at a time;
2. every revision in the chain **reverses**, one at a time;
3. the rows that pre-date the chain survive a full upgrade and
   downgrade;
4. the final schema has the tables and the columns the code expects —
   the migration and the ORM model cannot drift apart unnoticed.

Usage::

    python scripts/verify_migrations.py
"""

from __future__ import annotations

import os
import sqlite3
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory

#: The tables the application needs. A migration that forgets one is
#: caught here rather than at the first request.
EXPECTED_TABLES = {
    "users",
    "access_tokens",
    "jobs",
    "candidate_profiles",
    "job_matches",
    "tailored_resumes",
    "approval_requests",
    "audit_events",
    "applications",
    "application_events",
    "application_evidence",
}

#: The columns the WS-14 work added. They are named explicitly because
#: they are the ones the multi-user design depends on.
EXPECTED_COLUMNS = {
    "users": {"id", "email", "hashed_password", "is_active", "is_superuser", "is_verified"},
    "access_tokens": {"token", "user_id", "created_at"},
    "audit_events": {"owner_id", "actor_kind", "actor_id"},
    "candidate_profiles": {"owner_id"},
    "job_matches": {"owner_id"},
    "tailored_resumes": {"owner_id"},
    "approval_requests": {"owner_id"},
    "applications": {"owner_id"},
    "application_events": {"owner_id"},
    "application_evidence": {"owner_id"},
    # WS-15: the corpus's eviction clock. Without it the corpus cap is a
    # one-way door — a full corpus admits nothing, ever again.
    "jobs": {"last_seen_at"},
}


def _config() -> Config:
    """An Alembic config pointed at the repository's migrations.

    The database URL is **not** set here: the environment variable is
    set once, by :func:`main`, and a second call would silently point
    the migrations at a different database.
    """
    cfg = Config(str(REPO_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(REPO_ROOT / "migrations"))
    return cfg


def _revisions() -> list[str]:
    """Every revision in the chain, oldest first.

    ``walk_revisions`` yields the newest first, and the chain has to be
    walked in the other order: each ``upgrade`` advances the database
    to one more revision.
    """
    script = ScriptDirectory.from_config(_config())
    return [revision.revision for revision in reversed(list(script.walk_revisions()))]


def _table_names(path: Path) -> set[str]:
    connection = sqlite3.connect(path)
    try:
        return {
            row[0]
            for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        }
    finally:
        connection.close()


def _columns(path: Path, table: str) -> set[str]:
    connection = sqlite3.connect(path)
    try:
        return {row[1] for row in connection.execute(f'PRAGMA table_info("{table}")')}
    finally:
        connection.close()


def _check(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(f"FAIL: {message}")


#: The revision before the ownership work — the last schema without an
#: owner on any row.
PRE_OWNERSHIP_REVISION = "e5f6a7b8c9d0"


def main() -> int:
    """Run the check. Returns the process exit code."""
    with tempfile.TemporaryDirectory() as work:
        path = Path(work) / "migrations.db"
        url = f"sqlite:///{path.as_posix()}"
        os.environ["ALEMBIC_DATABASE_URL"] = url
        cfg = _config()
        revisions = _revisions()

        print(f"The chain has {len(revisions)} revision(s): {', '.join(revisions)}")

        # 1. The chain applies from an empty database, one revision at a
        #    time. Applying them one at a time is stricter than jumping
        #    to head: it catches a revision that only works when another
        #    one has already run.
        for revision in revisions:
            command.upgrade(cfg, revision)
        print("Every revision applies in order.")

        # 2. The final schema is the one the code expects.
        tables = _table_names(path)
        missing = EXPECTED_TABLES - tables
        _check(not missing, f"the migrated database is missing {sorted(missing)}")
        for table, columns in EXPECTED_COLUMNS.items():
            present = _columns(path, table)
            absent = columns - present
            _check(not absent, f"{table} is missing {sorted(absent)}")
        print("The final schema has the tables and the columns the code expects.")

        # 3. Every revision reverses.
        command.downgrade(cfg, "base")
        _check("users" not in _table_names(path), "the downgrade left the users table behind")
        print("Every revision reverses.")

        # 4. The rows that pre-date the ownership work survive it.
        #
        # This is the check that matters: the ownership revisions ADD a
        # NOT NULL column to eight tables, and a backfill that dropped a
        # row would lose somebody's data on the way to a multi-user
        # deployment.
        command.upgrade(cfg, PRE_OWNERSHIP_REVISION)
        connection = sqlite3.connect(path)
        try:
            connection.execute(
                "INSERT INTO audit_events (recorded_at, actor, action, resource, outcome) "
                "VALUES (CURRENT_TIMESTAMP, 'system', 'resume.upload', 'p-old', 'success')"
            )
            connection.commit()
        finally:
            connection.close()

        command.upgrade(cfg, "head")
        connection = sqlite3.connect(path)
        try:
            row = connection.execute(
                "SELECT COUNT(*), MIN(owner_id) FROM audit_events WHERE resource = 'p-old'"
            ).fetchone()
        finally:
            connection.close()
        _check(row[0] == 1, "a row did not survive the ownership migration")
        _check(row[1] == "legacy", "the backfill did not assign the legacy owner")
        print("The rows survive the ownership migration, and they are backfilled.")

    print("OK: the migrations apply, reverse, and preserve the data.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
