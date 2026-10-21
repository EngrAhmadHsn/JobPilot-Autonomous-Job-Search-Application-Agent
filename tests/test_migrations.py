"""WS-01 tests: Alembic migrations driven through the alembic command API.

Alembic is authoritative outside the test suite (``Base.metadata.create_all()``
is test-suite-only), so these tests exercise the real migration scripts against
throwaway SQLite databases in pytest tmp dirs. Live PostgreSQL is covered by
offline (--sql) DDL rendering, which uses the real PostgreSQL dialect without
needing a server or driver.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect

from src.db.session import ensure_sqlite_parent_dir

REPO_ROOT = Path(__file__).resolve().parents[1]
ALEMBIC_INI = REPO_ROOT / "alembic.ini"

JOBS_COLUMNS = {
    "id",
    "source",
    "source_job_id",
    "title",
    "company",
    "description",
    "location",
    "remote_policy",
    "employment_type",
    "salary",
    "currency",
    "seniority",
    "required_skills",
    "preferred_skills",
    "experience_requirements",
    "education_requirements",
    "application_url",
    "company_url",
    "posted_at",
    "extra_metadata",
}

EVIDENCE_COLUMNS = {
    "id",
    "workflow_id",
    "adapter_name",
    "job_url",
    "application_id",
    "confirmation_text",
    "screenshot_path",
    "trace_path",
    "status",
    "metadata",
    "recorded_at",
    "owner_id",
}

CANDIDATE_PROFILE_COLUMNS = {
    "id",
    "name",
    "email",
    "phone",
    "location",
    "title",
    "profile_json",
    "file_path",
    "created_at",
    "owner_id",
}

JOB_MATCHES_COLUMNS = {
    "id",
    "profile_id",
    "job_id",
    "scores",
    "explanation",
    "created_at",
    "owner_id",
}

TAILORED_RESUMES_COLUMNS = {
    "id",
    "profile_id",
    "job_id",
    "tailored",
    "factuality",
    "ats_report",
    "insights",
    "docx_path",
    "created_at",
    "owner_id",
}

APPROVAL_REQUESTS_COLUMNS = {
    "id",
    "workflow_id",
    "adapter_name",
    "job_url",
    "job_title",
    "company_name",
    "payload",
    "status",
    "approver",
    "decision_reason",
    "created_at",
    "decided_at",
    "result",
    "owner_id",
}

AUDIT_EVENTS_COLUMNS = {
    "id",
    "recorded_at",
    "actor",
    "action",
    "resource",
    "outcome",
    "workflow_id",
    "metadata",
    "owner_id",
}

APPLICATIONS_COLUMNS = {
    "id",
    "profile_id",
    "job_id",
    "workflow_id",
    "approval_id",
    "adapter_name",
    "job_url",
    "job_title",
    "company_name",
    "status",
    "tailored_resume_id",
    "submitted_at",
    "verified_at",
    "application_url",
    "notes",
    "created_at",
    "updated_at",
    "owner_id",
}

APPLICATION_EVENTS_COLUMNS = {
    "id",
    "application_id",
    "event_type",
    "actor",
    "from_status",
    "to_status",
    "metadata",
    "recorded_at",
    "owner_id",
}


@pytest.fixture
def migration_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Config, str]:
    """Alembic config + SQLite URL isolated to a pytest tmp dir."""
    cfg = Config(str(ALEMBIC_INI))
    cfg.set_main_option("script_location", str(REPO_ROOT / "migrations"))
    db_path = tmp_path / "migration_test.db"
    url = f"sqlite:///{db_path.as_posix()}"
    monkeypatch.setenv("ALEMBIC_DATABASE_URL", url)
    return cfg, url


def _table_names(url: str) -> set[str]:
    engine = create_engine(url)
    try:
        return set(inspect(engine).get_table_names())
    finally:
        engine.dispose()


def test_upgrade_head_creates_jobs_and_evidence(
    migration_env: tuple[Config, str],
) -> None:
    cfg, url = migration_env
    command.upgrade(cfg, "head")
    tables = _table_names(url)
    assert {
        "jobs",
        "application_evidence",
        "candidate_profiles",
        "job_matches",
        "tailored_resumes",
        "approval_requests",
        "audit_events",
        "applications",
        "application_events",
        "alembic_version",
    } <= tables

    engine = create_engine(url)
    try:
        inspector = inspect(engine)
        jobs_cols = {col["name"] for col in inspector.get_columns("jobs")}
        assert jobs_cols == JOBS_COLUMNS
        evidence_cols = {col["name"] for col in inspector.get_columns("application_evidence")}
        assert evidence_cols == EVIDENCE_COLUMNS
        # WS-04 tables.
        profile_cols = {col["name"] for col in inspector.get_columns("candidate_profiles")}
        assert profile_cols == CANDIDATE_PROFILE_COLUMNS
        match_cols = {col["name"] for col in inspector.get_columns("job_matches")}
        assert match_cols == JOB_MATCHES_COLUMNS
        # Indexes declared on the models.
        jobs_indexes = {ix["name"] for ix in inspector.get_indexes("jobs")}
        assert {"ix_jobs_source", "ix_jobs_company"} <= jobs_indexes
        evidence_indexes = {ix["name"] for ix in inspector.get_indexes("application_evidence")}
        assert "ix_application_evidence_workflow_id" in evidence_indexes
        match_indexes = {ix["name"] for ix in inspector.get_indexes("job_matches")}
        assert {"ix_job_matches_profile_id", "ix_job_matches_job_id"} <= match_indexes
        # WS-05 table.
        tailored_cols = {col["name"] for col in inspector.get_columns("tailored_resumes")}
        assert tailored_cols == TAILORED_RESUMES_COLUMNS
        tailored_indexes = {ix["name"] for ix in inspector.get_indexes("tailored_resumes")}
        assert {
            "ix_tailored_resumes_profile_id",
            "ix_tailored_resumes_job_id",
        } <= tailored_indexes
        # WS-06 tables.
        approval_cols = {col["name"] for col in inspector.get_columns("approval_requests")}
        assert approval_cols == APPROVAL_REQUESTS_COLUMNS
        audit_cols = {col["name"] for col in inspector.get_columns("audit_events")}
        assert audit_cols == AUDIT_EVENTS_COLUMNS
        approval_indexes = {ix["name"] for ix in inspector.get_indexes("approval_requests")}
        assert {
            "ix_approval_requests_workflow_id",
            "ix_approval_requests_status",
        } <= approval_indexes
        audit_indexes = {ix["name"] for ix in inspector.get_indexes("audit_events")}
        assert {
            "ix_audit_events_actor",
            "ix_audit_events_action",
            "ix_audit_events_outcome",
            "ix_audit_events_workflow_id",
        } <= audit_indexes
        # WS-07 tables.
        application_cols = {col["name"] for col in inspector.get_columns("applications")}
        assert application_cols == APPLICATIONS_COLUMNS
        event_cols = {col["name"] for col in inspector.get_columns("application_events")}
        assert event_cols == APPLICATION_EVENTS_COLUMNS
        application_indexes = {ix["name"] for ix in inspector.get_indexes("applications")}
        assert {
            "ix_applications_profile_id",
            "ix_applications_job_id",
            "ix_applications_workflow_id",
            "ix_applications_approval_id",
            "ix_applications_status",
        } <= application_indexes
        event_indexes = {ix["name"] for ix in inspector.get_indexes("application_events")}
        assert {
            "ix_application_events_application_id",
            "ix_application_events_event_type",
            "ix_application_events_actor",
        } <= event_indexes
        # The evidence row now names the application it belongs to.
        evidence_indexes = {ix["name"] for ix in inspector.get_indexes("application_evidence")}
        assert "ix_application_evidence_application_id" in evidence_indexes
    finally:
        engine.dispose()


def test_downgrade_base_removes_tables(migration_env: tuple[Config, str]) -> None:
    cfg, url = migration_env
    command.upgrade(cfg, "head")
    command.downgrade(cfg, "base")
    tables = _table_names(url)
    assert "jobs" not in tables
    assert "application_evidence" not in tables
    assert "candidate_profiles" not in tables
    assert "job_matches" not in tables
    assert "tailored_resumes" not in tables
    assert "approval_requests" not in tables
    assert "audit_events" not in tables
    assert "applications" not in tables
    assert "application_events" not in tables


def test_migrations_are_reversible(migration_env: tuple[Config, str]) -> None:
    cfg, url = migration_env
    for _ in range(2):
        command.upgrade(cfg, "head")
        assert {
            "jobs",
            "application_evidence",
            "candidate_profiles",
            "job_matches",
            "tailored_resumes",
            "approval_requests",
            "audit_events",
            "applications",
            "application_events",
        } <= _table_names(url)
        command.downgrade(cfg, "base")
        assert not {
            "jobs",
            "application_evidence",
            "candidate_profiles",
            "job_matches",
            "tailored_resumes",
            "approval_requests",
            "audit_events",
            "applications",
            "application_events",
        } & _table_names(url)


def _offline_ddl(monkeypatch: pytest.MonkeyPatch, url: str) -> str:
    """Render the full upgrade script for *url*'s dialect without a server."""
    cfg = Config(str(ALEMBIC_INI))
    cfg.set_main_option("script_location", str(REPO_ROOT / "migrations"))
    monkeypatch.setenv("ALEMBIC_DATABASE_URL", url)
    # Offline mode compiles DDL via the URL's dialect; no DBAPI driver needed.
    import contextlib
    import io

    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        command.upgrade(cfg, "head", sql=True)
    return buffer.getvalue()


