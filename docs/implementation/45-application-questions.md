# WS-45 — Per-application questions: answering, persistence, context-dependent profile questions

Status: **In progress — 2026-11-21** · Owner: sprint WS-43…49 · Design authority: `docs/Job Pilot (Copy).pdf` + `docs/design/Images-figma/Job Pilot/`

## Goal

The per-application questions flow exists only as a read-only queue — the backend has nowhere to save a human answer, so a required employer question blocks approval with no path through the console. Build the answering flow end to end (design's Review screen), and fix the profile questions that pretend to be context-free when they are not — work authorization depends on the country being asked about.

## Design references (primary)

- `docs/design/Images-figma/Job Pilot/04 · Review · 1440.png` — packet card with "5 of 6 answers confirmed" + "View all questions →"; right rail "One answer needs you." with Needs-you/Confirmed chips, `QUESTION 6 OF 6` + `Required` chips, the visa-sponsorship question with Yes/No controls, ← Previous / "Save answer →", "Each unanswered question appears here, one at a time. Review all before approval.", and the "Not ready to authorize → Confirm the required answer to unlock approval" panel.
- `docs/design/Images-figma/Job Pilot/20 · Questions & privacy · 1440.png` — profile-side gaps: "Questions that still need you", per-gap rows with **Needs answer** / **Confirmed** chips and Add/Edit answer links; "Your choice. Never a ranking signal." EEO card with "Off · no answers saved", Manage/Delete voluntary answers, and "Only supported work-eligibility countries are selectable. Missing employer answers stop execution for your review."
- `docs/design/Images-figma/Job Pilot/11 · Application profile · 1440.png` — "Work eligibility country" select, "Visa sponsorship for this role" with "This answer is required. It is never inferred from your résumé.", right rail "Your answers have a clear source."
- Zoom detail: `docs/design/Images-figma/04.jpg`, `41.jpg`, `66.jpg`.

## Current state

- Backend: `src/db/form_questions.py` (board-scoped `form_questions`), `src/applications/questions.py` (taxonomy, `NEVER_AUTOFILL`), `src/applications/form_plan.py` (`build_question_plan`, verdicts `answerable | never_autofill | needs_human | optional_unanswered`), `src/applications/form.py::facts_with_provenance` (WS-25c country-qualified work authorization), `src/db/applications.py` (no answers storage), WS-25c `may_work_in` three-valued semantics.
- Frontend: `frontend/src/screens/review/question-card.tsx` (read-only), `frontend/src/screens/approvals-screen.tsx`, `frontend/src/components/profile/application-profile-panel.tsx` (generic "Authorized to work here?" tri-select + countries multi-select).

## Concrete tasks

**Backend (A4):**
1. New table `application_answers` — `id, owner_id, application_id, question_key, label, category, answer_text, answered_at, updated_at` + alembic revision (pattern from `migrations/versions/`); accessors in `src/db/access.py` (AST rule: no route queries the table directly).
2. Routes in `src/api/routes/applications.py`: `GET /api/applications/{application_id}/answers`, `PUT /api/applications/{application_id}/answers` (upsert list; **422 for `NEVER_AUTOFILL` categories** — EEO/attestation stay never-autofilled; answer_text length-bounded); append an `application_events` row on save.
3. `build_question_plan` / `facts_with_provenance` accept saved answers: an answer whose category matches an open question flips its verdict to `answerable` with `answer_from="you"`; `blocking_questions()` shrinks accordingly. Approval gate unchanged. Tests: `tests/test_ws45_answers.py` (CRUD via accessors, route contract, plan merge, never-autofill rejection, event row). Commits: `feat: employer answers persist per application (ws-45)`, `feat: saved answers unblock the prepare plan (ws-45)`.

**Frontend (A3/A2 file split):**
4. **Review answering UI** (`approvals-screen.tsx`, `question-card.tsx` area, new `frontend/src/screens/review/question-answer.tsx`): per the design — one-question-at-a-time card, Yes/No segmented control for booleans, input/date/select by `answer_type`, ← Previous / "Save answer →", Needs-you/Confirmed chips, "Not ready to authorize" panel that unlocks when `blocking_questions` is empty; tracker detail links here. Commit: `feat: employer questions are answered one at a time on Review (ws-45)`.
5. **Profile gaps UI** (`application-profile-panel.tsx`): gap rows with Needs answer/Confirmed chips + Add/Edit answer links per screen 20; EEO card restyle ("Off · no answers saved" chip, Manage/Delete). Commit: `feat: profile question gaps read like the questions-and-privacy design (ws-45)`.
6. **Context-dependent profile questions** (`application-profile-panel.tsx`): "Work eligibility country" multi-select over `GET /api/profiles/countries` → `authorized_countries` becomes the primary authorization question (replaces the context-free framing); visa sponsorship keeps the never-inferred note; right-rail "Your answers have a clear source." card. `may_work_in` backend semantics untouched. Commit: `feat: work authorization is asked per country, not in the abstract (ws-45)`.

## Acceptance criteria

- A required answerable question answered in the console clears `blocking_questions` and unlocks the real approve action; an EEO/attestation question cannot be saved (422) and stays routed to the employer site.
- The Review screen matches `04 · Review · 1440` (chips, counter, Save answer, Previous/next).
- The profile gaps screen matches `20 · Questions & privacy · 1440`; work-eligibility is asked per country per `11 · Application profile · 1440`.
- Backend: answers persist per application per owner; plan merge flips verdicts; event row recorded.

## Tests

- `tests/test_ws45_answers.py` (new), `tests/test_form_plan.py` extensions.
- `frontend/src/screens/approvals-screen-form-questions.test.tsx` + new answering-flow test; `application-answers-card.test.tsx` updates.
- Manual: answer → save → approval unlock flow against the fake ATS stack.

## New dependencies

None.
