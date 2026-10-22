# WS-15 · Attack Surface, Round Two

Status: **Done (2026-10-22)** · Milestone: **M3** · Depends on: WS-12 (runtime attack surface), WS-14 (AppSec) · Blocks: —

> WS-12 audited the runtime and WS-14 added multi-user identity. This
> workstream audits **both tiers again**, with the console (`/frontend`)
> in scope explicitly, and closes what the first pass left open.

## Goal

Close the exploitable gaps a second, independent scan found, in six
families:

| Family | The attack | The control |
|---|---|---|
| **Amplification** (ReDoS) | A board returns one field of 500 KB of `<script>`; the neutralizer's lazy regex is quadratic, so the refresh thread burns minutes of CPU | a single-pass linear neutralizer, and a bounded input |
| **Starvation** (the embedding flood, round two) | A flood occupies the front of the board, so the per-refresh embedding budget is spent on listings that are already cached and the legitimate new ones never get a vector | the budget counts **cache misses**, the work that actually costs something |
| **Exhaustion** (the daily flood) | The default local embedding provider has no quota at all, so 2 000 embeddings per refresh, every refresh, forever | a persistent daily work budget, the same shape as the API provider's |
| **One-way door** (the corpus) | The corpus cap has no eviction, so once the corpus is full **nothing is ever admitted again** — from any source | eviction of the oldest listings, so the corpus stays bounded *and* live |
| **Exposure** (the open routes) | `POST /api/jobs/refresh` and `GET /api/jobs/{job_id}` are the only two state-changing or reading routes with no credential; the first is the most expensive operation in the system | the scope dependency, like every other route |
| **Confusion** (prompt injection, round two) | The research prompt's header fields and the tailoring prompt's requirements block sit **outside** the nonce fence, so the "untrusted block" claim does not hold for them | every untrusted field inside a fence |

Plus, on the console: a Content-Security-Policy and the response headers
that go with it, a link that only opens a safe scheme, a CSRF-token reader
that cannot be crashed by a malformed cookie, and a status map that cannot
be confused by a prototype key.

## What the scan found

The scan (2026-10-22) read every file under `src/` and every file under
`frontend/src`, and it was deliberately adversarial about the two questions
this project cares about most: **what can an untrusted caller make the
process do**, and **what can a hostile board put in front of a model**.

### Confirmed clean (and worth saying plainly)

- **Command injection / code execution** — no `eval`, `exec`, `subprocess`,
  `os.system`, `shell=True`, `pickle`, `marshal` or `yaml` anywhere in
  `src/`. The only `evaluate` calls are Playwright's DOM API.
- **SQL injection** — the DB layer is the SQLAlchemy ORM throughout; the
  only hand-written SQL is in the embedding cache and it is parameterised.
- **XSS in the console** — not one `dangerouslySetInnerHTML`, `innerHTML`,
  `eval`, `new Function`, `document.write`, `javascript:` or `data:` URL in
  `frontend/src`. Untrusted text is rendered through JSX text nodes and the
  `PlainText` component; the ESLint rules forbid the sinks that would
  create one, and a test asserts a hostile payload renders as text.
- **The SSRF predicate** — resisted every bypass tried (userinfo, fragment,
  trailing dot, decimal and octal IP literals, IPv4-mapped IPv6, homoglyphs).
  It fails closed on all of them.
- **Authorization** — no IDOR, no existence oracle (a foreign row is a 404,
  not a 403), and the scope is built from the verified principal only.
- **Path traversal** — the `resume_path` exfiltration channel that WS-12
  found is properly closed, with per-user, symlink-resolved containment.
- **The output-side prompt-injection contract** — enforced deterministically
  in code, not advisory: the grounding filters, the injection strip on every
  deliverable field, the job-title check and the PII minimisation all run
  after the model answers.

### The gaps that were real

1. **The HTML neutralizer was quadratic.** `_BLOCK_RE` and friends matched
   `<tag …>.*?</tag>` with a lazy `.*?` and `DOTALL`, which is O(n²) in the
   input. Measured: 128 KB of `<script>` took **25 seconds** of CPU. The
   length cap was applied *after* the neutralization, so it did not help,
   and the only bound on the input was the 8 MiB response cap. One hostile
   board could therefore pin a refresh thread for minutes.
