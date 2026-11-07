# WS-20 · Matching accuracy, BM25 lexical relevance & the candidate application profile

Status: **Done (2026-11-07)** · Milestone: **M5** · Depends on: WS-03 (matching engine), WS-04 (profile persistence + search API), WS-09 (evaluation harness), WS-13 (console), WS-18 (durable embedding queue)

> The hybrid matcher scored *unknown* information as a neutral **70** and let a
> missing embedding **redistribute its own weight** onto the other components —
> so a listing with no vector, or a candidate with no dated experience, could
> outrank a fully-evidenced one. Skill matching read only the structured
> `required_skills`/`preferred_skills` lists, so a requirement buried in the
> description was invisible. And the profile was the résumé: visa status,
> salary expectation, notice period and EEO selections had nowhere to live.
>
> This workstream makes unknown information *unknown* (never a positive score),
> fixes the weighting denominator, adds BM25 lexical retrieval over the whole
> posting, and introduces a user-confirmed **application profile** separate
> from the résumé facts — with work authorization, sponsorship and citizenship
> as three distinct questions and EEO data isolated from matching entirely.

---

## 1. Repository audit (2026-11-07)

`git status` is clean; `main` is level with `origin/main` (0 unpushed). The new
workstream takes the next free identifier after WS-19.

### 1.1 The matching data flow, as it exists

`POST /api/jobs/search` (`src/api/routes/jobs.py:223`) loads the stored profile
and calls `search_stored_jobs()` (`src/graph/job_executor.py:682`):

1. read up to `max_corpus_listings` rows from `jobs` (`:726`), map each to a
   `JobListing`;
2. optional client-side `query`/`location` narrowing (`:735`);
3. `store = _get_store(...)`; `similarities = store.similarities_for_all(
   candidate_query_text(profile))` (`:762`) — one query embedding, cosine for
   **every** stored vector;
4. `calculate_match(job, profile, semantic_score=similarities.get(job.id))` for
   each job, sorted by `overall_score` (`:777`);
5. the top-N `JobMatchPair`s are persisted as `job_matches` rows and returned.

`candidate_query_text` (`src/rag/chroma_store.py:416`) uses only the title,
the first **20** skills, and the first **300** chars of the summary. The
embedded document (`document_text`, `:154`) is required/preferred skills plus
the first 8,000 chars of the description.

### 1.2 The scorer, as it exists (`src/matching/engine.py`)

Six components, blended by `MATCH_WEIGHTS` (`weights.py:10`):

| Component | Source | Missing behaviour |
|---|---|---|
| semantic | caller-supplied cosine | `None` → `redistribute_without(…, "semantic")` |
| skill | `required_skills`/`preferred_skills` vs `profile.skills` | no lists → **70** |
| experience | `experience_score` | either side unknown → **70** |
| seniority | rank from title strings | either side unknown → **70** |
| location | remote policy / preferred cities | unstated prefs → **70** |
| preference | employment type + salary floor | no signals → **70** |

`NEUTRAL_SCORE = 70.0` is used in six places; `redistribute_without`
(`weights.py:57`) rescales the remaining five weights to sum to 1 whenever the
semantic value is `None` (`engine.py:187`).

### 1.3 Root causes of the ranking defects

1. **Unknown ≠ neutral.** Six code paths return `NEUTRAL_SCORE` for *absence* of
   data. A candidate with no dated experience and a candidate who meets the
   requirement both approach 70; a job with no skills listed is hard-coded to
   70 (`engine.py:100`). The result hides whether a score is *earned* or
   *defaulted*.
2. **Weight redistribution favours the unembedded.** When a listing has no
   vector, `redistribute_without` moves the semantic weight onto the five
   components the listing *does* have — so the missing component is not paid
   for, and a pending job can outscore a fully indexed one (`engine.py:186`).
3. **Overlapping employment double-counts.** `years_of_experience`
   (`experience.py:41`) sums `max(end) - min(start)` **per entry**, so two
   concurrent roles count twice.
