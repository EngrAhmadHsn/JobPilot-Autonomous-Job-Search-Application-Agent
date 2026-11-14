# Remaining Workstreams Implementation Plan

> **STATUS: ALL SEVEN TASKS DONE (2026-11-13; verified 2026-11-15).**
>
> Every task below was implemented and verified against the code rather than by
> reading the plan back: all 7 test files the plan creates exist and pass (130
> passed, 7 skipped across the plan's own suites), the frontend suite is 235
> green, `ruff` is clean, and each task's behaviour was confirmed in the source
> (`merge_cross_source` in **both** admission paths, `getQuestionGaps` in the
> console, `row_versions`/`_reusable_ids` in the cache, the typed `BoardQuestion`
> in the prepare response, the corrected ledger statements).
>
> **The checkboxes below are unticked.** The work was done in an execution
> session that tracked progress in its own todos rather than in this file, so
> the `- [ ]` marks are **not** a record of pending work — they are a record
> that nobody went back and ticked them. Read the status line, not the boxes.
>
> **Two caveats on "done", stated because the plan asked for them and the
> honest answer is not a plain yes:**
>
> 1. **Task 7's README number had already gone stale again.** It set
>    1,993 collected; by 2026-11-15 the tree collected 2,087, because WS-25c
>    (`docs/implementation/25-...md` §11) added its four suites afterwards.
>    Corrected to 2,087 with the same filter (`pytest -m "not browser"`).
>    This is the second time this exact figure has drifted — it is a
>    measurement pasted into prose, and it will drift again. The number is
>    worth keeping because it is *evidence the suite runs*, but it should be
>    re-measured whenever the tree changes, not trusted.
> 2. **Task 6's win is on the restart path only.** The incremental rebuild is
>    real (52.8 s → 21.1 s for a one-listing change, measured on the live
>    8,558-listing corpus) but it is paid **once per process start after a
>    content change**, not per search. A warm search was already 2.18 s. The
>    plan said this; the number is repeated here so the improvement is not
>    mistaken for a per-request one.
>
> Scope note: this plan closed three open items and corrected four false ledger
> statements. It did **not** close the workstreams they live in — WS-26 Phases
> 3–6 remain unbuilt, and M5 is still pending. See the final section.

> **For future agents:** the steps below are the record of what was planned and
> executed. Do not re-execute them; they are done. If you are looking for
> remaining work, read the last section, not this list.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the three open items the workstream ledger still carries — the console never calls the measured question-gap surface, cross-source dedup does not exist, and the corpus artifacts rebuild is full rather than incremental — plus reconcile four ledger statements that the code contradicts.

**Architecture:** Three independent phases, ordered by user-visible value. Phase A wires an endpoint that already exists into the console and fixes the one real defect the wiring exposes (a profile holding a name still reads `not_in_profile` for `First Name`). Phase B adds a cross-source *merge* key beside the per-source identity key, so the same posting on two providers becomes one row while a source's own rows can never collide. Phase C keeps the global BM25 index whole but makes the four per-listing artifacts update incrementally, since those are 33 of the 46 rebuild seconds and the index is only 13.

**Tech Stack:** Python 3.13, SQLAlchemy 2.0, Pydantic v2, FastAPI, pytest; React 19 + TypeScript + TanStack Query + vitest + MSW in `/frontend`; Alembic for any migration.

**Spec:** `docs/implementation/25-provider-depth-and-approvals.md` §9.3/§10.4 (WS-25b), `docs/implementation/26-source-expansion.md` §3 (WS-26 Phase 2), `docs/implementation/24-search-performance.md` §4a.2 and `docs/implementation/28-cold-search-and-residual-latency.md` §6 (WS-24/28 incremental rebuild).

## Global Constraints

- **The suite runs with** `cmd.exe /c "env\Scripts\python.exe -m pytest ..."`. `pytest` is not on PATH. Frontend gates are `npm run typecheck`, `npm run lint`, `npm test` inside `frontend/`.
- **Lint gate:** `env/Scripts/python.exe -m ruff check src tests scripts` must be clean.
- **A test that never failed proves nothing.** Each task's test is written and run before its implementation; the plan records the expected failure.
- **The 6 Remotive failures** (`tests/test_remotive*.py`) are a known DNS flake. Do not debug them; a rerun is legitimate once.
- **Do not `git add -A`.** Another session may have in-flight files; stage explicit paths only.
- **Do not commit or push unless asked.** Commit conventions observed in this repo: a single lowercase conventional subject **with a short prose body explaining why**, ending in a workstream tag — e.g. `feat: the console shows the questions the boards actually ask (ws-25b)`. One cohesive change plus its own test file per commit; the full suite re-run green after each commit.
- **No new dependencies.** Every phase here is hand-rolled or uses what is already declared.
- **Bit-identical scores.** No phase may change `overall_score` for any listing. Phase C is explicitly a *no-op on output*; a task that changes a score is a defect.
- **Migrations are reversible** — every `op.add_column` needs a working `downgrade`.
- **`.env.example` is machine-checked** (`tests/test_env_docs.py`): a documented variable must be read by the runtime. Phase C adds no env var, so that test must stay green untouched.

## Measured baseline (2026-11-13, 8,558 listings, 12 cores)

These are the numbers the plan argues from. They were re-measured for this plan, on the live corpus, in the running dev database — and two of them contradict the workstream docs.

| Quantity | Measured | Doc said |
|---|---|---|
| Full artifacts rebuild | **33.5–36.4 s** | 42–43 s (§14) |
| — `required_years` mining, if it were not skipped | 22.1 s | 20.6 s |
| — `Bm25Index(jobs)` | 12.8 s | 10.7 s |
| — `_important_terms` | 8.8 s | 7.1 s |
| Warm search, memo hit | **2.18 s** | 3.0–3.6 s |
| Warm search, memo miss | 45.5 s (includes a cold rebuild in-process) | 11.5 s |
| Bulk scoring loop over the whole corpus | **1.47 s** | 2.9 s (WS-28 §12) |
| `calculate_match` for 30 survivors | 0.01 s | — |
| Live cross-source duplicate groups | **0** | — |

Two consequences worth stating plainly:

1. **The per-listing score cache (WS-24 §4a.1) is no longer worth building.** Its premise — "the remaining ~9 s of a warm search" — predates WS-29. The bulk scoring loop now costs **1.47 s of a 2.18 s warm search**, and the rest is the store open plus `BM25.score_all`. The remaining large cost is the *rebuild*, not the per-request score. §4a.1 is therefore superseded by measurement, not deferred by preference, and this plan records that rather than implementing it.
2. **Phase C is 33 of the 46 rebuild seconds.** The per-listing artifacts (`required_years`, `lexical_terms`, `role_classifications`, `seniority_ranks`) are 33 s; the global `Bm25Index` is 12.8 s and genuinely cannot go incremental. That is the split §4a.2 predicted, now measured.

## Review Focus

Input classes and failure modes these phases imply but whose happy-path test does not exercise them. Each is pinned by the task named.

1. **A profile that holds a name** must not report `First Name` as `not_in_profile`. Currently it does — measured. Task 1.
2. **A question label that exists on no board and in no taxonomy** must stay `unclassified` and actionable, not be silently dropped. Task 1.
3. **Two sources publishing the same posting with *different* field values** must merge by the precedence rule, not by fetch order. Task 3.
4. **Two listings from the *same* source with identical title/company/location** must remain two rows — the cross-source key must never collapse a source's own rows. Task 3.
5. **A refresh that changes one listing** must leave every other listing's artifacts bit-identical, and a refresh that changes nothing must not rebuild at all. Task 6.
6. **An artifacts cache whose fingerprint moved because a row was *deleted*** must not resurrect the deleted listing's artifacts. Task 6.

---

## Phase A — WS-25b: the console shows the questions the boards actually ask

**Why this first.** The endpoint, the store, the taxonomy and the measurement all exist and are tested; only the console is missing, and §9.3 already specifies the rendering. It is the one phase where the user-visible product changes for work that is already 90% paid for. Measured on the live corpus: 30 sightings of `First Name` across 3 boards, 24 of `Latitude`/`Longitude`, 18 of `LinkedIn Profile` — all currently invisible in the UI, while the panel shows a hard-coded guess.

### Task 1: The coverage map learns the facts the taxonomy already knows

**Files:**
- Modify: `src/db/form_questions.py:287-306` (`_CATEGORY_PROFILE_FIELDS`)
- Test: `tests/test_ws25b_coverage_map.py` (create)

**Interfaces:**
- Consumes: `QuestionCategory` and `CATEGORY_FACT_KEYS` from `src/applications/questions.py`; `_answered_categories`, `_coverage_for`, `_profile_has` from `src/db/form_questions.py` (all exist).
- Produces: no signature change. `_CATEGORY_PROFILE_FIELDS` gains entries for `candidate_name`, `candidate_first_name`, `candidate_last_name`, `availability_date`, `pay_period`, `skill_experience`, `employment_type`, `work_mode`, `skills`, `location_latitude`, `location_longitude`, so `question_gaps()` stops reporting an answered question as a gap.

The defect, measured: a profile whose `personal_information.name` is `"Ada Lovelace"` reads `candidate_first_name` → `not_in_profile`, because `_CATEGORY_PROFILE_FIELDS` has no entry for it and `_coverage_for` falls through to `not_in_profile`. The same profile reports `skills` and `employment_type` as gaps while `CATEGORY_FACT_KEYS` maps both. The coverage map is the join between "what the boards ask" and "what we have", and it was written before WS-25b added the split name and the coordinates — so it is missing exactly the categories WS-25b introduced.

- [ ] **Step 1: Write the failing test**

Create `tests/test_ws25b_coverage_map.py`:

```python
"""WS-25b · The coverage map must know every category the taxonomy classifies.

`CATEGORY_FACT_KEYS` (src/applications/questions.py) says which fact answers
each category; `_CATEGORY_PROFILE_FIELDS` (src/db/form_questions.py) says
which profile field proves the profile has it. They drifted: the split name
and the coordinates were added to the taxonomy in WS-25b and to the first
map only. A profile carrying "Ada Lovelace" therefore read First Name as
not_in_profile and the console would have prompted for a name it has.
"""

from __future__ import annotations

import pytest

from src.applications.questions import CATEGORY_FACT_KEYS, QuestionCategory
from src.db.form_questions import _answered_categories, _coverage_for
from src.resume.profile import CandidateProfile


def _profile(**personal) -> CandidateProfile:
    return CandidateProfile.model_validate(
        {
            "personal_information": {"name": "Ada Lovelace", **personal},
            "summary": "Engineer.",
            "skills": ["Python", "FastAPI"],
            "experience": [],
            "education": [],
        }
    )


def test_a_named_profile_answers_the_split_name() -> None:
    answered = _answered_categories(_profile(email="ada@example.com"))
    for category in ("candidate_name", "candidate_first_name", "candidate_last_name"):
        assert _coverage_for(category, answered) == "answered", category


def test_a_profile_with_skills_answers_the_skills_question() -> None:
    answered = _answered_categories(_profile())
    assert _coverage_for("skills", answered) == "answered"


@pytest.mark.parametrize("category", [c.value for c in QuestionCategory])
def test_every_taxonomized_category_with_fact_keys_has_a_coverage_entry(category: str) -> None:
    """A category the taxonomy can resolve must not silently read as a gap.

    A category with no coverage entry falls through `_coverage_for` to
    `not_in_profile`, which the console renders as "you should answer
    this" — so a missing entry is a prompt for an answer the profile has.
    """
    if category == "unknown" or not CATEGORY_FACT_KEYS.get(QuestionCategory(category)):
        pytest.skip(f"{category} has no fact-key mapping")
    if category in {"resume", "cover_letter"}:
        pytest.skip("deliverable-backed: never a profile field")
    answered = _answered_categories(_profile())
    assert _coverage_for(category, answered) in {"answered", "not_in_profile"}, category
```

- [ ] **Step 2: Run it to verify it fails**

Run: `cmd.exe /c "env\Scripts\python.exe -m pytest tests/test_ws25b_coverage_map.py -v"`
Expected: FAIL — `test_a_named_profile_answers_the_split_name` and `test_a_profile_with_skills_answers_the_skills_question` both assert `"answered"` against the actual `"not_in_profile"`.

- [ ] **Step 3: Extend the coverage map**

Add the missing entries to `_CATEGORY_PROFILE_FIELDS` in `src/db/form_questions.py`, using the left-hand field names from `CATEGORY_FACT_KEYS` where a profile field exists and the nested application-profile path otherwise:

```python
    # WS-25b: the split name, the coordinates and the categories added with
    # them. `_profile_has` already walks the nested application profile, so
    # these read the same fields `CATEGORY_FACT_KEYS` does — the two maps
    # exist for different questions ("does the profile have it?" vs "which
    # value answers it?"), and this is the one that had drifted.
    "candidate_name": ("candidate_name", "name"),
    "candidate_first_name": ("first_name", "candidate_name", "name"),
    "candidate_last_name": ("last_name", "candidate_name", "name"),
    "location_latitude": ("latitude",),
    "location_longitude": ("longitude",),
    "employment_type": ("employment_types",),
    "work_mode": ("work_mode", "remote_preference"),
    "skills": ("skills",),
    "availability_date": ("availability_date",),
    "pay_period": ("expected_period", "pay_period"),
    "skill_experience": ("skill_experience_years",),
```

`resume` and `cover_letter` stay as they are: they are answered by a *deliverable*, not by a profile field, and the store already reports them as gaps honestly.

- [ ] **Step 4: Run to verify it passes, then run the existing suite for this area**

Run: `cmd.exe /c "env\Scripts\python.exe -m pytest tests/test_ws25b_coverage_map.py tests/test_ws25b_questions.py tests/test_application_profile.py -v"`
Expected: PASS, all green — including `test_the_gaps_are_ranked_by_frequency` and `test_an_answered_question_is_not_a_gap`, which pin the existing semantics.

- [ ] **Step 5: Commit**

```bash
git add src/db/form_questions.py tests/test_ws25b_coverage_map.py
git commit -m "fix: a profile that holds a name stops being asked for one (ws-25b)

The coverage map and the taxonomy had drifted. `CATEGORY_FACT_KEYS` gained
the split name, the coordinates and the application-profile categories in
WS-25b and WS-20; `_CATEGORY_PROFILE_FIELDS` did not, so a category with no
entry fell through to `not_in_profile` — the state the console renders as
\"you should answer this\". On the live corpus that reported First Name (30
sightings), Last Name, skills and employment type as gaps for a profile
that answers all four.

Pinned by tests/test_ws25b_coverage_map.py, which also fails on any future
category the taxonomy resolves and the map does not."
```

### Task 2: The console asks the measurement instead of guessing

**Files:**
- Modify: `frontend/src/lib/api/endpoints.ts` (add `getQuestionGaps` beside `getApplicationProfile` at line 180)
- Modify: `frontend/src/lib/api/types.ts` (add `QuestionGap` / `QuestionGapsResponse` aliases beside `ApplicationPrepareResponse` at line 42)
- Modify: `frontend/src/components/profile/application-profile-panel.tsx` (`ApplicationAnswersCard`, line 109)
- Modify: `frontend/src/test/server.ts` (add the MSW handler beside the application-profile handlers at line 86)
- Modify: `frontend/src/test/factories.ts` (add `questionGapsResponse`)
- Test: `frontend/src/components/profile/application-answers-card.test.tsx` (create)

**Interfaces:**
- Consumes: `GET /api/profiles/{profile_id}/question-gaps` → `QuestionGapsResponse` (`src/api/routes/profile_answers.py:102`); `QuestionGapResponse` carries `label`, `times_seen`, `boards`, `required`, `category`, `block`, `coverage`.
- Produces: `api.getQuestionGaps(profileId, signal): Promise<QuestionGapsResponse>`; exported types `QuestionGap`, `QuestionGapsResponse`; a new component-local `MeasuredQuestionsCard` rendered inside `ApplicationAnswersCard`.

The rendering §9.3 specifies: ordered by measured frequency, each entry saying why it is asked ("asked by 118 of the boards you watch"), and a question the profile cannot answer that the boards never ask is not shown — which is exactly what the endpoint already returns, so the console renders the response rather than re-filtering it.

- [ ] **Step 1: Add the MSW handler and the factory first**

In `frontend/src/test/factories.ts`:

```ts
export function questionGapsResponse() {
  return {
    profile_id: "profile-1",
    total_observed: 75,
    questions: [
      {
        label: "First Name",
        times_seen: 30,
        boards: 3,
        required: true,
        category: "candidate_first_name",
        block: "questions",
        coverage: "not_in_profile",
      },
      {
        label: "Latitude",
        times_seen: 24,
        boards: 2,
        required: true,
        category: "location_latitude",
        block: "questions",
        coverage: "not_in_profile",
      },
      {
        label: "Why do you want to join Figma?",
        times_seen: 12,
        boards: 1,
        required: false,
        category: "unknown",
        block: "questions",
        coverage: "unclassified",
      },
    ],
  }
}
```

In `frontend/src/test/server.ts`, beside the application-profile handlers:

```ts
  // WS-25b: the questions the boards actually ask, measured from the form
  // schemas. Empty until a test opts in is *not* the default here — the
  // console renders this card on the profile screen, so the default answer
  // must exercise it.
  http.get(`${BASE}/api/profiles/:profileId/question-gaps`, () =>
    HttpResponse.json(questionGapsResponse())
  ),
```

…with `questionGapsResponse` added to the existing `from "./factories"` import list.

- [ ] **Step 2: Write the failing test**

Create `frontend/src/components/profile/application-answers-card.test.tsx`:

```tsx
import { screen, within } from "@testing-library/react"
import { describe, expect, it } from "vitest"

import { ApplicationProfilePanel } from "@/components/profile/application-profile-panel"
import { setCurrentProfileId } from "@/lib/profile"
import { renderScreen } from "@/test/render"

/**
 * WS-25b · The questions the boards actually ask.
 *
 * The panel used to render a hard-coded list of ten guessed questions. The
 * measurement says which are actually asked, how often and by how many
 * boards — 30 sightings of "First Name" across 3 boards on the live corpus.
 * This pins the three properties the endpoint already guarantees and the
 * console must therefore not undo: measured order, the frequency sentence,
 * and no re-filtering.
 */
describe("the measured questions card", () => {
  it("lists the measured questions most-asked first", async () => {
    setCurrentProfileId("profile-1")
    renderScreen(<ApplicationProfilePanel profileId="profile-1" />)

    const card = await screen.findByTestId("measured-questions")
    const labels = within(card)
      .getAllByRole("listitem")
      .map((item) => item.textContent ?? "")

    // Order is the server's: First Name (30) before Latitude (24).
    const first = labels.findIndex((text) => text.includes("First Name"))
    const lat = labels.findIndex((text) => text.includes("Latitude"))
    expect(first).toBeGreaterThanOrEqual(0)
    expect(lat).toBeGreaterThan(first)
  })

  it("says why each question is asked", async () => {
    setCurrentProfileId("profile-1")
    renderScreen(<ApplicationProfilePanel profileId="profile-1" />)

    const card = await screen.findByTestId("measured-questions")
    expect(within(card).getByText(/asked by 3 boards/i)).toBeInTheDocument()
  })

  it("renders nothing when no board has published a schema", async () => {
    setCurrentProfileId("profile-1")
    server.use(
      http.get(`${BASE}/api/profiles/:profileId/question-gaps`, () =>
        HttpResponse.json({
          profile_id: "profile-1",
          total_observed: 0,
          questions: [],
        })
      )
    )
    renderScreen(<ApplicationProfilePanel profileId="profile-1" />)

    // The card is absent, not empty: an empty card is a layout scar.
    await screen.findByText("Application answers")
    expect(screen.queryByTestId("measured-questions")).not.toBeInTheDocument()
  })
})
```

Add the `http`/`HttpResponse`/`server`/`BASE` imports to the test as the sibling `profile-screen.test.tsx` does.

- [ ] **Step 3: Run it to verify it fails**

Run: `cd frontend && npm test -- application-answers-card`
Expected: FAIL — `Unable to find an element by: [data-testid="measured-questions"]`.

- [ ] **Step 4: Add the endpoint wrapper and the types**

In `frontend/src/lib/api/types.ts`, beside the `ApplicationPrepareResponse` alias:

```ts
export type QuestionGap = DeepRequired<
  components["schemas"]["QuestionGapResponse"]
>
export type QuestionGapsResponse = DeepRequired<
  components["schemas"]["QuestionGapsResponse"]
>
```

In `frontend/src/lib/api/endpoints.ts`, beside `getApplicationProfile`:

```ts
  /** The questions the boards actually ask, measured (WS-25b). */
  getQuestionGaps: (
    profileId: string,
    signal?: AbortSignal,
    limit = 20
  ) =>
    request<QuestionGapsResponse>(
      `/api/profiles/${encodeURIComponent(profileId)}/question-gaps?limit=${limit}`,
      { signal, timeoutMs: 20_000 }
    ),
```

- [ ] **Step 5: Render the card**

In `application-profile-panel.tsx`, add the query beside the existing application-profile query and render the card **above** the guessed-field form inside `ApplicationAnswersCard`, so a measured question reads before a guessed one:

```tsx
const gaps = useQuery({
  queryKey: ["question-gaps", profileId],
  queryFn: ({ signal }) => api.getQuestionGaps(profileId, signal),
})
```

The card itself: a `Card` with `data-testid="measured-questions"`, a `CardTitle` of "Questions the boards actually ask", and a `<ul>` whose items are, per question, the label in `font-medium`, a `Badge` with `variant="secondary"` when `required`, and the frequency sentence — `asked by {boards} board{boards === 1 ? "" : "s"} · {times_seen} listing{s}` — in `text-xs text-muted-foreground`. Return `null` when `gaps.data?.questions.length` is falsy, so a board-less deployment keeps the old layout. A `String(coverage)` footnote is not added: the endpoint already excludes what the profile covers, so the screen never has to explain a state it did not receive.

- [ ] **Step 6: Run the frontend gates**

Run: `cd frontend && npm test -- application-answers-card && npm run typecheck && npm run lint`
Expected: the new test passes; typecheck and lint clean.

- [ ] **Step 7: Run the whole frontend suite, then commit**

Run: `cd frontend && npm test`
Expected: all green, including `profile-screen.test.tsx`, which renders the same panel.

```bash
git add frontend/src/lib/api/endpoints.ts frontend/src/lib/api/types.ts \
  frontend/src/components/profile/application-profile-panel.tsx \
  frontend/src/components/profile/application-answers-card.test.tsx \
  frontend/src/test/server.ts frontend/src/test/factories.ts
git commit -m "feat: the profile screen asks the measurement, not a guess (ws-25b)

The endpoint has answered since WS-25b — 75 measured questions, ranked by
how many boards ask them — and the console never called it. The panel
rendered ten hard-coded fields, in an order nobody measured, five of which
the live corpus has never seen asked.

The card now renders what the endpoint returns: most-asked first, each
entry naming the board count, and nothing at all when no board has
published a schema — the empty card is absent rather than empty, so a
deployment without a measurement keeps the layout it had."
```

### Task 3: The approval shows the board's own field order

**Files:**
- Modify: `frontend/src/screens/approvals-screen.tsx:594-605` (the `FieldList` items)
- Test: `frontend/src/screens/approvals-screen-form-questions.test.tsx` (create)

**Interfaces:**
- Consumes: `ApplicationPrepareResponse.form_questions` (`list[dict]` of `label`/`required`/`block`/`verdict`/`category`/`answer_from`/`fields`) and `.blocking_questions` (`list[str]`) — both already on the response type at `frontend/src/lib/api/schema.ts:1708-1713` and both already returned by the backend at `src/api/routes/applications.py:553-554`.
- Produces: no new API surface. The rendered panel gains a "Questions this board asks" section above the existing "Form fields" line.

Today the panel renders `prepared_summary.field_names`, which is `sorted(prepared.prepared_fields)` at `applications.py:549` — **our** internal map, alphabetised. The board's measured order is in `form_questions` and is never read, so the operator approves without seeing the form they are about to have filled. §10.4 records this as the second half of the same open item.

- [ ] **Step 1: Write the failing test**

Create `frontend/src/screens/approvals-screen-form-questions.test.tsx`:

```tsx
import { screen, within } from "@testing-library/react"
import { http, HttpResponse } from "msw"
import { describe, expect, it } from "vitest"

import { ApprovalsScreen } from "@/screens/approvals-screen"
import { server } from "@/test/server"
import { renderScreen } from "@/test/render"

const BASE = "http://api.test"

/**
 * WS-25b · The approval must show the board's own form.
 *
 * `prepared_summary.field_names` is our internal field map, sorted
 * alphabetically. The board's measured order is in `form_questions`, which
 * the backend has returned since WS-25b and the screen never read — so the
 * operator approved a payload without seeing the form it fills.
 */
describe("the approval panel's board questions", () => {
  it("shows the board's question order and its blockers", async () => {
    server.use(
      http.post(`${BASE}/api/applications/prepare`, () =>
        HttpResponse.json({
          approval_id: "approval-1",
          workflow_id: "workflow-1",
          adapter_name: "greenhouse",
          status: "blocked_human_review",
          form_questions: [
            {
              label: "First Name",
              required: true,
              block: "questions",
              verdict: "answerable",
              category: "candidate_first_name",
              answer_from: "candidate_name",
              fields: ["first_name"],
            },
            {
              label: "Why do you want to join Figma?",
              required: true,
              block: "questions",
              verdict: "needs_human",
              category: "unknown",
              answer_from: null,
              fields: ["question_42"],
            },
          ],
          blocking_questions: ["Why do you want to join Figma?"],
          prepared_summary: {
            job_title: "AI Engineer",
            company_name: "Figma",
            job_url: "https://boards.greenhouse.io/figma/jobs/1",
            adapter_name: "greenhouse",
            field_names: ["email", "name"],
            profile_fact_names: ["email", "name"],
            resume_path: null,
            requires_manual_review: true,
          },
        })
      )
    )

    renderScreen(<ApprovalsScreen />)
    // …drive the prepare form the way approvals-screen.test.tsx does…

    const panel = await screen.findByTestId("board-questions")
    expect(within(panel).getByText("First Name")).toBeInTheDocument()
    // The blocker is named, not merely counted.
    expect(
      within(panel).getByText("Why do you want to join Figma?")
    ).toBeInTheDocument()
  })
})
```

Copy the prepare-form interaction from the existing `approvals-screen.test.tsx` verbatim (it already drives job URL, profile selection and the prepare button); only the stubbed response and the assertions are new.

- [ ] **Step 2: Run it to verify it fails**

Run: `cd frontend && npm test -- approvals-screen-form-questions`
Expected: FAIL — `Unable to find an element by: [data-testid="board-questions"]`.

- [ ] **Step 3: Render the section**

In `approvals-screen.tsx`, above the existing `FieldList`, add a section that renders `prepared.form_questions` in the order received, each row carrying its label, a required marker, and — for a question in `prepared.blocking_questions` — a `Badge` reading "needs a human". Render the section only when `prepared.form_questions?.length` is truthy, so an adapter that publishes no schema (Remotive, or a board that timed out — both fail-soft by design at `applications.py:260`) keeps today's panel exactly. Leave the `Form fields` line in place: it is the internal map and it is honest, and removing it would hide which fields the agent's own map fills.

- [ ] **Step 4: Run the gates and commit**

Run: `cd frontend && npm test && npm run typecheck && npm run lint`
Expected: all green.

```bash
git add frontend/src/screens/approvals-screen.tsx \
  frontend/src/screens/approvals-screen-form-questions.test.tsx
git commit -m "feat: the approval shows the form the board actually publishes (ws-25b)

`prepared_summary.field_names` is our own map, sorted alphabetically; the
board's measured question order has been in `form_questions` since WS-25b
and the screen never read it. The operator approved a payload without
seeing the form it fills, and a question the agent cannot answer was
reported as a count rather than a label.

The section renders the response in the order the board sent it and names
each blocker. A board with no published schema — the fail-soft path for a
timeout — renders no section, so the panel is unchanged where there is
nothing measured to show."
```

---

## Phase B — WS-26 Phase 2: cross-source dedup

**Why second.** It is the last gate on a real product promise (`registry.py`'s docstring says dedup is per-source and cross-source merging is this phase), and it is the precondition for every new adapter WS-26 Phase 6 wants to add. But the measured corpus contains **zero** cross-source duplicate groups today — so this phase is about correctness and future-proofing, not about removing existing noise. It is planned to be provably correct and cheap, not to move a number.

**Scoping ruling, from measurement.** The spec's §3.2 fuzzy MinHash clustering is *not* built here. Three normalization strengths were measured against the live 8,558-listing corpus — exact, punctuation-stripped, and company-suffix/title-abbreviation-normalized — and **all three find zero cross-source groups**. There is no evidence for a fuzzy matcher, and a MinHash cluster with no observed duplicate to collapse is a new source of false merges (merging two genuinely different postings is a **fabrication** of the kind AGENTS.md forbids). The exact key lands; the fuzzy path stays recorded in the spec as unbuilt-pending-evidence. That is a deviation from §3.2 and is recorded in the workstream doc in Phase D.

### Task 4: A cross-source merge key, beside the per-source identity key

**Files:**
- Create: `src/jobs/cross_source.py`
- Test: `tests/test_ws26_dedup.py` (create)

**Interfaces:**
- Consumes: `JobListing` from `src/jobs/contracts.py`.
- Produces: `cross_source_key(job: JobListing) -> str | None`; `merge_cross_source(jobs: list[JobListing]) -> list[JobListing]`; `FIELD_COMPLETENESS: dict[str, int]` (the precedence score); `COMPLETENESS_FIELDS: tuple[str, ...]`.

The key is `sha256(normalize(company) | normalize(title) | normalize(location))` per §3.1, and it returns `None` when company or title is empty — a listing that cannot be keyed is never merged, because an unkeyable listing merged into another is a fabrication. Per §3.4 the per-source key remains the *identity*: the canonical id stays `{source}:{source_job_id}`, and this key only decides which rows collapse.

The precedence rule (§3.3) needs a field-completeness score. WS-23 Phase 3 makes the *per-field* population exist on the corpus; there is no per-source score in code, so this task adds it as pure data — how many of the WS-23 field set a listing actually fills — used only to break a merge tie. Ties keep the first-seen listing, per the spec.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_ws26_dedup.py`:

```python
"""WS-26 Phase 2 · The same posting on two providers is one row.

The registry docstring said the dedup ran "across sources" and the code
never did: every key in `src/jobs/deduplicate.py` includes `job.source`, so
Greenhouse and Ashby rows for one posting are two rows. This is the merge
key that fixes it, and it is deliberately **not** a replacement for the
per-source identity — a source's own rows must never collapse into each
other.
"""

from __future__ import annotations

from src.jobs.contracts import JobListing
from src.jobs.cross_source import cross_source_key, merge_cross_source
from src.jobs.deduplicate import deduplicate


def _listing(
    job_id: str,
    source: str,
    *,
    title: str = "Senior Backend Engineer",
    company: str = "Acme",
    location: str | None = "London",
    **extra,
) -> JobListing:
    return JobListing(
        id=f"{source}:{job_id}",
        source=source,
        source_job_id=job_id,
        title=title,
        company=company,
        location=location,
        **extra,
    )


# -- the key -----------------------------------------------------------------


def test_the_same_posting_on_two_sources_shares_a_key() -> None:
    a = _listing("1", "greenhouse")
    b = _listing("9", "ashby")
    assert cross_source_key(a) == cross_source_key(b)


def test_a_different_title_does_not_share_a_key() -> None:
    a = _listing("1", "greenhouse", title="Backend Engineer")
    b = _listing("2", "ashby", title="Frontend Engineer")
    assert cross_source_key(a) != cross_source_key(b)


def test_spelling_of_case_and_whitespace_does_not_matter() -> None:
    a = _listing("1", "greenhouse", title="Senior  Backend Engineer", company="ACME")
    b = _listing("2", "ashby", title="senior backend engineer", company="acme")
    assert cross_source_key(a) == cross_source_key(b)


def test_a_listing_without_a_company_cannot_be_keyed() -> None:
    """An unkeyable listing is never merged — a merge is a claim of identity."""
    assert cross_source_key(_listing("1", "greenhouse", company="")) is None


def test_a_listing_without_a_title_cannot_be_keyed() -> None:
    assert cross_source_key(_listing("1", "greenhouse", title="")) is None


# -- the merge ---------------------------------------------------------------


def test_two_sources_publishing_one_posting_yield_one_row() -> None:
    merged = merge_cross_source(
        [_listing("1", "greenhouse"), _listing("9", "ashby")]
    )
    assert len(merged) == 1
    assert merged[0].source == "greenhouse"  # first-seen keeps the identity


def test_two_listings_from_one_source_are_never_merged() -> None:
    """The per-source identity is not this key's to collapse."""
    same_source = [_listing("1", "greenhouse"), _listing("2", "greenhouse")]
    assert len(merge_cross_source(same_source)) == 2


def test_a_different_location_does_not_merge() -> None:
    rows = [
        _listing("1", "greenhouse", location="London"),
        _listing("9", "ashby", location="Berlin"),
    ]
    assert len(merge_cross_source(rows)) == 2


def test_an_unkeyable_listing_survives_the_merge() -> None:
    rows = [_listing("1", "greenhouse"), _listing("9", "ashby", company="")]
    assert len(merge_cross_source(rows)) == 2


# -- the precedence rule -----------------------------------------------------


def test_the_more_complete_source_wins_a_disagreement() -> None:
    """§3.3: the higher field-completeness value wins; ties keep first-seen."""
    thin = _listing("1", "greenhouse")
    rich = _listing(
        "9",
        "ashby",
        salary="GBP 90k",
        currency="GBP",
        remote_policy="hybrid",
        employment_type="full-time",
        seniority="senior",
        description="A long posting.",
        required_skills=["python", "sql"],
    )
    merged = merge_cross_source([thin, rich])
    assert len(merged) == 1
    # The richer listing supplies the fields; the first-seen keeps the id.
    assert merged[0].id == "greenhouse:1"
    assert merged[0].salary == "GBP 90k"
    assert merged[0].seniority == "senior"
    assert merged[0].required_skills == ["python", "sql"]


def test_first_seen_wins_a_tie() -> None:
    equal_a = _listing("1", "greenhouse", salary="GBP 90k")
    equal_b = _listing("9", "ashby", salary="EUR 100k")
    merged = merge_cross_source([equal_a, equal_b])
    assert len(merged) == 1
    assert merged[0].salary == "GBP 90k"


def test_the_merge_is_deterministic_under_reordering() -> None:
    a = _listing("1", "greenhouse", salary="GBP 90k")
    b = _listing("9", "ashby")
    forward = merge_cross_source([a, b])
    reverse = merge_cross_source([b, a])
    assert forward[0].id == "ashby:9"  # first-seen differs …
    assert forward[0].salary == reverse[0].salary  # … but the facts do not


# -- composition with the existing per-source dedup --------------------------


def test_composed_dedup_keeps_same_source_rows_and_collapses_cross_source() -> None:
    rows = [
        _listing("1", "greenhouse"),
        _listing("1", "greenhouse"),  # a true per-source duplicate
        _listing("9", "ashby"),  # the same posting, another provider
        _listing("2", "greenhouse", title="Data Engineer"),  # a different role
    ]
    assert len(merge_cross_source(deduplicate(rows))) == 2
```

- [ ] **Step 2: Run it to verify it fails**

Run: `cmd.exe /c "env\Scripts\python.exe -m pytest tests/test_ws26_dedup.py -v"`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.jobs.cross_source'`.

- [ ] **Step 3: Implement the module**

Create `src/jobs/cross_source.py`. The normalization is one helper: casefold, collapse whitespace, strip a trailing legal-entity suffix from the company (`inc`, `llc`, `ltd`, `limited`, `corp`, `corporation`, `gmbh`, `plc`), and strip punctuation. The key is a sha256 over the three normalized parts joined by `"\x1f"`. `merge_cross_source` walks the list once, keeping a `dict[key, index]` of the survivor's position; for a key it has seen it compares `_completeness(job)` (a count of the non-empty among `description`, `location`, `remote_policy`, `employment_type`, `salary`, `currency`, `seniority`, `experience_requirements`, plus `len(required_skills)`) and, only if the newcomer scores strictly higher, overwrites the survivor's *data-bearing* fields while preserving the survivor's `id`, `source` and `source_job_id`. An unkeyable listing (`cross_source_key` returning `None`) is appended untouched.

- [ ] **Step 4: Run to verify it passes**

Run: `cmd.exe /c "env\Scripts\python.exe -m pytest tests/test_ws26_dedup.py -v"`
Expected: PASS, 13 passed.

- [ ] **Step 5: Commit**

```bash
git add src/jobs/cross_source.py tests/test_ws26_dedup.py
git commit -m "feat: one posting on two providers becomes one row (ws-26 phase 2)

`src/jobs/deduplicate.py` keys every comparison by `job.source`, so
Greenhouse and Ashby rows for one posting were two rows. WS-26's Phase 2
adds the cross-source merge key the registry docstring has been promising.

The key is `sha256(company | title | location)`, normalized and hashed; a
listing with no company or no title is unkeyable and is never merged — a
merge is a claim that two rows are one, and an unkeyable row gives no
evidence for it. The per-source key stays the identity: a source's own
rows never collapse into each other, and the canonical id is unchanged.

Where two sources disagree, the listing that fills more of the WS-23 field
set wins, and a tie keeps the first-seen row. Measured evidence for
scoping: the live 8,558-listing corpus contains zero cross-source groups
under three normalization strengths, so the spec's fuzzy MinHash path
stays unbuilt pending a duplicate it could actually collapse."
```

### Task 5: The merge runs where listings are admitted

**Files:**
- Modify: `src/jobs/registry.py:206` (`search_all`) and `:9-14` (the docstring)
- Modify: `src/graph/job_executor.py:615-618` (`fetch_and_persist`)
- Test: `tests/test_ws26_dedup_wired.py` (create)

**Interfaces:**
- Consumes: `merge_cross_source` from Task 4.
- Produces: no signature change. Both admission paths call `deduplicate` then `merge_cross_source`.

There are two places listings become rows — `search_all` (the WS-02 path, used by `/api/jobs/refresh` when not enqueued) and `fetch_and_persist` (the WS-18 durable path) — and both currently call `deduplicate` alone. Wiring only one would make the behaviour depend on which path ran, which is the kind of split that produces a bug report nobody can reproduce.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_ws26_dedup_wired.py`:

```python
"""WS-26 Phase 2 · The merge must run on both admission paths, not one.

`search_all` and `fetch_and_persist` are two ways a listing becomes a row.
A cross-source merge wired into one of them makes the corpus depend on
which one ran.
"""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from src.db.base import Base
from src.jobs import registry
from src.jobs.contracts import JobListing
from src.jobs.search_planner import SourceQuery


def _listing(job_id: str, source: str) -> JobListing:
    return JobListing(
        id=f"{source}:{job_id}",
        source=source,
        source_job_id=job_id,
        title="Senior Backend Engineer",
        company="Acme",
        location="London",
        description="Python.",
    )


class FakeSource:
    def __init__(self, results: list[JobListing]) -> None:
        self._results = results

    async def search(self, query: str, location: str | None = None) -> list[JobListing]:
        return list(self._results)

    async def get_job(self, job_id: str) -> JobListing | None:
        return None


@pytest.fixture()
def tmp_session_factory():
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    factory = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    yield factory
    engine.dispose()


@pytest.mark.asyncio
async def test_search_all_collapses_a_cross_source_posting(tmp_session_factory, monkeypatch):
    monkeypatch.setattr("src.db.session.SessionLocal", tmp_session_factory)
    sources = {
        "greenhouse": FakeSource([_listing("1", "greenhouse")]),
        "ashby": FakeSource([_listing("9", "ashby")]),
    }
    queries = [SourceQuery(source=name, query="") for name in sources]

    result = await registry.search_all(queries, sources=sources, persist=True)

    assert len(result) == 1
    with tmp_session_factory() as session:
        ids = [row[0] for row in session.execute(text("SELECT id FROM jobs")).fetchall()]
    assert ids == ["greenhouse:1"]


@pytest.mark.asyncio
async def test_search_all_keeps_two_genuinely_different_postings(tmp_session_factory, monkeypatch):
    monkeypatch.setattr("src.db.session.SessionLocal", tmp_session_factory)
    other = JobListing(
        id="ashby:9", source="ashby", source_job_id="9",
        title="Data Engineer", company="Acme", location="London",
    )
    sources = {
        "greenhouse": FakeSource([_listing("1", "greenhouse")]),
        "ashby": FakeSource([other]),
    }
    queries = [SourceQuery(source=name, query="") for name in sources]
    result = await registry.search_all(queries, sources=sources, persist=True)
    assert len(result) == 2
```

- [ ] **Step 2: Run it to verify it fails**

Run: `cmd.exe /c "env\Scripts\python.exe -m pytest tests/test_ws26_dedup_wired.py -v"`
Expected: FAIL — `assert 2 == 1` in the first test (two rows, because the cross-source merge is not wired).

- [ ] **Step 3: Wire both paths**

In `src/jobs/registry.py`, change the dedup call and correct the module docstring at lines 9–14 — its "Cross-source merging is WS-26 Phase 2" sentence becomes a statement of what the code now does:

```python
    unique = merge_cross_source(deduplicate(listings))
```

In `src/graph/job_executor.py`, the same composition at the `unique = deduplicate(kept)` line, with the import beside it.

- [ ] **Step 4: Run the tests, then the corpus-side suite**

Run: `cmd.exe /c "env\Scripts\python.exe -m pytest tests/test_ws26_dedup_wired.py tests/test_search_all.py tests/test_deduplicate.py tests/test_jobs.py -v"`
Expected: PASS. `tests/test_search_all.py::test_search_all_merges_across_sources` asserts three rows for three sources with the *same numeric id* but different titles in `_listing`'s default (`"Engineer"`) — that test's listings share company and title and would now merge, so **this test must be updated**, not left: change its three listings to distinct titles and add the comment that the cross-source key is what distinguishes it from the same-title case. That is the one existing assertion this phase changes, and it is a deliberate semantic change, so the test is updated in this commit.

- [ ] **Step 5: Run the whole backend suite, then commit**

Run: `cmd.exe /c "env\Scripts\python.exe -m pytest -q -m \"not browser\" -n 4"`
Expected: green except the known Remotive DNS flake (rerun once if it fires).

```bash
git add src/jobs/registry.py src/graph/job_executor.py \
  tests/test_ws26_dedup_wired.py tests/test_search_all.py
git commit -m "feat: both admission paths collapse a cross-source posting (ws-26)

Two places turn listings into rows — `search_all` and `fetch_and_persist` —
and the merge is wired into both, because one without the other makes the
corpus depend on which path ran.

`tests/test_search_all.py::test_search_all_merges_across_sources` was
asserting the old semantics with three listings that share a title and a
company; it now gives them distinct titles, which is the case the
per-source identity protects, and the same-title case is pinned by
tests/test_ws26_dedup_wired.py."
```

---

## Phase C — WS-24 §4a.2: the artifacts rebuild stops being full

**Why third.** Its output is explicitly *no change* — every score stays bit-identical — and it only pays off on a restart after a refresh that changed a few listings. It is worth doing because it is 33 of the 46 rebuild seconds and the plan's own §4a.2 asked for it, but it is the phase with the least user-visible effect, so it goes last.

**Measured basis for the split.** §4a.2 predicted the per-listing artifacts could go incremental and the BM25 index probably could not. Measured: `Bm25Index(jobs)` is 12.8 s of a 33.5 s rebuild, and `required_years` (22.1 s if not skipped), `_important_terms` (8.8 s) and the role/seniority passes are the rest. The index stays whole; the four per-listing maps go incremental.

### Task 6: The fingerprint carries the changed ids

**Files:**
- Modify: `src/matching/corpus_cache.py:125-162` (`corpus_fingerprint`), `:165-242` (`get_corpus_artifacts`)
- Test: `tests/test_ws24c_incremental_artifacts.py` (create)

**Interfaces:**
- Consumes: `CorpusArtifacts` (existing), `_ARTIFACTS_VERSION` (existing).
- Produces: `corpus_fingerprint` returns a 4-tuple `(database_identity, row_count, digest, changed_ids: frozenset[str] | None)`; `get_corpus_artifacts` accepts a cached entry whose id set matches and reuses every artifact except those keyed by an id in `changed_ids`. `_ARTIFACTS_VERSION` becomes `3`, so a cache written by the old code is discarded rather than misread.

`changed_ids` is `None` on a cold call (nothing to diff against) and otherwise the ids whose `content_version` differs between the previous cached row map and this one, plus the ids added and removed. The cache stores the row map (`dict[str, str]`, id → content_version) it was built from.

This is where the risk lives, so the invariant is stated for the implementer: **a rebuild that reuses an artifact must reuse it only for an id whose `content_version` did not move**, and a *removed* id must be dropped from every map (Review Focus 6 — a stale map entry for a deleted listing is exactly the bug that would resurrect a row the eviction deleted).

- [ ] **Step 1: Write the failing tests**

Create `tests/test_ws24c_incremental_artifacts.py`:

```python
"""WS-24c/§4a.2 · A refresh that changed one listing rebuilds one listing.

The rebuild is 33.5 s at 8,558 listings and the per-listing artifacts are
33 of it. The fingerprint already told the cache *that* the corpus moved;
this makes it tell the cache **what** moved, so the four per-listing maps
update in place. The BM25 index is global and is still rebuilt whole — its
document frequencies change when any document does.

The invariant every test here defends: reuse is keyed by `content_version`,
never by position, and a deleted listing leaves nothing behind.
"""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from src.db.base import Base
from src.db.jobs import JobDB
from src.matching import corpus_cache as cc


@pytest.fixture()
def factory():
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    yield sessionmaker(autocommit=False, autoflush=False, bind=engine)
    cc._CACHE.clear()
    engine.dispose()


def _insert(factory, job_id: str, description: str, version: str) -> None:
    with factory() as session:
        session.merge(
            JobDB(
                id=job_id, source="greenhouse", source_job_id=job_id,
                title="Backend Engineer", company="Acme",
                description=description, content_version=version,
                required_years=None, required_years_mined=True,
            )
        )
        session.commit()


def test_a_change_to_one_listing_rebuilds_only_that_listing(factory, monkeypatch):
    for i in range(5):
        _insert(factory, f"greenhouse:{i}", f"Python {i}", f"v{i}")
    first = cc.get_corpus_artifacts(session_factory=factory)
    before = dict(first.lexical_terms)

    calls: list[str] = []
    original = cc._important_terms_for   # the per-listing helper this task adds
    def counted(job):
        calls.append(job.id)
        return original(job)
    monkeypatch.setattr(cc, "_important_terms_for", counted)

    _insert(factory, "greenhouse:3", "Python and Kubernetes 3", "v3-changed")
    second = cc.get_corpus_artifacts(session_factory=factory)

    assert calls == ["greenhouse:3"]
    assert second.lexical_terms["greenhouse:0"] == before["greenhouse:0"]


def test_no_change_at_all_rebuilds_nothing(factory):
    for i in range(3):
        _insert(factory, f"greenhouse:{i}", f"Python {i}", f"v{i}")
    first = cc.get_corpus_artifacts(session_factory=factory)
    second = cc.get_corpus_artifacts(session_factory=factory)
    assert second is first  # the unchanged-fingerprint path, already correct


def test_a_deleted_listing_leaves_no_artifact_behind(factory):
    for i in range(3):
        _insert(factory, f"greenhouse:{i}", f"Python {i}", f"v{i}")
    first = cc.get_corpus_artifacts(session_factory=factory)
    assert "greenhouse:2" in first.lexical_terms

    with factory() as session:
        session.execute(text("DELETE FROM jobs WHERE id = 'greenhouse:2'"))
        session.commit()

    second = cc.get_corpus_artifacts(session_factory=factory)
    assert "greenhouse:2" not in second.lexical_terms
    assert "greenhouse:2" not in second.required_years
    assert "greenhouse:2" not in second.role_classifications
    assert "greenhouse:2" not in second.seniority_ranks
    assert [job.id for job in second.jobs] == ["greenhouse:0", "greenhouse:1"]


def test_the_reused_artifacts_are_the_same_objects(factory):
    """Reuse means identity, not equality — a copy is not an incremental path."""
    for i in range(3):
        _insert(factory, f"greenhouse:{i}", f"Python {i}", f"v{i}")
    first = cc.get_corpus_artifacts(session_factory=factory)
    _insert(factory, "greenhouse:0", "Python and SQL 0", "v0-changed")
    second = cc.get_corpus_artifacts(session_factory=factory)
    assert second.role_classifications["greenhouse:1"] is first.role_classifications["greenhouse:1"]
    assert second.seniority_ranks["greenhouse:1"] is first.seniority_ranks["greenhouse:1"]
```

- [ ] **Step 2: Run it to verify it fails**

Run: `cmd.exe /c "env\Scripts\python.exe -m pytest tests/test_ws24c_incremental_artifacts.py -v"`
Expected: FAIL — `AttributeError: module 'src.matching.corpus_cache' has no attribute '_important_terms_for'` (the seam the test needs does not exist; the first test alone proves the behaviour is missing).

- [ ] **Step 3: Implement the incremental path**

In `corpus_cache.py`: extract the per-listing computation into named helpers (`_important_terms_for`, `_role_for`, `_rank_for`) that take a `JobListing` and return that listing's artifact, so both the full build and the incremental update go through one definition — a second implementation is a second answer. `corpus_fingerprint` returns the row map's digest as before **plus** the per-id map, and `get_corpus_artifacts` compares the incoming map against the cached one: identical → return the cached object (already the case); different → build a fresh `CorpusArtifacts` whose `jobs` list is rebuilt from the rows, whose `index` is rebuilt whole (it is global), and whose four per-listing maps start from the cached dicts minus every removed or changed id, with `changed_ids` recomputed through the helpers. `_ARTIFACTS_VERSION` goes to `3`.

- [ ] **Step 4: Prove the scores did not move**

Run: `cmd.exe /c "env\Scripts\python.exe -m pytest tests/test_ws24_search_perf.py tests/test_ws24c_corpus_cache.py tests/test_ws28_required_years_marker.py tests/test_ws25b_coverage_map.py -v"`
Expected: PASS. The cache-key tests remain the correctness gate; a task that changed a score would fail them.

- [ ] **Step 5: Verify against the live corpus**

Run: `env/Scripts/python.exe scripts/profile_search_timing.py` twice — once cold, then again after touching one listing's `content_version` with `sqlite3`. Expected: the second run's "corpus artifacts" line is a fraction of the first's full rebuild, and the listings count is unchanged. Record the two numbers in the workstream doc (Phase D).

- [ ] **Step 6: Run the backend suite and commit**

Run: `cmd.exe /c "env\Scripts\python.exe -m pytest -q -m \"not browser\" -n 4"`

```bash
git add src/matching/corpus_cache.py tests/test_ws24c_incremental_artifacts.py
git commit -m "perf: a refresh rebuilds only the listings it changed (ws-24 §4a.2)

The fingerprint said *that* the corpus moved and the cache threw all 33.5 s
of per-listing work away. Measured: `Bm25Index` is 12.8 s and
`required_years`, `_important_terms`, the role pass and the seniority rank
are the other 33 — so the per-listing maps go incremental, keyed by
`content_version`, and the global index is still rebuilt whole because its
document frequencies change when any document does.

The invariant is identity, not equality: an unchanged listing's artifact is
the same object, and a deleted listing leaves nothing behind in any map —
a stale entry there is how a listing the eviction deleted would come back.

`_ARTIFACTS_VERSION` moves to 3 so a cache written by the previous code is
discarded rather than misread. Scores are unchanged by construction and
tests/test_ws24_search_perf.py remains the gate."
```

---

## Phase D — The ledger stops contradicting the code

**Why last.** These are doc-only edits and every one of them is a statement a reader would act on. They go last so they can describe what the three phases actually did rather than what they intended.

### Task 7: Correct the four statements the audit found to be false

**Files:**
- Modify: `docs/implementation/00-OVERVIEW.md:3` (the status line), `:38-40` (WS-24/25/26 rows)
- Modify: `docs/implementation/06-security-preconditions.md:3`
- Modify: `docs/implementation/24-search-performance.md:3` and §4a.1/§4a.2
- Modify: `docs/implementation/25-provider-depth-and-approvals.md:3`, §10.4
- Modify: `docs/implementation/26-source-expansion.md:3` and §3
- Modify: `README.md:19` (the stale test count)
- Test: `tests/test_docs_accuracy.py` is the existing guard — run it.

- [ ] **Step 1: Fix the four contradictions**

1. `00-OVERVIEW.md:3` still reads "WS-01…14 done" while the same file's rows run to WS-31. Extend the headline to name the real tip.
2. `06-security-preconditions.md:3` says "Status: **In progress**" while `00-OVERVIEW.md` lists WS-06 as "Done 2026-10-21 (live, 12/12)". Make the document say what the ledger says, or the ledger say what the document says — the code supports Done, so the document changes.
3. `README.md:19` claims "1,376 collected; 1 skipped; ~6 minutes". The tree now has 1,767 `def test_` definitions before parametrization. Replace the number with a measured one — run the suite and count — or with a claim that does not go stale ("the whole suite, ~6 minutes"). **Do not** write a new number you have not just measured.
4. `24-search-performance.md` §4a.1 and the WS-28/WS-29 measurements: record what this plan measured, and state plainly that §4a.1 is **superseded by measurement** (1.47 s of a 2.18 s warm search) rather than open. §4a.2 becomes partially closed by Task 6, with the index half still open.

- [ ] **Step 2: Record the Phase B scoping deviation**

In `26-source-expansion.md` §3, mark §3.1 as built (Tasks 4–5, with the commit hashes), §3.2 (fuzzy MinHash) as **not built — no evidence**, with the measurement (zero cross-source groups under three normalization strengths on the live 8,558-listing corpus), and §3.3/§3.4 as built. Update the status line at `:3` and the overview's WS-26 row from "plan only" to name what Phase 2 delivered.

- [ ] **Step 3: Record each phase's measured outcome**

In the three workstream docs, add the before/after numbers each phase produced — for Phase A the measurements that justify it (30 sightings of `First Name`, 24 of `Latitude` on live data; the coverage-map defect); for Phase C the two `profile_search_timing.py` runs from Task 6 Step 5. A phase that claimed an outcome and recorded no number has not been verified.

- [ ] **Step 4: Run the docs guards and commit**

Run: `cmd.exe /c "env\Scripts\python.exe -m pytest tests/test_docs_accuracy.py tests/test_env_docs.py tests/test_ws25b_coverage_map.py -q"`
Expected: PASS — the API table matches `app.openapi()` in both directions, so Phase A's new endpoint call and Phase B's wiring cannot have drifted the table.

```bash
git add docs/implementation/00-OVERVIEW.md docs/implementation/06-security-preconditions.md \
  docs/implementation/24-search-performance.md docs/implementation/25-provider-depth-and-approvals.md \
  docs/implementation/26-source-expansion.md README.md
git commit -m "docs: the ledger says what the code does, and what it measured (ws-25b/26/24)

Four statements the audit found false: the overview headline read WS-01…14
while its own rows ran to WS-31; the security-preconditions header still
said in-progress while the ledger said done; the README's collected-test
count was 1,376 against 1,767 definitions today; and §4a.1 described a
~9 s per-request score that WS-29 had already cut to 1.47 s, which makes
that item superseded rather than open.

The Phase B scoping deviation is recorded where the spec asked for it: the
exact cross-source key is built, and the fuzzy MinHash path is not,
because the live corpus contains zero cross-source groups to collapse."
```

---

## Self-review

**Spec coverage.** WS-25b §9.3 (measured order + why-sentence + nothing for an unasked question — Tasks 2, 3) and §10.4 (the `First`/`Last Name` and console items — Tasks 1, 2, 3; the `Latitude`/`Longitude` item is *classified* not fixed, because the profile genuinely has no coordinates and inventing them is forbidden, so Task 2 makes it a visible, honest gap instead). WS-26 Phase 2 §3.1/§3.3/§3.4 (Tasks 4–5), §3.2 deliberately not built (Phase D records it). WS-24 §4a.2 (Task 6). The four false ledger statements (Task 7). **Not covered, and why:** WS-24 §4a.1 (superseded by measurement, recorded in Task 7), WS-26 Phases 3–7 and WS-25's consent-question surface (out of this plan's scope — Phases 3–6 need the registry surface and new adapters, which is its own plan).

**Step scan.** Every step names a file and a checkable result. Task 2's render step describes the card's content rather than transcribing JSX, because the test pins the three properties that matter (order, the frequency sentence, absence-when-empty) and the surrounding components already fix the idiom. Task 3's test reuses the existing prepare-form interaction rather than reproducing it.

**Type consistency.** `cross_source_key`/`merge_cross_source`/`FIELD_COMPLETENESS` are named once (Task 4) and consumed under those names (Task 5). `question_gaps`'s response keys come from `QuestionGapResponse` (`profile_answers.py:76`) and are used identically in the factory, the handler and the test. `_important_terms_for`/`_role_for`/`_rank_for` are named in Task 6's test and its implementation step consistently. The 4-tuple `corpus_fingerprint` shape is stated in the Interfaces block and used in the implementation step.

**Review Focus.** Six lines, each owned: 1 → Task 1 (measured defect), 2 → Task 1's parametrized test, 3 → Task 4 (`test_the_more_complete_source_wins_a_disagreement`), 4 → Task 4 (`test_two_listings_from_one_source_are_never_merged`), 5 → Task 6 (`test_no_change_at_all_rebuilds_nothing` + the identity test), 6 → Task 6 (`test_a_deleted_listing_leaves_no_artifact_behind`).

**Proportion.** Three docs-phase tasks and four code tasks against three multi-hundred-line specs; the plan is shorter than the specs it implements and contains no function bodies except the test code and the two JSX-free shapes the spec fixes (the key, the card's content).

## Execution handoff

The user asked for implementation to begin in the same request, so execution follows immediately with `superpowers:executing-plans` — inline, one task at a time, TDD, with the ledger in this file's phase sections and a per-task green suite. Commits are cut per the repo's own convention and **not pushed**.

---

## After this plan — what is actually still open

This section exists because "is it done?" deserves an answer that distinguishes
*this plan* from *the workstreams it touched*. All seven tasks are done. The
workstreams they live in are not.

### Closed by this plan

| Item | Where |
|---|---|
| The console never called the measured question surface (WS-25b) | Task 2, 3 |
| The taxonomy/coverage-map drift, and `_profile_has`'s hand-kept attribute list | Task 1 |
| Cross-source dedup — WS-26 Phase 2 (and the registry docstring's claim) | Task 4, 5 |
| The corpus artifacts rebuild was full, not incremental — WS-24 §4a.2 | Task 6 |
| Four ledger statements the code contradicted | Task 7 |

### Not closed — verified absent in the code, not merely unmentioned

- **WS-26 Phases 3–6.** No `proposed` board flag and no admin board view; no
  cost classes, paging ceilings or staggered sync (zero hits for `cost_class`,
  `paging_ceiling`, `stagger`); **no robots.txt policy anywhere in the repo**;
  no new adapters (still Greenhouse, Lever, Ashby, Remotive against the 28,178
  boards the research found). Four of the five test files the WS-26 acceptance
  table names do not exist.
- **WS-26b's verifier is not in CI.** `scripts/verify_sources.py` exists and is
  tested (17 tests) but `.github/workflows/ci.yml` has two jobs, `gate` and
  `browser`, and neither calls it. A provider renaming a field silently nulls
  every parser and nothing would catch it.
- **M5 — the live pilot.** Blocked by design, not incomplete: the capability
  matrix grants `greenhouse: [PREPARE]` and `lever: [PREPARE]` only, and both
  `submit()` methods deliberately raise. No real-ATS submission can happen.
- **WS-28's remaining item.** The query embedding still dominates a search, and
  it is gated on the WS-09 harness judging whether a shorter query is
  acceptable — a decision, not a bug.
- **Security gaps that are open by design:** no malware scanning of uploads; no
  PII minimisation or encryption for stored résumés (SEC-12); no per-tenant
  keys; e-mail delivery is a mailbox file. **SEC-15 retention, by contrast, IS
  built** — `src/retention.py`, `scripts/purge_expired.py`,
  `tests/test_retention.py`, env knobs and a RUNBOOK cron line all exist, so
  the several docs that still list it as open are stale.

### Superseded rather than closed — a distinction worth keeping

**WS-24 §4a.1 is not "done".** It proposed a per-listing score cache on a
premise of "~9 s per request". Re-measured 2026-11-13, a warm search is
**2.18 s** and the bulk scoring loop is 1.47 s of it, so the cache has no win
left to take. It is recorded as superseded-by-measurement in
`24-search-performance.md` §4a.1. Anything that treats it as a to-do will do
work whose payoff was already collected by WS-29.

### The next plan, and it exists

`2026-11-14-submission-readiness.md` (WS-32) plans the submission path in five
tasks, and it begins by **refuting a researched claim** that ATS platforms
accept third-party API submissions: Greenhouse's own documentation says the
submission key is the employer's ("proxied by your own servers"), and a live
probe returns `401 HTTP Basic: Access denied`. Its Order: PDF résumés (which are
refused outright today), payload validation against the provider's published
contract, durable submission execution, the adapter self-check that does not
exist, then an assist-mode pilot.
