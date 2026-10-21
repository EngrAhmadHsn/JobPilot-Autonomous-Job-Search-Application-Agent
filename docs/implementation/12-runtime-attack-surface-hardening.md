# WS-12 · Runtime Attack-Surface Hardening

Status: **In progress (2026-10-21)** · Milestone: **M3** · Depends on: WS-06 (security preconditions) · Blocks: [11](11-docs-and-ops.md)

> This workstream is the **audit-and-close** pass over the runtime's
> attack surface. WS-06 built the controls that were specified at the
> time; WS-12 asks a different question of the code that exists *now*:
> given everything the system does today — fetching boards, embedding
> listings, prompting a model, driving a browser, serving an API — what
> can an untrusted party make it do, and what stops them?

## Goal

Close the exploitable gaps in the running application, in five families:

| Family | The attack | The control |
|---|---|---|
| **Abuse** (DDoS) | A script hammers the API; the refresh endpoint is called in a loop | per-client rate limit, body-size cap, concurrency gate, docs lockdown |
| **Starvation** (the embedding flood) | Fake jobs flood the corpus, spend the provider's daily quota, and fill the embedding cache so **legitimate** listings never get embedded or cached | spam screen, corpus admission control, bounded embedding work, bounded cache, bounded corpus scan |
| **Execution** (XSS) | A board returns HTML that the API serves and a consumer renders | HTML neutralization at ingest, `nosniff` and the other response headers |
| **Confusion** (prompt injection) | A listing impersonates the prompt's own scaffolding to steer the model | nonce-fenced untrusted blocks, the injection strip on every bullet, the job-title check, PII minimisation |
| **Traversal** (path traversal, malformed input) | A request points the browser at `.env`; a board returns a malformed payload | path containment, zip-bomb guard, type-safe payload access, one SSRF predicate |

## What the audit found

The audit (2026-10-21) read every file under `src/` and traced every
boundary where untrusted input enters. There was **no** `eval`, `exec`,
`subprocess`, `os.system`, `shell=True` or `pickle` anywhere in `src/`,
and no raw SQL — the DB layer is the SQLAlchemy ORM throughout. The
findings were therefore not code execution. They were **resource
exhaustion, stored payload, and control-flow gaps**, and they clustered
into the five families above.

The three that mattered most:

1. **The API had no rate limit, no body cap, and no concurrency gate.**
   `POST /api/jobs/refresh` walks every board and embeds the corpus. It
   was callable without limit, by anyone who could reach the port.
2. **The embedding flood was unbounded in every dimension.** A board
   returning 50,000 unique listings would spend the provider's whole
   daily quota, grow the SQLite embedding cache without limit, and make
   every search read a corpus of any size. The attack's victim is not
   the flood — it is the *legitimate* listing that arrives afterwards and
   never gets a vector, because the quota and the cache are already spent.
3. **`resume_path` was an unvalidated filesystem path** handed to
   `set_input_files()`. The browser uploads that file to a third-party
   job site, so any path the process can read — `.env`, an SSH key — was
   an exfiltration channel.

## Execution plan (added 2026-10-21)

Phases, in dependency order (each phase: implement → its own tests → the
full offline suite → `ruff`):

1. **Phase A — Abuse.** `src/security/limits.py` (every bound in one
   reviewable place), `src/security/rate_limit.py` (a per-client limiter
   whose own memory is bounded), `src/api/middleware.py` (rate limit,
   body cap, concurrency gate, response headers), wired into
   `src/main.py` with the docs surface disabled outside development.
2. **Phase B — Starvation.** `src/jobs/spam.py` (the fake-job screen),
   `src/security/admission.py` (the corpus admission control), the
   embedding-cache bound, the bounded corpus scan in the vector store and
   in the search, and the response-size cap on the job-source client.
3. **Phase C — Execution.** `src/security/html.py` (the neutralizer),
   applied at the contract so no adapter can forget it, plus the
   response headers.
