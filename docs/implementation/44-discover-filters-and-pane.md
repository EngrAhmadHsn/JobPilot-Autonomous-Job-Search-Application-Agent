# WS-44 — Discover: design filters, default selection, pane scroll

Status: **Delivered 2026-11-21** — three commits (one backend contract, two frontend features); Discover filters the stored corpus by workplace and location, selects the best match by default, and scrolls its two panes instead of the page.

## What shipped

| Commit | Feature |
|---|---|
| `02c3566` | job search filters by workplace and lists corpus locations (backend contract) |
| `da0e7b7` | discover filters match the design's dialog and chips |
| `a0d7f2c` | discover selects the best match by default and scrolls its panes, not the page |

**Evidence.** The backend half is `JobSearchRequest.workplace` plus `GET /api/jobs/locations`
(README API table, machine-checked); the backend agent's run of the full suite was **2246 passed /
8 skipped / 0 failed**. The frontend half is `screens/discover/filters-dialog.test.tsx` and the
Discover cases in `matches-screen.test.tsx` (default selection + pane scroll). The full FE suite is
green at **407 tests / 49 files**.

**Reader's notes.**

- **One commit, not two, for the backend:** the workplace filter, the location list and the
  pass-through that carries them both sit on the same executor seam in five files of
  `src/api/routes/jobs.py` and the search pipeline; splitting them would have cut one contract in
  half (ledgered ruling).
- **No employment-type filter — deliberately.** `employmentType` is populated on 0 of the corpus's
  rows (WS-23), so a control for it would be a lie. The dialog ships Location, Workplace, Skills
  and Rank top N.
- **A contract caveat worth knowing.** The workplace match is a normalized contains-match against
  the raw `remote_policy` column. Lever and Ashby write lowercase `onsite`; Greenhouse metadata is
  free text and can say `On-site`, which does not contains-match `onsite`. The result is a thin
  onsite slice on Greenhouse-sourced rows — a data-reality limit, recorded rather than papered over
  with fuzzy matching.
- Filters apply **server-side before scoring and `top_n`**, and the dialog's honesty note is
  verbatim: "These filters apply to the stored corpus. They do not fetch job boards."

## Goal

Replace the Discovery screen's not-useful filters (location substring + top-N) with the design's filter model, make the top-ranked match the default selection, and give the split view its own scroll so the whole page never scrolls at ≥1024.

## Design references (primary)

- `docs/design/Images-figma/Job Pilot/02 · Discover · 1440.png` / `· 1024.png` — search row, filter chips ("Remote · United Kingdom ×", "Python ×"), "Filters" button, "Stored corpus · refreshed …", "N matches", "Best match first ↓", result cards, detail pane.
- `docs/design/Images-figma/Job Pilot/Overlay · Job filters · 480.png` / `· 350.png` — the filters dialog: **Location** select, **Workplace** select, **Skills** text, honesty note verbatim *"These filters apply to the stored corpus. They do not fetch job boards."*, **Apply filters** / **Cancel**.
- Zoom detail: `docs/design/Images-figma/02.jpg`, `84.jpg`, `85.jpg`.

**Scope ruling:** no employment-type filter — that column is empty on 0 of 4,406 live listings (WS-23), so a filter on it would be dishonest. `Rank top N` moves into the dialog as a fourth field (an existing honest control that must not vanish).

## Current state

- `frontend/src/screens/discover/search-panel.tsx` — query combobox + location substring Input + top-N input behind a disclosure; `POST /api/jobs/search` with `only_embedded: false`.
- `frontend/src/screens/matches-screen.tsx` — no default selection (`?job=` param only); whole page scrolls; split grid `lg:grid-cols-[minmax(0,0.62fr)_minmax(0,1.38fr)]`.
- `frontend/src/lib/api/endpoints.ts` / `types.ts` — `JobSearchRequest = {profile_id, query?, location?, top_n, only_embedded}`.
- Backend `POST /api/jobs/search` (`src/api/routes/jobs.py`) — filters only `query` (ANY-token) and `location` (substring).

## Concrete tasks

**Backend (B1):**
1. `JobSearchRequest` gains `workplace: str | None` — `remote` / `hybrid` / `onsite`, matched against the corpus `remote_policy` column before scoring; applied server-side before `top_n`; `stats` echoes applied filters. Existing `location`/`query` kept.
2. `GET /api/jobs/locations` — distinct corpus locations (same response shape as `/api/jobs/suggest`), feeding the dialog's Location select.
3. Tests: `tests/test_jobs_api.py` additions (workplace filtering, locations endpoint, filter echo in stats). Commits: `feat: job search filters by workplace (ws-44)`, `feat: the search suggest family gains corpus locations (ws-44)`.

**Frontend (A2):**
4. **Filters dialog + chips** — dialog per the Overlay renders (Location select from `/locations`, Workplace select, Skills text, Rank top N, honesty note, Apply/Cancel; widths 480/350 responsive); active filters render as removable chips; "Best match first ↓" label; URL-synced params (`?workplace=…&location=…&skills=…&top_n=…`) alongside `?job=`. Commit: `feat: discover filters match the design's dialog and chips (ws-44)`.
5. **Default selection** — when ranked results exist (fresh search or restored last search) and no `?job=` param, select the first match and write it to the URL (replace, not push). Commit: `feat: the first ranked match is selected by default (ws-44)`.
6. **Pane scroll** — at ≥1024 the screen is a fixed-height flex (`h-[calc(100dvh-68px)] overflow-hidden`); the results list and the detail pane each scroll internally; keyboard navigation scrolls the selected row into view (`scrollIntoView: nearest`). Below 1024 the stacked layout keeps page scroll. Commit: `feat: discover's panes scroll independently on desktop (ws-44)`.

## Acceptance criteria

- The filters dialog matches the Overlay renders (fields, note text, buttons, both widths).
- Chips reflect and clear active filters; URL params survive reload; "Best match first ↓" present.
- A fresh visit with a stored last search shows the top match selected without a click.
- At 1440/1024 the page itself never scrolls; both panes scroll; arrow keys keep the selected row visible.
- Backend: workplace filter narrows results server-side; `/api/jobs/locations` lists corpus locations; stats echo filters.

## Tests

- `frontend/src/screens/matches-screen.test.tsx` + a new filters-dialog test file (MSW handlers for `/locations` and the new request fields).
- `tests/test_jobs_api.py` backend additions.
- Manual: four design frames + both dialog widths against the reference PNGs.

## New dependencies

None.
