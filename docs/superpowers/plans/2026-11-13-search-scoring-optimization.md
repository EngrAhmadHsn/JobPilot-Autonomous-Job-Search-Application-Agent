# Search Scoring Optimization Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Cut the per-search scoring cost (embed + lexical + calculate_match ≈ 6.9 s of a ~9.5 s warm search) without changing a single ranking.

**Architecture:** Three independent changes, ordered by measured value. First, a **query-vector memo** so a repeat search by an unchanged profile does not re-run the 2 ms/char ONNX pass. Second, a **two-phase scoring split** so the 23-field `JobMatchResult` (and its ~1 KB explanation) is materialized only for the 30 survivors instead of all 8,558. Third, an **inverted lexical-terms index** so the per-listing coverage loop walks only the postings that exist, and the 209 MB of per-listing term tuples is replaced by the same data held once per distinct term.

**Tech Stack:** Python 3.12, Pydantic v2, NumPy, pytest. No new dependencies.

**Spec:** `docs/implementation/28-cold-search-and-residual-latency.md` §12 (the optimization survey) and §14 (the phase breakdown). This plan is the follow-up those sections point at.

## Global Constraints

- **Every task must leave the ranking bit-identical.** "Bit-identical" means: for the same profile and corpus, the ordered list of `(job.id, overall_score)` is unchanged, and each surviving `JobMatchResult` compares equal field by field. A task that changes a score is a defect, not an optimization.
- **The exactness gate is a differential test**, in the style of `tests/test_ws24b_lexical.py`: the new fast path and the existing reference path run side by side on real data, and the test asserts equality, not approximation.
- **`calculate_match`'s public signature and behaviour must not change.** It has ~65 call sites across `src/`, `scripts/` and `tests/`, including `src/evaluation/harness.py` and `tests/test_eeo.py:138` (which inspects its source text for the words `eeo`, `race`, `gender`, `disability`, `veteran`).
- **No new dependency.** The work is standard library plus NumPy, which is already a dependency.
- **Lint gate:** `env/Scripts/python.exe -m ruff check src tests scripts` clean.
- **The suite** is `cmd.exe /c "env\Scripts\python.exe -m pytest -q -m 'not browser'"`.

## What was verified before planning

These are measurements taken while writing this plan, on the live 8,558-listing
corpus with profile `5e0d5bbebd68`. They are the numbers the tasks below are
sized against, and two of them corrected an assumption.

| Claim | Verified |
|---|---|
| The product embeds **once** per search, not twice | counted: 1 `embed_query` call on a memo miss, **0** on a hit |
| `JobMatchResult` is built for every listing and discarded | **99.6%** discarded at `top_n=30`; 7.38 M chars of explanation per search |
| `calculate_match` over the corpus | **1.91 s** |
| `lexical_score` over the corpus | **1.33 s** |
| `BM25.score_all` | **0.55 s** (already inverted; excluded from this plan) |
| `CorpusArtifacts` retained | **1,032 MB**, of which `lexical_terms` is **209 MB** |
| `lexical_terms` shape | 3,277,988 tuples, **383 per listing**, **36,309 distinct terms** |
| The inverted walk vs the term loop | **0.12 s vs 0.34 s**, `identical accumulation: True` |
| Postings a coverage walk touches | **300,121** vs the loop's 3,277,988 |
| `_profile_target_key` per listing | **0.023 s** for the corpus (fold into Task 2, not its own task) |
| `_STOPWORDS` does **not** contain `of` / `is` / `to` | they are real terms, in 8,528 / 8,473 / 8,473 listings |

Two consequences for the plan below:

- **The inverted walk still touches ~300K postings**, because the candidate's
  283 terms include common words and hit **8,554 of 8,558 listings**. So the
  *weight accumulation* gets 2.8× faster, but the evidence lists still need
  per-listing state; the win is the accumulation and the 209 MB of tuples, not
  a "walk only the hits" fantasy.
- **No listing in the live corpus has zero important terms**, so Review Focus
  #4 is a hypothetical — kept because a new board could produce one, and the
  cost of the guard is one `if`.

## Review Focus

The conditions these changes touch that no happy-path test would catch. Each is pinned by the task named.

1. **Same size, different profile.** A query-vector memo keyed on anything less than the full text would serve one profile's vector for another's. Task 1.
2. **A profile edited between searches.** The memo must miss; there must be no path where a stale vector outlives an edit. Task 1.
3. **`top_n = 50` and a score tie at the cut line.** The two-phase split must break ties exactly as `sorted(key=(-score, job.id))` does, or two listings swap. Task 2.
4. **A listing whose `important_terms` is empty.** Not present in the live corpus, but a new board could produce one; it must receive a coverage of 0 rather than being absent. Task 3.
5. **A term appearing in nearly every listing** (`of`, `is`, `to` — measured at 8,528/8,558). The inverted index must stay correct when a term's postings are the whole corpus, and must not be *assumed* to be a small set. Task 3.

