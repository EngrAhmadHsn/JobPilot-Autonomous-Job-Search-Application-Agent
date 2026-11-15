"""The supervised background worker (WS-18).

One process, one loop, one job: claim durable work and execute it. The API
never runs a refresh or an embedding inside a request any more, so a browser
that closes, an API process that restarts, or a second request cannot affect
accepted work.

The loop is deliberately boring:

1. register (once) and heartbeat;
2. reap expired leases (so a crashed sibling's work returns to the queue);
3. claim a bounded batch atomically;
4. execute it — embeddings as a batch, refresh/reconcile one at a time;
5. checkpoint and settle, conditioned on the lease token.

A stop signal finishes the **current** batch and then exits. A hard kill
leaves the lease behind, which is exactly what the reaper is for.

Run it with ``python scripts/run_worker.py``. The API does not start it: a
deployment supervises it separately (systemd, a container, a Windows
service), which is what "a dedicated worker process" means.
"""

from __future__ import annotations

import logging
import os
import signal
import socket
import threading
import time
import uuid
from collections.abc import Callable, Sequence
from typing import TYPE_CHECKING, Any

from sqlalchemy.orm import Session, sessionmaker

from src.db.runs import JobRunDB
from src.runs import queue
from src.runs.embedding import (
    EMBED_WORK_TYPE,
    RECONCILE_WORK_TYPE,
    SUBMISSION_WORK_TYPE,
    _classify,
    _retry_outcome,
    process_embedding_items,
    run_reconcile,
)
from src.runs.state import (
    ERROR_PERMANENT,
    WORK_COMPLETED,
    WORK_FAILED,
    WORKER_STOPPING,
    utcnow,
)

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from src.applications.contracts import ApplicationResult
    from src.db.approval import ApprovalRequestDB

__all__ = ["Worker", "default_worker_id", "main"]

#: The refresh work type. (``SUBMISSION_WORK_TYPE``, WS-32, is imported from
#: ``src.runs.embedding`` instead of being redeclared here: the enqueue helper,
#: the dispatch below and the queue's item identity all match on that string,
#: and a second literal would be a second truth. ``REFRESH_WORK_TYPE`` predates
#: that rule and stays where the dispatch reads it.)
REFRESH_WORK_TYPE = "refresh"

#: How often the reaper runs, even when the queue is busy.
_REAP_INTERVAL_SECONDS = 5.0


def default_worker_id() -> str:
    """A readable, unique id for this worker process."""
    from src.config.settings import get_settings

    configured = get_settings().worker_id
    if configured:
        return configured
    return f"{socket.gethostname()}-{os.getpid()}-{uuid.uuid4().hex[:6]}"


def _submission_attempt(metadata: dict[str, Any] | None) -> dict[str, Any] | None:
    """The recorded attempt of a submission run, when there is one.

    WS-32 writes ``{"submission": {"attempt_started_at": ..., "approval_id":
    ..., "workflow_id": ...}}`` into the run's ``extra_metadata`` **before** the
    adapter is reached. The record survives a failure and a success (a success
    extends it with the outcome summary), so this helper answers "has an attempt
    ever been started for this run?" — which is only half the question the guard
    asks.

    The other half is on the approval row, and it is asked **first**: a row with
    a recorded outcome is never read as "outcome unknown". So this mapping being
    present alongside a committed result is not a false positive — the guard
    reaches case 3 before it reaches case 2.

    Returns ``None`` when no attempt was ever recorded.
    """
    if not metadata:
        return None
    submission = metadata.get("submission")
    if not isinstance(submission, dict):
        return None
    if not submission.get("attempt_started_at"):
        return None
    return submission


def _submission_summary(result: Any) -> dict[str, Any]:
    """The operator-facing summary of one submission, for the run's metadata.

    Deliberately small: the status, whether it succeeded, and the evidence's
    URL — no candidate field values, no resume contents. The run row is a
    progress record an operator reads in the console, and the full result
    (which does carry the evidence) is on the approval row where it belongs.

    The attempt marker is **kept** alongside the summary rather than replaced by
    it: ``attempt_started_at`` is the record that this attempt ran, and an
    operator reading the run after a failure wants to see when it began. It is
    also what makes the guard's case 3 distinguishable in the audit trail
    rather than only in the code.
    """
    evidence = getattr(result, "evidence", None)
    return {
        "status": getattr(result, "status", "unknown"),
        "success": bool(getattr(result, "success", False)),
        "message": getattr(result, "message", ""),
        "evidence_url": getattr(evidence, "url", None) if evidence is not None else None,
    }


