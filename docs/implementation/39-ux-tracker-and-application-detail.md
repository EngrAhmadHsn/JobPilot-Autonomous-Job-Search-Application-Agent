# WS-39 (WS-UX-07) · UX redesign: Application tracker and application detail

Status: **Delivered 2026-11-17** (commit `880478f`): board, list and timeline on real server totals, single-select filters where the backend lies about multi-status, and human outcomes attributed to a human · Source directive:
[JOBPILOT-UX-REDESIGN-AGENT-PROMPT-v2.md](../JOBPILOT-UX-REDESIGN-AGENT-PROMPT-v2.md) §6.6, §8 (WS-UX-07) ·
Depends on: WS-34 (primitives + status centralization), WS-38 (status language) ·
Visual authority: [Redesign Image.png](../Redesign%20Image.png) (panel 5)

> **Where this starts.** `frontend/src/screens/tracker-screen.tsx` (tests:
> `tracker-screen.test.tsx`) implements the server-paginated list and
> `/app/tracker/:applicationId` detail with ordered history (WS-07's
> `Application`/`ApplicationEvent` lineage, the transition matrix with the actor rule —
> a human outcome is only settable by a human). The reference panel shows Board | List |
> Timeline toggles and stage columns with counts (Saved 8, Preparing 12, Awaiting Review
> 5, Submitted 9, Interview 2). Those sample counts are **illustrative**: a Kanban that
> needs all stages at once requires a complete server query contract — a partial page
> must never be presented as the stage total.

## Non-negotiable invariants for this workstream

Only real backend statuses and human outcomes render — never infer interview/offer/
rejection from email or board content, never present an agent status as a human outcome.
Server pagination/filter semantics are preserved; a board view without a complete-count
contract is labelled as a view of the current page or uses server-backed stage filters —
or a **narrow, tested server-side addition** is proposed to the lead (never implemented
unilaterally). Human outcome editing exists only where the API supports it and is always
attributed to the authenticated human actor. Evidence and artifacts render only through
the safe authorized download endpoints — server-side file paths are not browser URLs
(`lib/safe-url.ts`).

## File-ownership boundary (exclusive)

`frontend/src/screens/tracker-screen.tsx` (list + detail), its existing tests, and
**new** screen-local components under `frontend/src/screens/tracker/**` (board column,
timeline, outcome editor). Consumes WS-34 primitives. `lib/api/**` read-only.

## 1 — Task 1: contract inventory

- [ ] From the WS-33 audit + OpenAPI: pin the list endpoint's pagination/filter fields
      and server totals, the detail payload (events in order, actor, outcome, evidence
      links), the PATCH outcome contract, and whether any complete stage-count endpoint
      exists. Deliverable: the board-view decision (server filters / page-labelled view /
      proposed additive endpoint) written down before UI work.

## 2 — Task 2: the three views

- [ ] **List**: dense searchable/filterable/sortable table per the reference's List tab;
      server-side filters only; precise status inspection with the WS-34 presentation.
- [ ] **Board** (only per the Task 1 decision): stage columns built from real statuses;
      cards keep job/company/status/next action; no horizontal-scrolling tables on
      mobile — board is desktop-first with an honest mobile fallback (list).
- [ ] **Timeline** (detail): the application's chronology as ordered events with actor
      attribution (lime = agent, terracotta = human per the semantics), timestamps, and
      evidence links (screenshot/trace where the API exposes them safely).
- [ ] Application detail adds: job/company identity + plain-language status; applied/
      submitted/verified timestamps **only when present**; resume/cover-letter versions
      associated; next action and recovery path for blocked/uncertain/failed/unanswered;
      the human outcome editor where supported.

## 3 — Task 3: tests and verification

- [ ] Extend `tracker-screen.test.tsx`: server totals asserted (fixture where page size <
      total); board columns carry only real statuses and the labelled-subset honesty;
      timeline order and actor attribution; outcome editor PATCHes with the human actor
      and is absent when unsupported; evidence renders via safe URLs only; empty state.
- [ ] Browser-verify at 1440×1000, 1280×800, 390×844, 360×800 (assigned ports, real
      backend): columns, cards, timeline legible; no sideways scroll at 360; screenshots
      into `docs/design/ws39-tracker/`.

## Acceptance

- Recognizably reference panel 5 (Board/List/Timeline) with honest counts; detail is a
  complete chronological record with recovery paths.
- All tests green; pagination and actor-rule semantics preserved.

## Tests

`npm run test -- src/screens/tracker-screen.test.tsx` plus screen-local additions; full
suite at the lead's integration gate.