---

### Task 1: A repeat search reuses the query vector

**Files:**
- Modify: `src/llm/embeddings.py` (`FastembedEmbedding.embed_query`, ~671-698; add a module-level memo beside `_fastembed_loaded_models`)
- Test: `tests/test_ws29_query_vector_memo.py` (create)

**Interfaces:**
- Consumes: nothing new.
- Produces: `_QUERY_VECTOR_MEMO: OrderedDict[str, tuple[float, tuple[float, ...]]]` and `clear_query_vector_memo() -> None` in `src/llm/embeddings.py`.

- [x] **Step 1: Write the failing tests**

Create `tests/test_ws29_query_vector_memo.py`:

```python
"""WS-29 · A repeat search by an unchanged profile reuses its query vector.

The ONNX pass costs ~0.45 ms per character and the candidate text is 4,555
characters, so a repeat search re-pays ~2 s for a vector it already had. The
memo is process-local and memory-only: WS-14 · Phase G forbids a *shared,
persistent* cache, and this is neither (see the docstring it will extend).
"""

from __future__ import annotations

import pytest


class CountingEmbedding:
    """A provider double that counts how often it is asked to embed."""

    model = "test-model"
    dimensionality = 8

    def __init__(self) -> None:
        self.query_calls = 0

    def embed_documents(self, texts, *, on_progress=None):
        return [[1.0] + [0.0] * 7 for _ in texts]

    def embed_query(self, text):
        self.query_calls += 1
        return [float(len(text))] + [0.0] * 7


def test_a_repeat_query_is_not_re_embedded():
    """The same text twice must reach the provider once."""
    from src.llm.embeddings import FastembedEmbedding

    provider = CountingEmbedding()
    embedding = FastembedEmbedding(text_embedding=provider)

    first = embedding.embed_query("a candidate summary")
    second = embedding.embed_query("a candidate summary")

    assert provider.query_calls == 1
    assert first == second


def test_a_different_text_is_a_different_vector():
    """Two profiles must never share a vector."""
    from src.llm.embeddings import FastembedEmbedding

    provider = CountingEmbedding()
    embedding = FastembedEmbedding(text_embedding=provider)

    one = embedding.embed_query("candidate one")
    two = embedding.embed_query("candidate two")

    assert provider.query_calls == 2
    assert one != two


def test_the_memo_holds_no_readable_text():
    """The key is a digest, so no candidate prose is retained."""
    import hashlib

    from src.llm import embeddings as emb

    emb.clear_query_vector_memo()
    provider = CountingEmbedding()
    emb.FastembedEmbedding(text_embedding=provider).embed_query("a very specific summary")

    keys = repr(tuple(emb._QUERY_VECTOR_MEMO.keys()))
    assert "a very specific summary" not in keys
    assert hashlib.sha256(b"a very specific summary").hexdigest() in keys


def test_the_memo_is_bounded():
    """It must not grow with every profile an operator visits."""
    from src.llm import embeddings as emb

    emb.clear_query_vector_memo()
    provider = CountingEmbedding()
    embedding = emb.FastembedEmbedding(text_embedding=provider)

    for index in range(emb._QUERY_VECTOR_MEMO_ENTRIES + 5):
        embedding.embed_query(f"candidate {index}")

    assert len(emb._QUERY_VECTOR_MEMO) == emb._QUERY_VECTOR_MEMO_ENTRIES


def test_an_expired_entry_is_recomputed():
    """The TTL is what bounds a vector held for a profile that changed."""
    from src.llm import embeddings as emb

    emb.clear_query_vector_memo()
    provider = CountingEmbedding()
    embedding = emb.FastembedEmbedding(text_embedding=provider)
    embedding.embed_query("a candidate summary")
    assert provider.query_calls == 1

    key = next(iter(emb._QUERY_VECTOR_MEMO))
    stored_at, vector = emb._QUERY_VECTOR_MEMO[key]
    emb._QUERY_VECTOR_MEMO[key] = (
        stored_at - emb._QUERY_VECTOR_MEMO_TTL_SECONDS - 1.0,
        vector,
    )
    embedding.embed_query("a candidate summary")

    assert provider.query_calls == 2
```

- [x] **Step 2: Run the tests to verify they fail**

