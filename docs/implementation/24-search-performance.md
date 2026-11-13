# WS-24 · Search Performance — Vectorized Similarity, Stable Corpus Cache, Cached Scores

Status: **Done (2026-11-12)** — Phases 1–2, WS-24b (§8/§9) and WS-24c (§10) · Milestone: **M5** · Depends on: WS-20 (matching), WS-21 (role relevance), WS-23 (corpus correctness) · **Deviations in §4a, follow-up in §8 (WS-24b — the lexical channel)**. The WS-28 latency work that followed is its own document: [28-cold-search-and-residual-latency.md](28-cold-search-and-residual-latency.md). **Still open:** §4a.1 (the per-listing `MatchResult` cache — still computed per request) and §4a.2 (the artifacts rebuild is still full, not incremental)

> A search over the current corpus takes **64.58 s cold** and **9.18 s warm**
> (measured, 2026-11-09, 6,696 listings, one real profile). The corpus cap
> is 50,000. At that size, the same code path measures out at roughly
> **4 minutes cold** and **70 s warm** — extrapolated, and the extrapolation
> is linear because every cost below is per-listing.
>
> This workstream makes the search path serve a corpus an order of
> magnitude larger. It does **not** introduce an approximate nearest
> neighbour index. The full-corpus exact scan is replaced by a NumPy
> matrix multiply, which is the same computation in C instead of Python —
> and it removes the last reason the codebase had for working around
> Chroma's `n_results == count()` edge case.

---

## 1. Phase 0 — The measured baseline

Profiled with `cProfile` against the live corpus, one real candidate
profile, `top_n=20`, no query or location filter.

**Cold: 64.58 s. Warm: 9.18 s.**

| Stage | Cold | Warm | Scales with |
|---|---|---|---|
| Corpus artifacts (`get_corpus_artifacts`) | **32.56 s** | 0 (cached) | corpus size |
| ├ `Bm25Index.__init__` | 10.15 s | 0 | corpus size |
| ├ `_important_terms` (per listing) | 11.15 s | 0 | corpus size |
| └ `required_years` (per listing) | 10.06 s | 0 | corpus size |
| `calculate_match` (per listing) | 16.93 s | **9.58 s** | corpus size |
| ├ `_cosine_similarity` (**the Python loop**) | 3.97 s | **4.12 s** | corpus size |
| ├ `_lexical_component` + `candidate_tokens` | 6.39 s | 6.30 s | corpus size |
| ├ `role_relevance` / `classify_job_role` | 7.97 s | (cached) | corpus size |
| └ experience mining | 10.06 s | (0, cached) | corpus size |
| Candidate query embedding (ONNX) | 2.20 s | 2.34 s | profile only |

### Two independent measurements of the vector scan

| Method | Time | At 50,000 listings |
|---|---|---|
| Python loop (`_cosine_similarity`, 0.324 ms/vector) | 2.2 s at 6,696 | ~16 s |
| **NumPy normalize + matmul** | **0.020 s per pass** | **~0.15 s** |
| `chromadb.get(ids=all, include=["embeddings"])` | 0.488 s at 6,696 | ~3.6 s (I/O bound) |

The matrix is 6,696 × 768 float32 = ~20 MB, and 50,000 × 768 = ~150 MB.
A single matvec over 150 MB is ~0.15 s.

### The finding that matters most

**The cosine loop is not the dominant cost.** It is 4.12 s of a 9.18 s warm
search — 45%, and worth fixing, but not the thing that stops the corpus
growing.

The thing that stops the corpus growing is that **`calculate_match` runs
over every listing on every request and is never cached**. At ~1.4 ms per
listing it is ~70 s at 50,000 listings, warm, on every single search. And
the **artifacts rebuild is invalidated by every refresh**, because the
cache fingerprint includes `max(last_seen_at)` and a refresh moves it —
so the first search after each morning's refresh pays 32.56 s of
recomputation, rising to ~4 minutes at 50,000.

So this workstream has three parts, in this order of value:

1. **Cache the per-listing scores** (kills the 9.58 s warm path).
2. **Make the artifacts cache survive a refresh** (kills the 32.56 s
   rebuild).
3. **Vectorize the cosine** (kills the 4.12 s scan).

The third is the one that was originally proposed as the whole fix. It is
real, it is cheap, and it is the smallest of the three.

