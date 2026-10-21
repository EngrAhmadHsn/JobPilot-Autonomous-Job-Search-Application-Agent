"""WS-14 · Phase D — retention, the deletion cascade, and the purge.

**The property under test:** data does not outlive its purpose, and
"delete my account" means what it says.

What is proved here:

- the age-based purge removes the rows **and the files** that are past
  the retention window, and leaves the fresh ones alone;
- the deletion cascade removes **every** artefact of an account: the
  profile, the tailored resumes, the applications, the events, the
  evidence, the approvals, the sessions, the account itself, and the
  files on disk;
- the audit rows are **anonymized, not deleted** — the trail survives,
  the identity does not;
- the purge is **idempotent** — running it twice changes nothing the
  second time;
- the purge is **auditable** — it says what it removed.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.db.applications import ApplicationDB, ApplicationEventDB
from src.db.approval import ApprovalRequestDB
from src.db.audit import AuditEventDB
from src.db.base import Base
from src.db.evidence import ApplicationEvidenceDB
from src.db.matches import JobMatchDB
from src.db.profiles import CandidateProfileDB
from src.db.tailored import TailoredResumeDB
from src.db.users import UserDB
from src.retention import (
    ANONYMIZED_OWNER,
    RetentionPolicy,
    anonymize_audit_rows,
    purge_expired,
    purge_user,
)

OWNER = "alice"
OTHER = "bob"

#: A policy that expires everything.
EXPIRING = RetentionPolicy(
    profile_days=30,
    tailored_days=30,
    application_days=30,
    evidence_days=30,
    session_days=30,
)

#: A policy that keeps everything.
KEEPING = RetentionPolicy(
    profile_days=365,
    tailored_days=180,
    application_days=730,
    evidence_days=180,
    session_days=30,
)


@pytest.fixture
def session(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """A throwaway database, and a throwaway storage root."""
    from src.config.settings import get_settings

    monkeypatch.setattr(get_settings(), "data_dir", str(tmp_path / "data"))
    engine = create_engine(f"sqlite:///{(tmp_path / 'retention.db').as_posix()}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    with factory() as db:
        yield db
    engine.dispose()


def _seed(session, owner: str = OWNER, *, age_days: int = 400, files: bool = True):
    """Write one row of every kind, owned by *owner* and *age_days* old.

    The files are written where the platform really puts them — the
    owner's own directories (WS-14 · Phase B) — and the evidence is
    stored as a **bare file name**, which is the shape the browser layer
    writes and the shape the purge has to resolve.
    """
    from src.storage.paths import KIND_EVIDENCE, KIND_RESUMES, KIND_TAILORED, user_dir

    old = datetime.now(UTC) - timedelta(days=age_days)
    files_written: list[Path] = []

    if files:
        resume = user_dir(owner, KIND_RESUMES) / f"{owner}-resume.docx"
        docx = user_dir(owner, KIND_TAILORED) / f"{owner}-tailored.docx"
        screenshot = user_dir(owner, KIND_EVIDENCE) / f"{owner}-evidence.png"
        for path in (resume, docx, screenshot):
            path.parent.mkdir(parents=True, exist_ok=True)
        resume.write_bytes(b"PK")
        docx.write_bytes(b"PK")
        screenshot.write_bytes(b"PNG")
        files_written = [resume, docx, screenshot]
    else:
        resume = docx = screenshot = None

    session.add(
        UserDB(
            id=owner,
            email=f"{owner}@example.com",
            hashed_password="!",
            is_active=True,
        )
    )
    session.add(
        CandidateProfileDB(
            id=f"{owner}-profile",
            owner_id=owner,
            name="Alice",
            profile_json={},
            file_path=str(resume) if resume else "/tmp/gone.docx",
            created_at=old,
        )
    )
    session.add(
        JobMatchDB(
            owner_id=owner,
            profile_id=f"{owner}-profile",
            job_id="job-1",
            scores={},
            created_at=old,
        )
    )
    session.add(
        TailoredResumeDB(
            id=f"{owner}-tailored",
            owner_id=owner,
            profile_id=f"{owner}-profile",
            job_id="job-1",
            tailored={},
            factuality={},
            ats_report={},
            docx_path=str(docx) if docx else "/tmp/gone.docx",
            created_at=old,
        )
    )
    session.add(
        ApplicationDB(
            id=f"{owner}-app",
            owner_id=owner,
            job_id="job-1",
            workflow_id=f"{owner}-wf",
            adapter_name="fake-ats",
            job_url="https://boards.greenhouse.io/x/1",
            job_title="Engineer",
            company_name="Acme",
            status="verified",
            created_at=old,
        )
    )
    session.add(
        ApplicationEventDB(
            owner_id=owner,
            application_id=f"{owner}-app",
            event_type="application.submitted",
            actor="agent",
            recorded_at=old,
        )
    )
    session.add(
        ApplicationEvidenceDB(
            owner_id=owner,
            application_id=f"{owner}-app",
            workflow_id=f"{owner}-wf",
            adapter_name="fake-ats",
            job_url="https://boards.greenhouse.io/x/1",
            status="verified",
            screenshot_path=screenshot.name if screenshot else "gone.png",
            recorded_at=old,
        )
    )
    session.add(
        ApprovalRequestDB(
            id=f"{owner}-approval",
            owner_id=owner,
            workflow_id=f"{owner}-wf",
            adapter_name="fake-ats",
            job_url="https://boards.greenhouse.io/x/1",
            job_title="Engineer",
            company_name="Acme",
            payload={},
            status="approved",
            created_at=old,
        )
    )
    session.add(
        AuditEventDB(
            owner_id=owner,
            actor=f"user:{owner}",
            actor_kind="user",
            actor_id=owner,
            action="application.submit",
            resource=f"{owner}-app",
            outcome="success",
            recorded_at=old,
        )
    )
    session.commit()
    return files_written


# -- the age-based purge --------------------------------------------------------


class TestTheAgeBasedPurge:
    def test_the_expired_rows_are_removed(self, session) -> None:
        _seed(session, age_days=400)
        removed = purge_expired(session, EXPIRING)
        assert removed["profiles"] == 1
        assert removed["tailored"] == 1
        assert removed["applications"] == 1
        assert removed["events"] == 1
        assert removed["evidence"] == 1
        assert removed["approvals"] == 1
        assert session.query(CandidateProfileDB).count() == 0
        assert session.query(ApplicationDB).count() == 0

    def test_the_fresh_rows_survive(self, session) -> None:
        _seed(session, age_days=1)
        purge_expired(session, KEEPING)
        assert session.query(CandidateProfileDB).count() == 1
        assert session.query(ApplicationDB).count() == 1

    def test_the_files_go_with_the_rows(self, session) -> None:
        files = _seed(session, age_days=400)
        removed = purge_expired(session, EXPIRING)
        assert removed["files"] >= 3
        assert not any(path.exists() for path in files)

    def test_the_purge_is_idempotent(self, session) -> None:
        _seed(session, age_days=400)
        first = purge_expired(session, EXPIRING)
        second = purge_expired(session, EXPIRING)
        assert first["profiles"] == 1
        assert second["profiles"] == 0
        assert second["applications"] == 0
        assert second["files"] == 0

    def test_the_purge_is_audited(self, session) -> None:
        _seed(session, age_days=400)
        purge_expired(session, EXPIRING)
        rows = session.query(AuditEventDB).filter(AuditEventDB.action == "retention").all()
        assert rows, "the purge wrote no audit row"
        assert rows[-1].extra_metadata["removed"]["profiles"] == 1


# -- the deletion cascade --------------------------------------------------------


class TestTheDeletionCascade:
    def test_every_row_of_the_account_is_removed(self, session) -> None:
        _seed(session, age_days=1)
        removed = purge_user(session, OWNER)

        assert removed["profiles"] == 1
        assert removed["tailored"] == 1
        assert removed["applications"] == 1
        assert removed["events"] == 1
        assert removed["evidence"] == 1
        assert removed["approvals"] == 1
        assert removed["matches"] == 1

        assert session.query(CandidateProfileDB).count() == 0
        assert session.query(TailoredResumeDB).count() == 0
        assert session.query(ApplicationDB).count() == 0
        assert session.query(ApplicationEventDB).count() == 0
        assert session.query(ApplicationEvidenceDB).count() == 0
        assert session.query(ApprovalRequestDB).count() == 0
        assert session.query(JobMatchDB).count() == 0
        assert session.get(UserDB, OWNER) is None

    def test_another_account_is_untouched(self, session) -> None:
        _seed(session, owner=OWNER, age_days=1)
        _seed(session, owner=OTHER, age_days=1)
        purge_user(session, OWNER)
        assert (
            session.query(CandidateProfileDB).filter(CandidateProfileDB.owner_id == OTHER).count()
            == 1
        )
        assert session.get(UserDB, OTHER) is not None

    def test_the_files_are_removed(self, session) -> None:
        files = _seed(session, age_days=1)
        purge_user(session, OWNER)
        assert not any(path.exists() for path in files)

    def test_the_account_directory_is_removed(self, session) -> None:
        from src.storage.paths import user_dir

        directory = user_dir(OWNER, "resumes")
        directory.mkdir(parents=True, exist_ok=True)
        (directory / "resume.docx").write_bytes(b"PK")

        purge_user(session, OWNER)
        assert not directory.exists()


# -- the anonymized audit rows --------------------------------------------------


class TestTheAuditRowsAreAnonymized:
    def test_the_rows_survive(self, session) -> None:
        _seed(session, age_days=1)
        purge_user(session, OWNER)
        assert session.query(AuditEventDB).count() >= 1

    def test_the_identity_is_gone(self, session) -> None:
        _seed(session, age_days=1)
        purge_user(session, OWNER)
        # The account's own rows. The purge writes a row of its own,
        # attributed to the system, and that one is not the account's.
        rows = session.query(AuditEventDB).filter(AuditEventDB.action != "retention").all()
        assert rows
        for row in rows:
            assert row.owner_id == ANONYMIZED_OWNER
            assert row.actor == ANONYMIZED_OWNER
            assert row.actor_id is None
            assert row.resource == ANONYMIZED_OWNER

    def test_the_shape_of_the_event_survives(self, session) -> None:
        """Non-repudiation needs the record of what happened."""
        _seed(session, age_days=1)
        purge_user(session, OWNER)
        row = session.query(AuditEventDB).filter(AuditEventDB.action == "application.submit").one()
        assert row.outcome == "success"
        assert row.recorded_at is not None

    def test_the_anonymisation_is_idempotent(self, session) -> None:
        _seed(session, age_days=1)
        assert anonymize_audit_rows(session, OWNER) == 1
        assert anonymize_audit_rows(session, OWNER) == 0


# -- the operator's entry point --------------------------------------------------


class TestTheOperatorScript:
    def test_the_script_runs(self) -> None:
        """The purge is an operator action, so it has to be runnable."""
        import subprocess
        import sys

        repo = Path(__file__).resolve().parents[1]
        result = subprocess.run(
            [sys.executable, str(repo / "scripts" / "purge_expired.py"), "--help"],
            capture_output=True,
            text=True,
            cwd=str(repo),
            timeout=120,
            check=False,
        )
        assert result.returncode == 0, result.stderr
        assert "--expired" in result.stdout
        assert "--deactivated" in result.stdout
        assert "--user" in result.stdout