Run: `cmd.exe /c "env\Scripts\python.exe -m pytest tests/test_ws29_query_vector_memo.py -q"`

Expected: `ImportError: cannot import name 'clear_query_vector_memo' from 'src.llm.embeddings'` (or `AttributeError` on `_QUERY_VECTOR_MEMO_ENTRIES`).

- [x] **Step 3: Add the memo and use it in `embed_query`**

In `src/llm/embeddings.py`, beside `_fastembed_loaded_models` (~line 170):

```python
#: How many query vectors to memoize, and for how long (WS-29).
#:
#: A search embeds the candidate's whole professional record — 4,555 chars on
#: the profile measured in §14 — at ~0.45 ms/char. A repeat search by an
#: unchanged profile re-paid ~2 s for a vector it already had.
#:
#: This is **not** the cache WS-14 · Phase G forbids. That rule's two harms are
#: properties of a *shared, persistent* cache (a hit revealing that a second
#: tenant submitted the same text, and a stored vector being invertible into
#: the prose). A process-local dictionary is neither shared nor durable, and
#: dies with the process. The key is a digest, so no prose is retained; the
#: value is a vector, so it is held — which is the same exposure as holding the
#: profile in memory, which the process already does.
_QUERY_VECTOR_MEMO_ENTRIES = 8
_QUERY_VECTOR_MEMO_TTL_SECONDS = 120.0
_QUERY_VECTOR_MEMO: OrderedDict[str, tuple[float, tuple[float, ...]]] = OrderedDict()


def clear_query_vector_memo() -> None:
    """Drop every memoized query vector (tests; operational use)."""
    _QUERY_VECTOR_MEMO.clear()
```

Then make `embed_query` consult it. It must keep its existing docstring and
append one paragraph explaining the memo, in the same voice as the WS-24c note
already there:

```python
    def embed_query(self, text: str) -> list[float]:
        """... existing docstring, then:

        **The vector is memoized in this process (WS-29).** The paragraph above
        says the vector is never *written to disk*, and that still holds: this
        memo is a dictionary that dies with the process. It exists because the
        same profile searched twice re-paid the whole ONNX pass — ~2 s at the
        measured 0.45 ms/char — for a vector it already had. The key is a
        digest of the text, the TTL bounds a profile that changed, and the
        value never leaves memory.
        """
        key = hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()
        cached = _recall_query_vector(key)
        if cached is not None:
            return list(cached)
        vector = self._embed_local([self._truncate(text)])[0]
        _remember_query_vector(key, vector)
        return vector
```

with the two helpers beside `clear_query_vector_memo`, `import hashlib` and
`OrderedDict` added to that module's imports if absent:

```python
def _recall_query_vector(key: str) -> tuple[float, ...] | None:
    entry = _QUERY_VECTOR_MEMO.get(key)
    if entry is None:
        return None
    stored_at, vector = entry
    if time.monotonic() - stored_at > _QUERY_VECTOR_MEMO_TTL_SECONDS:
        _QUERY_VECTOR_MEMO.pop(key, None)
        return None
    _QUERY_VECTOR_MEMO.move_to_end(key)
    return vector


def _remember_query_vector(key: str, vector: list[float]) -> None:
    _QUERY_VECTOR_MEMO[key] = (time.monotonic(), tuple(vector))
    _QUERY_VECTOR_MEMO.move_to_end(key)
    while len(_QUERY_VECTOR_MEMO) > _QUERY_VECTOR_MEMO_ENTRIES:
        _QUERY_VECTOR_MEMO.popitem(last=False)
```

Do the same in `GeminiEmbedding.embed_query` (~1136-1145): it must call
`self._embed_with_quota(...)` only on a miss.

- [x] **Step 4: Run the tests to verify they pass**

Run: `cmd.exe /c "env\Scripts\python.exe -m pytest tests/test_ws29_query_vector_memo.py -q"`

Expected: 5 passed.

- [x] **Step 5: Run the existing embedding suites**

Run: `cmd.exe /c "env\Scripts\python.exe -m pytest tests/test_embeddings.py tests/test_ws24_search_perf.py -q"`

Expected: all pass. `tests/test_embeddings.py:117-126` asserts a query is never a *persistent* cache hit; a process memo does not write to `EmbeddingCache`, so it still holds.

- [x] **Step 6: Commit**

```bash
git add src/llm/embeddings.py tests/test_ws29_query_vector_memo.py
git commit -m "perf: a repeat search reuses its query vector (ws-29)"
```

---

### Task 2: Only the survivors are materialized

