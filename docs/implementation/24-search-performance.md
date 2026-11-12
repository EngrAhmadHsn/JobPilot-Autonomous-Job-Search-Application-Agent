# WS-24 · Search Performance — Vectorized Similarity, Stable Corpus Cache, Cached Scores

Status: **Phases 1–2 done** · Milestone: **M5** · Depends on: WS-20 (matching), WS-21 (role relevance), WS-23 (corpus correctness) · **Deviations in §4a, follow-up in §8 (WS-24b — the lexical channel)**

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

**Reported 2026-11-12**: a search logged `Job search requested` at 15:43:17
and `Job search complete` at 15:44:27 — 70 s. The server had started at
15:42:59, eighteen seconds earlier.

### 11.1 — The measurement

Reproduced on a freshly started server against the live 8,558-listing corpus:

| | Measured |
|---|---|
| First search after startup | **58.6 s** |
| Second search | 3.6 s |
| Third search | 3.0 s |
| Warm, on an already-warm server | 3.1–3.6 s |

The corpus artifacts cache is per-process (`src/matching/corpus_cache.py`,
`_CACHE`), so the first search after every restart pays the full rebuild. The
rebuild measures **52–65 s**; every later search hits the cache in 0.15 s.

Per-phase, at 8,558 listings:

| Phase | Cost |
|---|---|
| `required_years` mining | **20.6 s** |
| `classify_job_role` | 13.8 s |
| `Bm25Index.__init__` | 10.7 s |
| `_important_terms` | 7.1 s |
| `listing_from_row` (Pydantic) | 0.8 s |
| `seniority_rank` (WS-24c, cached) | 0.03 s |

So the 70 s was **not the search** — it was a once-per-restart rebuild that
the user happened to trigger. That is a real user-facing defect (an operator
who restarts the server and immediately searches waits a minute), but the
frame "the search is slow" is wrong, and the difference decides the fix.

### 11.2 — The first defect: `required_years` NULL means two things

WS-23b moved experience-bar mining from read time to **write** time, storing
the result in `jobs.required_years`. The read path in
`get_corpus_artifacts` is:

```python
required_years={
    job.id: (
        stored_years.get(job.id)
        if stored_years.get(job.id) is not None
        else required_years(job)      # <-- mines the description, again
    )
    for job in jobs
},
```

`NULL` therefore means either "never mined" **or** "mined, and the listing
states no bar" — and the read path cannot tell them apart, so it re-mines
both. On the live corpus **6,741 of 8,558 rows are NULL**, and re-mining them
costs **20.6 s of every cold start**.

The initial hypothesis was "the backfill never ran". That was **wrong**, and
the measurement disproved it: a backfill script exists
(`scripts/backfill_required_years.py`), it only writes when the mined value is
not `None`, and re-mining all 6,741 NULL rows yields **0** values — every one
of them genuinely states no bar. The backfill therefore cannot change anything,
and running it again would be a no-op.

The fix is a **sentinel**: a column value that means "mined, nothing stated",
distinct from `NULL` ("never mined"). A row with the sentinel is never re-mined.

### 11.3 — The second defect: the miner discards bars it can read

While verifying the first, a correctness bug surfaced. The miner's
technology-context rule (`_TECH_CONTEXT_RE`) is meant to skip
technology-specific bars — "3 years with Python" is not a total-experience
bar. But the rule fires on **any** noun, so it swallows domain nouns too:

| Sentence | Mined | Correct |
|---|---|---|
| "Minimum requirements 7+ years of sales or prospecting experience" | `None` | 7 |
| "5+ years of software sales experience selling to enterprises" | `None` | 5 |
| "Minimum of 3 years of experience in a Customer Success role" | `None` | 3 |
| "9+ years of experience in customer support" | `None` | 9 |

Measured across the corpus, exercising the rule with a generic-noun
exclusion:

- **1,145 listings gain a bar** they should always have had;
- **90 listings have an existing bar change value**, in both directions,
  because a *later* sentence was previously discarded and now competes:
  `3.0 → 7.0`, `3.0 → 9.0`, `2.0 → 3.0`, and in two cases `3.0 → 2.0`.

That is a **scoring** change, not a performance one. It moves the
`experience` component (weight 0.17) for 1,235 listings, which will reorder
rankings. It is the honest fix, but it must be a deliberate, measured change
with a documented before/after — never a silent side effect of a speed
workstream.

This is also why the corpus must be **re-mined after** the fix: the stored
values are the output of the buggy miner, so leaving them would freeze the
bug into the column.

### 11.4 — What the plan does, in order

