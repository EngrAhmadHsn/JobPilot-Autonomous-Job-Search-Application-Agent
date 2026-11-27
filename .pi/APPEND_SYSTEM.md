## Project: Agentic Job Applier (JobPilot)

Read the repo's own `AGENTS.md` first — it is the project contract. This file adds only what it
does not say, plus the facts that cost time when forgotten.

**Memory for this project:** `~/.free-pi/agent/memory/projects/agentic-job-applier/MEMORY.md`
(58 inherited entries + the 2026-11-21 review). Read its "Start here" three before touching the
search path, the browser layer, or the docs.

**Interpreters and gates**

- Python: `./env/Scripts/python.exe` (never `python3`; never wrap in `cmd.exe /c`).
- Targeted: `./env/Scripts/python.exe -m pytest <module> -q`. Suite is ~4 min — affordable, but
  run the affected modules first.
- Docs/env contract: `tests/test_docs_accuracy.py` (README API table ⇄ OpenAPI, both directions)
  and `tests/test_env_docs.py` (`.env.example` ⇄ settings). **A new route must add a README row or
  the suite fails.**
- Frontend: `cd frontend && npx tsc -b --force && npx eslint . && npx vitest run --maxWorkers=2`
  (the default worker count aborts with exit 134 on this machine).
- `--live` claims need the real thing: API + `scripts/serve_fake_ats.py` + Chromium.

**Invariants that must not be "fixed" away**

- No autonomous submission exists. `AssistAdapter` holds `PREPARE` only and never clicks submit;
  `AUTO_SUBMIT` is unreachable. M5 is **not** achieved — no live board has received an application.
- The approval is a persisted human decision with an identity; approve returns `202` + a durable
  run id and executes at most once. An unprovable outcome escalates as `submission.uncertain`.
- Untrusted text renders as text. No `dangerouslySetInnerHTML`; the ESLint rule is the guard.
- A component whose evidence is missing scores *unknown* and keeps its weight in the denominator.

**Known flakes (do not debug)**

- Six `tests/test_jobs.py` remotive tests fail on transient DNS (`gaierror`) — the SSRF guard
  resolves real DNS under `MockTransport`. Environmental.
- Chroma's `query(n_results=count)` can return `count - 1`, so an unfiltered full-corpus search
  reports `degraded=true`. Edge case, not a matching bug.
- fastembed's "Local file sizes do not match the metadata" warning is benign (the tokenizer patch).

**Do not touch** `reference_project/` (a separate project kept for reference).

**Open work** lives in `docs/implementation/00-OVERVIEW.md`; the live sprint is WS-43…49. When a
status line disagrees with the code, the code wins — and say so.
