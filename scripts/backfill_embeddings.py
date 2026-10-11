"""Backfill the embedding cache for every persisted job listing.

The Gemini free tier effectively allows ~100 embedded texts per minute (the
per-minute quota counts each batched Content as a request), so embedding a
full multi-thousand-job corpus in one pipeline run trips RESOURCE_EXHAUSTED.
This script walks the persisted jobs in API-sized batches (100 texts, the
live batch cap), retries rate-limited batches after a paced wait, and lets
``GeminiEmbedding`` write every vector to the SQLite content-hash cache. A
pipeline run after a completed backfill makes zero embedding API calls.

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
from src.llm.client import LLMRateLimited
from src.llm.embeddings import GeminiEmbedding
from src.rag.chroma_store import ChromaVectorStore

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("backfill_embeddings")

BATCH_SIZE = 100  # live API batch cap (see src/llm/embeddings.py)
RATE_LIMIT_WAIT_SECONDS = 60.0  # free-tier window; err on the safe side


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
