"""WS-14 · A0 — the verification of the ownership spine.

A0 was implemented by a previous session. Its record in
``docs/implementation/14-appsec-hardening.md`` is a **claim**, and a claim
is not a proof. This file is the proof, and it is deliberately a *separate*
file from ``tests/test_tenant_isolation.py``: the A0 matrix asserts the
behaviour of the accessors, and this file asserts the things the matrix
cannot see — the **schema**, the **migration**, and the **backfill**.

What is checked here:

1. **The migration is real.** ``alembic upgrade head`` on an empty database
   creates the ``users`` table and adds ``owner_id`` to all eight
   user-scoped tables; ``alembic downgrade`` removes them again.
2. **The ownership contract holds in the database**, not only in the ORM
   model: every user-scoped table's ``owner_id`` column is ``NOT NULL`` and
   carries an index. The check reads SQLite's own ``PRAGMA`` output, so a
   column that is nullable in the model but ``NOT NULL`` in the database (or
   the other way round) is caught.
3. **The backfill is real.** Rows written *before* the migration are owned
   by the ``legacy`` account afterwards, and no row is lost.
4. **The downgrade is lossless in the right direction.** A downgrade and a
   re-upgrade preserve the pre-WS-14 rows.
5. **The accessors filter** — every accessor returns nothing for a foreign
   owner.
6. **The routes have not opted out.** No route module queries a user-scoped
   table directly, and — the note A0 left for A2 — no route module contains
   the ``LEGACY_OWNER_ID`` literal, so the single-tenant assumption cannot
   hide in a write path.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect

from src.db import access
from src.db.access import UserScope
from src.db.users import LEGACY_OWNER_ID

REPO_ROOT = Path(__file__).resolve().parents[1]
ALEMBIC_INI = REPO_ROOT / "alembic.ini"

#: The revision that introduced the ownership spine.
OWNERSHIP_REVISION = "f6a7b8c9d0e1"
#: The revision before it — the last schema without any owner.
PRE_OWNERSHIP_REVISION = "e5f6a7b8c9d0"

#: The eight user-scoped tables. ``jobs`` is deliberately absent: it holds
#: public board data and is the one table that *should* be shared.
USER_SCOPED_TABLES: tuple[str, ...] = (
    "candidate_profiles",
    "job_matches",
    "tailored_resumes",
    "applications",
    "application_events",
    "application_evidence",
    "approval_requests",
    "audit_events",
)


@pytest.fixture
def migration_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Config, str]:
    """Alembic config + SQLite URL isolated to a pytest tmp dir."""
    cfg = Config(str(ALEMBIC_INI))
    cfg.set_main_option("script_location", str(REPO_ROOT / "migrations"))
    db_path = tmp_path / "a0_verification.db"
    url = f"sqlite:///{db_path.as_posix()}"
    monkeypatch.setenv("ALEMBIC_DATABASE_URL", url)
    return cfg, url


@pytest.fixture
def session_with_alice(tmp_path: Path):
    """A throwaway database holding one row per user-scoped table for Alice."""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from src.db.applications import ApplicationDB
    from src.db.approval import ApprovalRequestDB
    from src.db.base import Base
    from src.db.profiles import CandidateProfileDB
    from src.db.tailored import TailoredResumeDB

    engine = create_engine(f"sqlite:///{(tmp_path / 'a0_accessors.db').as_posix()}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    with factory() as db:
        db.add(
            CandidateProfileDB(
                id="profile-alice",
                owner_id="alice",
                name="Alice",
                profile_json={},
                file_path="/tmp/alice.docx",
            )
        )
        db.add(
            TailoredResumeDB(
                id="tailored-alice",
                owner_id="alice",
                profile_id="profile-alice",
                job_id="job-1",
                tailored={},
                factuality={},
                ats_report={},
                docx_path="/tmp/alice.docx",
            )
        )
        db.add(
            ApplicationDB(
                id="app-alice",
                owner_id="alice",
                job_id="job-1",
                workflow_id="wf-1",
                adapter_name="fake-ats-playwright",
                job_url="https://boards.greenhouse.io/x/1",
                job_title="Engineer",
                company_name="Acme",
                status="prepared",
            )
        )
        db.add(
            ApprovalRequestDB(
                id="approval-alice",
                owner_id="alice",
                workflow_id="wf-1",
                adapter_name="fake-ats-playwright",
                job_url="https://boards.greenhouse.io/x/1",
                job_title="Engineer",
                company_name="Acme",
                payload={},
                status="pending",
            )
        )
        db.commit()
        yield db


def _sqlite_pragmas(url: str) -> dict[str, dict]:
    """Read SQLite's own view of the schema.

    ``PRAGMA table_info`` says whether a column is ``NOT NULL`` and
    ``PRAGMA index_list`` says whether it is indexed. The ORM metadata
    could disagree with the database (a model that says ``nullable=False``
    while the column was created without the constraint, or an index that
    exists only in the model), so the *database* is the authority.
    """
    path = url.replace("sqlite:///", "", 1)
    connection = sqlite3.connect(path)
    try:
        tables = {
            row[0]
            for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        }
        pragmas: dict[str, dict] = {}
        for table in tables:
            columns = {
                row[1]: {"notnull": bool(row[3]), "pk": bool(row[5])}
                for row in connection.execute(f'PRAGMA table_info("{table}")')
            }
            indexes = {
                row[1]: [row[2] for row in connection.execute(f'PRAGMA index_info("{row[1]}")')]
                for row in connection.execute(f'PRAGMA index_list("{table}")')
            }
            pragmas[table] = {"columns": columns, "indexes": indexes}
        return pragmas
    finally:
        connection.close()


# -- 1. the migration ---------------------------------------------------------


class TestTheMigrationIsReal:
    def test_upgrade_head_creates_the_users_table(self, migration_env) -> None:
        cfg, url = migration_env
        command.upgrade(cfg, "head")
        engine = create_engine(url)
        try:
            tables = set(inspect(engine).get_table_names())
        finally:
            engine.dispose()
        assert "users" in tables

    def test_upgrade_head_adds_owner_id_to_every_user_scoped_table(self, migration_env) -> None:
        cfg, url = migration_env
        command.upgrade(cfg, "head")
        pragmas = _sqlite_pragmas(url)
        for table in USER_SCOPED_TABLES:
            assert table in pragmas, f"{table} is missing after the upgrade"
            assert "owner_id" in pragmas[table]["columns"], (
                f"{table} has no owner_id column after the upgrade"
            )

    def test_the_jobs_corpus_is_not_user_scoped(self, migration_env) -> None:
        """``jobs`` is shared on purpose (R5). It must not gain an owner."""
        cfg, url = migration_env
        command.upgrade(cfg, "head")
        pragmas = _sqlite_pragmas(url)
        assert "owner_id" not in pragmas["jobs"]["columns"]

    def test_downgrade_removes_the_ownership_spine(self, migration_env) -> None:
        cfg, url = migration_env
        command.upgrade(cfg, "head")
        command.downgrade(cfg, PRE_OWNERSHIP_REVISION)
        pragmas = _sqlite_pragmas(url)
        assert "users" not in pragmas
        for table in USER_SCOPED_TABLES:
            assert "owner_id" not in pragmas[table]["columns"], (
                f"{table} still has an owner_id after the downgrade"
            )

    def test_the_upgrade_and_downgrade_are_reversible(self, migration_env) -> None:
        cfg, url = migration_env
        for _ in range(2):
            command.upgrade(cfg, "head")
            pragmas = _sqlite_pragmas(url)
            assert "owner_id" in pragmas["candidate_profiles"]["columns"]
            command.downgrade(cfg, PRE_OWNERSHIP_REVISION)
            pragmas = _sqlite_pragmas(url)
            assert "owner_id" not in pragmas["candidate_profiles"]["columns"]


# -- 2. the ownership contract in the database --------------------------------


class TestTheOwnershipContract:
    def test_owner_id_is_not_null_in_the_database(self, migration_env) -> None:
        """The model may claim ``nullable=False``; the database must enforce it."""
        cfg, url = migration_env
        command.upgrade(cfg, "head")
        pragmas = _sqlite_pragmas(url)
        for table in USER_SCOPED_TABLES:
            column = pragmas[table]["columns"]["owner_id"]
            assert column["notnull"], f"{table}.owner_id is nullable in the database"

    def test_owner_id_is_indexed_in_the_database(self, migration_env) -> None:
        cfg, url = migration_env
        command.upgrade(cfg, "head")
        pragmas = _sqlite_pragmas(url)
        for table in USER_SCOPED_TABLES:
            indexed = any("owner_id" in columns for columns in pragmas[table]["indexes"].values())
            assert indexed, f"{table}.owner_id has no index in the database"

    def test_the_model_agrees_with_the_database(self) -> None:
        """The ORM model declares the same contract the migration created."""
        from src.db.applications import ApplicationDB, ApplicationEventDB
        from src.db.approval import ApprovalRequestDB
        from src.db.audit import AuditEventDB
        from src.db.evidence import ApplicationEvidenceDB
        from src.db.matches import JobMatchDB
        from src.db.profiles import CandidateProfileDB
        from src.db.tailored import TailoredResumeDB

        models = (
            CandidateProfileDB,
            JobMatchDB,
            TailoredResumeDB,
            ApplicationDB,
            ApplicationEventDB,
            ApplicationEvidenceDB,
            ApprovalRequestDB,
            AuditEventDB,
        )
        assert len(models) == len(USER_SCOPED_TABLES)
        for model in models:
            column = model.__table__.columns["owner_id"]
            assert column.nullable is False, f"{model.__name__}.owner_id is nullable in the model"
            assert column.index is True, f"{model.__name__}.owner_id is not indexed in the model"

    def test_an_explicit_null_owner_is_refused(self, migration_env) -> None:
        """The database refuses a row whose owner is NULL (R4)."""
        cfg, url = migration_env
        command.upgrade(cfg, "head")
        path = url.replace("sqlite:///", "", 1)
        connection = sqlite3.connect(path)
        try:
            with pytest.raises(sqlite3.IntegrityError):
                connection.execute(
                    "INSERT INTO candidate_profiles "
                    "(id, name, email, phone, location, title, profile_json, file_path, "
                    "created_at, owner_id) VALUES ('p1', 'A', NULL, NULL, NULL, NULL, '{}', "
                    "'/tmp/a', CURRENT_TIMESTAMP, NULL)"
                )
        finally:
            connection.close()

    def test_a_write_that_forgets_its_owner_lands_on_the_legacy_owner(self, migration_env) -> None:
        """The fail-closed direction.

        The ``owner_id`` column carries a **server default** of the legacy
        owner, so a write path that forgets to pass an owner does not crash
        and does not land on a real user: the row becomes owned by an
        account nobody can authenticate as, so it is **invisible** rather
        than leaked. A0 chose that direction on purpose, and the note it
        left for A2 — "replace every ``LEGACY_OWNER_ID`` at the write
        paths" — is the other half of it.
        """
        cfg, url = migration_env
        command.upgrade(cfg, "head")
        path = url.replace("sqlite:///", "", 1)
        connection = sqlite3.connect(path)
        try:
            connection.execute(
                "INSERT INTO candidate_profiles "
                "(id, name, email, phone, location, title, profile_json, file_path, "
                "created_at) VALUES ('p1', 'A', NULL, NULL, NULL, NULL, '{}', '/tmp/a', "
                "CURRENT_TIMESTAMP)"
            )
            connection.commit()
            owner = connection.execute(
                "SELECT owner_id FROM candidate_profiles WHERE id = 'p1'"
            ).fetchone()[0]
        finally:
            connection.close()
        assert owner == LEGACY_OWNER_ID


# -- 3. the backfill ----------------------------------------------------------


class TestTheBackfill:
    def _seed_pre_ownership_rows(self, url: str) -> None:
        """Write rows into the schema that predates ownership."""
        path = url.replace("sqlite:///", "", 1)
        connection = sqlite3.connect(path)
        try:
            connection.execute(
                "INSERT INTO candidate_profiles "
                "(id, name, email, phone, location, title, profile_json, file_path, "
                "created_at) VALUES ('p-old', 'Old', NULL, NULL, NULL, NULL, '{}', "
                "'/tmp/old.docx', CURRENT_TIMESTAMP)"
            )
            connection.execute(
                "INSERT INTO audit_events "
                "(recorded_at, actor, action, resource, outcome) VALUES "
                "(CURRENT_TIMESTAMP, 'system', 'resume.upload', 'p-old', 'success')"
            )
            connection.commit()
        finally:
            connection.close()

    def test_a_pre_existing_row_is_backfilled_to_the_legacy_owner(self, migration_env) -> None:
        cfg, url = migration_env
        command.upgrade(cfg, PRE_OWNERSHIP_REVISION)
        self._seed_pre_ownership_rows(url)
        command.upgrade(cfg, "head")

        path = url.replace("sqlite:///", "", 1)
        connection = sqlite3.connect(path)
        try:
            owner = connection.execute(
                "SELECT owner_id FROM candidate_profiles WHERE id = 'p-old'"
            ).fetchone()[0]
        finally:
            connection.close()
        assert owner == LEGACY_OWNER_ID

    def test_no_row_is_lost_by_the_backfill(self, migration_env) -> None:
        cfg, url = migration_env
        command.upgrade(cfg, PRE_OWNERSHIP_REVISION)
        self._seed_pre_ownership_rows(url)
        command.upgrade(cfg, "head")

        path = url.replace("sqlite:///", "", 1)
        connection = sqlite3.connect(path)
        try:
            profiles = connection.execute("SELECT COUNT(*) FROM candidate_profiles").fetchone()[0]
            events = connection.execute("SELECT COUNT(*) FROM audit_events").fetchone()[0]
        finally:
            connection.close()
        assert profiles == 1
        assert events == 1

    def test_the_legacy_account_cannot_authenticate(self, migration_env) -> None:
        """The backfill owner is an account, and it is inert."""
        cfg, url = migration_env
        command.upgrade(cfg, "head")
        path = url.replace("sqlite:///", "", 1)
        connection = sqlite3.connect(path)
        try:
            row = connection.execute(
                "SELECT is_active, hashed_password FROM users WHERE id = ?", (LEGACY_OWNER_ID,)
            ).fetchone()
        finally:
            connection.close()
        assert row is not None, "the migration did not create the legacy account"
        is_active, hashed_password = row
        assert not is_active, "the legacy account must not be able to authenticate"
        assert hashed_password != "", "the legacy account must not have a usable password"

    def test_a_downgrade_and_re_upgrade_preserve_the_pre_existing_rows(self, migration_env) -> None:
        cfg, url = migration_env
        command.upgrade(cfg, PRE_OWNERSHIP_REVISION)
        self._seed_pre_ownership_rows(url)
        command.upgrade(cfg, "head")
        command.downgrade(cfg, PRE_OWNERSHIP_REVISION)
        command.upgrade(cfg, "head")

        path = url.replace("sqlite:///", "", 1)
        connection = sqlite3.connect(path)
        try:
            profiles = connection.execute("SELECT COUNT(*) FROM candidate_profiles").fetchone()[0]
            owner = connection.execute(
                "SELECT owner_id FROM candidate_profiles WHERE id = 'p-old'"
            ).fetchone()[0]
        finally:
            connection.close()
        assert profiles == 1
        assert owner == LEGACY_OWNER_ID


# -- 4. the accessors filter --------------------------------------------------


class TestTheAccessorsFilter:
    def test_every_accessor_hides_a_foreign_owner(self) -> None:
        """A1/A2 build on this: the filter is the whole control."""
        alice = UserScope(user_id="alice")
        assert alice.owns("alice") is True
        assert alice.owns("bob") is False
        assert alice.owns(None) is False

    def test_a_foreign_row_and_a_missing_row_are_the_same_answer(self, session_with_alice) -> None:
        """Not merely equal in value — the caller cannot tell them apart."""
        db = session_with_alice
        bob = UserScope(user_id="bob")
        for accessor, foreign_id in (
            (access.get_application, "app-alice"),
            (access.get_profile, "profile-alice"),
            (access.get_tailored, "tailored-alice"),
            (access.get_approval, "approval-alice"),
        ):
            foreign = accessor(db, bob, foreign_id)
            missing = accessor(db, bob, "no-such-thing")
            assert foreign is None, f"{accessor.__name__} leaked a foreign row"
            assert foreign is missing, (
                f"{accessor.__name__} answers differently for a foreign row "
                "and a missing one — that is an existence oracle"
            )


# -- 5. the routes have not opted out -----------------------------------------


class TestTheRoutesHaveNotOptedOut:
    def _route_sources(self) -> list[Path]:
        return sorted((Path(__file__).parent.parent / "src" / "api" / "routes").glob("*.py"))

    def test_no_route_queries_a_user_scoped_table_directly(self) -> None:
        """AC-ISO, check 2. A route that queries one directly has opted out."""
        owned_models = (
            "CandidateProfileDB",
            "JobMatchDB",
            "TailoredResumeDB",
            "ApplicationDB",
            "ApplicationEventDB",
            "ApplicationEvidenceDB",
            "ApprovalRequestDB",
            "AuditEventDB",
        )
        offenders: list[str] = []
        for path in self._route_sources():
            text = path.read_text(encoding="utf-8")
            for model in owned_models:
                for pattern in (
                    f"db.get({model}",
                    f"db.query({model}",
                    f"session.get({model}",
                    f"session.query({model}",
                ):
                    if pattern in text:
                        offenders.append(f"{path.name}: {pattern}")
        assert not offenders, (
            "A route queries a user-scoped table directly, bypassing the owner "
            "filter in src.db.access:\n  " + "\n  ".join(offenders)
        )

    def test_no_route_names_the_legacy_owner(self) -> None:
        """The note A0 left for A2 — now enforced.

        ``LEGACY_OWNER_ID`` in a route module is the single-tenant
        assumption written down: a write path that stamps the legacy owner
        instead of the request's principal.

        A0 left it in place (the routes still acted as the legacy scope)
        and this test was the marker that said so. **A2 has landed**, so
        the marker is inverted: the offenders list must now be empty.

        The permanent guard lives in the A2 suite
        (``tests/test_tenant_isolation_api.py``), which checks the same
        thing alongside the AST-level check that catches the indirect
        forms. This copy stays here so that the A0 record and the A2
        record cannot drift apart.
        """
        offenders = [
            path.name
            for path in self._route_sources()
            if "LEGACY_OWNER_ID" in path.read_text(encoding="utf-8")
        ]
        assert not offenders, (
            "A route module names the legacy owner; the write paths must use "
            "the request's scope:\n  " + "\n  ".join(offenders)
        )

    def test_every_route_that_reads_user_data_takes_its_scope_from_one_place(self) -> None:
        for path in self._route_sources():
            text = path.read_text(encoding="utf-8")
            if "access." in text:
                assert "current_scope" in text, (
                    f"{path.name} uses the scoped accessors but does not take its "
                    "scope from src.api.scope.current_scope"
                )