4. **Phase D — Confusion.** The nonce fence in `src/security/injection.py`,
   applied in the research and tailoring prompts; the injection strip on
   project bullets; the job-title check; the PII minimisation.
5. **Phase E — Traversal.** `src/security/paths.py` (the containment
   check), the zip-bomb guard, the unified SSRF predicate, and the
   type-safe payload accessor.
6. **Phase F — Tests.** `tests/test_ws12_hardening.py` — 74 tests, one
   per control, written from the outside.
7. **Phase G — Reconciliation.** `docs/SECURITY.md` (the control
   register), `00-OVERVIEW.md`, `.env.example`, and this document.

## The controls, and why each is shaped the way it is

### The limits live in one file

`src/security/limits.py` holds every number that bounds how much work an
untrusted caller can cause. A limit defined next to the code it guards is
one somebody re-checks when it needs raising; a limit scattered across
five modules is one nobody finds. The values are read from the
environment and **validated at first use** — a knob that decides how much
memory a request may consume is a typo waiting to happen, and a limit
that silently reverts to a permissive value is a limit that is not doing
its job.

### The rate limiter's own memory is bounded

A limiter that stores a bucket per client IP is itself a denial-of-
service target: an attacker with many source addresses fills the bucket
table until the process is out of memory. The table is therefore capped
and the least-recently-used bucket is evicted.

The key is the **transport** address, never a forwarded header. A
`X-Forwarded-For` is trivially forged, so a limit keyed on it is no limit
at all — an attacker would mint a fresh budget per request by inventing
an address.

### The flood is screened *and* bounded

`src/jobs/spam.py` screens a batch on three deterministic signals: token
stuffing, link farming, and a body repeated across many companies. The
third signal is the flood's signature, and it has **two thresholds** on
purpose: the body must repeat more than ten times *and* across more than
five companies. One threshold is not enough — a company posting twenty
roles with the same blurb is normal, and the same body under a dozen
unrelated company names is generated. A control that cannot tell those
apart is a bug that deletes real jobs.

The screen is a *quality* control. The **admission** control
(`src/security/admission.py`) is the cost control, and it is
count-based, so it holds whatever the content looks like.

### The screen is advisory; the limits are authoritative

`screen_listings` returns what it would admit; the caller decides. The
screening is deterministic and explainable — a poisoned listing must not
be able to argue its way past the filter, and the reason for every drop
is recorded so the decision is auditable.

### Every drop is counted

A limit that discards data silently is indistinguishable from a bug. The
refresh report gained `screened_out` and `admission_capped` counters, so
a run that dropped 240 listings says so.

### The untrusted block is fenced with a nonce

WS-06 already had three layers against prompt injection: the system
rules, a deterministic pattern list, and a grounding filter that drops
any fact not traceable to the listing. What it did not have was a
**structural** boundary. A listing that contains a line reading
`SECURITY RULES:` or `Listing title:` can impersonate the prompt's own
scaffolding, because the untrusted text and the trusted instructions
shared one flat channel.

The fence gives the model a real boundary: the untrusted text goes
between `<<<UNTRUSTED_JOB_LISTING:{nonce}>>>` markers, and the nonce is
random per request. An attacker who wrote the listing cannot predict the
marker, because the marker did not exist when they wrote it. A *copied*
marker is removed whole before the fence is written.

The fence is defence in depth, not a replacement: the grounding filter
remains the backstop that makes a successful injection harmless.

### The candidate's contact details do not leave the process

The tailoring stage needs the candidate's *facts*, not their email
address. The contact details are removed at the boundary — the stored
profile keeps everything (the rendered resume needs the contact block),
but the copy that goes to the model does not. An injected listing that
tries to make the model repeat the candidate's email has nothing to
repeat.

### Paths are contained, not blocklisted

`resume_path` is request-supplied and the browser uploads that file to a
third party. The check is a **containment** check: the path must resolve
inside a directory this application owns. Containment is checked on the
*resolved* path, after symlinks are followed, because the attack is a
symlink pointing out of the directory just as much as it is a `../`
sequence — and a prefix comparison on the unresolved string would accept
`/data/uploads/../../etc/passwd`.