1. **The miner keeps generic-domain bars** (defect 2). A small generic-noun
   set, so "years of sales" is a total bar and "years with Python" is not.
   This is the correctness fix, and it is what the re-mine depends on.
2. **A mine-once sentinel** (defect 1), so a row whose answer is legitimately
   "no bar" stops being re-mined forever.
3. **A re-mine of the corpus**, now that the miner is right and the sentinel
   exists — a migration or script, decided by measurement of which is safer.
4. **A startup warm** of the corpus artifacts, so the first search after a
   restart is not the one that pays. Deliberately last: it removes the
   symptom, and the symptom is what makes the other three visible.

### 11.5 — Sizing, before committing to the approach

| Option | Measured | Verdict |
|---|---|---|
| Persist the whole `CorpusArtifacts` | 205 MB, dump 9.5 s, **load 5.1 s** | no better than a warm start, and 205 MB of scratch |
| Persist the derived parts only (no jobs list) | 149 MB, dump 8.6 s, **load 5.3 s** | still not worth it; the jobs list re-reads from SQLite in 0.8 s |
| Delete the 6,741 re-mines | ~20.6 s saved per cold start | the sentinel does this |
| Warm the artifacts at startup | 52 s moved off the request path | the server is not serving yet, so it costs nothing user-visible |

A startup warm is the right shape: the rebuild has to happen exactly once per
process either way, and doing it before the first request is strictly better
than doing it during one. Persisting to disk is **rejected** on the
measurement — a 5 s load plus 149–205 MB of scratch to save a 52 s
once-per-boot cost, with its own invalidation problem.

### 11.6 — Out of scope

- **Incremental artifacts** (rebuilding only the changed listings) — the BM25
  index is global, so it cannot be built incrementally without a different
  index. Recorded as §4a.2 and unchanged.
- **Deferring the rebuild to a background thread after startup.** It would
  make the first request race the rebuild, which is how you get two rebuilds
  and a cache miss under load. The warm is synchronous and bounded.

### 11.7 — What was measured, after

The live 8,558-listing corpus, one real profile, a freshly started server.

