# WS-36 (WS-UX-04) · UX redesign: Discover and job detail

Status: **Planned — not started** · Source directive:
[JOBPILOT-UX-REDESIGN-AGENT-PROMPT-v2.md](../JOBPILOT-UX-REDESIGN-AGENT-PROMPT-v2.md) §6.2, §6.3, §8 (WS-UX-04) ·
Depends on: WS-34 (shell + primitives), WS-35's density decisions ·
Visual authority: [Redesign Image.png](../Redesign%20Image.png) (panel 2)

> **Where this starts.** `frontend/src/screens/matches-screen.tsx` (test:
> `matches-screen.test.tsx`) and `frontend/src/screens/job-detail-screen.tsx` already
> implement search over the **stored corpus** with ranked matches, component
> explanations and evidence signals (WS-20/21/24/28/29 lineage). The reference panel
> gives the approved split view: search bar, filter/sort row, results list on the left,
> selected-job detail on the right, with the match score compact and the "why this
> matches" explanation prominent. Search must stay truthful: it searches **stored
> corpus**, never implying a live scrape of all boards.

## Non-negotiable invariants for this workstream

Server pagination and filtering semantics are preserved — a loaded page is never
presented as the whole corpus; counts come from the server. Match components keep their
real states: unavailable components keep their weight in the denominator (WS-20's fixed
denominator) and render as **unknown**, never as a value or a silent zero. Matched /
missing / unknown / not-measured stay visually distinct. "Missing" is explained as an
evidence gap, not a disqualification. Sponsorship is shown only from verified registers
(WS-22) and honestly as unknown otherwise. Job-board content renders as text only
(untrusted; WS-15's neutralization happens backend-side — do not re-introduce
`dangerouslySetInnerHTML`). Save/shortlist and Prepare actions must be wired to real
endpoints or not rendered.

## File-ownership boundary (exclusive)

`frontend/src/screens/matches-screen.tsx`, `frontend/src/screens/job-detail-screen.tsx`,
their existing tests, and **new** screen-local components under
`frontend/src/screens/discover/**`. Consumes WS-34 primitives; proposals to the lead.
`lib/api/**` read-only.

## 1 — Task 1: data inventory

- [ ] From the WS-33 audit, pin the exact search endpoint contract the screen uses today:
      query params, the response's total/page fields, match component list, evidence
      fields, sponsorship signal fields, and the degraded-flag behavior (Chroma's
      `count − 1` edge case makes `degraded` true on unfiltered full-corpus searches —
      render it honestly as a notice, not an error).
- [ ] Record which reference-panel filters are real today (location/remote, seniority,
      role family, employment type, salary where populated, sponsor signal where
      verified) and which have no data source — the latter are not rendered.

## 2 — Task 2: the split view

- [ ] Search area: single search input (job title, skills, company, location) plus the
      filter row, compact per the reference. Copy states the truth: "Search stored
      jobs" (with the Operations link for corpus refresh).
- [ ] Results list: dense rows — title, company, location, date/source where known, real
      score chip, up to 3 real skill chips — keyboard-navigable, active row visually
      selected, lazy-loads the next page with the real total stated ("of N").
- [ ] Detail panel: title/company, location, employment type, salary range **if present**,
      short description, match explanation with component breakdown (real values + real
      states), matched requirements with evidence, missing requirements as gaps,
      sponsorship as verified/unknown. Deeper scoring detail progressive (expandable),
      not eight dimensions per card.
- [ ] Actions: Save/shortlist and Prepare/Tailor (`/app/tailor/:jobId`), wired to real
      endpoints; the selected job persists in the URL so refresh/deep-link keeps the
      selection.
- [ ] Empty/error/degraded states: no results ("no stored jobs match — try broader terms
      or refresh the corpus in Operations"), source failure, degraded scoring notice.
- [ ] Mobile (≤5174px workstream but keep it composable): results-first list; detail
      becomes a full-height page with a clear back path, not a squeezed column.

## 3 — Task 3: job detail route

- [ ] `/app/matches/:jobId` remains fully useful opened directly: complete listing text
      (wrapped safely, `wrap-anywhere` for long tokens — `break-words` does not stop
      clipping), full match reasoning, matched/missing with evidence, research insights
      when present (facts vs inferred distinguished per master prompt §6.4D), source and
      freshness (`first_seen_at`/board) when available, and the same real actions.
- [ ] Do not duplicate every Discover card field in a second noisy layout.

## 4 — Task 4: tests and verification

- [ ] Extend `matches-screen.test.tsx` / add `job-detail` cases: total-from-server
      assertion; unknown component renders unknown; missing requirement renders as gap
      with its explanation; degraded flag renders a notice; empty and error states;
      deep-link to a job id selects it after load; untrusted description containing HTML
      renders as text.
- [ ] Browser-verify at 1440×1000, 1280×800, 390×844, 360×800 (assigned ports, real
      backend): long titles/companies wrap, no sideways scroll, chips don't clip, focus
      moves sensibly between list and detail. Screenshots into `docs/design/ws36-discover/`.

## Acceptance

- Split view recognizable as reference panel 2 at the reference's density; every filter
  and chip traceable to real data; search truthfully labelled.
- All tests green; server pagination semantics preserved; shared files untouched.

## Tests

`npm run test -- src/screens/matches-screen.test.tsx` and the screen-local additions;
full suite at the lead's integration gate.
