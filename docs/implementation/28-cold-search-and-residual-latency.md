# WS-28 · Why a Cold Search Takes 70 s, the Two Defects Inside It, and What Actually Moves the Number

Status: **Done (2026-11-13)** — the two corpus defects, the startup warm, the
resident vector matrix and the memo key are all committed · Milestone: **M5** ·
Depends on: WS-23b (`required_years` mined at ingest), WS-24 (vectorized scan),
WS-24b (the lexical channel), WS-24c (the per-listing residual and the scan
memo), WS-18 (durable execution, for the startup lifespan) ·
Live-verified: against the live 8,558-listing corpus on a freshly started
server, one real candidate profile, 12 cores · **Extracted from
[24-search-performance.md](24-search-performance.md) §11 on 2026-11-13, where it
was first recorded**

> **Framing that decides the fix.** The report was "a search takes 70 s". The
> measurement said something else: the 70 s was a **once-per-restart corpus
> artifacts rebuild** that the operator happened to trigger by searching first.
> Treating it as a slow search would have optimised the wrong path. See §1.
>
> **Two defects sat underneath it**, and only one is a performance problem:
> `required_years` NULL was overloaded to mean both "never mined" and "mined,
> and no bar stated" (20.6 s of re-mining per cold start), and the experience
> miner discarded bars it could read (a **scoring** change affecting 1,641
> listings). The second had to be fixed before the first could be made
> permanent — freezing a parser bug into a column would have been the wrong
> trade. See §2 and §3.
>
> **What remains is not in this workstream's control.** A memo-miss search is
> still dominated by the ONNX query embedding (1.9–3.3 s) and the per-listing
> `calculate_match` + `lexical_score` (2.9–3.5 s). Shortening the embedded text
> is the only large lever left and it is a **ranking-quality** decision
> (§12 and [WS-09](09-evaluation.md)).

---

**Reported 2026-11-12**: a search logged `Job search requested` at 15:43:17
and `Job search complete` at 15:44:27 — 70 s. The server had started at
15:42:59, eighteen seconds earlier.

## 1 — The measurement

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

## 2 — The first defect: `required_years` NULL means two things

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

## 3 — The second defect: the miner discards bars it can read

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

## 4 — What the plan does, in order

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

## 5 — Sizing, before committing to the approach

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

## 6 — Out of scope

- **Incremental artifacts** (rebuilding only the changed listings) — the BM25
  index is global, so it cannot be built incrementally without a different
  index. Recorded as §4a.2 of [24-search-performance.md](24-search-performance.md) and unchanged.
- **Deferring the rebuild to a background thread after startup.** It would
  make the first request race the rebuild, which is how you get two rebuilds
  and a cache miss under load. The warm is synchronous and bounded.

## 7 — What was measured, after

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

## 8 — The re-mine, and what it changed

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

## 9 — Acceptance

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

## 10 — What this does not fix

The remaining 42.1 s cold rebuild is still `classify_job_role` (13.8 s),
`Bm25Index` (10.7 s) and `_important_terms` (7.1 s) — inherent to a full
artifacts build. It now costs a restart rather than a user's first search.
Persisting it to disk was measured and rejected (§5).

An operator restarting the server still waits ~42 s before it serves. That is
a deliberate trade: the alternative is serving requests that race a rebuild,
which produces two rebuilds and a cache miss under load.

## 11 — Where the 11.5 s actually goes, to the millisecond

The §7 result left a question: the route logged 4.3 s while the browser
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

### Server side

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

### Why the embedding costs seconds, not milliseconds

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

### The second-largest item, and why it is unavoidable today

Fetching 47 MB of vectors costs 0.8 s, and only **7,666 of 8,558** listings have
a vector — the remaining 892 are `EMBEDDING_PENDING` or failed. That is why the
executor logs `Semantic coverage 7666/8558`: 10.4% of the corpus scores without
a semantic component. Closing the gap would raise coverage, not lower the scan
cost.

### What this means for the "why does the frontend render after 11 s" question

It does not. The console renders as soon as the response exists, and the
response does not exist for 11.7 s because the server is computing. Any
apparent frontend slowness is the browser's network panel showing a request
that has not been answered yet.

The only real frontend cost found is **the 417 KB payload** — larger than it
needs to be, because `JobMatchPair` carries the full `JobListing` (including
its description) for all 30 results. It costs ~10 ms to handle, so it is not a
latency problem, but it is 417 KB of mostly-unread description text per search.