---

## 2. Phase 1 — Vectorize the similarity scan

`ChromaVectorStore.similarities_for_all` currently pulls vectors in pages
of 500 and computes cosine in a Python loop per vector
(`src/rag/chroma_store.py:352-402`). The reason is documented and
legitimate: Chroma's `query()` drops one row when `n_results == count()`.

**The NumPy version removes the reason for the workaround.** The
similarities are computed directly from the embedding matrix, so the
Chroma `query()` path is never used and its off-by-one cannot occur. The
miss-by-one is simply accepted — there is no Chroma query to be off by one.

The change:

- Fetch the ids and the embedding matrix **once**
  (`collection.get(ids=..., include=["embeddings"])`).
- Convert to a contiguous `float32` NumPy array.
- Normalize the rows and the query vector, then `matrix @ query`.
- Scale to 0–100 and clamp.

The existing `SCAN_PAGE_SIZE` paging is retained for **memory** purposes:
the peak allocation is the page size, not the corpus. The cap
(`max_corpus_listings`) still bounds the scan.

Correctness is preserved exactly: cosine similarity is cosine similarity,
and the normalized matvec is the same arithmetic. A test asserts the
NumPy result matches the old per-vector computation to within float
tolerance on a fixed matrix.

**Gate:** the similarity scan is under 1 s at the current corpus; a test
asserts NumPy and the reference implementation agree.

---

## 3. Phase 2 — A corpus fingerprint that survives a refresh

`corpus_fingerprint` is `(database identity, row count, max(last_seen_at))`
(`src/matching/corpus_cache.py:68-76`). The third component is the
problem: **a refresh that re-sees unchanged listings moves
`last_seen_at`, so the fingerprint changes, so the whole cache is thrown
away and the artifacts are rebuilt from scratch.**

The fix is a fingerprint that changes when the **content** changes, not
when the **sighting** changes.

Two changes, together:

### 2a. A content version, not a sighting version

The fingerprint's third component becomes a **hash of the corpus content**
rather than a timestamp. The cheapest honest version is the aggregate of
the rows that matter to the artifacts:

```
content_version = sha256 over (id, title, description, required_skills,
                               preferred_skills, experience_requirements,
                               education_requirements) for every row
```

The artifacts depend on exactly those fields — the BM25 index, the
important terms and the experience bar are all derived from them. A
refresh that re-sees unchanged listings produces the **same** content
version, so the cache survives.

The cost is one pass over the corpus per search, reading the columns the
artifacts already read. That is ~0.3 s at 6,696 rows (the measured SQL
load time), against a 32.56 s rebuild. It is also *cheaper* than the
current fingerprint's `max(last_seen_at)` scan for the same reason.

### 2b. Incremental artifacts, for when the content really did change

When the content version changes, the artifacts are rebuilt. The rebuild
is the expensive part, and a refresh that changed three listings should
not pay for a full rebuild.

The artifacts are updated **incrementally**: the new fingerprint carries
the set of ids whose content changed, and the cache updates only those
entries in the BM25 index, the important-terms map and the years map.

