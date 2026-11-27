"""Document and question provenance for a stored listing's manual handoff."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

from fastapi import HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from src.api.routes.documents import owned_document_path
from src.api.routes.posting_applications import fill_saved_answers
from src.api.validation import MAX_UPLOAD_BYTES
from src.applications.assist_adapter import split_candidate_name
from src.applications.contracts import ApplicationRequest
from src.applications.posting_form import AnswerValue, PostingForm, read_posting_form
from src.db import access
from src.db.access import UserScope
from src.db.jobs import JobDB


@dataclass(frozen=True)
class SelectedDocument:
    id: str
    path: Path
    profile_id: str
    tailored_id: str | None
    sha256: str


def _file_digest(path: Path) -> str:
    try:
        with path.open("rb") as source:
            payload = source.read(MAX_UPLOAD_BYTES + 1)
    except OSError as exc:
        raise HTTPException(404, "The résumé is not available") from exc
    if not payload or len(payload) > MAX_UPLOAD_BYTES:
        raise HTTPException(422, "Select a nonempty résumé within the upload size limit.")
    return hashlib.sha256(payload).hexdigest()


def select_posting_document(
    db: Session, scope: UserScope, job_id: str, document_id: str
) -> SelectedDocument:
    """Resolve only an owned upload or a validated draft for this exact listing."""
    kind, _, record_id = document_id.partition("-")
    tailored_id = None
    if kind == "profile" and record_id:
        profile_id = record_id
    elif kind == "tailored" and record_id:
        draft = access.get_tailored(db, scope, record_id)
        if draft is None or draft.owner_id != scope.user_id or draft.job_id != job_id:
            raise HTTPException(404, "Résumé not found for this posting")
        if draft.factuality.get("passed") is not True:
            raise HTTPException(
                422,
                "This tailored draft did not pass factuality checks. Use the original or fix the draft.",
            )
        profile_id = draft.profile_id
        tailored_id = draft.id
    else:
        raise HTTPException(404, "Résumé not found")

    profile = access.get_profile(db, scope, profile_id)
    if profile is None or profile.owner_id != scope.user_id:
        raise HTTPException(404, "Résumé not found")
    path = owned_document_path(
        draft.docx_path if tailored_id is not None else profile.file_path, scope
    )
    return SelectedDocument(document_id, path, profile_id, tailored_id, _file_digest(path))


class PostingReview(BaseModel):
    """The candidate's local review packet; never a request to the ATS."""

    job_id: str
    document_id: str
    document_filename: str
    document_sha256: str = Field(exclude=False)
    form: PostingForm
    answers: dict[str, AnswerValue] = Field(default_factory=dict)
    missing: list[str] = Field(default_factory=list)
    on_employer_site: list[str] = Field(default_factory=list)


def build_posting_review(
    db: Session,
    scope: UserScope,
    job: JobDB,
    request: ApplicationRequest,
    document: SelectedDocument,
) -> PostingReview:
    form = fill_saved_answers(db, scope, job, read_posting_form(job.id, job.application_url))
    name = split_candidate_name(request.candidate_name)
    contact = {
        "name": request.candidate_name,
        "first_name": name[0] if name else None,
        "last_name": name[1] if name else None,
        "email": request.email,
        "phone": request.phone,
    }
    missing = []
    employer = []
    for question in form.questions:
        if question.kind == "employer":
            if question.required:
                employer.append(question.label)
        elif question.required and question.kind != "resume":
            value = (
                contact.get(question.field_name or "")
                if question.kind == "contact"
                else question.answer
            )
            if not value:
                missing.append(question.label)
    return PostingReview(
        job_id=job.id,
        document_id=document.id,
        document_filename=document.path.name,
        document_sha256=document.sha256,
        form=form,
        answers={q.question_key: q.answer for q in form.questions if q.answer is not None},
        missing=missing,
        on_employer_site=employer,
    )


def review_answers_are_current(db: Session, scope: UserScope, review: PostingReview) -> bool:
    """Compare only recorded question revisions; no board request on reopening a review."""
    keys = [
        q.question_key
        for q in review.form.questions
        if q.kind in {"text", "textarea", "select", "multiselect"}
    ]
    if not keys:
        return True
    rows = access.employer_answers_for_questions(db, scope, review.job_id, keys)
    return {key: row.answer for key, row in rows.items()} == review.answers


def document_is_current(db: Session, scope: UserScope, review: PostingReview) -> bool:
    try:
        return (
            select_posting_document(db, scope, review.job_id, review.document_id).sha256
            == review.document_sha256
        )
    except HTTPException:
        return False