### Where the next second of improvement actually is

Ranked by measured size, not by guess:

1. **The query embedding (6.6–9.7 s).** The candidate text is 4,584 chars and
   the model costs ~0.45 ms/char. Shortening what is embedded — the summary and
   titles rather than the entire professional record — would cut this
   proportionally, but it changes what semantic similarity *means*, so it is a
   ranking-quality decision, not a performance one, and needs the evaluation harness
   ([WS-09](09-evaluation.md)) to say whether it is acceptable.
2. **`calculate_match` + `lexical_score` (2.9 s combined).** Already the
   subject of WS-24c; the remaining cost is the 8,558 discarded
   `JobMatchResult` objects (§10.4 of [24-search-performance.md](24-search-performance.md)).
3. Everything else is sub-second.

Recorded here rather than acted on: (1) trades ranking quality for latency, and
that trade is the owner's to make. The measured facts are now on the page for
whoever makes it.

## 12 — The optimization survey: what would actually move the number

Measured 2026-11-13 on the live 8,558-listing corpus, 12 cores, one fresh
process per experiment. Every figure below is a measurement, not a projection;
several contradict what §11 guessed.

### The corrected baseline

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

### Lever 1 — Query text length. **The only large lever.** Not recommended alone.

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
lexical/BM25 channel, so shortening it moves both scores. It needs the evaluation
harness ([WS-09](09-evaluation.md)), and this document does not make that call.

A semantic-only trim (a separate function for the embed) would avoid touching
the lexical channel, at the cost of one more text to keep in sync.

### Lever 2 — Keep the vector matrix resident. **~1.0 s per memo miss.**

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

### Lever 3 — Move the memo check before the id fetch. **~0.02 s.**

`similarities_for_all` calls `count()`, `get(include=[])` and computes
`remaining` before `_recall_scan`. Keying on `collection.count()` instead of the
fetched id count makes a memo hit a pure dict read. The saving is small (0.023 s)
but the change is trivial and it makes the hit path honest. The correctness
trade: a same-size corpus whose contents changed would hit a stale entry for up
to the TTL — which is already true of the current key.

### Lever 4 — Overlap the embed and the vector fetch. **Saves nothing.**

Measured, interleaved, three trials each:

| | Time |
|---|---|
| serial: embed → fetch | 2.95–3.22 s |
| overlapped: embed ‖ fetch | 3.03–3.33 s |

No gain. The two are dominated by the same resource (memory bandwidth and the
CPU the ONNX session already saturates), so running them concurrently does not
shorten the critical path. Recorded so nobody tries it again on the theory that
it must help.

### Lever 5 — ONNX thread count. **Does not save memory; costs latency to cap.**

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

### Lever 6 — A process-wide store. **0.05 s.**

`ChromaVectorStore()` is constructed per request (a new Chroma client, a new
`FastembedEmbedding` wrapper, a new SQLite connection, and a tokenizer-config
re-read). Measured: **0.053 s**. The ONNX session itself is already shared
(`_fastembed_loaded_models`), which is why this is small. Worth doing for
tidiness, not for latency.

### Lever 7 — The 892 unembedded listings. **Coverage, not latency.**

Live queue state: `COMPLETED 3700, FAILED 300, QUEUED 721, RETRY_WAIT 3279`, and
~558 listings have no work item at all. Filling them moves `semantic_coverage`
from 89.6% to 100% and changes rankings, but does not reduce the scan — the
vectors are already fetched in one pass. It is a quality task, not a speed one.

### Summary of what to do, in order

| Lever | Saves | Risk |
|---|---|---|
| Resident vector matrix | ~1.0 s per miss; memo hit → ~0 s | low; +24 MB, invalidation work |
| Memo key off `count()` | ~0.02 s | trivial |
| Process-wide store | ~0.05 s | trivial |
| Query text trim | up to ~1.2 s | **ranking quality — needs [WS-09](09-evaluation.md)** |
| Overlap embed/fetch | **0** | don't |
| Thread cap | **negative** | don't |

Two levers together take a memo-miss search from ~7.8 s to ~6.7 s with no
ranking change. The query trim is the only way to reach ~5.5 s, and it is the
owner's call.

## 13 — The resident vector matrix, and the memo key

Two changes, both from §12, both exact: no score changes, and the full
score vector is still produced for every listing.

