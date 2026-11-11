"""Persisted approval requests (WS-06 · SEC-05).

An approval request is the record that stands between a prepared application
and a submission. It holds the **exact** payload a human reviewed, the
identity of the approver, the decision, and — once the application was
executed — the result.

The payload is stored as it was prepared: phase two of the flow restores it
from this row instead of re-deriving it, so *the approved payload is the
submitted payload* (spec S7.2 of the WS-06 document).

The JSON columns are portable ``sa.JSON()`` (SQLite and PostgreSQL), matching
the WS-01/WS-04/WS-05 convention. No foreign keys: an approval record must
outlive the rows it refers to.
"""

from __future__ import annotations

import hashlib
import logging
import os
import uuid
from datetime import UTC, datetime, timedelta

from pydantic import BaseModel
from sqlalchemy import JSON, DateTime, String
from sqlalchemy.orm import Mapped, mapped_column

from src.applications.contracts import ApplicationResult, PreparedApplication
from src.db.base import Base
from src.db.users import LEGACY_OWNER_ID

logger = logging.getLogger(__name__)


class ApprovalStatus:
    """The lifecycle states of an approval request."""

    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXECUTED = "executed"
    FAILED = "failed"
    #: WS-25: the approval was given, and its window closed. This is a
    #: distinct state from ``REJECTED`` (a human said no) and from
    #: ``PENDING`` (nobody said anything): a decision was made, and it is
    #: no longer valid.
    EXPIRED = "expired"


class ApprovalRequestDB(Base):
    """One prepared application awaiting (or carrying) a human decision."""

    __tablename__ = "approval_requests"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    #: The principal that owns this row (WS-13 · A0). NOT NULL and
    #: indexed: ownership is a column, not a convention a route has to
    #: remember. Every access goes through ``src.db.access``.
    owner_id: Mapped[str] = mapped_column(
        String,
        nullable=False,
        index=True,
        default=LEGACY_OWNER_ID,
        server_default=LEGACY_OWNER_ID,
    )
    workflow_id: Mapped[str] = mapped_column(String, index=True)
    adapter_name: Mapped[str] = mapped_column(String)
    job_url: Mapped[str] = mapped_column(String)
    job_title: Mapped[str] = mapped_column(String)
    company_name: Mapped[str] = mapped_column(String)
    payload: Mapped[dict] = mapped_column(JSON, nullable=False)
    status: Mapped[str] = mapped_column(String, default=ApprovalStatus.PENDING, index=True)
    approver: Mapped[str | None] = mapped_column(String, nullable=True)
    decision_reason: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(UTC))
    decided_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    #: WS-25: when the approval stops being valid. An approval past this
    #: moment is **expired**, not executable. The window is measured from
    #: the moment the approval was *created*, so a request that sat
    #: pending for a week does not get a fresh week when it is approved.
    expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)
    #: WS-25: the digest of the profile the payload was built from. An
    #: approval is bound to the profile it was approved against: if the
    #: candidate edits their profile afterwards, the approval no longer
    #: matches what it authorized.
    profile_version: Mapped[str | None] = mapped_column(String(length=64), nullable=True)
    result: Mapped[dict | None] = mapped_column(JSON, nullable=True)


class StoredApproval(BaseModel):
    """An approval request rebuilt from its row."""

    approval_id: str
    workflow_id: str
    adapter_name: str
    job_url: str
    job_title: str
    company_name: str
    payload: PreparedApplication
    status: str
    approver: str | None = None
    decision_reason: str | None = None
    created_at: datetime
    decided_at: datetime | None = None
    #: WS-25: when the approval stops being valid.
    expires_at: datetime | None = None
    #: WS-25: the digest of the profile the payload was built from.
    profile_version: str | None = None
    result: ApplicationResult | None = None

    def is_expired(self, *, now: datetime | None = None) -> bool:
        """Whether the approval's window has closed.

        An approval with no expiry is **not** expired: the column is
        nullable because an approval created before WS-25 has none, and
        refusing to execute it on that basis would break the rows that
        already exist. A missing expiry means "no window was set", not
        "expired forever".
        """
        if self.expires_at is None:
            return False
        moment = now or datetime.now(UTC)
        expiry = self.expires_at
        if expiry.tzinfo is None:
            expiry = expiry.replace(tzinfo=UTC)
        return expiry <= moment


