# JobPilot — UX Redesign & Frontend Evolution Directive

**Workstream ID:** `JOBPILOT-UX-01`  
**Status:** Approved direction; implementation not yet started  
**Product:** JobPilot — Autonomous AI Job Search & Application Agent  
**Repository:** `https://github.com/EngrAhmadHsn/JobPilot-Autonomous-Job-Search-Application-Agent`  
**Primary implementation surface:** `/frontend`  
**Reference design:** the user-attached JobPilot multi-screen dashboard/workspace image.  
**Planning-format reference:** the user-attached `REACT-MIGRATION-PLAN.md`.

---

## Agent instruction — read this first

Act as the product design lead, senior frontend engineer, and implementation owner for this workstream. **Redesign and improve the existing JobPilot product in the existing repository. Do not build a separate demo, a disconnected prototype, or a second frontend.** The result must be a coherent, production-ready experience connected to the real backend contracts.

Treat the attached JobPilot design image as the approved visual direction. It is the authority for composition, palette, navigation feel, component density, card treatment, and overall atmosphere. The attached React migration plan is a reference for how this directive should be organized and how rigorously work should be phased; it is **not** a design reference and its SmartDiet-specific technology, product requirements, palette, or decisions must not be copied into JobPilot.

The user has explicitly refined the dashboard direction: **JobPilot is first and foremost a job-search and application workspace, not an analytics dashboard.** Keep the user's core task dominant. Use a graph only when real data makes it useful for a decision. Do not add charts to fill space or make the dashboard look more sophisticated.

The user also specifically wants ResumeKaraage-inspired resume and cover-letter capabilities: visible original-versus-tailored differences, keyword matching, evidence-backed editing, and quality checks. Incorporate the useful interaction patterns without copying another product's branding or assuming its implementation.

Do not ask the user to choose between new visual directions. The direction is already approved. Make reasonable implementation decisions, record assumptions, and proceed. Ask only when a genuinely blocking product or safety decision cannot be resolved from this directive or the repository.

**This is a frontend evolution and UX redesign, not a React migration.** React already exists. Preserve the existing architecture unless a documented, tested reason requires a narrow change.

## 1. Why this work exists

JobPilot already has substantial capability: it ingests and stores job listings, ranks them against a candidate profile, explains match components, researches roles, tailors resumes, checks factuality and ATS-style criteria, prepares application payloads, requires human approval, executes supported browser workflows, records evidence, and tracks outcomes.

The user experience must make that capability feel like one connected workflow instead of a collection of technical screens.

The product's central job is to help a candidate:

1. Discover relevant opportunities from the available job corpus.
2. Understand why each opportunity fits or does not fit their profile.
3. Prepare a truthful, role-specific resume and cover letter.
4. Review every meaningful change and resolve employer questions.
5. Make the required human approval decision.
6. Complete supported application handoff steps safely.
7. Track the actual result and know what needs attention next.

The primary experience is therefore:

**Discover → Evaluate → Prepare → Review → Human approval → Supported handoff → Track.**

The home dashboard must answer: **“What is the next useful job-search or application action I should take?”** Analytics, agent status, and technical diagnostics support that journey; they are not the product's purpose.

## 2. Repository and product reality — audit before editing

The repository already contains a React operator console. Re-inspect the current branch and working tree before implementation; do not rely on an old plan or a prior conversation as a substitute for current source.

### 2.1 Existing frontend

The current frontend lives in `/frontend` and uses:

- React 19 + TypeScript.
- Vite 8.
- Tailwind CSS 4.
- Base UI / shadcn-style components.
- React Router 7.
- TanStack Query 5 for server state and request caching.
- React Hook Form + Zod for complex forms.
- Lucide icons.
- Vitest, Testing Library, MSW, ESLint, TypeScript and Playwright.

The package already has scripts for `dev`, `build`, `preview`, `lint`, `format:check`, `typecheck`, `test`, `coverage`, API type generation and Playwright E2E. Confirm the exact scripts from `frontend/package.json` before using them.

The route tree currently includes the public landing page and sign-in plus authenticated `/app` screens. Existing route modules include:

- `/app` — Overview / Home.
- `/app/resume` — resume upload, parsed profile and document library.
- `/app/profile` — candidate application profile and preferences.
- `/app/matches` — search and ranked job matches.
- `/app/matches/:jobId` — job detail and match explanation.
- `/app/tailor` — tailoring entry point / job selection.
- `/app/tailor/:jobId` — job-specific tailoring workspace.
- `/app/approvals` — prepare, inspect, approve or reject application.
- `/app/tracker` and `/app/tracker/:applicationId` — application list and detail/history.
- `/app/activity` — audit activity and grouped executions.
- `/app/operations` — job corpus refresh and durable run state.
- `/app/admin` — server-authorized platform administration.

The current route source is `frontend/src/routes.tsx`. Preserve deep links and existing route behavior. You may improve labels, navigation grouping, screen composition and shared components, but do not silently remove or strand an existing capability.

### 2.2 Existing backend and domain capabilities

The backend is Python/FastAPI. It remains authoritative for business logic, model calls, matching, factuality, application state, ownership, authorization, durable execution and evidence.

Relevant existing functionality to verify in source before changing anything:

- Resume upload/parsing and structured candidate profile creation.
- A separate user-confirmed application profile for facts not reliably carried by a resume, including work authorization and work preferences.
- Job search over the **stored corpus**. Search and corpus refresh are separate actions; do not label a store-only search as a live scrape of all boards.
- Hybrid matching with component scores, explanation, matched/missing requirements and evidence/availability signals.
- Job research and tailoring through `POST /api/tailor`, with a stored result retrievable from `GET /api/tailored/{id}` (verify actual current route contracts in OpenAPI and route source).
- The tailoring response already contains a tailored resume, factuality report, ATS report, style report, job insights and a render report.
- The deterministic ATS analyzer measures keyword coverage, section completeness, title alignment and format risks. Current weighting in `src/resume/ats.py` is 45% keywords, 20% sections, 20% title alignment and 15% format safety; confirm before presenting those numbers in UI copy.
- The factuality validator may remove unsupported skills, experience or projects. A factuality failure is valid report content, not a generic HTTP failure.
- The document editor attempts to edit the candidate's own uploaded document in place so formatting survives. `RenderReport` distinguishes `in_place` from `regenerated` and reports edits, appended/removed content, skipped content and notes.
- The tailoring pipeline produces a cover-letter draft as part of the structured result.
- Application preparation and approval are separate operations. Approval queues durable work and can return HTTP `202` with a run identifier; it is not proof that an application has been submitted or verified.
- The durable SQL-backed queue and worker support progress, recovery and retry states. The UI must display the backend's real state.
- Audit activity records actual actions, actor, outcome, workflow and timestamp. There is no SSE/WebSocket event stream in the audited design; do not call polling “live streaming”.
- Real-board assist mode can fill an application and hand it back to a human. It must not click the final submit action on the user's behalf. CAPTCHA/MFA/anti-bot challenges are handed to a human, not bypassed.
- Administrator-wide views are protected by backend authorization. A frontend-only `isAdmin` check is not authorization.