4. **The requirement is read off the first line only.** `required_years`
   (`experience.py:58`) falls back to `description.splitlines()[0]`, so
   "5+ years" on line 3 is invisible; and `_REQUIRED_YEARS_RE` returns the
   *second* number of "3-5 years" via `findall`-free `search` semantics that
   land on the last match in the string.
5. **Skill matching is list-only.** A description that demands Kubernetes but
   does not tag it is scored as if Kubernetes were not required.
6. **No evidence coverage.** A 71 built from one measured component and five
   defaults is indistinguishable from a 71 built from six.
7. **Candidate seniority uses `experience[0]` blindly** (`engine.py:106`).
8. **Query text is thin** (`chroma_store.py:416`): 20 skills, 300 chars.

### 1.4 Embedding-status handling, as it exists

`search_stored_jobs` infers "pending" purely from *absence in the similarity
map* (`job_executor.py:763`) and reports a single boolean `degraded`. WS-18
already stores the durable answer: `job_work_items` rows with
`work_type='embed'`, `job_id` (indexed), a `status` in
{QUEUED, RUNNING, RETRY_WAIT, COMPLETED, FAILED, CANCELLED}
(`src/db/runs.py:118`, `src/runs/state.py:171`) and a `content_hash`
(`src/db/runs.py:132`). **No helper maps a listing id to its embedding
status**; the only corpus-wide read is a status census (`queue.py:1152`).

### 1.5 Profile and application-question models, as they exist

- `CandidateProfile` (`src/resume/profile.py:73`) holds **resume facts** only;
  `WorkPreferences` (`:47`) carries `remote_preference`, `preferred_locations`,
  `min_salary`, `work_authorization`, `employment_types` — all **verbatim
  strings the résumé happened to state**, never user-confirmed.
- Persistence is `CandidateProfileDB.profile_json` (`src/db/profiles.py:44`).
- The form layer (`src/applications/form.py`) has a flat `FIELD_MAP`
  (`:145`) label→fact map and `FACT_SOURCES` (`:186`); answers come **only**
  from `facts_from_profile` (`:283`). There is **no** question taxonomy, no
  answer bank, no EEO handling, no notice period, no separate expected vs
  current salary, and `answer_question` (`:378`) has no provenance tracking.
- `SubmissionPolicy.AUTO_SUBMIT` exists but is unreachable
  (`policy.py:63`, `applications.py:257`); the approval gate is mandatory.

### 1.6 API / UI capabilities, as they exist

- Profiles: `POST /api/resumes`, `GET /api/resumes/{id}` — read-only.
- Matches render the six component scores in `score-grid.tsx`
  (`frontend/src/components/common/score-grid.tsx:12`), typed from the
  generated `schema.ts` (`JobMatchResult`, `schema.ts:1863`).
- The profile screen **displays** work preferences but has no editing UI
  (`profile-view.tsx:221`).

### 1.7 Evaluation harness, as it exists

Pure metrics in `src/evaluation/metrics.py` (nDCG@k `:155`, precision@k `:169`,
recall@k `:285`, matching FPR/FNR `:327`); golden dataset under
`tests/evaluation/golden/`; offline runner `scripts/run_eval.py`
(lexical semantic stand-in, canned drafts). `run_profile`
(`harness.py:190`) already measures a **degraded** ranking — the measurement
hook for this workstream's before/after.

### 1.8 What is already implemented / defective / new

- **Already correct, keep:** the six real scorers, `validate_weights`,
  deterministic behaviour, the `job_matches` persistence, the approval gate,
  the WS-18 queue (this workstream **reads** it, never duplicates it).
- **Defective, fix:** the neutral-70 defaults, the weight redistribution,
  overlap double-counting, first-line-only requirements, `experience[0]`
  seniority, thin query text, per-component score blindness.
- **New:** score states + evidence coverage, BM25 lexical component + keyword
  matching, embedding-status awareness, the application profile, the question
  taxonomy, EEO isolation, preferences/answers API + UI, extended evaluation.

### 1.9 Backwards-compatibility constraints

- Older `profile_json` must still validate → new profile sections are
  **optional with empty defaults** and live in a **new nullable column**, not
  inside `profile_json`.
