"""Per-process cache of the artifacts a store-only search rebuilds (WS-21 follow-up).

A search re-derives, from scratch on every request, things that do not depend
on the candidate at all: the corpus rows mapped to ``JobListing``, the BM25
index over their text, the weighted important terms of every posting, and
every posting's stated experience bar. Measured on 6,696 listings that is
roughly 40 seconds of the request — pure recomputation.

The cache is keyed by a **fingerprint the corpus maintains itself**: the
database identity, the row count, and the newest ``last_seen_at`` (the column
WS-15 added for corpus eviction, which a refresh moves for every listing it
sees). A refresh therefore invalidates the cache without any explicit call,
and a stale entry can never outlive a corpus change. It holds at most two
entries, and a benign race under the API's thread pool may build an entry
twice — never serve a wrong fingerprint.
"""

from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass, field

from src.db.jobs import JobDB, listing_from_row
from src.jobs.contracts import JobListing
from src.matching.experience import required_years
from src.matching.lexical import Bm25Index, _important_terms

__all__ = [
    "CorpusArtifacts",
    "clear_corpus_cache",
    "corpus_fingerprint",
    "get_corpus_artifacts",
]

#: How many distinct corpus states to keep. Two covers "a refresh landed while
#: a search was running" without letting the cache grow with every edit.
_MAX_ENTRIES = 2


@dataclass
class CorpusArtifacts:
    """Everything a search re-uses across requests (candidate-independent)."""

    fingerprint: tuple[str, int, str | None]
    jobs: list[JobListing] = field(default_factory=list)
    index: Bm25Index | None = None
    #: Weighted important terms per job id (the lexical coverage channel).
    lexical_terms: dict[str, list[tuple[str, float]]] = field(default_factory=dict)
    #: The stated experience bar per job id (``None`` = not stated).
    required_years: dict[str, float | None] = field(default_factory=dict)


_CACHE: OrderedDict[tuple[str, int, str | None], CorpusArtifacts] = OrderedDict()


def clear_corpus_cache() -> None:
    """Drop every cached entry (tests; operational use)."""
    _CACHE.clear()


def _database_identity(session_factory) -> str:
    """A stable name for the database a factory points at."""
    bind = getattr(session_factory, "kw", {}).get("bind")
    url = getattr(bind, "url", None)
    return str(url) if url is not None else "unknown"


def corpus_fingerprint(session_factory) -> tuple[str, int, str | None]:
    """The corpus's own bookkeeping: database, row count, newest last-seen."""
    from sqlalchemy import func, select

    with session_factory() as session:
        row = session.execute(select(func.count(JobDB.id), func.max(JobDB.last_seen_at))).one()
    count = int(row[0] or 0)
    newest = str(row[1]) if row[1] is not None else None
    return (_database_identity(session_factory), count, newest)


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

    artifacts = CorpusArtifacts(
        fingerprint=fingerprint,
        jobs=jobs,
        index=Bm25Index(jobs),
        lexical_terms={job.id: _important_terms(job) for job in jobs},
        required_years={job.id: required_years(job) for job in jobs},
    )
    _CACHE[fingerprint] = artifacts
    while len(_CACHE) > _MAX_ENTRIES:
        _CACHE.popitem(last=False)
    return artifacts
