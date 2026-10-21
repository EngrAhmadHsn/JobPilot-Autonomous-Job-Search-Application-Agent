# WS-08 · Browser Automation Depth

Status: **Done** (2026-10-21) · Milestone: **M4** · Depends on: [06](06-security-preconditions.md) (hard gate) · Blocks: M5 live pilot

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
| `/validation-recoverable` | rejects the **first** POST only | the remediation retry that works (added — see D11) |
| `/captcha` | renders a visible "reCAPTCHA" marker widget | CAPTCHA stop (WS-06 §8) |
| `/upload-required` | file input marked required | upload verification |
| `/submitted` / `/error` | confirmation and failure confirmation pages | verification both ways |
| `/session` | sets a cookie and reports the storage it saw | the session-isolation probe (SEC-07) |
| `/_last`, `/_requests`, `/_submissions` | test-only introspection | the *negative* assertions: that a page was never posted to |

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

- [x] Every fake-ATS variant passes its integration test through the **full LangGraph workflow** (prepare → approve → submit → verify), not by driving the adapter directly.
- [x] Unknown question → `needs_human` with the question text surfaced; no field auto-filled; no fabricated answer.
- [x] CAPTCHA variant stops with `blocked_human_review` and never attempts the widget.
- [x] Validation-error variant retries once with prepared data, then fails with captured messages.
- [x] Two consecutive runs share no cookies/storage (isolation test).
- [x] Zero coordinate-based clicks; zero CSS-only locators for labeled fields (grep check).

## Tests

- `tests/test_browser_variants.py` — parametrized per variant; asserts status, evidence artifacts (screenshot + trace exist), and DB rows from WS-06/07.
- `tests/test_form_plan.py` — walker classification over static HTML snapshots; answer/unresolved mapping incl. the §24 no-guess rule.
- `tests/test_isolation.py` — cookie/localStorage bleed check across runs.
- `tests/test_locator_policy.py` — the source-level check that no id/class selector and no coordinate click reaches a field.
- `tests/test_fake_ats_server.py` — the fake ATS serves what it claims, and the WS-06 pages are unchanged.
- `tests/test_profile_facts.py` — the grounded facts are derived from the stored profile, never from the request body.

*(The delivered test layout differs from the brief in one place: the plan is unit-tested
over plain `FormControl` lists rather than over saved HTML snapshots — see D14 in Part 3.)*

## New dependencies

None.

---
---

# Part 2 — Detailed specification (added 2026-10-21)

## S0. Scope, invariants, non-goals

**Goal.** Turn the runtime browser layer from a single-page, CSS-driven demo into a
**form-aware, evidence-backed, fail-closed** submission engine, and prove it against a
fake ATS that exercises the failure modes a real one has: multi-step forms, widget
controls, unknown questions, server-side validation errors, upload requirements and
challenges.

The workstream is a *depth* workstream, not a new capability: WS-06 already put the
approval gate, the allowlist, the challenge stop and the evidence capture in place.
What is missing is **form understanding** — the ability to look at a page, decide what
it is asking, answer only what it can answer from the candidate's own evidence, and
stop cleanly when it cannot.

### Invariants (binding)

| # | Invariant | Enforced by |
|---|---|---|
| I1 | Every value the adapter types comes from a **grounded** source: a prepared field or a profile fact. A field with no grounded value is never given an invented one. | `answer_question()` in `src/applications/form.py` |
| I2 | An **unknown** question (one the field map does not cover) ends the run with `status="needs_human"` **before** anything on the page is filled and before anything is submitted. The question text is surfaced in `metadata["questions"]`. | the plan build in `FakeAtsPlaywrightAdapter.submit` |
| I3 | A **labeled** field is located by its accessibility relation (`get_by_label`) or its **role** (`get_by_role`) — never by an id or a class. The only CSS in the browser layer is the documented file-input exception and the validation-error sweep. | `tests/test_locator_policy.py` (source-level grep) |
| I4 | No coordinate-based interaction anywhere. | `tests/test_locator_policy.py` |
| I5 | Every URL the browser reaches — before *and* after each navigation — is checked against the allowlist. A URL that fails ends the run with `status="unsafe_navigation"`. | `assert_navigation_allowed` per page (WS-06 primitive) |
| I6 | A challenge (CAPTCHA / MFA / "verify you are human") ends the run **before** any interaction with the page, with `status="blocked_human_review"`. The challenge is never attempted, never clicked, never typed into. | `inspect_page` (WS-06 §9), checked per page |
| I7 | Every run gets a **fresh browser context**. No cookie, no localStorage and no session storage is shared between two runs. | `browser.new_context()` per run; `tests/test_isolation.py` |
| I8 | A submission is a success only when the evidence artifacts are on disk (WS-06 · SEC-14). The rule is unchanged; WS-08 only exercises it on more variants. | `missing_evidence_files` in the verify node |
| I9 | The form plan is a **pure** function of (page controls, grounded facts). It is unit-testable without a browser, from checked-in page snapshots. | `build_form_plan()` in `src/applications/form.py` |
| I10 | "UNKNOWN" is a valid answer. False confidence is not. A question the candidate's evidence does not cover is never answered, guessed, or left silently blank. | I1 + I2 together |
| I11 | The adapter never invents a **successful** outcome. A confirmation page that does not say so is a failure, not a soft success. | the confirmation-marker check (unchanged) |

