"""Fair selection of listings across sources (WS-15 · WS-18).

A board is untrusted input and controls the order of its own response, so
"take the first N listings" is "take whatever the attacker put first". The
round-robin share gives every source an equal slice of a bounded budget until
its own listings run out, which caps a flood on one board at roughly
``1 / number_of_sources`` of the work.

The helper lived inside ``src.graph.job_executor`` until WS-18; the durable
embedding planner needs it too, and two copies of a fairness rule is two
rules.
"""

from __future__ import annotations

from collections.abc import Sequence

from src.jobs.contracts import JobListing

__all__ = ["share_by_source"]


def share_by_source(listings: Sequence[JobListing], limit: int) -> list[JobListing]:
    """Take up to *limit* listings, round-robin across their sources."""
    if limit <= 0 or not listings:
        return []
    buckets: dict[str, list[JobListing]] = {}
    order: list[str] = []
    for listing in listings:
        source = listing.source or "unknown"
        if source not in buckets:
            buckets[source] = []
            order.append(source)
        buckets[source].append(listing)

    chosen: list[JobListing] = []
    depth = 0
    while len(chosen) < limit:
        added = False
        for source in order:
            bucket = buckets[source]
            if depth < len(bucket):
                chosen.append(bucket[depth])
                added = True
                if len(chosen) >= limit:
                    break
        if not added:
            break
        depth += 1
    return chosen
