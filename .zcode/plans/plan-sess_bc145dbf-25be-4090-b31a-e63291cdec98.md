# WS-24c — the per-listing residual, and a skeleton instead of a clock

## What I verified (and the three things the original list missed)

Confirmed exactly as described: `_seniority_component` (`engine.py:308-324`) calls `_seniority_rank` per listing and `_candidate_rank(profile)` per listing; `_effective_preferences` (`engine.py:93-143`) is called from both `_location_component:328` and `_preference_component:393`, each doing a `WorkPreferences.model_copy(deep=True)`; `lexical_score` builds full matched/missing lists then truncates at `lexical.py:518-519`.

Three findings that change the ordering:

1. **The 0.88 s of `deepcopy` is mostly fix #2, not #3.** 17,116 `model_copy(deep=True)` calls per search (8,558 listings × 2) recursively copy the whole preferences model — that accounts for nearly all of the ~205 k `deepcopy` calls. Fixing `_effective_preferences` alone removes most of that cost, so the pydantic refactor is worth less than the 1.4 s projected.

2. **Caching the job-side seniority rank in the artifacts is silently incorrect without a fingerprint fix.** `content_version_for` (`src/db/jobs.py:135-142`) hashes title, description, skills, and requirement strings — **not `seniority`**. `_seniority_rank` reads `job.seniority` first (`engine.py:309`). A refresh that changed only `seniority` would keep the same fingerprint and serve a stale cached rank. Every other artifact's inputs *are* covered; `seniority` is the one gap, and only because this change makes it an artifact. So: add `seniority` to `content_version_for`, and seed the fingerprint digest with an artifact-schema constant so future artifact additions force exactly one rebuild.

3. **Two more per-listing costs nobody listed:** `validate_weights` runs 8,558× per search (`engine.py:609-613` — the executor never passes weights); and `years_of_experience(profile)` runs **twice** per listing (`engine.py:263` and again inside `experience_score`, `experience.py:222`), each a full regex union over every dated entry. Also `logger.info` fires per listing at `engine.py:711` — 8,558 log records per search through the PII-masking filter at INFO, which is both cost and noise.

And one honest measurement problem: `scripts/profile_search_timing.py` does **not** pass `context` or `artifacts` to `calculate_match`, so it profiles a slower path than `search_stored_jobs` actually takes. Its numbers can't be the baseline until it's corrected.

## The privacy question — resolved rather than waived

I'm not relaxing WS-14 Phase G. Read the rule's own reasoning (`src/llm/embeddings.py:671-689`): both named harms are properties of a **shared, persistent** cache — (a) a hit on identical text tells a second tenant that someone else submitted the same text, and (b) the vector sits on disk where it can be inverted. An in-process memo **keyed by the profile id** is neither shared nor persistent: two tenants can never collide because the key is per-tenant, and nothing is written to disk or logged. That is a distinction the rule anticipated, not a violation of it. I'll implement the memo and **rewrite both `embed_query` docstrings** to record the distinction explicitly, so a future reader doesn't "restore" the old absolute rule or over-extend the new exception.

## Phases