### Non-goals

- **No live-ATS adapter.** Real-site support is an M5 decision, taken only after 06 and
  08 are accepted. The `GenericBrowserAdapter` starts from `FormPlan` + this variant
  suite — not from a live site.
- **No Browser Use.** It stays optional and non-blocking (plan §13). If it is ever
  evaluated, it consumes the same `FormPlan` contract.
- **No change to the approval gate, the permission registry, the allowlist or the
  tracking state machine.** WS-08 adds a *result status* (`needs_human`,
  `form_error`), not a new state in the WS-07 machine.
- **No new dependencies.** Everything is Playwright, FastAPI, uvicorn and Pydantic —
  all already project dependencies.
- **No login, no session replay, no anti-bot evasion.** The challenge rule is absolute.

## S1. The form contract — `src/applications/form.py` (new)

The module is the *pure* half of the browser layer: it knows what a form is, what a
question is, and what may be answered. It knows nothing about Playwright — the page
reader is duck-typed, exactly as `src/security/page_guards.py` already is, so the whole
module is unit-testable with plain data.

### S1.1 The models

```python
class FormControl(BaseModel):
    """One control on a page, as read from the accessibility tree."""
    label: str                 # the accessible name of the control
    kind: str                  # text | textarea | email | tel | number | select | checkbox | radio | file
    required: bool = False
    options: list[str] = []    # the visible option texts (select, radio group, checkbox group)
    name: str = ""             # the form field name (grouping key for radio/checkbox)

class FormQuestion(BaseModel):
    """One question the page asks."""
    label: str
    kind: str
    required: bool = False
    options: list[str] = []
    classification: str = "unknown"   # known | mappable | unknown

class FormPlan(BaseModel):
    questions: list[FormQuestion] = []
    answers: dict[str, str] = {}      # label -> grounded value (only answered questions)
    unresolved: list[str] = []        # labels that must go to a human
    skipped: list[str] = []           # known-but-empty, optional questions left alone
```

`answers` is keyed by the **label as it appears on the page**, because that is what the
adapter needs in order to find the control again. The *value* comes from the field map,
never from the page.

### S1.2 The field map — label → fact key

```python
FIELD_MAP: dict[str, str] = {
    "full name": "candidate_name", "name": "candidate_name",
    "email": "email", "email address": "email",
    "phone": "phone", "phone number": "phone", "telephone": "phone",
    "cover letter": "cover_letter", "resume": "resume", "cv": "resume",
    "country": "country", "country of residence": "country",
    "years of experience": "years_of_experience",
    "years of professional experience": "years_of_experience",
    "work authorization": "work_authorization",
    "i am authorized to work": "work_authorization",
    "authorized to work": "work_authorization",
    "work mode": "work_mode", "preferred work mode": "work_mode",
    "work arrangement": "work_mode",
    "location": "location", "current location": "location",
    "linkedin": "linkedin", "github": "github", "website": "website",
    "desired salary": "min_salary", "salary expectation": "min_salary",
    "employment type": "employment_types", "skills": "skills",
}
```

Labels are normalized before lookup: lowercased, whitespace collapsed, trailing `?`,
`:`, `*` and a leading/trailing whitespace removed.

Some canonical keys have more than one possible source, because the same fact is
called different things by different forms:

```python
FACT_SOURCES: dict[str, tuple[str, ...]] = {
    "work_mode": ("work_mode", "remote_preference"),
    "work_authorization": ("work_authorization", "eligibility"),
    "min_salary": ("min_salary", "desired_salary"),
    "cover_letter": ("cover_letter",),
    "resume": ("resume",),
}
```

The first source key that carries a non-empty value wins.

### S1.3 The grounded facts — `ProfileFacts`

```python
class ProfileFacts(BaseModel):
    values: dict[str, str] = {}

    def get(self, key: str) -> str | None: ...

    @classmethod
    def from_prepared(cls, prepared: PreparedApplication) -> "ProfileFacts":
        # prepared.prepared_fields  ∪  prepared.profile_facts
        # ∪ {"cover_letter": prepared.cover_letter, "resume": prepared.resume_path}
```

`ProfileFacts` holds **only** values that exist. A missing key is not an empty string —
it is absent, and an absent key means "no evidence", which is a different thing from
"the answer is no".

`facts_from_profile(profile: CandidateProfile) -> dict[str, str]` derives the facts a
parsed resume actually states:

