# WS-32 · Submission Readiness: a PDF Résumé, a Validated Payload, a Durable Submission, and the Assist Pilot

Status: **Code complete (2026-11-15) — Tasks 1–4 landed; the pilot's code and rehearsal are
done and its first real run is awaiting the human** · Milestone: **M5** ·
Depends on: WS-06 (the allowlist, the approval gate and the evidence trail), WS-07
(the tracking tables), WS-08 (the form walker and the fake-ATS variants), WS-18
(the durable queue), WS-25/25b/25c (the provider depth, the board registry and the
measured questions), WS-14 · Phase B (per-user storage) ·
Plan: [2026-11-14-submission-readiness.md](../superpowers/plans/2026-11-14-submission-readiness.md)

> **Where this starts.** Phase 0 of the plan verified the research material's central
> claim — that a third-party agent can submit an application to a board over the
> provider's API — against primary sources, and found it partly true and false in the
> way that matters. Greenhouse's application endpoint is real, and its documented
> field list is a genuine artefact (Task 2 uses it as a **validator**). The
> credential is not ours: `POST .../boards/{token}/jobs/{id}` answers **401
> `HTTP Basic: Access denied.`** without the hiring company's own API key. So WS-32
> adds **no API submission channel**; it prepares the browser path to be the one
> that is ready.
>
> **The provider does not validate either.** Greenhouse, verbatim: *"Greenhouse will
> not reject applications that are missing required fields."* A submission missing an
> answer therefore **succeeds and is silently incomplete** — the candidate believes
> they applied, the employer receives a blank, and nothing reports an error. Task 2
> exists for exactly that.
>
> **And the safest first real submission is not unattended.** Every other task here is
> preparation for one; Task 5 is that submission, in the form the evidence supports —
> the agent prepares everything, fills the form up to the final submit, and hands the
> browser to a human. Its purpose is **measurement, not automation**: where the run
> stops decides which board shape to support next, instead of guessing.

---

## 1 — Task 1: a PDF résumé is read, not refused

`.pdf` is the format ATS upload fields expect — Greenhouse's own submission example
posts one — and `src/resume/parser.py` refused it outright: a candidate whose résumé
is a PDF could not use the system at all.

**What landed.** A `.pdf` is accepted end to end. `_read_pdf_lines`
(`src/resume/parser.py:121`) reads the text layer and dispatches from `_read_lines`;
the upload boundary (`src/api/validation.py`) gained `.pdf` in `ALLOWED_EXTENSIONS`
and a `_validate_pdf` that requires the `%PDF-` magic **and** a successful
`pypdf.PdfReader` open, so a renamed ZIP is refused at the boundary. Every page is
extracted, not just the first.

**The refusals are the point of the task** — four distinct messages, because they are
four different problems with four different user fixes:

| Refusal (match string) | Shape | What the user is told |
|---|---|---|
| `no extractable text` | a scan or an image-only export — a PDF wrapper around no text | extract the text, or upload the DOCX |
| `not readable text` | the text layer exists but is broken | the characters could not be decoded; re-export with embedded fonts |
| `password` | `reader.is_encrypted` | remove the password and upload again |
| `could not be read` | pypdf cannot open or parse the file at all | pypdf's own exception never escapes as a 500 |

**The follow-up fix matters as much as the first commit.** Review round 1 found the
garbage-detector's blind spot: it counted only U+FFFD, so the *real* broken shape — a
CID font with **no** `/ToUnicode` — extracted as C0 control characters (`\x01\x02…`),
the flag read `False`, and `parse_resume` returned a **profile whose name was a run of
control characters** (`'\x01\x02\x03\x04\x05\x06\x07\x08'`). That is a fabricated
candidate profile, which the project forbids. `_is_unreadable_char`
(`src/resume/parser.py:89`) now classifies U+FFFD, C0 (excluding `\t`/`\n`/`\r`), C1
and Unicode `Cf`; more than 20% of the non-whitespace characters makes the extraction
unreadable. Commit `9bbe792` carries it, with the new fixture
`tests/fixtures/pdf/resume_no_tounicode.pdf`.

