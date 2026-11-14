# Submission Readiness (WS-32) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the submission path genuinely usable — a real résumé format, a validated payload against the provider's own published contract, execution that survives a long browser run, and an assist-mode pilot that is the safest ground for a first real application.

**Architecture:** Five independent tasks, ordered by blocking severity. A PDF résumé is read (today it is refused outright). The prepared payload is validated against Greenhouse's **documented** submission contract before anything is submitted, because the provider explicitly does not validate it for us. The approve→submit hop moves off the synchronous HTTP request onto the existing WS-18 durable queue. The adapter-layer self-check the registry docstring already claims exists is made true. Finally an assist-mode pilot that prepares and drives the form up to the human's submit key.

**Tech Stack:** Python 3.13, FastAPI, Pydantic v2, Playwright, pypdf (new), pytest; the existing WS-18 durable queue in `src/runs/`.

**Spec:** This plan is its own spec (it opens a new workstream). On execution the spec lands in `docs/implementation/32-submission-readiness.md`, and the `00-OVERVIEW.md` status line gains the WS-32 row. It argues from the M5 direction recorded 2026-10-22 and from `docs/SECURITY.md` §14.

---

## Phase 0 — The verification that shaped this plan

The user supplied research material claiming that major ATS platforms (Greenhouse, Lever, Ashby, Workable, Recruitee, Workday) **allow third-party agents to submit candidate applications over an API**, and asking for a plan to exploit that. I verified the claim against primary sources before planning against it. **The claim is partly true and false in the way that matters.**

### What the material gets right

Greenhouse genuinely has an application-submission endpoint, and I recovered its exact contract from Greenhouse's own documentation source (`grnhse/greenhouse-api-docs`, `source/includes/job-board/_applications.md`):

```
POST https://boards-api.greenhouse.io/v1/boards/{board_token}/jobs/{job_id}
Authorization: Basic <API_KEY>        # the username IS the key; no password
Content-Type: multipart/form-data | application/json
```

The field names it documents are real and are the useful artefact of all of this:

| Group | Fields |
|---|---|
| Identity | `first_name`, `last_name`, `email`, `phone` |
| Address | `location`, `latitude`, `longitude`, `country_short_name` |
| Documents | `resume` (file) / `resume_text`, `cover_letter` (file) / `cover_letter_text` |
| Custom questions | `question_{id}`, `question_{id}_url` + `_filename`, `question_{id}_content` (base64) + `_filename` |
| Structured history | `educations[][school_name_id]`, `degree_id`, `discipline_id`, dates; `employments[][company_name]`, `title`, dates, `current` |
| Consent | `data_compliance[gdpr_processing_consent_given]`, `[gdpr_retention_consent_given]`, `[gdpr_demographic_data_consent_given]` |
| Demographics | `demographic_answers[][question_id]` + `answer_options[][answer_option_id]` |
| Provenance | `mapped_url_token`, `applicant_ip` |

### What the material gets wrong — and it decides the architecture

**The API key belongs to the employer, not to us.** Greenhouse's own words, from the same document:

> "the HTTP Basic Auth API token is a secret key. Any form posts should be **proxied by your own servers**. Any direct post to the /applications POST method would reveal your secret key to anybody that views source"
> "the Basic Auth username is **your API key (found on the API Credentials page)**"

"Your own servers" is the **hiring company's** servers — Greenhouse's developer index describes this API's purpose as "Build careers pages with a unique look and feel, construct department-level pages and more", i.e. it exists so a company can host its own board. The key is issued to the employer for its own board.

Live confirmation (read-only probes, 2026-11-14):

| Probe | Result |
|---|---|
| `GET boards-api.greenhouse.io/v1/boards/stripe/jobs` | **200** — the read API is public |
| `POST .../boards/anthropic/jobs/{id}` with no credential | **401 `HTTP Basic: Access denied.`** |
| `POST api.ashbyhq.com/applicationForm.submit` | **401 `Unauthorized`** |
| `POST api.lever.co/v0/postings/{token}/{id}` | **400** — not a public submit route |
| `job-boards.greenhouse.io/api/v1/boards/{token}/jobs` | **404** — no public JSON API on the new host |

**Conclusion: a third-party agent cannot submit an application to a company's Greenhouse board without that company's cooperation.** The endpoint is real; the credential is not ours to hold. Any plan that assumed otherwise would be building on a false premise.

This is why the plan below does **not** add an API submission channel. It uses the one thing the material legitimately gave us — the **documented field contract** — as a *validator*, and keeps the submission path where the project already decided it belongs: the browser, with a human in the loop.

### Two further findings from the same verification

1. **The provider does not validate required fields.** Greenhouse, verbatim: *"Note that when submitting an application through this method, Greenhouse will not confirm the inclusion of required fields. Validation for required fields must be done on the client side, as Greenhouse will not reject applications that are missing required fields."* A submission missing a required answer therefore **succeeds silently and incompletely**. That is a real risk for the browser path too, and it is what Task 2 addresses.

2. **`latitude` / `longitude` / `country_short_name` are submission fields, and the corpus already contains a Greenhouse geocoding service** (`api-geocode-earth-proxy.greenhouse.io`, seen in the board page). This corroborates the `Latitude`/`Longitude` gap WS-25c left open (§11.5) — those fields are not decoration, they are part of the submit contract.

---

## Global Constraints

