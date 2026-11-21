# WS-46 — Profile documents pagination + Account & Security screen (BYOK move)

Status: **Delivered 2026-11-21** — two commits; Profile's library pages, the model key has a screen of its own reached from the account menu, and the audit instrument's stale tab labels are repaired.

## What shipped

| Commit | Feature |
|---|---|
| `36a3efc` | an account and security screen hosts the model key, reached from the account menu |
| `1846713` | the profile library pages and model credentials move to account and security |

**Evidence.** `screens/account-screen.test.tsx` (6, new), `screens/profile-screen.test.tsx` (9),
`components/profile/model-credentials-card.test.tsx` (12),
`components/profile/application-answers-card.test.tsx` (13),
`components/profile/work-eligibility-countries.test.tsx` (5),
`components/profile/work-preferences-card.test.tsx` (5) — 50 tests green in the agent's own pass;
the full FE suite is green at **407 tests / 49 files**.

**Reader's notes.**

- **No Sessions tab.** The API has no sessions surface, so a tab would have to invent device names
  and last-active times. The screen ships the three surfaces the backend can honestly serve:
  Profile, Model credentials, Privacy.
- **The identity card is genuinely editable** because `PATCH /api/auth/me` was verified to exist
  (WS-14) — name, email and password, with the backend's own "your other sessions are signed out"
  side effect stated in the copy.
- The audit script's `TAB_STEPS.profile` was **stale**: it asked for "Preferences"/"Settings",
  labels the Profile screen no longer renders, so the sweep photographed the first tab and reported
  a clean surface it had never visited. Repaired in `d4e8ea5`, along with the `/app/account`
  surface, the design's 1024×1000 frame and the discovered questions surface.

## Goal

The profile's document library renders every résumé in one unpaged list, and the "Your model" BYOK card sits stranded at the bottom of Profile behind the data guard — an inaccessible location. The design answers both: a paginated documents list, and a dedicated **Account & Security** screen ("Your workspace, your rules.") reached from the account menu, whose Profile's privacy card states verbatim: *"Model credentials and account controls remain in your account menu."*

## Design references (primary)

- `docs/design/Images-figma/Job Pilot/15 · Account & security · 1440.png` — tabs **Profile | Model credentials | Sessions | Privacy**; "Your account" card (Name/Email, Save changes / Change password); "Your model key" card ("No key configured" chip, "Store, replace, or remove your key. Only a masked state is returned after saving.", Provider API key masked input, Save key / Test connection, "Testing makes a separate, billable provider call. It does not run automatically when saving."); "Privacy & deletion" panel.
- `docs/design/Images-figma/Job Pilot/06 · Profile & documents · 1440.png` — Documents tab ("Your original stays original.", ORIGINAL/TAILORED chips, source-facts panel) + "Private by design." card with the account-menu line and "Privacy & account →".
- Zoom detail: `docs/design/Images-figma/15.jpg`, `16.jpg`.

**Scope ruling:** the design draws a Sessions tab; the backend has no sessions surface — it is **not built and not mocked**. The screen ships the tabs the backend actually supports (Profile, Model credentials, Privacy) with honest content.

## Current state

- `frontend/src/screens/profile-screen.tsx` — Documents tab renders `documents.data.documents` inline, unpaged; "Your model" section at the bottom outside the tabs and the data guard, rendering `ModelCredentialsCard`.
- `frontend/src/components/documents/document-picker.tsx::DocumentList` — the paged precedent: `DOCUMENTS_PER_PAGE = 5` + the shared `Pagination` component (client-side; renders nothing when total ≤ pageSize).
- `frontend/src/components/profile/model-credentials-card.tsx` — provider select, model, masked key, base URL; endpoints `getLlmCredentials/putLlmCredentials/deleteLlmCredentials/testLlmCredentials`.
- `frontend/src/components/layout/account-menu.tsx` — theme/motion/sign-out; no account link. `frontend/src/routes.tsx` — no `/app/account`.

## Concrete tasks

1. **Profile documents pagination** — reuse the `Pagination` pattern (per-page 5) on the profile's inline library list. Commit: `feat: the profile document library pages like the rest of the console (ws-46)`.
2. **Account & Security screen** — new `frontend/src/screens/account-screen.tsx` at `/app/account` (registered in `routes.tsx`): "Your workspace, your rules." header; Model credentials tab (restyled `model-credentials-card.tsx` to the design's "Your model key" card, keeping the existing API surface); account identity card (name/email **editable only if** a fastapi-users PATCH endpoint actually exists — verified at implementation time; read-only otherwise, never fake); "Privacy & deletion" panel with the EEO-separate copy. Commits: `feat: an account and security screen hosts the model key (ws-46)`, `feat: the account menu reaches account and security (ws-46)`.
3. **BYOK move** — remove the "Your model" section from Profile's bottom; Profile's "Private by design." card gains the design line *"Model credentials and account controls remain in your account menu."* + "Privacy & account →" link to `/app/account`. Commit: `refactor: model credentials live on account and security, not at profile's foot (ws-46)`.
4. **Audit script** — fix `frontend/scripts/ws41-audit.mjs` `TAB_STEPS.profile` (references tabs that no longer exist) and add the design's exact frames (1440×1000, 1024×1000, 768×1024, 390×844) to the sweep. Commit: `fix: the audit sweeps the current profile tabs at the design's frames (ws-46)`.

## Acceptance criteria

- Profile documents list pages at 5 per page with the shared pager; totals honest.
- `/app/account` matches `15 · Account & security · 1440` at all four frames (tabs wrap at 768 per the design); the model key works exactly as before (save/test/delete against `/api/llm/credentials*`).
- Profile no longer renders "Your model"; its privacy card links to the account screen; the account menu links there too.
- The audit's profile tab steps pass and the new frames are swept.

## Tests

- `frontend/src/screens/profile-screen.test.tsx` (pagination, "Your model" absence, privacy link), new `account-screen.test.tsx`, `model-credentials-card.test.tsx` updates.
- Manual: four frames vs `15 · Account & security`.

## New dependencies

None.
