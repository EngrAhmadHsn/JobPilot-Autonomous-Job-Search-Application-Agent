"""The tracking API (WS-07).

Three read/annotate endpoints over the application lifecycle:

- ``GET /api/applications`` — list the tracked applications, with a status
  filter and pagination.
- ``GET /api/applications/{id}`` — one application **with its full history**,
  ordered by the event id.
- ``PATCH /api/applications/{id}/status`` — record a human outcome.

The endpoint never invents a transition: the status machine decides whether a
move is legal, and the actor rule decides whether the caller may make it. An
illegal move is a 409; a human outcome claimed by a non-human actor is a 403.

The approval record is a different resource and keeps its own path
(``/api/applications/approvals/{id}``, WS-06).
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from src.api.scope import UserScope, current_scope
from src.applications.tracking import (
    ActorNotPermittedError,
    ApplicationStatus,
    IllegalTransitionError,
    transition,
)
from src.db import access
from src.db.applications import ApplicationDB
from src.db.session import get_db

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/applications", tags=["tracking"])

#: The largest page the list endpoint will return.
MAX_PAGE_SIZE = 200
#: The default page size.
DEFAULT_PAGE_SIZE = 50


class ApplicationEventResponse(BaseModel):
    """One entry in an application's history."""

    id: int
    event_type: str
    actor: str
    from_status: str | None = None
    to_status: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    recorded_at: datetime


class ApplicationSummary(BaseModel):
    """A tracked application, without its history."""

    id: str
    profile_id: str | None = None
    job_id: str
    workflow_id: str
    approval_id: str | None = None
    adapter_name: str
    job_url: str
    job_title: str
    company_name: str
    status: str
    tailored_resume_id: str | None = None
    submitted_at: datetime | None = None
    verified_at: datetime | None = None
    application_url: str | None = None
    notes: str | None = None
    created_at: datetime
    updated_at: datetime


class ApplicationDetailResponse(ApplicationSummary):
    """A tracked application with its full, ordered history."""

    events: list[ApplicationEventResponse] = Field(default_factory=list)


class ApplicationListResponse(BaseModel):
    """A page of tracked applications."""

    items: list[ApplicationSummary]
    total: int
    limit: int
    offset: int


class StatusUpdateRequest(BaseModel):
    """A human outcome for a tracked application."""

    status: str = Field(..., min_length=1, description="The status to move to")
    actor: str = Field(
        ...,
        min_length=1,
        description=(
            "Who is recording this. A human outcome needs a human identity: 'human:<who>'."
        ),
    )
    notes: str | None = Field(None, description="A note stored with the application")


