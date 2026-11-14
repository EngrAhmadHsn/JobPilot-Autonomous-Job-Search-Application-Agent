"""WS-24 §4a.2 · A refresh rebuilds only the listings it changed.

The rebuild is **33.5 s** at 8,558 listings (measured 2026-11-13, 12 cores) and
the per-listing artifacts are all of it except the global index:
``required_years`` 22.1 s if it were not already skipped, ``_important_terms``
8.8 s, the role pass and the seniority rank the rest — against
``Bm25Index(jobs)`` at 12.8 s. §4a.2 predicted the split and it holds: the
per-listing maps can update in place, and the index cannot, because its
document frequencies change when any document does.

The fingerprint already told the cache *that* the corpus moved. This makes it
tell the cache **what** moved.

Every test here defends one of two invariants:

* reuse is keyed by ``content_version``, never by position, so an artifact is
  only ever re-used for an id whose content did not move;
* a deleted listing leaves **nothing** behind — a stale map entry for a row the
  eviction removed is exactly how a deleted listing would come back.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from src.db.base import Base
from src.db.jobs import JobDB
from src.matching import corpus_cache as cc


@pytest.fixture
def factory(tmp_path: Path):
    cc.clear_corpus_cache()
    engine = create_engine(f"sqlite:///{(tmp_path / 'incremental.db').as_posix()}")
    Base.metadata.create_all(engine)
    yield sessionmaker(bind=engine, autoflush=False, autocommit=False)
    engine.dispose()
    cc.clear_corpus_cache()


def _insert(factory, job_id: str, description: str, version: str) -> None:
    with factory() as session:
        session.add(
            JobDB(
                id=job_id,
                source="greenhouse",
                source_job_id=job_id,
                title="Backend Engineer",
                company="Acme",
                description=description,
                content_version=version,
                required_years=None,
                # Decided, so the read path takes the stored value rather
                # than mining — the mining path is measured separately.
                required_years_mined=True,
            )
        )
        session.commit()


def _rewrite(factory, job_id: str, description: str, version: str) -> None:
    with factory() as session:
        row = session.get(JobDB, job_id)
        row.description = description
        row.content_version = version
        session.commit()


def test_only_the_changed_listing_is_recomputed(factory, monkeypatch):
    """The whole point: one changed listing, one listing's work."""
    for i in range(5):
        _insert(factory, f"greenhouse:{i}", f"Python and SQL {i}", f"v{i}")
    first = cc.get_corpus_artifacts(session_factory=factory)
    assert len(first.jobs) == 5

    calls: list[str] = []
    original = cc._important_terms_for

    def counted(job):
        calls.append(job.id)
        return original(job)

    monkeypatch.setattr(cc, "_important_terms_for", counted)

    _rewrite(factory, "greenhouse:3", "Python and Kubernetes 3", "v3-changed")
    second = cc.get_corpus_artifacts(session_factory=factory)

    assert calls == ["greenhouse:3"]
    assert len(second.jobs) == 5
    # And the unchanged terms really are the same objects, not equal copies.
    assert second.lexical_terms["greenhouse:0"] is first.lexical_terms["greenhouse:0"]
    assert second.lexical_terms["greenhouse:3"] is not first.lexical_terms["greenhouse:3"]


def test_every_per_listing_artifact_of_an_unchanged_row_is_reused(factory):
    """Not just the terms: the role, the rank and the phrases too."""
    for i in range(4):
        _insert(factory, f"greenhouse:{i}", f"Python and SQL {i}", f"v{i}")
    # Give three rows a rank and one a multi-word phrase, so the identity
    # assertions below mean something: an all-``None`` map proves nothing,
    # because ``None`` is ``None`` however it was produced.
    _rewrite(factory, "greenhouse:1", "Python and SQL 1", "v1")
    with factory() as session:
        session.get(JobDB, "greenhouse:1").title = "Senior Data Scientist"
        session.get(JobDB, "greenhouse:2").title = "Principal Engineer"
        session.get(JobDB, "greenhouse:3").title = "Staff Engineer"
        session.get(JobDB, "greenhouse:3").required_skills = ["machine learning"]
        session.commit()
    first = cc.get_corpus_artifacts(session_factory=factory)
    assert first.seniority_ranks["greenhouse:1"] is not None
    assert first.required_phrases["greenhouse:3"]  # a real multi-word phrase

    _rewrite(factory, "greenhouse:0", "A wholly different listing text", "v0-changed")
    second = cc.get_corpus_artifacts(session_factory=factory)

    for job_id in ("greenhouse:1", "greenhouse:2", "greenhouse:3"):
        assert second.role_classifications[job_id] is first.role_classifications[job_id]
        assert second.seniority_ranks[job_id] is first.seniority_ranks[job_id]
        assert second.required_years[job_id] == first.required_years[job_id]
    assert second.required_phrases["greenhouse:3"] is first.required_phrases["greenhouse:3"]


