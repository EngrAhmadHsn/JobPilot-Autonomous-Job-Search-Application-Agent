"""Daily refresh CLI (FU-1 · WS-18): boards → normalize → dedup → persist → embed.

Two modes:

- ``python scripts/refresh_jobs.py`` runs the refresh **in this process**
  and prints the report. It uses the same transactional outbox and the same
  embedding handler as the worker, so it exercises the production path.
- ``python scripts/refresh_jobs.py --enqueue`` writes a durable refresh run
  and returns immediately. A separate ``scripts/run_worker.py`` executes it.
  This is the mode a cron/Task Scheduler entry should use when a worker is
  deployed: the schedule and the execution have different lifetimes.

Idempotent either way: the content hash means only new or changed listings
cost an embedding, and a daily-quota stop leaves everything persisted and
queued for the next run.
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from src.graph.job_executor import refresh_jobs

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("refresh_jobs")


def _enqueue() -> int:
    """Write the durable run and exit without doing the work here."""
    from src.db.session import SessionLocal
    from src.runs import queue as run_queue
    from src.runs import service as run_service

    with SessionLocal() as session:
        try:
            run, created = run_service.enqueue_refresh_platform(session)
        except run_queue.QueueFull as exc:
            print(f"Queue full: {exc} (retry after {exc.retry_after}s)")
            return 1
    print(
        f"Refresh {'enqueued' if created else 'already active'}: run_id={run.id} status={run.status}"
    )
    print("Run `python scripts/run_worker.py` (or the supervised service) to execute it.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--enqueue",
        action="store_true",
        help="Accept the refresh as a durable run and exit; a worker executes it",
    )
    args = parser.parse_args()

    if args.enqueue:
        return _enqueue()

    try:
        report = refresh_jobs()
    except Exception:
        logger.exception("Job refresh failed unexpectedly")
        return 1

    stats = report.stats
    print("Refresh summary:")
    print(f"  run id         : {report.run_id or 'none (nothing new to embed)'}")
    print(f"  sources failed : {', '.join(sorted(report.source_errors)) or 'none'}")
    print(f"  found raw      : {stats.found}")
    print(f"  dropped        : {stats.dropped}")
    print(f"  unique         : {stats.deduped}")
    print(f"  persisted      : {stats.persisted}")
    print(f"  embedded       : {stats.embedded}")
    print(
        f"  embed requests : planned {report.embedding_requests_planned}, "
        f"used {report.embedding_requests_used}"
    )
    if report.quota_exhausted:
        print(
            "  NOTE           : daily embedding quota exhausted — partial run, "
            "the work is queued and resumes after the reset (exit 0 on purpose)"
        )
    if report.degraded_embedding:
        print("  NOTE           : vector store unavailable — rows persisted and indexing queued")
    return 0


if __name__ == "__main__":
    sys.exit(main())