### 2.3 Existing source files to inspect

At minimum, inspect these files plus their dependencies, tests and current route/API contracts:

- `AGENTS.md`, `CLAUDE.md`, `docs/ARCHITECTURE.md`, `docs/SECURITY.md`, `docs/PROJECT_PLAN.md`.
- `docs/implementation/00-OVERVIEW.md` and the current workstream docs, especially `13`, `17`, `18`, `19`, `20`, `21`, `22`, `25`, `31` and `32`.
- `frontend/package.json`, `frontend/src/routes.tsx`, `frontend/src/index.css`.
- `frontend/src/components/layout/**` and shared components under `frontend/src/components/**`.
- `frontend/src/screens/**` and their tests.
- `frontend/src/lib/api/**`, query configuration, polling helpers, status helpers and profile hooks.
- `src/api/routes/**`, `src/resume/**`, `src/matching/**`, `src/applications/**`, `src/db/**`, `src/runs/**` and corresponding tests where relevant.

**The source code and running API outrank stale comments or older workstream documents.** When documentation and source disagree, reproduce the behavior, document the discrepancy and do not silently invent a contract.

## 3. Non-negotiable product and engineering rules

Every workstream is bound by these rules.

1. **The backend is the source of truth.** The frontend renders returned facts and may hold temporary editor state, but it must not invent match scores, outcomes, queue states, application statuses, evidence, or success claims.
2. **The agent proposes; the human decides.** Preserve the mandatory approval boundary. Never add a “mass apply”, “apply to all”, hidden-submit, or auto-submit control.
3. **Real-board assist remains assist.** A filled form is not a submitted application. A handoff is not a verified result. The human completes the final board action. Do not click a real employer's final submit button, bypass CAPTCHA/MFA, or defeat anti-bot controls.
4. **Fake ATS and real-board flows must be visibly distinct.** Do not let a demo/test adapter imply a real-world submission capability.
5. **Never fabricate candidate facts.** Do not invent skills, years, employers, job titles, qualifications, dates, metrics or achievements. Every claim in tailored content must be traceable to the candidate's source profile or explicitly confirmed by the candidate.
6. **Never keyword-stuff.** The ATS analyzer reports coverage; it does not grant permission to add unsupported keywords. A missing keyword is an honest gap, not an instruction to manufacture experience.
7. **Keep the original resume immutable.** Tailored drafts and revisions must be traceable to the source document. Do not overwrite the only original uploaded artifact.
8. **Show document-generation truth.** Distinguish in-place edits from regenerated files. Surface `RenderReport` notes and skipped paragraphs instead of claiming that original formatting was preserved when it was not.
9. **Keep unknown distinct from negative.** An absent match component, unknown sponsorship status, missing resume evidence or unavailable metric must be labelled unknown/unavailable, never silently scored as a positive or as a confirmed negative.
10. **Keep state transitions honest.** Distinguish prepared, awaiting approval, approved/queued, running, submitted, verified, blocked, uncertain and failed according to the backend's actual state model. Approval `202` means accepted/queued, not completed.
11. **Preserve ownership and tenant isolation.** Never fetch another user's profile, documents, application, audit data, model credential or evidence. Keep server authorization authoritative.
12. **Treat external job-board content as untrusted data.** Render it as text; do not allow job content to become HTML, executable instructions or trusted agent directives.
13. **Protect secrets and PII.** Never display, log, copy into analytics or expose model API keys, cookies, tokens or private credentials. Respect the existing PII masking and BYOK behavior.
14. **Keep EEO data out of job matching.** The user-confirmed profile distinguishes work authorization, sponsorship, citizenship and EEO data. EEO selections must not influence matching or recommendation ranking.
15. **Do not invent a real-time service.** Use truthful polling labels and returned timestamps until a real streaming endpoint exists.
16. **Keep the API request budget under control.** Follow existing polling helpers and the project's documented per-resource polling limits. Do not introduce aggressive intervals or screen-wide ticking state.
17. **Accessibility is part of completion.** Target WCAG 2.2 AA: semantic controls, keyboard use, visible focus, labels, status announcements, sufficient contrast, reduced-motion support and usable touch targets.
18. **Preserve tests and repository instructions.** Do not delete tests to make a build green. Follow `AGENTS.md`, including Windows-specific test invocation guidance and known environmental flakes.
19. **No broad backend rewrite.** Keep Python business logic, LangGraph orchestration, database schema and security model unchanged unless a narrowly scoped, demonstrably necessary addition is specified, documented and tested.
20. **No surprise dependencies.** Prefer the existing component and icon systems. Add a dependency only with a written reason and a measurable benefit.

## 4. Approved visual direction

### 4.1 Visual reference hierarchy

The attached JobPilot screenshot is the approved visual authority. Reproduce its overall feel:

- Warm ivory/cream workspace background.
- Deep forest-green vertical sidebar with a clear active navigation state.
- Clean paper-like content surfaces, thin warm borders and soft, restrained elevation.
- Bricolage-style display headings with Geist for body/interface text.
- Green match and success indicators, amber/terracotta attention states, and understated neutral information states.
- Rounded but controlled cards and controls; clear hierarchy and readable dense information.
- Spacious page headings, compact metadata, legible tables/lists, and clear primary actions.
- A premium, calm, credible career-operations product — not a generic enterprise admin template and not a neon AI toy.

Preserve the existing semantic color meaning already embedded in the codebase:

- **Lime = agent-originated work/action.**
- **Terracotta = human-originated action/decision or human attention.**
- Forest = brand, primary navigation and primary actions.
- Sage = quiet positive support state.
- Neutral paper/stone = structure and content.

Do not replace these semantics without an explicit design decision and a migration of all affected states.

### 4.2 Existing code tokens are the starting point

The current `frontend/src/index.css` declares the coherent visual language. Reuse and reconcile those tokens instead of scattering raw hex values across components:

| Role | Current token/value |
|---|---|
| Main canvas | Ivory `#F7F5EF` |
| Paper/card surface | `#FFFDF8` |
| Primary forest | `#173D32` |
| Agent lime | `#D9F36A` |
| Human terracotta | `#F1D6C8` |
| Supporting sage | `#E6ECE8` |
| Warm border | `#E3DDD0` |
| Primary ink | `#23211C` |
| Muted text | `#6A6459` |
| Heading typeface | Bricolage Grotesque Variable |
| Interface typeface | Geist Variable |

