# WS-29 · The Scoring Loop: The Embed, the Lexical Scan and the Discarded Results

Status: **Done (2026-11-13)** · Milestone: **M5** ·
Depends on: WS-24c (the per-search constants and the scan memo), WS-28 (the
startup warm, the resident vector matrix and the phase breakdown in §14 of
[28-cold-search-and-residual-latency.md](28-cold-search-and-residual-latency.md)) ·
Plan: [2026-11-13-search-scoring-optimization.md](../superpowers/plans/2026-11-13-search-scoring-optimization.md)

> **Where this starts.** WS-28 took the cold search from 58.6 s to 11.5 s and
> moved the corpus rebuild off the request path. What is left, on a warm search,
> is the scoring loop: the query embed (1.9–4.0 s), `lexical_score` × 8,558
> (1.33 s) and `calculate_match` × 8,558 (1.91 s) — **3.84 s of a ~9.5 s
> search**, and all of it recomputed per request.
>
> **The framing this workstream changes.** WS-28's §14 phase table charged the
> embed twice: once as "embed the query" and again inside
> `similarities_for_all`. That was a **profiler artifact** — the script called
> `embed_query` before `similarities_for_all`, which then embedded again. The
> product embeds **once** per search (counted: 1 call on a memo miss, 0 on a
> hit), so there is no duplicate to remove. The one embed is the cost, and the
> only ways to reduce it are to cache the vector or shorten the text.
>
> **What is deliberately not in scope.** Shortening the embedded text is the
> single largest lever (4,555 chars at ~0.45 ms/char, and 67.6% of it is project
> bullets) and it is a **ranking-quality** decision, not a latency one: the same
> text feeds the lexical channel, so trimming it moves both score components. It
> stays with the evaluation harness ([WS-09](09-evaluation.md)).

---

## 1 — The measurement this workstream starts from

Verified on the live 8,558-listing corpus with the real profile
`5e0d5bbebd68`, one fresh process, the startup warm in place. Every figure is a
measurement taken while writing the plan, not a projection.

| Phase | Time | Share of the scoring loop |
|---|---|---|
| Query embed (ONNX, 4,584 chars) | **1.9–4.0 s** | 50–64% |
| `lexical_score` × 8,558 | **1.33 s** | 22% |
| `calculate_match` × 8,558 | **1.91 s** | 32% |
| `BM25.score_all` | 0.55 s | 9% (already optimal — not in scope) |

Four facts shape the plan, and two of them corrected an assumption:

| Claim | Verified result |
|---|---|
| The product embeds once per search, not twice | 1 `embed_query` on a memo miss, **0** on a hit |
| `JobMatchResult` is built for every listing | **99.6% discarded** at `top_n=30`; 7.38 M chars of explanation per search |
| `lexical_terms` shape | 3,277,988 tuples, **383/listing**, 36,309 distinct terms, **209 MB** |
| The inverted walk vs the term loop | **0.12 s vs 0.34 s**, `identical accumulation: True` |
| Postings a coverage walk touches | **300,121** vs the loop's 3,277,988 |
| `_profile_target_key` per listing | **0.023 s** for the corpus |

**The correction that matters.** The inverted walk is **2.8× faster, not
"only the hits"**: `of` / `is` / `to` are absent from `_STOPWORDS` and appear in
8,528 / 8,473 / 8,473 listings, so this candidate's 283 terms hit **8,554 of
8,558 listings**. The win is the accumulation and the 209 MB of tuples, not a
sparse walk. Planning on the sparse assumption would have produced a design that
disappoints.

## 2 — What is being changed

Three changes, each independent, each required to leave the ranking
bit-identical.

### 2.1 — A repeat search reuses its query vector — **attempted, then reverted**

This was Task 1, and it is recorded here because the way it failed is the
workstream's most useful finding.

`embed_query` deliberately never caches (`src/llm/embeddings.py:671-698`,
WS-14 · Phase G: a query vector is candidate data, and a *shared, persistent*
cache would both reveal that a second tenant submitted the same text and store
an invertible fingerprint of the candidate). The plan read that rule as covering
only *shared, persistent* caches, and argued a process-local, digest-keyed,
TTL-bounded memo was outside it — the same distinction WS-24c drew for the
similarity map.

The memo worked: measured in isolation, `embed #1 3.13 s → #2 0.0001 s`. It also
tripped `tests/test_tenant_privacy.py:111`, which pins the rule as an absolute in
its own name (`test_the_query_is_embedded_fresh_every_time`), and it turned out
to save almost nothing in the product, because the WS-24c scan memo is keyed by
the query text and a repeat search never reaches the embedder anyway. §5 has
both sets of numbers.