- **Python is `env/Scripts/python.exe`**; `pytest` is not on PATH. Run tests as `cmd.exe /c "env\Scripts\python.exe -m pytest ..."`, or `./env/Scripts/python.exe -m pytest` from Git Bash.
- **Lint gate:** `env/Scripts/python.exe -m ruff check src tests scripts` must be clean.
- **A test that never failed proves nothing.** Each task's test is written and run before its implementation; the expected failure is recorded.
- **The DNS flake is environmental.** Run `tests/test_jobs.py` **serially**; under `-n 4` it flakes on `api.ashbyhq.com` and `remotive.com`. Do not debug it.
- **Do not `git add -A`** — a concurrent session may have in-flight files. Stage explicit paths.
- **Do not commit or push unless asked.** Commit style when asked: lowercase conventional subject, a short prose body explaining *why*, ending in a workstream tag — e.g. `feat: a PDF résumé is read, not refused (ws-32)`.
- **No new dependency without justification.** This plan adds exactly one: `pypdf` (Task 1), pure-Python, no external binary, justified below.
- **The submission safety invariants are not negotiable** and no task may weaken them: `AUTO_SUBMIT` stays unreachable (`src/security/policy.py:63`), the capability matrix stays the gate (`src/security/registry_setup.py`), consent and demographic questions are never auto-answered (`src/applications/form_plan.py:122`), and a submission without its evidence artifacts is never reported as a success (`src/applications/fake_ats_adapter.py:685`).
- **Never fabricate.** A field the profile does not state is left unanswered and the question goes to a human. This is what WS-25c's three-valued `may_work_in` encodes; no task may flatten it.

## Review Focus

Input classes and failure modes these tasks imply but whose happy-path test does not exercise them. Each is pinned by the task named.

1. **A PDF that is a scan (images, no text layer)** must fail with a readable reason, not parse to an empty profile. Task 1.
2. **A PDF whose text extracts as garbage** (bad encoding, CID fonts, ligatures) must be reported rather than silently producing a nonsense profile. Task 1.
3. **A payload missing a field Greenhouse requires but does not validate** must be caught by us before submission. Task 2.
4. **A submission that takes longer than the HTTP request** must not be lost, and must not leave the approval row in a state that lies. Task 3.
5. **A process crash mid-submission** must leave the application recoverable and must never report success. Task 3.
6. **An adapter that holds no SUBMIT capability** must refuse at the adapter layer too, not only at the node gate. Task 4.

---

## Task 1: A PDF résumé is read, not refused

**Why first.** This blocks the product for a large share of real users. `src/resume/parser.py:85` currently raises `ValueError("Unsupported resume format: ... (use .docx or .txt)")` for anything that is not `.docx`, `.txt` or `.md`, and no PDF library is declared. ATS upload fields conventionally want a PDF, and Greenhouse's own submission example uses one — so the system cannot accept the format its target ATS expects.

**Files:**
- Modify: `pyproject.toml` (add `pypdf>=5.0` to `dependencies`)
- Modify: `src/resume/parser.py:61-85` (add a PDF reader beside `_read_docx_lines`)
- Test: `tests/test_ws32_pdf_resume.py` (create)

**Interfaces:**
- Consumes: `_read_docx_lines(path) -> list[tuple[str, bool]]` (exists; the bool is "is a heading"), and the public `parse_resume(file_path: str) -> CandidateProfile` (`src/resume/parser.py:460` — note it takes a **string**, so the test must pass `str(FIXTURES / "resume_with_text.pdf")`, and `_read_lines` is where the suffix dispatch lives).
- Produces: `_read_pdf_lines(path) -> list[tuple[str, bool]]`, and `.pdf` accepted by the suffix dispatch inside `_read_lines`.

**Dependency justification (required by AGENTS.md).** `pypdf` is pure Python, ships no external binary, is BSD-licensed, and reads the text layer of a PDF without a rendering engine. The alternative — shelling out to `pdftotext` — would add an OS-level binary the deployment must provide, which the project's Windows dev environment makes worse, not better. Nothing here writes PDFs, so a heavier toolkit (`PyMuPDF`) would be unjustified weight.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_ws32_pdf_resume.py`:

