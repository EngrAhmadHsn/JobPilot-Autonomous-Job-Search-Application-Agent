# WS-49 — Sprint cleanup, docs ledger, commit cutting

Status: **Delivered 2026-11-21** — the formatting gate is real again, the instrument improvements are in, and the sprint's docs and ledger record what shipped. Two items stay open and are named at the end of this document.

## What shipped

| Commit | Feature |
|---|---|
| `f6f2408` | the console's source formatting is real again, and the sweep tooling lands |

**Evidence.** `npm run format:check` is green for the first time since the redesign waves
(36 files were failing it); `npx tsc -b --force` and `eslint .` are clean; the full suites are
re-run against the formatted tree.

**What was actually removed, and what was not.**

- **The sprint's replaced implementations are gone**: the sheet's superseded CSS travel classes
  (the animate-ui primitive owns the panel's motion now), the answering card's duplicated
  taxonomy sets (one module, `screens/review/question-taxonomy.ts`), the tracker's old
  "Review the questions →" link (replaced by the application's own questions page), and the
  module-internal `export`s the new taxonomy module did not need.
- **No broad dead-export sweep was performed.** A scan finds ~66 exports with no reference outside
  their own module, but most are deliberate module contracts (the `lib/api/*` aliases, the
  `schema.ts` type vocabulary, presentation types) and deleting them wholesale is a different,
  riskier change than this sprint's cleanup. The rule this workstream actually enforces is that
  **nothing the sprint replaced is left standing**, and that holds.
- **The plan's `bombadil` assumption was wrong.** `bombadil` is a property-based exploration
  harness (Antithesis: it generates action sequences and checks invariants over time), not a
  dead-code sweeper. Its skill is committed as project tooling, but no property-based run was made:
  the package is not a dependency and this sprint added none. That is the one plan item this
  workstream did not deliver as written, recorded rather than quietly dropped.
- **`format:check` was failing on `.scratch/`** — the sweeps' own machine-written JSON reports,
  which are git-ignored artifacts rather than source. `.prettierignore` now excludes that directory
  so the gate reports on what people edit.

**Left open (carried, not hidden).**

- The design-frame **manual browser pass** the WS-43...47 docs each name (sidebar overlay geometry
  at 1440/1024, the drawer at 768/390, Home's card colors, Discover's default selection and pane
  scroll, the questions page's save→unlock, Profile pagination, `/app/account`'s key card, the
  studio's edit→save→revalidate). The automated sweep covers the mechanical half of it; a human
  comparing each screen against `docs/design/Images-figma/Job Pilot/NN · Screen · width.png`
  has not been done in this pass.
- The WS-41 state matrix and the per-screen keyboard focus-return item.

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
