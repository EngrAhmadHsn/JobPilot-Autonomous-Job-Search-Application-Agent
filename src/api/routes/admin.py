"""The platform overview, read by a platform administrator (WS-17).

One endpoint: ``GET /api/admin/overview`` returns platform-wide aggregates —
how many accounts exist, how the applications are distributed across their
statuses, how the audit trail splits by outcome and by actor, and how large
the shared job corpus is.

**Why this is a superuser route, and why that is the whole control.**
WS-14 makes every other read tenant-scoped: a caller sees their own rows and
nothing else, and :mod:`src.db.access` is the only way a route reaches a
user-scoped table. This route is the one deliberate exception — the
platform's own view across owners — and it is safe for exactly one reason:
the scope it queries with is built from the **authenticated principal's**
``is_superuser`` flag, and a principal that is not a superuser is refused
with a 403 **before any query runs**. There is no header, query parameter
or body field that can widen the scope (WS-14 · R2), so there is no way to
ask for this view without the flag on the account.

The aggregates go through :mod:`src.db.access`, not through direct queries,
for the same reason every other route does: the isolation matrix greps the
route sources and fails if a route queries an owner-scoped table directly,
which is what keeps this exception from spreading.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from src.api.scope import UserScope, current_scope
from src.db import access
from src.db.applications import ApplicationDB
from src.db.audit import AuditEventDB
from src.db.session import get_db

router = APIRouter(prefix="/api/admin", tags=["admin"])


def require_superuser(
    scope: Annotated[UserScope, Depends(current_scope)],
) -> UserScope:
    """Refuse anyone who is not a platform administrator.

    It depends on :func:`src.api.scope.current_scope`, so a request with no
    credential is refused with a 401 before this runs, and the answer comes
    from the session's own ``is_superuser`` flag — never from the request.
    """
    if not scope.is_superuser:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Administration is available to platform administrators only.",
        )
    return scope


@router.get("/overview")
def read_overview(
    db: Annotated[Session, Depends(get_db)],
    scope: Annotated[UserScope, Depends(require_superuser)],
) -> dict:
    """Platform-wide counts, for the administration screen.

    Every figure is a live count over the platform's own tables. Nothing is
    cached, sampled or estimated: an administrator looking at this screen is
    looking at the database.
    """
    return {
        "accounts": {
            "total": access.count_users(db),
            "active": access.count_users(db, active=True),
            "superusers": access.count_users(db, superuser=True),
        },
        "applications": {
            "total": access.count_owned(db, scope, ApplicationDB),
            "by_status": access.group_owned(db, scope, ApplicationDB, ApplicationDB.status),
        },
        "workflows": {
            "total": access.count_distinct_owned(
                db, scope, ApplicationDB, ApplicationDB.workflow_id
            ),
        },
        "audit": {
            "total": access.count_owned(db, scope, AuditEventDB),
            "by_outcome": access.group_owned(db, scope, AuditEventDB, AuditEventDB.outcome),
            "by_actor_kind": access.group_owned(db, scope, AuditEventDB, AuditEventDB.actor_kind),
        },
        "corpus": {"jobs": access.count_jobs(db)},
        "generated_at": datetime.now(UTC).isoformat(),
    }