### One SSRF predicate

The job-source HTTP client kept its own copy of the "is this address
internal" rule, and the two copies had **drifted**: the allowlist's
refused CGNAT (`100.64.0.0/10`) and multicast addresses, the client's
did not. A blocklist with two versions of itself is only as strict as its
weakest copy. There is now one implementation, and the client's
predicate delegates to it.

## Acceptance criteria

- [x] Every limit is defined in one file and read from the environment.
- [x] The API refuses requests over a client's budget with 429 and a
      `Retry-After`.
- [x] A request body over the cap is refused with 413, whether or not it
      declares a length.
- [x] The expensive endpoints run at most `MAX_CONCURRENT_HEAVY` at once.
- [x] The interactive API docs are disabled outside development.
- [x] A flood of fake listings cannot spend more than
      `MAX_EMBED_PER_REFRESH` of the embedding budget in one run.
- [x] The embedding cache cannot grow past `MAX_CACHE_ENTRIES`.
- [x] The corpus cannot grow past `MAX_CORPUS_LISTINGS`, and the
      full-corpus read is bounded and paged.
- [x] No stored listing carries markup.
- [x] Every response carries `nosniff` and the other hardening headers.
- [x] The untrusted block in a prompt is nonce-fenced.
- [x] An injected sentence in a project bullet is removed.
- [x] A job title the candidate never held is removed.
- [x] The candidate's contact details are not in the prompt.
- [x] A `resume_path` outside the application's directories is refused.
- [x] A DOCX that expands beyond the cap is refused.
- [x] A malformed board payload degrades the source instead of raising.

## Tests

`tests/test_ws12_hardening.py` — 74 tests, one family per control:

| Class | Covers |
|---|---|
| `TestRateLimiter` | the budget, the window, the per-client isolation, the bounded client table |
| `TestRateLimitMiddleware` | the 429, the `Retry-After`, the budget headers |
| `TestBodySizeLimit` | the declared and the undeclared body |
| `TestConcurrencyGate` | the path matcher, the cheap paths |
| `TestSecurityHeaders` | the headers on every response |
| `TestSpamScreen` | stuffing, link farms, legitimate boilerplate, the flood signature |
| `TestAdmissionControl` | the per-source, per-refresh and corpus caps |
| `TestEmbeddingCacheBound` | the eviction, oldest first |
| `TestBoundedCorpusScan` | the paged scan, the ceiling |
| `TestResponseSizeCap` | the oversized board response |
| `TestMalformedPayloads` | the string `jobs` field |
| `TestHtmlNeutralization` | ten hostile payloads, the entity-encoded one, the preserved prose |
| `TestListingNeutralization` | the stored listing, the caps, the verbatim text |
| `TestPromptFencing` | the nonce, the unforgeable and the copied marker |
| `TestTailoringInjectionControls` | the PII minimisation, the project bullet, the job title |
| `TestResearchPrompt` | the fence, the prompt cap |
| `TestPathContainment` | the outside path, the traversal, the symlink-equivalent |
| `TestZipBombGuard` | the expansion, the entry count, the ordinary document |
| `TestUnifiedSsrfPredicate` | the addresses the two copies disagreed about |

Plus the suite-wide fixture in `tests/conftest.py` that keeps the rate
limiter from refusing the suite's own requests (the limiter is a real
control and it is not disabled — the budget is raised).

## New dependencies

None. Every control is hand-rolled, per the project rule: the rate
limiter, the spam screen, the HTML neutralizer, the fence, and the path
containment check are all a few dozen lines each, and the workspace
rule is "no dependencies without clear justification".

## Status

- Full suite: **1003 passed**, 6 failed (the known Remotive DNS flake —
  see AGENTS.md), `ruff` clean.
- The eval gate is unchanged: the same metrics as the shipped baseline,
  and the gate now reports a failure instead of crashing when it has one.