**The one new dependency.** `pypdf>=5.0` (`pyproject.toml:40`): pure Python, no
external binary, BSD-licensed, reads a text layer without a rendering engine. The
alternative — shelling out to `pdftotext` — would add an OS-level binary the
deployment must provide, which the Windows dev environment makes worse. Nothing here
writes PDFs, so a heavier toolkit would be unjustified weight. Fixtures are
checked-in binaries with a checked-in generator (`tests/fixtures/pdf/make_fixtures.py`,
stdlib plus `pypdf` for the encrypted variant), because the machine has no Word, no
LibreOffice and no `pdftoppm`.

Commits: `048cd2b` (the reader and the boundary), `9bbe792` (the CID-font fix).
Tests: `tests/test_ws32_pdf_resume.py` — **10 cases**.

## 2 — Task 2: the prepared payload is validated against the provider's published contract

Nothing checked the *assembled payload* against the provider's contract before it was
submitted. Our own prepare path decides what is unanswered (`needs_human` verdicts,
blocking questions), but the provider's documented failure mode is that it accepts the
blank anyway.

**What landed.** `src/applications/greenhouse_contract.py` — a policy table plus
functions, the shape `src/jobs/board_metadata.py` already uses. It carries the
documented field names as data (`GREENHOUSE_APPLICATION_FIELDS`: identity, documents,
address, consent, provenance; `REQUIRED_FIELDS` = `first_name`, `last_name`, `email`,
`phone`; `RESUME_FIELDS` = `resume`/`resume_text`) and one validator,
`validate_against_contract(prepared, *, schema=None, consent_required=()) ->
ContractReport`, with `missing`, `consent_unanswered` and `is_complete`.

Two reading rules, both tested: **a blank value is not an answer** (`"   "` reads as
missing — the exact silent incompleteness the provider permits), and the resume
requirement is satisfied by `resume_path` **or** a `resume`/`resume_text` field.

**Adapter-delegated.** The field names are Greenhouse's, and the local fake ATS's
payload is a form-walk summary (`candidate_name`, not `first_name`/`last_name`) whose
completeness protection is its own WS-08 walker. So the gate is gated on a second
policy table, `CONTRACT_ADAPTERS = frozenset({"greenhouse", "assist-playwright"})` —
a future provider adapter adds one row to be covered.

**Fail-closed, not a crash.** `submit_node` (`src/graph/nodes.py:267`) runs the check
**after** the permission gate and **before** the adapter is reached: an incomplete
payload sets `status="incomplete_payload"`, `success=False`, names the missing fields
in the message, records an audit row (`ACTION_SUBMIT` + `OUTCOME_BLOCKED` — no new
constant was invented) and returns. Nothing raises; a prepare-time defect is a
reported outcome.

**The endpoint is employer-authenticated, so the list validates ours and is never used
to submit.** That is stated in the module docstring, alongside the verbatim provider
sentence and the 401 finding.

Commit: `23a17b4`. Tests: `tests/test_ws32_payload_contract.py` — **18 cases**.

## 3 — Task 3: a submission survives the request that started it

The approve route ran the whole submission **inline**, in the request thread, with a
`MemorySaver` and no recovery. Against the local fake ATS that is invisible; against a
real board it is an HTTP request that outlives its client, and a crash loses the run
with the approval row left mid-flight.

**What landed.** The approve route records the human decision and **accepts** the
submission as durable work; the worker performs the same `execute_approved` call the
route used to make. The run kind is `JOB_TYPE_SUBMISSION = "submission"`
(`src/runs/embedding.py`, re-exported through `src/runs/service.py`), enqueued by
`enqueue_submission(db, *, approval_id, workflow_id, owner_id, approver)`,
`PRIORITY_SUBMISSION = 15` — above every scheduled drain, below an administrator's
explicit recovery. `scripts/run_worker.py` needed no change: the claim is
kind-agnostic.