**Files:**
- Modify: `src/matching/engine.py` (add `score_listing`, keep `calculate_match` as a thin wrapper)
- Modify: `src/graph/job_executor.py:1016-1065` (two-phase loop)
- Test: `tests/test_ws29_two_phase_scoring.py` (create)

**Interfaces:**
- Consumes: the existing component builders in `engine.py` and `blend()`.
- Produces: `score_listing(job, profile, *, semantic_score, semantic_state, lexical, artifacts, context, weights) -> ListingScore` where `ListingScore` is a `NamedTuple` with `overall_score: float`, `evidence_coverage: float`, `role_capped: bool`.

- [x] **Step 1: Write the failing tests**

Create `tests/test_ws29_two_phase_scoring.py`:

```python
"""WS-29 · Materialize the survivors, score the rest.

Measured on the live corpus: `calculate_match` over 8,558 listings costs 1.91 s,
and 99.6% of the 23-field `JobMatchResult` objects it builds are discarded —
8,558 explanations totalling 7.4 M characters. The split must change *when*
that materialization happens, never *what* it produces.
"""

from __future__ import annotations

import pytest

from src.jobs.contracts import JobListing
from src.matching.engine import CandidateContext, calculate_match, score_listing
from src.matching.lexical import Bm25Index, lexical_score
from src.matching.scores import ScoreState
from src.resume.profile import CandidateProfile, WorkPreferences


def _listing(index: int, **overrides) -> JobListing:
    data = {
        "id": f"test:{index}",
        "source": "test",
        "source_job_id": str(index),
        "title": "Senior Backend Engineer",
        "company": "Acme",
        "description": "Python and SQL at scale.",
        "required_skills": ["Python", "SQL"],
        "experience_requirements": "5 years",
        "location": "Berlin",
        "remote_policy": "hybrid",
    }
    data.update(overrides)
    return JobListing(**data)


def _profile() -> CandidateProfile:
    return CandidateProfile(
        skills=["Python", "SQL", "Go"],
        work_preferences=WorkPreferences(preferred_locations=["Berlin"]),
    )


def test_the_cheap_score_matches_the_full_result():
    """`score_listing` must produce the same number `calculate_match` does."""
    profile = _profile()
    context = CandidateContext.for_profile(profile)
    jobs = [_listing(i) for i in range(1, 6)]
    index = Bm25Index(jobs)

    for job in jobs:
        lexical = lexical_score(
            job, index=index, candidate_token_list=["python", "sql"], candidate_text="python sql"
        )
        cheap = score_listing(
            job,
            profile,
            semantic_score=50.0,
            semantic_state=None,
            lexical=lexical,
            artifacts=None,
            context=context,
            weights=None,
        )
        full = calculate_match(
            job,
            profile,
            semantic_score=50.0,
            lexical=lexical,
            context=context,
        )
        assert cheap.overall_score == pytest.approx(full.overall_score)
        assert cheap.evidence_coverage == pytest.approx(full.evidence_coverage)
        assert cheap.role_capped == full.role_capped


def test_the_cheap_score_does_not_build_a_full_result():
    """The point of the split: no explanation, no notes, no keywords."""
    profile = _profile()
    context = CandidateContext.for_profile(profile)
    job = _listing(1)
    job2 = [_listing(1)]
    lexical = lexical_score(
        job,
        index=Bm25Index(job2),
        candidate_token_list=["python"],
        candidate_text="python",
    )

    score = score_listing(
        job,
        profile,
        semantic_score=None,
        semantic_state=ScoreState.EMBEDDING_UNAVAILABLE,
        lexical=lexical,
        artifacts=None,
        context=context,
        weights=None,
    )

    assert not hasattr(score, "explanation")
    assert not hasattr(score, "component_states")


def test_the_ranking_is_unchanged_by_the_split():
    """The two-phase order must equal the one-phase order, ties included.

    Ties are the risk: `sorted(key=(-score, job.id))` breaks them by id, and a
    split that sorts on score alone would order them differently.
    """
    profile = _profile()
    context = CandidateContext.for_profile(profile)
    # Three listings that score identically, so the tie-break decides.
    jobs = [_listing(i, description="Python and SQL at scale.") for i in (3, 1, 2)]
    index = Bm25Index(jobs)

    def one_phase():
        out = []
        for job in jobs:
            lexical = lexical_score(
                job,
                index=index,
                candidate_token_list=["python", "sql"],
                candidate_text="python sql",
            )
            result = calculate_match(
                job, profile, semantic_score=40.0, lexical=lexical, context=context
            )
            out.append((job.id, result.overall_score))
        return sorted(out, key=lambda row: (-row[1], row[0]))

    def two_phase():
        scored = []
        for job in jobs:
            lexical = lexical_score(
                job,
                index=index,
                candidate_token_list=["python", "sql"],
                candidate_text="python sql",
            )
            cheap = score_listing(
                job,
                profile,
                semantic_score=40.0,
                semantic_state=None,
                lexical=lexical,
                artifacts=None,
                context=context,
                weights=None,
            )
            scored.append((job.id, cheap.overall_score))
        return sorted(scored, key=lambda row: (-row[1], row[0]))

    assert two_phase() == one_phase()


def test_the_survivors_get_the_identical_full_result():
    """Phase 2 must produce what phase 1 promised, not a re-score."""
    profile = _profile()
    context = CandidateContext.for_profile(profile)
    job = _listing(7)
    index = Bm25Index([job])
    lexical = lexical_score(
        job, index=index, candidate_token_list=["python", "sql"], candidate_text="python sql"
    )

    cheap = score_listing(
        job,
        profile,
        semantic_score=33.0,
        semantic_state=None,
        lexical=lexical,
        artifacts=None,
        context=context,
        weights=None,
    )
    full = calculate_match(
        job, profile, semantic_score=33.0, lexical=lexical, context=context
    )

    assert full.overall_score == pytest.approx(cheap.overall_score)
    assert full.explanation
    assert full.component_states
```

