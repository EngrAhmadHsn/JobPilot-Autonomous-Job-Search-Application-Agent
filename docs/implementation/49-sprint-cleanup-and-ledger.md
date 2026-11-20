# WS-49 — Sprint cleanup, docs ledger, commit cutting

Status: **In progress — 2026-11-21** · Owner: sprint WS-43…49 · Runs last

## Goal

Close the sprint the way the repo's waves always close: junk removed, the docs reconciled with what actually shipped, and the work cut into atomic per-feature commits — each verified green against its own tree.

## Concrete tasks

1. **Junk sweep** (`bombadil` skill + sweep agent) — dead code the sprint made removable: superseded CSS animation utilities the animate-ui CLI stripped, unused exports/components, stale comments referencing replaced behavior, leftover experimental helpers. Nothing behavioral changes; the full suites prove it. Commit: `chore: the sprint's dead code goes (ws-49)`.
2. **Docs finalize** — `docs/implementation/43…49-*.md` gain their "what shipped" records (commits, test evidence, reference-image evidence per feature, documented deviations); `00-OVERVIEW.md` ledger row updated; README API table updated (the machine-checked README test enforces it). Commit: `docs: the ws-43..49 sprint records what shipped (ws-49)`.
3. **Commit cutting** — the standing policy for this sprint: **one commit per feature, never per workstream**; each commit verified green (tests for the touched area) against its own tree before the next; messages in repo style (`feat:/fix:/test:/docs:/chore:/refactor: … (ws-NN)`). Staging is per-feature deliberate — the known `git add` trap of sweeping already-staged files applies: stage explicitly, `git status` before every commit.
4. **Push** — after the final gate, push `main` (the repo's waves push at sprint end).

## Acceptance criteria

- No dead code remains from the sprint's replaced implementations; suites green.
- Every feature of WS-43…48 exists as its own commit with green evidence; the ledger and the overview row reconcile with `git log`.
- README API table test green (new endpoints `/api/applications/{id}/answers`, `/api/jobs/locations`, `PUT /api/tailored/{id}` documented).

## Tests

- `./env/Scripts/python.exe -m pytest -q`; `cd frontend && npm run test -- --maxWorkers=2` + `typecheck` + `lint` + `format:check`; `ws41-audit.mjs`; e2e.

## New dependencies

None.