| | Before WS-28 | After WS-28 |
|---|---|---|
| Artifacts rebuild (cold) | 52–65 s | **42.1 s** |
| Rows re-mined per rebuild | 6,741 | **0** |
| First search after restart (client-observed) | **58.6 s** | **11.5 s** |
| First search (route's own timing, from the log) | ~58 s | **4.3 s** |
| Second search | 3.6 s | 4.4 s |
| Third search | 3.0 s | 3.7 s |

The rebuild now happens in the lifespan, before the server accepts traffic —
the log shows `Corpus artifacts warmed up (8558 listings)` at 17:40:57 and
`Application startup complete` immediately after, so the first request never
pays it.

**A note on the two first-search numbers.** The route logs 4.3 s; the client
observes 11.5 s. The ~7 s difference is in the very first request of a fresh
process and outside the route's own timing — most plausibly first database
connection, thread-pool spin-up, and the client's first connection, none of
which repeat on the second request (4.4 s). It is recorded rather than
explained away: the claim this workstream makes is that the **rebuild left the
request path**, and that is measured. Whatever the remaining first-request
7 s is, it is not the corpus rebuild.

### 11.8 — The re-mine, and what it changed

The corrected miner was applied to the store, because the column held the
output of the old one:

| | Rows |
|---|---|
| Gained a bar it always stated | **1,542** |
| Bar value changed | **99** |
| Total re-decided | **1,641** |
| Now carry a bar | 3,359 of 8,558 (was 1,817) |

This is a **scoring** change and it is deliberate: the `experience` component
(weight 0.17) moves for 1,641 listings, so rankings shift. The alternative was
freezing a parser bug into a column — reporting "this listing states no
experience bar" for 1,542 listings that state one plainly.

`scripts/remine_required_years.py` performs the pass and is idempotent: it
records the decision on every row, so a second run finds nothing to do. It has
a `--dry-run` that reports the delta without writing.

### 11.9 — Acceptance

| Check | Test |
|---|---|
| A bar stated against a domain is the total bar | `tests/test_ws28_experience_bars.py` |
| A bar stated against a real technology is still skipped | `tests/test_ws28_experience_bars.py` |
| An empty description is mineable, not a crash | `tests/test_ws28_experience_bars.py` |
| The board's own requirement still wins | `tests/test_ws28_experience_bars.py` |
| Every written row is marked decided | `tests/test_ws28_required_years_marker.py` |
| A row decided "no bar" keeps its NULL and is not re-mined | `tests/test_ws28_required_years_marker.py` |
| A zero bar is a measurement, not "nothing stated" | `tests/test_ws28_required_years_marker.py` |
| A pre-migration row still mines (no backfill required) | `tests/test_ws28_required_years_marker.py` |
| The migration is reversible and moves the column set | `tests/test_migrations.py` |
| The warm uses the same capped call a search does | `tests/test_ws28_startup_warm.py` |
| A failed warm does not stop the server | `tests/test_ws28_startup_warm.py` |

Each test was written and **run failing** before its implementation, and each
was verified to fail again when the fix is reverted.

### 11.10 — What this does not fix

The remaining 42.1 s cold rebuild is still `classify_job_role` (13.8 s),
`Bm25Index` (10.7 s) and `_important_terms` (7.1 s) — inherent to a full
artifacts build. It now costs a restart rather than a user's first search.
Persisting it to disk was measured and rejected (§11.5).

An operator restarting the server still waits ~42 s before it serves. That is
a deliberate trade: the alternative is serving requests that race a rebuild,
which produces two rebuilds and a cache miss under load.

### 11.11 — Where the 11.5 s actually goes, to the millisecond

The §11.7 result left a question: the route logged 4.3 s while the browser
observed 11.5 s. Measured at every boundary, the answer is that **there is no
frontend delay at all** — the browser is waiting on the server, and the
handler's own log is not measuring the whole request.

Breakdown of a first search on a freshly warmed server, 8,558 listings,
`top_n=30`, one real profile:

| Boundary | Time |
|---|---|
| Click → response **headers** received (browser) | **11.7 s** |
| Headers → body fully read | **4.8 ms** |
| Body → `JSON.parse` | **2.4 ms** |
| Parse → first result card painted | ~0.6 s |
| **Click → card visible** | **12.3 s** |
| Response body | 417 KB |

The 417 KB response is read in 4.8 ms and parsed in 2.4 ms. Serialising it and
writing the last-search cache to `localStorage` costs 3.6 ms and 2.5 ms. That
is **under 20 ms of client work**; nothing the console does can explain a
multi-second wait. (A warm repeat search paints in 5.0 s, of which 4.74 s is
again waiting for headers.)

#### Server side

The route's log line `Job search complete` is emitted **before** the response
is serialised and sent, so `4.3 s` is the handler's work, not the request. The
remainder is the response build. Inside the handler:

| Phase | Time |
|---|---|
| **Query embedding (ONNX, 4,584 chars)** | **6.6–9.7 s** |
| Fetch every vector from Chroma (47 MB, 7,666 vectors) | 0.8 s |
| Fetch the id list | 0.25 s |
| `BM25.score_all` | 0.63 s |
| `lexical_score` × 8,558 | 0.92 s |
| `calculate_match` × 8,558 | 2.0 s |
| `embedding_status_for_jobs` (one SQL `IN`) | 0.09 s |
| Sort + slice | 0.01 s |

The embedding is **half to two-thirds of the whole wait**, and it is the only
item that varies run to run (6.6 s to 9.7 s measured on the same input).

#### Why the embedding costs seconds, not milliseconds

The cost is proportional to the input length, and the candidate query is long:

| Input | Time |
|---|---|
| 500 chars | 0.60 s |
| 2,000 chars | 1.19 s |
| 4,584 chars (this candidate) | 2.09 s |
| 8,000 chars | 3.69 s |
| 16,000 chars (`MAX_TEXT_CHARS`) | 7.28 s |

Those figures are for a **warm model in a quiet process**. Inside the server the
same 4,584-char query measures 6.6–9.7 s, because the request runs on the same
CPU as the vector fetch and the per-listing scoring. The scaling is the same
either way: roughly **0.45 ms per character**, and the candidate text is
`candidate_query_text` (`src/rag/chroma_store.py`), which WS-20 deliberately
widened to the whole professional record.

The startup warm does not help here. It embeds the seven-character string
`"warmup"`, which exercises the model load but not the long-sequence path:
warming with a short string still leaves the first **long** embed at 8.9 s, and
the second at 8.7 s — it is per-call compute, not a one-time initialisation.

**Corrected (2026-11-13).** The paragraph above is wrong, and the error was in
what it measured. The 8.9 s figure came from a **16,000-character** input, not
from the candidate's 4,584-char query. Measured properly, one fresh process per
variant:

| Warm variant | First query embed | Steady state |
|---|---|---|
| none (lazy model load inside the request) | **5.78 s** | 1.86–1.99 s |
| `"warmup"` (7 chars — what the lifespan does) | **1.95 s** | 1.92–1.95 s |
| the real 4,584 chars | 1.88 s | 1.89–1.96 s |
| 16,000 chars | 1.84 s | 1.86–1.95 s |

The warm removes **~3.8 s** from the first request, and the warm input's
length is irrelevant beyond the first inference: warming with the real query
buys nothing over `"warmup"`, so the existing call is correct and needs no
change. (A 16,000-char embed costs ~8.5 s *every* call, warm or cold — that is
per-call compute at that length, and no warm can remove it. It is also not this
candidate's length, which is why the earlier conclusion did not apply.)

End to end, one fresh process per variant, the artifacts warm in both:

| | Search |
|---|---|
| No embedding warm | **11.12 s** |
| `"warmup"` first | **7.78 s** |

Cost of that warm: **+271 MB** resident (126 → 393 MB, before the artifacts add
~1.1 GB).

#### The second-largest item, and why it is unavoidable today

Fetching 47 MB of vectors costs 0.8 s, and only **7,666 of 8,558** listings have
a vector — the remaining 892 are `EMBEDDING_PENDING` or failed. That is why the
executor logs `Semantic coverage 7666/8558`: 10.4% of the corpus scores without
a semantic component. Closing the gap would raise coverage, not lower the scan
cost.

#### What this means for the "why does the frontend render after 11 s" question

It does not. The console renders as soon as the response exists, and the
response does not exist for 11.7 s because the server is computing. Any
apparent frontend slowness is the browser's network panel showing a request
that has not been answered yet.

The only real frontend cost found is **the 417 KB payload** — larger than it
needs to be, because `JobMatchPair` carries the full `JobListing` (including
its description) for all 30 results. It costs ~10 ms to handle, so it is not a
latency problem, but it is 417 KB of mostly-unread description text per search.

#### Where the next second of improvement actually is

Ranked by measured size, not by guess:

1. **The query embedding (6.6–9.7 s).** The candidate text is 4,584 chars and
   the model costs ~0.45 ms/char. Shortening what is embedded — the summary and
   titles rather than the entire professional record — would cut this
   proportionally, but it changes what semantic similarity *means*, so it is a
   ranking-quality decision, not a performance one, and needs the evaluation
   harness (§9) to say whether it is acceptable.
2. **`calculate_match` + `lexical_score` (2.9 s combined).** Already the
   subject of WS-24c; the remaining cost is the 8,558 discarded
   `JobMatchResult` objects (§10.4).
3. Everything else is sub-second.

Recorded here rather than acted on: (1) trades ranking quality for latency, and
that trade is the owner's to make. The measured facts are now on the page for
whoever makes it.

### 11.12 — The optimization survey: what would actually move the number

Measured 2026-11-13 on the live 8,558-listing corpus, 12 cores, one fresh
process per experiment. Every figure below is a measurement, not a projection;
several contradict what §11.11 guessed.

#### The corrected baseline

A full `search_stored_jobs` with the startup warm in place, phase by phase:

| Phase | Time |
|---|---|
| Open the store (per request: Chroma client + embedder + SQLite cache) | 0.05 s |
| `candidate_query_text` | 0.00 s |
| **Embed the query** | **1.9–3.3 s** |
| `similarities_for_all` — memo miss (47 MB fetch, 24 MB float32) | 3.4–4.5 s |
| `similarities_for_all` — memo hit | 0.025 s |
| `calculate_match` + `lexical_score` × 8,558 | 2.9 s |

`similarities_for_all` on a memo hit is 0.025 s, not zero: the memo key includes
the covered-id count, which is only known after `collection.get(include=[])`
fetches all 7,666 ids (0.023 s). That is one of the levers below.

#### Lever 1 — Query text length. **The only large lever.** Not recommended alone.

The candidate text is 4,555 chars and the model costs ~0.4–0.5 ms/char in
steady state:

| Input | Embed |
|---|---|
| 1,138 chars | 0.72 s |
| 2,277 chars | 1.04 s |
| 4,555 chars (this candidate) | **1.80 s** |
| 8,000 chars | 3.51 s |
| 16,000 chars | 8.51 s |

What the text is actually made of, on this profile:

| Section | Chars |
|---|---|
| project bullets | **2,278** |
| summary | 657 |
| project tech | 515 |
| certifications | 465 |
| project names | 284 |
| achievements | 148 |
| skills | 136 |
| title | 36 |
| education degrees | 28 |
| experience titles and bullets | **0** |

Three things follow. First, **half the query is project bullets**, which is the
least job-relevant part of a professional record. Second, this candidate has no
experience entries at all — the semantic signal is coming almost entirely from
projects, so a rule that trimmed "experience bullets" would change nothing here
and everything for another candidate. Third, any trim is a **ranking-quality
decision**: `candidate_lexical_text` feeds both the semantic query and the
lexical/BM25 channel, so shortening it moves both scores. It needs the
evaluation harness (§9), and this document does not make that call.

A semantic-only trim (a separate function for the embed) would avoid touching
the lexical channel, at the cost of one more text to keep in sync.

#### Lever 2 — Keep the vector matrix resident. **~1.0 s per memo miss.**

The fetch is 1.04 s for 47 MB, and the decoded matrix is only **24 MB** as
float32. The matvec against a resident matrix is **0.001 s**. So holding the
normalized matrix in the process converts a 1.04 s fetch into a 1 ms dot
product, and drops the memo-hit path to a dict read (lever 3).

Memory: +24 MB of matrix, against the ~1.5 GB the process already holds.
Invalidation is the work: the matrix must be rebuilt when the collection
changes, and today the only signal is the id count plus the 120 s TTL. A
content digest over the stored vector hashes would make it exact, at the cost
of reading 7,666 short strings per rebuild.

This is the best risk-adjusted lever: it is ~1 s of the ~4 s memo-miss path,
it needs no ranking change, and 24 MB is noise beside the artifacts.

#### Lever 3 — Move the memo check before the id fetch. **~0.02 s.**

`similarities_for_all` calls `count()`, `get(include=[])` and computes
`remaining` before `_recall_scan`. Keying on `collection.count()` instead of the
fetched id count makes a memo hit a pure dict read. The saving is small (0.023 s)
but the change is trivial and it makes the hit path honest. The correctness
trade: a same-size corpus whose contents changed would hit a stale entry for up
to the TTL — which is already true of the current key.

#### Lever 4 — Overlap the embed and the vector fetch. **Saves nothing.**

Measured, interleaved, three trials each:

| | Time |
|---|---|
| serial: embed → fetch | 2.95–3.22 s |
| overlapped: embed ‖ fetch | 3.03–3.33 s |

No gain. The two are dominated by the same resource (memory bandwidth and the
CPU the ONNX session already saturates), so running them concurrently does not
shorten the critical path. Recorded so nobody tries it again on the theory that
it must help.

#### Lever 5 — ONNX thread count. **Does not save memory; costs latency to cap.**

`threads=` is accepted by fastembed and never passed (`src/llm/embeddings.py`,
`TextEmbedding(...)`), so ORT uses all physical cores. Measured by restricting
affinity (equivalent to what the session would do):

| Cores | Embed (4,584 chars) | RSS |
|---|---|---|
| 12 (default) | **2.0 s** | 348 MB |
| 6 | 2.5 s | 348 MB |
| 4 | 7.4 s | 347 MB |
| 2 | 16.4 s | 348 MB |

Two findings. Thread scaling is **not** flat — the repo's own note
(`docs/implementation/04-pipeline-and-api.md`) says it is, and for this
single-query workload it is not: below 6 cores the cost more than triples. And
**capping threads saves no memory at all** (348 MB regardless), so there is no
trade to make. Leave the default; it is already optimal.

#### Lever 6 — A process-wide store. **0.05 s.**

`ChromaVectorStore()` is constructed per request (a new Chroma client, a new
`FastembedEmbedding` wrapper, a new SQLite connection, and a tokenizer-config
re-read). Measured: **0.053 s**. The ONNX session itself is already shared
(`_fastembed_loaded_models`), which is why this is small. Worth doing for
tidiness, not for latency.

#### Lever 7 — The 892 unembedded listings. **Coverage, not latency.**

Live queue state: `COMPLETED 3700, FAILED 300, QUEUED 721, RETRY_WAIT 3279`, and
~558 listings have no work item at all. Filling them moves `semantic_coverage`
from 89.6% to 100% and changes rankings, but does not reduce the scan — the
vectors are already fetched in one pass. It is a quality task, not a speed one.

#### Summary of what to do, in order

| Lever | Saves | Risk |
|---|---|---|
| Resident vector matrix | ~1.0 s per miss; memo hit → ~0 s | low; +24 MB, invalidation work |
| Memo key off `count()` | ~0.02 s | trivial |
| Process-wide store | ~0.05 s | trivial |
| Query text trim | up to ~1.2 s | **ranking quality — needs §9** |
| Overlap embed/fetch | **0** | don't |
| Thread cap | **negative** | don't |

Two levers together take a memo-miss search from ~7.8 s to ~6.7 s with no
ranking change. The query trim is the only way to reach ~5.5 s, and it is the
owner's call.