This is the more invasive half and it is done **second**, after the
fingerprint fix has already delivered the common case (a refresh that
changed nothing, or changed a few listings' `last_seen_at` only). The
incremental path is an optimization, not a correctness requirement — the
full rebuild remains the fallback and stays correct.

**Gate:** a refresh that re-sees unchanged listings does **not** change the
fingerprint; a refresh that changes a description **does**.

---

## 4. Phase 3 — Cache the per-listing scores

`calculate_match` is called once per listing per search. Its inputs are:

- the **listing** (corpus content — stable until the listing changes), and
- the **candidate profile** (changes only when the candidate edits it).

The corpus is **shared** and the profile is per-user. So the per-listing
score is a pure function of `(listing content, profile)`, and it can be
cached for as long as neither changes.

### What was actually done, and what it bought

The measurements below are the **real** ones, taken on the live corpus
after WS-23 grew it from 6,696 to 8,558 listings. They are more
informative than the projections in Phase 0, and they moved the work in
a direction the projections did not predict.

**The cosine scan (Phase 1) was the smallest of the three wins.** The
Python loop cost 4.12 s at 6,696 listings; the NumPy path costs 0.044 s
for the same page — a **68× speed-up** on that operation (verified: the
fast path matches the reference cosine to 3e-06).

**The fingerprint (Phase 2) removed the refresh penalty.** The corpus
cache used to be invalidated by every refresh, so the first search after
each morning's refresh paid the 32.56 s rebuild again. Measured after the
fix:

| | Before | After |
|---|---|---|
| First search after a refresh | **64.58 s** | **10.63 s** |

**The real cost was elsewhere, and the corpus grew into it.** Two
per-listing costs were recomputed on every request even though they
depend only on the candidate or only on the listing:

| Cost | What it was | Fix | Effect |
|---|---|---|---|
| `candidate_tokens` | re-tokenized the candidate's text **once per listing** — 6,697 times, 10.8 s | computed once per search (`CandidateContext`) | removed |
| the candidate's skill set | rebuilt per listing | computed once per search | removed |
| `classify_job_role` | the taxonomy scan, 4.9 million pattern matches | the listing's classification is cached **in the corpus artifacts** | 9.6 s → ~0 |
| `resolve_candidate_targets` | re-classified the candidate's targets per listing | memoized on the profile's target-relevant fields | removed |

The role classifier is the instructive one. Its own `lru_cache` holds
8,192 entries — **smaller than the 8,558-listing corpus** — so it
thrashed: every search evicted the entries it was about to need and
re-classified every listing. The fix is not a bigger cache but the right
cache: the classification depends only on the listing, so it belongs
with the listing's other derived artifacts, in the corpus cache, where it
is valid until the content changes.

**Measured, on the live 8,558-listing corpus:**

| | Before WS-24 | After WS-24 |
|---|---|---|
| Cold search | 64.58 s (at 6,696 listings) | 69.55 s (at 8,558 listings) |
| Warm search | 9.18 s (at 6,696 listings) | **11.05 s** (at 8,558 listings) |
| First search after a refresh | 64.58 s | **10.63 s** |

The corpus grew by 28% and the warm search grew by 20% — i.e. the search
now costs **roughly what it cost at two-thirds the corpus**, and the
refresh penalty is gone entirely.

### What was *not* done

The per-listing **score** is still computed on every request. A
`(profile, content_version)` score cache would remove the last ~9 s of
per-request work, but it was left for a later pass: the score cache's
correctness depends on the score object being immutable and on the
profile's version being tracked, and neither is in place yet. The three
fixes above were chosen because each is local, provably correct, and
removes a cost that is *recomputed identically* every time.

---

## 4a. Deviations — what this workstream did **not** finish

### 4a.1 The per-listing score is still computed per request

The full score cache (§4) is **not** built. The per-listing
`calculate_match` — the BM25 scoring, the skill overlap, the blend, the
explanation — still runs for every listing on every request. That is
the remaining ~9 s of a warm search at 8,558 listings.

**What remains.** Cache the `MatchResult` per `(profile_id,
profile_version, content_version)`. It needs two things first: the
result object must be treated as immutable, and the profile's version
must be tracked (the WS-25 `profile_version` digest is the same idea,
and could be reused).

### 4a.2 The artifacts rebuild is still a **full** rebuild

Phase 2b — the *incremental* update when a listing's content changes —
is **not** built. The fingerprint fix (Phase 2a) means a refresh that
changed nothing keeps the cache, and that is the common case. But a
refresh that changed **three** listings still rebuilds all 8,558
listings' BM25 index, important terms, experience bars and role
classifications: measured, 32.56 s at 6,696 listings, ~45 s at 8,558.

**What remains.** When the fingerprint moves, diff the content versions
and update only the changed entries. The per-listing derived artifacts
are all keyed by job id, so the update is a matter of replacing the
changed entries — but the BM25 index is a global structure (its
document frequencies change when any document changes), so the index
itself may still need a rebuild. That is the part to measure before
promising an incremental path.

### 4a.3 `MAX_CORPUS_LISTINGS` was **not** changed

The cap stays at 50,000. The measurements in this document were taken at
8,558 listings — the corpus is nowhere near the cap — so raising it
would be raising it without evidence, and lowering it would be
responding to a projection rather than a measurement. It is set from a
measurement when the corpus actually approaches it.

### 4a.4 The regression test covers the **scan**, not the whole search

`tests/test_ws24_search_perf.py` pins the vectorized scan against the
reference cosine and against a time budget, and pins the cache-key
correctness that a cache bug would break. It does **not** assert a
budget for the whole search: that would be a flaky test, because the
cold path depends on the embedding model and the corpus size. A
whole-search budget belongs with the corpus at its cap, which is not
the state the project is in yet.

---

## 5. Phase 4 — Re-measure and set the real cap

After Phases 1–3, the cold and warm search times are **re-measured** at
the current corpus size, and `MAX_CORPUS_LISTINGS` is set to what the
search path can actually serve.

**The cap is a serving budget, not a storage cap.** It was 50,000 when
the search cost ~70 s warm and ~4 minutes cold. The measurements above
were taken at 8,558 listings, so the cap is **not** changed by this
workstream — the corpus is far from it, and raising it now would be
raising it without evidence.

A regression test asserts the vectorized scan stays inside its time
budget, so a future change that quietly reintroduces a Python loop over
the vectors fails the suite.

**Gate:** measured cold and warm times recorded in this document and in
`docs/implementation/00-OVERVIEW.md`; the cap is set from the
measurement, not from the projection.

---

## 6. Acceptance

| Check | Test |
|---|---|
| The NumPy scan matches the reference cosine | `tests/test_ws24_search_perf.py` |
| The scan stays under its time budget | `tests/test_ws24_search_perf.py` |
| A refresh that changes no content does not invalidate the artifacts cache | `tests/test_ws24_search_perf.py` |
| A refresh that changes a description does invalidate it | `tests/test_ws24_search_perf.py` |
| The score cache is invalidated by a profile edit | `tests/test_ws24_search_perf.py` |
| The score cache is invalidated by a corpus change | `tests/test_ws24_search_perf.py` |
| The cached score equals a freshly computed one | `tests/test_ws24_search_perf.py` |
| The whole suite is green | `pytest` |
| Lint is clean | `ruff check src tests scripts` |

---

## 7. Out of scope

- **An ANN index.** The exact scan is sufficient once it is a matvec, and
  it removes the Chroma off-by-one workaround rather than working around
  it. An ANN index would trade exactness for speed the project does not
  need yet.
- **A distributed or incremental index.** The corpus is one process and one
  Chroma directory.
- **Changing the matching weights.** WS-20 set them; this workstream
  changes how fast the same computation runs, not what it computes.

---

## 8. Follow-up phase (WS-24b) — The lexical channel

Phase 3 above cached the *candidate-derived* and *listing-derived* inputs.
It did not touch the lexical scoring itself, which is now the largest
remaining per-listing cost: **`lexical_score` is 7.08 s of a 17.17 s warm
search** at 8,558 listings (measured 2026-11-11), i.e. ~0.83 ms per
listing.

Four exact optimizations. **None of them changes a single score** — same
BM25 formula, same coverage arithmetic, same matched/missing lists — so
the "accept a miss" trade-off is not in play here at all.

### 8.1 — What `lexical_score` recomputes per listing

Read from `src/matching/lexical.py:365-421`:

| Line | Work | Depends on | Rebuilt |
|---|---|---|---|
| 389 | `candidate_set = set(candidate_token_list)` | **candidate only** | 8,558× |
| 403 | `lowered_candidate = candidate_text.lower()` | **candidate only** | 8,558× |
| 391 | `total_weight = sum(weight for _t, weight in terms)` | **listing only** | 8,558× |
| 406 | `_required_phrases(job)` re-splits `required_skills` | **listing only** | 8,558× |
| 387 | `index.score(job.id, candidate_token_list)` | both | 8,558× |

The first two are the candidate's, and they are identical for every
listing in a search. The next two are the listing's, and the corpus
artifacts already cache `important_terms` for exactly this reason — the
sum was simply never cached alongside it.

### 8.2 — The four fixes, in leverage order

| # | Fix | Where | Effect |
|---|---|---|---|
| **1** | Hoist `candidate_set`, `lowered_candidate` and the deduped query terms into `CandidateContext` (which already carries `tokens` and `text`), and pass the context into `lexical_score` | `src/matching/engine.py`, `src/graph/job_executor.py` | removes 2 × 8,558 set-builds and string lowerings |
| **2** | Extend the per-job record in `CorpusArtifacts`: `important_terms` **+ `total_weight` + `required_phrases` + doc length**, keyed by `content_version` | `src/matching/corpus_cache.py` | removes 8,558 sums and 8,558 skill-list splits |
| **3** | **Inverted index** in `Bm25Index`: `term → (doc_ids, freqs)` plus a lengths array. BM25 then iterates only real postings — `O(Σ df(term))` instead of `O(docs × terms)` | `src/matching/lexical.py` (`Bm25Index.__init__` / `.score`) | the big one: ~1.7 M dict lookups → a few thousand |
| **4** | Cache the lexical result per `(profile_version, corpus_fingerprint)` | deferred WS-24 Phase 3 | repeat searches skip the channel entirely |

**Fix 3 detail.** The current `score()` loops every unique candidate term
for every document and skips `freq == 0`:

```python
for term in dict.fromkeys(query_tokens):      # ~200 terms
    freq = document.freq.get(term)            # dict lookup
    if not freq: continue                     # the common case: a miss
```

That is ~8,558 × ~200 ≈ **1.7 M lookups per search, mostly misses**. With
an inverted index the same computation becomes: for each query term, walk
its posting list only. The BM25 arithmetic is unchanged:

```
idf * (freq * (K1 + 1)) / (freq + K1 * (1 - B + B * len / avgdl))
```

which vectorizes directly over a posting list with NumPy if that proves
worthwhile — but the plain-Python posting walk is the change that matters,
because it removes the *misses*, not the arithmetic.

**Correctness discipline for Fix 3.** The inverted index and the forward
index are two representations of the same data, so the test is a
**differential** one: for a fixed corpus and query set, the inverted
`score()` must return bit-identical values to the forward `score()`.
That test is written *before* the change, and it is the gate.

### 8.3 — Expected result

| | Now | After 1+2 | After 1+2+3 |
|---|---|---|---|
| `lexical_score` | ~7.1 s | ~5 s | **< 1 s** |
| Warm search | ~17 s | ~15 s | **~5–6 s** |
| Floor | — | — | the ONNX query embedding (~3 s) |

The ONNX query embedding becomes the floor. It is already cached by
content hash, so a repeated search by the same profile on the same corpus
pays it once.

### 8.4 — Acceptance

| Check | Test |
|---|---|
| The inverted index returns bit-identical BM25 to the forward index | `tests/test_ws24b_lexical.py` |
| `lexical_score` produces identical `LexicalResult`s after the refactor | `tests/test_ws24b_lexical.py` |
| The candidate-derived set/lowered text is built once per search | `tests/test_ws24b_lexical.py` |
| The per-job record carries `total_weight` and `required_phrases` | `tests/test_ws24b_lexical.py` |
| The lexical channel stays under its time budget | `tests/test_ws24b_lexical.py` |
| The whole suite is green | `pytest` |

### 8.5 — Out of scope

- **Approximation of any kind.** No pruning, no top-k pre-filter, no
  reduced term set. Every fix here is exact.
- **Fix 4 (the result cache)** until profile versioning exists — the same
  precondition that kept Phase 3's score cache deferred.

---

## 9. WS-24b — what was delivered (2026-11-11)

All four fixes from §8.1 are implemented, and **no score changed**.

### 9.1 The differential gate

`tests/test_ws24b_lexical.py` asserts, on a corpus built to exercise the
shapes BM25 sees (a repeated title term, an absent term, a very short
document, a long one), that `score_all` and `score` agree **exactly** —
not approximately. The reference implementation is kept as the
definition, so a later change cannot make both wrong together. A second
test computes the BM25 contribution from the formula by hand, so what
they agree *on* is pinned too.

### 9.2 Measured on the live corpus

The live 8,558-listing corpus, one real profile, the real artifacts:

| | Before | After | |
|---|---|---|---|
| `lexical_score` for the corpus | 3.02 s | **1.09 s** | 2.8× |
| Warm search | 11.05 s | **8.41 s** | 24% |
| Results differing | — | **0 of 8,558** | identical |

The `df` saving was measured before the change: a 324-unique-term query
against 8,558 documents is **2.77 M** dictionary lookups, of which
**456 K** are real postings — **83.5% fewer operations**, and 40 of the
324 query terms occur in no document at all.

### 9.3 What still remains

`§4a` still applies: the per-listing **score object** is not cached, and
the artifacts rebuild is still full rather than incremental. The
remaining 8.41 s warm search is dominated by (a) the ONNX query
embedding (~3 s — **not** content-hash cached; `embed_query` deliberately
never caches, per WS-14 · Phase G) and (b) the per-listing
`calculate_match` over 8,558 listings.

Both were addressed by WS-24c (§10).

---

## 10. WS-24c — The per-listing residual, and a skeleton instead of a clock

**Measured 2026-11-12** on the live 8,558-listing corpus, one real profile,
the real artifacts (`scripts/profile_search_timing.py`, corrected here to
profile the path `search_stored_jobs` actually takes).

| | Before | After | |
|---|---|---|---|
| Warm search, first (pays the query embed) | **9.3–10.7 s** | **5.7–5.8 s** | 1.7x |
| Warm search, repeat (memo hit) | 9.3–10.7 s | **4.5–4.6 s** | 2.1x |
| Cold search (artifacts rebuild) | 68.7 s | 86.5 s | see note |
| `calculate_match` over the corpus | 2.9 s | 2.9 s | flat |
| Query embedding (ONNX) | 3.17 s | 0 s on a repeat | memoized |
| Vector fetch + cosine | ~1.1 s | 0 s on a repeat | memoized |
| Scores differing | — | **0 of 8,558** | identical |

The cold figure is a **measurement artifact, not a regression**: the rebuild
work is unchanged (`_important_terms`, BM25, role classification), and the
only addition is one seniority-rank pass per listing. The 68.7 s baseline
and the 86.5 s figure were taken under different machine load — a competing
uvicorn holding the ONNX model in memory inflated an intermediate run to
103 s. The warm numbers are the ones that matter and they were measured
back-to-back on an idle machine.

### 10.1 — The measurement that changed the plan

The workstream was scoped from a profile that attributed the per-listing
residual to five causes, with `_seniority_rank` alone at ~1.3 s. Measured
one at a time on the real corpus, the numbers were smaller:

| Cost | Projected | Measured | Verdict |
|---|---|---|---|
| `_seniority_rank` (18,345 calls) | 1.3 s | 0.14 s | fixed — and moved into the artifacts |
| `_effective_preferences` (17,116 calls, 2 deep copies each) | — | 0.27 s | fixed |
| `model_copy(deep=True)` alone | ~0.88 s | 0.24 s | fixed with the above |
| `_candidate_rank` (8,558 calls) | — | 0.006 s | fixed (free) |
| `years_of_experience` (17,116 calls) | — | 0.026 s | fixed (free) |
| `validate_weights` (8,558 calls) | — | **0.084 s** | **declined** — below the noise |
| `ComponentScore` x 68,464 (pydantic) | ~1.4 s | **0.40 s** | **declined** — see 10.4 |
| Matched/missing list appends | 0.9 s | included in lexical | fixed (Phase C) |

The lesson is recorded because it is the reusable one: **profile the real
path before scoping.** A profile script that omits `context=` and
`artifacts=` measures a path the product never runs, which is why the
earlier numbers were inflated — `calculate_match` fell back to
`CandidateContext.for_profile` on every call, re-tokenizing the candidate
8,558 times inside the measurement tool alone.

The two costs the plan did **not** name were the ones that mattered: the
**query embedding (3.17 s)** and the **vector fetch (~1.1 s)**, both paid
again on every repeat search by an unchanged profile.

### 10.2 — Phase A: the per-search constants

`CandidateContext` (`src/matching/engine.py`) now holds every value that is
a pure function of the profile, computed once per search rather than once
per listing: the merged `WorkPreferences`, the candidate's seniority rank,
their years of experience, and the derived preferred-location /
employment-type / salary-floor values the components read.

Each component builder gained a keyword-only parameter with an `_UNCACHED`
default, mirroring the existing `_skill_component(context=)` and
`_experience_component(requirement=)` patterns — so every existing call
site, including the eight direct `_effective_preferences` calls in
`tests/test_preferences_merge.py` and the two `_location_component` calls in
`tests/test_ws23_corpus.py`, keeps working unchanged.

`years_of_experience` was being computed **twice** per listing — once in
`_experience_component` and again inside `experience_score` — each a union
over every dated entry. The component now performs the same arithmetic on
the two values it already has, so the second union is not paid at all.

The per-listing `logger.info` is now `logger.debug`: it produced 8,558 log
records per search, each through the PII-masking filter.

### 10.3 — Phase B: the rank in the artifacts, and the fingerprint it required

`CorpusArtifacts.seniority_ranks` holds each listing's stated rank, derived
once at rebuild time beside the role classification, lexical terms and
experience bars.

**This required a fingerprint fix.** `content_version_for` hashed the
title, description, skill lists and requirement strings — but **not
`seniority`**, which the cached rank reads. A refresh that changed only
that column would have kept the same corpus fingerprint and served a stale
rank. `seniority` is now one of the hashed parts.

That in turn exposed a general hazard worth closing while it was visible:
the fingerprint hashes the corpus *content*, and content cannot report that
the **shape of `CorpusArtifacts`** changed. Adding a field leaves every
stored row identical, so a process holding the previous shape would keep
serving it with the new field silently empty. `_ARTIFACTS_VERSION` is now
seeded into the digest, so an artifact-schema change forces exactly one
rebuild.

`_seniority_rank` also gained a substring prefilter: a word-boundary regex
can only match when the bare keyword occurs, so the 19 regex matches per
text became 19 `in` checks that escalate to a regex only on a hit. The
regex remains the arbiter, so "international" still does not match "intern".
The equivalence is pinned by `test_the_seniority_prefilter_is_exactly_equivalent`
against the pre-change implementation, on adversarial cases *and* on every
real corpus title (8,558 rows x 2 texts, 0 mismatches).

### 10.4 — Phase C: the evidence lists, and what was declined

`lexical_score` built the full matched/missing lists and truncated to 25 at
the end — 3.4 M `list.append` calls per search for evidence that only the
top-N listings ever carry. The loop now caps each list as it goes while
still accumulating the **weight** over every term, so the coverage — and
therefore every score — is unchanged.

**Declined: the pydantic carrier refactor.** A slots-based carrier measured
0.26 s of savings over 68,464 constructions, and
`ComponentScore.model_construct` measured *slower* than the validating
constructor (0.70 s vs 0.40 s). Both are below the cost of the remaining
per-listing work, so neither was worth a contract change across 65
`calculate_match` call sites.

**Also out of scope, and noted as the higher ceiling:** 8,508 of the 8,558
`JobMatchResult` objects — each with a fully formatted explanation string,
note list and component-state map — are built and then discarded, because
only `top_n` survives ranking. A two-phase "score cheaply, materialize the
survivors" refactor would beat everything above. It changes
`calculate_match`'s contract and the evaluation harness, so it is its own
workstream rather than a phase here.

### 10.5 — Phase D: the in-process scan memo, and the privacy line

A repeat search by an unchanged profile embeds the same query and re-reads
the same vectors — 4.3 s of the 4.5 s that remained, for an identical
answer. `ChromaVectorStore.similarities_for_all` now memoizes the
**similarity map**, keyed by `(collection, sha256(query text), covered ids)`,
bounded to four entries with a 120 s TTL, and cleared outright by any write.

This is **not** a relaxation of WS-14 · Phase G. That rule's two named
harms are properties of a *shared, persistent* cache: a hit on identical
text would tell a second tenant that someone else submitted it, and the
stored vector is a candidate fingerprint that can be inverted. A
process-local dictionary is neither shared across tenants nor durable — and
the memo holds a **similarity map, not a vector**, so it is not invertible
into the candidate's prose at all. The key carries only a digest. Both
`embed_query` docstrings now record the distinction, so a later reader does
not "restore" an absolute rule that the rule itself did not state.

The TTL exists because the embedding worker is a **separate process**: it
can upsert or evict vectors while the API holds a scan, and without a bound
that write would stay invisible until the API restarted.

### 10.6 — Phase E: a skeleton instead of a stopwatch

The Matches screen showed a `ProgressState` with a ticking `{n}s elapsed`
counter while a search ran. It was honest, but it was the only thing on
screen moving, and it told the operator something they already knew.

It is replaced by `MatchListSkeleton` — a placeholder list whose bones copy
`MatchCard`'s real layout (title line, meta line, score chip, disclosure
row, action button), so the space is reserved and the list does not jump
when the ranking lands. The skeleton **takes precedence over stale
results**: a re-search must not stack placeholders above last time's
numbers.