### What is being changed, and what is not

`similarities_for_all` currently does three things on every memo miss:

1. fetch all 7,666 ids (`collection.get(include=[])`, 0.023 s),
2. embed the query (1.9–3.3 s),
3. page 47 MB of vectors out of Chroma and reduce each page to a matvec (0.8–1.0 s).

The first and third are repeated work. The ids never change unless the
collection does, and the **decoded matrix is only 24 MB as float32** — the 47 MB
is the serialized bytes Chroma hands back. Measured: fetching it is 1.04 s, and
the matvec against a matrix already in memory is **0.001 s**.

So the store keeps, per (persist directory, collection):
- the **id list**, and
- the **L2-normalized float32 matrix**, row-aligned with the ids.

A search then does: memo lookup → embed → `matrix @ unit_query` → map to a dict.
No per-search fetch, no per-page normalization.

**This is not HNSW, and it is not approximate.** The whole matrix is still
multiplied; every listing still gets a score. HNSW answers "the nearest k",
which is a different question — the blend needs a value for all of them because
`semantic` keeps its 0.13 weight in the denominator whether or not a listing is
near the query. §12 records the measurement that settles it: HNSW top-50 is
5.0 ms but scores 50 of 7,666, while the full matvec against a resident matrix
is **1.1 ms** and scores all of them.

### The memo key

The memo key was `(scope, digest, covered_id_count)` and `covered` was only
known **after** fetching every id — so a memo *hit* still paid 0.023 s. The key
becomes `(scope, digest, collection.count())`, which is a single O(1) call.
`collection.count()` and the id list are the same number for a collection that is
not mid-write, and the memo already tolerated a same-size-different-content
corpus for up to the TTL. This makes the hit path a pure dict read.

### The consistency rules, and why they are safe

The matrix must never be newer than the store, and must never outlive a write.
Three mechanisms, in order of strength:

1. **Any write from this process drops it.** `upsert_jobs` and `delete_jobs`
   already call `clear_process_scan_cache()`; they now also clear the matrix.
   This is the common case: the embedding worker writes, the API reads.
2. **A size change drops it.** The cache entry records the id count it was built
   at; a mismatch rebuilds. This catches a write from the **worker process**,
   which this process cannot observe — the same limitation the scan memo has,
   and the reason the TTL exists.
3. **A TTL drops it.** Reuses `_PROCESS_SCAN_TTL_SECONDS` (120 s), so a
   same-size write by another process resolves within two minutes.

One matrix is held at a time, not one per corpus state: at 24 MB the tradeoff
between "keep two corpora" and "rebuild after a corpus flip" is not worth the
bookkeeping, and a rebuild on flip is 1.04 s against a 24 MB saving.

### What this costs

**+24 MB** resident at 7,666 vectors, scaling with the corpus (150 MB at the
50,000 cap). Against the ~1.5 GB the process already holds, and against the
271 MB the embedding warm costs for a 3.3 s saving, this is the cheapest memory
in the system.

**One rebuild per corpus change.** The first search after the worker finishes a
batch pays the fetch once more.

### What it does not fix

The query embedding (1.9–3.3 s) is untouched — it is the only item left that is
worth seconds, and §12 explains why trimming it is a ranking-quality
decision. `calculate_match` + `lexical_score` (2.9 s) is the other, and its
remaining cost is the discarded `JobMatchResult` objects (§10.4 of [24-search-performance.md](24-search-performance.md)).

## 14 — What the matrix and the key change actually measured

**Measured 2026-11-13**, live 8,558-listing corpus, one fresh process, the real
lifespan first.

### The change works, and it is small

| | Time |
|---|---|
| Building the matrix (one 47 MB fetch + normalize) | **1.43 s** |
| Scores from the resident matrix | **0.006 s** |
| Page fetch, the old path (forced for comparison) | **1.04 s** |
| **Saving per memo miss** | **~0.6–1.0 s** |

The saving is real but smaller than §12 projected, and the reason is worth
recording: the page scan was already vectorized *per page*, so its cost was the
fetch (1.04 s) plus a fast matvec, not the per-vector loop §12 assumed. The
matrix removes the fetch; it cannot remove a matvec that was already cheap.

**Scores are bit-identical.** Forcing both paths on the same new query:
`max abs difference 0.000e+00` across all 7,666 scores, `identical: True`.

### The complete phase breakdown of one search