```python
"""WS-32 · A PDF résumé is parsed, and a PDF we cannot read says so.

`.pdf` is the format ATS upload fields expect — Greenhouse's own submission
example posts a PDF — and the parser refused it outright: a candidate whose
résumé is a PDF could not use the system at all.

The hard part is not extracting text; it is refusing to invent it. A scanned
PDF has no text layer and a CID-font PDF extracts as mojibake. Both must be
reported, because a profile built from mojibake is a fabricated profile.

The fixtures are **checked-in binaries** under `tests/fixtures/`, the same
convention `tests/fixtures/Ahmad_Hassan_AI_Engineer_Resume.docx` already
follows. `pypdf` reads text layers but deliberately does not write them, so a
generated fixture would be a test of pypdf's writer rather than of our reader.
Four small files, each one shape:
`resume_with_text.pdf`, `resume_scanned.pdf` (an image page, no text layer),
`resume_mojibake.pdf`, `resume_encrypted.pdf`.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from src.resume.parser import parse_resume

FIXTURES = Path(__file__).parent / "fixtures" / "pdf"


def test_a_pdf_resume_is_parsed() -> None:
    """The happy path: a real text layer extracts, and the profile is populated."""
    profile = parse_resume(str(FIXTURES / "resume_with_text.pdf"))

    assert profile.personal_information.name == "Ada Lovelace"
    assert profile.personal_information.email == "ada@example.com"
    # Not just the contact block — the body has to survive extraction, or the
    # profile has no experience and the matcher has nothing to work with.
    assert profile.experience


def test_a_scanned_pdf_is_refused_with_a_readable_reason() -> None:
    """No text layer means no profile — never an empty one presented as a parse.

    This is the failure a real user hits: a phone-scanned résumé is an image in
    a PDF wrapper, and silently returning a blank profile would have them
    believe the upload worked.
    """
    with pytest.raises(ValueError, match="no extractable text"):
        parse_resume(str(FIXTURES / "resume_scanned.pdf"))


def test_a_mojibake_pdf_is_refused_rather_than_parsed() -> None:
    """A text layer of replacement characters is not text.

    A profile built from ``\\ufffd`` runs would pass every downstream validator
    and produce a résumé full of rubbish, so the refusal belongs here.
    """
    with pytest.raises(ValueError, match="not readable text"):
        parse_resume(str(FIXTURES / "resume_mojibake.pdf"))


def test_a_corrupt_pdf_is_refused_not_raised_as_a_crash(tmp_path: Path) -> None:
    """`pypdf`'s own exception must not surface to the user as a 500."""
    path = tmp_path / "broken.pdf"
    path.write_bytes(b"%PDF-1.4\nthis is not a valid pdf body")

    with pytest.raises(ValueError, match="could not be read"):
        parse_resume(str(path))


def test_an_encrypted_pdf_is_refused_with_its_own_reason() -> None:
    """A password-protected résumé is a user problem with a user fix, and it
    must not read the same as a corrupt file."""
    with pytest.raises(ValueError, match="password"):
        parse_resume(str(FIXTURES / "resume_encrypted.pdf"))


def test_the_docx_and_text_paths_are_unchanged() -> None:
    """The new reader must not become the only one."""
    docx = Path(__file__).parent / "fixtures" / "Ahmad_Hassan_AI_Engineer_Resume.docx"
    assert parse_resume(str(docx)).personal_information.name

    txt = tmp_path / "resume.txt"
    txt.write_text("Ada Lovelace\nada@example.com\n", encoding="utf-8")
    assert parse_resume(str(txt)).personal_information.email == "ada@example.com"


def test_the_upload_endpoint_accepts_a_pdf() -> None:
    """The parser is not the boundary — the upload validation is.

    A parser that accepts `.pdf` behind a validator that rejects it is worse
    than neither: the user is refused a format the system can now read.
    """
    from src.api.routes.resumes import _is_supported_resume  # adjust to the real predicate

    assert _is_supported_resume("resume.pdf")
    assert _is_supported_resume("RESUME.PDF")  # case must not decide it
    assert not _is_supported_resume("resume.exe")
```

**Producing the four fixtures** (a one-time step, recorded so the binaries are not unexplained blobs): `resume_with_text.pdf` is exported from a DOCX via Word or LibreOffice; `resume_scanned.pdf` is that same page rasterized so it has an image but no text layer (`pdftoppm`/a print-to-PDF of a screenshot); `resume_mojibake.pdf` is produced by saving text in a symbolic CID font; `resume_encrypted.pdf` is `resume_with_text.pdf` re-saved with a user password. Each is a few KB.

- [ ] **Step 2: Run it to verify it fails**

Run: `./env/Scripts/python.exe -m pytest tests/test_ws32_pdf_resume.py -v`
Expected: FAIL — `ValueError: Unsupported resume format: '.pdf' (use .docx or .txt)`, and the `pypdf` import itself fails until the dependency lands.

- [ ] **Step 3: Add the dependency and implement the reader**

Add `pypdf>=5.0` to `pyproject.toml` under `dependencies`, install it into `env/`, then add `_read_pdf_lines` to `src/resume/parser.py` and dispatch `.pdf` to it. Four refusals, each with its own message, because they are four different problems for the user: no text layer (a scan — "extract the text, or upload the DOCX"), text that is mostly replacement characters ("not readable text"), an encrypted file ("remove the password"), and a file `pypdf` cannot open at all ("could not be read"). Heading detection reuses whatever heuristic `_read_docx_lines` already applies to a short capitalised line, so a PDF's section headings behave like a DOCX's.

- [ ] **Step 4: Verify it passes, then run the résumé suites**

Run: `./env/Scripts/python.exe -m pytest tests/test_ws32_pdf_resume.py tests/test_parsing.py tests/test_resume.py -q`
Expected: PASS, including the existing DOCX/TXT/MD coverage.

- [ ] **Step 5: Check the upload boundary too**

Read the upload validation (`grep -rn "\.docx\|content_type\|magic" src/api/routes/resumes.py src/security/`) and add `.pdf` wherever an allowed-extension or content-type list exists. A parser that accepts `.pdf` behind a validator that rejects it is worse than neither — the user gets a rejection for a format the system can now read.

Run: `./env/Scripts/python.exe -m pytest tests/test_uploads.py -q` (adjust to the real file name).

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml src/resume/parser.py src/api/routes/resumes.py tests/test_ws32_pdf_resume.py
git commit -m "feat: a PDF résumé is read, not refused (ws-32)

`.pdf` is the format ATS upload fields expect — Greenhouse's own submission
example posts one — and the parser refused it outright, so a candidate whose
résumé is a PDF could not use the system at all.

pypdf is the one new dependency: pure Python, no external binary, and it reads
the text layer without a rendering engine. Nothing here writes PDFs, so a
heavier toolkit would be unjustified weight.

