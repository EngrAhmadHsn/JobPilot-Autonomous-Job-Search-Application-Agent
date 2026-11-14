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

WS-24 §4a.2 makes a moved fingerprint **cheap**: the cache also keeps the
per-row ``content_version`` map it built from, so the next build recomputes
only the listings whose content actually moved and re-uses the rest by
identity. Measured at 8,558 listings, the per-listing artifacts are 33.5 s of
a 46 s rebuild; the global BM25 index is the remaining 12.8 s and is still
rebuilt whole, because its document frequencies change when any document does.
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
#: 3 — WS-24 §4a.2: the build is incremental, so the cache keeps the row map
#:     it built from and re-uses an artifact only for an id whose
#:     ``content_version`` did not move.
_ARTIFACTS_VERSION = 3


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
    #: The ``content_version`` of every row this build read, by job id.
    #:
    #: WS-24 §4a.2. The fingerprint is a single digest, so it can say *that*
    #: the corpus moved and nothing about *what* moved. Keeping the per-row
    #: map lets the next build diff the two and recompute only the listings
    #: whose content actually changed — measured, the per-listing artifacts
    #: are 33.5 s of a 46 s rebuild at 8,558 listings, against 12.8 s for
    #: the global BM25 index, which cannot go incremental.
    row_versions: dict[str, str] = field(default_factory=dict)


_CACHE: OrderedDict[tuple[str, int, str], CorpusArtifacts] = OrderedDict()


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


def _important_terms_for(job: JobListing) -> list[tuple[str, float]]:
    """One listing's weighted important terms.

    WS-24 §4a.2. A named seam, so the full build and the incremental update
    call the same definition — a second implementation would be a second
    answer — and so a test can count the work a rebuild actually did.
    """
    return _important_terms(job)


def _role_for(job: JobListing):
    """One listing's occupational-role classification."""
    from src.matching.roles import classify_job_role

    return classify_job_role(job)


def _rank_for(job: JobListing) -> int | None:
    """The seniority rank one listing states, in the title or the field."""
    from src.matching.engine import _seniority_rank

    return _seniority_rank(job.seniority) or _seniority_rank(job.title)


def _bar_for(job: JobListing, stored: float | None, decided: bool) -> float | None:
    """One listing's stated experience bar.

    A row whose mining decision was recorded is taken as decided — including
    when the answer is "no bar". A row from before the WS-28 marker is still
    mined, so an un-migrated corpus scores correctly without a backfill.
    """
    return stored if decided else required_years(job)


def _weight_total_for(terms: list[tuple[str, float]]) -> float:
    """The summed weight of a listing's terms (the coverage denominator)."""
    return sum(weight for _term, weight in terms)