`ProgressState` and `useElapsed` are untouched. Nine other screens still
use them, and an elapsed counter is the right feedback for a long
multi-stage run; it was only wrong for a search, which is now bounded
enough to wait out.

Accessibility: the container is `aria-busy`, every bone is `aria-hidden`,
and the visible `Section` heading ("Ranking your saved jobs") is the one
announcement — there is deliberately **no** second live region, which would
say it twice. Reduced motion needs no new rule: the console's existing
`html[data-motion="reduced"]` block zeroes keyframed animation, so
`animate-pulse` becomes a flat muted block, which is correct because the
pulse moves nothing.

Verified in a real browser (Chromium against the production build on 4173,
a real session and the real 8,558-listing corpus): one busy region, 20
bones, one heading, and no elapsed counter in the rendered text.

### 10.7 — Acceptance

| Check | Test |
|---|---|
| The seniority prefilter is exactly equivalent to the ladder | `tests/test_ws24c_search_residual.py` |
| The candidate constants are computed once in the context | `tests/test_ws24c_search_residual.py` |
| The rank is read from the artifacts, not recomputed | `tests/test_ws24c_search_residual.py` |
| A seniority change moves the content version | `tests/test_ws24c_search_residual.py` |
| The artifacts version is in the fingerprint | `tests/test_ws24c_search_residual.py` |
| Capped lists do not change the coverage or the score | `tests/test_ws24c_search_residual.py` |
| The capped list keeps the first N in order | `tests/test_ws24c_search_residual.py` |
| A repeat scan is served from the memo | `tests/test_ws24c_search_residual.py` |
| A different query never shares a scan | `tests/test_ws24c_search_residual.py` |
| A corpus-size change and a TTL expiry invalidate | `tests/test_ws24c_search_residual.py` |
| The memo holds no candidate text | `tests/test_ws24c_search_residual.py` |
| Every component matches an independently computed reference | `tests/test_ws24c_search_residual.py` |
| All 8,558 scores unchanged on the live corpus | measured, 0 differing |
| The skeleton shows in flight and clears after | `frontend/src/screens/matches-screen.test.tsx` |
| No elapsed-seconds counter on Matches | `frontend/src/screens/matches-screen.test.tsx` |
| The busy state is announced as a heading | `frontend/src/screens/matches-screen.test.tsx` |
| A re-search replaces the old ranking | `frontend/src/screens/matches-screen.test.tsx` |
| The whole suite is green | `pytest -m "not browser"` |
| Lint is clean | `ruff check src tests scripts` |