The refusals matter more than the parsing. A scanned PDF has no text layer and
a CID-font PDF extracts as mojibake; both are reported rather than turned into
a profile, because a profile built from mojibake is a fabricated profile."
```

---

## Task 2: The prepared payload is validated against the provider's published contract

**Why.** Verified above: Greenhouse *does not validate required fields* on submission — "Greenhouse will not reject applications that are missing required fields." A payload missing a required answer therefore **submits successfully and incompletely**: the candidate believes they applied, the employer receives an application with a blank, and nothing anywhere reports an error. Our own prepare path already decides what is unanswered (`needs_human` verdicts, `blocking_questions`), but nothing checks the *assembled payload* against the provider's contract before it is submitted.

This is where the research material genuinely pays off. Its documented field list is a real contract we can validate against, and it is the only part of that material that survives verification.

**Files:**
- Create: `src/applications/greenhouse_contract.py`
- Test: `tests/test_ws32_payload_contract.py` (create)
- Modify: `src/graph/nodes.py` (`submit_node`, the pre-submit check at ~line 211-237)

**Interfaces:**
- Consumes: `PreparedApplication` (`prepared.prepared_fields: dict[str, str]`, `prepared.request`, `prepared.resume_path`), and the form plan's `blocking_questions` (a required question the agent cannot answer).
- Produces:
  - `REQUIRED_FIELDS: tuple[str, ...]` — the fields Greenhouse documents as needed for a complete application (`first_name`, `last_name`, `email`, `phone`, `resume` or `resume_text`)
  - `custom_question_fields(schema) -> dict[str, str]` — maps a form question's `field_names` to the `question_{id}` form the contract uses
  - `validate_against_contract(prepared, *, schema=None) -> ContractReport` with `missing: list[str]`, `consent_unanswered: list[str]`, and `is_complete: bool`
  - `ContractReport` — a dataclass, so the report is readable in a log and assertable in a test

**The rule.** A payload that is incomplete is **not submitted** and the application stays at `needs_human` with the missing field names. This is the same fail-closed shape the project already uses for a blocking question (`docs/implementation/25-...md` §9.2); what is new is that it inspects the finished payload rather than the plan.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_ws32_payload_contract.py`:

```python
"""WS-32 · We validate the payload because the provider does not.

Greenhouse's documentation says it plainly: "Greenhouse will not reject
applications that are missing required fields." So an incomplete submission
SUCCEEDS and is silently incomplete — the candidate believes they applied and
the employer receives a blank. The contract below is Greenhouse's own published
field list, recovered from its documentation source; it is the only part of the
researched material that survived verification against the live API.
"""

from __future__ import annotations

import pytest

from src.applications.contracts import ApplicationRequest, PreparedApplication
from src.applications.greenhouse_contract import (
    REQUIRED_FIELDS,
    validate_against_contract,
)


def _prepared(**fields) -> PreparedApplication:
    return PreparedApplication(
        request=ApplicationRequest(
            job_title="Backend Engineer",
            company_name="Acme",
            job_url="https://boards.greenhouse.io/acme/jobs/1",
        ),
        prepared_fields=fields,
    )


def test_a_complete_payload_is_complete() -> None:
    report = validate_against_contract(
        _prepared(
            first_name="Ada",
            last_name="Lovelace",
            email="ada@example.com",
            phone="+44 20 7946 0000",
        )
    )
    assert report.is_complete
    assert report.missing == []


def test_a_missing_identity_field_is_reported_by_name() -> None:
    report = validate_against_contract(_prepared(first_name="Ada", email="ada@example.com"))
    assert not report.is_complete
    assert "last_name" in report.missing
    assert "phone" in report.missing


def test_a_text_resume_satisfies_the_resume_requirement() -> None:
    """`resume` is a file OR `resume_text` — the contract accepts either."""
    assert validate_against_contract(
        _prepared(
            first_name="Ada", last_name="Lovelace",
            email="ada@example.com", phone="+1",
            resume_text="Experience: ...",
        )
    ).is_complete


def test_an_uploaded_file_satisfies_the_resume_requirement() -> None:
    prepared = _prepared(
        first_name="Ada", last_name="Lovelace", email="ada@example.com", phone="+1"
    )
    prepared.resume_path = "data/resumes/profile-1.pdf"
    assert validate_against_contract(prepared).is_complete


def test_a_payload_with_no_resume_at_all_is_incomplete() -> None:
    report = validate_against_contract(
        _prepared(first_name="Ada", last_name="Lovelace", email="ada@example.com", phone="+1")
    )
    assert not report.is_complete
    assert "resume" in report.missing


def test_a_consent_field_left_unanswered_is_reported_separately() -> None:
    """Consent is not "missing" — it is a human's to give, and the distinction
    is what stops a missing consent from reading as a bug the agent should fix."""
    report = validate_against_contract(
        _prepared(
            first_name="Ada", last_name="Lovelace",
            email="ada@example.com", phone="+1", resume_text="x",
        ),
        consent_required=("data_compliance[gdpr_processing_consent_given]",),
    )
    assert report.is_complete
    assert report.consent_unanswered == [
        "data_compliance[gdpr_processing_consent_given]"
    ]


def test_the_required_field_list_is_the_documented_one() -> None:
    assert set(REQUIRED_FIELDS) == {"first_name", "last_name", "email", "phone"}
```

- [ ] **Step 2: Run it to verify it fails**

Run: `./env/Scripts/python.exe -m pytest tests/test_ws32_payload_contract.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.applications.greenhouse_contract'`.

- [ ] **Step 3: Implement the contract module**

Create `src/applications/greenhouse_contract.py`. It is a **policy table plus one function**, in the shape `src/jobs/board_metadata.py` already uses: the documented field names as data, with the function reading them. Document in the module docstring that these names come from Greenhouse's published application documentation (with the URL) and that the endpoint itself is employer-authenticated — so the list is used to *validate ours*, never to submit.

- [ ] **Step 4: Wire it into the submit node as a fail-closed gate**

In `src/graph/nodes.py`, before the adapter is called, run the validation. On an incomplete payload: set `state.submission_result = ApplicationResult(success=False, status="incomplete_payload", message=...)` naming the missing fields, record the audit row, and return — exactly the shape the existing `permission_denied` branch uses (lines 216-230). Do **not** raise: a prepare-time defect must be a reported outcome, not a crash.

Run: `./env/Scripts/python.exe -m pytest tests/test_ws32_payload_contract.py tests/test_application_workflow.py tests/test_evidence.py tests/test_permissions.py -q`

