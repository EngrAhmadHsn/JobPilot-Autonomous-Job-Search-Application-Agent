# WS-08 · Browser Automation Depth

Status: **Not started** · Milestone: **M4** · Depends on: [06](06-security-preconditions.md) (hard gate) · Blocks: M5 live pilot

## Goal

Harden the runtime browser layer per the plan's browser-automation skill rules (semantic
locators, verify every action, isolated contexts, safe failure) and build the **fake-ATS test
suite** the plan mandates (§32) before any real-world contact: multi-page forms, dropdowns,
checkboxes, unknown questions, validation errors, CAPTCHA/MFA variants.

## Current state

- `src/applications/fake_ats_adapter.py` — real Playwright flow against a single static page: `#candidate-name` / `#email` / `#phone` CSS locators, optional file upload, click submit, confirmation-text verification. No fake-ATS *server* exists in the repo (tests need one served over HTTP).
- No multi-page handling, no question typing, no unknown-question pause (plan §24), no unexpected-navigation guard (WS-06 adds the guard primitive), no dropdown/checkbox support.
- Playwright MCP (development-time) stays the inspection tool; the runtime layer is this adapter (dev-time/runtime split per plan §36).

## Concrete tasks

### 1. Fake ATS server — `tests/fixtures/fake_ats/` (new)

A small FastAPI app (run in-process with `uvicorn`/`TestServer` on an ephemeral port; base URL passed to the adapter). Page variants under `/`:

| Route | Variant | What it exercises |
|---|---|---|
| `/basic` | current single-page form (kept as-is) | regression baseline |
| `/multipage` | 3-step form (step 1 personal, step 2 experience questions, step 3 review+submit) | multi-page flow, state carried across pages |
| `/widgets` | dropdowns (country, years-of-experience), checkboxes (work authorization), radio (work mode: remote/hybrid/onsite) | widget mapping |
| `/unknown` | one standard question + one **unknown** question ("Have you served on a submarine?") with no profile evidence | unknown-question pause (plan §24) |
| `/validation` | rejects empty required field with inline error on submit | error detection + retry-once-then-fail |
| `/captcha` | renders a visible "reCAPTCHA" marker widget | CAPTCHA stop (WS-06 §8) |
| `/upload-required` | file input marked required | upload verification |
| `/submitted` / `/error` | confirmation and failure confirmation pages | verification both ways |

Each page serves semantic HTML with proper `<label for>` / roles — the adapter must be able to rely on **accessibility locators only**.

### 2. Adapter hardening — `src/applications/fake_ats_adapter.py`

- **Semantic locators**: replace `#candidate-name`-style selectors with `page.get_by_label("Full name")`, `get_by_role("button", name="Submit")` etc. CSS selectors remain only as the documented exception for the file input.
- **Form walker**: enumerate visible labeled fields (`page.locator("label")` → input mapping); classify each into `{known, mappable, unknown}` using a field map from `PreparedApplication.prepared_fields` + profile facts.
- **Unknown-question pause (plan §24)**: unknown question → do **not** guess, do **not** leave blank silently: capture question text + page screenshot → `status="needs_human"`, `metadata={"questions": [...]}`; workflow surfaces it as a final result requiring human input. "UNKNOWN" is a valid answer; false confidence is not.
- **Widget support**: select/checkbox/radio fill helpers driven by the field map (values validated against profile facts before typing).
- **Multi-page**: loop pages until a submit is reached; per-page `assert_navigation_allowed(page.url)` (WS-06 guard) + unknown-field scan per page.
- **Validation errors**: after submit, detect inline `[role=alert]`/`.error` elements → one remediation retry with prepared fields → else `status="form_error"` with the messages captured as evidence.
- **Session isolation (SEC-07)**: per-run fresh `browser.new_context()` (already close to true — make it explicit and tested: two sequential runs must not share cookies/storage); context closed in `finally` (already present).
- Evidence: WS-06's screenshot/trace wiring exercised here on every variant.

### 3. Application-form contract — `src/applications/form.py` (new)

```python
class FormQuestion(BaseModel):
    label: str
    kind: str          # text | select | checkbox | radio | file | textarea
    required: bool
    options: list[str] = []
class FormPlan(BaseModel):
    questions: list[FormQuestion]
    answers: dict[str, str]        # only answered, only profile-grounded
    unresolved: list[str]          # unknown question labels
```

`build_form_plan(page) -> FormPlan` is a pure-ish function over the accessibility tree — used by the walker and directly unit-testable from saved page snapshots. `answer_question(question, profile)` implements the §24 rule: answer only when the profile contains evidence; else `unresolved`.

### 4. Scope boundary

- **No live-ATS adapter work in this workstream.** Real-site support is an M5-pilot decision taken only after 06 + 08 acceptance; the `GenericBrowserAdapter` from plan Phase 2 milestone 2b starts from `FormPlan` + the variant suite, not from a live site.
- Browser Use remains optional and non-blocking (plan §13); if evaluated later, it consumes the same `FormPlan` contract.

## Acceptance criteria

- [ ] Every fake-ATS variant passes its integration test through the **full LangGraph workflow** (prepare → approve → submit → verify), not by driving the adapter directly.
- [ ] Unknown question → `needs_human` with the question text surfaced; no field auto-filled; no fabricated answer.
- [ ] CAPTCHA variant stops with `blocked_human_review` and never attempts the widget.
- [ ] Validation-error variant retries once with prepared data, then fails with captured messages.
- [ ] Two consecutive runs share no cookies/storage (isolation test).
- [ ] Zero coordinate-based clicks; zero CSS-only locators for labeled fields (grep check).

## Tests

- `tests/test_browser_variants.py` — parametrized per variant; asserts status, evidence artifacts (screenshot + trace exist), and DB rows from WS-06/07.
- `tests/test_form_plan.py` — walker classification over static HTML snapshots; answer/unresolved mapping incl. the §24 no-guess rule.
- `tests/test_isolation.py` — cookie/localStorage bleed check across runs.

## New dependencies

None.