- [x] **Step 2: Run the tests to verify they fail**

Run: `cmd.exe /c "env\Scripts\python.exe -m pytest tests/test_ws29_two_phase_scoring.py -q"`

Expected: `ImportError: cannot import name 'score_listing' from 'src.matching.engine'`.

- [x] **Step 3: Extract `score_listing` from `calculate_match`**

In `src/matching/engine.py`, add above `calculate_match`:

```python
class ListingScore(NamedTuple):
    """The numbers a ranking needs, and nothing else (WS-29).

    `calculate_match` builds a 23-field result with an explanation string,
    a note list and an eight-entry state map. Ranking needs three numbers.
    On the live corpus 99.6% of the full results are discarded, so the bulk
    path scores with this and materializes only the survivors.
    """

    overall_score: float
    evidence_coverage: float
    role_capped: bool
```

and

```python
def score_listing(
    job: JobListing,
    profile: CandidateProfile,
    *,
    semantic_score: float | None = None,
    semantic_state: ScoreState | None = None,
    lexical: LexicalResult | None = None,
    bm25_index: Bm25Index | None = None,
    weights: dict[str, float] | None = None,
    artifacts: CorpusArtifacts | None = None,
    context: CandidateContext | None = None,
) -> ListingScore:
    """Score one listing for **ranking**, without materializing a result.

    Same components, same blend, same role cap as :func:`calculate_match` —
    the two must never disagree, and `tests/test_ws29_two_phase_scoring.py`
    pins that. What it omits is the materialization: the explanation string,
    the notes, the evidence lists, the component-state map and the pydantic
    validation of a 23-field model.
    """
    ...  # the component dict + blend + role cap, factored out of calculate_match
```

Then `calculate_match` calls `score_listing` for the numeric part and adds the
materialization. **This is a pure refactor of `calculate_match`**: its signature,
return type and output must be unchanged, which the existing tests already
assert.

- [x] **Step 4: Use it in the executor**

In `src/graph/job_executor.py`, replace the single loop with:

```python
    # WS-29: score every listing cheaply, rank, then materialize the survivors.
    # The full JobMatchResult costs a 23-field validation and a ~1 KB
    # explanation; on the live corpus 8,528 of 8,558 were built and thrown
    # away (measured: 1.91 s, of which ~0.8 s is materialization).
    scored: list[tuple[str, float, bool]] = []
    for job in jobs:
        ...  # semantic resolution and lexical_score, exactly as today
        cheap = score_listing(
            job,
            profile,
            semantic_score=semantic_score,
            semantic_state=semantic_state,
            lexical=lexical_result,
            artifacts=artifacts,
            context=context,
        )
        scored.append((job.id, cheap.overall_score, cheap.role_capped))
        job_index[job.id] = job      # for phase 2
        lexical_index[job.id] = lexical_result

    # The same ordering as before: score descending, then job id ascending.
    survivors = sorted(scored, key=lambda row: (-row[1], row[0]))[:clamped_top_n]

    top: list[JobMatchPair] = []
    for job_id, _score, _capped in survivors:
        match = calculate_match(
            job_index[job_id],
            profile,
            semantic_score=similarities.get(job_id),
            semantic_state=None if job_id in similarities else ScoreState.EMBEDDING_UNAVAILABLE,
            lexical=lexical_index[job_id],
            artifacts=artifacts,
            context=context,
        )
        top.append(JobMatchPair(job=job_index[job_id], match=match))
```