- [ ] **Step 5: Commit**

```bash
git add src/applications/greenhouse_contract.py src/graph/nodes.py tests/test_ws32_payload_contract.py
git commit -m "feat: the payload is checked against the provider's own contract (ws-32)

Greenhouse's documentation is explicit that it does not validate required
fields: a submission missing an answer succeeds and is silently incomplete.
The candidate believes they applied, the employer receives a blank, and nothing
reports an error.

The field list is Greenhouse's own, recovered from its published application
documentation. It is used to validate ours and never to submit: verification of
that documentation against the live API showed the submit endpoint is
employer-authenticated (HTTP Basic with the hiring company's key, 401 without
it), so a third-party agent cannot post an application without that company's
cooperation.

An incomplete payload is not submitted. The application stops with the missing
field names, the same fail-closed shape a blocking question already uses."
```

---

## Task 3: A submission survives the request that started it

**Why.** Verified: the approve route calls `execute_approved` **synchronously in the request thread** (`src/api/routes/applications.py:931` → `src/graph/executor.py:159`, `graph.invoke` with a `MemorySaver`). Every submission so far ran against the local fake ATS on localhost, where that is fine. A real board is a network round trip plus a browser walk — the WS-08 suite's own runs take tens of seconds. An HTTP request that long will be cut by any proxy or client timeout, and a crash loses the run with no recovery, while the approval row is left mid-flight.

The project already built the answer for exactly this class of problem: the WS-18 durable queue (`src/runs/`), used by the refresh and embedding paths. This task moves the submission onto it.

**Files:**
- Modify: `src/runs/` (a new run kind — read `src/runs/queue.py` and the existing `embedding`/`refresh`/`reconcile` kinds to follow the pattern)
- Modify: `src/api/routes/applications.py:895-944` (the approve handler enqueues instead of executing)
- Modify: `scripts/run_worker.py` (the worker drains the new kind)
- Test: `tests/test_ws32_durable_submission.py` (create)

**Interfaces:**
- Consumes: the WS-18 queue and its lease mechanics — **all in `src/runs/queue.py`** (there is no separate `lease.py`; read `queue.py`, `worker.py`, `state.py` and `embedding.py` first, and do not reimplement any of it) — and `execute_approved` (`src/graph/executor.py:93`).
- Produces: a `submission` run kind whose payload carries `{approval_id, workflow_id, owner_id}`; the approve handler returns **202 + a run id** with the approval row at a new `EXECUTING`-equivalent state, and the worker performs the same `execute_approved` call the route performs today.

**The invariants this task must not break.** The approval row must never claim `EXECUTED` before the work ran; a crash must leave the run reclaimable by the lease and the row recoverable (the admin recovery surface at `/api/admin/runs/{run_id}` already exists); and the response the operator gets must distinguish "accepted" from "submitted" — the console already has that vocabulary in the refresh flow.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_ws32_durable_submission.py`:

```python
"""WS-32 · The approve returns accepted, not submitted.

The approve route ran the whole submission inline, with a MemorySaver and no
recovery: on the local fake ATS that is invisible, and against a real board it
is an HTTP request that outlives its client and a run a crash can lose.

The WS-18 queue already solved this for the refresh and the embedding drain, so
this reuses it rather than inventing a second mechanism.
"""

from __future__ import annotations

import pytest


def test_approving_enqueues_a_submission_run(client, approved_payload) -> None:
    response = client.post(
        f"/api/applications/{approved_payload.approval_id}/approve", json={}
    )
    assert response.status_code == 202
    body = response.json()
    assert body["run_id"]
    # The wording matters: the operator must be able to tell "queued" from
    # "applied". A 200 with a success-shaped body would be a false claim.
    assert "submitted" not in body["status"].lower()


def test_the_approval_row_is_not_marked_executed_before_the_run_finishes(
    client, approved_payload, db_session
) -> None:
    """A row that reads EXECUTED while the work is queued is a lie in the audit
    trail — the one place this system promises not to lie."""
    client.post(f"/api/applications/{approved_payload.approval_id}/approve", json={})

    row = db_session.get(ApprovalRequestDB, approved_payload.approval_id)
    assert row.status is ApprovalStatus.APPROVED  # decided, not executed
    assert row.status is not ApprovalStatus.EXECUTED


def test_the_worker_executes_the_queued_submission(
    approved_payload, db_session, run_worker_once
) -> None:
    """Draining the queue performs the same call the route used to."""
    run_worker_once(kind="submission")

    row = db_session.get(ApprovalRequestDB, approved_payload.approval_id)
    assert row.status in {ApprovalStatus.EXECUTED, ApprovalStatus.FAILED}


def test_a_submission_that_crashes_mid_run_is_reclaimable(
    approved_payload, db_session, run_worker_once, expire_lease
) -> None:
    """The lease expires, the run is retried, and the row never reads EXECUTED."""
    run_worker_once(kind="submission", crash_after_claim=True)
    row = db_session.get(ApprovalRequestDB, approved_payload.approval_id)
    assert row.status is not ApprovalStatus.EXECUTED

    expire_lease()
    run_worker_once(kind="submission")  # reclaimed and completed


def test_a_retried_submission_does_not_submit_twice(
    approved_payload, db_session, run_worker_once
) -> None:
    """At-most-once matters: a double submission is a real harm, not a nuisance.

    The crash lands *after* the board accepted the application, so the retry
    must refuse rather than apply again.
    """
    counter = _CountingAdapter()
    run_worker_once(kind="submission", adapter=counter, crash_after_submit=True)
    run_worker_once(kind="submission", adapter=counter)

    assert counter.submit_calls == 1


