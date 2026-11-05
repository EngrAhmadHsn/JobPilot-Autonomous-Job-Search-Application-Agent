"""Durable execution states and the transition matrix (WS-18).

The statuses are deliberately few and the transitions are deliberately
strict. A run's status is a **claim about durable work**, so an arbitrary
write to ``COMPLETED`` is not a cosmetic bug — it is the system telling an
operator that work finished when it did not. :func:`assert_transition` is
therefore the one gate every status change in :mod:`src.runs.queue` passes
through.

Two ideas separate this module from a plain enum:

- **A run is terminal for the worker, not for an administrator.** ``FAILED``
  and ``PARTIAL`` mean "the worker gave up"; an attributable recovery request
  may still put the run back in the queue. ``COMPLETED`` and ``CANCELLED`` are
  the only states nothing may leave.
- **``RECOVERABLE`` is derived, not requested.** It is what the lease reaper
  writes when a worker stopped heartbeating while it still owned outstanding
  work. An administrator resuming it is the explicit act the brief asks for.

Timestamps are **naive UTC**. SQLite stores a ``DateTime`` as text and drops
the offset, so an aware value would compare differently against the rows the
database itself wrote. :func:`utcnow` is the single source for "now".
"""

from __future__ import annotations

from datetime import UTC, datetime

__all__ = [
    "ACTIVE_RUN_STATUSES",
    "CLAIMABLE_RUN_STATUSES",
    "ERROR_PERMANENT",
    "ERROR_QUOTA",
    "ERROR_RETRYABLE",
    "EVENT_BATCH_COMPLETED",
    "EVENT_BATCH_STARTED",
    "EVENT_QUOTA_EXHAUSTED",
    "EVENT_RECONCILE_COMPLETED",
    "EVENT_RECONCILE_STARTED",
    "EVENT_RECOVERY_REQUESTED",
    "EVENT_RECOVERY_STARTED",
    "EVENT_RETRY_SCHEDULED",
    "EVENT_RUN_CANCELLED",
    "EVENT_RUN_COMPLETED",
    "EVENT_RUN_CREATED",
    "EVENT_RUN_FAILED",
    "EVENT_RUN_PAUSED",
    "EVENT_WORKER_CLAIMED",
    "EVENT_WORKER_INTERRUPTED",
    "RESUMABLE_RUN_STATUSES",
    "RUN_CANCELLED",
    "RUN_COMPLETED",
    "RUN_FAILED",
    "RUN_PARTIAL",
    "RUN_PAUSED",
    "RUN_QUEUED",
    "RUN_RECOVERABLE",
    "RUN_RETRY_WAIT",
    "RUN_RUNNING",
    "RUN_STATUSES",
    "RUN_TRANSITIONS",
    "TERMINAL_RUN_STATUSES",
    "WORK_CANCELLED",
    "WORK_COMPLETED",
    "WORK_FAILED",
    "WORK_QUEUED",
    "WORK_RETRY_WAIT",
    "WORK_RUNNING",
    "WORK_STATUSES",
    "WORK_TRANSITIONS",
    "IllegalTransition",
    "LeaseLost",
    "assert_transition",
    "assert_work_transition",
    "utcnow",
]

# -- run statuses ------------------------------------------------------------

RUN_QUEUED = "QUEUED"
RUN_RUNNING = "RUNNING"
RUN_PAUSED = "PAUSED"
RUN_RETRY_WAIT = "RETRY_WAIT"
RUN_RECOVERABLE = "RECOVERABLE"
RUN_COMPLETED = "COMPLETED"
RUN_PARTIAL = "PARTIAL"
RUN_FAILED = "FAILED"
RUN_CANCELLED = "CANCELLED"

RUN_STATUSES: frozenset[str] = frozenset(
    {
        RUN_QUEUED,
        RUN_RUNNING,
        RUN_PAUSED,
        RUN_RETRY_WAIT,
        RUN_RECOVERABLE,
        RUN_COMPLETED,
        RUN_PARTIAL,
        RUN_FAILED,
        RUN_CANCELLED,
    }
)

#: A run that has not finished: it holds the queue's capacity and is what
#: "pending runs" counts.
ACTIVE_RUN_STATUSES: frozenset[str] = frozenset(
    {RUN_QUEUED, RUN_RUNNING, RUN_RETRY_WAIT, RUN_RECOVERABLE}
)

#: A run whose work items the worker may claim. ``RECOVERABLE`` is
#: deliberately **excluded**: an interrupted run is resumed by an
#: attributable administrator action, not adopted silently by whichever
#: worker polls next. ``PAUSED`` is excluded for the same reason (a budget
#: stop must not spin).
CLAIMABLE_RUN_STATUSES: frozenset[str] = frozenset(
    {RUN_QUEUED, RUN_RUNNING, RUN_RETRY_WAIT}
)

#: A run an administrator may explicitly put back in the queue.
RESUMABLE_RUN_STATUSES: frozenset[str] = frozenset(
    {RUN_PAUSED, RUN_RECOVERABLE, RUN_RETRY_WAIT, RUN_FAILED, RUN_PARTIAL}
)

#: The two states nothing may leave. A completed run is an assertion about
#: durable work, and a cancelled run is an explicit human decision.
TERMINAL_RUN_STATUSES: frozenset[str] = frozenset({RUN_COMPLETED, RUN_CANCELLED})

