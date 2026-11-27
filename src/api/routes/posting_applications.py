"""The listing's public questions and the signed-in account's answer library."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel, Field
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from src.api.scope import UserScope, current_scope
from src.applications.posting_form import (
    MAX_ANSWER_LENGTH,
    AnswerValue,
    LoadedForm,
    PostingForm,
    PostingQuestion,
    read_posting_form,
    validated_answer,
)
from src.db import access
from src.db.jobs import JobDB
from src.db.session import get_db
from src.security.audit import OUTCOME_SUCCESS, Actor, record_audit

router = APIRouter(tags=["application preparation"])
DB = Annotated[Session, Depends(get_db)]
Scope = Annotated[UserScope, Depends(current_scope)]

AnswerText = Annotated[str, Field(min_length=1, max_length=MAX_ANSWER_LENGTH)]
ChoiceValue = Annotated[str, Field(min_length=1, max_length=200)]
BoundedAnswer = AnswerText | Annotated[list[ChoiceValue], Field(min_length=1, max_length=100)]


class AnswerUpdate(BaseModel):
    answer: BoundedAnswer


class PostingAnswer(AnswerUpdate):
    question_key: str = Field(pattern=r"^[0-9a-f]{64}$")


class PostingAnswersUpdate(BaseModel):
    answers: list[PostingAnswer] = Field(min_length=1, max_length=100)


class EmployerAnswer(PostingQuestion):
    id: str
    job_id: str
    company_name: str
    job_title: str
    updated_at: datetime
    answer: AnswerValue


class EmployerAnswersPage(BaseModel):
    items: list[EmployerAnswer]
    next_offset: int | None = None


def require_stored_job(db: Session, job_id: str) -> JobDB:
    row = db.get(JobDB, job_id)
    if row is None:
        raise HTTPException(404, "Job listing not found")
    return row


def fill_saved_answers(
    db: Session, scope: UserScope, job: JobDB, loaded: LoadedForm
) -> PostingForm:
    form = loaded.form
    if form.state != "available" or not form.questions:
        return form
    current_keys = [item.question_key for item in form.questions]
    saved = access.employer_answers_for_questions(db, scope, job.id, current_keys)
    rows = []
    for question in form.questions:
        try:
            row = saved[question.question_key]
        except KeyError:
            rows.append(question)
            continue
        try:
            answer = validated_answer(question, row.answer)
        except ValueError:
            answer = None
        rows.append(question.model_copy(update={"answer": answer}))
    return form.model_copy(update={"questions": rows})


@router.get("/api/jobs/{job_id}/application-form", response_model=PostingForm)
def get_posting_form(job_id: str, db: DB, scope: Scope, response: Response) -> PostingForm:
    response.headers["Cache-Control"] = "private, no-store"
    job = require_stored_job(db, job_id)
    return fill_saved_answers(db, scope, job, read_posting_form(job.id, job.application_url))


def _answer_or_422(question: PostingQuestion, answer: AnswerValue) -> AnswerValue:
    try:
        return validated_answer(question, answer)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


def _audit(scope: UserScope, resource: str, action: str, count: int) -> None:
    record_audit(
        f"application.employer_answers_{action}",
        actor=Actor.user(scope.user_id),
        resource=resource,
        owner_id=scope.user_id,
        outcome=OUTCOME_SUCCESS,
        metadata={"count": count},
    )


@router.put("/api/jobs/{job_id}/application-form/answers", response_model=PostingForm)
def save_posting_answers(
    job_id: str, body: PostingAnswersUpdate, db: DB, scope: Scope, response: Response
) -> PostingForm:
    response.headers["Cache-Control"] = "private, no-store"
    job = require_stored_job(db, job_id)
    loaded = read_posting_form(job.id, job.application_url)
    if loaded.form.state != "available":
        raise HTTPException(
            409, "The employer's form could not be checked. Try again before saving."
        )
    questions = {question.question_key: question for question in loaded.form.questions}
    keys = {item.question_key for item in body.answers}
    if len(keys) != len(body.answers):
        raise HTTPException(422, "Enter one answer for each question.")
    if keys - questions.keys():
        raise HTTPException(
            409, "The employer's form has changed. Reload its current questions before saving."
        )
    entries = [
        {
            "question_key": key,
            "question": questions[key].model_dump(exclude={"answer"}),
            "answer": _answer_or_422(questions[key], value),
        }
        for key, value in ((item.question_key, item.answer) for item in body.answers)
    ]
    access.upsert_employer_answers(db, scope, job, entries)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            409, "An answer was saved at the same time. Refresh and try again."
        ) from exc
    _audit(scope, job.id, "saved", len(entries))
    return fill_saved_answers(db, scope, job, loaded)


def _employer_answer(row) -> EmployerAnswer:
    return EmployerAnswer.model_validate(
        {
            **row.question,
            "id": row.id,
            "job_id": row.job_id,
            "company_name": row.company_name,
            "job_title": row.job_title,
            "answer": row.answer,
            "updated_at": row.updated_at,
        }
    )


@router.get("/api/profiles/employer-answers", response_model=EmployerAnswersPage)
def list_employer_answers(
    db: DB,
    scope: Scope,
    response: Response,
    offset: Annotated[int, Query(ge=0, le=100_000)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> EmployerAnswersPage:
    response.headers["Cache-Control"] = "private, no-store"
    rows = access.list_employer_answers(db, scope, offset=offset, limit=limit + 1)
    return EmployerAnswersPage(
        items=[_employer_answer(row) for row in rows[:limit]],
        next_offset=offset + limit if len(rows) > limit else None,
    )


@router.put("/api/profiles/employer-answers/{answer_id}", response_model=EmployerAnswer)
def edit_employer_answer(
    answer_id: str, body: AnswerUpdate, db: DB, scope: Scope, response: Response
):
    response.headers["Cache-Control"] = "private, no-store"
    row = access.get_employer_answer(db, scope, answer_id)
    if row is None:
        raise HTTPException(404, "Employer answer not found")
    # It is safe to edit an old answer in Profile without refetching the employer:
    # only the identical posting/question revision can use it in a new review.
    row.answer = _answer_or_422(PostingQuestion.model_validate(row.question), body.answer)
    row.updated_at = datetime.now(UTC)
    db.commit()
    _audit(scope, row.id, "edited", 1)
    return _employer_answer(row)


@router.delete("/api/profiles/employer-answers/{answer_id}", status_code=204)
def delete_employer_answer(answer_id: str, db: DB, scope: Scope) -> Response:
    row = access.get_employer_answer(db, scope, answer_id)
    if row is None:
        raise HTTPException(404, "Employer answer not found")
    db.delete(row)
    db.commit()
    _audit(scope, answer_id, "deleted", 1)
    return Response(status_code=204, headers={"Cache-Control": "private, no-store"})