def test_no_code_path_executes_a_submission_inside_a_request_thread() -> None:
    """The inline path is gone, not merely unused.

    A leftover call is a path that runs again the moment someone re-wires the
    route, and the failure it causes (a timeout mid-submission) is one nobody
    would connect back to this refactor.
    """
    source = (ROOT / "src" / "api" / "routes" / "applications.py").read_text("utf-8")
    assert "execute_approved" not in source
```

- [ ] **Step 2: Run it to verify it fails**

Run: `./env/Scripts/python.exe -m pytest tests/test_ws32_durable_submission.py -v`
Expected: FAIL — the approve handler returns 200 and executes inline (`execute_approved` is still called at `applications.py:931`).

- [ ] **Step 3: Read the queue before adding a kind**

Run: `sed -n '1,80p' src/runs/queue.py; ls src/runs/`. Report the existing kind-dispatch mechanism in the plan's ledger. Do not add a second queue, a thread pool, or `BackgroundTasks` — all three are the mistake this task exists to undo.

- [ ] **Step 4: Add the run kind and the worker branch**

Follow the existing kind exactly. **Idempotency is the part to get right**: the worker must refuse to submit an approval whose row already records a submission, so a lease retry after a crash that happened *after* the board accepted the application cannot submit it twice.

- [ ] **Step 5: Verify, including the recovery surface**

Run: `./env/Scripts/python.exe -m pytest tests/test_ws32_durable_submission.py tests/test_durable_queue.py tests/test_runs_api.py tests/test_admin_recovery.py tests/test_submit_api.py tests/test_approval_flow.py -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/runs/ src/api/routes/applications.py scripts/run_worker.py tests/test_ws32_durable_submission.py
git commit -m "feat: a submission outlives the request that started it (ws-32)

The approve route ran the whole submission inline, with a MemorySaver and no
recovery. Against the local fake ATS that is invisible; against a real board it
is an HTTP request that outlives its client, and a crash loses the run while the
approval row is left mid-flight.

The WS-18 queue already solved this for the refresh and the embedding drain, so
this adds a run kind rather than a second mechanism. The approve now returns
accepted with a run id, and the row is not marked EXECUTED until the work has
actually run — a row that says executed while the work is queued would be a lie
in the audit trail, which is the one place this system promises not to lie.

Submission is at-most-once: the worker refuses an approval that already records
a submission, so a lease retry after a crash cannot apply twice."
```

---

## Task 4: The adapter-layer refusal the docstring already claims

**Why.** `src/security/registry_setup.py:20-21` states: *"the adapters themselves refuse a submit they were not granted as a second layer."* Verified: only `greenhouse_adapter.py:108` and `lever_adapter.py:51` do. `fake_ats_adapter.py` has no self-check — it holds SUBMIT so the gap is invisible today, but the claim is false as written, and the fake ATS is the adapter a future change is most likely to copy.

This is the same class of defect WS-26b fixed in `registry.py`: a docstring that overclaims, which is worse than a missing one because a reader relies on it instead of reading the code. A test already exists (`tests/test_permissions.py` pins that the real adapters refuse), so the gap is specifically the fake ATS and the general claim.

**Files:**
- Modify: `src/applications/fake_ats_adapter.py` (a capability self-check at the top of `submit`)
- Modify: `src/security/registry_setup.py:20-21` (make the sentence true, or narrow it to what is true)
- Test: `tests/test_ws32_adapter_selfcheck.py` (create)

**Interfaces:**
- Produces: `ApplicationAdapter.require_capability(self, level, registry=None) -> None` raising `PermissionError` — a small helper on the base class (`src/applications/contracts.py`) so the check has one implementation rather than one per adapter, and each adapter's `submit`/`verify` calls it first.

- [ ] **Step 1: Write the failing tests**

```python
"""WS-32 · "The adapters themselves refuse" must be true of every adapter.

`registry_setup.py` claims the adapter layer refuses a submit it was not granted
as a second layer. Only greenhouse and lever do; the fake ATS — the adapter a
new adapter is most likely to be written from — does not. A docstring that
overclaims is worse than a missing one.
"""


def test_every_adapter_refuses_a_capability_it_does_not_hold() -> None:
    """Parametrized over the registered adapters, so a new one is covered the
    day it is registered rather than the day someone remembers."""
    from src.applications import ADAPTERS
    from src.security.registry_setup import build_registry

    for name, adapter in ADAPTERS.items():
        registry = PermissionRegistry()  # grants nothing
        with pytest.raises(PermissionError):
            adapter.require_capability(CapabilityLevel.SUBMIT, registry=registry)


def test_the_fake_ats_refuses_submit_when_the_registry_withholds_it() -> None:
    """The specific gap: the fake ATS holds SUBMIT today, so nothing exposes
    its missing check — and it is the adapter a new adapter is copied from."""
    from src.applications.fake_ats_adapter import FakeAtsAdapter

    empty = PermissionRegistry()
    with pytest.raises(PermissionError):
        FakeAtsAdapter().require_capability(CapabilityLevel.SUBMIT, registry=empty)


def test_the_helper_is_on_the_base_class_not_copied_per_adapter() -> None:
    """One implementation, or the next adapter forgets it — which is exactly
    how this gap opened."""
    from src.applications.contracts import ApplicationAdapter

    assert hasattr(ApplicationAdapter, "require_capability")
    # And no adapter re-implements it locally.
    for path in (ROOT / "src" / "applications").glob("*_adapter.py"):
        assert "def require_capability" not in path.read_text("utf-8"), path
