# WS-40 (WS-UX-08) · UX redesign: Profile & Documents, Activity, Operations, Administration

Status: **Planned — not started** · Source directive:
[JOBPILOT-UX-REDESIGN-AGENT-PROMPT-v2.md](../JOBPILOT-UX-REDESIGN-AGENT-PROMPT-v2.md) §6.7, §6.8, §6.9, §8 (WS-UX-08) ·
Depends on: WS-34 (primitives + nav regrouping), WS-33 audit ·
Visual authority: [Redesign Image.png](../Redesign%20Image.png) (panels 6 and 7)

> **Where this starts.** Four existing screens: `frontend/src/screens/profile-screen.tsx`
> (test: `profile-screen.test.tsx`) — the candidate application profile with the
> question-gap surface and the per-country work-eligibility picker (WS-20/25b/25c
> lineage); `frontend/src/screens/resume-screen.tsx` (test: `resume-screen.test.tsx`) —
> the résumé library and parsed facts (WS-19 lineage); `frontend/src/screens/
> activity-screen.tsx` (tests: `activity-screen.test.tsx`, `activity-screen-polling.test.tsx`)
> — audit events with grouped executions; `frontend/src/screens/operations-screen.tsx` +
> `admin-screen.tsx` (tests incl. polling) — corpus refresh and durable runs with the
> WS-18 recovery surface. The reference panel 6 shows a tabbed profile; panel 7 shows the
> activity center with All/Agent/Applications/System filters.

## Non-negotiable invariants for this workstream

Résumé-derived facts and user-confirmed profile facts stay distinct. Work authorization,
sponsorship and citizenship stay distinct questions; `may_work_in`'s three-valued
semantics (`None` = not stated → the question goes to a human) are preserved; EEO data
renders only in its isolated place and never influences anything else. Résumé/Profile
share **one** Work Preferences source (WS-21's single shared editor) — no duplicate
competing forms. BYOK credential values are never rendered after save (write-only
fields). Model-unavailable states show the specific API error. Activity filters exist
only where the audit API actually supports them; polling keeps `ACTIVITY_POLL_MS = 30_000`
and is labelled as polling ("updated every 30 s"), never "Live". Operations explains
queued-but-no-worker honestly, with the documented recovery/start path. Administration is
server-authorized only; a non-admin never fetches cross-account data, and no cross-tenant
view shows private résumés, cover letters, emails or application payloads. Original
documents are never deleted or replaced as a side effect.

## File-ownership boundary (exclusive)

`frontend/src/screens/profile-screen.tsx`, `frontend/src/screens/resume-screen.tsx`,
`frontend/src/screens/activity-screen.tsx`, `frontend/src/screens/operations-screen.tsx`,
`frontend/src/screens/admin-screen.tsx`, their existing tests, and **new** screen-local
components under `frontend/src/screens/facts/**`. Consumes WS-34 primitives. `lib/api/**`
read-only.

## 1 — Task 1: Profile & Documents as one conceptual destination

- [ ] Profile areas per master prompt §6.7: identity/contact + parsed résumé facts;
      experience/education/skills/projects/certifications; work preferences (locations,
      remote/hybrid/on-site, employment types, salary where supported); the distinct
      authorization/sponsorship/citizenship questions with the existing country picker;
      application answers with confirmation/source state; BYOK credentials with secure
      handling; EEO isolated. Tabbed composition per reference panel 6, "Profile
      Complete"-style completeness only from real coverage signals (e.g. the measured
      question gaps), never a fabricated percentage.
- [ ] Document library: original uploads, tailored outputs, cover-letter outputs; file
      name/type/size, created time, associated job, current/in-use marker where
      available; preview/download via the safe authorized endpoints only; pagination +
      clear empty/loading/error states.
- [ ] Keep `/app/profile` and `/app/resume` routes working (nav labels may consolidate
      them as "Profile & Documents" — route compatibility is preserved, per WS-34's map).

## 2 — Task 2: Activity Center

- [ ] Reference panel 7's composition: filter chips (All/Agent/Applications/System —
      only where the audit API supports each), grouped executions where a real workflow
      id exists, real action/outcome/timestamp values, blocked/denied/error events
      understandable with routes to the affected job/application, raw event data behind
      progressive disclosure. "Mark all as read" from the reference is **not rendered**
      unless a real backend contract exists.
- [ ] Last-read timestamp + interval stated truthfully.

## 3 — Task 3: Operations & Administration as the System area

- [ ] Operations: corpus refresh action with honest queued/running/completed/failed
      state; current + recent durable runs with real counts and errors (child embedding
      run included); worker availability/health where returned; the queued-but-no-worker
      explanation with the documented recovery command; run selection preserved across
      reload via the existing derived backend-state behavior.
- [ ] Administration: platform totals + worker/run oversight for a server-authorized
      administrator only; the UI hides nothing the server enforces and shows nothing the
      server would refuse.

## 4 — Task 4: tests and verification

- [ ] Extend the four screens' tests: single-source work preferences (no second writer);
      three-valued eligibility rendering; EEO isolation; BYOK write-only rendering;
      activity filters map to real API params; polling interval unchanged; operations
      no-worker state; admin gate renders from server authorization.
- [ ] Browser-verify at 1440×1000 and 390×844 (assigned ports, real backend): tabs,
      library rows, activity feed, operations panels; screenshots into
      `docs/design/ws40-facts/`.

## Acceptance

- Profile/Documents reads as reference panel 6, Activity as panel 7, with Operations/
  Administration demoted to the System group (per WS-34) but fully functional.
- All tests green; ownership, masking, and polling invariants preserved.

## Tests

`npm run test -- src/screens/profile-screen.test.tsx src/screens/resume-screen.test.tsx
src/screens/activity-screen.test.tsx src/screens/operations-screen.test.tsx
src/screens/admin-screen.test.tsx` plus screen-local additions; full suite at the lead's
integration gate.