def get_corpus_artifacts(*, session_factory=None, limit: int | None = None) -> CorpusArtifacts:
    """The artifacts for the current corpus state, building them once.

    WS-24 §4a.2: when a previous entry exists for the same database, the
    **per-listing** artifacts of the ids whose ``content_version`` did not
    move are re-used as they are — the same objects, not copies. The global
    ``Bm25Index`` is rebuilt whole, because its document frequencies change
    when any document does.

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
    row_versions: dict[str, str] = {row.id: (row.content_version or "") for row in rows}

    # WS-23b: the bar is mined once at **write** time and stored, so the
    # rebuild reads a column instead of re-mining every description. The
    # mining was 9.5 s of the 32.56 s rebuild — the most expensive
    # per-listing item — and it produced the same answer every time.
    stored_years: dict[str, float | None] = {row.id: row.required_years for row in rows}
    # WS-28: and whether that value was **decided**. NULL alone cannot say:
    # it means "never mined" for a row from before the WS-23b write path, and
    # "mined, the listing states no bar" for a row written after it. Re-mining
    # the second kind yields the same NULL every time — measured at 20.6 s of
    # every cold start across 6,741 such rows, for an answer that cannot change.
    mined_flags: dict[str, bool] = {row.id: bool(row.required_years_mined) for row in rows}

    # WS-24 §4a.2: reuse whatever the previous build of **this database** can
    # still answer. An id whose content_version is unchanged has the same
    # terms, role, rank, phrases and weight total it had a moment ago, so
    # recomputing them is work that cannot produce a different answer. An id
    # that is new, changed, or was never built is not reusable and is
    # computed below.
    prior = _prior_entry(session_factory, fingerprint)
    reusable = _reusable_ids(row_versions, prior)

    lexical_terms: dict[str, list[tuple[str, float]]] = {}
    required_bars: dict[str, float | None] = {}
    roles: dict[str, object] = {}
    seniority: dict[str, int | None] = {}
    phrases: dict[str, list[str]] = {}
    totals: dict[str, float] = {}

    for job in jobs:
        if job.id in reusable:
            terms = prior.lexical_terms.get(job.id, [])
            lexical_terms[job.id] = terms
            totals[job.id] = prior.lexical_weight_totals.get(job.id, _weight_total_for(terms))
            required_bars[job.id] = prior.required_years.get(job.id)
            roles[job.id] = prior.role_classifications.get(job.id)
            seniority[job.id] = prior.seniority_ranks.get(job.id)
            phrases[job.id] = prior.required_phrases.get(job.id, [])
            continue
        terms = _important_terms_for(job)
        lexical_terms[job.id] = terms
        totals[job.id] = _weight_total_for(terms)
        required_bars[job.id] = _bar_for(
            job, stored_years.get(job.id), mined_flags.get(job.id, False)
        )
        roles[job.id] = _role_for(job)
        seniority[job.id] = _rank_for(job)
        phrases[job.id] = _required_phrases(job)

    artifacts = CorpusArtifacts(
        fingerprint=fingerprint,
        jobs=jobs,
        # The index is global: its document frequencies change when any
        # document does, so it is rebuilt whole. This is the half of §4a.2
        # that cannot go incremental, and it is measured at 12.8 s of the
        # 46 s rebuild — the per-listing maps above are the other 33.
        index=Bm25Index(jobs),
        lexical_terms=lexical_terms,
        required_years=required_bars,
        role_classifications=roles,
        lexical_weight_totals=totals,
        required_phrases=phrases,
        seniority_ranks=seniority,
        row_versions=row_versions,
    )
    _CACHE[fingerprint] = artifacts
    while len(_CACHE) > _MAX_ENTRIES:
        _CACHE.popitem(last=False)
    return artifacts


def _prior_entry(session_factory, fingerprint: tuple[str, int, str]) -> CorpusArtifacts | None:
    """The most recent cached build of the **same database**, if any.

    Deliberately not "the most recent entry": the cache holds two states, and
    a second database's entry is not a source of this one's artifacts. The
    database identity is the first component of the fingerprint, and the
    content digest the third — so matching on the first is what makes reuse
    safe across a content change.
    """
    identity = fingerprint[0]
    for key in reversed(_CACHE):
        if key[0] == identity:
            return _CACHE[key]
    return None


def _reusable_ids(
    row_versions: dict[str, str],
    prior: CorpusArtifacts | None,
) -> set[str]:
    """The ids whose per-listing artifacts the previous build still answers.

    An id is reusable when the previous build read it **with the same
    ``content_version``** and produced an entry for each per-listing map. The
    redundancy is not paranoia: a map that is missing an id because the
    previous build's row was evicted mid-build would otherwise hand a later
    search a ``None`` where a computed value belongs.

    **An empty digest is never a match**, not even against another empty one.
    A row written before WS-24 carries ``content_version IS NULL``, and the
    cache stores that as ``""``; two absent digests are not evidence that two
    rows are the same listing, and treating them as equal would re-use an
    artifact for content that may have changed. Such a row is recomputed —
    which is exactly what happened before this incremental path existed, so
    the fallback costs the old behaviour and never a wrong answer. The
    migration `d2e3f4a5b6c7` backfills the column and every write path sets
    it, so this is a guard rather than a common case.

    An id that is absent from ``prior`` or whose version moved is not
    reusable. An id the previous build had and this one does not is simply
    not in ``row_versions``, so it never enters the new maps — which is what
    keeps a deleted listing from coming back.
    """
    if prior is None:
        return set()
    reusable: set[str] = set()
    for job_id, version in row_versions.items():
        if not version:
            # No digest: no evidence. Never reuse.
            continue
        if prior.row_versions.get(job_id) != version:
            continue
        if (
            job_id in prior.lexical_terms
            and job_id in prior.required_years
            and job_id in prior.role_classifications
            and job_id in prior.seniority_ranks
            and job_id in prior.required_phrases
            and job_id in prior.lexical_weight_totals
        ):
            reusable.add(job_id)
    return reusable
