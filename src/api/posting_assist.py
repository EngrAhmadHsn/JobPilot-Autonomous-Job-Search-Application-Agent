"""One-time authorization for the candidate's own local, fill-only browser."""

from __future__ import annotations

import hashlib
import re
import secrets
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from urllib.parse import urlsplit

from fastapi import HTTPException
from sqlalchemy.orm import Session

from src.api.posting_review import (
    PostingReview,
    review_answers_are_current,
    select_posting_document,
)
from src.api.validation import MAX_UPLOAD_BYTES
from src.applications.contracts import PreparedApplication
from src.applications.posting_form import PostingForm, read_posting_form
from src.config.settings import get_settings
from src.db import access
from src.db.access import UserScope
from src.db.approval import ApprovalStatus
from src.db.jobs import JobDB
from src.security.allowlist import DisallowedDomainError, assert_job_url_allowed
from src.security.audit import OUTCOME_SUCCESS, Actor, record_audit
from src.security.policy import SubmissionPolicy, get_submission_policy

TTL_MINUTES = 10


class FillRefused(ValueError):
    """A safe-to-display refusal; never embed a code or candidate data."""


@dataclass(frozen=True, repr=False)
class LocalFill:
    owner_id: str
    application_id: str
    job_url: str
    full_name: str
    email: str
    phone: str
    resume_name: str
    resume_bytes: bytes = field(repr=False)
    form: PostingForm = field(repr=False)


def canonical_fill_target(url: str) -> bool:
    try:
        target = urlsplit(url)
        return (
            target.scheme == "https"
            and target.netloc.lower() in {"boards.greenhouse.io", "job-boards.greenhouse.io"}
            and re.fullmatch(r"/[A-Za-z0-9_-]+/jobs/[0-9]+/?", target.path) is not None
        )
    except ValueError:
        return False


def assist_available(url: str, review: PostingReview) -> bool:
    if (
        get_settings().app_env != "development"
        or not canonical_fill_target(url)
        or review.form.state != "available"
        or not review.form.questions
    ):
        return False
    try:
        assert_job_url_allowed(url)
    except DisallowedDomainError:
        return False
    return get_submission_policy() == SubmissionPolicy.REQUIRE_APPROVAL


def _now(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=UTC)


def _checked_packet(db: Session, scope: UserScope, application_id: str, *, local: bool):
    app = access.get_application(db, scope, application_id)
    if app is None or app.owner_id != scope.user_id or app.adapter_name != "manual-handoff":
        raise HTTPException(404, "Posting review not found")
    row = access.get_approval(db, scope, app.approval_id or "")
    if row is None or row.owner_id != scope.user_id:
        raise HTTPException(404, "Posting review not found")
    if row.status != ApprovalStatus.PENDING or (
        row.expires_at and _now(row.expires_at) <= datetime.now(UTC)
    ):
        raise FillRefused("This review has expired or is no longer pending. Prepare a new review.")
    review = PostingReview.model_validate(row.payload.get("posting_review"))
    request = PreparedApplication.model_validate(row.payload).request
    if not assist_available(request.job_url, review) or review.missing:
        raise FillRefused(
            "This review is not ready for local autofill. Check its questions or continue manually."
        )
    job = db.get(JobDB, review.job_id)
    if (
        job is None
        or job.application_url != request.job_url
        or not review_answers_are_current(db, scope, review)
    ):
        raise FillRefused("The posting or your answers changed. Prepare a new review.")
    document = select_posting_document(db, scope, job.id, review.document_id)
    if document.sha256 != review.document_sha256:
        raise FillRefused("The résumé changed. Prepare a new review.")
    # Recheck the public form before any upload or typing. This sends no user data.
    live = read_posting_form(job.id, request.job_url, local=local).form
    if live.state != "available" or {q.question_key for q in live.questions} != {
        q.question_key for q in review.form.questions
    }:
        raise FillRefused(
            "The employer form changed or could not be checked. Refresh the posting first."
        )
    return row, review, request, document


def authorize_local_fill(
    db: Session, scope: UserScope, application_id: str
) -> tuple[str, datetime]:
    row, *_ = _checked_packet(db, scope, application_id, local=False)
    now = datetime.now(UTC)
    expiry = (
        min(now + timedelta(minutes=TTL_MINUTES), _now(row.expires_at))
        if row.expires_at
        else now + timedelta(minutes=TTL_MINUTES)
    )
    code = secrets.token_urlsafe(32)
    digest = hashlib.sha256(code.encode("ascii")).hexdigest()
    access.replace_local_fill_grant(db, scope, application_id, digest, expiry)
    db.commit()
    record_audit(
        "application.fill_authorized",
        actor=Actor.user(scope.user_id),
        resource=application_id,
        outcome=OUTCOME_SUCCESS,
        owner_id=scope.user_id,
        metadata={"purpose": "fill_only"},
    )
    return code, expiry


def claim_local_fill(db: Session, code: str) -> LocalFill:
    """Redeem on the machine hosting JobPilot, never via HTTP. No sessions or credentials are shared."""
    denied = (
        "This code is invalid, expired, or already used. Request a new one from the saved review."
    )
    if not isinstance(code, str) or not re.fullmatch(r"[a-zA-Z0-9_-]{43}", code):
        raise FillRefused(denied)
    digest = hashlib.sha256(code.encode("ascii")).hexdigest()
    now = datetime.now(UTC)
    # Consume atomically BEFORE any checks that could lead to a real browser action.
    claimed = access.consume_local_fill_grant(db, digest, now)
    db.commit()
    if claimed is None:
        raise FillRefused(denied)
    owner_id, application_id = claimed
    scope = UserScope(user_id=owner_id)
    try:
        _, review, request, document = _checked_packet(
            db, scope, application_id, local=True
        )
        with document.path.open("rb") as source:
            content = source.read(MAX_UPLOAD_BYTES + 1)
        if (
            not content
            or len(content) > MAX_UPLOAD_BYTES
            or hashlib.sha256(content).hexdigest() != review.document_sha256
        ):
            raise FillRefused("The reviewed file is no longer available. Nothing was filled.")
    except (HTTPException, OSError) as exc:
        raise FillRefused(
            "The reviewed posting or résumé is no longer available. Nothing was filled."
        ) from exc
    record_audit(
        "application.fill_code_claimed",
        actor=Actor.user(scope.user_id),
        resource=application_id,
        outcome=OUTCOME_SUCCESS,
        owner_id=scope.user_id,
    )
    return LocalFill(
        scope.user_id,
        application_id,
        request.job_url,
        request.candidate_name,
        request.email,
        request.phone,
        document.path.name,
        content,
        review.form,
    )
