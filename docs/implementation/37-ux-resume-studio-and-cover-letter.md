# WS-37 (WS-UX-05) · UX redesign: Resume Studio and cover-letter workflow

Status: **Delivered 2026-11-17** (commit `f32c877`): the read-only original-versus-tailored diff, keyword evidence, honest reports, and an editable cover letter · Source directive:
[JOBPILOT-UX-REDESIGN-AGENT-PROMPT-v2.md](../JOBPILOT-UX-REDESIGN-AGENT-PROMPT-v2.md) §6.4, §9, §8 (WS-UX-05) ·
Depends on: WS-34 (primitives), WS-33 audit (tailoring/ATS/factuality/render contracts) ·
Visual authority: [Redesign Image.png](../Redesign%20Image.png) (panel 3)

> **Where this starts.** The backend already delivers the hard part: `POST /api/tailor`
> returns the tailored resume, factuality report, ATS report, style report, job insights
> and a render report; `GET /api/tailored/{id}` retrieves a stored result (verify exact
> contracts in OpenAPI first). The deterministic ATS analyzer weights keywords 45 /
> sections 20 / title 20 / format 15 (confirm against `src/resume/ats.py` before printing
> numbers). The editor edits the candidate's own document in place — experience entries
> matched by **company + title identity**, bullets by **ordinal position** — and
> deliberately skips content it cannot safely edit; `RenderReport` distinguishes
> `in_place` from `regenerated` with edits, appended/removed content, skipped content and
> notes (WS-31). The pipeline also produces a cover-letter draft. The gap the master
> prompt names: there may be **no persistent per-change accept/reject proposal model** —
> audit this before building any Accept/Reject control.

## Non-negotiable invariants for this workstream

The original uploaded document is immutable — never overwritten by tailoring or editing.
Factuality is a hard trust boundary: a failed factuality report is report content, not an
HTTP error, and must never be hidden by a green ATS score. Never keyword-stuff: a missing
term is an honest gap; a profile-supported but under-emphasized term may be proposed; a
term unsupported by the candidate's facts stays missing. Never invent candidate facts.
Diff pairing uses the renderer's identity rules — if a paragraph cannot be paired
confidently it is "not compared / manual review required"; never a fuzzy rewrite of the
wrong role or bullet (compare content, not pixel positions). No fake Accept/Reject
controls that only mutate local state and vanish on reload. Distinguish document truth:
in-place vs regenerated, with skipped content and notes surfaced. Cover letter and resume
stay independently versioned; one must not silently alter the other. Model/BYOK failures
show the API's specific actionable error (`lib/errors.ts`), never an endless spinner.

## File-ownership boundary (exclusive)

`frontend/src/screens/tailor-screen.tsx` (both `TailorIndexScreen` and `TailorJobScreen`),
its existing test, and **new** screen-local components under
`frontend/src/screens/studio/**` (diff block, keyword panel, report panels, change-review
item, cover-letter editor). Consumes WS-34 primitives. `lib/api/**` read-only. **Backend
additions (the revision model) are proposed as a written contract for the lead, never
implemented unilaterally** — master prompt §6.4B/§8B.

## 1 — Task 1: contract audit

- [ ] From the WS-33 audit + OpenAPI: pin the exact tailoring result schema (fields for
      tailored content, `AtsReport.keyword_coverage` required/preferred hits and misses,
      factuality removed-items and violations, style findings + quantified-bullet ratio,
      `RenderReport` states, job insights with source/availability), the retrieval
      endpoint, and the document download endpoints. Record which §6.4B change-review
      fields exist today and which do not.
- [ ] Deliverable: a written gap statement — either "a server-backed revision model is
      required; here is the proposed additive API/data model" (stable change/revision id,
      source + job + tailoring identifiers, section/entry identity, original vs proposed
      text, change type, reason, evidence references, review state proposed/accepted/
      edited/rejected, revision number, timestamp) — **or** "ship the truthful read-only
      diff and label per-change review as a scoped follow-up". The lead decides; the
      master prompt explicitly permits the read-only-first path.

