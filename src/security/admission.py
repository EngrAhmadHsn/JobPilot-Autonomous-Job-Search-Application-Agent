"""Corpus admission control (WS-12).

The refresh pipeline pulls listings from several boards and stores them. A
board is untrusted input, so the *number* of listings it may contribute,
and the *size* of the corpus those listings build, must be bounded by the
system rather than by the board.

Four limits, applied in order:

1. **Per source** — no single board may contribute more than
   ``max_listings_per_source`` listings in one refresh. A board that
   suddenly returns 50,000 listings is either broken or hostile; either way
   it does not get to dictate the shape of the corpus.
2. **Per refresh** — the total number of *new* listings admitted in one
   refresh is bounded by ``max_new_listings_per_refresh``.
3. **Corpus** — the persisted corpus is bounded by ``max_corpus_listings``.
   This is the limit that protects the read path: every search scans the
   corpus, so an unbounded corpus is an unbounded search.
4. **Embedding work** — at most ``max_embed_per_refresh`` listings are
   embedded in one refresh. This is the limit that protects the *provider
   quota* and therefore the cache: a flood of unique listings must not be
   able to spend the whole daily budget on texts nobody will search for.

The admission decision is **recorded, not silent**: every truncation is
counted and reported, so a refresh report says how many listings were
dropped and why. A limit that silently discards data is a bug waiting to be
mistaken for a feature.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from src.jobs.contracts import JobListing
from src.security.limits import SecurityLimits, get_limits

logger = logging.getLogger(__name__)

__all__ = ["AdmissionReport", "admit_listings", "cap_corpus_size"]


@dataclass
class AdmissionReport:
    """What admission control did to one batch of listings."""

    #: The listings that were admitted.
    admitted: list[JobListing] = field(default_factory=list)
    #: How many listings were dropped before admission.
    screened_out: int = 0
    #: How many listings were dropped because a per-source cap was hit.
    per_source_capped: int = 0
    #: How many listings were dropped because the per-refresh cap was hit.
    per_refresh_capped: int = 0
    #: The corpus size after admission, when it was measured.
    corpus_size: int | None = None
    #: How many listings were dropped because the corpus was full.
    corpus_capped: int = 0
    #: How many listings were dropped for being older than the age bound.
    age_capped: int = 0
    #: The reasons recorded for the screened-out listings.
    reasons: list[str] = field(default_factory=list)

    @property
    def total_dropped(self) -> int:
        """Every listing that did not make it in, for any reason."""
        return (
            self.screened_out
            + self.per_source_capped
            + self.per_refresh_capped
            + self.corpus_capped
            + self.age_capped
        )


def _drop_too_old(
    listings: list[JobListing],
    max_age_days: int,
    report: AdmissionReport,
) -> list[JobListing]:
    """Drop listings whose ``posted_at`` is older than the age bound.

    WS-23b. Uses ``posted_at`` — which every adapter already populates —
    so it costs no extra request. A listing that states **no** date is
    kept: refusing it would be guessing that it is old, and a listing
    with no date is not evidence of an old listing.

    ``max_age_days <= 0`` disables the bound, which is what a first run
    against a historical archive would want.
    """
    if max_age_days <= 0 or not listings:
        return listings

    from datetime import UTC, datetime, timedelta

    cutoff = datetime.now(UTC) - timedelta(days=max_age_days)
    kept: list[JobListing] = []
    for listing in listings:
        posted = _parse_posted_at(listing.posted_at)
        if posted is not None and posted < cutoff:
            report.age_capped += 1
            continue
        kept.append(listing)

    if report.age_capped:
        logger.warning(
            "Age bound (%d days) dropped %d listings that were posted before %s",
            max_age_days,
            report.age_capped,
            cutoff.date().isoformat(),
        )
    return kept


def _parse_posted_at(value: str | None):
    """A listing's ``posted_at`` as an aware datetime, or ``None``.

    The adapters normalize to ISO-8601 strings of varying shapes (Lever
    is a millisecond epoch converted at ingest, Ashby is offset-aware,
    Remotive is naive local). An unparsable value is ``None`` — kept,
    not dropped, because an unreadable date is not evidence of age.
    """
    from datetime import UTC, datetime

    if not value or not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed


def admit_listings(
    listings: list[JobListing],
    *,
    limits: SecurityLimits | None = None,
    corpus_size: int | None = None,
) -> AdmissionReport:
    """Apply the per-source, per-refresh, and corpus limits to *listings*.

    Args:
        listings: The listings a refresh collected, across all sources.
        limits: The limits to apply; the process-wide ones by default.
        corpus_size: How many listings the corpus already holds. ``None``
            means "not measured", and the corpus limit is then not applied
            (the caller does not know the size and must not guess).

    Returns:
        The admitted listings and a report of everything that was dropped.
    """
    active = limits or get_limits()
    report = AdmissionReport()

    # -- the age bound (WS-23b) --------------------------------------------
    # A posting from six months ago is not a job anyone should apply to.
    # The corpus had no age signal at all, so a listing closed months ago
    # was still admitted, still ranked, and still carried a valid
    # application URL.
    #
    # This runs **first** so it does not consume any of the other
    # budgets: a washed-out listing should not take a per-source slot or
    # an embedding budget slot from a live one.
    listings = _drop_too_old(listings, active.max_job_age_days, report)

    # -- per source ---------------------------------------------------------
    per_source: dict[str, int] = {}
    kept: list[JobListing] = []
    for listing in listings:
        source = listing.source or "unknown"
        seen = per_source.get(source, 0)
        if seen >= active.max_listings_per_source:
            report.per_source_capped += 1
            continue
        per_source[source] = seen + 1
        kept.append(listing)

    if report.per_source_capped:
        logger.warning(
            "Per-source listing cap (%d) dropped %d listings",
            active.max_listings_per_source,
            report.per_source_capped,
        )

    # -- per refresh --------------------------------------------------------
    if len(kept) > active.max_new_listings_per_refresh:
        report.per_refresh_capped = len(kept) - active.max_new_listings_per_refresh
        kept = kept[: active.max_new_listings_per_refresh]
        logger.warning(
            "Per-refresh listing cap (%d) dropped %d listings",
            active.max_new_listings_per_refresh,
            report.per_refresh_capped,
        )

    # -- corpus -------------------------------------------------------------
    if corpus_size is not None:
        report.corpus_size = corpus_size
        room = max(0, active.max_corpus_listings - corpus_size)
        if len(kept) > room:
            report.corpus_capped = len(kept) - room
            kept = kept[:room]
            logger.warning(
                "Corpus cap (%d) dropped %d listings; the corpus is full",
                active.max_corpus_listings,
                report.corpus_capped,
            )

    report.admitted = kept
    return report


def cap_corpus_size(
    listings: list[JobListing],
    *,
    limits: SecurityLimits | None = None,
) -> list[JobListing]:
    """Trim *listings* to the per-refresh admission cap.

    The narrow companion to :func:`admit_listings`, for the call sites that
    only need the batch cap (the embedding path, for instance) and not the
    corpus accounting.
    """
    active = limits or get_limits()
    if len(listings) <= active.max_new_listings_per_refresh:
        return listings
    logger.warning(
        "Trimming %d listings to the per-refresh cap of %d",
        len(listings),
        active.max_new_listings_per_refresh,
    )
    return listings[: active.max_new_listings_per_refresh]
