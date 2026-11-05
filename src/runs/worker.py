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
from typing import Any

from sqlalchemy.orm import sessionmaker

from src.db.runs import JobRunDB
from src.runs import queue
from src.runs.embedding import (
    EMBED_WORK_TYPE,
    RECONCILE_WORK_TYPE,
    _classify,
    _retry_outcome,
    process_embedding_items,
    run_reconcile,
)
from src.runs.state import (
    ERROR_PERMANENT,
    WORK_COMPLETED,
    WORK_FAILED,
    utcnow,
)

logger = logging.getLogger(__name__)

__all__ = ["Worker", "default_worker_id", "main"]

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
            self._processed_since_heartbeat = 0
            self._failed_since_heartbeat = 0
        except Exception:
            logger.exception("Worker heartbeat failed")

    # -- execution ----------------------------------------------------------

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
        try:
            store = self._embedding_store()
            result = process_embedding_items(
                items,
                run_id=run_id,
                worker_id=self.worker_id,
                store=store,
                session_factory=self._session_factory,
                now=self._now(),
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
            self._settle_failure(
                item, error=f"{type(exc).__name__}: {exc}", retryable=retryable
            )

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
