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

import uuid
from datetime import UTC, datetime

from pydantic import BaseModel
from sqlalchemy import JSON, DateTime, String
from sqlalchemy.orm import Mapped, mapped_column

from src.applications.contracts import ApplicationResult, PreparedApplication
from src.db.base import Base
from src.db.users import LEGACY_OWNER_ID


class ApprovalStatus:
    """The lifecycle states of an approval request."""

    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXECUTED = "executed"
    FAILED = "failed"


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
    result: ApplicationResult | None = None


def generate_approval_id() -> str:
    """Short opaque id used as the primary key of an approval request."""
    return uuid.uuid4().hex[:12]


def build_approval_row(
    *,
    owner_id: str = LEGACY_OWNER_ID,
    workflow_id: str,
    adapter_name: str,
    prepared: PreparedApplication,
) -> ApprovalRequestDB:
    """Map a prepared application onto a new pending approval row."""
    request = prepared.request
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
        result=ApplicationResult.model_validate(row.result) if row.result else None,
    )