The screenshot may use slight optical variations. Reconcile through tokens, not one-off inline colors. Measure text contrast; do not assume it passes because the colors look harmonious. The default authenticated workspace remains the light warm-paper theme shown in the reference. Preserve existing dark-theme support if it is already wired and tested; do not let it derail the core redesign.

### 4.3 Visual rules

- Prefer hierarchy, typography, whitespace and grouping over adding more cards.
- Do not put cards inside cards without a clear structural reason.
- Avoid huge decorative match circles, chart-heavy hero sections, gradient text, glassmorphism, oversized empty space, unnecessary illustration, emoji-as-icons and decorative motion.
- Use the existing Lucide icon system consistently.
- Do not introduce new fonts unless the current branded fonts cannot meet a demonstrated requirement.
- Motion is purposeful and subtle: reinforce navigation, status changes or completion. Respect `prefers-reduced-motion`. Do not animate every card or every section on every render.
- Keep content widths and card density appropriate to the real workload. Job descriptions, company names, long requirements, missing answers and status labels must wrap safely.

## 5. Information architecture and navigation

Reorganize the presentation around the user's task while preserving existing routes and features. The approved screen uses a dark left sidebar with clear, compact destinations. Use this conceptual navigation:

1. **Home** — priority actions and job-search overview.
2. **Discover** — job search, ranked matches and job details.
3. **Applications** — prepared, awaiting review, in-progress and historical applications.
4. **Resume Studio** — tailored resume, change review, keyword coverage and cover letter.
5. **Profile & Documents** — original resume library, parsed facts, confirmed application profile and preferences.
6. **Activity** — agent actions, human actions, failures, blocked steps and execution history.

Place **Operations** and **Administration** in a secondary System/Workspace area, not as equal steps in the candidate's job-search journey. Keep the admin area visible only where appropriate and always backed by server authorization. Account controls, theme and credential settings belong in the existing account/profile mechanisms; do not invent Settings or Help pages without real product behavior behind them.

Navigation labels may be consolidated or renamed for clarity, but deep links and the existing route contracts must continue working. Where two current screens become one conceptual workspace, preserve route compatibility and redirect/link behavior deliberately rather than deleting screens casually.

## 6. Screen-by-screen experience specification

### 6.1 Home — “Your next career move”

**Purpose:** make the next action obvious and give a quick, factual view of the current job-search effort.

**Priority order:**

1. Greeting/page heading and compact agent/account status.
2. One clear “Your attention” / “Your next actions” area: approvals to review, unanswered employer questions, blocked or uncertain tasks, ready packets, and an invitation to continue discovery where appropriate.
3. A featured high-fit job or application that has a meaningful next action. It should be a real item returned by the API, not a fabricated sample card.
4. A compact pipeline/status summary, using only real application states and counts.
5. A concise Recent Activity feed with links to the related job, application or run.
6. A compact shortlist of additional relevant opportunities only when actual match data exists.

**Analytics restraint:**

- Do not make charts the hero or the main purpose of Home.
- A simple stage distribution or horizontal pipeline can be useful when it immediately explains where applications are waiting. Prefer it over multiple charts.
- A time-series chart is allowed only if the API provides a sufficiently complete, correctly timestamped event/application dataset and the chart answers a real user question. Label the date window and denominator.
- Do not invent interview rates, response rates, conversion percentages, average response times or “growth” metrics. Do not infer a metric from a partial page of applications or the latest limited audit page.
- When data is insufficient, replace the graph with a short list, stage strip or “not enough history yet” explanation. Empty chart space is not a design problem to solve with fake data.

The dashboard is an operations surface for the candidate, not a reporting dashboard. A user should be able to identify their next action within seconds.

### 6.2 Discover — find and evaluate opportunities

**Purpose:** let the candidate scan matches quickly while retaining enough context to make a confident decision.

**Desktop layout:**

- Top search area for job title, skills, company and location.
- Compact, useful filters (location/remote, experience/seniority, role family, employment type, salary if present, sponsor signal if verified).
- Results list on the left; selected job details on the right.
- Each result displays title, company, location, date/source where known, match score and a small number of relevant skill chips.
- Selected result shows title/company, location, employment type, salary range if present, short description, match explanation, component breakdown, evidence-backed matched requirements, missing requirements and verified/unknown sponsorship information.
- Actions: Save/shortlist and Prepare/Tailor for this job. Actions must be wired to real behavior.

**Match explanation:**

- Keep the overall score visually legible but not oversized.
- Explain the score with the actual component values, component states and evidence coverage available from the API.
- Separate “matched”, “missing”, “unknown” and “not measured”.
- “Missing” is not necessarily a hard disqualification. Explain the role requirement and the profile evidence gap.
- Expose deeper scoring detail progressively; do not put eight score dimensions in every card.

**Search truth:** job search currently operates over the stored corpus; corpus refresh is a separate Operations action. Use copy such as “Search stored jobs” or otherwise make the behavior clear. Do not imply that every Search click contacts all employer boards.

### 6.3 Job detail

The job detail route must remain useful when opened directly or from Home, Discover, a saved job or an application. It should show the complete listing, match reasoning, matched and missing requirements, any research insights, source and freshness information when available, and clear next actions. Do not repeat every Discover card field in a second noisy layout.

### 6.4 Resume Studio — tailored resume and change review

**This is a priority differentiator.** The user wants a ResumeKaraage-inspired review experience integrated into JobPilot's existing tailoring and factuality pipeline.

The Studio is job-specific and should retain the selected role/company context. Suggested sections/tabs:

- Overview.
- Resume.
- Cover Letter.
- Keywords.
- Questions.
- Research.
- Validation / ATS & Quality.

The exact tab grouping may be adjusted to avoid clutter, but all capabilities must be easy to find.

#### A. Original-versus-tailored resume comparison

Provide a readable document comparison, not just two download buttons.

- Show the original resume and the tailored draft side-by-side on wide desktop screens.
- On narrow/mobile screens, use a toggle or vertically stacked original/draft view with a clear “Original” / “Tailored” label.
- Show additions, rewrites and removals with accessible visual treatment: subtle green/lime for supported additions or improved wording, terracotta for removed/replaced text, neutral styling for unchanged content. Never rely on color alone; add labels/icons or an accessible diff legend.
- Support line/paragraph/bullet-level inspection. Each change should be traceable to the correct section and experience/project entry.
- Include “View full diff”, “Undo/revert draft change” and document download actions only when implemented and reliable.
- Never mark a whole paragraph as changed just because the PDF/DOCX layout shifted. Compare content, not pixel positions.
- Preserve original formatting where the current renderer supports in-place edits. Clearly display whether the final export was edited in place or regenerated, and surface skipped content and reasons.

The existing editor matches experience entries by identity (company + title) and bullets by ordinal position; it deliberately skips content it cannot safely edit. Preserve those safety properties. Do not use fuzzy paragraph matching that could rewrite the wrong role or bullet.

