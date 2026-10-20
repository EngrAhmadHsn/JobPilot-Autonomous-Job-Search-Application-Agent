"""Embed persisted listings that have no vector in the vector store yet.

The daily refresh (FU-1) embeds the listings it just fetched. Listings that
have since disappeared from every board stay in the jobs table but never
re-enter the store, so they would keep the store-only search in degraded mode
forever. This script closes that gap: it embeds every persisted listing whose
id is missing from the collection and upserts it.

With the local provider (FU-7) the embeddings are computed on the CPU and
cached by content hash, so a run over an already-embedded corpus costs
seconds; a run after a provider switch re-embeds the gaps only.

Usage:
    python scripts/embed_store_gaps.py
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.config.settings import get_settings
from src.db.jobs import JobDB, listing_from_row
from src.rag.chroma_store import ChromaVectorStore

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("embed_store_gaps")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=None, help="embed at most N gaps")
    args = parser.parse_args()

    settings = get_settings()
    engine = create_engine(settings.database_url, future=True)
    with sessionmaker(bind=engine)() as session:
        rows = session.query(JobDB).all()
    engine.dispose()

    store = ChromaVectorStore()
    have = store.stored_ids()
    gaps = [listing_from_row(row) for row in rows if row.id not in have]
    if args.limit:
        gaps = gaps[: args.limit]

    if not gaps:
        print(f"no gaps: all {len(rows)} persisted listings have vectors")
        return 0

    logger.info(
        "Embedding %d gap listings (store has %d, db has %d)", len(gaps), len(have), len(rows)
    )
    written = store.upsert_jobs(gaps)
    print(f"embedded {written} gap listings; store now holds {store.count()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