#: The legal transitions. Every status write goes through this table.
RUN_TRANSITIONS: dict[str, frozenset[str]] = {
    RUN_QUEUED: frozenset(
        {RUN_RUNNING, RUN_PAUSED, RUN_RETRY_WAIT, RUN_RECOVERABLE, RUN_COMPLETED, RUN_CANCELLED}
    ),
    RUN_RUNNING: frozenset(
        {
            RUN_RUNNING,
            RUN_COMPLETED,
            RUN_PARTIAL,
            RUN_FAILED,
            RUN_PAUSED,
            RUN_RETRY_WAIT,
            RUN_RECOVERABLE,
            RUN_CANCELLED,
        }
    ),
    RUN_PAUSED: frozenset({RUN_QUEUED, RUN_CANCELLED}),
    RUN_RETRY_WAIT: frozenset(
        {
            RUN_QUEUED,
            RUN_RUNNING,
            RUN_PAUSED,
            RUN_RECOVERABLE,
            RUN_COMPLETED,
            RUN_PARTIAL,
            RUN_FAILED,
            RUN_CANCELLED,
        }
    ),
    # A recoverable run resumes only by explicit request; the worker does not
    # silently adopt it (the lease reaper requeues the *items*, and the
    # administrator's resume is the attributable act that moves the run).
    RUN_RECOVERABLE: frozenset({RUN_QUEUED, RUN_RUNNING, RUN_CANCELLED}),
    RUN_COMPLETED: frozenset(),
    # A partial run may be retried after its failed items are corrected.
    RUN_PARTIAL: frozenset({RUN_QUEUED}),
    RUN_FAILED: frozenset({RUN_QUEUED}),
    RUN_CANCELLED: frozenset(),
}

# -- work item statuses ------------------------------------------------------

WORK_QUEUED = "QUEUED"
WORK_RUNNING = "RUNNING"
WORK_RETRY_WAIT = "RETRY_WAIT"
WORK_COMPLETED = "COMPLETED"
WORK_FAILED = "FAILED"
WORK_CANCELLED = "CANCELLED"

WORK_STATUSES: frozenset[str] = frozenset(
    {WORK_QUEUED, WORK_RUNNING, WORK_RETRY_WAIT, WORK_COMPLETED, WORK_FAILED, WORK_CANCELLED}
)

WORK_TRANSITIONS: dict[str, frozenset[str]] = {
    WORK_QUEUED: frozenset({WORK_RUNNING, WORK_CANCELLED, WORK_FAILED}),
    WORK_RUNNING: frozenset({WORK_COMPLETED, WORK_FAILED, WORK_RETRY_WAIT, WORK_CANCELLED}),
    WORK_RETRY_WAIT: frozenset({WORK_QUEUED, WORK_RUNNING, WORK_FAILED, WORK_CANCELLED}),
    WORK_COMPLETED: frozenset(),
    WORK_FAILED: frozenset({WORK_QUEUED}),
    WORK_CANCELLED: frozenset(),
}

# -- failure categories ------------------------------------------------------

#: The provider / dependency is briefly unhealthy. Another attempt may work.
ERROR_RETRYABLE = "retryable"
#: The input or configuration is wrong. Another attempt cannot work.
ERROR_PERMANENT = "permanent"
#: The daily budget is spent. The work is valid but must wait for the reset.
ERROR_QUOTA = "quota"

# -- lifecycle events --------------------------------------------------------

EVENT_RUN_CREATED = "run.created"
EVENT_WORKER_CLAIMED = "worker.claimed"
EVENT_BATCH_STARTED = "batch.started"
EVENT_BATCH_COMPLETED = "batch.completed"
EVENT_RETRY_SCHEDULED = "retry.scheduled"
EVENT_QUOTA_EXHAUSTED = "quota.exhausted"
EVENT_WORKER_INTERRUPTED = "worker.interrupted"
EVENT_RECOVERY_REQUESTED = "recovery.requested"
EVENT_RECOVERY_STARTED = "recovery.started"
EVENT_RUN_PAUSED = "run.paused"
EVENT_RUN_COMPLETED = "run.completed"
EVENT_RUN_FAILED = "run.failed"
EVENT_RUN_CANCELLED = "run.cancelled"
EVENT_RECONCILE_STARTED = "reconcile.started"
EVENT_RECONCILE_COMPLETED = "reconcile.completed"


class IllegalTransition(RuntimeError):
    """A status change the backend refuses to make."""


class LeaseLost(RuntimeError):
    """A worker tried to commit work after its lease had been reclaimed.

    This is not a transient error to retry: the item now belongs to somebody
    else (or is queued again), and the stale worker must **not** write its
    result. The handler logs it and moves on.
    """


def utcnow() -> datetime:
    """The current time as a naive UTC datetime.

    Naive because SQLite stores ``DateTime`` as text and strips the offset:
    comparing an aware value against a stored naive one is the kind of
    bug that only appears in production, on the engine nobody tested.
    """
    return datetime.now(UTC).replace(tzinfo=None)


def _check(current: str, target: str, table: dict[str, frozenset[str]], kind: str) -> None:
    if current == target:
        return
    if current not in table:
        raise IllegalTransition(f"Unknown {kind} status: {current!r}")
    if target not in table[current]:
        raise IllegalTransition(
            f"Illegal {kind} transition {current} -> {target}. "
            f"Allowed from {current}: {', '.join(sorted(table[current])) or 'nothing'}."
        )


def assert_transition(current: str, target: str) -> None:
    """Refuse a run status change the state machine does not allow."""
    _check(current, target, RUN_TRANSITIONS, "run")


def assert_work_transition(current: str, target: str) -> None:
    """Refuse a work-item status change the state machine does not allow."""
    _check(current, target, WORK_TRANSITIONS, "work item")