#### B. Proposed change review and persistence

The current tailoring result provides the complete tailored content and render report; it may not yet provide a persistent, per-change accept/reject proposal model. Audit this gap before implementing controls.

If there is no existing server-backed change-review model, design a narrow additive revision mechanism rather than pretending that browser-only state is authoritative. Each proposed change should carry, at minimum:

- Stable change/revision identifier.
- Source document/profile and job/tailoring identifiers.
- Section and entry identity (company/title or project identity; bullet index where applicable).
- Original text and proposed text.
- Change type (rewrite, addition, removal, reorder/emphasis) where supported.
- Plain-language reason for the change.
- Source evidence reference(s) that support the proposed wording.
- Human review state: proposed, accepted, edited or rejected.
- Revision number and creation timestamp.

The candidate must be able to inspect the change, accept it, edit it or reject it. Accepted/edited changes create a new tailored revision; rejected changes do not appear in the final output. The original upload remains immutable. Re-run factuality, style and ATS validation after the candidate changes the draft. Never let the model mark its own proposal as accepted.

Do not ship fake Accept/Reject controls that only change local component state and disappear on reload. If the full persistence contract requires more backend work than can safely be completed in this workstream, ship a truthful read-only diff first, document the proposed revision API/data model and mark interactive per-change review as a clearly scoped follow-up. Do not silently imply that the functionality is complete.

#### C. Keyword coverage and evidence mapping

The existing ATS report already returns required/preferred keyword hits and misses. Build a visible, actionable keyword panel from that real report.

- Show required coverage and preferred coverage separately.
- Show actual matched and missing terms.
- Let the candidate select a keyword to see the supporting resume/profile evidence where available.
- Distinguish “present in resume”, “supported in profile but not emphasized”, “missing from source evidence” and “unknown/unmeasured” only when the data model can support those exact distinctions.
- A profile-supported but under-emphasized term may be proposed for inclusion. A term not supported by the candidate's facts must remain missing; never add it to raise the score.
- Do not claim that a keyword coverage percentage guarantees ATS acceptance or an interview.
- If the job listing has no reliable structured requirement data, clearly say coverage could not be measured rather than presenting a misleading 100% or 0%.

#### D. ATS, factuality and writing quality

Present the existing deterministic analysis in useful language:

- ATS report: keyword coverage, section completeness, title alignment and format risks.
- Factuality report: passed/failed plus all removed unsupported skills/experience/projects and violations.
- Style report: detected jargon/filler findings and quantified-bullet ratio/count.
- Render report: in-place vs regenerated, edits/appends/removals, skipped items and notes.
- Job research insights: show source/availability and distinguish facts from inferred or unverified information.

Treat the validator as a hard trust boundary. A failed factuality report is not a generic error and must not be hidden by a green ATS score.

#### E. Cover Letter Studio

The cover letter should use the same selected job, confirmed candidate profile, resume facts and job insights. It must remain editable and must not make claims unsupported by the candidate's records.

Provide:

- A readable editor/preview, with clear document title and role/company context.
- Optional concise structure cues (opening, relevant evidence, company/role connection, close) without forcing a rigid formula.
- Evidence/source context for factual claims where practical.
- Save draft / regenerate selected section / undo where supported by persistence.
- Relevant keyword/role alignment as a secondary check, not keyword stuffing.
- Validation after edits, and an accurate generated/exported file state.

Do not generate generic company praise or fabricate facts about the employer. Use researched details only when they are actually returned and clearly sourced.

### 6.5 Review & human approval

**Purpose:** make the irreversible boundary explicit and give the human the exact prepared payload to inspect.

The review screen should show:

- Employer, role, board/source and candidate identity.
- Exact resume version and cover-letter version selected for the application.
- Employer questions in the order the board published them, with required flags and unresolved/human-needed questions visible.
- Application answers and their sources: confirmed profile fact, candidate-provided answer or unresolved.
- Supporting documents and any research summary included in the prepared payload.
- Readiness blockers and warnings.
- Clear actions to edit the packet, reject it or approve/queue it.

Approval must act on the exact persisted prepared payload that the user reviewed. If a document or answer changes after preparation, invalidate/rebuild the prepared packet or make the changed version explicit; do not approve a different payload from the one displayed.

The post-approval state must reflect the actual API response. If the API returns `202` and a run id, show “Approved — queued” (or the exact backend-supported label), the run identifier/progress link and the next expected action. Do not display “Submitted” or “Verified” until the backend reports those states.

For real-board assist, explain that the agent can fill the form and return control for the final human action. Show a clear handoff state and do not present the action as autonomous submission.

### 6.6 Applications — tracker and application detail

Provide a strong portfolio-like tracker while retaining the current server-backed list/detail behavior.

**Views:**

- Board view for scanning workflow stages.
- List view for dense search/filter/sort and precise status inspection.
- Timeline/activity view for a single application's chronology.

Use only actual backend statuses and human outcome events. The current tracker is paginated from the server; do not filter a loaded page locally and then present its partial count as the total. If a Kanban view needs all stages/counts at once, either use an existing complete query contract or define a narrow server-side addition with tests. Otherwise label the board as a view of the current server page or use server-backed stage filters.

Application detail should contain:

- Job/company identity and current status with plain-language explanation.
- Applied/submitted/verified timestamps only when present.
- Resume and cover-letter versions associated with the application.
- Ordered event history and actor (agent vs human) attribution.
- Evidence/confirmation and screenshots where the API exposes them safely.
- Next action and recovery path for blocked, uncertain, failed or unanswered states.
- A human outcome editor for interview/offer/rejected/withdrawn only where supported and always attributed to the authenticated human actor.

Do not infer interview/offer/rejection from email or job board content. Do not treat an agent status as a human outcome.

### 6.7 Profile & Documents

Keep résumé-derived facts distinct from user-confirmed application information.

**Profile areas:**

- Candidate identity/contact and parsed resume facts.
- Experience, education, skills, projects and certifications.
- Work preferences: locations, remote/hybrid/on-site, employment types and salary expectations where supported.
- Work authorization, sponsorship and citizenship as distinct questions; preserve the project's semantics.
- Application answers and their confirmation/source state.
- Model provider credentials/BYOK settings with secure handling; never render secret values after save.
- EEO data only in its isolated purpose; never use it to match or rank jobs.

**Document library:**

- Original uploads, tailored outputs and cover-letter outputs.
- File name/type/size, created time, associated job and current/in-use marker where available.
- Preview/download when the server has a safe authorized content endpoint; server-side file paths are not browser URLs.
- Pagination and clear empty/loading/error states.
- Do not delete or replace an original document as a side effect of tailoring.

Resume/Profile must share the same authoritative Work Preferences source. Do not create duplicate forms that write competing values.

### 6.8 Activity Center

