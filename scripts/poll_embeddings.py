"""Poll the embedding cache every 10 minutes and log vector counts.

Usage: python scripts/poll_embeddings.py [interval_seconds]
Logs to embeddings_poll.log and stdout.
"""

import sqlite3
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

DB = Path(__file__).resolve().parent.parent / "data" / "embedding_cache.sqlite"
LOG = Path(__file__).resolve().parent.parent / "embeddings_poll.log"
INTERVAL = int(sys.argv[1]) if len(sys.argv) > 1 else 600


def snapshot():
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    try:
        total = con.execute("select count(*) from embeddings").fetchone()[0]
        by_model = con.execute("select model, count(*) from embeddings group by model").fetchall()
        recent = con.execute(
            "select count(*) from embeddings where created_at >= datetime('now', ?)",
            (f"-{INTERVAL + 60} seconds",),
        ).fetchone()[0]
        return total, by_model, recent
    finally:
        con.close()


def log(msg):
    line = msg
    print(line, flush=True)
    with LOG.open("a", encoding="utf-8") as f:
        f.write(line + "\n")


log(f"=== poller started {datetime.now(UTC):%Y-%m-%d %H:%M:%S} (interval {INTERVAL}s) ===")
prev = None
while True:
    try:
        total, by_model, recent = snapshot()
        delta = "" if prev is None else f" (+{total - prev} since last poll)"
        models = ", ".join(f"{m}={c}" for m, c in by_model)
        log(
            f"{datetime.now(UTC):%Y-%m-%d %H:%M:%S} | total vectors: {total}{delta} "
            f"| new in last ~{INTERVAL}s: {recent} | models: {models}"
        )
        prev = total
    except Exception as exc:  # noqa: BLE001 - poller must survive a transient DB error
        log(f"{datetime.now(UTC):%Y-%m-%d %H:%M:%S} | ERROR: {exc}")
    time.sleep(INTERVAL)