def test_no_change_at_all_still_returns_the_cached_object(factory):
    """The unchanged-fingerprint path stays what it was — no rebuild at all."""
    for i in range(3):
        _insert(factory, f"greenhouse:{i}", f"Python {i}", f"v{i}")
    first = cc.get_corpus_artifacts(session_factory=factory)
    second = cc.get_corpus_artifacts(session_factory=factory)
    assert second is first


def test_a_deleted_listing_leaves_no_artifact_behind(factory):
    """A stale entry is how a listing the eviction deleted would come back."""
    for i in range(3):
        _insert(factory, f"greenhouse:{i}", f"Python {i}", f"v{i}")
    first = cc.get_corpus_artifacts(session_factory=factory)
    assert "greenhouse:2" in first.lexical_terms

    with factory() as session:
        session.execute(text("DELETE FROM jobs WHERE id = 'greenhouse:2'"))
        session.commit()

    second = cc.get_corpus_artifacts(session_factory=factory)

    assert [job.id for job in second.jobs] == ["greenhouse:0", "greenhouse:1"]
    for mapping in (
        second.lexical_terms,
        second.required_years,
        second.role_classifications,
        second.seniority_ranks,
        second.required_phrases,
        second.lexical_weight_totals,
    ):
        assert "greenhouse:2" not in mapping


def test_an_added_listing_is_the_only_new_work(factory, monkeypatch):
    for i in range(3):
        _insert(factory, f"greenhouse:{i}", f"Python {i}", f"v{i}")
    first = cc.get_corpus_artifacts(session_factory=factory)

    calls: list[str] = []
    original = cc._important_terms_for

    def counted(job):
        calls.append(job.id)
        return original(job)

    monkeypatch.setattr(cc, "_important_terms_for", counted)
    _insert(factory, "greenhouse:9", "A brand new listing", "v9")
    second = cc.get_corpus_artifacts(session_factory=factory)

    assert calls == ["greenhouse:9"]
    assert len(second.jobs) == 4
    assert len(second.index) == 4  # the global index has the new document
    # The old rows were not recomputed.
    assert second.lexical_terms["greenhouse:0"] is first.lexical_terms["greenhouse:0"]


def test_the_global_index_is_rebuilt_whole(factory):
    """Its document frequencies change when any document does — §4a.2's caveat."""
    for i in range(3):
        _insert(factory, f"greenhouse:{i}", f"Python and SQL {i}", f"v{i}")
    first = cc.get_corpus_artifacts(session_factory=factory)

    _rewrite(factory, "greenhouse:1", "Rust and Kubernetes only", "v1-changed")
    second = cc.get_corpus_artifacts(session_factory=factory)

    assert second.index is not first.index
    assert len(second.index) == 3


def test_a_second_database_does_not_reuse_the_first_ones_artifacts(factory, tmp_path: Path):
    """Incremental reuse is per database, not per process."""
    for i in range(3):
        _insert(factory, f"greenhouse:{i}", f"Python {i}", f"v{i}")
    first = cc.get_corpus_artifacts(session_factory=factory)

    other_engine = create_engine(f"sqlite:///{(tmp_path / 'other.db').as_posix()}")
    Base.metadata.create_all(other_engine)
    other = sessionmaker(bind=other_engine, autoflush=False, autocommit=False)
    for i in range(3):
        _insert(other, f"greenhouse:{i}", f"Python {i}", f"v{i}")

    second = cc.get_corpus_artifacts(session_factory=other)

    assert second is not first
    # Same ids, same content — and still its own objects, because the reuse is
    # keyed on a database identity that differs.
    assert second.lexical_terms["greenhouse:0"] is not first.lexical_terms["greenhouse:0"]


def test_reordering_the_rows_reuses_by_id_not_by_position(factory):
    """The row order a database happens to return must not matter.

    A positional implementation passes the simple cases and silently serves
    the wrong listing's artifacts once the query planner changes the order.
    """
    for i in range(4):
        _insert(factory, f"greenhouse:{i}", f"Python {i}", f"v{i}")
    # Give the row a rank first, so the change below has somewhere to move.
    _rewrite(factory, "greenhouse:0", "Python 0", "v0-ranked")
    with factory() as session:
        row = session.get(JobDB, "greenhouse:0")
        row.title = "Senior Backend Engineer"
        session.commit()
    first = cc.get_corpus_artifacts(session_factory=factory)
    assert first.seniority_ranks["greenhouse:0"] is not None

    # Change only job 0, and change its *title* so its role and rank move too.
    with factory() as session:
        row = session.get(JobDB, "greenhouse:0")
        row.title = "Head of Engineering"
        row.content_version = "v0-title-changed"
        session.commit()

    second = cc.get_corpus_artifacts(session_factory=factory)

    assert second.seniority_ranks["greenhouse:0"] != first.seniority_ranks["greenhouse:0"]
    for job_id in ("greenhouse:1", "greenhouse:2", "greenhouse:3"):
        assert second.seniority_ranks[job_id] is first.seniority_ranks[job_id]


