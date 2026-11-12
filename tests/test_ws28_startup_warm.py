"""WS-28 · The rebuild happens once per process, before the first request.

The artifacts cache is per-process, so the first search after a restart paid
the whole 52–65 s rebuild — measured at 58.6 s on a freshly started server,
3.0–3.6 s on the second and third. Warming at startup moves that cost to a
moment when nothing is waiting for it.
"""

from __future__ import annotations


def test_the_warm_builds_the_artifacts(monkeypatch):
    """The warm must go through the same capped call a search uses.

    The cap matters: an uncapped warm would build a bigger corpus than the
    search is allowed to consider, and the first search would then miss the
    cache and rebuild anyway.
    """
    from src.matching import corpus_cache

    called: dict[str, object] = {}

    def fake_get_corpus_artifacts(*, session_factory=None, limit=None):
        called["limit"] = limit
        return "artifacts"

    monkeypatch.setattr(corpus_cache, "get_corpus_artifacts", fake_get_corpus_artifacts)

    from src.main import _warm_corpus_artifacts

    _warm_corpus_artifacts()

    assert called["limit"] is not None, "the warm must honour the corpus cap"


def test_a_failed_warm_does_not_stop_startup(monkeypatch):
    """A corpus the warm cannot read must not prevent the server starting.

    The warm is an optimisation. A locked database or a migration mid-flight
    must leave the app serving, with the first search paying the rebuild as it
    did before.
    """
    from src.matching import corpus_cache

    def boom(*, session_factory=None, limit=None):
        raise RuntimeError("database is locked")

    monkeypatch.setattr(corpus_cache, "get_corpus_artifacts", boom)

    from src.main import _warm_corpus_artifacts

    _warm_corpus_artifacts()  # must not raise


def test_the_warm_reraises_nothing_but_logs(monkeypatch, caplog):
    """A failure is recorded, not silently swallowed."""
    from src.matching import corpus_cache

    def boom(*, session_factory=None, limit=None):
        raise RuntimeError("corpus unreadable")

    monkeypatch.setattr(corpus_cache, "get_corpus_artifacts", boom)

    from src.main import _warm_corpus_artifacts

    with caplog.at_level("ERROR"):
        _warm_corpus_artifacts()

    assert any("warm-up failed" in record.message for record in caplog.records)