2. **The embedding budget counted listings, not work.** `to_embed =
   unique[:embed_budget]` took the *first* N listings in board order, so a
   flood that occupied the front of the board consumed the whole budget —
   including on listings that were already cached and cost nothing to
   re-embed — while legitimate new listings later in the same response got
   no vector at all. Because the board's order is stable, this was
   permanent, not transient.
3. **The local embedding provider had no daily budget.** The API provider
   counts batch requests against a persistent UTC-day counter; the default
   local provider counts nothing, so 2 000 embeddings per refresh, every
   refresh, forever, with no quota to exhaust.
4. **The corpus cap was a one-way door.** `room = max(0, cap - corpus_size)`
   means a full corpus admits **nothing**, from any source, ever again.
   Nothing in the retention pass prunes the `jobs` table.
5. **Two routes had no credential.** `POST /api/jobs/refresh` (the most
   expensive operation in the system) and `GET /api/jobs/{job_id}` are the
   only reading or state-changing routes without the scope dependency. The
   measured "0.0 unauthenticated access rate" was true for the thirteen
   endpoints it covered and silent about these two.
6. **Two prompt sites left untrusted text outside the fence.** The research
   prompt put the listing's title, company, location and skills in the
   prompt as ordinary labelled fields — outside the markers the security
   rules describe — and the tailoring prompt did the same with the whole
   extracted-requirements block. The output filters still bounded the
   blast radius, but the prompt-side claim was not true.
7. **The console shipped without a CSP.** The API sets `nosniff`,
   `X-Frame-Options` and `Referrer-Policy` on its own responses, but the
   console's HTML and JavaScript were served with no policy at all, and the
   console holds the "Approve and submit" button.

## Execution plan

Phases, in dependency order (each phase: implement → its own tests → the
full offline suite → `ruff`):

1. **Phase A — Amplification.** A single-pass linear neutralizer in
   `src/security/html.py`, and a bounded input, so no board can buy minutes
   of CPU with one field.
2. **Phase B — Starvation.** The embedding budget counts cache misses; the
   local provider gets the persistent daily work budget the API provider
   already had; the corpus evicts its oldest listings instead of refusing
   everything.
3. **Phase C — Exposure.** The scope dependency on the two open job routes,
   and the evaluation's protected-endpoint list extended to cover them, so
   the measured metric cannot be quietly scoped to the easy ones.
4. **Phase D — Abuse.** A cap on the requests in flight at once, so a
   connection flood cannot hold every worker, and the browser-driving
   approval endpoint joins the heavy-path list.
5. **Phase E — Confusion.** Every untrusted field inside a nonce fence, in
   the research prompt and in the tailoring prompt, and the tailoring
   prompt's untrusted block length-capped like the research one.
6. **Phase F — Containment.** Per-user containment on the document
   download, a validated job id in the board URL, and a validated
   `application_url` scheme.
7. **Phase G — The console.** A Content-Security-Policy and the response
   headers, a link that only opens `http(s)`, a CSRF-token reader that
   cannot be crashed, a prototype-safe status map, a broader set of
   forbidden ESLint sinks, and a client-side cap on the response the
   console will parse.

## The controls, and why each is shaped the way it is

### The neutralizer is a scanner, not a pattern

The quadratic came from the engine retrying `.*?` at every position where
`<` matched. A scanner that advances a cursor cannot retry: it finds the
next `<`, decides what it is, and jumps past it. The same output, the same
order, the same guarantee — **no tag survives** — in one pass.

### The budget counts the work, not the rows

A cache hit costs a lookup. A cache miss costs an embedding. The flood
attacks the miss, so the budget is denominated in misses. A listing that is
already cached **and** already in the vector store is not re-embedded at
all, which is what makes a repeated flood free.

### The daily budget is persistent, like the API one

A counter in memory resets when the process restarts, which is exactly when
an attacker wants it to. The counter lives next to the vectors, in the
same SQLite file, in the same UTC-day shape as the provider's own.

### The corpus evicts; it does not close

A bound that can only be reached once and never left is an outage waiting
for a flood. The corpus evicts its oldest listings to make room, so the
bound still protects the read path and the corpus still moves.

### The fence covers every untrusted field

The security rules say *text between the markers is data*. A field outside
the markers is, by the rules' own terms, trusted. So every untrusted field
goes inside a fence, and the fence is what the model is told about.

## Acceptance criteria

