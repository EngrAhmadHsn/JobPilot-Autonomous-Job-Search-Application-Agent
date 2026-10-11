"""Backfill the embedding cache for every persisted job listing.

Free-tier embedding quota (AI Studio dashboard, verified 2026-10-11):
RPM 5, TPM ~250K (never binding at ~1.5K tokens/job), RPD 20. With the
100-text live batch cap that is ~2,000 embeddable texts per DAY, so a full
multi-thousand-job corpus is a multi-day background trickle, not an
in-pipeline operation. This script walks the persisted jobs in API-sized
batches (100 texts), waits out rate-limited windows (self-healing across
the daily quota reset), and lets ``GeminiEmbedding`` write every vector to
the SQLite content-hash cache. A pipeline run after a completed backfill
makes zero embedding API calls. See 04-pipeline-and-api.md FU-1/FU-4.

Usage:
    python scripts/backfill_embeddings.py            # all persisted jobs
    python scripts/backfill_embeddings.py --limit 500
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.config.settings import get_settings
from src.db.jobs import JobDB, listing_from_row
from src.llm.client import LLMDailyQuotaExhausted, LLMRateLimited
from src.llm.embeddings import GeminiEmbedding
from src.rag.chroma_store import ChromaVectorStore

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("backfill_embeddings")

BATCH_SIZE = 100  # live API batch cap (see src/llm/embeddings.py)
# 60s respects RPM 5 on 429s; after the DAILY quota (RPD 20) is spent the
# retries keep failing until the quota window resets, then resume automatically.
RATE_LIMIT_WAIT_SECONDS = 60.0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=None, help="Embed only the first N jobs")
    args = parser.parse_args()

    settings = get_settings()
    engine = create_engine(settings.database_url, future=True)
    factory = sessionmaker(bind=engine)
    with factory() as session:
        rows = session.query(JobDB).order_by(JobDB.id).all()
    if args.limit:
        rows = rows[: args.limit]

    if not rows:
        logger.info("No persisted jobs found in %s", settings.database_url)
        return 0

    embeddings = GeminiEmbedding()
    logger.info("Backfilling embeddings for %d persisted jobs", len(rows))

    done = 0
    started = time.monotonic()
    for start in range(0, len(rows), BATCH_SIZE):
        chunk = rows[start : start + BATCH_SIZE]
        documents = [ChromaVectorStore.document_text(listing_from_row(row)) for row in chunk]
        while True:
            try:
                embeddings.embed_documents(documents)
                break
            except LLMDailyQuotaExhausted:
                # FU-4: the class paces and distinguishes daily exhaustion;
                # stop cleanly, the cache keeps every completed batch.
                logger.warning(
                    "Daily embedding quota exhausted at batch %d; exiting — "
                    "re-run tomorrow to resume (completed batches stay cached)",
                    start // BATCH_SIZE + 1,
                )
                logger.info("Backfill partial: %d/%d jobs embedded and cached", done, len(rows))
                engine.dispose()
                return 0
            except LLMRateLimited:
                logger.warning(
                    "Rate limited at batch %d; sleeping %.0fs (cache keeps prior batches)",
                    start // BATCH_SIZE + 1,
                    RATE_LIMIT_WAIT_SECONDS,
                )
                time.sleep(RATE_LIMIT_WAIT_SECONDS)
        done += len(chunk)
        elapsed = time.monotonic() - started
        logger.info("Embedded %d/%d jobs (%.0fs elapsed)", done, len(rows), elapsed)

    logger.info("Backfill complete: %d jobs embedded and cached", done)
    engine.dispose()
    return 0


if __name__ == "__main__":
    sys.exit(main())