| Invariant | How it holds |
|---|---|
| The approve returns **accepted, not submitted** | `POST /api/applications/{id}/approve` answers **202 + a run id**; `ApprovalStatus` was not extended |
| The row never reads `EXECUTED` before the work ran | the row is committed as `APPROVED`; only the worker's recorded outcome moves it |
| Submission is **at-most-once** | the recorded-outcome guard: an approval whose row already records a submission is never submitted again |
| A crash **after the board accepted** but **before the outcome was recorded** is not re-sent | an attempt marker (`attempt_started_at`) is committed to the run's metadata **before** the adapter is reached; a retry that finds the marker with no recorded outcome refuses, settles the item with the event `submission.uncertain`, and leaves the row `APPROVED` — decided, outcome unknown, which is the truth |
| The tracking write can no longer discard the acceptance | the acceptance (decision + queued run) is committed **first**; a best-effort tracking failure can lose an event, never the work |

Each existing guard stayed in place: the PENDING check, the WS-25 expiry, the WS-25b
job-liveness check, the WS-14 principal-is-the-approver rule, `assert_execution_allowed`
before anything is enqueued, the WS-07 tracking event and the approve audit row.

Found while doing it: `_adapter_for_url` had been calling the two-argument
`select_adapter_for_url` with one argument, raising `TypeError` into a bare `except` —
so **the WS-25b liveness gate had never run**. Fixed in this task.

Commits: `fb3c38a` (the queue), `ca6ec22` (the uncertain-attempt escalation and the
discarded acceptance). Tests: `tests/test_ws32_durable_submission.py` — **10 cases**,
plus `tests/test_submit_api.py` and `tests/test_browser_variants.py` updated for the
202-then-drain shape.

## 4 — Task 4: the adapter-layer refusal the docstring already claimed

`src/security/registry_setup.py` stated that *"the adapters themselves refuse a submit
they were not granted as a second layer."* Only greenhouse and lever did. The fake ATS
did not — it holds `SUBMIT`, so nothing exposed the gap, and it is the adapter a new
adapter is most likely to be written from. A docstring that overclaims is worse than a
missing one.

**What landed.** `ApplicationAdapter.require_capability(level, registry=None) ->
None` on the base class (`src/applications/contracts.py`) raising `PermissionError`
that names the adapter and the capability; every adapter's `submit` calls it first
and so does every adapter's `verify`. **The gap was one method wider than the
docstring claimed**: `verify` is a separately granted capability, so a submit-only
check would have left the same hole one method over. A spy test parametrized over
`src.graph.executor.AVAILABLE_ADAPTERS` proves each adapter asks for the right
capability before it acts (it raises and records), so a future adapter that forgets
the call fails a test the day it is registered.

Commit: `3f39854`. Tests: `tests/test_ws32_adapter_selfcheck.py` — **11 cases**.

## 5 — Task 5: the assist-mode pilot

The M5 direction recorded 2026-10-22: prepare everything, open the browser, fill the
form up to the final submit, then hand the browser to the human. No unattended run
happens on the way there.

### 5.1 The design

`AssistAdapter` (`src/applications/assist_adapter.py`), `name = "assist-playwright"`,
holds **`PREPARE` and nothing else** (`src/security/registry_setup.py:57`;
`tests/test_permissions.py` pins the four-name matrix). Its `submit`
(`src/applications/assist_adapter.py:353`) asks `self.require_capability(PREPARE)`
first, fills the form, and returns
`ApplicationResult(success=False, status="awaiting_human_submit", message=<contains
"filled">)` with the browser left open — `self.browser_open = True`, and a `close()`
the operator calls, never the agent. **The agent cannot press submit because it does
not hold `SUBMIT`**: the safety property is enforced by the capability matrix, not by
the code remembering to stop, and a spy test proves the `require_capability` call
happens before anything else.

The walk is the WS-08 walker **reused, not forked**: `AssistAdapter` subclasses
`FakeAtsPlaywrightAdapter` and overrides only its identity, its `prepare` (below), the
one method that *is* the stop, and the result plumbing. So a multi-step form still
advances (the override finds the page's button first; only a button that **submits**
stops the walk, before the click), a challenge still ends the agent's part of the run
(SEC-09 — and the window is **closed** rather than handed to a human standing in front
of a CAPTCHA), and the per-page allowlist check, the unanswered-question stop and the
one-retry-on-rejection behaviour are all inherited.