- `JobMatchResult` gains fields but keeps every existing one (the frontend
  reads them; `DeepRequired` tolerates additions only if the schema is
  regenerated — it is).
- `MATCH_WEIGHTS` gains a seventh component; `validate_weights` now requires
  the full set. Documented as a breaking config change with the new default.
- The existing degradeded/`degraded` report flag stays for API compatibility.

---

## 2. Design

### 2.1 Score states and the fixed denominator (Part 1)

New module `src/matching/scores.py` defines

```python
class ScoreState(StrEnum):
    MATCHED; PARTIAL_MATCH; MISMATCH
    CANDIDATE_DATA_MISSING; JOB_REQUIREMENT_MISSING
    EMBEDDING_PENDING; EMBEDDING_UNAVAILABLE
    NOT_APPLICABLE

class ComponentScore(BaseModel):
    name; value: float(0..100); state: ScoreState; reason: str
    matched: list[str]; missing: list[str]
```

**Policy (documented, single rule):**

- A component with a *measured* value contributes `weight * value`.
- A component that is **unknown** — candidate data missing, job requirement
  missing, embedding pending or unavailable — contributes **zero to the
  numerator and keeps its full weight in the denominator**. Its `state` says
  *why*, and its `reason` is written into the explanation. Unknown is never
  presented as a match.
- A genuinely **`NOT_APPLICABLE`** component (the concept does not apply to
  this pair) is removed from **both** numerator and denominator, and reported
  in the coverage so the exclusion is visible.
- **Coverage** = `Σ weight(evidence states) / Σ weight(counted states)` as a
  0–100 percentage, exposed on `JobMatchResult.evidence_coverage` alongside
  the overall score. A score is always readable with its coverage.
- `redistribute_without` is **deleted** from the search path (kept for nothing).

`overall = Σ wᵢvᵢ / Σ wᵢ` over counted components — the denominator is the
configured weight set, never a function of which components happened to be
available.

### 2.2 Experience and seniority (Part 1.3)

- `years_of_experience` **unions** all dated ranges across entries (overlap
  counted once), still ignoring education/projects and still `None` when
  undated.
- `required_years` scans the **whole** description (and
  `experience_requirements`), understands `3+`, `3-5`, `at least 4`, `minimum
  of 3`, `4 or more`, and treats a "years … in/with <tech>" mention as
  **technology-specific** (reported, not used as the total bar).
- Candidate seniority is resolved from the **most recent dated entry**, falling
  back to the highest-ranked title, and may be **supplemented** by an explicit
  `application_profile.professional.seniority_level`.
- Candidate total years may be **supplemented** by an explicit
  `application_profile.professional.total_experience_years` when the résumé
  has none.
- The rank ladder gains a leading `principal`/`distinguished` tier and
  `associate`, all word-boundary matched.

### 2.3 BM25 lexical retrieval (Part 2)

New module `src/matching/lexical.py` — a **dependency-free** Okapi BM25 (no
`rank-bm25`; the corpus is small and the formula is ~30 lines):

- `Bm25Index(listings)` builds one index per search: field-weighted documents
  (title ×3, `required_skills` ×3, `preferred_skills` ×2, experience/education
  requirements ×2, description ×1), with `k1=1.5`, `b=0.75`; `avgdl` and IDF
  from the corpus (deterministic).
- Tokenizer: word characters, lowercased, `#`/`+`/`.` kept so `c++`, `c#`,
  `node.js` survive; **tokens shorter than 2 chars are dropped** so `C` never
  matches an unrelated word; `java` and `javascript` are distinct tokens.
- **Normalization without per-query min-max:** `100 · raw / (raw + K)` with
  `K = BM25_HALF_SATURATION = 6.0` — monotonic, absolute, stable across
  searches.
- **Keyword coverage** alongside BM25: important terms = title tokens +
  required-skill phrases + salient description tokens (stop-words removed);
  matched/missing lists are reported. Mandatory (required-skill / title) terms
  weigh more than preferred ones. **Structured skill lists are excluded from
  the coverage numerator** so the lexical channel does not double-count what
  the `skill` component already measures; they *remain* in the BM25 corpus
  (they help retrieval).
