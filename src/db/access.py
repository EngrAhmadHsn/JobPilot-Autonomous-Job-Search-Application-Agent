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

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import Select, func, select, update
from sqlalchemy.orm import Session

from src.db.application_answers import ApplicationAnswerDB
from src.db.applications import ApplicationDB, ApplicationEventDB
from src.db.approval import ApprovalRequestDB
from src.db.audit import AuditEventDB
from src.db.byok import LlmCredentialDB
from src.db.eeo import CandidateEeoDB
from src.db.employer_answers import EmployerAnswerDB, LocalFillGrantDB
from src.db.evidence import ApplicationEvidenceDB
from src.db.jobs import JobDB
from src.db.matches import JobMatchDB
from src.db.profiles import CandidateProfileDB
from src.db.runs import JobRunDB, JobRunEventDB, JobWorkItemDB
from src.db.tailored import TailoredResumeDB
from src.db.users import LEGACY_OWNER_ID, UserDB

__all__ = [
    "LEGACY_SCOPE",
    "UserScope",
    "activate_llm_credential",
    "claim_legacy_rows",
    "count_applications",
    "count_distinct_owned",
    "count_jobs",
    "count_owned",
    "count_users",
    "create_llm_credential",
    "delete_llm_credential",
    "get_application",
    "get_application_by_approval",
    "get_approval",
    "get_llm_credential",
    "get_profile",
    "get_run",
    "get_tailored",
    "get_tailored_for_update",
    "group_owned",
    "list_application_answers",
    "list_applications",
    "list_applications_for_job",
    "list_audit_events",
    "list_llm_credentials",
    "list_profiles",
    "list_run_events",
    "list_runs",
    "list_tailored",
    "list_work_items",
    "touch_llm_credential",
    "update_llm_credential",
    "upsert_application_answers",
    "upsert_llm_credential",
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
    CandidateEeoDB,
    JobMatchDB,
    TailoredResumeDB,
    ApplicationDB,
    ApplicationEventDB,
    ApplicationEvidenceDB,
    ApprovalRequestDB,
    AuditEventDB,
    JobRunDB,
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


# -- EEO / voluntary self-identification (WS-20) ------------------------------


def get_eeo(db: Session, scope: UserScope, profile_id: str) -> object | None:
    """The EEO row of one profile if this scope may read it, else ``None``.

    The same ownership rule as every other user-scoped table: a foreign row is
    ``None`` (the caller answers 404), never "forbidden".
    """
    if not profile_id:
        return None
    from src.db.eeo import CandidateEeoDB

    statement = select(CandidateEeoDB).where(CandidateEeoDB.profile_id == profile_id)
    return db.execute(_owned(statement, CandidateEeoDB, scope)).scalar_one_or_none()


# -- job matches --------------------------------------------------------------


def list_job_matches(db: Session, scope: UserScope, profile_id: str) -> list[JobMatchDB]:
    """The match history of one profile, if the scope may read it."""
    statement = (
        select(JobMatchDB).where(JobMatchDB.profile_id == profile_id).order_by(JobMatchDB.id.desc())
    )
    return list(db.execute(_owned(statement, JobMatchDB, scope)).scalars())


def list_ranked_job_matches(
    db: Session, scope: UserScope, profile_id: str, *, limit: int = 25
) -> list[JobMatchDB]:
    """The most recent match of each job, best score first (WS-21).

    The Tailor picker offers *relevance*; the history accessor above offers
    the audit trail. Repeated searches insert a row per (profile, job), so
    this deduplicates to the newest row of each job with a window function
    (portable across SQLite ≥ 3.25 and PostgreSQL — no JSON column
    ordering, and no dialect-specific operators), drops rows with an
    unusable score safely, sorts by the persisted overall score descending
    with deterministic tie-breaks (newest record, then job id), and limits
    only **after** the deduplication and the sort.
    """
    from sqlalchemy import func

    numbered = (
        select(
            JobMatchDB.id.label("id"),
            func.row_number()
            .over(partition_by=JobMatchDB.job_id, order_by=JobMatchDB.id.desc())
            .label("row_rank"),
        )
        .where(JobMatchDB.profile_id == profile_id)
        .subquery()
    )
    statement = (
        select(JobMatchDB)
        .join(numbered, JobMatchDB.id == numbered.c.id)
        .where(numbered.c.row_rank == 1)
    )
    rows = list(db.execute(_owned(statement, JobMatchDB, scope)).scalars())

    def score_of(row: JobMatchDB) -> float | None:
        value = dict(row.scores or {}).get("overall_score")
        if value is None or isinstance(value, bool):
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    def sort_key(row: JobMatchDB) -> tuple[int, float, float, str]:
        score = score_of(row)
        created = row.created_at.timestamp() if row.created_at is not None else 0.0
        # Missing and malformed scores sort last; a tie goes to the newest
        # record, then to the job id, so the order is deterministic.
        return (
            0 if score is not None else 1,
            -(score if score is not None else 0.0),
            -created,
            row.job_id or "",
        )

    ranked = sorted(rows, key=sort_key)
    return ranked[: max(1, min(int(limit), 200))]


# -- tailored resumes ---------------------------------------------------------


def get_tailored(db: Session, scope: UserScope, tailoring_id: str) -> TailoredResumeDB | None:
    """The tailored resume *tailoring_id* if this scope may read it."""
    if not tailoring_id:
        return None
    statement = select(TailoredResumeDB).where(TailoredResumeDB.id == tailoring_id)
    return db.execute(_owned(statement, TailoredResumeDB, scope)).scalar_one_or_none()


def get_tailored_for_update(
    db: Session, scope: UserScope, tailoring_id: str
) -> TailoredResumeDB | None:
    """The tailored resume *tailoring_id* if this scope may **edit** it.

    A write is fenced harder than a read. The read accessor above grants the
    platform's superuser scope its cross-owner audit view; a write must not:
    an edit replaces the candidate's deliverable content, and nobody rewrites
    somebody else's résumé — the same rule as :func:`upsert_application_answers`
    (the check is on the owner column, never relaxed). A foreign row and a
    missing row are both ``None``, so the route answers one 404 and the API
    stays a non-oracle.
    """
    row = get_tailored(db, scope, tailoring_id)
    if row is None or row.owner_id != scope.user_id:
        return None
    return row


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


def _application_filters(
    status: str | None, statuses: Sequence[str] | None, profile_id: str | None
) -> list:
    """The WHERE clauses for the application list filters.

    Shared by the list and the count so the two can never disagree: a page
    whose items were filtered one way and whose total was filtered another
    is a paginator that lies.

    ``statuses`` is the multi-status form the board's grouped columns need
    (one column covers several lifecycle statuses). A set of one produces
    the same predicate as ``status``, so the single-status path is not a
    special case. When both are given, ``statuses`` wins — it is the more
    specific request, and the route never sends both.
    """
    clauses = []
    wanted = [value for value in (statuses or []) if value]
    if wanted:
        clauses.append(ApplicationDB.status.in_(wanted))
    elif status:
        clauses.append(ApplicationDB.status == status)
    if profile_id:
        clauses.append(ApplicationDB.profile_id == profile_id)
    return clauses


def list_applications(
    db: Session,
    scope: UserScope,
    *,
    status: str | None = None,
    statuses: Sequence[str] | None = None,
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
    for clause in _application_filters(status, statuses, profile_id):
        statement = statement.where(clause)
    statement = statement.limit(max(1, min(limit, 200))).offset(max(0, offset))
    return list(db.execute(_owned(statement, ApplicationDB, scope)).scalars())


def count_applications(
    db: Session,
    scope: UserScope,
    *,
    status: str | None = None,
    statuses: Sequence[str] | None = None,
    profile_id: str | None = None,
) -> int:
    """How many applications this scope may read, with the same filters.

    The count is scoped too. A total that counted other users' rows
    would leak the size of somebody else's activity, and a paginated
    list whose total disagrees with its items is a bug in its own right.
    Both sides call :func:`_application_filters`, so they cannot drift.
    """
    statement = select(func.count()).select_from(ApplicationDB)
    for clause in _application_filters(status, statuses, profile_id):
        statement = statement.where(clause)
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


def list_applications_for_job(
    db: Session,
    scope: UserScope,
    job_url: str,
    *,
    limit: int = 10,
) -> list[ApplicationDB]:
    """The applications this scope already has for one posting, newest first.

    WS-45: the prepare flow is the only way the console reaches the
    questions screen, and every prepare creates a **new** application — so
    the answers a human saved are attached to the application that existed
    *before* the prepare that needs them. The merge walks this list newest
    first and takes the newest answer per question.
    """
    if not job_url:
        return []
    statement = (
        select(ApplicationDB)
        .where(ApplicationDB.job_url == job_url)
        .order_by(ApplicationDB.created_at.desc())
        .limit(max(1, min(limit, 50)))
    )
    return list(db.execute(_owned(statement, ApplicationDB, scope)).scalars())


# -- the saved per-application answers (WS-45) --------------------------------


def list_application_answers(
    db: Session, scope: UserScope, application_id: str
) -> list[ApplicationAnswerDB]:
    """The saved answers of one application, if this scope may read it.

    The application is the authorization boundary: a foreign or missing
    application yields ``[]`` — the same answer, so a caller cannot tell a
    foreign id from a missing one. The answers themselves carry one more
    filter, and it is **never** relaxed: an answer is personal data, so
    even a superuser scope reads no more than its own rows (the same rule
    as :func:`get_llm_credential`).
    """
    if not application_id or get_application(db, scope, application_id) is None:
        return []
    statement = (
        select(ApplicationAnswerDB)
        .where(
            ApplicationAnswerDB.application_id == application_id,
            ApplicationAnswerDB.owner_id == scope.user_id,
        )
        .order_by(ApplicationAnswerDB.id)
    )
    return list(db.execute(statement).scalars())


def upsert_application_answers(
    db: Session,
    scope: UserScope,
    application_id: str,
    items: Sequence[dict],
) -> list[ApplicationAnswerDB] | None:
    """Insert or update the caller's answers for one application (caller commits).

    One row per ``(owner, application, question_key)``: a re-answered
    question updates its row in place and refreshes ``answered_at`` — it
    never creates a second one. The rows are stamped with the **scope's**
    owner id, and the application must be owned by the same principal: the
    check is on the owner column, so a superuser gets no cross-owner
    exception here either (the same rule as :func:`get_llm_credential` —
    nobody writes answers onto somebody else's application).

    Returns:
        The saved rows, in the order *items* gave them — or ``None`` when
        the application is missing or not owned by the caller, which the
        route answers with a 404 exactly like every other foreign resource.
    """
    if not application_id:
        return None
    application = get_application(db, scope, application_id)
    if application is None or application.owner_id != scope.user_id:
        return None

    from datetime import UTC, datetime

    now = datetime.now(UTC)
    saved: list[ApplicationAnswerDB] = []
    for item in items:
        question_key = str(item["question_key"])
        row = db.execute(
            select(ApplicationAnswerDB).where(
                ApplicationAnswerDB.owner_id == scope.user_id,
                ApplicationAnswerDB.application_id == application_id,
                ApplicationAnswerDB.question_key == question_key,
            )
        ).scalar_one_or_none()
        if row is None:
            row = ApplicationAnswerDB(
                owner_id=scope.user_id,
                application_id=application_id,
                question_key=question_key,
            )
            db.add(row)
        # A partial update (a re-answer that repeats only the key and the
        # value) preserves the stored label and category: the wording the
        # console displayed is not the caller's to erase by omission.
        if item.get("label") is not None:
            row.label = item["label"]
        if item.get("category") is not None:
            row.category = item["category"]
        row.answer_text = str(item["answer"])
        row.answered_at = now
        row.updated_at = now
        saved.append(row)
    db.flush()
    return saved


def list_employer_answers(
    db: Session, scope: UserScope, *, job_id: str | None = None, limit: int = 100, offset: int = 0
) -> list[EmployerAnswerDB]:
    """Account-private answers, including when the caller is an administrator."""
    statement = select(EmployerAnswerDB).where(EmployerAnswerDB.owner_id == scope.user_id)
    if job_id is not None:
        statement = statement.where(EmployerAnswerDB.job_id == job_id)
    return list(
        db.scalars(
            statement.order_by(EmployerAnswerDB.updated_at.desc(), EmployerAnswerDB.id)
            .offset(offset)
            .limit(limit)
        )
    )


def get_employer_answer(db: Session, scope: UserScope, answer_id: str) -> EmployerAnswerDB | None:
    return db.scalars(
        select(EmployerAnswerDB).where(
            EmployerAnswerDB.owner_id == scope.user_id, EmployerAnswerDB.id == answer_id
        )
    ).one_or_none()


def upsert_employer_answers(db: Session, scope: UserScope, job: JobDB, entries: list[dict]) -> None:
    """Stage writes to exactly these question revisions; the route owns the commit."""
    keys = [entry["question_key"] for entry in entries]
    current = {
        row.question_key: row
        for row in db.scalars(
            select(EmployerAnswerDB).where(
                EmployerAnswerDB.owner_id == scope.user_id,
                EmployerAnswerDB.job_id == job.id,
                EmployerAnswerDB.question_key.in_(keys),
            )
        )
    }
    now = datetime.now(UTC)
    for entry in entries:
        row = current.get(entry["question_key"])
        if row is not None:
            row.answer = entry["answer"]
            row.question = entry["question"]
            row.company_name = job.company
            row.job_title = job.title
            row.updated_at = now
        else:
            db.add(
                EmployerAnswerDB(
                    owner_id=scope.user_id,
                    job_id=job.id,
                    company_name=job.company,
                    job_title=job.title,
                    updated_at=now,
                    **entry,
                )
            )


def replace_local_fill_grant(
    db: Session, scope: UserScope, app_id: str, digest: str, expiry: datetime
) -> None:
    """A new explicit authorization replaces any older code for this review."""
    application = get_application(db, scope, app_id)
    if application is None or application.owner_id != scope.user_id:
        raise ValueError("Posting review not found")
    row = db.get(LocalFillGrantDB, app_id)
    if row is None:
        db.add(
            LocalFillGrantDB(
                application_id=app_id, owner_id=scope.user_id, code_digest=digest, expires_at=expiry
            )
        )
    elif row.owner_id == scope.user_id:
        row.code_digest, row.expires_at, row.used_at = digest, expiry, None
    else:
        raise ValueError("Posting review not found")


def consume_local_fill_grant(db: Session, digest: str, now: datetime) -> tuple[str, str] | None:
    """Redeem the bearer grant atomically, only while its owner is active."""
    already_claimed = db.execute(
        update(LocalFillGrantDB)
        .where(
            LocalFillGrantDB.code_digest == digest,
            LocalFillGrantDB.used_at.is_(None),
            LocalFillGrantDB.expires_at > now,
            LocalFillGrantDB.owner_id.in_(select(UserDB.id).where(UserDB.is_active.is_(True))),
        )
        .values(used_at=now)
        .returning(LocalFillGrantDB.owner_id, LocalFillGrantDB.application_id)
        .execution_options(synchronize_session=False)
    ).one_or_none()
    if already_claimed is None:
        return None
    return already_claimed.owner_id, already_claimed.application_id


def employer_answers_for_questions(
    db: Session, scope: UserScope, job_id: str, keys: list[str]
) -> dict[str, EmployerAnswerDB]:
    return {
        row.question_key: row
        for row in db.scalars(
            select(EmployerAnswerDB).where(
                EmployerAnswerDB.owner_id == scope.user_id,
                EmployerAnswerDB.job_id == job_id,
                EmployerAnswerDB.question_key.in_(keys),
            )
        )
    }


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


# -- durable execution (WS-18) ------------------------------------------------


def get_run(db: Session, scope: UserScope, run_id: str) -> JobRunDB | None:
    """The run *run_id* if this scope may see it, else ``None``.

    A run with no owner is a platform run (a scheduled refresh): a
    superuser may read it, an ordinary account may not. A foreign run and a
    missing run are both ``None``, so a route answers the same 404 for both.
    """
    if not run_id:
        return None
    statement = select(JobRunDB).where(JobRunDB.id == run_id)
    return db.execute(_owned(statement, JobRunDB, scope)).scalar_one_or_none()


def list_runs(
    db: Session,
    scope: UserScope,
    *,
    job_type: str | None = None,
    statuses: list[str] | tuple[str, ...] | None = None,
    limit: int = 50,
) -> list[JobRunDB]:
    """The runs this scope may read, newest first and paged."""
    statement = select(JobRunDB).order_by(JobRunDB.created_at.desc())
    if job_type:
        statement = statement.where(JobRunDB.job_type == job_type)
    if statuses:
        statement = statement.where(JobRunDB.status.in_(tuple(statuses)))
    statement = statement.limit(max(1, min(limit, 200)))
    return list(db.execute(_owned(statement, JobRunDB, scope)).scalars())


def list_work_items(db: Session, scope: UserScope, run_id: str) -> list[JobWorkItemDB]:
    """The work items of a run this scope may read.

    The items carry no owner of their own: they belong to a run, and the
    run's owner is the authorization boundary. The run is checked first, so
    a foreign run yields ``[]`` rather than another tenant's work.
    """
    if get_run(db, scope, run_id) is None:
        return []
    return list(
        db.execute(
            select(JobWorkItemDB)
            .where(JobWorkItemDB.run_id == run_id)
            .order_by(JobWorkItemDB.created_at.asc(), JobWorkItemDB.id.asc())
        ).scalars()
    )


def list_run_events(db: Session, scope: UserScope, run_id: str) -> list[JobRunEventDB]:
    """The lifecycle events of a run this scope may read."""
    if get_run(db, scope, run_id) is None:
        return []
    return list(
        db.execute(
            select(JobRunEventDB)
            .where(JobRunEventDB.run_id == run_id)
            .order_by(JobRunEventDB.id.desc())
        ).scalars()
    )

    # -- the caller's own model credentials (WS-22) -------------------------------


#: The ``created_at`` a row may be missing. Rows written before the timestamps
#: existed read back as ``NULL`` (the column is nullable in the migration that
#: added it), and ``NULL`` sorts differently by default on SQLite and
#: PostgreSQL. The order therefore asks for ``NULLS FIRST`` explicitly, which
#: both dialects accept, rather than substituting a sentinel instant.
def _credential_order():
    """The order the console shows, and the order that answers "who is next".

    The connection in use first (highest activation rank), then the ones that
    would take over if it were removed — oldest first, so the order is stable
    across calls and the same on every deployment.
    """
    return (
        LlmCredentialDB.activation_rank.desc(),
        LlmCredentialDB.created_at.asc().nulls_first(),
        LlmCredentialDB.id.asc(),
    )


def list_llm_credentials(db: Session, scope: UserScope) -> list[LlmCredentialDB]:
    """Every connection this scope owns, the one in use first.

    **A superuser scope reads no more than an ordinary one here.** The
    platform's cross-owner view is a legitimate exception for audit rows and
    an illegitimate one for a credential: it is somebody's private key. The
    filter is therefore on the scope's own id, never relaxed.
    """
    if not scope.user_id:
        return []
    statement = (
        select(LlmCredentialDB)
        .where(LlmCredentialDB.owner_id == scope.user_id)
        .order_by(*_credential_order())
    )
    return list(db.execute(statement).scalars())


def get_llm_credential(
    db: Session, scope: UserScope, credential_id: str | None = None
) -> LlmCredentialDB | None:
    """One of the caller's stored connections.

    Without *credential_id*: the connection in use (``None`` when the caller
    has none). With one: that connection, **only if the caller owns it** — a
    row that belongs to somebody else reads as absent, so the routes answer
    404 and the API never becomes an existence oracle.
    """
    if not scope.user_id:
        return None
    if credential_id is None:
        rows = list_llm_credentials(db, scope)
        return rows[0] if rows else None
    statement = select(LlmCredentialDB).where(
        LlmCredentialDB.owner_id == scope.user_id,
        LlmCredentialDB.id == credential_id,
    )
    return db.execute(statement).scalar_one_or_none()


def create_llm_credential(
    db: Session,
    scope: UserScope,
    *,
    provider: str,
    model: str,
    base_url: str | None,
    encrypted_key: str,
    hint: str,
) -> LlmCredentialDB:
    """Add a connection for the caller (the caller commits).

    The rank is 0, which is also every existing row's rank: a new connection
    therefore does **not** become the one in use. An older row wins the tie
    on ``created_at``, so adding a second provider leaves the first in use
    until the owner says otherwise.
    """
    row = LlmCredentialDB(
        owner_id=scope.user_id,
        provider=provider,
        model=model,
        base_url=base_url,
        encrypted_key=encrypted_key,
        hint=hint,
        activation_rank=0,
    )
    db.add(row)
    db.flush()
    return row


def update_llm_credential(
    db: Session,
    scope: UserScope,
    credential_id: str,
    *,
    provider: str,
    model: str,
    base_url: str | None,
    encrypted_key: str | None,
    hint: str | None,
) -> LlmCredentialDB | None:
    """Edit one of the caller's connections; ``None`` when there is no such row.

    ``encrypted_key`` and ``hint`` are ``None`` to **keep the stored key** —
    editing a model or a display name must not require re-entering a secret
    the user may not have to hand. The service decides when a new key is
    required and passes it here.
    """
    row = get_llm_credential(db, scope, credential_id)
    if row is None:
        return None
    row.provider = provider
    row.model = model
    row.base_url = base_url
    if encrypted_key is not None:
        row.encrypted_key = encrypted_key
    if hint is not None:
        row.hint = hint
    db.flush()
    return row


def activate_llm_credential(
    db: Session, scope: UserScope, credential_id: str
) -> LlmCredentialDB | None:
    """Put one of the caller's connections in use; ``None`` when it is not theirs.

    Rank is raised above the owner's current maximum rather than being a
    boolean flag: "in use" is then a single value no two writers can
    disagree about, and a rank can keep climbing without a reset step.
    """
    row = get_llm_credential(db, scope, credential_id)
    if row is None:
        return None
    current_max = db.execute(
        select(func.max(LlmCredentialDB.activation_rank)).where(
            LlmCredentialDB.owner_id == scope.user_id
        )
    ).scalar()
    row.activation_rank = (current_max or 0) + 1
    db.flush()
    return row


def upsert_llm_credential(
    db: Session,
    scope: UserScope,
    *,
    provider: str,
    model: str,
    base_url: str | None,
    encrypted_key: str,
    hint: str,
) -> LlmCredentialDB:
    """Insert or **replace the connection in use** (the caller commits).

    The pre-multi-connection contract, kept for the ``PUT`` route: there is
    one credential, and registering another replaces it. With several
    connections the same call edits the one in use, or creates the first one
    when the account has none — it never adds a second.
    """
    row = get_llm_credential(db, scope)
    if row is None:
        return create_llm_credential(
            db,
            scope,
            provider=provider,
            model=model,
            base_url=base_url,
            encrypted_key=encrypted_key,
            hint=hint,
        )
    row.provider = provider
    row.model = model
    row.base_url = base_url
    row.encrypted_key = encrypted_key
    row.hint = hint
    db.flush()
    return row


def delete_llm_credential(db: Session, scope: UserScope, credential_id: str | None = None) -> bool:
    """Delete one of the caller's connections; True when it was there.

    With no *credential_id* the connection **in use** is the one removed —
    the pre-multi-connection meaning of the call. Removing it promotes
    nothing by hand: the next row in :func:`list_llm_credentials` order
    already has the highest remaining rank, so the fallback is the same
    answer the console displays.
    """
    row = get_llm_credential(db, scope, credential_id)
    if row is None:
        return False
    db.delete(row)
    db.flush()
    return True


def touch_llm_credential(db: Session, scope: UserScope, credential_id: str | None = None) -> None:
    """Record that a connection was just used (``last_used_at``).

    Without an id it stamps the connection in use; with one it stamps exactly
    that connection, so exercising an inactive provider does not make it look
    like the one that answered a real call.
    """
    row = get_llm_credential(db, scope, credential_id)
    if row is None:
        return
    row.last_used_at = datetime.now(UTC)
    db.flush()


# -- aggregates (the platform view) -------------------------------------------


def count_owned(db: Session, scope: UserScope, model: type) -> int:
    """Count the rows of an owner-scoped table this scope may read.

    The scope does the filtering, exactly as it does for a row-fetching
    accessor: an ordinary scope counts its own rows, and a superuser scope
    counts every row. The count never bypasses the owner filter, so a route
    cannot use it to learn about another tenant's data.
    """
    statement = select(func.count()).select_from(model)
    return int(db.execute(_owned(statement, model, scope)).scalar_one())


def count_distinct_owned(db: Session, scope: UserScope, model: type, column) -> int:
    """Count the distinct values of *column* this scope may read."""
    statement = select(func.count(func.distinct(column))).select_from(model)
    return int(db.execute(_owned(statement, model, scope)).scalar_one())


def group_owned(db: Session, scope: UserScope, model: type, column) -> dict[str, int]:
    """Count rows of an owner-scoped table grouped by *column*."""
    statement = select(column, func.count()).select_from(model).group_by(column)
    rows = db.execute(_owned(statement, model, scope)).all()
    return {str(key): int(count) for key, count in rows if key is not None}


def count_jobs(db: Session) -> int:
    """Count the shared job corpus.

    ``jobs`` is the one table that is deliberately **not** owner-scoped: it
    holds public board data, shared by every account. It is counted here so
    the route does not query a table directly (the pattern the isolation
    matrix forbids), and it takes no scope because there is nothing to
    scope it by.
    """
    return int(db.execute(select(func.count()).select_from(JobDB)).scalar_one())


def count_users(
    db: Session,
    *,
    active: bool | None = None,
    superuser: bool | None = None,
) -> int:
    """Count platform accounts, optionally filtered by a flag.

    Accounts are the platform's own rows, not a tenant's data: they are the
    same for every caller, which is exactly why only a superuser route
    should ask for this count.
    """
    statement = select(func.count()).select_from(UserDB)
    if active is not None:
        statement = statement.where(UserDB.is_active.is_(active))
    if superuser is not None:
        statement = statement.where(UserDB.is_superuser.is_(superuser))
    return int(db.execute(statement).scalar_one())