def generate_approval_id() -> str:
    """Short opaque id used as the primary key of an approval request."""
    return uuid.uuid4().hex[:12]


def approval_expiry(
    created_at: datetime | None = None, *, ttl_hours: int | None = None
) -> datetime:
    """When an approval created at *created_at* stops being valid.

    WS-25. The window is measured from **creation**, not from approval:
    an approval that sat pending for six days and is then approved gets
    one day, not a fresh seven — the decision was made about a payload
    that is six days old.

    The TTL is configurable (``APPROVAL_TTL_HOURS``); the default is
    seven days.
    """
    if ttl_hours is None:
        ttl_hours = approval_ttl_hours()
    start = created_at or datetime.now(UTC)
    if start.tzinfo is None:
        start = start.replace(tzinfo=UTC)
    return start + timedelta(hours=ttl_hours)


def approval_ttl_hours() -> int:
    """How long an approval stays valid, in hours."""
    raw = os.getenv("APPROVAL_TTL_HOURS", "").strip()
    if not raw:
        return 168
    try:
        value = int(raw)
    except ValueError:
        logger.warning("APPROVAL_TTL_HOURS=%r is not an integer; using the default", raw)
        return 168
    return value if value > 0 else 168


def profile_version_for(profile_facts: dict[str, str] | None) -> str | None:
    """The digest of the facts a prepared payload was built from.

    WS-25. An approval authorizes a **specific** payload. If the
    candidate's profile changes afterwards, the payload is no longer the
    one the human saw, and the approval no longer matches what it
    authorized. The digest is over the grounded profile facts — the
    ones the payload may answer a form question with — so a change to
    any of them invalidates the approval.
    """
    if not profile_facts:
        return None
    payload = "\x1f".join(f"{key}={profile_facts[key]}" for key in sorted(profile_facts))
    return hashlib.sha256(payload.encode("utf-8", errors="replace")).hexdigest()


def build_approval_row(
    *,
    owner_id: str = LEGACY_OWNER_ID,
    workflow_id: str,
    adapter_name: str,
    prepared: PreparedApplication,
    profile_version: str | None = None,
) -> ApprovalRequestDB:
    """Map a prepared application onto a new pending approval row."""
    request = prepared.request
    now = datetime.now(UTC)
    return ApprovalRequestDB(
        id=generate_approval_id(),
        owner_id=owner_id,
        workflow_id=workflow_id,
        adapter_name=adapter_name,
        job_url=request.job_url,
        job_title=request.job_title,
        company_name=request.company_name,
        payload=prepared.model_dump(mode="json"),
        status=ApprovalStatus.PENDING,
        created_at=now,
        expires_at=approval_expiry(now),
        profile_version=profile_version,
    )


def approval_from_row(row: ApprovalRequestDB) -> StoredApproval:
    """Rebuild the stored approval request from its row."""
    return StoredApproval(
        approval_id=row.id,
        workflow_id=row.workflow_id,
        adapter_name=row.adapter_name,
        job_url=row.job_url,
        job_title=row.job_title,
        company_name=row.company_name,
        payload=PreparedApplication.model_validate(row.payload),
        status=row.status,
        approver=row.approver,
        decision_reason=row.decision_reason,
        created_at=row.created_at,
        decided_at=row.decided_at,
        expires_at=row.expires_at,
        profile_version=row.profile_version,
        result=ApplicationResult.model_validate(row.result) if row.result else None,
    )