```

- [ ] **Step 2: Run it to verify it fails.** Expected: FAIL — `FakeAtsAdapter` has no `require_capability`, and the base class does not define one.

- [ ] **Step 3: Add the helper and call it from every adapter's `submit`/`verify`.**

- [ ] **Step 4: Correct the docstring** at `registry_setup.py:20-21` so it describes what the code does after this change — and if any adapter still cannot self-check, say which and why.

- [ ] **Step 5: Run and commit**

Run: `./env/Scripts/python.exe -m pytest tests/test_ws32_adapter_selfcheck.py tests/test_permissions.py tests/test_application_adapter.py tests/test_browser_variants.py -q`

```bash
git add src/applications/contracts.py src/applications/fake_ats_adapter.py src/security/registry_setup.py tests/test_ws32_adapter_selfcheck.py
git commit -m "fix: every adapter refuses what it was not granted (ws-32)

`registry_setup.py` claimed the adapter layer refuses a submit it was not
granted as a second layer. Only greenhouse and lever did; the fake ATS did not,
and it is the adapter a new adapter is most likely to be written from.

The check moves to the base class so it has one implementation rather than one
per adapter — a check that is copied is a check the next adapter forgets, which
is how this gap opened."
```

---

## Task 5: The assist-mode pilot

**Why last, and why it is the one that matters.** Every other task here is preparation for a real submission. This is the real submission — and the verified findings say the safest form of it is **not** unattended. The research material's own taxonomy reaches the same conclusion from the other direction: "human-in-the-loop autofill... sits on much safer ground because a human is actively initiating the final submission." That matches the M5 direction recorded 2026-10-22: prepare everything, open the browser, fill the form up to the final submit, then hand the browser to the human.

The pilot's purpose is **measurement, not automation**: run one real posting and find out where it stops. That measurement decides which board shape to support first, instead of guessing.

**This task is not complete until a human has run it against one real posting.** Its deliverable therefore includes the run's findings, not only code.

**Files:**
- Create: `scripts/pilot_assist.py` (the runnable harness)
- Create: `src/applications/assist_adapter.py` (an adapter that fills and then stops)
- Test: `tests/test_ws32_assist_mode.py` (create)
- Create: `docs/implementation/32-submission-readiness.md` — the workstream doc, carrying the pilot's measured findings

**Interfaces:**
- Consumes: the WS-08 form walker (`src/applications/form.py` — the field map, the answer rule, `_drive_form` in the fake ATS adapter), the capability matrix, `assert_execution_allowed`.
- Produces: `AssistAdapter` with `name = "assist-playwright"`, holding `PREPARE` only — **not** `SUBMIT`. Its `submit` fills the form and then returns `ApplicationResult(success=False, status="awaiting_human_submit", ...)` with the browser left open. That is the whole design: the agent cannot press submit, because it does not hold the capability, and the capability matrix is what enforces it rather than a convention.

**The two things this must get right.** A fresh browser context per run (SEC-07) still applies, and the pilot must run with the allowlist enforcing a real board's domain — which means the operator's `ALLOWED_DOMAINS` has to include it, deliberately, per run. The pilot must refuse to start if the target domain is not allowlisted, rather than silently reaching a board the config did not intend.

- [ ] **Step 1: Write the failing tests**

```python
"""WS-32 · Assist mode is a capability, not a convention.

The agent fills the form and stops. It cannot press submit because it does not
hold SUBMIT — which is the point: the safety property is enforced by the
capability matrix, not by the code remembering to stop.
"""


def test_the_assist_adapter_holds_prepare_and_not_submit() -> None:
    """The safety property is the capability, not a comment."""
    from src.security.permissions import CapabilityLevel
    from src.security.registry_setup import build_registry

    capabilities = build_registry().capabilities("assist-playwright")
    assert CapabilityLevel.PREPARE in capabilities
    assert CapabilityLevel.SUBMIT not in capabilities


def test_its_submit_fills_the_form_and_returns_awaiting_human() -> None:
    result = AssistAdapter().submit(prepared)

    assert result.success is False
    assert result.status == "awaiting_human_submit"
    # It must say what it did, so the operator knows the form is waiting.
    assert "filled" in result.message.lower()


def test_the_browser_is_left_open_for_the_human() -> None:
    """A form filled and then closed is an expensive no-op — the human has to
    be able to press the button on the page the agent filled."""
    adapter = AssistAdapter()
    adapter.submit(prepared)
    assert adapter.browser_open is True


def test_the_pilot_refuses_a_target_outside_the_allowlist() -> None:
    """The pilot must not silently reach a board the config did not intend."""
    with pytest.raises(DisallowedDomainError):
        pilot_assist(url="https://boards.example.org/acme/jobs/1", profile_id="p1")


def test_a_human_submit_after_the_run_produces_verifiable_evidence() -> None:
    """The evidence comes from the page the human submitted on, and it is what
    `verify` reads — an assist run with no evidence is not verifiable and must
    not be reported as submitted."""
    result = assist_then_human_submits(fake_ats_server)
    assert result.evidence.confirmation_text
    assert result.evidence.screenshot_path
    verified = adapter.verify(result)
    assert verified.status in {"verified", "verification_failed"}
```

- [ ] **Step 2: Run it to verify it fails.** Expected: FAIL — `No module named 'src.applications.assist_adapter'`, and `assist-playwright` is not in the capability matrix.

- [ ] **Step 3: Implement the adapter and the harness.** The harness takes a job URL, prepares the application from a stored profile, opens the browser, fills what the evidence covers, prints what it could not answer, and waits.

- [ ] **Step 4: Run it against the local fake ATS first** — the flow must be proven end to end where a mistake is free.

- [ ] **Step 5: Run it once against one real posting, with the human present.** Record where it stopped: which questions it could not answer, which widgets it did not recognize, whether the page's own validation complained, and how long it took. This is the measurement the pilot exists for.

- [ ] **Step 6: Write the findings into `docs/implementation/32-submission-readiness.md`** and update `00-OVERVIEW.md`. A pilot task that produced no recorded measurement is not complete.

- [ ] **Step 7: Commit**

```bash
git add src/applications/assist_adapter.py scripts/pilot_assist.py tests/test_ws32_assist_mode.py docs/implementation/32-submission-readiness.md docs/implementation/00-OVERVIEW.md
git commit -m "feat: the pilot fills the form and hands over the submit (ws-32)