def _summary(row: ApplicationDB) -> ApplicationSummary:
    """The application without its history."""
    return ApplicationSummary(
        id=row.id,
        profile_id=row.profile_id,
        job_id=row.job_id,
        workflow_id=row.workflow_id,
        approval_id=row.approval_id,
        adapter_name=row.adapter_name,
        job_url=row.job_url,
        job_title=row.job_title,
        company_name=row.company_name,
        status=row.status,
        tailored_resume_id=row.tailored_resume_id,
        submitted_at=row.submitted_at,
        verified_at=row.verified_at,
        application_url=row.application_url,
        notes=row.notes,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _detail(
    row: ApplicationDB, db: Session, scope: UserScope
) -> ApplicationDetailResponse:
    """The application with its full history, in append order.

    The history is read through the scoped accessor, so the events of an
    application the caller may read are the events **they** may read —
    the two cannot drift apart.
    """
    events = [
        ApplicationEventResponse(
            id=event.id,
            event_type=event.event_type,
            actor=event.actor,
            from_status=event.from_status,
            to_status=event.to_status,
            metadata=dict(event.extra_metadata or {}),
            recorded_at=event.recorded_at,
        )
        for event in access.list_application_events(db, scope, row.id)
    ]
    return ApplicationDetailResponse(**_summary(row).model_dump(), events=events)


def _parse_statuses(values: list[str] | None) -> list[ApplicationStatus]:
    """Parse the requested status filter.

    Raises:
        HTTPException 400: one of the values is not a known status.
    """
    if not values:
        return []
    parsed: list[ApplicationStatus] = []
    for value in values:
        for part in value.split(","):
            part = part.strip()
            if not part:
                continue
            try:
                parsed.append(ApplicationStatus(part))
            except ValueError as exc:
                known = ", ".join(status.value for status in ApplicationStatus)
                raise HTTPException(
                    status_code=400,
                    detail=f"Unknown status {part!r}. Known statuses: {known}.",
                ) from exc
    return parsed


@router.get("", response_model=ApplicationListResponse)
def list_applications(
    db: Annotated[Session, Depends(get_db)],
    scope: Annotated[UserScope, Depends(current_scope)],
    status: Annotated[list[str] | None, Query()] = None,
    profile_id: str | None = None,
    limit: Annotated[int, Query(ge=1, le=MAX_PAGE_SIZE)] = DEFAULT_PAGE_SIZE,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> ApplicationListResponse:
    """List the tracked applications, newest first.

    Only the caller's own applications are listed. The listing and the
    total both go through the scoped accessors, so a total that counted
    other users' rows — and a list that showed them — are both
    impossible by construction rather than by a check somebody has to
    remember.

    Args:
        db: The request-scoped database session.
        scope: The caller's access scope.
        status: Filter by one or more statuses (repeat the parameter, or
            pass a comma-separated list).
        profile_id: Filter by the candidate profile.
        limit: The page size (at most 200).
        offset: How many applications to skip.

    Returns:
        The page of applications and the total number that matched.
    """
    statuses = _parse_statuses(status)
    status_filter = statuses[0].value if len(statuses) == 1 else None

    rows = access.list_applications(
        db,
        scope,
        status=status_filter,
        profile_id=profile_id,
        limit=limit,
        offset=offset,
    )
    total = access.count_applications(
        db,
        scope,
        status=status_filter,
        profile_id=profile_id,
    )

    return ApplicationListResponse(
        items=[_summary(row) for row in rows],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/{application_id}", response_model=ApplicationDetailResponse)
def get_application(
    application_id: str,
    db: Annotated[Session, Depends(get_db)],
    scope: Annotated[UserScope, Depends(current_scope)],
) -> ApplicationDetailResponse:
    """Return a tracked application with its full history.

    Raises:
        HTTPException 404: the application is unknown.
    """
    row = access.get_application(db, scope, application_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Application not found")
    return _detail(row, db, scope)


@router.patch("/{application_id}/status", response_model=ApplicationDetailResponse)
def update_application_status(
    application_id: str,
    req: StatusUpdateRequest,
    db: Annotated[Session, Depends(get_db)],
    scope: Annotated[UserScope, Depends(current_scope)],
) -> ApplicationDetailResponse:
    """Record a human outcome on a tracked application.

    The status machine decides whether the move is legal, and the actor rule
    decides whether the caller may make it: a human outcome needs a human
    identity, so the agent can never record an offer it was not told about.

    Args:
        application_id: The application to move.
        req: The status, the actor, and an optional note.
        db: The request-scoped database session.

    Returns:
        The updated application, with its history.

    Raises:
        HTTPException 400: the status is not a known status.
        HTTPException 403: the actor may not set this status.
        HTTPException 404: the application is unknown.
        HTTPException 409: the move is not a legal transition.
    """
    row = access.get_application(db, scope, application_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Application not found")

    try:
        target = ApplicationStatus(req.status)
    except ValueError as exc:
        known = ", ".join(status.value for status in ApplicationStatus)
        raise HTTPException(
            status_code=400,
            detail=f"Unknown status {req.status!r}. Known statuses: {known}.",
        ) from exc

    try:
        transition(
            row,
            target,
            actor=req.actor,
            db=db,
            metadata={"notes": req.notes} if req.notes else None,
        )
    except ActorNotPermittedError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except IllegalTransitionError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    if req.notes:
        row.notes = req.notes
        db.commit()

    return _detail(row, db, scope)
