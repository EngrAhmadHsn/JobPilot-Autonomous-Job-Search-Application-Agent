"""Retention, the deletion cascade, and the purge (WS-14 · Phase D).

**What this module is for.** Two obligations that a multi-user
deployment has and a single-operator one does not:

1. **Data does not outlive its purpose.** An application the candidate
   finished with six months ago is a liability, not an asset — it holds
   their name, their phone number, the employer's name, and a
   screenshot of a page they filled in. The age-based purge removes the
   rows *and the files* that are past the retention window.
2. **"Delete my account" means what it says.** The cascade removes
   every artefact of an account: the profile, the tailored resumes and
   their files, the applications, the events, the evidence and its
   files, the approvals, the sessions, and the account itself.

**The audit rows are the exception, and the exception is the point.**
They are **anonymized, not deleted**. A trail that can be rewritten is
not a trail, and non-repudiation needs the record of what happened to
survive the person it happened to. What goes is the *identity*: the
owner, the actor and the resource the row referred to. What stays is
the shape of the event — what happened, when, and how it ended — with
the personal data already masked by the redaction policy.

**The purge is idempotent.** Running it twice changes nothing the
second time, because every step is "delete the rows that are still
there" and "anonymize the rows that are not anonymized yet". That is
what makes it safe to run on a schedule and safe to retry after a
crash.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy.orm import Session

from src.db.applications import ApplicationDB, ApplicationEventDB
from src.db.approval import ApprovalRequestDB
from src.db.audit import AuditEventDB
from src.db.evidence import ApplicationEvidenceDB
from src.db.matches import JobMatchDB
from src.db.profiles import CandidateProfileDB
from src.db.tailored import TailoredResumeDB
from src.security.audit import (
    ACTION_RETENTION,
    OUTCOME_SUCCESS,
    SYSTEM_ACTOR,
    record_audit,
)

logger = logging.getLogger(__name__)

__all__ = [
    "ANONYMIZED_OWNER",
    "RetentionPolicy",
    "anonymize_audit_rows",
    "get_policy",
    "purge_expired",
    "purge_user",
]

#: The owner an anonymized audit row is left with. It is not an account,
#: so no user can ever read those rows — only the platform's own audit
#: view can.
ANONYMIZED_OWNER = "anonymized"


@dataclass(frozen=True)
class RetentionPolicy:
    """How long each kind of data is kept.

    The windows are deliberately different, because the data is: a
    tailored resume is a document the candidate will reuse, an
    application is a record of an interaction with an employer, and a
    session is a credential that should stop working quickly.
    """

    profile_days: int = 365
    tailored_days: int = 180
    application_days: int = 730
    evidence_days: int = 180
    session_days: int = 30
    #: The grace period between a deletion request and the irreversible
    #: purge. The account is deactivated at once; the data goes later,
    #: so an accidental request is recoverable.
    deletion_grace_days: int = 30


def get_policy() -> RetentionPolicy:
    """The retention policy, read from the environment."""
    from src.config.settings import get_settings

    settings = get_settings()
    return RetentionPolicy(
        profile_days=settings.retention_profile_days,
        tailored_days=settings.retention_tailored_days,
        application_days=settings.retention_application_days,
        evidence_days=settings.retention_evidence_days,
        session_days=settings.retention_session_days,
        deletion_grace_days=settings.retention_deletion_grace_days,
    )


# -- helpers -------------------------------------------------------------------


def _delete_files(paths: list[str | None]) -> int:
    """Remove the files at *paths*, and return how many were removed.

    A file that is already gone is not an error: the purge is idempotent,
    and a file that was never written is not a failure.
    """
    removed = 0
    for stored in paths:
        if not stored:
            continue
        candidate = Path(stored)
        try:
            if candidate.is_file():
                candidate.unlink()
                removed += 1
        except OSError as exc:
            logger.warning("Could not remove %s: %s", candidate, exc)
    return removed


def _evidence_file_paths(rows: list[ApplicationEvidenceDB]) -> list[str]:
    """The files the evidence rows point at.

    The browser layer stores an evidence artifact as a **bare file
    name**, relative to the evidence directory — so a bare name has to
    be resolved against the **owner's own** evidence directory
    (WS-14 · Phase B) before it can be removed. An absolute path is
    used as it is.

    The resolution is per row, because one purge may span several
    owners and each of them has their own directory.
    """
    from src.storage.paths import KIND_EVIDENCE, user_dir

    paths: list[str] = []
    for row in rows:
        try:
            directory = user_dir(row.owner_id, KIND_EVIDENCE)
        except Exception:  # noqa: BLE001 - an unusable id has no directory
            directory = None
        for stored in (row.screenshot_path, row.trace_path):
            if not stored:
                continue
            candidate = Path(stored)
            if not candidate.is_absolute() and directory is not None:
                candidate = directory / candidate
            paths.append(str(candidate))
    return paths


def _cutoff(days: int, now: datetime) -> datetime:
    """The moment before which a row is expired."""
    return now - timedelta(days=max(0, days))


def _naive(value: datetime | None) -> datetime | None:
    """A timezone-naive UTC timestamp, for comparison with SQLite rows.

    SQLite stores naive datetimes, so a row read back from it has no
    timezone and comparing it with an aware ``now`` raises. Every
    timestamp in this module is normalised to naive UTC.
    """
    if value is None:
        return None
    if value.tzinfo is None:
        return value
    return value.astimezone(UTC).replace(tzinfo=None)


# -- the age-based purge --------------------------------------------------------


def purge_expired(
    db: Session,
    policy: RetentionPolicy | None = None,
    now: datetime | None = None,
) -> dict[str, int]:
    """Remove the rows (and the files) that are past the retention window.

    Args:
        db: The database session.
        policy: The retention windows; the configured policy by default.
        now: The moment to measure from; the current time by default.

    Returns:
        How many rows and files were removed, per kind.
    """
    policy = policy or get_policy()
    now = _naive(now or datetime.now(UTC))
    removed: dict[str, int] = {
        "profiles": 0,
        "tailored": 0,
        "applications": 0,
        "events": 0,
        "evidence": 0,
        "approvals": 0,
        "sessions": 0,
        "files": 0,
    }

    # The evidence first: it hangs off the applications.
    evidence_cutoff = _cutoff(policy.evidence_days, now)
    evidence_rows = (
        db.query(ApplicationEvidenceDB)
        .filter(ApplicationEvidenceDB.recorded_at < evidence_cutoff)
        .all()
    )
    removed["files"] += _delete_files(_evidence_file_paths(evidence_rows))
    for row in evidence_rows:
        db.delete(row)
    removed["evidence"] = len(evidence_rows)

    # The events and the approvals.
    event_cutoff = _cutoff(policy.application_days, now)
    event_rows = (
        db.query(ApplicationEventDB).filter(ApplicationEventDB.recorded_at < event_cutoff).all()
    )
    for row in event_rows:
        db.delete(row)
    removed["events"] = len(event_rows)

    approval_cutoff = _cutoff(policy.application_days, now)
    approval_rows = (
        db.query(ApprovalRequestDB).filter(ApprovalRequestDB.created_at < approval_cutoff).all()
    )
    for row in approval_rows:
        db.delete(row)
    removed["approvals"] = len(approval_rows)

    # The applications.
    application_cutoff = _cutoff(policy.application_days, now)
    application_rows = (
        db.query(ApplicationDB).filter(ApplicationDB.created_at < application_cutoff).all()
    )
    for row in application_rows:
        db.delete(row)
    removed["applications"] = len(application_rows)

    # The tailored resumes, and their files.
    tailored_cutoff = _cutoff(policy.tailored_days, now)
    tailored_rows = (
        db.query(TailoredResumeDB).filter(TailoredResumeDB.created_at < tailored_cutoff).all()
    )
    removed["files"] += _delete_files([row.docx_path for row in tailored_rows])
    for row in tailored_rows:
        db.delete(row)
    removed["tailored"] = len(tailored_rows)

    # The profiles, and their files. The match rows go with them: a
    # match without its profile is meaningless, and it is the candidate's
    # data either way.
    profile_cutoff = _cutoff(policy.profile_days, now)
    profile_rows = (
        db.query(CandidateProfileDB).filter(CandidateProfileDB.created_at < profile_cutoff).all()
    )
    removed["files"] += _delete_files([row.file_path for row in profile_rows])
    profile_ids = [row.id for row in profile_rows]
    for row in profile_rows:
        db.delete(row)
    removed["profiles"] = len(profile_rows)

    if profile_ids:
        matches = db.query(JobMatchDB).filter(JobMatchDB.profile_id.in_(profile_ids)).all()
        for row in matches:
            db.delete(row)

    # The sessions: a credential that should have stopped working.
    from src.auth.tokens import AccessTokenDB

    session_cutoff = _cutoff(policy.session_days, now)
    sessions = db.query(AccessTokenDB).filter(AccessTokenDB.created_at < session_cutoff).all()
    for row in sessions:
        db.delete(row)
    removed["sessions"] = len(sessions)

    db.commit()

    if any(removed.values()):
        record_audit(
            ACTION_RETENTION,
            actor=SYSTEM_ACTOR,
            resource="retention.purge",
            outcome=OUTCOME_SUCCESS,
            owner_id=ANONYMIZED_OWNER,
            metadata={"removed": removed},
            session=db,
        )
        logger.info("The retention purge removed %s", removed)
    return removed


# -- the deletion cascade --------------------------------------------------------


def anonymize_audit_rows(db: Session, user_id: str) -> int:
    """Strip the identity from an account's audit rows.

    The rows **stay** — non-repudiation needs them — but the owner, the
    actor and the resource lose the identity that connects them to a
    person. The action, the outcome, the timestamp, the workflow id and
    the (already sanitized) metadata stay, because those are what make
    the trail a trail.

    Returns:
        How many rows were anonymized.
    """
    rows = db.query(AuditEventDB).filter(AuditEventDB.owner_id == user_id).all()
    for row in rows:
        row.owner_id = ANONYMIZED_OWNER
        row.actor = ANONYMIZED_OWNER
        row.actor_id = None
        row.actor_kind = "system"
        row.resource = ANONYMIZED_OWNER
    db.commit()
    return len(rows)


def purge_user(
    db: Session,
    user_id: str,
    policy: RetentionPolicy | None = None,
) -> dict[str, int]:
    """Remove every artefact of one account.

    The rows, the files, the sessions and the account itself. The audit
    rows are **anonymized**, not deleted.

    Args:
        db: The database session.
        user_id: The account to purge.
        policy: The retention windows (used for the file cleanup).

    Returns:
        How many rows and files were removed, per kind.
    """
    policy = policy or get_policy()
    removed: dict[str, int] = {
        "profiles": 0,
        "tailored": 0,
        "applications": 0,
        "events": 0,
        "evidence": 0,
        "approvals": 0,
        "matches": 0,
        "sessions": 0,
        "files": 0,
        "audit_anonymized": 0,
    }

    # The evidence and its files.
    evidence_rows = (
        db.query(ApplicationEvidenceDB).filter(ApplicationEvidenceDB.owner_id == user_id).all()
    )
    removed["files"] += _delete_files(_evidence_file_paths(evidence_rows))
    for row in evidence_rows:
        db.delete(row)
    removed["evidence"] = len(evidence_rows)

    # The events.
    event_rows = db.query(ApplicationEventDB).filter(ApplicationEventDB.owner_id == user_id).all()
    for row in event_rows:
        db.delete(row)
    removed["events"] = len(event_rows)

    # The approvals.
    approval_rows = db.query(ApprovalRequestDB).filter(ApprovalRequestDB.owner_id == user_id).all()
    for row in approval_rows:
        db.delete(row)
    removed["approvals"] = len(approval_rows)

    # The applications.
    application_rows = db.query(ApplicationDB).filter(ApplicationDB.owner_id == user_id).all()
    for row in application_rows:
        db.delete(row)
    removed["applications"] = len(application_rows)

    # The tailored resumes, and their files.
    tailored_rows = db.query(TailoredResumeDB).filter(TailoredResumeDB.owner_id == user_id).all()
    removed["files"] += _delete_files([row.docx_path for row in tailored_rows])
    for row in tailored_rows:
        db.delete(row)
    removed["tailored"] = len(tailored_rows)

    # The profiles, their files, and their match history.
    profile_rows = db.query(CandidateProfileDB).filter(CandidateProfileDB.owner_id == user_id).all()
    removed["files"] += _delete_files([row.file_path for row in profile_rows])
    profile_ids = [row.id for row in profile_rows]
    for row in profile_rows:
        db.delete(row)
    removed["profiles"] = len(profile_rows)

    if profile_ids:
        matches = db.query(JobMatchDB).filter(JobMatchDB.profile_id.in_(profile_ids)).all()
        for row in matches:
            db.delete(row)
        removed["matches"] = len(matches)

    # The sessions.
    from src.auth.tokens import AccessTokenDB

    sessions = db.query(AccessTokenDB).filter(AccessTokenDB.user_id == user_id).all()
    for row in sessions:
        db.delete(row)
    removed["sessions"] = len(sessions)

    # The audit rows: anonymized, not deleted.
    removed["audit_anonymized"] = anonymize_audit_rows(db, user_id)

    # The account itself.
    from src.db.users import UserDB

    account = db.get(UserDB, user_id)
    if account is not None:
        db.delete(account)
    db.commit()

    # The user's own directory: the files that are left in it.
    removed["files"] += _remove_user_directory(user_id)

    record_audit(
        ACTION_RETENTION,
        actor=SYSTEM_ACTOR,
        resource="account.purge",
        outcome=OUTCOME_SUCCESS,
        owner_id=ANONYMIZED_OWNER,
        metadata={"removed": removed},
        session=db,
    )
    logger.info("The account %s was purged: %s", user_id, removed)
    return removed


def _remove_user_directory(user_id: str) -> int:
    """Remove the account's own directory, and count the files in it."""
    from src.storage.paths import user_root

    try:
        root = user_root(user_id)
    except Exception:  # noqa: BLE001 - a bad id has no directory
        return 0
    if not root.exists():
        return 0
    files = sum(1 for path in root.rglob("*") if path.is_file())
    try:
        import shutil

        shutil.rmtree(root)
    except OSError as exc:
        logger.warning("Could not remove the account directory %s: %s", root, exc)
        return 0
    return files


def deactivated_accounts_older_than(
    db: Session, grace_days: int, now: datetime | None = None
) -> list[str]:
    """The accounts that asked to be deleted more than *grace_days* ago.

    A deletion request deactivates the account at once; the data goes
    later, so an accidental request is recoverable. This is the list the
    operator's purge acts on.
    """
    from src.db.users import UserDB

    now = _naive(now or datetime.now(UTC))
    cutoff = now - timedelta(days=max(0, grace_days))
    accounts = db.query(UserDB).filter(UserDB.is_active.is_(False)).all()
    return [row.id for row in accounts if (_naive(row.updated_at) or now) <= cutoff]


def account_files(user_id: str) -> list[str]:
    """The files an account owns, for the report."""
    from src.storage.paths import user_root

    try:
        root = user_root(user_id)
    except Exception:  # noqa: BLE001
        return []
    if not root.exists():
        return []
    return [str(path) for path in root.rglob("*") if path.is_file()]


#: The name used when the purge is asked to remove a file by name.
def safe_filename(name: str) -> str:
    """A file name that cannot escape its directory."""
    return os.path.basename(name)
