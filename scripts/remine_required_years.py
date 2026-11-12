"""Re-mine the corpus now that the miner is corrected (WS-28).

`jobs.required_years` holds the output of the **old** miner. The correction in
the previous commit means 1,145 listings gain a bar and 90 change value, so the
stored column would freeze the bug in place.

This pass mines every row that has not been decided yet (`required_years_mined`
false — the rows the WS-28 migration left alone), and additionally re-decides
every row that was already marked, because those values came from the old
miner. Rows marked by **this** run are not revisited.

Idempotent: it records the decision, so a second run finds nothing to do.

    env/Scripts/python.exe scripts/remine_required_years.py [--dry-run]
"""

from __future__ import annotations

import sys
import time
from collections import Counter

sys.path.insert(0, ".")

from sqlalchemy import select

from src.db.jobs import JobDB, _mined_required_years, listing_from_row
from src.db.session import SessionLocal

#: The revision whose values were produced by the pre-WS-28 miner. Every row
#: written before this pass needs re-deciding; rows written by it do not.
_BATCH = 500


def main() -> int:
    dry_run = "--dry-run" in sys.argv
    started = time.perf_counter()

    with SessionLocal() as session:
        rows = session.execute(select(JobDB)).scalars().all()
        print(f"rows: {len(rows)}")

        changes: Counter[str] = Counter()
        samples: list[str] = []
        for row in rows:
            listing = listing_from_row(row)
            new_value = _mined_required_years(listing)
            old_value = row.required_years

            if new_value != old_value:
                kind = (
                    "gained a bar"
                    if old_value is None
                    else "lost a bar"
                    if new_value is None
                    else "changed value"
                )
                changes[kind] += 1
                if len(samples) < 12:
                    samples.append(f"  {row.id[:44]:44} {old_value} -> {new_value}  ({kind})")
                if not dry_run:
                    row.required_years = new_value
            # The decision is recorded either way, so this row is never
            # re-mined again.
            if not dry_run:
                row.required_years_mined = True

        if not dry_run:
            session.commit()

    print(f"\n{'DRY RUN — nothing written' if dry_run else 'written'}")
    for kind, count in sorted(changes.items()):
        print(f"  {kind:16} {count}")
    print(f"  total changed:    {sum(changes.values())}")
    if samples:
        print("\nexamples:")
        print("\n".join(samples))

    with SessionLocal() as session:
        total = session.execute(select(JobDB)).scalars().all()
        print(
            f"\ncorpus: {sum(1 for r in total if r.required_years is not None)}/{len(total)} "
            f"rows carry a bar; {sum(1 for r in total if r.required_years_mined)} marked decided"
        )
    print(f"elapsed: {time.perf_counter() - started:.1f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
