# WS-38 (WS-UX-06) · UX redesign: Review and human approval

Status: **Planned — not started** · Source directive:
[JOBPILOT-UX-REDESIGN-AGENT-PROMPT-v2.md](../JOBPILOT-UX-REDESIGN-AGENT-PROMPT-v2.md) §6.5, §8 (WS-UX-06) ·
Depends on: WS-34 (primitives + status centralization), WS-33 audit (prepare/approve
contracts, board questions) · Visual authority:
[Redesign Image.png](../Redesign%20Image.png) (panel 4)

> **Where this starts.** `frontend/src/screens/approvals-screen.tsx` (tests:
> `approvals-screen.test.tsx`, `approvals-screen-form-questions.test.tsx`) already renders
> the two-phase prepare → approve flow, the board's own question order from
> `form_questions`, and blockers by name (WS-25b lineage). The reference panel gives the
> approved composition: a review header ("Review Your Application"), the in-control
> notice, an Application Package checklist, Unresolved Questions with the board's radio
> options, Job Details, and the approve action. WS-32 moved execution onto the durable
> queue: approve returns **202 + a run id** — accepted, not submitted. The console
> already renders an accepted submission as accepted with its run id (WS-32 fix), and the
> button copy was flagged: it still says "Approve and submit".

## Non-negotiable invariants for this workstream

Approval is the irreversible boundary: the payload the human inspects is the **exact
persisted prepared payload** approved — if any document or answer changed after
preparation, the packet is invalidated/rebuilt or the change is explicit; never approve a
different payload than displayed. `202` renders as "Approved — queued" with the run id
and next expected action; "Submitted"/"Verified" render only when the backend reports
those states. Real-board assist is explained as fill-then-hand-back; the final submit is
the human's; CAPTCHA/MFA/anti-bot are handed to a human, never bypassed. Fake-ATS and
real-board paths stay visibly distinct. Unresolved/human-needed questions are visible
with required flags, in the board's published order. Expiry and profile-binding semantics
(WS-25) are preserved: an expired or stale approval shows its real state and a rebuild
path. No "mass apply", no auto-submit control, ever.

## File-ownership boundary (exclusive)

`frontend/src/screens/approvals-screen.tsx`, its existing tests, and **new** screen-local
components under `frontend/src/screens/review/**` (packet checklist, question card,
approval-boundary panel). Consumes WS-34 primitives. `lib/api/**` read-only.

## 1 — Task 1: contract inventory

- [ ] From the WS-33 audit + OpenAPI: pin the prepare payload schema, the approval
      request/decision endpoints, the 202 response shape (run id), the durable-run
      status endpoint and its real state names, approval expiry fields, and the
      `submission.uncertain` surface (noted in WS-32 as having no operator surface yet —
      if absent in the API, record that as a follow-up, do not invent a rendering of
      nothing).
- [ ] Record the exact question-source contract (`form_questions` order, required flags,
      `needs_human` verdicts) and the profile-binding digest behavior.

## 2 — Task 2: the review screen

- [ ] Header: employer, role, board/source, candidate identity — per the reference.
- [ ] The in-control notice (amber/attention tone, truthful copy: "The agent will wait
      for your approval before submission" for the assist path; for the fake-ATS
      path the equivalent honest framing — visibly distinct).
- [ ] Application Package checklist: tailored resume and cover-letter **version
      identity** (which revision/id), generated answers with their sources (confirmed
      profile fact / candidate-provided / unresolved), supporting documents, research
      summary — each with a real anchor to the source object.
- [ ] Questions card: the board's published order, required flags, unresolved and
      human-needed questions visible and labelled; answer sources shown.
- [ ] Readiness blockers and warnings named exactly as the backend reports them.
- [ ] Actions: edit packet, reject, approve/queue. Fix the flagged copy: the primary
      action must not say "Approve and submit" — it queues work; the reference's
      "Approve & Continue" is closer, with the queued consequence stated in the
      confirmation.
- [ ] Post-approval: "Approved — queued" + run id + link to run progress
      (`/app/operations` run panel or the application's tracker entry); duplicate
      submit guarded; reload shows the persisted state.

## 3 — Task 3: states and edges

- [ ] Exercise: accepted 202 runs; reload mid-run; duplicate approve attempt; expired
      approval; profile changed after approval (binding digest mismatch → real state +
      rebuild path); blocked human review; uncertain submission (real API state or
      documented absence); rejection path.
- [ ] Real-board assist handoff rendered explicitly: form filled → control returns to
      the human → nothing suggests autonomous submission happened or will happen.

## 4 — Task 4: tests and verification

- [ ] Extend `approvals-screen.test.tsx` (+ form-questions test): 202 → queued label
      with run id, never "submitted"; question order preserved from the payload;
      unresolved questions block with the board's naming; expired approval renders its
      real state; the approve action is disabled/confirmed against duplicate submission;
      payload identity shown matches the payload referenced by the approve call (assert
      the id in the request fixture).
- [ ] Browser-verify at 1440×1000, 1280×800, 390×844, 360×800 (assigned ports, real
      backend + fake-ATS flow): the boundary notice, checklist, questions and queued
      state all legible on mobile without horizontal scroll; screenshots into
      `docs/design/ws38-review/`.

## Acceptance

- The screen reads as reference panel 4: checklist + unresolved questions + in-control
  panel + approve action, with honest state language throughout.
- Exact-payload approval preserved and test-pinned; 202 semantics correct; assist and
  fake-ATS visibly distinct.

## Tests

`npm run test -- src/screens/approvals-screen` (both files); full suite at the lead's
integration gate.
