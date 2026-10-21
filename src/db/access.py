"""Scoped data access — the authorization layer (WS-13 · A0).

**Why this module exists.** WS-13 changed the threat model: the caller is
no longer assumed to be the operator, so a request may be trying to read
somebody else's data. The tempting fix is a check in each route — and
that is a check that one of the routes will eventually miss. There are
**eleven** direct reads of user-scoped tables across the route modules
today, and every one of them is a potential IDOR.

So the check lives here, in the layer that fetches the data, and the
routes are forbidden from touching those tables directly. A route that
wants a profile asks this module for it, and this module applies the
owner's filter whether or not the route remembered to.

**The rules, in code.**

- A :class:`UserScope` is the *only* way to reach user-scoped data, and
  it is built from a verified principal — never from a request body, a
  header, a query parameter or a path.
- Every accessor filters by ``owner_id``. A superuser scope may read
  across owners; that is the platform's own audit view, and it is the
  only exception.
- A resource that exists but belongs to somebody else is **not found**,
  not "forbidden". The accessors return ``None`` for both, so the caller
  answers 404 and the API never becomes an existence oracle.
- The one table that is *not* user-scoped is ``jobs``: it holds public
  board data and is deliberately shared. It has no accessors here
  because it needs none.

**What A0 does and does not change.** A0 lands the schema and these
accessors, and the routes start calling them — but until Phase A2 the
scope the routes pass is still the single legacy owner, so the
*behaviour* is unchanged while the *shape* of every call is already the
final one. That is deliberate: it means A2 is a small, mechanical change
(the scope source) rather than a rewrite (the call sites), and it means
no intermediate commit claims an isolation it does not have.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session

from src.db.applications import ApplicationDB, ApplicationEventDB
from src.db.approval import ApprovalRequestDB
from src.db.audit import AuditEventDB
from src.db.evidence import ApplicationEvidenceDB
from src.db.matches import JobMatchDB
from src.db.profiles import CandidateProfileDB
from src.db.tailored import TailoredResumeDB
from src.db.users import LEGACY_OWNER_ID

__all__ = [
    "LEGACY_SCOPE",
    "UserScope",
    "claim_legacy_rows",
    "count_applications",
    "get_application",
    "get_application_by_approval",
    "get_approval",
    "get_profile",
    "get_tailored",
    "list_applications",
    "list_audit_events",
    "list_profiles",
    "list_tailored",
]


@dataclass(frozen=True)
class UserScope:
    """The principal a request acts as.

    Built from a **verified** identity. The two fields are the whole
    contract: ``user_id`` says whose data may be touched, and
    ``is_superuser`` says whether the platform's audit view may look
    across owners.
    """

    user_id: str
    is_superuser: bool = False

    def owns(self, owner_id: str | None) -> bool:
        """True when a row with this owner may be read by this scope."""
        if self.is_superuser:
            return True
        return owner_id is not None and owner_id == self.user_id


#: The scope that owns everything that predates the identity work.
#:
#: The migration backfills every existing row to a single ``legacy``
#: owner, so this scope sees the whole corpus. It is the *only* scope
#: that is not derived from an authenticated principal, and it is
#: replaced by the request's scope in Phase A2. It is deliberately
#: conspicuous: a reader should be able to see exactly where the
#: single-tenant assumption still lives.
LEGACY_SCOPE = UserScope(user_id=LEGACY_OWNER_ID, is_superuser=True)


def _owned(statement: Select, model: type, scope: UserScope) -> Select:
    """Add the owner filter to *statement* unless the scope may read all."""
    if scope.is_superuser:
        return statement
    return statement.where(model.owner_id == scope.user_id)


# -- the legacy corpus --------------------------------------------------------


#: The user-scoped tables, in the order the claim walks them. The order
#: is irrelevant to the outcome and is kept stable so the claim is
#: reproducible.
_OWNED_MODELS: tuple[type, ...] = (
    CandidateProfileDB,
    JobMatchDB,
    TailoredResumeDB,
    ApplicationDB,
    ApplicationEventDB,
    ApplicationEvidenceDB,
    ApprovalRequestDB,
    AuditEventDB,
)


def claim_legacy_rows(db: Session, user_id: str) -> int:
    """Give the rows that pre-date the identity work to *user_id*.

    The migration backfilled every pre-existing row to the single
    ``legacy`` owner, because those rows had no owner the data could
    justify. That owner is an account nobody can authenticate as, so the
    rows are reachable by nobody — which is safe, and useless.

    The **first** account to register takes them: an operator's existing
    resumes, matches, applications and audit rows should reach the
    operator's own account rather than be orphaned. The claim is
    therefore a one-time transfer: once the legacy rows are gone, a
    second registration claims nothing, so a later user cannot take
    over the first user's data by registering.

    Args:
        db: The database session.
        user_id: The account that takes the rows.

    Returns:
        How many rows were transferred.
    """
    if not user_id or user_id == LEGACY_OWNER_ID:
        return 0

    moved = 0
    for model in _OWNED_MODELS:
        result = (
            db.query(model)
            .filter(model.owner_id == LEGACY_OWNER_ID)
            .update({"owner_id": user_id}, synchronize_session=False)
        )
        moved += int(result or 0)
    if moved:
        db.commit()
    return moved


# -- candidate profiles -------------------------------------------------------


def get_profile(db: Session, scope: UserScope, profile_id: str) -> CandidateProfileDB | None:
    """The profile *profile_id* if this scope may read it, else ``None``."""
    if not profile_id:
        return None
    statement = select(CandidateProfileDB).where(CandidateProfileDB.id == profile_id)
    return db.execute(_owned(statement, CandidateProfileDB, scope)).scalar_one_or_none()


def list_profiles(db: Session, scope: UserScope) -> list[CandidateProfileDB]:
    """Every profile this scope may read."""
    statement = select(CandidateProfileDB).order_by(CandidateProfileDB.created_at.desc())
    return list(db.execute(_owned(statement, CandidateProfileDB, scope)).scalars())


# -- job matches --------------------------------------------------------------


def list_job_matches(db: Session, scope: UserScope, profile_id: str) -> list[JobMatchDB]:
    """The match history of one profile, if the scope may read it."""
    statement = (
        select(JobMatchDB).where(JobMatchDB.profile_id == profile_id).order_by(JobMatchDB.id.desc())
    )
    return list(db.execute(_owned(statement, JobMatchDB, scope)).scalars())


# -- tailored resumes ---------------------------------------------------------


def get_tailored(db: Session, scope: UserScope, tailoring_id: str) -> TailoredResumeDB | None:
    """The tailored resume *tailoring_id* if this scope may read it."""
    if not tailoring_id:
        return None
    statement = select(TailoredResumeDB).where(TailoredResumeDB.id == tailoring_id)
    return db.execute(_owned(statement, TailoredResumeDB, scope)).scalar_one_or_none()


def list_tailored(
    db: Session, scope: UserScope, profile_id: str | None = None
) -> list[TailoredResumeDB]:
    """The tailored resumes this scope may read, optionally for one profile."""
    statement = select(TailoredResumeDB).order_by(TailoredResumeDB.created_at.desc())
    if profile_id:
        statement = statement.where(TailoredResumeDB.profile_id == profile_id)
    return list(db.execute(_owned(statement, TailoredResumeDB, scope)).scalars())


# -- applications -------------------------------------------------------------


def get_application(db: Session, scope: UserScope, application_id: str) -> ApplicationDB | None:
    """The application *application_id* if this scope may read it.

    This is the accessor that closes the IDOR the brief named: reading
    ``/api/applications/123`` as another user returns ``None``, and the
    route answers 404 — the same answer it gives for an id that never
    existed.
    """
    if not application_id:
        return None
    statement = select(ApplicationDB).where(ApplicationDB.id == application_id)
    return db.execute(_owned(statement, ApplicationDB, scope)).scalar_one_or_none()


def list_applications(
    db: Session,
    scope: UserScope,
    *,
    status: str | None = None,
    profile_id: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[ApplicationDB]:
    """The applications this scope may read, filtered and paged.

    The filters are applied **inside** the owner filter, not after it:
    a filter that ran on the unfiltered set would be a filter that
    counted other users' rows.
    """
    statement = select(ApplicationDB).order_by(ApplicationDB.created_at.desc())
    if status:
        statement = statement.where(ApplicationDB.status == status)
    if profile_id:
        statement = statement.where(ApplicationDB.profile_id == profile_id)
    statement = statement.limit(max(1, min(limit, 200))).offset(max(0, offset))
    return list(db.execute(_owned(statement, ApplicationDB, scope)).scalars())


def count_applications(
    db: Session,
    scope: UserScope,
    *,
    status: str | None = None,
    profile_id: str | None = None,
) -> int:
    """How many applications this scope may read, with the same filters.

    The count is scoped too. A total that counted other users' rows
    would leak the size of somebody else's activity, and a paginated
    list whose total disagrees with its items is a bug in its own right.
    """
    statement = select(func.count()).select_from(ApplicationDB)
    if status:
        statement = statement.where(ApplicationDB.status == status)
    if profile_id:
        statement = statement.where(ApplicationDB.profile_id == profile_id)
    return int(db.execute(_owned(statement, ApplicationDB, scope)).scalar() or 0)


def get_application_by_approval(
    db: Session, scope: UserScope, approval_id: str
) -> ApplicationDB | None:
    """The application that was created from this approval, if any.

    The approval and the application are two rows for one act, and both
    carry an owner. Looking the application up by its approval id must
    therefore be scoped too — otherwise the lookup is a second, unfiltered
    door into the applications table.
    """
    if not approval_id:
        return None
    statement = select(ApplicationDB).where(ApplicationDB.approval_id == approval_id)
    return db.execute(_owned(statement, ApplicationDB, scope)).scalar_one_or_none()


def list_application_events(
    db: Session, scope: UserScope, application_id: str
) -> list[ApplicationEventDB]:
    """The history of one application, if the scope may read it."""
    statement = (
        select(ApplicationEventDB)
        .where(ApplicationEventDB.application_id == application_id)
        .order_by(ApplicationEventDB.id)
    )
    return list(db.execute(_owned(statement, ApplicationEventDB, scope)).scalars())


# -- approvals ----------------------------------------------------------------


def get_approval(db: Session, scope: UserScope, approval_id: str) -> ApprovalRequestDB | None:
    """The approval request *approval_id* if this scope may read it."""
    if not approval_id:
        return None
    statement = select(ApprovalRequestDB).where(ApprovalRequestDB.id == approval_id)
    return db.execute(_owned(statement, ApprovalRequestDB, scope)).scalar_one_or_none()


# -- evidence -----------------------------------------------------------------


def list_evidence(db: Session, scope: UserScope, workflow_id: str) -> list[ApplicationEvidenceDB]:
    """The evidence rows of one workflow, if the scope may read them."""
    statement = (
        select(ApplicationEvidenceDB)
        .where(ApplicationEvidenceDB.workflow_id == workflow_id)
        .order_by(ApplicationEvidenceDB.id)
    )
    return list(db.execute(_owned(statement, ApplicationEvidenceDB, scope)).scalars())


# -- audit --------------------------------------------------------------------


def list_audit_events(
    db: Session,
    scope: UserScope,
    *,
    limit: int = 200,
) -> list[AuditEventDB]:
    """The audit rows this scope may read."""
    statement = (
        select(AuditEventDB).order_by(AuditEventDB.id.desc()).limit(max(1, min(limit, 1000)))
    )
    return list(db.execute(_owned(statement, AuditEventDB, scope)).scalars())