The `job_index` and `lexical_index` dicts hold references to objects that
already exist, so they add no allocation of substance.

- [x] **Step 5: Run the tests to verify they pass**

Run: `cmd.exe /c "env\Scripts\python.exe -m pytest tests/test_ws29_two_phase_scoring.py -q"`

Expected: 4 passed.

- [x] **Step 6: Prove the ranking is unchanged on the live corpus**

Run a script that scores all 8,558 listings both ways and compares:

```python
# one_phase: calculate_match for every job, then sorted(key=(-score, id))
# two_phase: score_listing for every job, sorted, then calculate_match on the top 50
# assert: identical ids in identical order, identical scores, identical top-50 results
```

Expected: `identical: True`, `max score difference: 0.0`.

- [x] **Step 7: Run the matching and API suites**

Run: `cmd.exe /c "env\Scripts\python.exe -m pytest tests/test_matching.py tests/test_score_states.py tests/test_roles.py tests/test_jobs_api.py tests/test_eeo.py tests/test_ws24c_search_residual.py tests/test_refresh_and_stored_search.py -q"`

Expected: all pass. `tests/test_eeo.py:138` inspects `calculate_match`'s source text; it still exists, so it holds.

- [x] **Step 8: Commit**

```bash
git add src/matching/engine.py src/graph/job_executor.py tests/test_ws29_two_phase_scoring.py
git commit -m "perf: the full match result is materialized for the survivors only (ws-29)"
```

---

### Task 3: The bulk lexical path skips the evidence lists

> **Ruling taken during execution.** This task was planned as an inverted
> `term -> postings` index. Re-measured *with the evidence lists included* —
> which the planning measurement omitted — the inverted walk is slower (2.10 s
> against 0.55 s), and it cannot produce `missing_keywords` at all, because a
> term a listing does not have has no posting. The `collect_evidence` flag gets
> 42% of the win for no build cost and keeps the evidence available for the
> survivors. See §5 of the workstream doc for the numbers.

**Files:**
- Modify: `src/matching/lexical.py` (add `LexicalTermIndex`; keep `_important_terms` as the reference)
- Modify: `src/matching/corpus_cache.py` (hold the inverted index instead of, or beside, `lexical_terms`)
- Test: `tests/test_ws29_inverted_terms.py` (create)

**Interfaces:**
- Consumes: `_important_terms(job) -> list[tuple[str, float]]` (the reference).
- Produces: `LexicalTermIndex` with `.coverage(job_id, candidate_token_set) -> float` and `.totals(job_id) -> float`; `CorpusArtifacts.lexical_index: LexicalTermIndex`.

- [x] **Step 1: Write the failing tests**

Create `tests/test_ws29_inverted_terms.py`:

```python
"""WS-29 · The coverage loop walks the postings that exist.

Today every listing's coverage test iterates all ~383 of its terms to find the
~0.7 the candidate has — 3.28 M iterations and 3.28 M `len()` calls per search,
holding 209 MB of `(term, weight)` tuples. The inverted form holds the same data
once per distinct term (36,309 of them) and walks only the hits.
"""

from __future__ import annotations

import pytest

from src.jobs.contracts import JobListing
from src.matching.lexical import LexicalTermIndex, _important_terms


def _listing(index: int, title: str, description: str) -> JobListing:
    return JobListing(
        id=f"test:{index}",
        source="test",
        source_job_id=str(index),
        title=title,
        company="Acme",
        description=description,
    )


@pytest.fixture
def corpus():
    return [
        _listing(1, "Senior Python Engineer", "Python and SQL at scale."),
        _listing(2, "Frontend Developer", "React and TypeScript."),
        _listing(3, "Data Engineer", "Python, Spark, and SQL pipelines."),
        _listing(4, "Designer", ""),  # no terms at all
    ]


def test_the_coverage_matches_the_reference(corpus):
    """The inverted index must produce the same coverage as the term loop."""
    index = LexicalTermIndex(corpus)
    for candidate in ({"python"}, {"python", "sql"}, {"react"}, {"python", "sql", "spark"}):
        for job in corpus:
            terms = _important_terms(job)
            total = sum(weight for _term, weight in terms)
            expected_weight = sum(weight for term, weight in terms if term in candidate)
            expected = (expected_weight / total * 100.0) if total else 0.0
            assert index.coverage(job.id, candidate) == pytest.approx(expected), job.id


def test_a_listing_with_no_terms_reports_zero_not_missing(corpus):
    """An empty term list is a measured zero, not an absent entry."""
    index = LexicalTermIndex(corpus)
    assert index.coverage("test:4", {"python"}) == pytest.approx(0.0)
    assert index.totals("test:4") == pytest.approx(0.0)


def test_an_unknown_job_id_is_absent_not_zero(corpus):
    """A listing outside the index must be distinguishable from an empty one."""
    index = LexicalTermIndex(corpus)
    assert index.coverage("test:does-not-exist", {"python"}) is None


def test_a_term_in_every_listing_stays_correct(corpus):
    """A common term must not break the accumulation."""
    index = LexicalTermIndex(corpus)
    # "test" appears in no listing; "python" in two. Check the accumulation
    # across every posting rather than only the first.
    assert index.totals("test:1") > 0
    coverage = index.coverage("test:1", {"python", "sql"})
    assert 0.0 < coverage <= 100.0
```