def test_json_columns_render_portably_on_sqlite(
    migration_env: tuple[Config, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    _cfg, url = migration_env
    ddl = _offline_ddl(monkeypatch, url)
    assert "CREATE TABLE jobs" in ddl
    assert "CREATE TABLE application_evidence" in ddl
    assert "CREATE TABLE candidate_profiles" in ddl
    assert "CREATE TABLE job_matches" in ddl
    assert "CREATE TABLE tailored_resumes" in ddl
    assert "CREATE TABLE approval_requests" in ddl
    assert "CREATE TABLE audit_events" in ddl
    assert "CREATE TABLE applications" in ddl
    assert "CREATE TABLE application_events" in ddl
    # JSON columns render as plain JSON, not dialect-specific types.
    assert re.search(r"required_skills\s+JSON", ddl)
    assert re.search(r"extra_metadata\s+JSON", ddl)
    assert re.search(r"\bmetadata\s+JSON", ddl)
    assert re.search(r"profile_json\s+JSON", ddl)
    assert re.search(r"scores\s+JSON", ddl)
    assert re.search(r"tailored\s+JSON", ddl)
    assert re.search(r"factuality\s+JSON", ddl)
    assert re.search(r"ats_report\s+JSON", ddl)
    # WS-06 JSON columns.
    assert re.search(r"payload\s+JSON", ddl)
    assert re.search(r"result\s+JSON", ddl)


def test_json_columns_render_portably_on_postgres(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Dummy URL: offline mode never connects, the URL only selects the dialect.
    ddl = _offline_ddl(
        monkeypatch,
        "postgresql://alembic_offline:unused@localhost:5432/render_only",
    )
    assert "CREATE TABLE jobs" in ddl
    assert "CREATE TABLE application_evidence" in ddl
    assert "CREATE TABLE candidate_profiles" in ddl
    assert "CREATE TABLE job_matches" in ddl
    assert "CREATE TABLE tailored_resumes" in ddl
    assert "CREATE TABLE approval_requests" in ddl
    assert "CREATE TABLE audit_events" in ddl
    assert "CREATE TABLE applications" in ddl
    assert "CREATE TABLE application_events" in ddl
    assert re.search(r"required_skills\s+JSON", ddl)
    assert re.search(r"extra_metadata\s+JSON", ddl)
    assert re.search(r"\bmetadata\s+JSON", ddl)
    assert re.search(r"profile_json\s+JSON", ddl)
    assert re.search(r"scores\s+JSON", ddl)
    assert re.search(r"tailored\s+JSON", ddl)
    assert re.search(r"ats_report\s+JSON", ddl)
    # WS-06 JSON columns.
    assert re.search(r"payload\s+JSON", ddl)
    assert re.search(r"result\s+JSON", ddl)


def _import_app_subprocess(env_overrides: dict[str, str]) -> subprocess.CompletedProcess[str]:
    """Run `from src.main import app` in a fresh interpreter with env overrides."""
    env = {**os.environ, **env_overrides}
    return subprocess.run(
        [sys.executable, "-c", "from src.main import app; print('startup-ok')"],
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
        env=env,
        timeout=120,
        check=False,
    )


def test_ensure_sqlite_parent_dir_creates_missing_dir(tmp_path: Path) -> None:
    target = tmp_path / "fresh" / "nested" / "app.db"
    ensure_sqlite_parent_dir(f"sqlite:///{target.as_posix()}")
    assert target.parent.is_dir()


def test_ensure_sqlite_parent_dir_is_safe_noop_for_other_urls() -> None:
    # Must not raise and must not create anything for these URL shapes.
    ensure_sqlite_parent_dir("postgresql://localhost:5432/app")
    ensure_sqlite_parent_dir("sqlite:///:memory:")
    ensure_sqlite_parent_dir("sqlite://")
    ensure_sqlite_parent_dir("sqlite:///relative_at_cwd.db")  # parent is cwd
    ensure_sqlite_parent_dir(f"sqlite:///{Path.cwd().as_posix()}/existing.db")


def test_production_startup_fails_fast_when_cors_unset() -> None:
    # Empty value: .env (loaded by the child too) cannot override an existing var.
    result = _import_app_subprocess({"APP_ENV": "production", "CORS_ORIGINS": ""})
    assert result.returncode != 0
    assert "APP_ENV=production" in result.stderr
    assert "CORS_ORIGINS" in result.stderr


def test_production_startup_fails_fast_on_wildcard_cors() -> None:
    result = _import_app_subprocess({"APP_ENV": "production", "CORS_ORIGINS": "*"})
    assert result.returncode != 0
    assert "wildcard" in result.stderr
    assert "CORS_ORIGINS" in result.stderr


def test_production_startup_succeeds_with_explicit_origins() -> None:
    result = _import_app_subprocess(
        {"APP_ENV": "production", "CORS_ORIGINS": "https://app.example.com"}
    )
    assert result.returncode == 0
    assert "startup-ok" in result.stdout
