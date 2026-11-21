# WS-45 — Per-application questions: answering, persistence, context-dependent profile questions

Status: **Delivered 2026-11-21** — seven commits; a human answer persists per application, the plan merges it so the approval gate unlocks, Review answers one question at a time, the profile asks work authorization per country, and one page answers every question of a prepared application.

## What shipped

| Commit | Feature |
|---|---|
| `4b63c45` | employer answers persist per application (`application_answers` + `GET`/`PUT .../answers`) |
| `b81cc99` | saved answers unblock the prepare plan (the merge) |
| `42d99b1` | employer questions are answered one at a time on Review |
| `c842967` | the tracker links to the application's questions |
| `9fb07b9` | work authorization is asked per country, and the question gaps read like the design |
| `6d0a964` | the packet keeps its questions (`approval_requests.form_questions` + `GET .../questions`) |
| `d4e8ea5` | one page answers every question of a prepared application |

**Evidence.** `tests/test_ws45_answers.py` (23 tests: CRUD, ownership, the never-autofill 422, the
plan merge, the event row), `tests/test_ws45_questions_page.py` (6 tests: the stored plan, the
saved-answer fold, the never-autofill guard, the 404 matrix), `tests/test_form_plan.py` (41 tests),
`frontend/src/screens/questions-screen.test.tsx` (4 tests) and the existing
`approvals-screen-answers.test.tsx`. The backend suite is green at **2275 passed / 0 failed**; the
FE suite at **407 tests / 49 files**.

**Reader's notes.**

- **The plan moved onto the approval row.** `GET .../questions` reads the questions the *packet*
  was built around (`approval_requests.form_questions`, migration `d3e4f5a6b7c8`) instead of
  re-fetching the employer's live form — otherwise the page would describe a form the reviewed
  packet was never built from. A saved answer is folded back into the stored verdicts on the read,
  so an answered question stops reading as "needs you" without a re-prepare.
- **The per-application page was new scope.** The sprint plan named the Review screen; the design's
  "View all questions →" had no destination at all. The page
  (`/app/tracker/:applicationId/questions`) is that missing half, reached from Review and from the
  application's own detail screen.
- **`prepare` creates a new application, and the answers follow the posting.** The console reaches
  prepare with a fresh form each time, so answers saved against a prior application for the same
  owner + `job_url` are merged into the plan and the facts, and copied onto the newly created
  application (`inherit_answers`). Without that copy a third prepare would regress to blocked.
- **Known limits recorded, not addressed here:** an unknown-category question (no fact key)
  unblocks the gate but can still stop the browser-fill walk at `FIELD_MAP`; same-category
  collisions ("Website" / "Portfolio") share one injected fact key, so last save wins.
- EEO and attestation questions are listed with their verdict and **no control**, because the API
  refuses to store such an answer (422) — policy, not a limitation.

**Live evidence (2026-11-21).** The answering loop was exercised over HTTP against an isolated copy
of the real database: the prepared packet reported the sponsorship question as `needs_human` with
it in `blocking_questions`; `PUT .../answers` returned 200; the very next `GET .../questions`
reported that question `answerable` with `answer_from="you"` and `blocking_questions` empty, with
the saved answer listed. An EEO answer was refused **422** with the policy message, and a `PUT`
sent without the `X-CSRF-Token` header was refused **403** — the CSRF control doing its job, not a
gap. The per-application page swept clean at 12 surfaces × 7 viewports (see WS-49).

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
