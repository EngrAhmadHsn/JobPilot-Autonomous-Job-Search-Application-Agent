# WS-19 · The console follow-up pass

Status: **Done (2026-11-07)** · Milestone: **M5** · Depends on: WS-13 (the console), WS-17 (the experience), WS-18 (durable execution) · Verified live against the running console

> Six defects and gaps reported from using the console: a stale remembered
> profile produced an error instead of a working screen, the résumé library
> could not be paged and did not say which document was in use, the tailor
> screen offered no way in from a job search, the tracker and the activity
> trail were too long for one page, the site explained how the system is
> built rather than what it gets done, and the administration screen showed
> no progress — so a queued reconciliation looked like a button that did
> nothing.

---

## 1. What was reported, and what changed

| # | Report | Change |
|---|---|---|
| 1 | "If résumé documents are already present, use the most recent one instead of erroring; highlight which document is selected; check whether the list shows all documents; page the résumés five at a time" | A stale handle now resolves to the newest document the account has (`use-profile-fallback`); the library marks the document the console is reading ("In use"); the list is the account's whole library (the endpoint already returned profiles **and** tailorings — 56 résumés and 8 tailorings in the local deployment) paged five at a time |
| 2 | "For tailor, first show 'find jobs that suit you' and a button back to the jobs page when there is no job link" | The tailor index opens with that prompt and a **Find jobs that suit you** button; the empty state and the unknown-job state link there too |
| 3 | "The tracker shows 20 applications per page — reduce it to 10" | `PAGE_SIZE = 10`, and the counter now reads as a range ("41 applications · showing 1–10") |
| 4 | "Activity: the executions should be collapsed at first, and the trail paged by 10" | Each execution's steps sit behind a closed disclosure; the trail pages ten at a time |
| 5 | "The site text should focus on what it gets done for the user, not how we did it" | The landing page rewritten around outcomes (and the console's heaviest descriptions de-jargoned); no claim removed that the code does not support |
| 6 | "Reconcile does nothing for admin; the administration page should be as good as operations; and the operations detail disappears when I come back" | The admin listing now covers **every** run type (a reconciliation was queued, then invisible under an embedding-only list), says plainly when **no worker is running** (with the command), and expands any run into the same progress panel the operator sees. The operations panel is **derived**, so a reload re-adopts the run that is still going |

## 2. The two defects behind the reports

**A stale profile handle could clear itself into the wrong screen.** The
first version of the fallback wrote "no profile" to the store as soon as the
404 arrived — which can be *before* the document library does. That threw away
the fallback the hook exists to find: the account landed on the upload prompt
with 64 résumés in the library. The write is now guarded on
`documents.isSuccess`, and a regression test delays the profile check and the
library independently so the race is pinned.

**The administration screen's silence.** `POST /api/admin/embeddings/reconcile`
was answering `202` with a run id, and the list behind it filtered to
`job_type=embedding` — so a reconciliation *never appeared*, and with no worker
process running, nothing executed it either. Both halves are fixed in the
view (a new platform-wide `GET /api/admin/runs`, a worker-health banner) and
neither is papered over: a queued run with no worker is *shown as queued*, with
the command that starts the worker.

## 3. Backend additions

- `GET /api/admin/runs` and `GET /api/admin/runs/{run_id}` — every durable
  run, optionally filtered by `job_type` or `status`, administrator-only, both
  covered by `tests/test_runs_api.py` and by the anonymous-access metric in
  `src/evaluation/security.py`.
- The embedding-only listing stays exactly as it was; the recovery surface for
  that kind of work is unchanged.

## 4. Verification

- Frontend: 147 tests (up from 137), `tsc -b --force`, eslint and the
  production build pass. Backend: `tests/test_runs_api.py` 17 tests, and the
  docs/env/isolation/security-metrics suites pass.
- Live, against the running console and a real backend (Chromium,
  1440×1000), on a deployment holding **64 documents, 41 applications and 100
  audit events** — enough that every pager had more than one page:

| Check | Result |
|---|---|
| Résumé library, page 1 → 2 | `1–5 of 64 documents` → `6–10 of 64 documents` |
| Stale profile handle | no error, the profile of the newest résumé renders, the document is marked **In use**, and the stored handle is corrected to `9913319375ba` |
| Tailor index | **Find jobs that suit you** present |
| Tracker | the server is asked for `limit=10`; counter reads "41 applications · showing 1–10" |
| Activity | 20 disclosures, **0** open; trail `1–10 of 100 recorded actions` |
| Operations | "Latest run · corpus refresh · Waiting for a worker", queued 1 h ago, plus the run history and per-row **Show** |
| Administration | "No background worker is running" with `python scripts/run_worker.py` and "2 runs waiting"; both queued runs listed (refresh + reconcile); **Progress** expands the run id, priority, lease, embedding space and the lifecycle events |
| Landing page | opens on "Your job search runs itself.", the process section reads as outcomes |

## 5. Notes for the next session

- The two new admin routes only appear after the API process restarts; the
  running server predated them during this pass and the admin list 404'd until
  it was restarted. That is the same module-graph behaviour WS-18 recorded.
- `react-hooks` v7 refuses `setState` inside an effect, so the profile
  fallback is **derived** (a pure function of the server's answer and the
  library) with a single external-store sync, and the operations screen
  derives the run it follows instead of adopting it in an effect. The store's
  writer is named `chooseProfile` (the former `setCurrentProfileId` remains as
  an alias) because it is an external store, not React state.