| Fact | Source | Rule |
|---|---|---|
| `name`, `email`, `phone`, `location`, `title` | `personal_information` | verbatim, omitted when empty |
| `remote_preference` | `work_preferences.remote_preference` | verbatim |
| `work_authorization` | `work_preferences.work_authorization` | verbatim |
| `min_salary` | `work_preferences.min_salary` | verbatim |
| `employment_types` | `work_preferences.employment_types` | joined with `", "` |
| `skills` | `profile.skills` | joined with `", "` |
| `years_of_experience` | `experience[*].years` | the **sum** of the stated per-entry years, and **only** when at least one entry states a number |

The derivation is deterministic and additive. It never infers a fact that the document
does not state: a resume that lists no dates yields no `years_of_experience` fact, and
the question that asks for it becomes *unresolved* rather than "0".

### S1.4 Classification — the three classes

For each question:

| Class | Meaning | Effect |
|---|---|---|
| `known` | the label is in the field map **and** a grounded value exists | answered and filled |
| `mappable` | the label is in the field map but **no** grounded value exists | left alone (`skipped`) — unless the question is required |
| `unknown` | the label is **not** in the field map | **unresolved** → the run stops with `needs_human` |

A **required** question with no grounded value is `unresolved` as well, whatever its
class: submitting a required field we cannot ground is a guess wearing a disguise.

So the rule for `unresolved` is:

> A question is unresolved when it is unknown, **or** when it is required and has no
> grounded value.

Everything else is either answered (`known`) or skipped (`mappable`, optional, no
value).

### S1.5 The answer rule — `answer_question()`

```python
def answer_question(question: FormQuestion, profile: ProfileFacts | Mapping[str, str]) -> str | None
```

1. Normalize the label, look it up in `FIELD_MAP`. No entry → `None` (unknown).
2. Walk `FACT_SOURCES[key]` and take the first non-empty value. None → `None`.
3. **Widget-specific validation** — the value must be usable by that control:
   - `select` / `radio`: the value must match one of the question's options
     (case-insensitively, whitespace-normalized). No match → `None`: choosing a
     different option would be a fabrication.
   - `checkbox` (boolean): the value must be recognizably true or false
     (`yes/no`, `true/false`, `1/0`, `authorized/not authorized`, …). Anything else →
     `None`: the meaning of an unrecognized token is not ours to guess.
   - `text` / `textarea` / `email` / `tel` / `number`: the value is used as-is.

`None` means **unanswered** — and for a required question, unresolved.

### S1.6 Reading the page — `read_controls(page)`

`read_controls` enumerates the page's controls and returns `list[FormControl]`. It is
duck-typed (`page.locator(...)`, `locator.evaluate(...)`, `locator.is_visible()`) so
the module never imports Playwright.

Enumeration uses a **structural** selector (`input, select, textarea`) to find the
*set* of controls; each individual control is then described by the browser's own
accessibility information:

- **label** — the DOM's own label association (`element.labels`), falling back to
  `aria-label`, then to a wrapping `<label>`;
- **group label** — for a radio/checkbox inside a `<fieldset>`, the `<legend>` text;
- **kind** — from the tag name and the `type` attribute;
- **required** — the `required` attribute;
- **options** — the `<option>` texts of a `<select>`, or the sibling labels of a
  radio/checkbox group (grouped by `name`).

Controls that are hidden, or of type `hidden`/`submit`/`button`/`image`/`reset`, are
skipped: they are not questions.

### S1.7 Building the plan — `build_form_plan()`

```python
def build_form_plan(
    source: Sequence[FormControl] | Any,   # a list of controls, or a page
    facts: ProfileFacts | Mapping[str, str] | None = None,
) -> FormPlan
```

- A **list** of controls → the pure path (unit tests, saved snapshots).
- Anything with a `locator` attribute → the page path: `read_controls(page)` first.

The plan is built by classifying each question and applying §S1.4/§S1.5. The function
is pure: it never touches the browser, never raises on a malformed control, and never
mutates its inputs.

## S2. The fake ATS — `tests/fixtures/fake_ats/`

The current `tests/fixtures/fake_ats.py` is a stdlib `ThreadingHTTPServer` serving the
three WS-06 pages (`/apply`, `/apply/confirm`, `/challenge`). It is imported by
`tests/test_evidence.py`, `scripts/verify_ws06.py` and `scripts/verify_ws07.py`, so the
module becomes a **package** with the same import path:

```
tests/fixtures/fake_ats/
├── __init__.py     # re-exports serve_fake_ats (WS-06) + serve_fake_ats_variants (WS-08)
├── ws06.py         # the WS-06 server, moved verbatim
├── pages.py        # the HTML of every variant
└── variants.py     # the FastAPI variant app + the uvicorn runner
```

### S2.1 The WS-06 pages keep working — with one change

The WS-06 form page gains `<label for="...">` elements next to the existing inputs. The
`id`s stay exactly as they are, so the old CSS-based assertions keep their meaning, and
the WS-06 live script (`scripts/verify_ws06.py`) keeps passing unchanged.

The labels are the canonical ones this workstream standardises on:

| Control | Label | Fact key |
|---|---|---|
| `#candidate-name` | Full name | `candidate_name` |
| `#email` | Email address | `email` |
| `#phone` | Phone number | `phone` |
| `#cover-letter` | Cover letter | `cover_letter` |
| `#resume` | Resume | `resume` |