- Aliases: a small curated map (`js↔javascript`, `k8s↔kubernetes`,
  `postgres↔postgresql`, `golang↔go`, …).
- The lexical component blends BM25 (0.6) and keyword coverage (0.4) into a
  0–100 value; its state follows the same measured/unknown rule.

`candidate_query_text` (`chroma_store.py`) is widened (title, summary, skills,
experience titles + bullets, project tech + names, education, certifications —
no contact identifiers) for the **semantic** channel, and `lexical.py` builds
the **lexical** query from the same professional text.

Weights become seven components, calibrated on the WS-09 harness:

| component | semantic | lexical | skill | experience | seniority | location | preference |
|---|---|---|---|---|---|---|---|
| weight | 0.15 | 0.10 | 0.25 | 0.20 | 0.10 | 0.10 | 0.10 |

### 2.4 Unembedded jobs (Part 3)

New `src/matching/embedding_status.py`:

```python
def embedding_status_for_jobs(job_ids, *, session_factory) -> dict[str,str]
```

— one indexed query over `job_work_items` (`work_type='embed'`), returning the
latest status per job id. `search_stored_jobs` uses it to give each
vector-less listing a **honest semantic state**:

- store is `None` (whole-store outage) → `EMBEDDING_UNAVAILABLE`;
- store is up but the listing has no vector → `EMBEDDING_PENDING` (a
  QUEUED/RUNNING/RETRY_WAIT/FAILED item, or simply no vector yet);
- a measured similarity, **including a measured `0.0`**, stays a measurement.

A pending listing **remains visible** (no silent dropping) but receives
**zero semantic credit** — it can no longer gain from redistribution because
there is no redistribution. Sorting is `(overall desc, job.id)` for stable,
deterministic ties. `degraded` is retained; a new `semantic_coverage` count is
added to the report. An optional `only_embedded` search flag filters to fully
indexed listings, default **off** and documented as a trade-off.

### 2.5 Application profile and question taxonomy (Part 4)

New module `src/resume/application_profile.py`: `ApplicationProfile` with
three separated groups —

- **ProfessionalInfo**: total years, seniority level, per-skill years, current
  title, portfolio/LinkedIn URLs;
- **JobSearchPreferences**: preferred locations, remote/hybrid/onsite,
  employment types, relocation;
- **ApplicationAnswers**: `WorkAuthorizationInfo` (three **distinct** fields:
  `legally_authorized`, `requires_sponsorship`, `citizenship_status`),
  `Compensation` (expected **and** current, each with currency + period),
  `NoticePeriod` (`notice_days` incl. `0`, `available_from`).

Stored in a **new nullable `application_json` column** on `candidate_profiles`
— logically separate from the résumé's `profile_json`, so resume-derived and
user-confirmed values stay distinguishable. A `confirmed_fields` list records
which fields the user explicitly confirmed (provenance). EEO lives in a
**separate `candidate_eeo` table** and is never serialized into `profile_json`,
never returned by the profile read, and never read by the matcher.

New module `src/applications/questions.py`: a deterministic
`QuestionCategory` taxonomy with regex/alias rules and **explicit precedence**
(`VISA_SPONSORSHIP` → `WORK_AUTHORIZATION` → `CITIZENSHIP_STATUS`;
`CURRENT_SALARY` → `DESIRED_SALARY`), an `answer_type`, an EEO group that is
never auto-answered, and an `ATTESTATION` group that is never auto-ticked. Low
confidence → manual review. `form.py` consults the taxonomy after `FIELD_MAP`
and tracks answer **provenance** (`user_confirmed` / `resume_derived` /
`derived`).

### 2.6 API, migration, frontend (Part 5)

- `GET`/`PUT /api/profiles/{id}/application-profile` — owner-scoped,
  validated, input-bounded.