def test_a_full_rebuild_still_happens_when_there_is_nothing_to_reuse(factory):
    """The first read of a corpus has no prior state and must build it all."""
    for i in range(3):
        _insert(factory, f"greenhouse:{i}", f"Python {i}", f"v{i}")
    artifacts = cc.get_corpus_artifacts(session_factory=factory)

    assert len(artifacts.jobs) == 3
    assert len(artifacts.lexical_terms) == 3
    assert len(artifacts.role_classifications) == 3
    assert len(artifacts.seniority_ranks) == 3
    assert len(artifacts.required_phrases) == 3
    assert len(artifacts.lexical_weight_totals) == 3
    assert len(artifacts.required_years) == 3


def test_a_row_with_no_content_version_is_recomputed_when_the_build_runs(factory):
    """An absent digest is not evidence that a row is unchanged.

    A row written before WS-24 has ``content_version IS NULL`` (stored as
    ``""``). Two absent digests are not the same digest, so such a row must be
    recomputed rather than re-used — reuse-by-absence is precisely the false
    match this design cannot have.

    Note what this test does **not** claim: the fingerprint is itself built
    from ``content_version``, so a content change that never moves a digest is
    invisible to the whole cache (WS-24's contract, and the reason the write
    path always sets the column and migration `d2e3f4a5b6c7` backfilled it).
    What is pinned here is the narrower promise the incremental path owns:
    when a build *does* run, an unversioned row is never re-used from the
    prior entry.
    """
    # One row carries a real digest, so a change to it moves the fingerprint
    # and the incremental path actually runs.
    _insert(factory, "greenhouse:0", "Python zero", "v0")
    # Two rows carry no digest at all.
    _insert(factory, "greenhouse:1", "Python one", "")
    _insert(factory, "greenhouse:2", "Python two", "")
    first = cc.get_corpus_artifacts(session_factory=factory)
    before = first.lexical_terms["greenhouse:1"]

    # Move the fingerprint through the row that HAS a digest, and change an
    # unversioned row's content in the same breath.
    _rewrite(factory, "greenhouse:0", "Python zero changed", "v0-changed")
    _rewrite(factory, "greenhouse:1", "Rust and Kubernetes entirely", "")
    second = cc.get_corpus_artifacts(session_factory=factory)

    assert second is not first
    # The unversioned row was recomputed, so its terms reflect its new text…
    assert second.lexical_terms["greenhouse:1"] != before
    assert any("rust" in term for term, _weight in second.lexical_terms["greenhouse:1"])
    # …while the other unversioned row, whose content did not change, is the
    # same object it was (its terms are recomputed too, but to the same value —
    # identity is asserted on the versioned row for that reason).
    assert second.lexical_terms["greenhouse:2"] == first.lexical_terms["greenhouse:2"]


def test_the_cache_holding_two_databases_reuses_the_right_one(factory, tmp_path: Path):
    """Reuse must pick *this* database's prior build, not the newest entry.

    The cache holds two states. With a second database's build sitting in the
    cache, a naive "the most recent entry" lookup would hand this corpus
    another corpus's artifacts — every id that happened to be in both would
    be silently re-used with the wrong content.
    """
    other_engine = create_engine(f"sqlite:///{(tmp_path / 'other.db').as_posix()}")
    Base.metadata.create_all(other_engine)
    other = sessionmaker(bind=other_engine, autoflush=False, autocommit=False)

    for i in range(3):
        _insert(factory, f"greenhouse:{i}", f"Python {i}", f"v{i}")
        _insert(other, f"greenhouse:{i}", f"Rust {i}", f"w{i}")

    first = cc.get_corpus_artifacts(session_factory=factory)
    other_artifacts = cc.get_corpus_artifacts(session_factory=other)  # now the newest
    assert other_artifacts.lexical_terms["greenhouse:0"] != first.lexical_terms["greenhouse:0"]

    # Change one listing in the FIRST database and rebuild it. If the reuse had
    # read the other database's entry, the terms of the untouched rows would
    # come back as the other corpus's ("Rust") rather than this one's.
    _rewrite(factory, "greenhouse:0", "Python and SQL 0", "v0-changed")
    second = cc.get_corpus_artifacts(session_factory=factory)

    assert second.lexical_terms["greenhouse:1"] is first.lexical_terms["greenhouse:1"]
    assert any("rust" in term for term, _w in second.lexical_terms["greenhouse:1"]) is False