The first real submission, in the form the evidence supports: the agent
prepares everything, drives the form up to the final submit, and stops. It
cannot press submit because it does not hold SUBMIT — the safety property is
enforced by the capability matrix rather than by the code remembering to stop.

The purpose is measurement, not automation. One real posting, and a record of
where it stopped: the questions it could not answer, the widgets it did not
recognise, whether the page's own validation complained. That measurement
decides which board shape to support next instead of guessing."
```

---

## Where WS-26 continues, and in what order

These are the corpus workstream's remaining phases. They are **not** in this plan — each needs its own — but the order is a dependency chain and worth stating, because two of the phases are prerequisites for the third rather than independent.

**Recommended order: Phase 5 → CI wiring → Phase 4 → Phase 3 → Phase 6.**

1. **Phase 5 (crawl policy) first** — because robots.txt is described in the spec as "policy, not politeness... it settles the legal questions with the provider's own file", and it is the cheapest item on the list. It also adds the adaptive-cooling rule (a `Retry-After` over 60 s opens the circuit instead of sleeping), which `src/jobs/http_client.py` currently lacks.
2. **CI wiring for `scripts/verify_sources.py`** — the verifier exists and is tested but does not run in CI (`.github/workflows/ci.yml` has two jobs, `gate` and `browser`, and neither calls it). A provider renaming a field silently nulls every parser, and CI is where that should surface.
3. **Phase 4 (ordering and ceilings) before Phase 6** — not optional. Workday's documented "offset>2,000 repeats page one" is silent data corruption, so a big board cannot be added before ceilings exist.
4. **Phase 3 (proposals)** — low value on its own today. Boards are added by editing `.env`, and the SRS rule "the operator curates; the system may only propose" is currently satisfied by `enabled` being operator-set. Do it when a discovery helper exists to feed it.
5. **Phase 6 (the adapters), one provider at a time** — BambooHR (5,168 boards) is the largest gain and the spec's first. Each must fill the WS-23 fields or it re-introduces the ranking bias WS-23 removed; an adapter that leaves `seniority`/`salary` empty makes the corpus bigger and worse.

**One scale warning to carry into Phase 6.** The artifacts rebuild is **52.8 s** at 8,558 listings (measured 2026-11-13) and scales with corpus size. The 50,000 cap is therefore a **projection** of several minutes per cold start, not a measurement. Before the corpus grows an order of magnitude, the rebuild wants a plan of its own — the incremental path (§4a.2, built) removes only the per-listing half.

---

## Self-review

**Spec coverage.** Phase 0's verification is the spec for this plan's *decisions*: it is why Task 2 validates rather than submits, and why Task 5 is assist-mode. The five tasks cover the blocking gaps verified in Phase 0: PDF (Task 1), the unvalidated payload (Task 2), inline execution (Task 3), the false adapter-layer claim (Task 4), and the M5 direction's first phase (Task 5). The WS-26 order is stated with its dependency chain and the scale caveat. **Not covered, deliberately:** an API submission channel (the credential is the employer's), auto-submit (still unreachable by design), the `Latitude`/`Longitude` geocoding gap (a decision, not a task — noted in Phase 0 as corroborated by the submission contract), and WS-26's own phases (each gets its own plan).

**Step scan.** Every step names a file and a checkable result. Test steps carry the test names and assertions; implementation steps carry the signature and the specific rule, not the body. The two places where the body is genuinely underdetermined — the PDF reader's refusals and the queue's idempotency — state the rule instead, because the implementer must read the surrounding code either way.

**Type consistency.** `validate_against_contract(prepared, *, schema=None, consent_required=()) -> ContractReport` is defined once (Task 2) and consumed in the submit node under that name. `require_capability(level, registry=None)` is defined on the base class (Task 4) and called per adapter. `AssistAdapter` holds `PREPARE` only (Task 5) and its `submit` returns `status="awaiting_human_submit"`. The run kind (Task 3) carries `{approval_id, workflow_id, owner_id}`.

**Review Focus.** Six lines, each owned: 1 → Task 1 (`test_a_scanned_pdf_is_refused_with_a_readable_reason`), 2 → Task 1 (`test_a_mojibake_pdf_is_refused_rather_than_parsed`), 3 → Task 2 (`test_a_payload_with_no_resume_at_all_is_incomplete`), 4 → Task 3 (`test_the_approval_row_is_not_marked_executed_before_the_run_finishes`), 5 → Task 3 (`test_a_submission_that_crashes_mid_run_is_reclaimable` plus the at-most-once test), 6 → Task 4 (`test_every_adapter_refuses_a_capability_it_does_not_hold`).

**Proportion.** Five tasks against three verified defects and one unbuilt pilot; no function bodies except the test code and the two contract tables, which are data rather than logic.

## Execution handoff

The user asked for a plan, so this plan is the deliverable and it stops here. On approval the execution method is a choice: subagent-driven if per-task review is wanted (five tasks, and the interfaces between them are narrow), or inline if speed matters more. Tasks 1, 2 and 4 are independent and could run in parallel; **Task 3 must precede Task 5** (a pilot on an inline submission would time out), and Task 2 should land before Task 5 for the same reason a validation layer should exist before the first real submission.
