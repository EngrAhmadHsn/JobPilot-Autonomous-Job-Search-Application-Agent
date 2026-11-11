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
embedding (~3 s, already content-hash cached) and (b) the per-listing
`calculate_match` over 8,558 listings.
