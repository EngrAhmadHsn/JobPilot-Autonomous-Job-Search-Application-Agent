"""Per-process cache of the artifacts a store-only search rebuilds (WS-21 follow-up).

A search re-derives, from scratch on every request, things that do not depend
on the candidate at all: the corpus rows mapped to ``JobListing``, the BM25
index over their text, the weighted important terms of every posting, and
every posting's stated experience bar. Measured on 6,696 listings that is
roughly 32 seconds of the request — pure recomputation.

The cache is keyed by a **fingerprint the corpus maintains itself**: the
database identity, the row count, and a hash of the corpus's **content**
(WS-24). The third component used to be the newest ``last_seen_at``, which
is a *sighting* time rather than a content time — a refresh that re-sees
unchanged listings moved it for every listing, so every refresh invalidated
the cache and the first search after each refresh paid the full rebuild
again. The fingerprint now hashes the fields the artifacts are actually
derived from, so a refresh that changed nothing keeps the cache, and a
refresh that changed a description does not. It holds at most two entries,
and a benign race under the API's thread pool may build an entry twice —
never serve a wrong fingerprint.
"""

from __future__ import annotations

import hashlib
from collections import OrderedDict
from dataclasses import dataclass, field

from src.db.jobs import JobDB, listing_from_row
from src.jobs.contracts import JobListing
from src.matching.experience import required_years
from src.matching.lexical import Bm25Index, _important_terms, _required_phrases

__all__ = [
    "CorpusArtifacts",
    "clear_corpus_cache",
    "corpus_fingerprint",
    "get_corpus_artifacts",
]

#: How many distinct corpus states to keep. Two covers "a refresh landed while
#: a search was running" without letting the cache grow with every edit.
_MAX_ENTRIES = 2

#: The shape of :class:`CorpusArtifacts`, as a version in the fingerprint.
#:
#: WS-24c. The fingerprint hashes the corpus *content* it can see, so it moves
#: when a field the artifacts are derived from changes. It cannot see when the
#: **set of derived fields** changes — adding ``seniority_ranks`` to the
#: dataclass leaves every stored row identical, so without this a process that
#: had already cached the previous shape would keep serving it, with the new
#: field silently empty. Bumping this constant forces exactly one rebuild.
#:
#: 1 — WS-24/24b artifacts (terms, bars, classifications, phrase lists).
#: 2 — WS-24c: adds ``seniority_ranks``, and hashes ``seniority``.
_ARTIFACTS_VERSION = 2


@dataclass
class CorpusArtifacts:
    """Everything a search re-uses across requests (candidate-independent)."""

    fingerprint: tuple[str, int, str]
    jobs: list[JobListing] = field(default_factory=list)
    index: Bm25Index | None = None
    #: Weighted important terms per job id (the lexical coverage channel).
    lexical_terms: dict[str, list[tuple[str, float]]] = field(default_factory=dict)
    #: The stated experience bar per job id (``None`` = not stated).
    required_years: dict[str, float | None] = field(default_factory=dict)
    #: The occupational-role classification per job id.
    #:
    #: WS-24. The classifier has an ``lru_cache`` of 8,192 entries, but
    #: the corpus now holds 8,558 listings — so the cache **thrashes**:
    #: every search evicted the entries it was about to need and
    #: re-classified all of them. The taxonomy scan is the most
    #: expensive part of the per-listing work (measured: 4.9 million
    #: pattern matches and 9.6 s of a warm search at 8,558 listings).
    #:
    #: The classification depends only on the listing, so it belongs
    #: here, with the listing's other derived artifacts. It is computed
    #: once when the corpus is read and re-used by every search until
    #: the content changes.
    role_classifications: dict[str, object] = field(default_factory=dict)
    #: The weight total per job id — ``sum(weight for _t, weight in terms)``.
    #:
    #: WS-24b. The coverage channel divides the matched weight by this
    #: total, and it depends only on the listing's terms — which are
    #: already cached one line up. It was being summed for every listing
    #: on every search (8,558 additions per request).
    lexical_weight_totals: dict[str, float] = field(default_factory=dict)
    #: The multi-word required phrases per job id (``_required_phrases``).
    #:
    #: WS-24b. It re-split ``required_skills`` for every listing on every
    #: search. The phrases depend only on the listing, so they are cached
    #: with its other derived artifacts.
    required_phrases: dict[str, list[str]] = field(default_factory=dict)
    #: The seniority rank stated by each listing (``None`` = not stated).
    #:
    #: WS-24c. ``_seniority_component`` derives the rank from
    #: ``job.seniority`` and then from ``job.title``, walking a 19-keyword
    #: ladder with a word-boundary regex on each step. The rank depends only
    #: on the listing, so it belongs here with the other derived artifacts.
    #:
    #: This field is why ``content_version_for`` hashes ``seniority``: the
    #: rank reads that column, so a refresh that changed only the seniority
    #: must move the fingerprint or a stale rank would be served. See the
    #: ``_ARTIFACTS_VERSION`` note on the fingerprint for the general rule.
    seniority_ranks: dict[str, int | None] = field(default_factory=dict)


