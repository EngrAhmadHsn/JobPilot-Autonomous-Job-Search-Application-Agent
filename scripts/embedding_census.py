"""How much of the corpus is embedded, and in which embedding space.

Run it after a refresh, a backfill, or a worker run:

    env\\Scripts\\python.exe scripts\\embedding_census.py

Three questions, answered from the stores themselves rather than from a log:

1. **The corpus** — how many listings the database holds, how many of them have
   a vector, and how many of the queue's outstanding items are already cached
   (those need no model work at all).
2. **The space** — which vectors came from the configured local model. Chroma
   records the model at *collection* level, so a per-vector answer is an
   inference: the local embedder's content-hash cache holds one key per
   (model, dimension, document) it has ever produced, and a stored vector whose
   stored document is in that cache was produced by that model. Vectors
   produced through a different cache (a validation script, an older DATA_DIR)
   cannot be attributed; they are counted as such rather than guessed at.
3. **The legacy space** — vectors whose document is in the *retired* Gemini
   cache and not in the local one. Those are in a different embedding space and
   must be re-embedded, not resumed.

Read-only: it opens the database and the two stores, and writes nothing.
"""

from __future__ import annotations

import sqlite3
import sys
from collections import Counter
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from src.config.settings import get_settings
from src.db.jobs import JobDB, listing_from_row
from src.db.runs import JobWorkItemDB
from src.llm.embeddings import MAX_TEXT_CHARS, EmbeddingCache
from src.rag.chroma_store import ChromaVectorStore

LEGACY_MODEL = "gemini-embedding-2"
OUTSTANDING_STATUSES = ("QUEUED", "RETRY_WAIT", "RUNNING")


def _cache_keys(path: Path) -> dict[str, set[str]]:
    """Every cache key, grouped by the model identity that produced it."""
    con = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
    try:
        keys: dict[str, set[str]] = {}
        for model, key in con.execute("select model, key from embeddings"):
            keys.setdefault(model, set()).add(key)
        return keys
    finally:
        con.close()


def _stored_documents(path: Path) -> dict[str, str]:
    """job id → the document text stored next to its vector."""
    con = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
    try:
        rows = con.execute(
            "select e.embedding_id, m.string_value from embeddings e "
            "join embedding_metadata m on m.id = e.id and m.key = 'chroma:document'"
        ).fetchall()
        return {str(job_id): (document or "") for job_id, document in rows}
    finally:
        con.close()


def _key(model: str, dimension: int, document: str) -> str:
    """The cache key the embedder itself would compute for *document*."""
    return EmbeddingCache.key(model, dimension, document[:MAX_TEXT_CHARS])


def main() -> None:
    settings = get_settings()
    model = settings.embedding_model
    dimension = settings.embedding_dimensionality
    keys = _cache_keys(Path(settings.data_dir) / "embedding_cache.sqlite")
    local_keys = keys.get(model, set())
    print(f"model under test : {model} ({dimension}-dim)")
    print(
        "cache            : "
        + ", ".join(f"{name}={len(found)}" for name, found in sorted(keys.items()))
    )

    documents = _stored_documents(Path(settings.chroma_dir) / "chroma.sqlite3")
    spaces: Counter[str] = Counter()
    for document in documents.values():
        in_local = _key(model, dimension, document) in local_keys
        in_legacy = _key(LEGACY_MODEL, dimension, document) in keys.get(LEGACY_MODEL, set())
        if in_local and in_legacy:
            spaces["local (also embedded in the legacy space earlier)"] += 1
        elif in_local:
            spaces["local only"] += 1
        elif in_legacy:
            spaces["LEGACY space only — re-embed these"] += 1
        else:
            spaces["unattributed (no cache record)"] += 1
    print(f"\nstored vectors   : {len(documents)}")
    for label, count in spaces.most_common():
        print(f"  {count:6d}  {label}")

    engine = create_engine(settings.database_url, future=True)
    with Session(engine) as session:
        listings = list(session.execute(select(JobDB.id)).scalars())
        outstanding = list(
            session.execute(
                select(JobWorkItemDB.run_id, JobWorkItemDB.job_id).where(
                    JobWorkItemDB.status.in_(OUTSTANDING_STATUSES)
                )
            ).all()
        )
        job_ids = {job_id for _, job_id in outstanding}
        rows = {
            row.id: row
            for row in session.execute(select(JobDB).where(JobDB.id.in_(job_ids))).scalars()
        }

    cached = 0
    missing = 0
    for job_id in job_ids:
        row = rows.get(job_id)
        if row is None:
            missing += 1
            continue
        document = ChromaVectorStore.document_text(listing_from_row(row))
        if _key(model, dimension, document) in local_keys:
            cached += 1

    print(f"\nlistings         : {len(listings)}")
    print(f"without a vector : {len(listings) - len(documents)}")
    print(f"\noutstanding items: {len(outstanding)} (over {len(job_ids)} distinct listings)")
    print(f"  already cached : {cached}  (no model work needed)")
    print(f"  row missing    : {missing}")
    print(f"  model work left: {len(job_ids) - cached - missing}")


if __name__ == "__main__":
    main()