Translate the audit trail into readable activity while preserving its exact underlying facts.

- Filters for all, agent, human, application and system/attention only when supported by actual records.
- Group related events into executions/workflows where a real workflow id exists.
- Use actual action/outcome/timestamp values returned by the audit API.
- Make blocked/denied/error events understandable and provide a route to the affected job/application when possible.
- Keep the detailed raw event data available for investigation, but progressively disclose it rather than making the default screen a log dump.
- State when the data was last read and that it refreshes on an interval. Do not label it “Live” unless the backend genuinely streams updates.

### 6.9 Operations & Administration

These are secondary technical surfaces; they must not dominate the candidate's main navigation.

**Operations:**

- Job corpus refresh action and honest queued/running/completed/failed state.
- Current and recent durable runs, run details, child embedding run if relevant, real counts and errors.
- Worker availability/health where returned.
- Explain when work is queued but no worker is running and show the documented recovery/start command where appropriate.
- Preserve run selection across navigation/reload using the existing derived backend-state behavior.

**Administration:**

- Platform-wide totals and worker/run oversight only for a server-authorized administrator.
- Never fetch cross-account data for a non-admin.
- Do not show private resumes, cover letters, emails or application payloads in a cross-tenant view.

## 7. Mobile and responsive experience

The attached reference contains a mobile companion view. Build a real responsive experience, not a scaled-down desktop screenshot.

Minimum viewport checks:

- Desktop: `1440 × 1000` and `1280 × 800`.
- Mobile: `390 × 844` and `360 × 800`.
- Tablet/intermediate widths: at least one width around `768–900px`.

Mobile principles:

- Keep the same ivory/forest identity and semantic color rules.
- Use a compact top bar and a bottom navigation with no more than five primary destinations; secondary destinations can live in a clearly labelled More/account menu.
- Dashboard priorities appear before metrics. Keep the featured job/application action reachable without a long scroll.
- Discover becomes a results-first list; open job detail in a full-height page or well-behaved sheet with a clear back path.
- Resume comparison becomes stacked or toggle-based. The user must still distinguish original and tailored copy and inspect individual changes; do not squeeze two desktop columns into a tiny phone.
- Review must keep unresolved questions and approval state legible. Primary actions must not cover form content or keyboard focus.
- Tracker cards must preserve job/company/status/next action. Avoid horizontal scrolling tables.
- Drawers, menus and dialogs must contain their own scroll and return focus correctly.
- Avoid sticky bottom actions that hide inputs, keyboard, focused elements or system safe areas.
- Touch targets should meet platform accessibility guidance, with sufficient separation.

## 8. Implementation workstreams and gates

Deliver the redesign in reviewable, testable phases. Work in the existing frontend repository and reuse its patterns. Follow §8A for mandatory skill loading, §8B for subagent delegation/integration, and §8C for the shadcn/Base UI component strategy.

### WS-UX-01 — Repository audit and design contract

**Tasks**

1. Check `git status`, branch, recent commits and uncommitted/untracked files. Do not overwrite or revert user work.
2. Read the current architecture/security instructions and relevant implementation docs.
3. Map every current route, screen, API call, status, state and test.
4. Identify stale documentation or UI assumptions by comparing them with current source/OpenAPI.
5. Capture baseline screenshots of current Home, Discover, Tailor, Review, Tracker, Profile, Activity and Operations at desktop and mobile sizes.
6. Produce a concise `docs/design/JOBPILOT-UX-01-AUDIT.md` and `docs/design/JOBPILOT-DESIGN-SYSTEM.md` (or extend authoritative existing docs; do not create competing authorities).

**Exit:** route/API map, visual baseline, existing feature inventory and a documented implementation plan exist. No behavior has been removed.

### WS-UX-02 — Design foundations and application shell

**Tasks**

1. Reconcile existing tokens to the approved reference; preserve the current palette unless contrast/accessibility testing proves a necessary adjustment.
2. Refine the sidebar, logo/brand lockup, account/profile affordances, active states, top-level content grid and responsive drawer/bottom navigation.
3. Establish shared typography, spacing, surfaces, borders, status badges, buttons, inputs, tables, empty/error/loading states and responsive rules.
4. Centralize status presentation so one backend state has one consistent label, tone, icon and explanation across Home, Review, Tracker and Activity.
5. Preserve route semantics, lazy-loaded screens and React Router view transitions.

**Exit:** shell and shared design system pass visual, responsive, keyboard and contrast checks.

### WS-UX-03 — Home dashboard reference implementation

Implement the Home direction in §6.1 first. The dashboard is the reference screen for component density, hierarchy, spacing and navigation.

**Gate:** validate the rendered dashboard at `1440 × 1000`, `1280 × 800`, `390 × 844` and `360 × 800`. Confirm that a user can identify the next action quickly, the screen is job/application-first, every metric is grounded, and graphs are omitted when not justified. Fix issues before applying the same system to the remaining screens.

### WS-UX-04 — Discover and job detail

Implement split-view discovery, filters, match rationale, evidence, job details, shortlist and handoff into tailoring. Verify empty results, source failures, degraded scoring, missing/unknown evidence, long job descriptions and direct job-detail links.

### WS-UX-05 — Resume Studio and cover-letter workflow

Implement side-by-side/stacked content diff, keyword coverage, ATS/style/factuality panels, job research and editable cover letter. Audit and, if required, design the server-backed revision model described in §6.4B. Preserve original files and render reports. Add tests for incorrect mapping, unsupported claims, rejected/edited changes, reload persistence and validation after edits.

### WS-UX-06 — Review and approval

Implement the packet summary, board questions in source order, unresolved answer states, version identity and human decision. Confirm that the exact prepared payload shown is the payload approved. Exercise accepted `202` runs, reloading, duplicate actions, expired approvals, blocked human review and uncertain submission. Keep real-board assist and fake ATS paths distinct.

### WS-UX-07 — Application tracker and detail

Implement board/list/timeline presentation using real server-side pagination/filter semantics. Add useful detail context, ordered event history and evidence. Do not invent complete stage counts or outcomes from a partial page.

### WS-UX-08 — Profile, documents, activity and operations

Unify candidate facts and confirmed application profile; improve document library; refine activity feed; make Operations/Administration secondary while preserving all their current functions and server authorization.

### WS-UX-09 — Mobile, accessibility, hardening and final polish

Complete responsive layouts, keyboard/focus flows, screen-reader status announcements, empty/loading/error/disabled states, reduced motion, overflow handling and visual polish. Run the full test/build suite and end-to-end journeys. Capture committed screenshots at the required viewports.

**Completion gate:** all screen workstreams above pass their acceptance tests and the end-to-end journey works from first resume/profile setup through job discovery, tailoring, approval/handoff and tracking.


## 8A. Mandatory skill strategy — load and use repository skills