### S2.2 The variant app (FastAPI)

A FastAPI application served by uvicorn on an **ephemeral port** in a background
thread. `serve_fake_ats_variants()` is a context manager yielding the base URL, exactly
like the existing `serve_fake_ats()`.

| Route | Variant | Behaviour |
|---|---|---|
| `GET /basic` | single-page form | the regression baseline: name, email, phone, resume, submit |
| `GET /multipage` | 3-step form | step 1 personal (name, email, phone) → step 2 experience (years of experience, work authorization) → step 3 review + submit; each step POSTs to the next and carries the values in hidden fields |
| `GET /widgets` | widget controls | country (`<select>`), years of experience (text), work authorization (checkbox), work mode (radio group in a `<fieldset>`/`<legend>`) |
| `GET /unknown` | unknown question | name, email, phone + "Have you served on a submarine?" (a text input with **no** field-map entry) |
| `GET /validation` | persistent validation error | the POST always rejects with an inline `role="alert"` the prepared data cannot fix |
| `GET /validation-recoverable` | transient validation error | the **first** POST is rejected, the second is accepted — this is the branch that proves the remediation retry actually works |
| `GET /captcha` | challenge page | a visible "reCAPTCHA" marker; the flow must stop there |
| `GET /upload-required` | upload requirement | the file input is `required`; the POST rejects when no file arrived |
| `GET /submitted` | confirmation | "Application Submitted — Thanks for applying" |
| `GET /error` | failure page | a page with no confirmation marker |
| `GET /session` | session probe | sets a cookie and reports whether one was sent |
| `GET /_last` | test introspection | the last request the server received (path, method, cookie header, uploaded filenames) |

The `/_last` route is **test-only instrumentation**. It is how the tests assert the
negative facts: that the CAPTCHA variant posted nothing, that the unknown variant
posted nothing, and that the second isolation run carried no cookie.

### S2.3 The pages are semantic

Every page uses `<label for>`, `<fieldset>`/`<legend>`, real `<button type="submit">`
elements and `role="alert"` error boxes. The variant pages additionally keep a
`data-testid` on the *container* only — never on a control the adapter addresses.

## S3. The adapter — `src/applications/fake_ats_adapter.py` (rewrite)

The adapter keeps its identity (`name = "fake-ats-playwright"`), its allowlist gate,
its challenge stop and its evidence capture. What changes is the **middle**: the form is
now walked, planned and filled, and the run is a loop over pages rather than a single
submit.

### S3.1 The run

```text
_open_page(url)
  ├─ fresh browser + fresh context          (I7)
  ├─ allowlist check before the navigation  (I5)
  └─ allowlist check after the navigation
for each page (max 10):
  ├─ allowlist check on the current URL      (I5)
  ├─ inspect_page → challenge? stop          (I6)
  ├─ read_controls → build_form_plan         (I9)
  ├─ unresolved questions? stop (needs_human) (I2, I10)
  ├─ fill the plan (text/select/checkbox/radio) + upload the resume
  ├─ a submit button?  → click → check for validation errors
  │      ├─ errors → retry once with the prepared fields
  │      │      ├─ errors again → status="form_error" (messages captured)
  │      │      └─ no errors   → confirmation page → verify
  └─ otherwise a "next"/"continue" button? → click → next page
```

### S3.2 Filling a plan — the semantic locators

| Kind | Locator | Interaction |
|---|---|---|
| `text`, `textarea`, `email`, `tel`, `number` | `page.get_by_label(label)` | `.fill(value)` |
| `select` | `page.get_by_label(label)` | `.select_option(label=<matched option text>)` |
| `checkbox` (boolean) | `page.get_by_label(label)` | `.check()` / `.uncheck()` from the truthiness rule |
| `checkbox` (group) | `page.get_by_role("checkbox", name=<option>)` | `.check()` on the matching option |
| `radio` | `page.get_by_role("radio", name=<option>)` | `.check()` on the matching option |
| `file` | `page.locator("input[type='file']")` | `.set_input_files(path)` — **the documented CSS exception** |

`get_by_label` is used with `exact=True` first; when that resolves to nothing, the
adapter falls back to a case-insensitive regex on the same label, so a form that writes
`Full name *` is still found. The **fallback is a regex on the label, never a CSS
selector**.

The submit button is `page.get_by_role("button", name="Submit")` (with a
`re.compile("submit|apply", re.I)` fallback for a differently-worded button), and the
multi-page advance is `page.get_by_role("button", name=re.compile("next|continue", re.I))`.

### S3.3 The new result statuses

| Status | Meaning | Evidence |
|---|---|---|
| `needs_human` | an unknown (or required-and-ungrounded) question stopped the run | screenshot + the question texts in `metadata["questions"]` |
| `form_error` | the server rejected the form twice; the messages are captured | screenshot + `metadata["errors"]` |
| `blocked_human_review` | a challenge was present (WS-06, unchanged) | screenshot |
| `unsafe_navigation` | a URL failed the allowlist (WS-06, unchanged) | — |
| `evidence_incomplete` | the artifacts were not captured (WS-06, unchanged) | partial |
| `verification_failed` | the confirmation was absent (WS-06, unchanged) | screenshot + trace |