## 2 — Task 2: Studio shell and tabs

- [ ] Job-specific workspace retaining role/company context, tabs per master prompt §6.4:
      Overview, Resume, Cover Letter, Keywords, Questions, Research, Validation/ATS &
      Quality (grouping may be adjusted to avoid clutter; all capabilities findable).
- [ ] Keep `/app/tailor` (index) and `/app/tailor/:jobId` routes working unchanged.

## 3 — Task 3: original-versus-tailored comparison

- [ ] Side-by-side on wide desktop; stacked/toggle on narrow screens with clear
      "Original"/"Tailored" labels. Content-level diff (paragraph/bullet), additions in
      lime-tinted treatment, removals/replacements in terracotta, unchanged neutral —
      with a diff legend and non-color cues (icons/labels) so color is never the only
      signal. Pairing follows the renderer's identity rules; unpairable content is
      labelled, not diffed.
- [ ] Show whether the deliverable was edited **in place** or **regenerated**, with
      skipped content and reasons from `RenderReport`; never claim formatting survived
      when the report says otherwise. Download actions only where the endpoints exist.
- [ ] "Undo/revert draft change" and per-change accept/edit/reject ship **only if** the
      Task 1 audit established a real persistence contract; otherwise the diff is
      read-only and labelled as such in the UI.

## 4 — Task 4: keyword coverage and evidence panel

- [ ] Required and preferred coverage **separate**, with actual matched and missing
      terms from `keyword_coverage`. Selecting a keyword shows supporting
      resume/profile evidence where the data supports it. The four-way distinction
      (present in resume / supported in profile but not emphasized / missing from source
      evidence / unknown) renders **only** where the data model can support exactly that
      distinction. No claim that coverage guarantees ATS acceptance or interviews; if the
      listing has no reliable structured requirements, say coverage could not be measured
      — never a misleading 100 % or 0 %.

## 5 — Task 5: ATS, factuality, style, render, research panels

- [ ] One panel per real report, in plain language, each honest about its limits.
      Factuality failures are rendered as findings (removed unsupported skills/experience/
      projects, violations) with visual weight, not tucked behind a green score. Style
      report shows jargon/filler findings and the quantified-bullet ratio. Research
      insights distinguish sourced facts from inferred/unverified.
- [ ] Validation re-runs after any candidate edit where the backend supports it; the UI
      never presents stale validation as current.

## 6 — Task 6: cover letter

- [ ] Editable preview with role/company context and the same evidence rules; structure
      cues optional and non-rigid; save/regenerate where persistence supports it. No
      fabricated employer facts; researched details only when actually returned and
      sourced. Model-unavailable and BYOK-misconfigured states show the specific API
      error with a recovery path.

## 7 — Task 7: tests and verification

- [ ] Tests per master prompt §9.5 as far as the frontend contract reaches: correct diff
      pairing for multiple roles, repeated bullets and projects; unmatched paragraphs
      surfaced as "not compared"; original source untouched; no interactive accept/reject
      rendered unless backed by the persisted contract; factuality findings always
      visible alongside ATS; keyword panel renders real required/preferred splits;
      cover-letter and resume versions independent; every stated weight matches
      `src/resume/ats.py`.
- [ ] Browser-verify at 1440×1000, 1280×800, 390×844 (assigned ports, real backend, a
      real tailored result): side-by-side alignment, stacked toggle on mobile, wrapping,
      legend visible, panels readable. Screenshots into `docs/design/ws37-studio/`.

## Acceptance

- The Studio reads as reference panel 3's density: two-column comparison + keyword
  matching, with every panel grounded in the real reports and every safety rule above
  intact.
- The Task 1 gap statement is recorded and the lead's decision carried out — no fake
  persistence either way.

## Tests

`npm run test -- src/screens/tailor-screen.test.tsx` plus screen-local additions; full
suite at the lead's integration gate.
