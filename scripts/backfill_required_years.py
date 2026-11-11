"""Backfill jobs.required_years for rows written before WS-23b.

One pass over the corpus, mining each description with the same function
the ingest now uses. Idempotent: it only touches rows whose value is NULL.
"""

import sys
import time

sys.path.insert(0, ".")

from sqlalchemy import select

from src.db.jobs import JobDB, _mined_required_years, listing_from_row
from src.db.session import SessionLocal

t0 = time.perf_counter()
with SessionLocal() as s:
    rows = (
        s.execute(
            select(JobDB).where(JobDB.required_years.is_(None), JobDB.description.isnot(None))
        )
        .scalars()
        .all()
    )
    print(f"rows to backfill: {len(rows)}")

    filled = 0
    for row in rows:
        listing = listing_from_row(row)
        value = _mined_required_years(listing)
        if value is not None:
            row.required_years = value
            filled += 1
    s.commit()
    print(
        f"mined a bar for {filled} of {len(rows)} ({filled / len(rows) * 100:.1f}%)"
        if rows
        else "nothing to do"
    )

with SessionLocal() as s:
    total = s.execute(select(JobDB.id)).all()
    with_bar = s.execute(select(JobDB.id).where(JobDB.required_years.isnot(None))).all()
    print(
        f"corpus: {len(with_bar)}/{len(total)} rows now carry a mined bar "
        f"({len(with_bar) / len(total) * 100:.1f}%)"
    )
print(f"elapsed: {time.perf_counter() - t0:.1f}s")
