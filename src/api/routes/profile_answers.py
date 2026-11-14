"""Candidate application-profile and EEO API (WS-20).

Two owner-scoped resources, deliberately kept apart:

- ``/api/profiles/{profile_id}/application-profile`` — the user-confirmed
  preferences and application answers. Stored in the ``application_json``
  column of the profile row; returned alongside the résumé profile only when
  asked for here.
- ``/api/profiles/{profile_id}/eeo`` — voluntary self-identification data. Its
  own table, its own routes, **never** returned by the résumé read and never
  read by the matcher.

Every route resolves the profile through :mod:`src.db.access`, so a profile a
request does not own is a 404 — never an existence oracle. Writes are audited
with **field names and counts only**: no EEO value, no salary figure and no
work-authorization answer is ever written to the audit trail.
"""

from __future__ import annotations

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from src.api.scope import UserScope, current_scope
from src.db import access
from src.db.eeo import CandidateEeoDB
from src.db.profiles import application_profile_from_row
from src.db.session import get_db
from src.resume.application_profile import ApplicationProfile
from src.resume.eeo import EEO_FIELDS, EeoProfile
from src.security.audit import (
    ACTION_PROFILE_UPDATE,
    OUTCOME_SUCCESS,
    SYSTEM_ACTOR,
    record_audit,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/profiles", tags=["profiles"])


class ApplicationProfileResponse(BaseModel):
    """The stored application profile for one résumé profile."""

    profile_id: str
    application_profile: ApplicationProfile


class EeoResponse(BaseModel):
    """The stored EEO selections for one profile (empty when unset)."""

    profile_id: str
    eeo: EeoProfile


class ProfileUpdateAck(BaseModel):
    """Acknowledgement of an application-profile write."""

    profile_id: str
    updated_fields: list[str] = Field(default_factory=list)


class CountryOption(BaseModel):
    """One selectable country (WS-25c)."""

    code: str = Field(..., description="ISO 3166-1 alpha-2 code")
    name: str = Field(..., description="The country's common English name")


class CountriesResponse(BaseModel):
    """The countries the profile may store, for a country picker."""

    countries: list[CountryOption]


def _require_profile(db: Session, scope: UserScope, profile_id: str):
    """The profile row, or a 404 (also for a foreign profile)."""
    row = access.get_profile(db, scope, profile_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Profile not found")
    return row


class QuestionGapResponse(BaseModel):
    """One question the boards ask, and whether the profile answers it."""

    label: str
    times_seen: int
    boards: int
    required: bool
    category: str
    block: str
    #: ``unclassified``, ``not_in_profile``, ``answered`` or
    #: ``never_autofill``.
    coverage: str


class QuestionGapsResponse(BaseModel):
    """The measured question gaps for one profile."""

    profile_id: str
    #: How many distinct questions the measurement has seen.
    total_observed: int
    #: The ranked gaps — most-asked first, excluding what the profile
    #: already answers and excluding consent/EEO (which is never the
    #: agent's to answer).
    questions: list[QuestionGapResponse] = Field(default_factory=list)


@router.get("/countries", response_model=CountriesResponse)
def list_countries() -> CountriesResponse:
    """The countries a profile may state, for a country picker (WS-25c).

    The list comes from the **same table the write path validates against**
    (:mod:`src.applications.countries`), so the console cannot offer a country
    the model would refuse — a picker built from its own copy of the list
    drifts, and the failure is a validation error on a value the UI just
    suggested.

    It is public in the sense that matters: no personal data is involved and
    every authenticated operator needs it to fill a profile. It still requires
    a credential, like every other profile route.
    """
    from src.applications.countries import COUNTRIES

    return CountriesResponse(
        countries=[
            CountryOption(code=code, name=name)
            for code, name in sorted(COUNTRIES.items(), key=lambda item: item[1])
        ]
    )


@router.get("/{profile_id}/question-gaps", response_model=QuestionGapsResponse)
def get_question_gaps(
    profile_id: str,
    db: Annotated[Session, Depends(get_db)],
    scope: Annotated[UserScope, Depends(current_scope)],
    limit: int = 20,
) -> QuestionGapsResponse:
    """The questions the boards actually ask, that this profile cannot answer.

    WS-25b. The profile screen used to show a **guessed** set of fields.
    This returns the **measured** set — the labels the boards publish in
    their own application forms — ranked by how often they are asked, and
    filtered to the ones the profile does not already answer.

    The consent and demographic questions are excluded: they are never
    the agent's to answer, so asking the user to fill a profile field for
    them would be wrong. They are surfaced at approval time instead.

    Args:
        profile_id: The profile to check coverage against.
        limit: How many questions to return (1..100).

    Returns:
        The ranked gaps, with the reason each is listed.

    Raises:
        HTTPException 404: The profile is unknown, or belongs to another
            account (the two answers are indistinguishable).
    """
    from src.db.form_questions import FormQuestionDB
    from src.db.form_questions import question_gaps as read_gaps
    from src.db.profiles import profile_from_row

    row = _require_profile(db, scope, profile_id)
    profile = profile_from_row(row)

    total = db.query(FormQuestionDB).count()
    gaps = read_gaps(profile, limit=max(1, min(limit, 100)))

    return QuestionGapsResponse(
        profile_id=profile_id,
        total_observed=total,
        questions=[
            QuestionGapResponse(
                label=gap.label,
                times_seen=gap.times_seen,
                boards=gap.boards,
                required=gap.required,
                category=gap.category,
                block=gap.block,
                coverage=gap.coverage,
            )
            for gap in gaps
        ],
    )


@router.get("/{profile_id}/application-profile", response_model=ApplicationProfileResponse)
def get_application_profile(
    profile_id: str,
    db: Annotated[Session, Depends(get_db)],
    scope: Annotated[UserScope, Depends(current_scope)],
) -> ApplicationProfileResponse:
    """Return the user-confirmed application profile (empty when never set)."""
    row = _require_profile(db, scope, profile_id)
    return ApplicationProfileResponse(
        profile_id=row.id, application_profile=application_profile_from_row(row)
    )


@router.put("/{profile_id}/application-profile", response_model=ApplicationProfileResponse)
def put_application_profile(
    profile_id: str,
    body: ApplicationProfile,
    db: Annotated[Session, Depends(get_db)],
    scope: Annotated[UserScope, Depends(current_scope)],
) -> ApplicationProfileResponse:
    """Replace the user-confirmed application profile (validated, bounded).

    The body is a full :class:`ApplicationProfile`; Pydantic validation caps
    every list and range, so an oversized or malformed body is a 422 before it
    reaches the database.
    """
    row = _require_profile(db, scope, profile_id)
    row.application_json = body.model_dump(mode="json")
    db.add(row)
    db.commit()

    updated = sorted(body.model_fields_set)
    record_audit(
        ACTION_PROFILE_UPDATE,
        actor=SYSTEM_ACTOR,
        resource=profile_id,
        outcome=OUTCOME_SUCCESS,
        owner_id=scope.user_id,
        metadata={"section": "application_profile", "fields": updated},
    )
    return ApplicationProfileResponse(profile_id=row.id, application_profile=body)


@router.get("/{profile_id}/eeo", response_model=EeoResponse)
def get_eeo(
    profile_id: str,
    db: Annotated[Session, Depends(get_db)],
    scope: Annotated[UserScope, Depends(current_scope)],
) -> EeoResponse:
    """Return the stored EEO selections (all-unset when never provided)."""
    _require_profile(db, scope, profile_id)
    row = access.get_eeo(db, scope, profile_id)
    profile = EeoProfile.model_validate(row.data) if row is not None else EeoProfile()
    return EeoResponse(profile_id=profile_id, eeo=profile)


@router.put("/{profile_id}/eeo", response_model=EeoResponse)
def put_eeo(
    profile_id: str,
    body: EeoProfile,
    db: Annotated[Session, Depends(get_db)],
    scope: Annotated[UserScope, Depends(current_scope)],
) -> EeoResponse:
    """Upsert the voluntary EEO selections for a profile.

    The values are never echoed to logs and never audited (only the fact that a
    write happened, and which fields were present, is recorded). Storing the
    values requires ``opt_in``.
    """
    _require_profile(db, scope, profile_id)
    if not body.opt_in and not body.is_empty():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="EEO data may only be stored with opt_in set to true",
        )
    row = access.get_eeo(db, scope, profile_id)
    if row is None:
        row = CandidateEeoDB(profile_id=profile_id, owner_id=scope.user_id, data={})
    row.data = body.model_dump(mode="json")
    db.add(row)
    db.commit()

    provided = sorted(field for field in EEO_FIELDS if field in body.model_fields_set)
    record_audit(
        ACTION_PROFILE_UPDATE,
        actor=SYSTEM_ACTOR,
        resource=profile_id,
        outcome=OUTCOME_SUCCESS,
        owner_id=scope.user_id,
        metadata={"section": "eeo", "fields_present": provided, "count": len(provided)},
    )
    return EeoResponse(profile_id=profile_id, eeo=body)


@router.delete("/{profile_id}/eeo", status_code=status.HTTP_204_NO_CONTENT)
def delete_eeo(
    profile_id: str,
    db: Annotated[Session, Depends(get_db)],
    scope: Annotated[UserScope, Depends(current_scope)],
) -> Response:
    """Delete a profile's EEO row outright (a real delete, not a soft flag)."""
    _require_profile(db, scope, profile_id)
    row = access.get_eeo(db, scope, profile_id)
    if row is not None:
        db.delete(row)
        db.commit()
        record_audit(
            ACTION_PROFILE_UPDATE,
            actor=SYSTEM_ACTOR,
            resource=profile_id,
            outcome=OUTCOME_SUCCESS,
            owner_id=scope.user_id,
            metadata={"section": "eeo", "deleted": True},
        )
    return Response(status_code=status.HTTP_204_NO_CONTENT)