- `GET`/`PUT`/`DELETE /api/profiles/{id}/eeo` — owner-scoped, isolated.
- One Alembic migration adds `candidate_profiles.application_json` (nullable)
  and the `candidate_eeo` table; portable JSON/String columns, reversible.
- Frontend: a profile **edit** panel for preferences + application answers,
  showing which fields are still missing; EEO is a separate, clearly optional
  card.

### 2.7 Evaluation (Part 6)

Extend the harness with `evidence_coverage` per profile, before/after ranking
metrics, and a small labelled benchmark of the required cases (strong/partial
matches, buried requirements, missing metadata, missing embeddings, incomplete
résumés). Record baseline vs new in `docs/evaluations/`.

---

## 3. Concrete task list

| # | Area | Files |
|---|---|---|
| 1 | Score states + fixed denominator + coverage | `src/matching/scores.py` (new), `engine.py`, `contracts.py`, `weights.py` |
| 2 | Experience/seniority fixes | `src/matching/experience.py`, `engine.py` |
| 3 | BM25 + keyword matching | `src/matching/lexical.py` (new), `chroma_store.py` |
| 4 | Embedding status | `src/matching/embedding_status.py` (new), `graph/job_executor.py` |
| 5 | Application profile models | `src/resume/application_profile.py` (new), `profile.py` |
| 6 | EEO model + table | `src/resume/eeo.py` (new), `src/db/eeo.py` (new) |
| 7 | Question taxonomy + form integration | `src/applications/questions.py` (new), `form.py` |
| 8 | Profile/answers API | `src/api/routes/resumes.py`, `src/db/profiles.py`, `src/db/access.py` |
| 9 | Migration | `migrations/versions/<rev>_ws20_application_profile.py` |
| 10 | Match persistence | `src/db/matches.py` |
| 11 | Frontend | `frontend/src/screens/*`, `lib/api/*` |
| 12 | Tests | `tests/test_score_states.py`, `test_lexical_bm25.py`, `test_embedding_status.py`, `test_question_taxonomy.py`, `test_application_profile.py`, `test_eeo.py`, extend `test_matching.py` |
| 13 | Evaluation | `src/evaluation/harness.py`, `metrics.py`, `tests/evaluation/golden/` |
| 14 | Docs | this file, `00-OVERVIEW.md`, `README.md` |

## 4. Acceptance criteria

1. Missing candidate data no longer receives an artificial 70% match.
2. Unembedded jobs get no semantic-weight redistribution.
3. Component weights and the denominator behave consistently (no silent change).
4. BM25 evaluates the whole posting, not just the structured lists.
5. Explanations show matched / missing / **unknown** evidence and coverage.
6. Preferences and application answers are explicitly supplyable.
7. Work authorization and sponsorship are separate, correctly classified.
8. Salary, experience and notice-period answers carry proper semantics.
9. EEO is optional, explicit, isolated, never used for ranking.
10. Unknown or legally significant questions go to human review.
11. Existing profiles remain compatible.
12. WS-18 queue/worker/recovery remains intact.
13. Evaluation shows measured before/after.

## 5. Tests

New: `test_score_states.py`, `test_lexical_bm25.py`, `test_embedding_status.py`,
`test_question_taxonomy.py`, `test_application_profile.py`, `test_eeo.py`.
Updated: `test_matching.py` (new policy), `test_eval_*` (coverage metric),
`test_migrations.py` (new revision). Plus the full suite, `ruff`, frontend
`vitest`, and the production build.

## 6. New dependencies

**None.** BM25 is implemented in-repo (deterministic, ~30 lines) rather than
adding `rank-bm25`; the corpus is small and the formula is transparent.

---

## 7. Delivery report

### Files changed

