"""The audit trail, read by the account it belongs to (WS-14 · Phase C).

One endpoint: ``GET /api/audit`` returns the caller's own audit rows,
newest first.

**Why the read is scoped.** An audit row is user data like any other: it
records what happened to *that* account's resumes, applications and
submissions, and it names the principals involved. A shared audit view
would be a cross-tenant read of exactly the kind WS-14 is closing, so
the read goes through the scoped accessor and the caller sees their own
trail and nobody else's.

The platform's own audit view — the superuser scope — is the one
deliberate exception, and it is not exposed as a route: it is a scope
the platform's own tooling uses, not a thing a user can ask for.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from src.api.scope import UserScope, current_scope
from src.db import access
from src.db.session import get_db

router = APIRouter(prefix="/api/audit", tags=["audit"])


@router.get("")
def list_audit_events(
    db: Annotated[Session, Depends(get_db)],
    scope: Annotated[UserScope, Depends(current_scope)],
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> dict:
    """The caller's own audit rows, newest first.

    Args:
        db: The request-scoped database session.
        scope: The caller's access scope.
        limit: How many rows to return (at most 500).

    Returns:
        The rows, and how many there are.
    """
    rows = access.list_audit_events(db, scope, limit=limit)
    return {
        "events": [
            {
                "id": row.id,
                "recorded_at": row.recorded_at.isoformat() if row.recorded_at else None,
                "action": row.action,
                "actor": row.actor,
                "actor_kind": row.actor_kind,
                "actor_id": row.actor_id,
                "resource": row.resource,
                "outcome": row.outcome,
                "workflow_id": row.workflow_id,
                "metadata": dict(row.extra_metadata or {}),
            }
            for row in rows
        ],
        "count": len(rows),
    }
