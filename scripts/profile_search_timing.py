"""Where a store-only search spends its time — a diagnostic, not a test.

A search scores **every** stored listing through all eight components. At
several thousand listings that adds up to seconds, and the per-listing work is
where the remaining time goes once the corpus artifacts are cached. This
module times each phase so a change to that path is measured, not guessed.

It profiles the **real** search path (WS-24c). Earlier versions called
``calculate_match`` without the corpus artifacts or the candidate context,
which is a slower path than ``search_stored_jobs`` ever takes — the numbers
reported here were not the numbers a user waits for. The phases below mirror
``src/graph/job_executor.py::search_stored_jobs``.

Run against the local database (read-only):

    env/Scripts/python.exe scripts/profile_search_timing.py [profile_id]

A cold run (a fresh process, nothing cached) also pays the artifacts rebuild;
calling this in one process twice reports the second as warm.
"""

from __future__ import annotations

import sys
import time
from collections.abc import Callable
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.db.profiles import CandidateProfileDB, profile_from_row
from src.db.session import SessionLocal
from src.graph.job_workflow import _get_store
from src.llm.embeddings import build_query_text
from src.matching.corpus_cache import get_corpus_artifacts
from src.matching.engine import CandidateContext, calculate_match
from src.matching.lexical import (
    candidate_lexical_text,
    candidate_tokens,
    lexical_score,
)
from src.matching.scores import ScoreState
from src.rag.chroma_store import candidate_query_text
from src.security.limits import get_limits

DEFAULT_PROFILE_ID = "5e0d5bbebd68"


def timed[T](label: str, fn: Callable[[], T]) -> T:
    start = time.perf_counter()
    result = fn()
    elapsed = time.perf_counter() - start
    print(f"{label:52} {elapsed:7.2f}s", flush=True)
    return result


def main() -> int:
    profile_id = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_PROFILE_ID
    with SessionLocal() as session:
        row = session.get(CandidateProfileDB, profile_id)
        if row is None:
            print(f"profile {profile_id!r} not found")
            return 1
        profile = timed("load profile", lambda: profile_from_row(row))

    limit = get_limits().max_corpus_listings
    artifacts = timed(
        "corpus artifacts (cold = rebuild, warm = cached)",
        lambda: get_corpus_artifacts(session_factory=SessionLocal, limit=limit),
    )
    jobs = artifacts.jobs
    print(f"{'  listings':52} {len(jobs)}")

    store = timed("open the vector store", lambda: _get_store(None))
    query_text = candidate_query_text(profile)

    timed(
        "embed the candidate query (fastembed, never cached)",
        lambda: store._embedding_fn.embed_query(build_query_text(query_text)),
    )
    similarities = timed(
        f"similarities for ALL {len(jobs)} vectors (fetch + cosine)",
        lambda: store.similarities_for_all(query_text),
    )
    print(f"{'  similarities':52} {len(similarities)}")

    token_list = timed("candidate_tokens", lambda: candidate_tokens(profile))
    text = timed("candidate_lexical_text", lambda: candidate_lexical_text(profile))
    context = timed(
        "CandidateContext (per-search constants)",
        lambda: CandidateContext(profile, tokens=token_list, text=text),
    )
    bm25_scores = timed(
        "BM25 score_all (one posting walk)",
        lambda: artifacts.index.score_all(token_list),
    )

    def lexical_only():
        return [
            lexical_score(
                job,
                index=artifacts.index,
                candidate_token_list=token_list,
                candidate_text=text,
                important_terms=artifacts.lexical_terms.get(job.id),
                candidate_token_set=context.token_set,
                lowered_candidate_text=context.lowered_text,
                total_weight=artifacts.lexical_weight_totals.get(job.id),
                required_phrases=artifacts.required_phrases.get(job.id),
                bm25_raw=bm25_scores.get(job.id, 0.0),
            )
            for job in jobs
        ]

    lexical_results = timed(f"lexical_score x {len(jobs)}", lexical_only)

    def match_all():
        out = []
        for job, lexical in zip(jobs, lexical_results, strict=True):
            score = similarities.get(job.id)
            state = None if score is not None else ScoreState.EMBEDDING_UNAVAILABLE
            out.append(
                calculate_match(
                    job,
                    profile,
                    semantic_score=score,
                    semantic_state=state,
                    lexical=lexical,
                    artifacts=artifacts,
                    context=context,
                )
            )
        return out

    matches = timed(f"calculate_match x {len(jobs)} (all 8 components)", match_all)
    timed(
        "rank (stable sort on score desc, id asc)",
        lambda: sorted(matches, key=lambda match: (-match.overall_score, "")),
    )

    ranked = sorted(matches, key=lambda match: -match.overall_score)
    print(f"\ntop overall score: {ranked[0].overall_score:.1f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