### Phase 0 — A baseline that is the real path
- Update `scripts/profile_search_timing.py` to use `get_corpus_artifacts` + `CandidateContext` + `score_all`, matching `search_stored_jobs`, and to report per-phase times.
- Record warm/cold at 8,558 in the doc. (Your 13.25 s and the doc's 8.41 s differ; re-measure rather than assume.)

### Phase A — Per-search constants hoisted (exact, lowest risk)
All of these are pure functions of the profile, computed once per search instead of per listing:
- Extend `CandidateContext` (`engine.py:506-562`) with: `effective_preferences` (kills both `model_copy` calls and all the derived list builds), `candidate_rank`, `years_of_experience`, `lowered_preferred_locations`, `normalized_employment_types`, `parsed_min_salary`.
- Component builders gain keyword-only parameters with `_UNCACHED` defaults, mirroring `_skill_component`'s existing `context=` pattern and `_experience_component`'s `requirement=` pattern — so every current call site (including `tests/test_preferences_merge.py`'s eight direct `_effective_preferences` calls and `tests/test_ws23_corpus.py`'s two `_location_component` calls) keeps working unchanged.
- Resolve `validate_weights` once in `search_stored_jobs` and pass it down; `calculate_match` keeps its fallback for its other 64 call sites.
- `logger.info` → `logger.debug` for the per-listing match log.

### Phase B — Job-side rank into the artifacts (exact, needs the fingerprint fix)
- Add `seniority` to `content_version_for`; seed `corpus_fingerprint`'s digest with an `_ARTIFACTS_VERSION` constant (one-time rebuild, documented — no backfill needed, since only `merge_jobs` writes rows).
- `seniority_ranks: dict[str, int | None]` on `CorpusArtifacts`, populated at build (`corpus_cache.py:174-198`), read with the `_UNCACHED` sentinel exactly as `required_years` is.
- `_seniority_rank`: keep the ladder and the word-boundary regex as the **arbiter**, but pre-filter with `keyword in lowered` so 19 regex scans per title become 19 substring checks that only escalate to a regex on a hit. This preserves semantics *exactly* — unlike a combined alternation regex, which would change which keyword wins unless carefully priority-ranked. I prefer exact-by-construction over a rewrite that needs an equivalence proof.

### Phase C — The per-listing result object
- Truncate matched/missing keyword lists during the loop (keep the first 25 while still accumulating `matched_weight` over all terms), so coverage is unchanged and only the lists stop growing.
- Replace the 8 intermediate `ComponentScore` constructions with a slots-based internal carrier that exposes the same `counted`/`is_evidence` properties, so `blend()` stays duck-typed and `tests/test_score_states.py` keeps passing. Pydantic is built only where a model actually crosses a boundary (`JobMatchResult`).
- **Explicitly out of scope, noted in the doc:** the deeper win — 8,508 of 8,558 `JobMatchResult` objects (with their explanation strings) are built and discarded because only `top_n` survives ranking. A two-phase score-then-materialize refactor would beat everything above, but it changes `calculate_match`'s contract across 65 call sites and the eval harness. That is its own workstream, not a phase here.

### Phase D — Repeat-search memo (decided, as above)
- A bounded in-process memo, keyed by `(profile_id, profile_digest)` for the query vector and `(profile_digest, corpus_fingerprint)` for the similarity map. LRU-bounded to a handful of entries, invalidated when the profile digest changes, never persisted, never logged.
- Tests: no cross-profile reuse, profile edit invalidates, nothing reaches disk.

### Phase E — Skeleton loading on Matches
- New `frontend/src/components/ui/skeleton.tsx` (`bg-muted` + `animate-pulse`; both already available — `tw-animate-css` is imported, and the token exists in light and dark). No new dependency.
- New `frontend/src/components/common/match-list-skeleton.tsx` whose bones mirror `MatchCard` (`matches-screen.tsx:109-184`): title line, meta line, score chip, disclosure row.
- In `matches-screen.tsx`, the skeleton **takes precedence** over stale results, so a re-search shows one clear signal instead of a skeleton above the previous ranking. `ProgressState` and `useElapsed` stay untouched — the other nine screens keep their elapsed counter, so the blast radius is this one call site.
- Accessibility: container `aria-busy="true"`, bones `aria-hidden="true"`, and exactly one `sr-only` polite live region announcing "Ranking your saved jobs…" — matching the existing `role="status"` convention in `progress-state.tsx:33-36`.
- Reduced motion needs no new rule: the `html[data-motion="reduced"] *` block (`index.css:244-256`) already zeroes keyframed animation, so `animate-pulse` freezes into a static muted block — the correct reduced-motion rendering, since the pulse is opacity-only and moves nothing.
- Tests in `matches-screen.test.tsx`: skeleton visible while the request is in flight (a deferred MSW handler, following the existing `server.use` convention), gone after, no `s elapsed` on this screen, live region present. No existing assertion covers the loading UI, and `e2e/smoke.spec.ts` waits on results rather than loading copy, so nothing breaks.

### Phase F — Docs and gates
- Write the spec + phase table into `docs/implementation/24-search-performance.md` as §10 (WS-24c) before implementing, per this project's convention.
- Fix `13-frontend.md:128` ("a progress state with the elapsed seconds" becomes false) and the §9.3 inaccuracy that calls the query embedding "already content-hash cached" — it deliberately is not.
- Gates: **0 of 8,558 scores may differ**, asserted by a differential test in the style of `test_ws24b_lexical.py`; `ruff check src tests scripts` clean; full suite green apart from the known Remotive DNS flakes; vitest green; measured before/after recorded in the doc.

## Projected result

| | Warm search |
|---|---|
| Today | 13.25 s |
| After A+B+C | ~8–9 s |
| After D (repeat search, unchanged profile) | ~5 s |

Every change except Phase D's memo is exact — the score math and every ranking stay bit-identical, so the "accept miss-by-1 over speed" tradeoff never comes into play.

## One thing I'd flag

Your list ranked the pydantic item third at ~1.4 s. My reading is that it's the *least* valuable of the five, because most of its `deepcopy` share disappears with Phase A, and the truly large win in that area is the discarded-`JobMatchResult` problem I've put out of scope. If you'd rather chase that instead of Phase D's memo, that's the higher ceiling — but it's a bigger, contract-touching change, so I'd do it as its own workstream.