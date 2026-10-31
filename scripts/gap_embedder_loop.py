"""Close the vector-store gap, resumably, then keep polling.

Runs ``embed_store_gaps`` until the Chroma store holds every persisted
listing, chunk by chunk. The daily work cap (MAX_EMBED_WORK_PER_DAY) is
enforced inside the embedder, so a run that hits it stops cleanly and this
loop simply waits for the next UTC day and resumes — the script is safe to
re-run at any time because the content-hash cache makes completed work free.

Designed to be launched detached (see scripts/run_gap_embedder_detached.ps1):
it survives the ZCode session, logs to gap_embedder.log in the repo root,
and appends one line per cycle so progress can be followed with:

    Get-Content gap_embedder.log -Tail 20
"""

from __future__ import annotations

import logging
import subprocess
import sys
import time
import traceback
from datetime import UTC, datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

LOG = REPO_ROOT / "gap_embedder.log"
IDLE_SLEEP_SECONDS = 15 * 60  # re-check for new gaps every 15 minutes
ERROR_SLEEP_SECONDS = 5 * 60  # back off after a failed cycle

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("gap_embedder_loop")


def log(msg: str) -> None:
    line = f"{datetime.now(UTC):%Y-%m-%d %H:%M:%S} | {msg}"
    print(line, flush=True)
    with LOG.open("a", encoding="utf-8") as f:
        f.write(line + "\n")


def gap_report() -> tuple[int, int, int]:
    """Return (db jobs, store vectors, gaps) using the same imports as the app."""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from src.config.settings import get_settings
    from src.db.jobs import JobDB
    from src.rag.chroma_store import ChromaVectorStore

    settings = get_settings()
    engine = create_engine(settings.database_url, future=True)
    with sessionmaker(bind=engine)() as session:
        db_ids = {row[0] for row in session.query(JobDB.id).all()}
    engine.dispose()
    store = ChromaVectorStore()
    have = store.stored_ids()
    return len(db_ids), store.count(), len(db_ids - have)


def embed_chunk(limit: int) -> int:
    """Embed at most ``limit`` gaps via the app's own script; return count embedded."""
    result = subprocess.run(
        [sys.executable, str(REPO_ROOT / "scripts" / "embed_store_gaps.py"), "--limit", str(limit)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=3600,
    )
    out = (result.stdout or "") + (result.stderr or "")
    out = out.strip()
    if out:
        for line in out.splitlines()[-3:]:
            log(f"  [embed_store_gaps] {line}")
    if result.returncode != 0:
        raise RuntimeError(f"embed_store_gaps exited {result.returncode}")
    for line in out.splitlines():
        # "embedded N gap listings; store now holds M" — N=0 means quota hit.
        if line.startswith("embedded ") and " gap listings" in line:
            return int(line.split()[1])
    return 0


def main() -> int:
    log("=== gap embedder loop started (detached; safe to kill and re-run) ===")
    while True:
        try:
            db_jobs, store_count, gaps = gap_report()
            if gaps == 0:
                log(
                    f"idle: store {store_count} / db {db_jobs}, no gaps; sleeping {IDLE_SLEEP_SECONDS // 60} min"
                )
                time.sleep(IDLE_SLEEP_SECONDS)
                continue

            # One embed_store_gaps run over 100 gaps takes minutes of CPU; work in
            # chunks of 50 so every completed chunk is durable and a crash or a
            # daily-quota stop loses nothing (the cache holds completed work).
            chunk_size = 50
            remaining = gaps
            while remaining > 0:
                embedded = embed_chunk(min(chunk_size, remaining))
                if embedded == 0:
                    # Either the daily work budget is spent or the embedder wrote
                    # nothing — report both possibilities and wait; the loop self-
                    # heals when the UTC day rolls over (budget resets) or the
                    # cause is fixed.
                    db_jobs, store_count, gaps = gap_report()
                    log(
                        f"quota-or-zero-progress: store {store_count} / db {db_jobs} "
                        f"({gaps} gaps); sleeping {IDLE_SLEEP_SECONDS // 60} min"
                    )
                    break
                remaining -= embedded
                db_jobs, store_count, gaps = gap_report()
                log(
                    f"progress: +{embedded} vectors; store {store_count} / db {db_jobs} ({gaps} gaps left)"
                )
            time.sleep(IDLE_SLEEP_SECONDS)
        except Exception as exc:  # noqa: BLE001 - loop must survive transient failures
            log(f"ERROR: {exc}")
            traceback.print_exc()
            time.sleep(ERROR_SLEEP_SECONDS)


if __name__ == "__main__":
    sys.exit(main())