`_fill_and_submit` (`src/applications/assist_adapter.py:498`) looks for the page's
button **before** the fill and returns the new outcome kind `awaiting_human_submit`
**without ever calling `click`**. A wizard's *next* button runs the parent's
implementation unchanged. The stop point is captured as evidence (a screenshot and the
navigation trace), while the Playwright trace is deliberately **left running** across
the handover, so the human's own submit lands inside the archive written by
`capture_human_submission()` or `close()`.

### 5.2 The identity fields (R4)

`ApplicationRequest` carries a single `candidate_name`, and the boards ask for two
parts. `split_candidate_name(name) -> tuple[str, str] | None`
(`src/applications/assist_adapter.py:169`) splits on whitespace — first token, rest —
and returns **`None` for a single token or an empty name, never a guess**: an invented
surname is fabricated candidate data submitted to an employer. `prepare` emits the
provider's documented identity fields (`first_name`, `last_name`, `email`, `phone`)
plus a résumé (`resume_path` or `prepared_fields["resume_text"]`), because the
contract gate requires them; with no split available, both name fields stay absent and
**the gate refuses the payload** — the correct fail-closed outcome, with a human
supplying the missing part. `ApplicationRequest`'s own placeholder defaults
(`candidate@example.com` and friends) read as "not supplied", so the stored profile's
values are used instead of putting a placeholder on a real board.

### 5.3 The pilot harness (R5)

`scripts/pilot_assist.py` exposes a callable
`run_pilot(url, profile_id, ...) -> PilotReport`; `main()` is a thin CLI wrapper that
maps refusals to exit codes (3 = the allowlist refused the target, 4 = the payload was
incomplete). Its first statement is `assert_target_allowed(url)`
(`scripts/pilot_assist.py:356`) — **the real guard, before a profile is read and
before a browser exists** — so `DisallowedDomainError` propagates with a message that
names the host and the `ALLOWED_DOMAINS` variable. The report is a measurement: the
stop result, the questions it could not answer, the questions it left alone, the
widgets it did not recognise, the evidence from the page the human submitted on, and
the verified status. A fresh browser context per run (SEC-07) is the parent's
behaviour, and the harness never closes the browser out from under the human unless
asked to.

The **human's** submit is not the agent's: `capture_human_submission()` reads the page
the human submitted on and returns the evidence; `verify` asks for the capability it
*practices* (`PREPARE`), not `VERIFY`, because asking for `VERIFY` would make the one
thing the pilot exists to verify permanently unreachable. An assist run with no
evidence is not verifiable and is never reported as submitted.

### 5.4 The local rehearsal — done

The plan's Step 4 is satisfied twice over: `@pytest.mark.browser` test
`test_a_human_submit_after_the_run_produces_verifiable_evidence` drives a real
Chromium against the local fake ATS, has the "human" click the page's own submit
button, and asserts the server received **no** submission before that click; and a
CLI smoke run was taken while finishing this task:

```
env\Scripts\python.exe scripts\serve_fake_ats.py --port 8911
env\Scripts\python.exe scripts\pilot_assist.py --url http://127.0.0.1:8911/basic \
    --candidate-name "Ada Lovelace" --email ada@example.com --phone "+1 555 0101" \
    --resume-path <a txt résumé> --unattended --close-when-done
```

Result: `awaiting_human_submit` in **1.3 s**, questions left for the human
`['Cover letter']`, no unrecognised widgets, and `GET /_submissions` still `[]`
afterwards — the agent filled the form and did not submit it. (`--unattended` is for
the rehearsal only; it claims no evidence and no verification.)

### 5.5 The first live run — the protocol, and it has not happened yet

**Status: awaiting the human's first live run.** No measurement of a real posting has
been taken, and none is claimed here.

