"""Seed the embedding cache from the vectors already persisted in Chroma.

The FU-7 migration re-embedded the whole corpus with the local provider, but
the local provider's content-hash cache (added after that run) starts empty.
Without seeding it, the next daily refresh would re-embed every listing
(~4.3 s/doc locally) instead of only the new or changed ones.

This script reads the collection's persisted (document, embedding) pairs and
writes them into the shared SQLite content-hash cache under the current
model identity. No model is loaded and no embedding is computed: the vectors
come straight from the store.

Usage:
    python scripts/backfill_cache_from_store.py
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from src.config.settings import get_settings
from src.llm.embeddings import MAX_TEXT_CHARS, EmbeddingCache

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("backfill_cache_from_store")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--chroma-dir", default=None, help="override CHROMA_DIR")
    parser.add_argument("--collection", default="job_listings")
    args = parser.parse_args()

    settings = get_settings()
    chroma_dir = args.chroma_dir or settings.chroma_dir

    import chromadb

    client = chromadb.PersistentClient(path=str(chroma_dir))
    collection = client.get_collection(args.collection)
    result = collection.get(include=["documents", "embeddings"])
    ids = result.get("ids") or []
    documents = result.get("documents") or []
    embeddings = result.get("embeddings")
    if embeddings is None:  # numpy array: `or []` would raise on truthiness
        embeddings = []

    cache = EmbeddingCache(Path(settings.data_dir) / "embedding_cache.sqlite")
    seeded = 0
    skipped = 0
    for job_id, document, embedding in zip(ids, documents, embeddings):
        if not document or embedding is None:
            skipped += 1
            continue
        # The cache key must describe the text the provider actually embeds:
        # the provider truncates at MAX_TEXT_CHARS before hashing, so the seed
        # must truncate identically or the cache would serve a vector that was
        # computed from a different input than its key claims.
        prepared = document[:MAX_TEXT_CHARS]
        key = EmbeddingCache.key(
            settings.embedding_model, settings.embedding_dimensionality, prepared
        )
        if cache.get(key) is not None:
            skipped += 1
            continue
        cache.put(
            key,
            settings.embedding_model,
            settings.embedding_dimensionality,
            [float(value) for value in embedding],
        )
        seeded += 1
    cache.close()

    logger.info(
        "Seeded %d cached vectors from %s (skipped %d) under model %s",
        seeded,
        chroma_dir,
        skipped,
        settings.embedding_model,
    )
    print(f"cached vectors seeded: {seeded} (skipped: {skipped})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