The repository contains dedicated design, frontend, accessibility, and agent-engineering skills under `.claude/skills/` and `.agents/skills/`. Do not assume a skill is active merely because its directory exists. Before each relevant workstream, read the applicable `SKILL.md` and follow its instructions. Use the equivalent skill path supported by the active coding agent (Claude, Cursor, ZCode, Codex, etc.); do not duplicate skill content into source files.

### Required design and UX skills

Load these for the redesign, in the order that best fits the work:

1. **`impeccable`** — primary design director workflow. Use `context`/`shape`/`critique`/`audit`/`polish`/`harden`/`adapt` as appropriate. Treat JobPilot as an Operate product: task completion, clarity and precision outrank decorative effects. Inspect existing tokens and rendered UI before changing them. Follow its required craft-floor and relevant reference instructions before UI edits.
2. **`better-ui`** — component surface quality, optical alignment, icon consistency, restrained shadows, transitions, press feedback, reduced motion and performance.
3. **`better-layout`** — density, spacing rhythm, responsive composition, navigation and breakpoint behavior.
4. **`better-typography`** — heading/body hierarchy, line lengths, wrapping, tabular numerals and type consistency.
5. **`better-colors`** — token semantics, contrast and light/dark state consistency.
6. **`better-accessibility`** — keyboard navigation, focus, labels, target size, status announcements, reduced motion and WCAG 2.2 AA.
7. **`ui-ux-pro-max`** — use its local search data for product-appropriate dashboard patterns, design-system choices, UX rules and React/Tailwind implementation guidance. Search the specific domains needed; do not accept generic output that conflicts with JobPilot's established visual identity.
8. **`frontend-design`** and **`frontend-ui-engineering`** — high-quality React composition and implementation. Use them to avoid generic template output and to keep components maintainable.
9. **`critique`**, **`audit`** and **`polish`** — run iterative design review, technical/accessibility review and final refinement. A passing screenshot and working interaction are required, not just a code review.
10. **`clarify`**, **`harden`** and **`adapt`** — use for product language, error/empty/loading states, edge cases and responsive behavior.

### Required engineering/domain skills

- **`shadcn`** — use when selecting, composing or extending the existing shadcn/Base UI component layer. Check the installed component source and API before adding or replacing a component.
- **`state-machine`** — use when modeling application, run, approval, handoff and verification states. The backend state machine remains authoritative.
- **`agent-architecture`** and **`agent-evaluation`** — use when changing agent workflow presentation, tool orchestration or evaluation behavior. Do not change backend agent behavior merely to satisfy a screen design.
- **`browser-automation`** — use for browser-driven visual verification and E2E interaction where available; never use it to bypass CAPTCHA/MFA or the human-submit boundary.
- **`vercel-react-best-practices`** — use for React performance, component boundaries, async data and rendering practices where relevant.

### Skill execution rules

- Read each skill's `SKILL.md` before invoking it. Follow references that the skill marks mandatory; do not load every reference file indiscriminately.
- Use the exact skill's supported command/script if it provides one. Do not merely state that a skill was used.
- If a skill tool/script is unavailable in the current agent environment, state that limitation and apply the documented principles manually. Never claim a tool or skill ran when it did not.
- Resolve conflicting skill advice in this order: user-approved screenshot and product constraints → repository instructions and current implementation contracts → accessibility/security requirements → skill recommendations → personal stylistic preference.
- Do not let a marketing/portfolio-oriented skill impose cinematic hero sections, giant headings, pinned scroll, GSAP or decorative animation on the authenticated operator console. Those techniques are only appropriate where the user explicitly wants them and they improve the task.

## 8B. Subagent orchestration — parallelize bounded work, integrate centrally

Use subagents when the coding environment supports them. The lead agent remains accountable for architecture, integration, safety and final acceptance. Do not delegate the entire redesign to multiple agents editing the same files.

### Recommended subagents

**Subagent A — UX / Product Audit**
- Inspect current routes, user journeys, screen states and feature parity.
- Read the applicable Impeccable and UI/UX Pro Max skills.
- Produce an issue inventory, route-to-capability map, screen acceptance criteria and proposed information architecture.
- Do not edit application code.

**Subagent B — Design System / Shell**
- Audit current tokens, typography, sidebar, navigation, shared controls and responsive shell.
- Read `impeccable`, `better-ui`, `better-layout`, `better-typography`, `better-colors`, `better-accessibility` and `shadcn` skills.
- Implement or propose shared foundations and reusable primitives only after the lead agent approves the design contract.
- Own the shell/shared-component files; coordinate file ownership before edits.

**Subagent C — Discover / Job Detail**
- Redesign the job search, result list, selected-job detail, match explanation and shortlist/prepare actions.
- Preserve real API semantics, server pagination and unknown/missing evidence states.
- Own Discover/job-detail screen files and their tests.

**Subagent D — Resume Studio / Cover Letter**
- Audit the existing tailoring, ATS, factuality, render and cover-letter contracts.
- Design and implement original-versus-tailored diff, keyword evidence mapping, editable cover-letter experience and revision-aware validation.
- Read `resume-intelligence`, `better-ui`, `better-accessibility`, `state-machine` and relevant `impeccable` references.
- Do not invent backend endpoints or claim persistent accept/reject behavior without a server-backed revision contract.
- Own Resume Studio/tailor files and focused tests; propose backend additions separately for lead approval.

**Subagent E — Review / Applications / Activity**
- Redesign human approval, application tracker/detail, evidence, activity and operations views.
- Preserve exact prepared-payload approval, durable run states, server-side filtering and truthful status semantics.
- Read `state-machine`, `agent-architecture`, `agent-evaluation`, `better-accessibility` and `impeccable` references.
- Own review/tracker/activity/operations screen files and tests.

**Subagent F — Mobile / Accessibility / Visual QA**
- Audit every screen at mobile breakpoints, keyboard/screen-reader flows, contrast, touch targets, overflow and reduced motion.
- Read `better-accessibility`, `better-layout`, `accessibility-audit`, `accessibility-inspect`, `accessibility-scan`, `adapt` and `browser-automation` skills.
- Produce screenshots, defects and reproduction steps. Fix only explicitly assigned isolated issues to avoid conflicting edits.

### Orchestration and integration protocol

1. Lead agent performs the initial repository audit and writes the shared design contract before parallel implementation.
2. Delegate bounded work with explicit file ownership, existing API contracts, design tokens, non-negotiable safety rules, required tests and expected outputs.
3. Parallelize analysis first. Parallel code edits are allowed only where file ownership is disjoint and shared interfaces are agreed.
4. No subagent may independently change routes, global tokens, shared status semantics, API types or package dependencies without lead approval.
5. Each subagent returns: files changed, behavior preserved/added, API assumptions, tests run and results, screenshots, unresolved issues and any required backend contract changes.
6. Lead agent reviews every diff, resolves design inconsistencies, integrates navigation/shared components, checks imports and route compatibility, then runs the full test/build suite.
7. If subagents are unavailable, the lead agent executes the same workstreams sequentially and records that subagent execution was unavailable. Do not fabricate parallel work.
8. Never ask multiple agents to edit `index.css`, `routes.tsx`, the same screen, or shared status components simultaneously.