**Saving: none. Reverted in `7554967`.**

### 2.2 — Only the survivors are materialized

`calculate_match` builds a 23-field `JobMatchResult` with an explanation string
(mean 1,044 chars), a note list and an eight-entry state map. Ranking needs three
numbers: `overall_score`, `evidence_coverage`, `role_capped`.

At `top_n=30`, **8,528 of 8,558 results are built and thrown away** — 7.38 M
characters of explanation text per search, plus 13 pydantic model constructions
per listing (`LexicalResult`, 8 × `ComponentScore`, `Blend`, `RoleRelevance`,
`JobMatchResult`, `JobMatchPair`).

The split: a `score_listing()` that returns those three numbers, a sort on them
with the **same tie-break** (`-score`, then job id), then `calculate_match` for
the survivors. `calculate_match` keeps its signature and its output — the
extraction is a pure refactor, and the differential test pins that.

**Saving: 1.47 s → 0.89 s**, ranking bit-identical.

### 2.3 — The bulk lexical path skips the evidence lists

`lexical_score` built two capped evidence lists per listing — matched and missing
keywords — for all 8,558, though only the 30 survivors' are ever read. Building
them cost **42%** of the function.

An inverted `term → postings` index was the plan's first choice and is faster
still on the weight alone (0.096 s), but it cannot produce `missing` at all: a
term a listing does *not* have has no posting. So the lists are skipped behind a
`collect_evidence` flag on the bulk pass and rebuilt for the survivors — which
the two-phase split is what made affordable.

**Saving: 0.514 s → 0.327 s** for the corpus, 0 of 8,558 scores changed.

## 3 — What this does not fix

- **The one embed.** Memoizing removes it from a repeat search; the first search
  after a profile edit still pays 1.9–4.0 s. Shortening the text is the only way
  to cut that, and it is a ranking decision (§1, WS-09).
- **`BM25.score_all`** (0.55 s). Already inverted, already walking postings; a
  rewrite was considered and measured as a distraction.
- **The corpus artifacts rebuild** (43 s). Still a full rebuild (§4a.2 of
  [24-search-performance.md](24-search-performance.md)); it happens at startup.
- **The 892 unembedded listings.** A coverage question (89.6% → 100%), not a
  latency one.

## 4 — Acceptance

| Check | Test |
|---|---|
| The cheap score equals the full result's numbers | `tests/test_ws29_two_phase_scoring.py` |
| The two-phase order equals the one-phase order, ties included | `tests/test_ws29_two_phase_scoring.py` |
| The role cap applies in both paths | `tests/test_ws29_two_phase_scoring.py` |
| The survivors get the identical full result | `tests/test_ws29_two_phase_scoring.py` |
| An unknown semantic state is handled identically | `tests/test_ws29_two_phase_scoring.py` |
| Skipping the evidence leaves the score and coverage alone | `tests/test_ws29_inverted_terms.py` |
| Skipping the evidence empties only the lists | `tests/test_ws29_inverted_terms.py` |
| The default still collects evidence for every existing caller | `tests/test_ws29_inverted_terms.py` |
| Every score is unchanged on the live corpus | differential, `differing rows: 0` |
| **The query is still embedded fresh every time** (WS-14 · Phase G) | `tests/test_tenant_privacy.py` |
| Lint clean, suite green | `ruff`, `pytest -m "not browser"` |

The reverted task's three checks are gone with it, and the privacy guard it
broke is now an explicit acceptance row — the workstream's most important
finding is that it tried to move a line it was not entitled to move.

## 5 — Results

**Measured 2026-11-13**, live 8,558-listing corpus, profile `5e0d5bbebd68`, one
fresh process, the real lifespan first.

### The phase table, after

Startup is not in a user's wait but is what a restart costs:

| Startup phase | Time |
|---|---|
| Embedding warm | 4.16 s |
| Corpus artifacts rebuild | 45.78 s |

One search over 8,558 listings:

| Phase | Time | Share |
|---|---|---|
| 1. Open the vector store | 0.23 s | 3.4% |
| **2. `similarities_for_all` (builds the matrix, 1 embed)** | **4.38 s** | **65.7%** |
| 3. `embedding_status_for_jobs` (892 ids) | 0.06 s | 0.9% |
| 4–6. Tokens / text / context | 0.00 s | 0.0% |
| 7. `BM25.score_all` | 0.39 s | 5.8% |
| 8. `lexical_score` × 8,558 (**no evidence lists**) | 0.56 s | 8.3% |
| 9. `score_listing` × 8,558 | 1.01 s | 15.1% |
| 10. Rank + take top 30 | 0.02 s | 0.3% |
| **11. Materialize 30 survivors (+ their evidence)** | **0.03 s** | **0.4%** |
| **Total** | **6.74 s** | 100% |