_CACHE: OrderedDict[tuple[str, int, str | None], CorpusArtifacts] = OrderedDict()


def clear_corpus_cache() -> None:
    """Drop every cached entry (tests; operational use)."""
    _CACHE.clear()


def _database_identity(session_factory) -> str:
    """A stable name for the database a factory points at."""
    bind = getattr(session_factory, "kw", {}).get("bind")
    url = getattr(bind, "url", None)
    return str(url) if url is not None else "unknown"


def corpus_fingerprint(session_factory) -> tuple[str, int, str]:
    """The corpus's **content** version: database, row count, content hash.

    WS-24: this used to be ``(database, row count, max(last_seen_at))``, and
    the third component was the bug. ``last_seen_at`` is a **sighting**
    time, not a content time: a refresh that re-sees unchanged listings
    moves it for every one of them, so every refresh changed the
    fingerprint, so the whole artifacts cache was discarded and the 32.56 s
    rebuild was paid again by the first search after every morning's
    refresh (measured on the 6,696-listing corpus; ~4 minutes projected at
    the 50,000 cap).

    The artifacts depend on exactly the fields hashed here — the title, the
    description, the skill lists and the requirement strings — so a corpus
    whose *content* is unchanged has an unchanged fingerprint, and the
    cache survives a refresh that changed nothing.

    The cost is one pass over the corpus reading the stored per-row
    ``content_version`` digest — 64 characters per listing, rather than
    its full description text — which is cheap enough to do on every
    search (hashing the raw text instead cost ~1 s per search at 6,696
    rows, because the corpus carries ~43 MB of descriptions).
    """
    from sqlalchemy import select

    with session_factory() as session:
        rows = session.execute(select(JobDB.id, JobDB.content_version)).all()

    digest = hashlib.sha256()
    # The artifacts' own shape, so adding a derived field invalidates once.
    digest.update(f"artifacts-v{_ARTIFACTS_VERSION}".encode())
    digest.update(b"\x1d")
    for job_id, content_version in rows:
        digest.update((job_id or "").encode("utf-8", errors="replace"))
        digest.update(b"\x1f")
        digest.update((content_version or "").encode("utf-8", errors="replace"))
        digest.update(b"\x1e")
    return (_database_identity(session_factory), len(rows), digest.hexdigest())


def get_corpus_artifacts(*, session_factory=None, limit: int | None = None) -> CorpusArtifacts:
    """The artifacts for the current corpus state, building them once.

    Args:
        session_factory: The sessionmaker to read through (defaults to the
            application's ``SessionLocal``).
        limit: The corpus cap (a row limit, also applied on a rebuild).
    """
    if session_factory is None:
        from src.db.session import SessionLocal

        session_factory = SessionLocal

    fingerprint = corpus_fingerprint(session_factory)
    cached = _CACHE.get(fingerprint)
    if cached is not None:
        _CACHE.move_to_end(fingerprint)
        return cached

    with session_factory() as session:
        statement = session.query(JobDB)
        if limit is not None:
            statement = statement.limit(limit)
        rows = statement.all()
    jobs = [listing_from_row(row) for row in rows]
    # WS-23b: the bar is mined once at **write** time and stored, so the
    # rebuild reads a column instead of re-mining every description. The
    # mining was 9.5 s of the 32.56 s rebuild — the most expensive
    # per-listing item — and it produced the same answer every time.
    stored_years: dict[str, float | None] = {row.id: row.required_years for row in rows}

    # WS-24c: the seniority ladder is imported here rather than at module
    # scope because ``engine`` imports this module (``CorpusArtifacts``), so a
    # top-level import would be circular. WS-24: the role classification is
    # derived from the listing alone, so it is computed below with the
    # listing's other derived artifacts and re-used by every search until the
    # content changes.
    from src.matching.engine import _seniority_rank
    from src.matching.roles import classify_job_role

    lexical_terms = {job.id: _important_terms(job) for job in jobs}
    artifacts = CorpusArtifacts(
        fingerprint=fingerprint,
        jobs=jobs,
        index=Bm25Index(jobs),
        lexical_terms=lexical_terms,
        # A row written before WS-23b has no stored bar; fall back to
        # mining it, so an un-migrated corpus still scores correctly.
        required_years={
            job.id: (
                stored_years.get(job.id)
                if stored_years.get(job.id) is not None
                else required_years(job)
            )
            for job in jobs
        },
        role_classifications={job.id: classify_job_role(job) for job in jobs},
        # WS-24b: the sum over the terms just computed, cached beside
        # them — it depends only on the listing.
        lexical_weight_totals={
            job_id: sum(weight for _term, weight in terms)
            for job_id, terms in lexical_terms.items()
        },
        # WS-24b: the multi-word required phrases, split once.
        required_phrases={job.id: _required_phrases(job) for job in jobs},
        # WS-24c: the seniority rank the listing states, resolved once.
        seniority_ranks={
            job.id: _seniority_rank(job.seniority) or _seniority_rank(job.title) for job in jobs
        },
    )
    _CACHE[fingerprint] = artifacts
    while len(_CACHE) > _MAX_ENTRIES:
        _CACHE.popitem(last=False)
    return artifacts
