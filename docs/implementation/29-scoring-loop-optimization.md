# WS-29 · The Scoring Loop: The Embed, the Lexical Scan and the Discarded Results

Status: **In progress (2026-11-13)** · Milestone: **M5** ·
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

### 2.1 — A repeat search reuses its query vector

`embed_query` deliberately never caches (`src/llm/embeddings.py:671-698`,
WS-14 · Phase G: a query vector is candidate data, and a *shared, persistent*
cache would both reveal that a second tenant submitted the same text and store an
invertible fingerprint of the candidate). That rule stands, and this workstream
does not weaken it.

What it adds is the same distinction WS-24c already drew for the similarity map:
a **process-local, memory-only** memo is neither shared nor durable. WS-24c's
docstring says the store memoizes the *map* "without ever caching the vector
itself"; WS-29 takes the vector into the same kind of memo, keyed by a digest of
the text, bounded to eight entries with a 120 s TTL, cleared with the process.
The exposure is identical to holding the profile in memory, which the process
already does.

**Saving:** ~1.9–4.0 s on every repeat search by an unchanged profile.

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

**Saving:** ~0.47 s (`JobMatchResult` validation) + ~0.33 s (explanation) of the
1.91 s, and ~50 MB of transient retention.

### 2.3 — The lexical coverage walks postings

`lexical_score` iterates every one of a listing's ~383 terms to find the ~0.7
the candidate has, and checks `len(matched) < EVIDENCE_LIMIT` on each —
3.28 M iterations and 3.28 M `len()` calls per search.

`LexicalTermIndex` holds the same data inverted (`term → [(job_id, weight)]`,
36,309 distinct terms) and accumulates only the postings that exist: **300,121
touches instead of 3,277,988**, 0.12 s against 0.34 s, with an identical
accumulation. It also replaces the 209 MB of per-listing tuples.

**Saving:** ~0.22 s and ~209 MB.

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
| A repeat query reaches the provider once | `tests/test_ws29_query_vector_memo.py` |
| A different text is a different vector | `tests/test_ws29_query_vector_memo.py` |
| The memo holds no readable text, and is bounded and expiring | `tests/test_ws29_query_vector_memo.py` |
| The cheap score equals the full result's numbers | `tests/test_ws29_two_phase_scoring.py` |
| The two-phase order equals the one-phase order, ties included | `tests/test_ws29_two_phase_scoring.py` |
| The survivors get the identical full result | `tests/test_ws29_two_phase_scoring.py` |
| The inverted coverage matches the term loop | `tests/test_ws29_inverted_terms.py` |
| An empty term list is a zero, an unknown id is absent | `tests/test_ws29_inverted_terms.py` |
| A near-universal term stays correct | `tests/test_ws29_inverted_terms.py` |
| Every score is unchanged on the live corpus | differential, `differing rows: 0` |
| Lint clean, suite green | `ruff`, `pytest -m "not browser"` |

## 5 — Results

*(Filled in by the last task of the plan.)*