- [x] A 1 MB field of `<script>` is neutralized in well under a second,
      and the cost grows linearly with the input. **Measured: 128 KB went
      from 25.3 s to 0.12 s** — 210× faster, and the curve is linear
      where it was quadratic.
- [x] A flood of already-cached listings costs **no** embedding budget, and
      the legitimate new listing in the same response is embedded.
- [x] The local provider stops embedding when the daily work budget is
      spent, and resumes on the next day, and the counter survives a
      restart (it lives in the cache database, not in memory).
- [x] A full corpus still admits new listings, and the corpus stays within
      its cap.
- [x] `POST /api/jobs/refresh` and `GET /api/jobs/{job_id}` refuse an
      anonymous caller, and the evaluation's protected-endpoint list says so
      (15 endpoints now, not 13).
- [x] The in-flight request cap refuses with 503, and the approval endpoint
      is on the heavy-path list.
- [x] No untrusted field reaches a prompt outside a fence.
- [x] The console is served with a Content-Security-Policy, and
      `application_url` only becomes a link when it is `http(s)`.

## What each phase changed

| Phase | The control | Where |
|---|---|---|
| A | the linear neutralizer, and a bounded input | `src/security/html.py` |
| B | the budget counts cache misses; the per-source share; the daily work counter; the corpus eviction | `src/graph/job_executor.py`, `src/llm/embeddings.py`, `src/db/jobs.py`, `src/rag/chroma_store.py`, `migrations/versions/c3d4e5f6a7b8_ws15_job_last_seen.py` |
| C | the scope dependency on the two job routes; the evaluation's list | `src/api/routes/jobs.py`, `src/evaluation/security.py` |
| D | the in-flight cap; the heavy-path list | `src/api/middleware.py`, `src/main.py` |
| E | the fence around every untrusted field; the capped prompt blocks | `src/research/engine.py`, `src/resume/tailor.py` |
| F | the per-user containment; the validated job id; the validated scheme | `src/storage/paths.py`, `src/api/routes/documents.py`, `src/api/routes/artifacts.py`, `src/jobs/greenhouse_adapter.py`, `src/jobs/contracts.py`, `src/security/allowlist.py` |
| G | the console's policy, headers, safe link, robust CSRF reader, prototype-safe map, broader lint sinks, the response cap | `frontend/vite.config.ts`, `frontend/src/lib/safe-url.ts`, `frontend/src/lib/api/client.ts`, `frontend/src/lib/status.ts`, `frontend/eslint.config.js` |

## The new limits

| Variable | Default | What it bounds |
|---|---|---|
| `MAX_INFLIGHT_REQUESTS` | 64 | the requests in the process at once (the pile-up) |
| `MAX_CORPUS_EVICTIONS_PER_REFRESH` | 5 000 | the rows one refresh may evict to make room |
| `MAX_EMBED_WORK_PER_DAY` | 5 000 | the documents one UTC day may embed |

`HEAVY_QUEUE_TIMEOUT_SECONDS` was a **dead knob** — defined, documented,
and read by nothing, because the heavy-path gate refuses immediately. It
is now the grace period the in-flight cap waits before it refuses, so a
burst is absorbed rather than turned into a wave of errors.

## Tests

`tests/test_ws15_hardening.py` — one class per phase, each asserting the
attack is stopped rather than the control exists. The frontend's half is
`frontend/src/lib/safe-url.test.ts`, plus the new cases in
`frontend/src/lib/status.test.ts` and `frontend/src/lib/api/client.test.ts`.

## New dependencies

None. Every control here is the standard library or the code that is
already there.

## What is still open

- **The DNS-rebinding gap in the browser path.** `assert_navigation_allowed`
  checks the host literally and does not resolve it, so a DNS change on
  an allowlisted host could point the browser at a loopback or a metadata
  address. The job-source HTTP client does resolve and re-check; the
  browser path does not. Closing it means resolving in the navigation
  guard, and failing **closed** when the resolution fails — which would
  break the local fake ATS, so it needs the same explicit dev-scoped
  exception the allowlist already has for it.
- **The rate limiter keys on the transport peer**, so behind one reverse
  proxy every user shares one budget (WS-14 recorded this; it is still
  open). It is the reason a back-to-back end-to-end run in one workspace
  can refuse the second test.
- **The `requests_today` counter counts API *batches*, the new
  `work_today` counter counts *documents*.** Two counters, two units, and
  a reader has to know which is which.