`needs_human` and `form_error` are **failures** (`success=False`): the run did not
submit, and the workflow must not claim otherwise.

### S3.4 Where the questions surface

`needs_human` is a result, so it travels the existing path: the submit node stores the
evidence row, `should_verify_conditional` routes to the end, and the rejection node
carries the submission's own status into `final_result`. The tracked application stays
in `AWAITING_APPROVAL` (WS-07's machine has no `needs_human` state, and inventing one
would be a status the workflow never actually reached). The **questions** are recorded
in the evidence row's metadata and in the result's `metadata["questions"]`, so the
human sees exactly what the agent could not answer.

### S3.5 Session isolation (I7)

`_open_page` creates the context explicitly:

```python
context = browser.new_context()
page = context.new_page()
```

and the context is closed in the `finally` block, next to the browser shutdown. Each
`submit()` call opens its own browser **and** its own context, so no cookie or storage
survives a run. The isolation test proves it against the real server.

## S4. The wiring — contracts and the prepare route

### S4.1 `src/applications/contracts.py`

```python
class ApplicationRequest(BaseModel):
    ...
    profile_facts: dict[str, str] = Field(default_factory=dict)

class PreparedApplication(BaseModel):
    ...
    profile_facts: dict[str, str] = Field(default_factory=dict)
```

`profile_facts` carries the **grounded** facts derived from the candidate's parsed
profile. It is a separate field from `prepared_fields` (which is the form payload) so
the approval summary can show both, and so the two are not confused.

### S4.2 `POST /api/applications/prepare`

When the request carries a `profile_id` **and** the row exists, the route derives the
facts with `facts_from_profile(profile_from_row(row))` and puts them on the request.
When the row is missing, the facts are empty — the flow still works, and the questions
that depend on them become *unresolved* rather than invented.

The caller cannot inject arbitrary profile facts: the facts come from the **stored
profile**, not from the request body. (`custom_fields` remains the existing WS-06
escape hatch, and it is still an explicit, human-supplied input.)

### S4.3 The adapter's `prepare()`

`FakeAtsPlaywrightAdapter.prepare()` copies `request.profile_facts` into
`prepared.profile_facts`. Everything else is unchanged.

## S5. The test matrix

| Test module | What it proves | Browser? |
|---|---|---|
| `tests/test_form_plan.py` | the field map, the three classes, the answer rule, the widget rules, the no-guess rule, the plan over the **saved page snapshots** | no |
| `tests/test_browser_variants.py` | every variant through the **full workflow** (prepare → approve → submit → verify), the statuses, the evidence artifacts, the DB rows | yes |
| `tests/test_isolation.py` | two consecutive runs share no cookie or storage | yes |
| `tests/test_locator_policy.py` | the source-level grep: no id/class CSS for fields, no coordinates | no |
| `tests/test_application_adapter.py` (extended) | the adapter's unit behaviour with fake pages | no |
| `tests/test_evidence.py` (extended) | the WS-06 evidence rules still hold after the rewrite | partly |

### S5.1 The saved page snapshots

`tests/fixtures/fake_ats/snapshots/*.json` holds the control snapshot of each variant
page, captured from the **real** browser. Two things are asserted against them:

1. `tests/test_form_plan.py` builds the plan over the snapshot — the pure path, no
   browser;
2. `tests/test_browser_variants.py` asserts that the **live** page still produces the
   same snapshot — so the fake ATS's markup and the unit tests cannot drift apart.

## S6. Execution plan (phases A–H)

Each phase: implement → its own tests → the full offline suite → `ruff check`.
Nothing is committed until the phase's tests are green.

- **Phase A — The form contract.** `src/applications/form.py`: the models, the field
  map, `ProfileFacts`, `facts_from_profile`, `read_controls`, `classify_question`,
  `answer_question`, `build_form_plan`. Tests: `tests/test_form_plan.py` (the pure
  path, over hand-written controls and over the saved snapshots).
  *Gate:* the three classes behave; the answer rule never invents a value; a required
  ungrounded question is unresolved; a select value that matches no option is
  unanswered; an unrecognized checkbox token is unanswered.

- **Phase B — The fake ATS.** `tests/fixtures/fake_ats/` as a package: `ws06.py`
  (moved verbatim), `pages.py`, `variants.py` (the FastAPI app + the uvicorn runner),
  `__init__.py` (the two context managers). The WS-06 form page gains its labels.
  Tests: `tests/test_fake_ats_server.py` — the server serves what it claims, the
  WS-06 pages are unchanged in behaviour, the snapshot files match the live pages.
  *Gate:* the WS-06 script and the WS-06/WS-07 tests still pass; every variant route
  answers.