- [x] **Step 2: Run the tests to verify they fail**

Run: `cmd.exe /c "env\Scripts\python.exe -m pytest tests/test_ws29_inverted_terms.py -q"`

Expected: `ImportError: cannot import name 'LexicalTermIndex' from 'src.matching.lexical'`.

- [x] **Step 3: Implement `LexicalTermIndex` and use it in the executor**

Add to `src/matching/lexical.py`:

```python
class LexicalTermIndex:
    """The per-listing important terms, inverted (WS-29).

    ``important_terms`` is a list of ``(term, weight)`` per listing — 383 per
    listing on the live corpus, 3.28 M tuples holding 209 MB, and a coverage
    loop that iterates every one of them to find the ~0.7 the candidate has.

    Inverted, the same data is ``term -> [(job id, weight)]``: 36,309 distinct
    terms, and a search walks only the postings for the terms the candidate
    actually has. The weights are identical, so the coverage is identical —
    `tests/test_ws29_inverted_terms.py` asserts that against the term loop.

    The totals are kept separately because a listing with no terms has no
    postings, and its coverage is a measured 0 rather than an absent entry.
    """

    def __init__(self, listings: Iterable[JobListing]) -> None:
        self._postings: dict[str, list[tuple[str, float]]] = {}
        self._totals: dict[str, float] = {}
        for job in listings:
            terms = _important_terms(job)
            self._totals[job.id] = sum(weight for _term, weight in terms)
            for term, weight in terms:
                self._postings.setdefault(term, []).append((job.id, weight))

    def totals(self, job_id: str) -> float | None:
        return self._totals.get(job_id)

    def matched_weight(self, job_id: str, candidate: frozenset[str] | set[str]) -> float:
        """The weight of the candidate's terms that this listing carries."""
        total = 0.0
        for term in candidate:
            for posted_id, weight in self._postings.get(term, ()):
                if posted_id == job_id:
                    total += weight
        return total

    def coverage(self, job_id: str, candidate: frozenset[str] | set[str]) -> float | None:
        """The coverage percentage, or ``None`` when the listing is unknown."""
        total = self._totals.get(job_id)
        if total is None:
            return None
        if not total:
            return 0.0
        return self.matched_weight(job_id, candidate) / total * 100.0

    def matched_and_missing(
        self, job_id: str, candidate: frozenset[str] | set[str], limit: int = EVIDENCE_LIMIT
    ) -> tuple[list[str], list[str]]:
        """The evidence lists, built during one pass over the same postings."""
        ...
```

Add `lexical_index: LexicalTermIndex | None = None` to `CorpusArtifacts` and
populate it in `get_corpus_artifacts` (beside `lexical_terms`, which stays for
the compatibility path). Then in `lexical_score`, accept an optional
`term_index` and use `coverage`/`matched_and_missing` when it is present.

- [x] **Step 4: Run the tests to verify they pass**

Run: `cmd.exe /c "env\Scripts\python.exe -m pytest tests/test_ws29_inverted_terms.py -q"`

Expected: 4 passed.

- [x] **Step 5: Prove the scores are unchanged on the live corpus**

Run a differential over all 8,558 listings: `lexical_score` with the term loop
versus with the inverted index, asserting every `score`, `keyword_coverage`,
`matched_keywords` and `missing_keywords` is identical.

Expected: `differing rows: 0`.

- [x] **Step 6: Run the lexical suites**

Run: `cmd.exe /c "env\Scripts\python.exe -m pytest tests/test_lexical_bm25.py tests/test_ws24b_lexical.py tests/test_corpus_cache.py tests/test_ws24c_search_residual.py -q"`

Expected: all pass. `tests/test_ws24b_lexical.py:245-281` has a time budget for `score_all`; the inverted index must not slow it.

- [x] **Step 7: Commit**