One fresh process, the real lifespan, one search over all 8,558 listings. The
percentages are of the search only — the startup row is what a restart pays
before the server serves.

**Startup (not in the user's wait, but it is what a restart costs):**

| Phase | Time | Memory |
|---|---|---|
| Embedding warm (`"warmup"`) | 4.06 s | +267 MB |
| Corpus artifacts rebuild | 43.05 s | +1,131 MB |

**One search (the user's wait):**

| Phase | Time | Share | Memory |
|---|---|---|---|
| 1. Open the vector store (Chroma client + embedder + SQLite cache) | 0.30 s | 2.1% | +6 MB |
| 2. `candidate_query_text` | 0.00 s | 0.0% | — |
| **3. Embed the query (ONNX)** | **3.98 s** | **28.6%** | +6 MB |
| **4. `similarities_for_all` — memo miss (builds the matrix)** | **5.27 s** | **37.8%** | **+64 MB** |
| 4b. `similarities_for_all` — memo hit | 0.00 s | 0.0% | — |
| 5. `embedding_status_for_jobs` (892 ids, one SQL `IN`) | 0.25 s | 1.8% | — |
| 6–8. `candidate_tokens` / `candidate_lexical_text` / `CandidateContext` | 0.00 s | 0.0% | — |
| 9. `BM25.score_all` | 0.59 s | 4.2% | — |
| 10. `lexical_score` × 8,558 | 1.68 s | 12.1% | +6 MB |
| 11. `calculate_match` × 8,558 | 1.83 s | 13.1% | +31 MB |
| 12. Rank + take top 30 | 0.03 s | 0.2% | +1 MB |
| **Total** | **13.93 s** | 100% | 1,640 MB RSS |

Phase 4 includes a **second** query embed (it recomputes the vector internally
on a memo miss), so the embed is charged twice in this table — 3.98 s in
phase 3 and again inside phase 4. The two together are ~9 s, or **65% of the
search**, which is why §12 calls the query embedding the only remaining large
lever.

**Corrected 2026-11-13: the second charge is an artifact of the profiler, not a
cost the product pays.** `scripts/profile_search_timing.py` times the embed in
isolation (phase 3) and *then* calls `similarities_for_all` (phase 4), which
embeds again internally — deliberately, so each phase is separately measurable.
The production path does not do this: `search_stored_jobs`
(`src/graph/job_executor.py:966`) calls `similarities_for_all` once and never
embeds separately, and `calculate_match` contains no embed call. **A production
memo-miss search therefore embeds once — ~9.8 s rather than 13.9 s**, with the
embed at ~40% of the request rather than 65%. The conclusion is unchanged (the
embed is still the only remaining lever worth a second), but the table's total
overstates a real request by one embed, and the "65%" figure is this document's
arithmetic, not the product's.

For scale: phase 4 at 5.27 s = the 3.98 s embed + the 1.43 s matrix build. A
warm memo hit makes the whole of phase 4 disappear (0.00 s).

### What this proves about the remaining levers

- The matrix turned a 1.04 s fetch into a 0.006 s matvec. **Done.**
- The memo key change made a hit a pure dict read (0.00 s). **Done.**
- `collection.count()` is 0.004 s, so the key costs nothing.
- Everything left that is worth a second is the **embed** (~4 s each, twice per
  memo miss), which is a ranking-quality decision, and `calculate_match` +
  `lexical_score` (3.5 s combined), whose remaining cost is the discarded
  `JobMatchResult` objects (§10.4 of [24-search-performance.md](24-search-performance.md)).

A memo-miss search is ~13.9 s in this process; the API's own log measured
~4–7 s for the same work, because the API process has the ONNX session and the
artifacts already hot from a longer-lived run and the OS page cache is warm.
Both are the same shape: the embed and the semantic scan dominate, and the
per-listing scoring is the second tier.

### The correctness gate

`tests/test_ws28_vector_matrix.py` has eight cases, and three of them were
verified to **fail** when the code is broken:

- removing the row normalization fails the exactness test;
- removing the query normalization fails the exactness test;
- the memo-hit test fails if the hit path touches the collection.

The second and third matter because the first version of the fixture used
**unit-length** vectors, which made both normalizations no-ops — the test
passed with the normalizer deleted. The fixture now uses vectors at two
different scales (7.5 for documents, 3.25 for the query), which is also the
more honest input, since a real provider's vectors are not exactly unit length.