- **Phase C — The adapter rewrite.** `src/applications/fake_ats_adapter.py`: the
  semantic locators, the walker, the page loop, the widget filling, the
  unknown-question pause, the validation retry, the explicit context. The existing
  fakes in `tests/test_application_adapter.py` and `tests/test_evidence.py` are
  updated to the new locator contract.
  *Gate:* the WS-06 evidence and permission tests still pass; the adapter fills a
  labelled form, stops on a challenge, and stops on an unknown question.

- **Phase D — The wiring.** `src/applications/contracts.py` (`profile_facts`),
  `src/applications/fake_ats_adapter.py` (`prepare`), `src/api/routes/applications.py`
  (derive the facts from the stored profile), `src/applications/__init__.py` (the
  exports). Tests: `tests/test_submit_api.py` (extended) — a prepared application
  carries the profile's facts; a missing profile row yields no facts and no error.
  *Gate:* the facts are derived, never invented; the prepare flow still works without
  a profile.

- **Phase E — The variant integration tests.** `tests/test_browser_variants.py`: the
  parametrized variants, driven through the **API** (prepare → approve), asserting the
  status, the evidence artifacts on disk, and the WS-06/WS-07 database rows.
  *Gate:* every variant reaches its expected status through the full workflow, and
  the negative variants prove what they claim (no POST for the challenge, no POST for
  the unknown question, the errors captured for the validation variant).

- **Phase F — The isolation test.** `tests/test_isolation.py`: two consecutive runs
  against the `/session` route; the second request carries no cookie, and no
  localStorage survives.
  *Gate:* the second run's request has an empty `Cookie` header.

- **Phase G — The locator policy.** `tests/test_locator_policy.py`: the source-level
  grep over the browser layer.
  *Gate:* the test fails if anyone reintroduces an id/class selector for a field, or
  a coordinate-based click.

- **Phase H — Live verification + docs.** `scripts/verify_ws08.py`: a real HTTP
  server, a real Chromium browser, the real API, every variant, the evidence on disk
  and the database rows inspected directly. `docs/implementation/00-OVERVIEW.md` and
  this document's status part.
  *Gate:* every check prints PASS and the script exits 0.

**Ordering rationale.** A before B (the plan is built over the controls the pages
produce). B before C (the adapter is written against the variants). C before D (the
wiring hands the adapter its facts). D before E (the variants need the facts to be
answerable). E before F (the isolation test reuses the variant harness). G after C
(the policy check reads the rewritten source). H is last because it asserts the
finished behaviour over real HTTP.

**Risk register for this workstream**

| Risk | Mitigation |
|---|---|
| The rewrite breaks the live-verified WS-06 behaviour | the WS-06 pages keep their ids and their routes, and `scripts/verify_ws06.py` / `scripts/verify_ws07.py` are re-run as part of the gate |
| The semantic locators are too strict for real markup | the fallback is a **regex on the label**, never a CSS selector; the field map normalizes labels (case, punctuation, trailing `*`) |
| A required field we cannot answer silently blocks every form | that is the intended behaviour (I1/I10): the run stops with `needs_human` instead of guessing. The variants that must succeed use questions the candidate's evidence covers |
| A multi-page loop never terminates | the page count is bounded (10) and every page re-checks the allowlist |
| The Playwright tests are slow or flaky | one browser per test, a fresh context each time, an ephemeral port per server; the suite is run with `-n 4` like every other workstream |
| The variant app changes the WS-06 fixture's behaviour | the WS-06 server moves **verbatim**; only the form page gains labels, and the ids are unchanged |

---

# Part 3 — Deviations from the Part 1 brief (recorded for audit)

## S7. Deviations from the Part 1 brief (recorded for audit)