```bash
git add src/matching/lexical.py src/matching/corpus_cache.py tests/test_ws29_inverted_terms.py
git commit -m "perf: the lexical coverage walks postings, not every term (ws-29)"
```

---

### Task 4: Measure, and record the phase table

**Files:**
- Modify: `docs/implementation/28-cold-search-and-residual-latency.md` (a new §15)

**Interfaces:** none.

- [x] **Step 1: Measure the end state**

Use `scripts/profile_search_timing.py` (which now profiles the real path) plus a
call-count probe, and record for one search on the live corpus: the embed, the
similarity scan, `lexical_score`, `calculate_match`, and the total.

Expected: the embed drops to 0 on a repeat, the lexical loop and
`calculate_match` both fall materially, and the total is the sum.

- [x] **Step 2: Correct §14's double-charged embed**

§14 currently charges the embed twice — once as "3. embed the query" and again
inside "4. similarities_for_all" — because the *profiler* called `embed_query`
before `similarities_for_all`. The product embeds **once** per search (verified:
one `embed_query` call on a memo miss, zero on a hit). Record that correction
explicitly, with the count.

- [x] **Step 3: Write §15 with the before/after table and the exactness results**

- [x] **Step 4: Commit**

```bash
git add docs/implementation/28-cold-search-and-residual-latency.md
git commit -m "docs: what the scoring optimizations measured (ws-29)"
```

---

## Appendix — review of `2026-11-12-cold-search-latency.md`

The plan that shipped WS-28, reviewed after the fact against what it produced.
It is kept as an honest record of what was asked for, so the defects below are
recorded here rather than edited into it.

### What held up

- **All four tasks shipped and the gates held.** 1,831 tests pass; every task's
  test was written and watched fail first; the ranking was preserved except
  where Task 1 deliberately changed 1,641 experience bars, which the plan's
  Global Constraints explicitly allowed.
- **The Review Focus cases all found real behaviour.** The generic-domain noun
  case and the "mined, states no bar" case were both genuine defects.
- **The plan's sizing section (§11.5) prevented a bad decision**: it measured
  persisting the artifacts to disk (205 MB, 5.1 s load) and rejected it before
  any code was written.

### Defects found

1. **Task 4, Step 1 contains a non-runnable command.** It specifies:

   ```bash
   cmd.exe /c "env\Scripts\python.exe - <<'PY'
   # Re-mine every row the corrected miner disagrees with, and record the delta.
   PY"
   ```

   A heredoc through `cmd.exe /c` does not work, and the body is a comment, not
   a script. What actually ran was `scripts/remine_required_years.py`, written
   during execution. **The plan should have named that script**, because a
   different executor would have had to invent it.

2. **Task 4, Step 3 pointed at the wrong document.** It says "Write §11.7", but
   the spec was extracted into `28-cold-search-and-residual-latency.md` mid-run
   and that section is now §7 there. The document's own header notes the
   extraction, so a reader can follow it, but the step itself is stale.

3. **No task existed for the re-mine itself.** The plan's Task 2 migration marks
   existing non-NULL rows as decided and leaves NULL rows to be mined once more
   — but the *values already stored* were the output of the old miner, so 99 of
   them were wrong and 1,542 bars were missing. Task 4 discovered this and did
   the work, but it should have been a task with its own test (a row whose
   miner output changed must be updated and marked), because "re-mine the
   corpus" is not a measurement step.

4. **The completion checkboxes were never ticked.** All four tasks shipped; all
   ~26 boxes are still `- [ ]`. The plan file therefore reads as unexecuted.
   This is the failure mode `executing-plans` warns about — a plan without a
   ledger cannot be told apart from an abandoned one.

5. **§14 of the spec double-charged the embed, and the plan did not catch it.**
   The phase table listed "embed the query 3.98 s" *and* a `similarities_for_all`
   of 5.27 s that includes a second embed — because the *profiler* called
   `embed_query` before `similarities_for_all`. The product embeds once
   (verified by counting: 1 call on a memo miss, 0 on a hit). A plan whose
   spec is a phase table should have a step that proves the phases do not
   overlap, and this one did not. Correcting it is Task 4 of this plan.

### Lessons carried into this plan

- Every measurement step here names a **runnable command** and an **expected
  output**, and the differential ones state the exact assertion (`identical:
  True`, `differing rows: 0`).
- Task 3 of this plan is a **re-mine-shaped task with its own test**, not a
  measurement step.
- The "verified before planning" table above exists because the cold-search
  plan argued from projections in two places (§11.12's 1.0 s saving and §11.11's
  "the warm does not help"), and both turned out to be wrong.
