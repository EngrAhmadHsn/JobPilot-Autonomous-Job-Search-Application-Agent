"""Daily refresh CLI (FU-1): boards → normalize → dedup → persist → embed.

The cron / Windows Task Scheduler entry point for the decoupled refresh.
Runs the same executor as ``POST /api/jobs/refresh`` without HTTP timeout
concerns. Idempotent and resumable: the content-hash cache means only new or
changed listings cost embedding requests, and a daily-quota stop is reported
(and exit code 0) so the next scheduled run resumes from the cache.

Usage:
    python scripts/refresh_jobs.py
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


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    args = parser.parse_args()

    try:
        report = refresh_jobs()
    except Exception:
        logger.exception("Job refresh failed unexpectedly")
        return 1

    stats = report.stats
    print("Refresh summary:")
    print(f"  sources failed : {', '.join(sorted(report.source_errors)) or 'none'}")
    print(f"  found raw      : {stats.found}")
    print(f"  dropped        : {stats.dropped}")
    print(f"  unique         : {stats.deduped}")
    print(f"  persisted      : {stats.persisted}")
    print(f"  embedded       : {stats.embedded}")
    print(
        f"  embed requests : planned {report.embedding_requests_planned}, used {report.embedding_requests_used}"
    )
    if report.quota_exhausted:
        print(
            "  NOTE           : daily embedding quota exhausted — partial run, "
            "re-run after the reset to resume (exit 0 on purpose)"
        )
    if report.degraded_embedding:
        print("  NOTE           : vector store unavailable — rows persisted but not embedded")
    return 0


if __name__ == "__main__":
    sys.exit(main())
