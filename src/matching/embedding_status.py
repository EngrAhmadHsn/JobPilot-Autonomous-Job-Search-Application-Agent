"""Embedding status for the corpus (WS-20, reading the WS-18 queue).

The search used to infer "this listing has no vector" purely from its absence
in the similarity map, which collapsed three different situations into one
boolean: a listing whose embedding is simply *queued*, a listing whose
embedding *failed*, and the *whole store being down*. Because the old engine
then redistributed the semantic weight, a listing that had no embedding could
score *higher* than one that did.

This module answers the missing question — **what is this listing's embedding
state?** — from the durable queue WS-18 already maintains
(``job_work_items``). It creates no second queue and no duplicate state: it
reads the existing work items.

The three-way distinction the caller can then make:

- the store is unreachable → ``EMBEDDING_UNAVAILABLE`` for every listing;
- the store is up and a listing has a vector → a real measurement;
- the store is up and a listing has **no** vector → ``EMBEDDING_PENDING``
  (its work item is queued / running / retrying / failed, or it has no vector
  and no item yet).
"""

from __future__ import annotations

import logging
from collections.abc import Iterable

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from src.runs import state as run_state

logger = logging.getLogger(__name__)

WORK_TYPE_EMBED = "embed"

#: Work-item statuses that mean "the embedding is not done".
_PENDING_STATUSES = frozenset(
    {
        run_state.WORK_QUEUED,
        run_state.WORK_RUNNING,
        run_state.WORK_RETRY_WAIT,
        run_state.WORK_FAILED,
    }
)


def embedding_status_for_jobs(
    job_ids: Iterable[str],
    *,
    session: Session | None = None,
    session_factory: sessionmaker | None = None,
) -> dict[str, str]:
    """Embedding work-item status per job id (latest attempt wins).

    Returns a mapping of job id to the most recent ``work_type='embed'`` work
    item's status (one of :data:`src.runs.state.WORK_STATUSES`). A listing with
    no embed work item at all is simply absent from the mapping — which means
    "no vector and no queued work", still a pending state to the caller.

    Exactly one of ``session`` or ``session_factory`` must be given.
    """
    ids = list(dict.fromkeys(str(job_id) for job_id in job_ids))
    if not ids:
        return {}

    from src.db.runs import JobWorkItemDB

    def _query(db: Session) -> dict[str, str]:
        stmt = (
            select(
                JobWorkItemDB.job_id,
                JobWorkItemDB.status,
                JobWorkItemDB.created_at,
            )
            .where(
                JobWorkItemDB.job_id.in_(ids),
                JobWorkItemDB.work_type == WORK_TYPE_EMBED,
            )
            .order_by(JobWorkItemDB.created_at.asc())
        )
        result: dict[str, str] = {}
        for job_id, status, _created in db.execute(stmt):
            # Ascending order means the last write for a job id is the latest.
            result[job_id] = status
        return result

    if session is not None:
        return _query(session)
    if session_factory is None:
        from src.db.session import SessionLocal

        session_factory = SessionLocal
    with session_factory() as db:
        return _query(db)


def is_pending_status(status: str | None) -> bool:
    """Whether a work-item status means the embedding is not finished."""
    return status in _PENDING_STATUSES