class Worker:
    """The background execution loop.

    Args:
        worker_id: A stable name, or ``None`` to generate one.
        session_factory: The database sessionmaker (tests inject a tmp DB).
        poll_interval: Seconds to sleep when the queue is empty.
        lease_seconds: How long a claim is valid.
        batch_size: Work items claimed per iteration (the checkpoint
            granularity).
        store_factory: Vector-store override (tests inject a fake).
        embedding_fn: Embedding override (tests inject a fake).
        sources: Job-source override for the refresh handler.
        sleep: The sleep seam, so a test never waits.
        now: The clock seam.
    """

    def __init__(
        self,
        *,
        worker_id: str | None = None,
        session_factory: sessionmaker | None = None,
        poll_interval: float | None = None,
        lease_seconds: float | None = None,
        batch_size: int | None = None,
        store_factory: Callable[[], Any] | None = None,
        embedding_fn: Any = None,
        sources: dict | None = None,
        sleep: Callable[[float], None] = time.sleep,
        now: Callable[[], Any] = utcnow,
    ) -> None:
        from src.config.settings import get_settings

        settings = get_settings()
        self.worker_id = worker_id or default_worker_id()
        self._session_factory = session_factory
        self._poll_interval = (
            settings.worker_poll_interval_seconds if poll_interval is None else poll_interval
        )
        self._lease_seconds = (
            settings.worker_lease_seconds if lease_seconds is None else lease_seconds
        )
        self._batch_size = settings.worker_batch_size if batch_size is None else batch_size
        self._user_store_factory = store_factory
        self._embedding_fn = embedding_fn
        self._sources = sources
        self._sleep = sleep
        self._now = now
        self._stop = threading.Event()
        self._store: Any = None
        self._registered = False
        self._last_reap = 0.0
        self._processed_since_heartbeat = 0
        self._failed_since_heartbeat = 0

    # -- lifecycle ----------------------------------------------------------

    def request_stop(self) -> None:
        """Ask the loop to stop after the current batch."""
        self._stop.set()

    @property
    def stopping(self) -> bool:
        return self._stop.is_set()

    def register(self) -> None:
        if self._registered:
            return
        from src.db.session import SessionLocal

        factory = self._session_factory or SessionLocal
        with factory() as session:
            queue.register_worker(session, worker_id=self.worker_id)
        self._registered = True
        logger.info("Worker %s registered", self.worker_id)

    def shutdown(self, status: str = "stopped") -> None:
        from src.db.session import SessionLocal

        factory = self._session_factory or SessionLocal
        try:
            with factory() as session:
                queue.mark_worker_stopped(session, worker_id=self.worker_id, status=status)
        except Exception:
            logger.exception("Marking worker %s stopped failed", self.worker_id)
        logger.info("Worker %s stopped", self.worker_id)

    # -- the loop -----------------------------------------------------------

    def run_forever(self) -> None:
        self.register()
        try:
            while not self._stop.is_set():
                processed = self.run_once()
                if not processed and not self._stop.is_set():
                    self._sleep(self._poll_interval)
        finally:
            self.shutdown()

    def run_once(self) -> int:
        """One iteration: reap, claim, execute. Returns the item count."""
        if not self._registered:
            self.register()
        self._heartbeat()

        now = self._now()
        if (
            now.timestamp() if hasattr(now, "timestamp") else 0.0
        ) - self._last_reap >= _REAP_INTERVAL_SECONDS:
            try:
                queue.reap_expired_leases(session_factory=self._session_factory, now=now)
            except Exception:
                logger.exception("Lease reaper failed")
            self._last_reap = now.timestamp() if hasattr(now, "timestamp") else 0.0

        items = queue.claim_work_items(
            worker_id=self.worker_id,
            limit=self._batch_size,
            lease_seconds=self._lease_seconds,
            session_factory=self._session_factory,
            now=now,
        )
        if not items:
            return 0

        self._execute(items)
        self._heartbeat()
        return len(items)

    def _heartbeat(self) -> None:
        from src.db.session import SessionLocal

        factory = self._session_factory or SessionLocal
        try:
            with factory() as session:
                queue.heartbeat_worker(
                    session,
                    worker_id=self.worker_id,
                    processed_items=self._processed_since_heartbeat,
                    failed_items=self._failed_since_heartbeat,
                    now=self._now(),
                )
                # The stop request is cooperative and lives in the heartbeat
                # row, so an operator who started this worker from anywhere —
                # the console, a shell, a service manager — can ask it to stop
                # without the caller holding a handle on the process.
                status = queue.read_worker_status(session, worker_id=self.worker_id)
            self._processed_since_heartbeat = 0
            self._failed_since_heartbeat = 0
            if status == WORKER_STOPPING and not self._stop.is_set():
                logger.info(
                    "Worker %s was asked to stop; finishing the current batch", self.worker_id
                )
                self.request_stop()
        except Exception:
            logger.exception("Worker heartbeat failed")

    # -- execution ----------------------------------------------------------

    def _renew_batch(self, run_id: str, items: Sequence[queue.ClaimedWork]) -> None:
        """Keep a batch's lease — and this worker's heartbeat — alive mid-work.

        Called from inside the embedding loop, every few documents. Both
        halves matter and they are one call for a reason: the lease is what
        stops the reaper from giving the batch to another worker, and the
        heartbeat is what stops the console from reporting "no worker is
        running" (and offering to start a *second* local model) while this one
        is nine minutes into a batch. A stop request is picked up here too, so
        an operator's stop lands between sub-batches instead of after the run.
        """
        from src.db.session import SessionLocal

        factory = self._session_factory or SessionLocal
        try:
            queue.renew_lease(
                run_id=run_id,
                leases={item.id: item.lease_token for item in items},
                lease_seconds=self._lease_seconds,
                session_factory=factory,
                now=self._now(),
            )
        except queue.LeaseLost:
            raise
        except Exception:
            # A missed renewal is not worth abandoning a batch that is still
            # producing vectors: the next call tries again, and if the lease
            # really is gone, the settle refuses the result anyway.
            logger.exception("Renewing the lease on run %s failed", run_id)
        self._heartbeat()

    def _execute(self, items: Sequence[queue.ClaimedWork]) -> None:
        embed_items = [item for item in items if item.work_type == EMBED_WORK_TYPE]
        run_items = [item for item in items if item.work_type != EMBED_WORK_TYPE]

        groups: dict[str, list[queue.ClaimedWork]] = {}
        for item in embed_items:
            groups.setdefault(item.run_id, []).append(item)
        for run_id, group in groups.items():
            self._execute_embedding(run_id, group)

        for item in run_items:
            self._execute_run_item(item)

    def _embedding_store(self):
        if self._store is not None:
            return self._store
        if self._user_store_factory is not None:
            self._store = self._user_store_factory()
            return self._store
        if self._embedding_fn is None:
            from src.llm.embeddings import build_embedding_fn

            self._embedding_fn = build_embedding_fn()
        from src.rag.chroma_store import ChromaVectorStore

        self._store = ChromaVectorStore(embedding_fn=self._embedding_fn)
        return self._store

    def _execute_embedding(self, run_id: str, items: list[queue.ClaimedWork]) -> None:
        def renew(_embedded: int) -> None:
            self._renew_batch(run_id, items)

        try:
            store = self._embedding_store()
            result = process_embedding_items(
                items,
                run_id=run_id,
                worker_id=self.worker_id,
                store=store,
                session_factory=self._session_factory,
                now=self._now(),
                on_progress=renew,
            )
        except queue.LeaseLost:
            logger.warning(
                "Worker %s lost the lease on run %s; its batch was discarded",
                self.worker_id,
                run_id,
            )
            return
        except Exception:
            logger.exception("Embedding batch for run %s failed unexpectedly", run_id)
            self._settle_failure(
                items,
                error="The embedding batch failed unexpectedly.",
                run_id=run_id,
            )
            return
        self._processed_since_heartbeat += result.completed + result.skipped
        self._failed_since_heartbeat += result.failed

    def _execute_run_item(self, item: queue.ClaimedWork) -> None:
        try:
            if item.work_type == REFRESH_WORK_TYPE:
                self._execute_refresh(item)
            elif item.work_type == RECONCILE_WORK_TYPE:
                self._execute_reconcile(item)
            elif item.work_type == SUBMISSION_WORK_TYPE:
                self._execute_submission(item)
            else:
                queue.settle_work_items(
                    run_id=item.run_id,
                    outcomes=[
                        queue.ItemOutcome(
                            item_id=item.id,
                            lease_token=item.lease_token,
                            status=WORK_FAILED,
                            error=f"Unknown work type {item.work_type!r}.",
                            error_kind=ERROR_PERMANENT,
                        )
                    ],
                    worker_id=self.worker_id,
                    session_factory=self._session_factory,
                    now=self._now(),
                )
                self._failed_since_heartbeat += 1
        except queue.LeaseLost:
            logger.warning(
                "Worker %s lost the lease on item %s; its result was discarded",
                self.worker_id,
                item.id,
            )
        except Exception as exc:  # noqa: BLE001 - classified below
            retryable, _kind = _classify(exc)
            self._settle_failure(item, error=f"{type(exc).__name__}: {exc}", retryable=retryable)

    def _execute_refresh(self, item: queue.ClaimedWork) -> None:
        run = self._load_run(item.run_id)
        if run is None:
            self._settle_failure(item, error="The run row no longer exists.")
            return
        from src.graph.job_executor import fetch_and_persist

        stage = fetch_and_persist(
            sources=self._sources,
            store_factory=(
                self._user_store_factory
                if self._user_store_factory is not None
                else self._embedding_store
            ),
            embedding_fn=self._embedding_fn,
            session_factory=self._session_factory,
            owner_id=run.owner_id,
            parent_run_id=run.id,
            raise_on_persist_error=True,
        )
        self._update_run_metadata(
            run.id,
            {
                "refresh": {
                    "found": stage.stats.found,
                    "deduped": stage.stats.deduped,
                    "persisted": stage.stats.persisted,
                    "screened_out": stage.stats.screened_out,
                    "admission_capped": stage.stats.admission_capped,
                    "source_errors": stage.source_errors,
                    "embedding_run_id": stage.run_id,
                    "degraded": stage.degraded,
                    "correlation_id": stage.correlation_id,
                }
            },
        )
        queue.settle_work_items(
            run_id=run.id,
            outcomes=[
                queue.ItemOutcome(
                    item_id=item.id,
                    lease_token=item.lease_token,
                    status=WORK_COMPLETED,
                )
            ],
            worker_id=self.worker_id,
            session_factory=self._session_factory,
            event="refresh.completed",
            message=(
                f"Refresh fetched {stage.stats.found}, persisted "
                f"{stage.stats.persisted}; embedding run {stage.run_id or 'not needed'}"
            ),
            metadata={
                "persisted": stage.stats.persisted,
                "embedding_run_id": stage.run_id,
                "failed_sources": sorted(stage.source_errors),
            },
            now=self._now(),
        )
        self._processed_since_heartbeat += 1

    def _execute_reconcile(self, item: queue.ClaimedWork) -> None:
        run = self._load_run(item.run_id)
        if run is None:
            self._settle_failure(item, error="The run row no longer exists.")
            return
        report = run_reconcile(
            correlation_id=run.correlation_id,
            owner_id=run.owner_id,
            session_factory=self._session_factory,
            store=self._embedding_store(),
            reconcile_run_id=run.id,
        )
        self._update_run_metadata(run.id, {"reconcile": report.as_dict()})
        queue.settle_work_items(
            run_id=run.id,
            outcomes=[
                queue.ItemOutcome(
                    item_id=item.id,
                    lease_token=item.lease_token,
                    status=WORK_COMPLETED,
                )
            ],
            worker_id=self.worker_id,
            session_factory=self._session_factory,
            event="reconcile.completed",
            message=(
                f"Reconciliation: {report.missing} missing, "
                f"{report.orphaned} orphaned, {report.planned} queued"
            ),
            metadata=report.as_dict(),
            now=self._now(),
        )
        self._processed_since_heartbeat += 1

    def _execute_submission(self, item: queue.ClaimedWork) -> None:
        """Execute one approved application — the same call the route used to make.

        WS-32. The route now only *accepts* the work; this is where the payload
        is restored, the adapter is resolved and ``execute_approved`` runs. The
        call is unchanged, so everything the graph enforced inside the request
        (the submit capability gate, the payload contract check, the form walk,
        the verification, the WS-07 tracking writes) still applies — it just
        applies in the worker, where a crash is survivable.

        **At-most-once, and the guards are durable records.** The queue hands
        out at-least-once delivery: a lease can expire mid-run and the item can
        be claimed again — by the reaper, or by an administrator's resume. For
        an embedding that is harmless, because the work is idempotent. For an
        application submission it is not: applying twice is a real harm to a
        real candidate, not a duplicated batch.

        The guarantee therefore is **not** "a submission is never attempted
        twice", which no record written around the attempt can promise: there
        is always a moment between the board accepting the application and the
        outcome being committed, and a process can die in it. The guarantee is:

        - **A recorded outcome is never submitted again.** One row says what
          happened, and it outlives the process.
        - **An attempt whose outcome was never recorded is escalated to a
          human**, never re-sent. The system cannot know whether the board
          accepted it, so it stops and says so.

        Three cases, and they must not be conflated — the difference is what the
        durable records say, not what the lease says:

        1. **No attempt marker and no outcome** — nothing was ever started (or
           the process died before the marker was committed, which is the same
           thing: the marker is written *before* the adapter is reached). The
           retry **runs**. Refusing here would leave an approved application
           that never gets applied, which is its own failure.
        2. **An attempt marker with no recorded outcome** — the previous
           attempt reached the adapter and died before the outcome was durable.
           The board may or may not hold the application. The retry **refuses
           and escalates**: the item settles with ``submission.uncertain``, and
           the row is left ``APPROVED`` — decided, outcome unknown, which is
           the truth. It is deliberately *not* written ``FAILED`` (that would
           assert the application was not sent, which nobody knows) and *not*
           ``EXECUTED`` (nothing was confirmed).
        3. **A recorded outcome** (``EXECUTED``/``FAILED``, or a ``result``) —
           the application was submitted and the result is on the row. The
           retry **refuses**; there is nothing left to do.

        The lease says who may write; these records say what already happened,
        and only they survive a crash.
        """
        run = self._load_run(item.run_id)
        if run is None:
            self._settle_failure(item, error="The run row no longer exists.")
            return

        metadata = dict(run.extra_metadata or {})
        # The approval id is the work item's job_id, and it is also on the run
        # metadata; either is authoritative. The item is read first because it
        # is the thing this worker actually claimed.
        approval_id = item.job_id or str(metadata.get("approval_id") or "")
        workflow_id = str(metadata.get("workflow_id") or run.correlation_id or "")
        if not approval_id:
            self._settle_failure(
                item,
                error="The submission work item carries no approval id.",
                retryable=False,
            )
            return

        from src.db.approval import ApprovalRequestDB, ApprovalStatus
        from src.db.session import SessionLocal

        factory = self._session_factory or SessionLocal
        # The worker opens **its own** session. It must not take a
        # request-scoped one: there is no request, the work outlives any that
        # existed, and the tracking writes ``execute_approved`` performs belong
        # to this run, not to whoever approved it.
        with factory() as session:
            row = session.get(ApprovalRequestDB, approval_id)
            if row is None:
                # The approval the run names is gone. There is nothing to
                # submit and nothing to submit it *for*, so the item is failed
                # permanently — a retry would look for the same missing row.
                message = (
                    f"The approval {approval_id!r} named by run {run.id} no longer exists; "
                    "nothing was submitted."
                )
                logger.error("Submission refused: %s", message)
                self._settle_submission(
                    item,
                    run_id=run.id,
                    event="submission.refused",
                    message=message,
                    metadata={"approval_id": approval_id, "reason": "approval_missing"},
                    status=WORK_FAILED,
                    error=message,
                    error_kind=ERROR_PERMANENT,
                )
                return
            if row.status in (ApprovalStatus.EXECUTED, ApprovalStatus.FAILED) or row.result:
                # Case 3: the outcome is durable, so the board has the
                # application and this item must NOT submit again. The item is
                # *completed* rather than failed: the work this item represents
                # is done — by the earlier attempt — and failing it would make
                # the run look broken and invite a recovery that would
                # re-submit.
                message = (
                    f"The approval {approval_id!r} already records a submission "
                    f"({row.status}); the retry did not submit again."
                )
                logger.warning("Submission refused (at-most-once): %s", message)
                self._settle_submission(
                    item,
                    run_id=run.id,
                    event="submission.refused",
                    message=message,
                    metadata={
                        "approval_id": approval_id,
                        "reason": "already_submitted",
                        "approval_status": row.status,
                    },
                    status=WORK_COMPLETED,
                )
                self._processed_since_heartbeat += 1
                return

            # The submission policy is re-checked **here**, where the
            # submission actually happens, and not only at accept time. The
            # route reads it before it enqueues, but WS-32 moved the execution
            # off the request thread onto a durable queue: the gap between "the
            # operator approved this" and "the adapter is called" is now an
            # unbounded queue delay rather than a few milliseconds. Without this
            # check an approval granted while submitting was allowed would still
            # submit after ``SUBMISSION_POLICY`` was flipped to
            # ``PREPARE_ONLY`` — and that policy is the kill switch, so the
            # control has to be read where it binds.
            #
            # A refusal is an outcome, not a crash: the item settles as a
            # permanent failure, the approval row is left untouched (a human
            # decided it and the decision stands — only its execution was
            # refused), and nothing is submitted. It sits before the attempt
            # marker below on purpose: no submission attempt was started, so a
            # later run must not escalate it as "outcome unknown".
            from src.security.policy import (
                AutoSubmitNotAllowed,
                PolicyError,
                assert_execution_allowed,
                get_submission_policy,
            )

            submission_policy_name: str | None = None
            try:
                submission_policy = get_submission_policy()
                submission_policy_name = submission_policy.value
                assert_execution_allowed(submission_policy)
            except (PolicyError, AutoSubmitNotAllowed) as exc:
                message = (
                    f"The submission policy refuses executing approval {approval_id!r}: {exc} "
                    "Nothing was submitted."
                )
                logger.warning("Submission refused (policy): %s", message)
                self._settle_submission(
                    item,
                    run_id=run.id,
                    event="submission.refused",
                    message=message,
                    metadata={
                        "approval_id": approval_id,
                        "workflow_id": workflow_id,
                        "reason": "policy_blocked",
                        # ``get_submission_policy`` itself raises on an unknown
                        # configured value, so this is ``None`` in that case and
                        # carries the configured policy's value otherwise. The
                        # exception's own message names what was wrong.
                        "policy": submission_policy_name,
                    },
                    status=WORK_FAILED,
                    error=message,
                    error_kind=ERROR_PERMANENT,
                )
                return

            previous_attempt = _submission_attempt(run.extra_metadata)
            if previous_attempt is not None:
                # Case 2: an attempt was started and no outcome was recorded.
                # This is the window a crash can land in — after the adapter
                # submitted and before the result was committed — so the system
                # cannot know whether the board holds the application. It
                # refuses and hands the decision to a person rather than
                # guessing in either direction.
                started = previous_attempt.get("attempt_started_at") or "an earlier attempt"
                message = (
                    f"An earlier submission attempt for approval {approval_id!r} started at "
                    f"{started} and never recorded an outcome. It may or may not have reached "
                    "the board, so nothing was re-sent. A person must check the application "
                    "with the employer before it is submitted again."
                )
                logger.warning("Submission escalated (attempt outcome unknown): %s", message)
                self._settle_submission(
                    item,
                    run_id=run.id,
                    event="submission.uncertain",
                    message=message,
                    metadata={
                        "approval_id": approval_id,
                        "workflow_id": workflow_id,
                        "reason": "attempt_uncertain",
                        "previous_attempt": previous_attempt,
                    },
                    status=WORK_COMPLETED,
                )
                self._processed_since_heartbeat += 1
                return

            # Case 1 (nothing was attempted) and the window of case 2 are
            # separated by this marker. It is committed **before** the adapter
            # is reached, which is what makes the distinction decidable after a
            # crash: a marker with no outcome means "the adapter may have run",
            # and no marker means "it cannot have run".
            attempt_started_at = utcnow().isoformat()
            self._update_run_metadata(
                run.id,
                {
                    "submission": {
                        "attempt_started_at": attempt_started_at,
                        "approval_id": approval_id,
                        "workflow_id": workflow_id,
                    }
                },
            )

            result = self._submit_approved_application(
                row,
                workflow_id=workflow_id,
                approval_id=approval_id,
                session=session,
            )
            self._record_submission_outcome(session, row, result)

        # The summary **extends** the attempt marker rather than replacing it:
        # ``_update_run_metadata`` merges one level deep, so a bare summary would
        # drop ``attempt_started_at`` and erase the record that this attempt ran.
        # Keeping it is safe for the guard, because the recorded-outcome case is
        # checked before the uncertain-attempt case — a row with a result is
        # never read as "outcome unknown".
        self._update_run_metadata(
            run.id,
            {
                "submission": {
                    "attempt_started_at": attempt_started_at,
                    "approval_id": approval_id,
                    "workflow_id": workflow_id,
                    **_submission_summary(result),
                }
            },
        )
        # The item's status tracks the submission's outcome, because the run's
        # status is derived from its items. A submission that failed settles
        # ``FAILED`` (permanent), so the run reads ``FAILED`` and an operator
        # sees that this needs a human — a run reading ``COMPLETED`` while the
        # approval row reads ``FAILED`` would be the run lying about what
        # happened.
        #
        # ``FAILED`` here does **not** mean "retry it": the retry is refused
        # below by the at-most-once guard, for the reason the guard exists. A
        # failure is often ambiguous about whether the board received the
        # application — ``verification_failed`` means the form *was* submitted
        # and the confirmation could not be read — so retrying could apply
        # twice. The human decides, from the recorded result and evidence.
        if result.success:
            self._settle_submission(
                item,
                run_id=run.id,
                event="submission.completed",
                message=(
                    f"Submission for approval {approval_id}: {result.status} ({result.message})"
                ),
                metadata={
                    "approval_id": approval_id,
                    "workflow_id": workflow_id,
                    "status": result.status,
                    "success": True,
                },
                status=WORK_COMPLETED,
            )
            self._processed_since_heartbeat += 1
            return

        self._settle_submission(
            item,
            run_id=run.id,
            event="submission.failed",
            message=(f"Submission for approval {approval_id}: {result.status} ({result.message})"),
            metadata={
                "approval_id": approval_id,
                "workflow_id": workflow_id,
                "status": result.status,
                "success": False,
            },
            status=WORK_FAILED,
            error=f"{result.status}: {result.message}",
            error_kind=ERROR_PERMANENT,
        )
        self._failed_since_heartbeat += 1
        logger.warning(
            "Worker %s: submission %s for approval %s did not succeed: %s",
            self.worker_id,
            workflow_id,
            approval_id,
            result.message,
        )

    def _submit_approved_application(
        self,
        row: ApprovalRequestDB,
        *,
        workflow_id: str,
        approval_id: str,
        session: Session,
    ) -> ApplicationResult:
        """Restore the approved payload, resolve the adapter, execute it.

        The three steps the approve route used to perform in the request
        thread, unchanged — the payload is the **persisted** one (so the
        submitted application is the one the human reviewed), and the adapter
        is resolved from the one shared registry (so the route and the worker
        cannot disagree about which adapter exists).
        """
        from src.applications.contracts import PreparedApplication
        from src.db import access
        from src.graph.executor import execute_approved, select_adapter_by_name

        prepared = PreparedApplication.model_validate(row.payload)
        try:
            adapter = select_adapter_by_name(row.adapter_name)
        except LookupError as exc:
            # An approval built for an adapter this deployment no longer
            # registers. Retrying cannot fix it, so it is a permanent failure
            # and the row is left for a human rather than silently retried.
            from src.applications.contracts import ApplicationResult

            logger.error("Submission for approval %s refused: %s", approval_id, exc)
            return ApplicationResult(
                success=False,
                status="adapter_unavailable",
                message=str(exc),
                metadata={"workflow_id": workflow_id, "adapter": row.adapter_name},
            )

        # The tracking write needs a scope, and the worker has no caller: it is
        # the system acting on a decision that was already attributed to
        # ``row.approver``. ``LEGACY_SCOPE`` is the platform-wide view (a
        # superuser scope), which is what "no tenant" means here — the
        # approval's own owner is carried by the row, and the *authority* for
        # the submission is the recorded human decision, not this process.
        application = access.get_application_by_approval(session, access.LEGACY_SCOPE, approval_id)
        return execute_approved(
            prepared,
            adapter,
            workflow_id=workflow_id,
            approval_id=approval_id,
            approver=row.approver or "",
            decision_reason=row.decision_reason or "",
            session=session,
            application_id=application.id if application is not None else None,
        )

    def _record_submission_outcome(
        self,
        session: Session,
        row: ApprovalRequestDB,
        result: ApplicationResult,
    ) -> None:
        """Commit the submission's outcome onto the approval row.

        This is the write that makes the work durable, and it is deliberately a
        separate method: it is the last thing that happens before the work item
        is settled, so it is the point a crash must be simulated at to prove
        the at-most-once guard (a test subclasses this method and raises after
        the commit).

        The status is written **only here**, after the work ran. Nothing in
        this module writes ``EXECUTED`` for an approval that was merely
        accepted — a row that says executed while the work is queued is a lie
        in the audit trail, which is the one place this system promises not to
        lie.
        """
        from src.db.approval import ApprovalStatus

        row.status = ApprovalStatus.EXECUTED if result.success else ApprovalStatus.FAILED
        row.result = result.model_dump(mode="json")
        session.commit()

    def _settle_submission(
        self,
        item: queue.ClaimedWork,
        *,
        run_id: str,
        event: str,
        message: str,
        metadata: dict[str, Any],
        status: str,
        error: str | None = None,
        error_kind: str | None = None,
    ) -> None:
        """Settle a submission item, turning a lost lease into a warning.

        The same contract as the other handlers, with one addition: a refused
        or completed submission is recorded as one outcome, and a ``LeaseLost``
        means another worker now owns this item and this one's verdict must not
        land.
        """
        try:
            queue.settle_work_items(
                run_id=run_id,
                outcomes=[
                    queue.ItemOutcome(
                        item_id=item.id,
                        lease_token=item.lease_token,
                        status=status,
                        error=error,
                        error_kind=error_kind,
                    )
                ],
                worker_id=self.worker_id,
                session_factory=self._session_factory,
                event=event,
                message=message,
                metadata=metadata,
                now=self._now(),
            )
        except queue.LeaseLost:
            logger.warning(
                "Worker %s lost the lease on submission item %s; its verdict was discarded",
                self.worker_id,
                item.id,
            )

    def _load_run(self, run_id: str) -> JobRunDB | None:
        from src.db.session import SessionLocal

        factory = self._session_factory or SessionLocal
        with factory() as session:
            return session.get(JobRunDB, run_id)

    def _update_run_metadata(self, run_id: str, patch: dict[str, Any]) -> None:
        from src.db.session import SessionLocal

        factory = self._session_factory or SessionLocal
        with factory() as session:
            run = session.get(JobRunDB, run_id)
            if run is None:
                return
            run.extra_metadata = {**(run.extra_metadata or {}), **patch}
            session.commit()

    def _settle_failure(
        self,
        item_or_items: queue.ClaimedWork | Sequence[queue.ClaimedWork],
        *,
        error: str,
        run_id: str | None = None,
        retryable: bool | None = None,
    ) -> None:
        from src.config.settings import get_settings

        settings = get_settings()
        items = (
            [item_or_items] if isinstance(item_or_items, queue.ClaimedWork) else list(item_or_items)
        )
        if not items:
            return
        target_run = run_id or items[0].run_id
        if retryable is None:
            retryable = True
        outcomes = [
            _retry_outcome(
                item,
                error=error,
                kind="retryable" if retryable else ERROR_PERMANENT,
                now=self._now(),
                max_attempts=settings.worker_max_attempts,
                base=settings.worker_retry_base_seconds,
                max_delay=settings.worker_retry_max_seconds,
            )
            for item in items
        ]
        try:
            queue.settle_work_items(
                run_id=target_run,
                outcomes=outcomes,
                worker_id=self.worker_id,
                session_factory=self._session_factory,
                now=self._now(),
            )
        except queue.LeaseLost:
            logger.warning("Worker %s lost the lease while failing an item", self.worker_id)
            return
        self._failed_since_heartbeat += sum(
            1 for outcome in outcomes if outcome.status == WORK_FAILED
        )


def main(argv: Sequence[str] | None = None) -> int:
    """Run the worker until SIGINT/SIGTERM (``--once`` for a single pass)."""
    import argparse

    from src.core.logging import configure_logging

    parser = argparse.ArgumentParser(description="Run the JobPilot background worker.")
    parser.add_argument("--once", action="store_true", help="Drain currently due work and exit")
    parser.add_argument("--worker-id", default=None, help="Override WORKER_ID")
    parser.add_argument(
        "--poll", type=float, default=None, help="Seconds between empty-queue polls"
    )
    args = parser.parse_args(argv)

    configure_logging()
    worker = Worker(worker_id=args.worker_id, poll_interval=args.poll)

    if args.once:
        worker.register()
        try:
            while worker.run_once():
                pass
        finally:
            worker.shutdown()
        return 0

    def _stop(signum, _frame):
        logger.info("Worker received signal %s; finishing the current batch", signum)
        worker.request_stop()

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            signal.signal(sig, _stop)
        except (ValueError, OSError):  # pragma: no cover - not the main thread
            pass

    worker.run_forever()
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
