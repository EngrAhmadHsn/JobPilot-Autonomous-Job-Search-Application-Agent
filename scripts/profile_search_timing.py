"""Where a store-only search spends its time — a diagnostic, not a test.

A search scores **every** stored listing through all eight components, and it
recomputes the corpus-derived artifacts (the listings, the BM25 index, the
role classifications) on every request. At a few thousand listings that adds
up to tens of seconds. This module times each phase so a change to that
architecture is measured, not guessed.

Run against the local database (read-only):

    env/Scripts/python.exe scripts/profile_search_timing.py [profile_id]
"""

from __future__ import annotations

import sys
import time
from collections.abc import Callable
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.db.jobs import JobDB, listing_from_row
from src.db.profiles import CandidateProfileDB, profile_from_row
from src.db.session import SessionLocal
from src.graph.job_workflow import _get_store
from src.llm.embeddings import build_query_text
from src.matching.engine import calculate_match
from src.matching.lexical import (
    Bm25Index,
    candidate_lexical_text,
    candidate_tokens,
    lexical_score,
)
from src.matching.roles import classify_job_role
from src.matching.scores import ScoreState
from src.rag.chroma_store import candidate_query_text
from src.security.limits import get_limits

DEFAULT_PROFILE_ID = "5e0d5bbebd68"


def timed[T](label: str, fn: Callable[[], T]) -> T:
    start = time.perf_counter()
    result = fn()
    elapsed = time.perf_counter() - start
    print(f"{label:46} {elapsed:7.2f}s", flush=True)
    return result


def main() -> int:
    profile_id = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_PROFILE_ID
    with SessionLocal() as session:
        row = session.get(CandidateProfileDB, profile_id)
        if row is None:
            print(f"profile {profile_id!r} not found")
            return 1
        profile = timed("load profile", lambda: profile_from_row(row))

    def load_corpus():
        with SessionLocal() as session:
            rows = session.query(JobDB).limit(get_limits().max_corpus_listings).all()
            return [listing_from_row(r) for r in rows]

    jobs = timed("corpus load + validate (JobListing)", load_corpus)
    print(f"{'  listings':46} {len(jobs)}")

    store = timed("open the vector store", lambda: _get_store(None))
    query_text = candidate_query_text(profile)

    def embed_query():
        return store._embedding_fn.embed_query(build_query_text(query_text))

    timed("embed the candidate query (fastembed)", embed_query)
    similarities = timed(
        f"similarities for ALL {len(jobs)} vectors (fetch + cosine)",
        lambda: store.similarities_for_all(query_text),
    )
    print(f"{'  similarities':46} {len(similarities)}")

    index = timed("BM25 index over the corpus", lambda: Bm25Index(jobs))
    tokens = candidate_tokens(profile)
    candidate_text = candidate_lexical_text(profile)

    def score_all():
        results = []
        for job in jobs:
            score = similarities.get(job.id)
            state = None if score is not None else ScoreState.EMBEDDING_UNAVAILABLE
            lexical = lexical_score(
                job, index=index, candidate_token_list=tokens, candidate_text=candidate_text
            )
            results.append(
                calculate_match(
                    job,
                    profile,
                    semantic_score=score,
                    semantic_state=state,
                    lexical=lexical,
                )
            )
        return results

    matches = timed(f"calculate_match x {len(jobs)} (all 8 components)", score_all)
    timed(
        f"classify_job_role x {len(jobs)} (role taxonomy alone)",
        lambda: [classify_job_role(job) for job in jobs],
    )

    ranked = sorted(matches, key=lambda match: -match.overall_score)
    print(f"\ntop overall score: {ranked[0].overall_score:.1f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