```
set ALLOWED_DOMAINS=boards.greenhouse.io,greenhouse.io
set PLAYWRIGHT_HEADLESS=false
env\Scripts\python.exe scripts\pilot_assist.py ^
    --url https://boards.greenhouse.io/<company>/jobs/<id> ^
    --profile-id <stored profile id> --job-title "<the posting's title>" ^
    --company "<the company>" --json
```

The operator adds the board's host to `ALLOWED_DOMAINS` **deliberately, per run**;
without it the pilot prints `The pilot refused to start: …` and exits 3 before any
browser exists. `PLAYWRIGHT_HEADLESS=false` is required — the whole point is a window
the operator can finish the form in. `--close-when-done` stays off until the human has
pressed submit.

**To record** (the measurement the workstream exists for):

| What | Where it comes from in the report |
|---|---|
| elapsed time | `elapsed_seconds` |
| the questions it could not answer | `questions_unanswered` |
| the questions it left for the human | `questions_left_alone` |
| the widgets it did not recognise | `unrecognised_widgets` |
| whether the page's own validation complained | at the human's own submit — the browser's message, or `form_error` if the form was rejected before the handover |
| the stop point | `evidence.url`, `evidence.screenshot_path` |
| what the human's submit confirmed | `evidence.confirmation_text`, `verified_status` |

The run's findings belong in this document (a new section), and the board shape it
argues for becomes the next task's premise.

## 6 — Acceptance

| Task | Check | Test |
|---|---|---|
| 1 | a PDF text layer parses into a populated profile | `tests/test_ws32_pdf_resume.py` |
| 1 | a scan is refused with `no extractable text` | `tests/test_ws32_pdf_resume.py` |
| 1 | a mojibake PDF and an unmapped CID font are refused with `not readable text` | `tests/test_ws32_pdf_resume.py` |
| 1 | a corrupt PDF and an encrypted PDF are refused with their own messages | `tests/test_ws32_pdf_resume.py` |
| 1 | the DOCX/TXT paths are unchanged; the upload boundary accepts `.pdf` | `tests/test_ws32_pdf_resume.py`, `tests/test_upload_validation.py` |
| 2 | a complete payload passes; a missing field is named | `tests/test_ws32_payload_contract.py` |
| 2 | a payload with no resume at all is incomplete | `tests/test_ws32_payload_contract.py` |
| 2 | consent is reported separately and does not block | `tests/test_ws32_payload_contract.py` |
| 2 | the node refuses an incomplete payload without raising and never reaches the adapter | `tests/test_ws32_payload_contract.py` |
| 3 | approve returns 202 + a run id; the row is not `EXECUTED` yet | `tests/test_ws32_durable_submission.py` |
| 3 | the worker executes the queued submission; a crash is reclaimable | `tests/test_ws32_durable_submission.py` |
| 3 | a retried submission does not submit twice; an unrecorded attempt escalates | `tests/test_ws32_durable_submission.py` |
| 3 | no code path executes a submission inside a request thread | `tests/test_ws32_durable_submission.py` |
| 4 | every adapter refuses a capability it does not hold, and asks before acting | `tests/test_ws32_adapter_selfcheck.py` |
| 5 | `assist-playwright` holds PREPARE and not SUBMIT | `tests/test_ws32_assist_mode.py` |
| 5 | `submit` fills, returns `awaiting_human_submit` with "filled", never clicks, browser open | `tests/test_ws32_assist_mode.py` |
| 5 | the pilot refuses a target outside the allowlist before a browser exists | `tests/test_ws32_assist_mode.py` |
| 5 | the human's submit produces the evidence `verify` reads (real Chromium) | `tests/test_ws32_assist_mode.py` |
| 5 | `split_candidate_name` units; `prepare` emits the identity fields | `tests/test_ws32_assist_mode.py` |
| 5 | a spy proves `submit` calls `require_capability(PREPARE)` | `tests/test_ws32_assist_mode.py` |
| 3, 5 | the pilot hands over on every form-waiting stop, not only the happy one | `tests/test_ws32_assist_mode.py` |
| 3 | the submission policy is re-checked at execution, so the kill switch binds | `tests/test_ws32_durable_submission.py` |
| 2 | the contract docstring's consent claim is true, and no production caller exists | `tests/test_ws32_payload_contract.py` |
| 3 | the console reads an accepted submission as accepted, with its run id | `frontend/src/screens/approvals-screen.test.tsx` |