## 8C. Component strategy — shadcn/Base UI as foundation, not visual template

**Decision: retain the existing shadcn-style + Base UI component foundation. Do not migrate component libraries as part of this redesign.** The current frontend already depends on Base UI, Tailwind 4 and shadcn conventions; build on the installed stack and verify `components.json`, `src/components/ui/**` and installed package versions before implementation.

Use existing or shadcn-generated primitives for accessible behavior and predictable APIs, including:

- Button, input, textarea, select/combobox, checkbox, radio, switch and form field.
- Tabs, tooltip, popover, dropdown menu, command/search palette and navigation menu.
- Dialog, alert dialog, sheet/drawer, accordion, collapsible and separator.
- Table, badge, skeleton, progress, avatar and toast/sonner if already installed.

Compose product-specific components on top of those primitives:

- JobPilot sidebar and navigation groups.
- Match score and evidence breakdown.
- Job result row and selected-job detail panel.
- Application status/pipeline stage and next-action row.
- Agent activity item and execution timeline.
- Resume diff block, change-review item and keyword evidence row.
- ATS/factuality/format report panels.
- Application packet checklist and approval boundary panel.
- Responsive mobile navigation and mobile application review card.

### Styling and customization rules

- Do not accept stock shadcn colors, radius, shadows, spacing or default card-heavy page templates as the finished design.
- Style primitives with JobPilot's semantic CSS variables and existing tokens: ivory, paper, forest, lime, terracotta, sage, ink and warm border.
- Keep semantic colors consistent: lime for agent-originated work, terracotta for human decisions/attention, forest for primary actions and navigation.
- Use Bricolage Grotesque for display/heading roles and Geist for interface/body roles, matching the current source.
- Preserve the selected mockup's forest sidebar, warm surfaces, compact dense job cards, fine borders, restrained elevation and strong content hierarchy.
- Prefer composition built from a small number of meaningful regions over nesting generic Card components everywhere.
- Use CSS Grid/Flexbox and responsive layout deliberately. Do not turn desktop split views into clipped horizontal scrolling on mobile.
- Use Lucide React consistently; no emoji as interface icons.
- Keep accessible semantics, focus states, keyboard operation, reduced motion and appropriate touch targets. Do not trade accessibility for pixel resemblance.
- Extend existing primitives before introducing a second design system. Add a new component dependency only after a documented gap and lead approval.

### When a custom component is justified

A custom component is appropriate when the approved design requires a distinctive composition or interaction that a primitive cannot express cleanly (for example, a line-level diff editor, match-evidence visualization or multi-stage application packet). It should still use accessible Base UI/shadcn primitives for its controls and should expose a small, typed API with tests.

**Acceptance:** a reviewer should recognize the attached JobPilot mockup in the rendered app. It must not look like an unmodified shadcn starter dashboard. The component library is the implementation substrate; the mockup is the design authority.


## 9. Resume Studio technical design — implementation constraints

The resume-diff experience is a key product feature, so do not implement it as a static visual-only panel.

### 9.1 Source-of-truth model

- Source document and parsed profile are immutable inputs.
- Tailoring result is a generated proposal, not an accepted final resume by default.
- Candidate edits/acceptance create a new revision tied to the source document, profile and job.
- Export is generated from the accepted revision, and references that revision id.
- Application preparation references an exact resume revision and exact cover-letter revision.
- Approval binds to the exact persisted prepared payload and selected document revisions.

### 9.2 Change model

Use stable identities rather than relying on array order alone. Preserve the current renderer's safety rule: experience maps by exact company/title identity and bullets by their known ordinal position. Do not fuzzy-match two different roles or projects. If a section or paragraph cannot be paired confidently, mark it “not compared” or “manual review required”; do not invent a diff.

A change review must support:

- Inspect original and proposed wording.
- Understand why it changed and which job requirement it addresses.
- View the candidate fact(s) that support the change.
- Accept, edit or reject (if persistence has been implemented).
- Undo/revert before saving a final revision.
- Re-run factuality, style and ATS checks on the selected revision.

### 9.3 Keyword model

Use the real `AtsReport.keyword_coverage` data and requirement extraction. Required and preferred terms must remain distinct. Never promote a missing/unverified term into supported candidate evidence just because the model suggests it. A candidate may add a new fact only by explicitly entering/confirming it in the appropriate profile workflow; it must then pass the factuality rules and be traceable.

### 9.4 Cover letter model

Reuse the selected job/profile/research context. Keep text editable, versioned and evidence-aware. A cover-letter edit must not silently alter the resume; a resume edit must not silently alter a previously approved cover letter. If the model is unavailable or a BYOK key is misconfigured, show the specific actionable error from the API rather than an endless spinner or generic failure.

### 9.5 Required tests

- Correct diff pairing for multiple roles, repeated bullets, projects and reordered sections.
- Unmatched paragraphs and unsupported formatting are surfaced, not silently rewritten.
- Original source file remains unchanged.
- Accepted/edited/rejected proposal state persists if interactive change review is delivered.
- Every saved revision is tied to its source and job.
- Factuality catches unsupported skills, titles, dates, companies, years and achievements after edits.
- ATS keyword coverage changes deterministically with the selected revision.
- Cover-letter revision and resume revision remain independently versioned.
- Application packet and approval refer to the exact selected versions.

## 10. Verification standard

A workstream is not complete because the page renders or a unit test passes. Each acceptance criterion must have a test that would fail if the behavior regressed, plus browser evidence for each visual screen.

### 10.1 Frontend checks

Run from `/frontend` using the exact scripts in `package.json`:

- `npm run typecheck`
- `npm run lint`
- `npm run test`
- `npm run build`
- `npm run e2e` (after installing/confirming the configured Playwright browser)
- `npm run format:check`

Do not change scripts solely to make the project appear green. Record any known baseline/environment failures separately.

### 10.2 Backend checks if backend code changes

Follow `AGENTS.md` and the repository's Windows environment instructions. Run targeted backend tests for every changed contract, plus tenant-isolation, security, documentation accuracy, OpenAPI and relevant full suites. Do not change business logic to accommodate a visual design. Every new endpoint/schema/migration must be additive where possible, documented, tested and reflected in the API docs.

### 10.3 Visual and interaction checks

Use a real browser against the running frontend and backend. Capture and inspect:

| Surface | Desktop | Mobile |
|---|---:|---:|
| Home | 1440×1000, 1280×800 | 390×844, 360×800 |
| Discover + job detail | 1440×1000, 1280×800 | 390×844, 360×800 |
| Resume Studio + diff | 1440×1000, 1280×800 | 390×844, 360×800 |
| Cover Letter Studio | 1440×1000 | 390×844 |
| Review / approval | 1440×1000, 1280×800 | 390×844, 360×800 |
| Tracker / application detail | 1440×1000, 1280×800 | 390×844, 360×800 |
| Profile / documents | 1440×1000 | 390×844 |
| Activity / Operations | 1440×1000 | 390×844 where useful |

Inspect real content and these states: initial load, populated, empty, pending, error, degraded source, missing question, blocked challenge, durable run in progress, approval accepted/queued, submitted, verified, uncertain and failed. Ensure no clipped text, overlap, sideways page scrolling, inaccessible modal/drawer, hidden keyboard focus or false success state.

### 10.4 End-to-end journeys

At minimum, test these full journeys against the real backend or an accurately contract-matched MSW fixture:

1. New user → upload resume → parse profile → resolve profile details.
2. Discover stored jobs → filter/search → inspect match explanation → shortlist/select job.
3. Tailor resume → inspect diff → review keyword coverage → factuality/style/ATS checks → save/export correct revision.
4. Generate/edit cover letter → save exact revision.
5. Prepare application → inspect exact payload and employer questions → resolve blockers → approve/reject.
6. Approval returns `202` → durable run persists after reload → observe actual progress/result.
7. Real-board assist → fill form → hand back to human before final submit.
8. Tracker → inspect event history/evidence → record a human outcome.
9. Worker unavailable / job source error / model key unavailable → useful error and recovery path.
10. User A cannot view or mutate User B's documents, profile, applications, activity or evidence.

## 11. Risk register

| Risk | Why it matters | Required mitigation |
|---|---|---|
| Stale docs or route assumptions | Earlier workstream docs can lag current code | Re-audit current branch, code, OpenAPI and running behavior before planning changes |
| UI-only accept/reject diff | Changes would vanish on reload and approval could use a different document | Add a server-backed revision contract or ship a clearly labelled read-only diff first |
| Unsafe diff pairing | Wrong paragraph could be rewritten in a real resume | Stable identity matching; explicit “not compared” state where uncertain |
| Keyword stuffing / hallucinated facts | Damages candidate trust and can misrepresent experience | Evidence-linked suggestions; deterministic factuality after every revision |
| Fake analytics | Gives the candidate misleading career signals | Only calculate metrics from complete, actual, timestamped records and state the denominator/window |
| Partial pagination presented as total | Counts and pipeline distributions would be false | Use server totals/filters or label the visible subset accurately |
| Approval confused with submission | Could mislead the candidate about an irreversible action | Distinct queued/running/submitted/verified/uncertain states and exact payload binding |
| Real-board auto-submit creep | Violates the product safety model | Keep final submission human-controlled; never add bypass controls |
| Polling overload | Can consume the API request budget and cause broad rerenders | Reuse polling helpers; avoid aggressive intervals and screen-wide ticking state |
| Visual redesign breaks existing flows | The app has extensive safety/edge-case behavior | Preserve current behaviors, tests and direct routes; add tests before removing old patterns |
| Mobile squeezed desktop UI | Makes the document diff and approval unsafe to use | Design stacked/mobile-specific interactions; test 360px and 390px widths |

## 12. What must not change

Unless a specific, tested backend addition is necessary for the approved UX feature, do not change:

- The existing React/Vite/TypeScript application architecture or move the frontend to another framework.
- Python business logic, LangGraph orchestration, matching weights or source adapters.
- Candidate factuality and style policies.
- User ownership, authorization, BYOK, PII masking, credential and security boundaries.
- Durable queue semantics, idempotency, retry and recovery rules.
- Mandatory human approval and real-board assist-mode boundaries.
- Evidence requirements and the distinction between submitted and verified.
- Existing route compatibility, direct links, lazy loading and existing core workflows.
- Existing tests or known project guardrails merely to simplify the redesign.

This workstream should make the capabilities easier to understand and use, not weaken the rules that make JobPilot trustworthy.

## 13. Deliverables

Produce all of the following:

1. A repository audit and route/API/feature map.
2. A concise design-system specification using the approved screenshot and existing tokens.
3. A redesigned shared application shell and responsive navigation.
4. Updated Home, Discover, job detail, Resume Studio, Cover Letter Studio, Review, Tracker, Profile/Documents, Activity and Operations/Admin surfaces.
5. A usable desktop and mobile experience, not static mockups alone.
6. A real resume/cover-letter change-review and keyword workflow, or a clearly documented boundary between the shipped read-only diff and the server-backed revision follow-up if that scope cannot safely be completed.
7. Updated component/unit/integration/E2E tests.
8. Browser screenshots at the required viewports and states, inspected for actual rendering defects.
9. A final implementation report listing files changed, API/backend changes, tests run and results, screenshots captured, known limitations and follow-up work.

## 14. Definition of done

The workstream is done only when:

- The authenticated workspace looks and feels like the attached JobPilot reference.
- The Home screen remains job-search/application-first and uses no decorative or fabricated analytics.
- Every primary workflow is reachable and coherent from navigation and deep links.
- Discover explains why a role matched and what evidence is missing.
- Resume Studio provides a readable source-versus-tailored diff, keyword coverage, factuality, ATS and style reports, and accurate document export status.
- Cover letters are editable, truthful and versioned consistently with the selected job.
- Review shows the exact payload and preserves human approval.
- Tracker states, history, evidence and human outcomes are honest and attributable.
- Activity and Operations show the actual server state and do not pretend to be real-time when they are polling.
- Mobile users can complete the same core tasks without horizontal page scrolling or hidden controls.
- Existing safety, tenant isolation, security and regression tests remain green.
- Frontend typecheck, lint, unit tests, build and agreed E2E tests pass.
- Required browser screenshots have been inspected and any visible defects fixed.

**Do not declare completion based only on code generation or test output. The running application must be driven and visually inspected.**

---

## Suggested first message to the implementation agent

> Read `JOBPILOT-UX-REDESIGN-AGENT-PROMPT.md`, `AGENTS.md`, current architecture/security docs, and the existing frontend/backend source before editing. Treat the attached JobPilot screenshot as the approved visual reference and `REACT-MIGRATION-PLAN.md` as a structure/rigor reference only. Start with the repository audit, working-tree check, route/API/status map and baseline browser screenshots. Then implement the workstreams in order, beginning with the shared shell and job-first dashboard. Preserve every backend safety, factuality, ownership, approval, evidence and real-board handoff invariant. Do not invent charts, metrics, states, API routes or candidate facts. Complete the implementation, tests and browser verification; report exact evidence and any incomplete scope.