**New**
- `src/matching/scores.py` — `ScoreState`, `ComponentScore`, the fixed-denominator blend, evidence coverage.
- `src/matching/lexical.py` — dependency-free BM25, field-weighted, keyword/phrase matching, the candidate lexical query.
- `src/matching/embedding_status.py` — reads the WS-18 work queue for per-listing embedding status.
- `src/resume/application_profile.py` — the user-confirmed application profile models.
- `src/resume/eeo.py` — the isolated EEO model.
- `src/db/eeo.py` — the `candidate_eeo` table.
- `src/applications/questions.py` — the question taxonomy and value transforms.
- `src/api/routes/profile_answers.py` — the application-profile and EEO routes.
- `migrations/versions/f1e2d3c4b5a6_ws20_application_profile.py`.
- `frontend/src/components/profile/application-profile-panel.tsx`.
- Tests: `tests/test_score_states.py`, `test_lexical_bm25.py`, `test_embedding_status.py`, `test_question_taxonomy.py`, `test_application_profile.py`, `test_eeo.py`; `frontend/src/components/common/score-grid.test.tsx`.
- Docs: this file, `docs/evaluations/report-2026-11-07.*`, `docs/evaluations/ws20-comparison.md`.

**Changed**
- `src/matching/engine.py` — seven components, score states, fixed denominator, honest explanation.
- `src/matching/experience.py` — whole-description requirement parsing, overlap union, tech-vs-total, confirmed-years supplement.
- `src/matching/weights.py` — the `lexical` component; `redistribute_without` deleted.
- `src/matching/contracts.py` — the result gains `lexical_score`, `evidence_coverage`, `component_states`, `notes`, keyword lists.
- `src/graph/job_executor.py` — `search_stored_jobs` builds the BM25 index, consults the queue, gives honest semantic states, stable tie-break, `only_embedded`, `semantic_coverage`.
- `src/rag/chroma_store.py` — the widened `candidate_query_text`.
- `src/resume/profile.py` — `application_profile` on `CandidateProfile`.
- `src/applications/form.py` — taxonomy integration, application-profile facts, answer provenance.
- `src/db/profiles.py`, `src/db/access.py`, `src/db/matches.py`, `src/security/audit.py`, `src/main.py`, `src/api/routes/jobs.py`, `tests/conftest.py`, `migrations/env.py`, `README.md`, `docs/implementation/00-OVERVIEW.md`.
- `frontend/src/lib/api/{schema.ts,types.ts,endpoints.ts}`, `src/components/common/score-grid.tsx`, `src/screens/{resume-screen,job-detail-screen,matches-screen}.tsx`, `src/test/factories.ts`.

### Database migration

One additive, reversible revision `f1e2d3c4b5a6` (down from `a7b8c9d0e1f2`):
`candidate_profiles.application_json` (nullable JSON) and the `candidate_eeo`
table. The user's database was **not** recreated; existing rows validate.

### API and frontend

- `GET`/`PUT /api/profiles/{id}/application-profile`
- `GET`/`PUT`/`DELETE /api/profiles/{id}/eeo`
- `POST /api/jobs/search` gains `only_embedded` and returns `semantic_coverage`.
- The console's résumé screen gains the application-answers editor and the
  optional EEO card; the score breakdown shows the keyword component, unknown
  states in words, and evidence coverage.

### Tests executed

- Python: **1434 passed, 1 skipped** (`-m "not browser"`), ruff clean.
- Frontend: **147 + 2 Vitest**, eslint clean, `tsc -b` clean, production build
  succeeds.
- Evaluation: `scripts/run_eval.py --check` — all metrics within thresholds.
- Migrations: upgrade to head and downgrade to base, on SQLite, reversible.

### Before/after metrics

See `docs/evaluations/ws20-comparison.md`. Ranking order is stable (nDCG
0.7537 → 0.7537); degraded ranking is now *lower* (semantic weight is no longer
redistributed); false-negative rate improved (0.7722 → 0.6111) after the
decision threshold was recalibrated from the removed neutral 70 to 30; average
evidence coverage is 52.5%.

### Remaining limitations

- BM25's saturation constant and the seven weights are calibrated by inspection
  against the small golden set, not fitted on a large labelled corpus.
- `evidence_coverage` is reported but not yet gated in CI.
- EEO storage isolation is at the row/route/table level; column-level
  encryption at rest remains the WS-14 NFR-S13 work, not this workstream.
- No live (`--live`) run was performed for this workstream; the offline
  metrics are the reproducible baseline.