86 cases across the five WS-32 test files. For Tasks 1–4, each test was written before its
implementation and run failing; those RED runs are recorded in the per-task reports under
`.superpowers/sdd/2026-11-14-submission-readiness/`. Task 5 is the exception: its tests were
found already passing and its report records no RED for them. What Task 5 does have is the
fix round's reproducing tests, written and run failing before their fixes: the submit-click
window in `_fill_and_submit` (the walk delegated to a parent click path that re-read the
button — `test_a_page_whose_button_changes_between_lookups_is_never_submitted`) and the
pilot's country lookup (`_facts_for` handed `location_for_application_url` an `Engine`, so
every stored posting's country read as `None`). Both RED runs are recorded in the Task 5
report's fix-round section.

## 7 — New dependencies

| Package | Task | Justification |
|---|---|---|
| `pypdf>=5.0` | 1 | pure Python, no external binary, BSD-licensed; reads a PDF's text layer without a rendering engine. The alternative (`pdftotext`) adds an OS-level binary the deployment must provide |

Nothing else was added: the queue, the validation, the capability check and the pilot
are all existing machinery.

## 8 — Open items

1. **The pilot has not been run against a real posting.** §5.5 is the protocol; the
   findings section is empty on purpose. The task's measurement half is the human's
   next step.
2. **The `SUBMISSION_POLICY` was read only where the approval was accepted, and the
   worker now re-reads it.** This was found by the whole-branch review and fixed in
   this workstream's fix pass (`src/runs/worker.py`): moving execution onto the queue
   widened the gap from milliseconds to an unbounded queue delay, so a policy flip
   between the decision and the run would not have bound. Fixed, with the refused
   case and the allowed case both pinned.
3. **`src/api/routes/applications.py:685` hands `location_for_application_url` a
   `Session.get_bind()` (an `Engine`) where a `sessionmaker` is expected**, so the
   posting's country is always `None` and the country-qualified work-authorization
   fact (WS-25c) is **inert on the API prepare path**. This is **pre-existing** — it
   was committed with WS-25c (`a4f8673`) and is not WS-32's code; the pilot's identical
   call was fixed in Task 5. It fails safe (the question goes to a human), which is
   why nothing surfaced it. The fix is one line plus a test that drives the route with
   a seeded listing, and it belongs to the next workstream.
4. **The button still says "Approve and submit"** while the route now answers 202 + a
   run id. The *result* rendering was fixed in this pass (the console distinguishes
   accepted-and-queued from submitted, with the run id shown and the generated types
   regenerated); the button's own copy is a residual wording item.
5. **`submission.uncertain` needs a surface.** The uncertain attempt is recorded as a
   run event and the approval row stays `APPROVED`, so an operator looking only at the
   approvals list sees a decided approval — not that its outcome is unknown. Until the
   console surfaces the event where the operator decides, it will be missed in
   practice.
5. **The at-most-once guard treats `FAILED` as "already submitted".** Correct under
   the reading that a failed row cannot be safely retried, but it means no automatic
   path re-attempts a genuinely failed submission; recovery is a human act (prepare
   again, which creates a new approval).
6. **`docs/PROJECT_PLAN.md` and `docs/implementation/06-security-preconditions.md`
   still under-describe the PDF support and the two-layer capability refusal** — the
   historical records were left as they are; README was corrected in Task 1.
7. **Deferred minors** are listed per task in the SDD ledger
   (`.superpowers/sdd/2026-11-14-submission-readiness/progress.md`): the mojibake
   threshold is a judgement call bounded by the fixtures; the encrypted fixture is not
   byte-reproducible; `enqueue_submission` is missing from `src/runs/service.py`'s
   `__all__`; the submission constants live in `src/runs/embedding.py`, which is not
   where a reader hunting for "submission" would look; `test_ci_gate.py`'s browser-file
   list was updated by this task and is a tripwire, not a proof.