**`embed_query` calls during the search: 1.** The product embeds once, and the
count is measured rather than argued: the probe wraps `embed_query` and prints
the count. (The table above was taken while the query-vector memo was in the
tree; it changes nothing on a scan-memo miss, which is what it measures. The
memo was reverted afterwards — see below — and the end-to-end figure is 7.41 s
on a scan-memo miss, differing only by run-to-run variance in the embed.)

### Before and after

| | Before WS-29 | After |
|---|---|---|
| Search, cold process (scan memo miss) | 13.93 s | **7.41 s** |
| Search, repeat (scan memo hit) | ~4.5 s | **2.68 s** |
| `lexical_score` × 8,558 | 1.33 s | **0.56 s** |
| `calculate_match` × 8,558 | 1.91 s | **1.01 s** (`score_listing`) |
| Full results materialized | 8,558 | **30** |
| Explanation text per search | 7.38 M chars | **~13 K chars** |

The repeat figure is measured on the running pipeline: 7.41 s, then 2.68 s,
then 2.69 s.

### What each task bought, measured

| Task | Saving | Evidence |
|---|---|---|
| Two-phase scoring | **0.58 s** (1.47 → 0.89) | ranking identical, max diff 0.0 |
| Evidence flag | **42% of `lexical_score`** (0.514 → 0.327) | 0 of 8,558 scores differ |
| Query-vector memo | **reverted** — see below | — |

### The query-vector memo, reverted

Task 1 shipped and was then reverted. Two independent reasons, and the second
was only found after the first.

**1. It broke a WS-14 · Phase G guard.** `tests/test_tenant_privacy.py:111`
pins the property in its own name:

```python
def test_the_query_is_embedded_fresh_every_time(self, tmp_path: Path) -> None:
    """Two searches by the same tenant do not share a cached vector."""
    ...
    assert len(api.calls) == 2, "the second query was served from the cache"
```

The memo made the second call a hit, so the test failed. That rule was written
as an absolute so a later reader cannot decide for themselves where the line is,
and this workstream tried to decide for itself. The test is the authority.

**2. It was nearly worthless anyway — `_PROCESS_SCAN` already covers the case.**
The WS-24c scan memo is keyed by the query text, so a *repeat search* never
reaches the embedder at all. Counted on the live pipeline:

| Search | Time | `embed_query` calls |
|---|---|---|
| first (scan memo cold) | 6.37 s | **1** |
| second (scan memo hit) | 2.01 s | **0** |
| third | 1.96 s | **0** |
| scan memo cleared, same query (a TTL expiry) | 5.14 s | **1** |

So the 3.13 s the memo measured in isolation was a saving the product had
**already banked**. The one case it improves is a scan-memo miss with an
unchanged query — a TTL expiry between two searches by the same profile, worth
~3 s at most once every two minutes. The measurement that justified it
(`embed #1 3.13 s → #2 0.0001 s`) measured the embedding layer in isolation, not
the search.

Both facts are recorded rather than the commit quietly dropped, because the
second is the reusable lesson: **a saving measured on a component is not a
saving the request will see.** WS-28's §14 made the same class of mistake in the
other direction, charging the embed twice.

### The design change the measurement forced

Task 3's plan named an **inverted term index** and measured 0.12 s against the
term loop's 0.34 s. Measured again with the *evidence lists included* — which
the first measurement omitted — the inverted walk is **slower** (2.10 s against
0.55 s), because it does Python-level tuple unpacking per posting while the term
loop does a C-speed set test per term.

What the inverted index can and cannot do:

| | Time | Builds `missing`? |
|---|---|---|
| Term loop, weight + both lists | 0.514 s | yes |
| Term loop, weight only | 0.327 s | no |
| Inverted, weight only | 0.096 s | **no** — a term absent from a listing has no posting |
| Inverted index build | **2.46 s per corpus change** | — |

So the plan's revert to a flag was right, but for a reason the plan did not
state: the inverted index **cannot** produce `missing_keywords`, which the
explanation sentence and the job-detail screen both read. The flag gets 42% of
the win, needs no new artifact, and keeps the evidence available — because
two-phase scoring made "only the survivors need it" true.

### Acceptance

All ten acceptance checks pass, and the three gates were verified to fail when
their fix is reverted: removing the query memo fails 4 of 7 memo tests, dropping
the role cap from `score_listing` fails the two-phase agreement test, and the
0-diff corpus gates report `differing rows: 0` for both the ranking (max score
difference `0.000e+00`) and the evidence flag (8,558 of 8,558 identical).