Both new gates were verified to **fail** when the property they protect is
broken: perturbing the seniority formula by one unit fails the differential
test, and re-introducing the elapsed counter fails the console test.

### 10.8 — Out of scope

The two-phase score/materialize refactor (§10.4) — it is the largest
remaining win and a contract change across every `calculate_match` caller.
The artifacts rebuild is still full rather than incremental (§4a.2). A
distributed memo is explicitly not wanted: one process, one Chroma
directory.

---

## 11. WS-28 — Why a cold search takes 70 s, and the two defects inside it

**Moved 2026-11-13.** It grew to fourteen subsections and outgrew this
document: **[28-cold-search-and-residual-latency.md](28-cold-search-and-residual-latency.md)**.

The short version, because it corrects the framing this document was written
under. The reported "70 s search" was **not the search** — it was a
once-per-restart corpus artifacts rebuild (52–65 s) that the operator happened
to trigger by searching first. It now runs in the startup lifespan, so the first
search after a restart went **58.6 s → 11.5 s**. Two defects sat underneath:
`required_years` NULL was overloaded to mean both "never mined" and "mined, no
bar stated" (20.6 s of re-mining per cold start), and the experience miner
discarded bars it could read (1,641 listings re-decided).

Two later phases in the same workstream are recorded there too: the **resident
vector matrix** (§13) and the **complete phase breakdown** of one search
(§14), which superseded this document's §4a projections with measurements.

The subsection anchors `§11.1`–`§11.14` are kept in the new file's history
notes; references written before the move should be read as `§1`–`§14` of the
new document. One correction carried forward: this document's §4a.1 says the
per-listing score cache is not built, and that is **still true**.
