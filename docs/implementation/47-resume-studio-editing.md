# WS-47 — Resume Studio: editing, persistence, revalidation

Status: **Delivered 2026-11-21** — three commits; a tailored resume can be edited and revalidated, the studio's sections save, and the keyword evidence rail is the design's right card.

## What shipped

| Commit | Feature |
|---|---|
| `be2ce9e` | a tailored resume can be edited and revalidated (`PUT /api/tailored/{id}`) |
| `01e1dde` | the studio edits sections and saves them |
| `3d3ee63` | the studio's evidence rail becomes the design's right card |

**Evidence.** `tests/test_tailored_edit.py`, `tests/test_tailoring_api.py`,
`tests/test_migrations.py` — 46 passed in the agent's pass; the full backend suite is green at
**2275 passed / 0 failed** after the README row for the new route. The frontend half carries 10 new
tests; the FE suite is green at **407 tests / 49 files**.

**Reader's notes.**

- An edit is **revalidated, not trusted**: the saved text re-runs factuality (no new claim the
  profile does not support), ATS and the existing deliverable path, and a factuality violation is a
  **200 with the report** rather than a refusal — the honesty lives in the report the human reads,
  not in a blocked save.
- The toolbar renders the **real** source document's format from the render report ("Body · 11 pt",
  "source preserved"). There are no fake B/I/U controls, because the editor cannot faithfully
  regenerate DOCX runs it does not own.

## Goal

The Resume Studio tailors and downloads but is deliberately read-only — there is no way to adjust the draft or persist an edit, and its layout diverges from the design's studio (toolbar row, keyword rail as a right card, "Continue to review →"). Build the editing flow end to end: edit sections, save, re-run factuality/ATS, regenerate the deliverable — with the honesty rules intact (no new claims; the source document is preserved).

## Design references (primary)

- `docs/design/Images-figma/Job Pilot/03 · Resume Studio · 1440.png` — pill tabs **Inline diff | Original | Cover letter | Preview DOCX | Download DOCX** + status chip "Diff review · proposed"; toolbar row (format display); document card ("BACKEND ENGINEER", "Northstar Labs · tailored draft · source preserved", "− Original wording" / "+ Tailored wording" legend, strikethrough pink original vs lime tailored, "Source: experience, bullet 2 · wording changed, no new claims added."); right card "Make every claim count." (Required keywords · 7 of 9 progress bar, Preferred keywords · 2 of 4, Matched in your source chips, Not evidenced chips, "Missing keywords are gaps, not permission to invent experience.", "0 unsupported claims" chip, "Original preserved. Check regenerated DOCX layout before export.", **Continue to review →**).
- Zoom detail: `docs/design/Images-figma/03.jpg`, `12.jpg`.

**Scope ruling:** the design's toolbar row renders as the **real** source document format from the render report ("Body · 11 pt", "source preserved") — not fake B/I/U controls pretending to edit DOCX runs that the in-place path cannot faithfully regenerate. Format truth over visual completeness.

## Current state

- Backend: `src/api/routes/tailoring.py` — `POST /api/tailor` (one-shot), `GET /api/tailored/{id}`; pipeline `src/resume/pipeline.py::run_tailoring` (research → tailor → `deliver_tailored_resume` → `analyze_ats`); `src/db/tailored.py::TailoredResumeDB` (no edit fields); WS-31 in-place editing path in `src/resume/edit.py`.
- Frontend: `frontend/src/screens/tailor-screen.tsx` + `screens/studio/` (`resume-diff.tsx`, `original-document.tsx`, `cover-letter-panel.tsx`, `evidence-rail.tsx`, `report-panels.tsx`) — tabs, download anchor, no editing.

## Concrete tasks

**Backend (B2):**
1. `PUT /api/tailored/{tailoring_id}` — body: edited section texts (summary / experience bullets / projects / cover letter, length-bounded) → validate factuality of the edited content against the stored profile (no new claims), re-run `analyze_ats`, regenerate the deliverable through the existing WS-31 in-place path; persist updated tailored content + reports + `edited_at`; respond 200 with the updated `StoredTailoringResponse` (factuality violations are a 200-with-report, never an error — honesty preserved). Accessor through `src/db/access.py` (AST rule). Tests: `tests/test_tailored_edit.py` (edit→persist→revalidate→deliverable updated; violation → 200 + report; 404/ownership via accessors). Commit: `feat: a tailored resume can be edited and revalidated (ws-47)`.

**Frontend (B2):**
2. **Editor UI** (`tailor-screen.tsx` + `screens/studio/resume-editor.tsx`): Edit mode on the Inline diff tab — editable sections (summary, bullets, cover letter) with Save/Discard; toolbar row renders the source format truthfully; status chip becomes "Diff review · edited by you" after save; Validation tab reflects the updated reports. Commit: `feat: the studio edits sections and saves them (ws-47)`.
3. **Keyword rail restyle** (`screens/studio/evidence-rail.tsx`): right-card layout per the design — required/preferred progress bars, matched/not-evidenced chips, honesty lines, "Continue to review →" linking to the approvals flow. Commit: `feat: the studio's evidence rail becomes the design's right card (ws-47)`.

## Acceptance criteria

- An edit saved through the console persists, revalidates factuality and ATS, and regenerates the DOCX (in-place when the source allows); a factuality violation never blocks the save but is reported.
- The studio screen matches `03 · Resume Studio · 1440` at all four frames (tabs wrap at 390 per the design).
- "Continue to review →" reaches the approvals flow; the deliverable download stays honest about format.

## Tests

- `tests/test_tailored_edit.py` (new), `tests/test_tailoring_api.py` extensions.
- `frontend/src/screens/tailor-screen.test.tsx` extensions (edit mode, save flow, status chip, rail).
- Manual: edit → save → download at the four frames vs `03 · Resume Studio`.

## New dependencies

None.