| # | Brief says | Implemented as | Why |
|---|---|---|---|
| D1 | the fake ATS lives in `tests/fixtures/fake_ats/` (new) | it does — the existing `tests/fixtures/fake_ats.py` became the **package** `tests/fixtures/fake_ats/`, with the WS-06 server moved verbatim into `ws06.py` | a file and a directory cannot share a name. The package keeps the import path `from tests.fixtures.fake_ats import serve_fake_ats` working, so the WS-06 script and tests are untouched |
| D2 | `build_form_plan(page) -> FormPlan` is "a pure-ish function over the accessibility tree" | `build_form_plan(source, facts=None)` accepts **either** a list of `FormControl` **or** a page | a function that needs a live browser is not unit-testable, and the brief asks for the plan to be "directly unit-testable from saved page snapshots". The pure path is the list; the page path is a convenience |
| D3 | the adapter classifies fields into `{known, mappable, unknown}` and "unknown" means "not in the field map" | the same three classes, and a **required** question with no grounded value is also unresolved | submitting a required field we cannot ground is a guess. The brief's own rule ("answer only when the profile contains evidence") implies it |
| D4 | the unknown-question pause captures "question text + page screenshot" and sets `metadata={"questions": [...]}` | it does; the run stops **before** anything on the page is filled or submitted | "no field auto-filled" is the acceptance criterion; stopping before the fill is the only reading that guarantees it. The fake ATS records the POST, so the test can prove nothing was sent |
| D5 | the validation variant "rejects empty required field with inline error on submit" and the adapter "retries once with prepared fields" | `/validation` rejects with a message the prepared data **cannot** fix (the end state is a failure, as the brief says); `/validation-recoverable` rejects only the first POST | one variant cannot show both branches. The brief's own end state ("retries once with prepared data, then fails with captured messages") is the persistent one, so it keeps the name; the recoverable branch is added under its own name |
| D6 | the profile is the grounding source for `answer_question(question, profile)` | the grounding source is `ProfileFacts`, built from the prepared fields ∪ the profile facts ∪ the cover letter and resume | the adapter has no database session; the facts are prepared **before** the browser opens, which is what makes the browser step pure and testable |
| D7 | — | the profile facts are derived **server-side** from the stored `CandidateProfile` when the prepare request carries a `profile_id` | a caller-supplied "profile" would be a caller-supplied fact, and the agent's grounding must come from the candidate's own document. `custom_fields` remains the existing, explicit human-supplied channel |
| D8 | — | the adapter creates an explicit `browser.new_context()` per run | SEC-07 asks for isolated contexts and a clean session boundary; the previous `browser.new_page()` relied on the browser's implicit default context |
| D9 | — | a new result status `needs_human` is added, but **no** new WS-07 tracking status | inventing a tracking state the workflow never reached would fabricate history (WS-07 invariant I8). The application stays in `AWAITING_APPROVAL` and the questions are recorded as evidence |
| D10 | — | the graph's rejection node now **merges** the submission's metadata into the final result | the question text is the reason a human is needed; flattening it away made the pause useless. Found by the live run |
| D11 | the validation variant is one route | there are two: `/validation` (always rejected — the brief's end state) and `/validation-recoverable` (rejected once, accepted on the retry) | one variant cannot show both branches of "retry once with the prepared data" |
| D12 | — | the browser's **own** validation messages are read from the controls' validity state | a page that marks a field `required` refuses the submission before it is sent; the bubble is not in the DOM, but the reason is |
| D13 | — | the field map is exposed as `FieldLookup` (a namespace over `FIELD_MAP` and `FACT_SOURCES`) | the map is *the* statement of which questions the agent knows how to answer; it should be read and reviewed in one place |
| D14 | the plan is "directly unit-testable from saved page snapshots" | the plan is unit-tested over plain `FormControl` lists, and the **live** pages are pinned by the variant tests instead | the snapshot files would have been a second copy of the fake ATS's markup, free to drift. The live-page contract is stronger and cannot drift. The saved-snapshot fixtures are the one part of the brief that was not built as described |

---

# Part 4 — Implementation status (2026-10-21)

Status: **Done** · Suite: **793 passing** (baseline at the start of the workstream: 715),
offline, `ruff check` clean over `src/ tests/ scripts/ migrations/`. New: 78 tests across
7 new test modules plus extensions to 2 existing ones. Live-verified with a real HTTP
server, a real Chromium browser and a real database: **25/25 checks** in
`scripts/verify_ws08.py`. The WS-06 and WS-07 live scripts still pass unchanged
(12/12 and 21/21).

## What was built

| Area | Files | What it does |
|---|---|---|
| The form contract | `src/applications/form.py` | the models (`FormControl`, `FormQuestion`, `FormPlan`), the field map, `ProfileFacts`, `facts_from_profile`, `read_controls`, `build_form_plan`, `answer_question`, `checkbox_truth` — pure, browser-free, unit-testable |
| The adapter | `src/applications/fake_ats_adapter.py` | rewritten: semantic locators, the page loop, the widget filling, the unknown-question pause, the validation retry, the explicit context, the two new result statuses |
| The fake ATS | `tests/fixtures/fake_ats/` (package) | the WS-06 server (moved verbatim) plus the WS-08 variant app: `/basic`, `/multipage`, `/widgets`, `/unknown`, `/validation`, `/validation-recoverable`, `/captcha`, `/upload-required`, `/submitted`, `/error`, `/session`, and the test-only `/_last`, `/_requests`, `/_submissions` routes |
| The wiring | `src/applications/contracts.py`, `src/api/routes/applications.py`, `src/graph/application_workflow.py` | `profile_facts` on the request and the payload; the facts derived server-side from the stored profile; the submission's metadata survives the graph's rejection node |
| The tests | `tests/test_form_plan.py`, `tests/test_browser_variants.py`, `tests/test_isolation.py`, `tests/test_locator_policy.py`, `tests/test_fake_ats_server.py`, `tests/test_profile_facts.py`, `tests/fixtures/fake_page.py` | the plan over pure data, every variant through the full workflow, the session-isolation proof, the source-level locator policy, the server, the profile facts |

## The acceptance criteria (as delivered)

| # | Criterion | How it is met | Test |
|---|---|---|---|
| 1 | every variant passes through the **full LangGraph workflow** | the variant tests drive `POST /api/applications/prepare` → `POST /api/applications/{id}/approve`; the graph runs prepare → approval → submit → verify | `tests/test_browser_variants.py` (14 tests) |
| 2 | unknown question → `needs_human`, question surfaced, no field auto-filled | the run stops *before* the fill and *before* the submit; the question text is in `metadata["questions"]` and in the evidence row's metadata | `tests/test_browser_variants.py::TestNeedsHuman` |
| 3 | CAPTCHA → `blocked_human_review`, the widget is never attempted | the challenge check runs before any interaction; the fake ATS records that no POST arrived | `tests/test_browser_variants.py::TestChallenge` |
| 4 | validation error → retried once with the prepared data, then fails with the captured messages | `MAX_SUBMIT_ATTEMPTS = 2`; the second attempt's messages are in `metadata["errors"]` | `tests/test_browser_variants.py::TestFormError` |
| 5 | two consecutive runs share no cookies/storage | an explicit `browser.new_context()` per run; the probe page reports the cookie and the storage marker | `tests/test_isolation.py` (2 tests, one of them the control that proves the probe would notice a leak) |
| 6 | zero coordinate-based clicks; zero CSS-only locators for labeled fields | every CSS selector in the browser layer is on an allowlist of four, and no id selector is allowed at all | `tests/test_locator_policy.py` (7 tests) |

## The result statuses (as delivered)

| Status | When | Evidence |
|---|---|---|
| `verified` | the confirmation page confirmed the submission | screenshot + action trace + Playwright archive |
| `needs_human` | an unknown (or required-and-ungrounded) question | screenshot; the questions in `metadata["questions"]` |
| `form_error` | the server rejected the form twice | screenshot; the messages in `metadata["errors"]` |
| `blocked_human_review` | a challenge was on the page | screenshot; the marker in `metadata["challenge"]` |
| `unsafe_navigation` | a page URL failed the allowlist | screenshot |
| `evidence_incomplete` | the artifacts were not captured | partial |
| `verification_failed` | the confirmation was absent | screenshot + trace |

## Live verification (2026-10-21, real HTTP + real Chromium + real database)

`scripts/verify_ws08.py` — **25/25 checks**:

- the four completing variants (`/basic`, `/multipage`, `/widgets`, `/validation-recoverable`)
  are submitted and verified, each with its evidence on disk;
- the widget values really reached the server (`country=Germany`, `work_mode=remote`,
  `work_authorization=yes`);
- the unknown question ends the run with `needs_human`, the question text is surfaced, and
  **nothing was submitted** (the fake ATS recorded a GET, not a POST);
- the challenge ends the run with `blocked_human_review` and **was never posted to**;
- the rejected form ends with `form_error` and the server's own message is captured;
- the upload variant is verified and the resume really arrived (`files=['resume.txt']`);
- two consecutive runs inherit neither a cookie nor the browser's storage;
- the database holds the tracked applications, one evidence row per outcome (all four
  statuses), a screenshot on disk for every evidence row, and the audit trail.

## Two defects the live runs exposed (both fixed, both with regression tests)

1. **The graph's rejection node dropped the submission's metadata.** A `needs_human`
   result carried the question text, but the workflow's final result replaced the
   metadata with `{workflow_id, adapter}` — the human never saw the question. The
   submission's metadata is now merged into the final result
   (`src/graph/application_workflow.py`).
2. **The fake ATS's own upload form was wrong.** The form had a file input but no
   `enctype="multipart/form-data"`, so the browser encoded the submission as
   `application/x-www-form-urlencoded` and silently dropped the file. The pages that
   carry a file input now declare the enctype. (The agent was right all along: the file
   genuinely never left the browser.)

## Deviations added during the execution (recorded in S7)

| # | Deviation | Why |
|---|---|---|
| D10 | the rejection node merges the submission's metadata into the final result | the question text is the reason a human is needed; flattening it away made the pause useless |
| D11 | the fake ATS serves `/validation-recoverable` in addition to `/validation` | one variant cannot show both the "retry once and fail" and the "retry once and succeed" branches |
| D12 | the browser's **own** validation messages are read from the controls' validity state | a page that marks a field `required` refuses the submission before it is sent; the bubble is not in the DOM, but the reason is |
| D13 | the form contract is exposed as `FieldLookup` (a namespace over the field map) | the field map is *the* statement of which questions the agent knows how to answer; it should be read in one place |

## Follow-ups left for later workstreams

- **The real-ATS adapter** — deliberately out of scope here (Part 1, §4). The M5 pilot
  decides it, starting from `FormPlan` and this variant suite.
- **The field map is a first cut.** It covers the labels a typical form uses; a real ATS
  will need more, and the fuzzy second pass (longest unambiguous match) is where the
  extension goes.
- **SEC-15 (retention)** and **malware scanning** are still open, as they were.
- **The `FormPlan` snapshot fixtures** the Part 1 brief asked for were delivered as the
  live-page contract instead: the variant tests assert against the *real* pages, and the
  plan is unit-tested over plain `FormControl` lists. The snapshot files themselves are
  the one part of the brief that was not built as described.

