# Security Model for the Autonomous AI Job Application Agent

This document defines the security model for the autonomous job application system. It is a living document and must be updated whenever a new control is added, removed, or changed.

The system must be designed so that untrusted external content never gains authority over agent behavior, credentials, or submission actions.

## 1. Scope and purpose

This repository is building an autonomous job-application system that may eventually:

- parse resumes and candidate profiles
- search and normalize job listings
- rank and match jobs
- tailor resumes and cover letters
- automate browser-based application flows
- verify application submission
- persist application and audit data

This security model applies to:

- local Python application code
- FastAPI service boundaries
- browser automation flows
- external web pages and job platforms
- MCP tools and Cursor development-time tooling
- environment configuration and secrets
- data retention and privacy

This document intentionally distinguishes between:

- implemented controls
- planned controls
- not yet implemented controls

## 2. Current implementation status

_Reconciled 2026-10-21 (WS-11). This section used to describe the 2026-10-11 state — a minimal
FastAPI app and the Cursor configuration — while §5 and §12 in this same file described the
present. The document contradicted itself; the present is below._

### Implemented

**The runtime surface (WS-01 … WS-05, WS-10).**

- `src/config/settings.py` reads the environment with `python-dotenv` and fails loudly on an
  invalid value instead of silently falling back to a permissive default.
- `src/main.py` exposes the REST API, the middleware stack and the lifespan.
- `src/core/logging.py` configures logging with PII masking.
- `src/security/limits.py` holds every bound on how much work an untrusted caller can cause.

**The security controls (WS-06, WS-12).**

- production domain allowlist for navigation and fetch, enforced in runtime code
  (`src/security/allowlist.py`) — exact host matching, blocked internal hosts
- least-privilege permission model for the application adapters
  (`src/security/permissions.py`, `src/security/registry_setup.py`)
- two-phase application approval workflow with a persisted approver identity
  (`src/security/policy.py`, `src/db/approval.py`)
- file upload validation for resumes (`src/api/validation.py`) — type, size, real-file check
  and the zip-bomb guard
- append-only audit logging for resume upload, job search, match, and the whole application
  flow (`src/security/audit.py`, `src/db/audit.py`)
- submission verification with screenshot, navigation trace and an evidence-existence check
  (`src/applications/evidence.py`, `src/applications/fake_ats_adapter.py`)
- CAPTCHA/MFA detection that stops the flow (`src/security/page_guards.py`)
- PII masking in logs and audit rows (`src/security/redaction.py`, `src/core/logging.py`)
- SSRF protections for the job-source layer and internal-host blocking for navigation
  (`src/jobs/http_client.py`)
- the API abuse controls of WS-12: a per-client rate limit, a request-body cap, a concurrency
  gate on the expensive endpoints, and the interactive docs disabled outside development
- the corpus and embedding bounds of WS-12: the fake-job screen, the admission control, the
  bounded embedding cache and the paged corpus scan
- the stored-payload neutralization of WS-12: board HTML is neutralized at the contract, and
  every response carries the hardening headers
- the prompt-confusion controls of WS-12: a nonce-fenced untrusted block, the injection strip
  on every bullet, the exact job-title check, and PII minimisation before the prompt
- the traversal controls of WS-12: path containment for request-supplied files, the zip-bomb
  guard, and the type-safe board-payload accessor

**The browser session (WS-08).**

- browser session isolation: every run gets an explicit, fresh browser **and** context, so no
  cookie or storage survives it (`src/applications/fake_ats_adapter.py`,
  `src/applications/form.py`; proven by `tests/test_isolation.py`)

**The development-time tooling.**

- `.cursor/mcp.json` includes a Playwright MCP configuration for development-time browser
  inspection.
- `.cursor/hooks.json` exists and runs Python formatting and MCP auditing scripts.
- `.cursor/rules/project.mdc` contains project-level security and architecture guardrails.

### Planned for implementation

- runtime secret management with a secret scanning policy
- malware scanning of uploaded resumes and job pages
- retention and deletion policy for resumes and PII
- authentication on the API itself — the rate limit bounds abuse; it does not identify a
  caller, and the API remains a single-operator surface

### Not yet implemented

- browser automation runtime for a real (non-fake) ATS
- end-to-end verification and replay capability for a real ATS
- data retention policy enforcement
- resume redaction and PII minimization inside the stored documents
- production secret management (vault or encrypted secrets store)
- malicious content scanning for uploaded resumes and job pages
- MCP runtime permission enforcement beyond Cursor development-time configuration

## 3. Security principles

1. Untrusted web content is data, not instruction.
2. Secrets never enter prompts, logs, or browser automation traces.
3. Browser automation is only allowed for approved domains and validated flows.
4. Human approval is required before any irreversible application submission in early versions.
5. The system must never claim that an application was submitted without evidence.
6. The design should fail closed: ambiguous or risky conditions must pause or block.
7. The agent must prefer deterministic validation over model guesswork.
8. Job websites, ATS pages, and uploaded documents are all potentially hostile or deceptive.

## 4. Trust boundaries and threat model

### Trust boundaries

- User/uploaded resume files
- Remote job pages and ATS pages
- Browser automation and browser runtime
- MCP tool execution layer
- FastAPI app boundaries
- Database and logs
- External APIs and services

### Assets to protect

- candidate resume files and extracted PII
- API keys, auth tokens, session cookies, and secrets
- browser session state and cookies
- application history and verification evidence
- user identity and profile data
- database records for applications, resumes, and matching data
- audit logs

### Threat actors

- malicious job website content
- malicious or deceptive ATS forms
- prompt-injection attempts embedded in website text
- phishing or credential-harvesting pages
- rogue browser extensions or local scripts
- attacker-controlled uploaded files
- untrusted third-party APIs
- unauthorized automation or credential reuse
- insiders with access to local logs or database dumps

## 5. Security control register (living document)

Each control below records:

- control name
- what threat it mitigates
- where it is implemented
- how it is tested
- current status

| Control ID | Control | Threat mitigated | Implementation location | Status | Test/verification |
|---|---|---|---|---|---|
| SEC-01 | Web content treated as untrusted | prompt injection, malicious job descriptions | `src/security/injection.py` (shared pattern list), `src/research/engine.py` (grounding + injection filters), `src/resume/tailor.py` (validator strips injected sentences) | **Implemented** (runtime-enforced for research + tailoring; the browser path is data-only by construction) | `tests/test_injection_policy.py` (12 tests) |
| SEC-02 | Environment variable secret model | secret leakage and credential exposure | `src/config/settings.py`, `.env.example` | Implemented at config layer | config validation tests |
| SEC-03 | Basic logging configuration | operational visibility and safe debug logging | `src/core/logging.py` (+ `PiiMaskingFilter`) | Implemented | log emission smoke test, `tests/test_audit.py` |
| SEC-04 | Playwright MCP as dev-time browser tool | dev inspection capability, controlled exploration | `.cursor/mcp.json` | Implemented | MCP server startup validation |
| SEC-05 | Human approval gate before submission | accidental or unauthorized application submission | `src/security/policy.py`, `src/db/approval.py`, `src/api/routes/applications.py` (prepare → approve/reject), `src/graph/nodes.py::approval_node` | **Implemented** — two-phase, persisted, approver identity + reason; `AUTO_SUBMIT` unreachable | `tests/test_approval_flow.py`, `tests/test_submit_api.py`, `tests/test_policy.py` |
| SEC-06 | Domain allowlist | malicious redirect, fake ATS, phishing websites | `src/security/allowlist.py` (exact host match + blocked hosts), enforced in the API route, the browser adapter (pre- and post-navigation) and adapter `supports_url` | **Implemented** | `tests/test_allowlist.py` (38 tests) |
| SEC-07 | Browser session isolation | cross-session contamination and cookie leakage | an explicit `browser.new_context()` per run in `src/applications/fake_ats_adapter.py` (WS-08), closed in the same `finally` that stops the browser; no persistent profile | **Implemented** (WS-08, 2026-10-21) — two consecutive runs share no cookie and no browser storage | `tests/test_isolation.py`, `tests/test_evidence.py::TestBrowserLifecycle`, live run in `scripts/verify_ws08.py` |
| SEC-08 | Least privilege MCP permissions | overbroad tool access | `src/security/permissions.py`, `src/security/registry_setup.py`, enforced in `submit_node` / `verify_node`; the Greenhouse/Lever `submit()` placeholders now raise | **Implemented** | `tests/test_permissions.py` (15 tests) |
| SEC-09 | CAPTCHA/MFA restrictions | bypass of anti-bot controls | `src/security/page_guards.py`, `src/applications/fake_ats_adapter.py` (stops with `blocked_human_review`) | **Implemented** | `tests/test_page_guards.py`, `tests/test_evidence.py`, live run in `scripts/verify_ws06.py` |
| SEC-10 | File upload validation | malicious resume files | `src/api/validation.py` (extension, size, real-file check, generated name), used by `POST /api/resumes` | **Implemented** | `tests/test_upload_validation.py` (15 tests) |
| SEC-11 | SSRF protections | internal service probing and metadata leakage | `src/jobs/http_client.py` (DNS-resolving guard) + `src/security/allowlist.py` (literal internal/metadata hosts) | **Implemented** | `tests/test_http_client.py`, `tests/test_allowlist.py` |
| SEC-12 | Resume privacy / PII handling | exposure of personal data | `src/security/redaction.py` (audit metadata), `src/core/logging.py` (`PiiMaskingFilter`) | Partial — PII is masked in logs and audit rows; resumes are still stored in cleartext and the retention policy is SEC-15 | `tests/test_audit.py` |
| SEC-13 | Audit logging | non-repudiation and investigation | `src/db/audit.py` (append-only table), `src/security/audit.py` (`record_audit`), wired into resume upload, job search, match, prepare, approve, reject, submit, verify and every guard trip | **Implemented** | `tests/test_audit.py`, live run in `scripts/verify_ws06.py` |
| SEC-14 | Submission verification | false claim of application submitted | `src/applications/evidence.py`, `src/applications/fake_ats_adapter.py` (screenshot + action trace + Playwright archive), `src/graph/nodes.py::verify_node` (evidence-existence check) | **Implemented** | `tests/test_evidence.py` (16 tests) |
| SEC-15 | Data retention policy | stale or excessive data retention | not implemented — resumes, evidence and audit rows are kept until the operator deletes them | Planned | — |
| SEC-16 | Failure-safe shutdown | unsafe state after failures | `src/graph/nodes.py` (every guard produces a status, never an exception), `src/graph/conditionals.py`, `src/graph/application_workflow.py` (the failure reason survives) | **Implemented** for the application path | `tests/test_evidence.py::TestFailureStatusPreservation`, `tests/test_permissions.py` |
| SEC-17 | API abuse and resource exhaustion | DDoS, request floods, resource exhaustion via one expensive endpoint | `src/security/limits.py` (every bound in one place), `src/security/rate_limit.py` (per-client limiter, bounded client table), `src/api/middleware.py` (rate limit → 429, body cap → 413, concurrency gate → 503, response headers), `src/main.py` (wired; the interactive docs are disabled outside development) | **Implemented** (WS-12, 2026-10-21) | `tests/test_ws12_hardening.py::TestRateLimiter`, `::TestRateLimitMiddleware`, `::TestBodySizeLimit`, `::TestConcurrencyGate` |
| SEC-18 | Corpus and embedding-budget bounds | a flood of fake listings exhausting the provider quota, the embedding cache, or the corpus — and with them the **legitimate** listings that arrive later | `src/jobs/spam.py` (the deterministic fake-job screen), `src/security/admission.py` (per-source, per-refresh and corpus caps), `src/llm/embeddings.py` (the cache is bounded and prunes oldest-first), `src/rag/chroma_store.py` (the full-corpus scan is paged and capped), `src/graph/job_executor.py` (the per-refresh embedding budget; every drop is counted) | **Implemented** (WS-12, 2026-10-21) | `tests/test_ws12_hardening.py::TestSpamScreen`, `::TestAdmissionControl`, `::TestEmbeddingCacheBound`, `::TestBoundedCorpusScan` |
| SEC-19 | Stored-payload neutralization (XSS) | a board returning HTML that is stored, served, and rendered | `src/security/html.py` (the neutralizer — dangerous elements removed with their content, then every tag, then the entities), applied at the contract in `src/jobs/contracts.py` so no adapter can forget it; `src/api/middleware.py` (`nosniff` and the other response headers) | **Implemented** (WS-12, 2026-10-21) | `tests/test_ws12_hardening.py::TestHtmlNeutralization`, `::TestListingNeutralization`, `::TestSecurityHeaders` |
| SEC-20 | Prompt boundary and factuality gaps | a listing impersonating the prompt's scaffolding; an injected sentence reaching the deliverable; an invented job title | `src/security/injection.py` (the nonce-fenced untrusted block and the rules that explain it), `src/research/engine.py` and `src/resume/tailor.py` (the fence, the prompt cap, the PII minimisation, the injection strip on **every** bullet including project bullets, the exact job-title check) | **Implemented** (WS-12, 2026-10-21) | `tests/test_ws12_hardening.py::TestPromptFencing`, `::TestTailoringInjectionControls`, `::TestResearchPrompt` |
| SEC-21 | Path containment and malformed input | a request pointing the browser at a file outside the application's directories (the browser uploads it to a third party); a zip bomb; a malformed board payload | `src/security/paths.py` (the containment check, on the *resolved* path), enforced at the API boundary in `src/api/routes/applications.py`; `src/api/validation.py` (the zip-bomb guard); `src/jobs/normalize.py::job_records` (the type-safe payload accessor) | **Implemented** (WS-12, 2026-10-21) | `tests/test_ws12_hardening.py::TestPathContainment`, `::TestZipBombGuard`, `::TestMalformedPayloads` |
| SEC-22 | Tenant data isolation | one user reading another's data by changing an id (IDOR); a foreign resource acting as an existence oracle; a cross-user audit or evidence read | `src/db/users.py` (the principal), `owner_id` on every user-scoped table (`NOT NULL`, indexed), `src/db/access.py` (the scoped accessors — the only way a route may reach a user-scoped row), `src/api/scope.py` (the one dependency every route takes its scope from) | **Spine landed (WS-13 · A0, 2026-10-21); the identity that keys it is not yet in place** — the routes act as the legacy owner until WS-13 A2, so the mechanism is present and tested while the behaviour is still single-tenant | `tests/test_tenant_isolation.py` (17 tests: the two-user matrix, the "not yours" ≡ "does not exist" check, and a grep that fails if a route ever queries a user-scoped table directly — it found five such bypasses when written) |
| SEC-23 | Authentication and account lifecycle | an unauthenticated caller reaching a protected endpoint; an unverified identity; an unrevocable session | planned — WS-13 A1 (`fastapi-users`: registration, login, logout, argon2 password hashing, cookie **and** bearer transports, CSRF) and A3 (password change, session revocation, account deletion) | **Planned** — the API is currently open, and the rate limit bounds abuse without identifying the caller | — |

## 6. Threat-by-threat controls

### 6.1 Prompt injection from job websites

- Threat: A job page, ATS questionnaire, or recruiter message contains instructions like “ignore previous instructions,” “upload your secrets,” or “submit to this malicious endpoint.”
- Attack scenario: The agent reads the page, interprets the text as instructions, and follows malicious commands rather than system policy.
- Impact: secret leakage, wrong navigation, submission to attacker-controlled endpoints, malicious file upload behavior.
- Mitigation:
  - treat all web content as untrusted data
  - enforce explicit system instructions in code rather than model preference
  - do not let browser content override tool contracts
  - validate all extracted content before using it to drive workflow decisions
  - keep untrusted data separate from trusted system prompts
- Implementation location:
  - `.cursor/rules/project.mdc`
  - `docs/SECURITY.md`
  - future application security middleware and browser policy layer
- Verification/test:
  - add prompt-injection fixtures to a browser test suite
  - ensure malicious text is parsed as content, not instruction
  - assert that the agent does not follow page-injected commands
- Status: implemented — the shared pattern list in `src/security/injection.py` filters the
grounded research output and the tailored summary, cover letter and bullets; the browser
path never derives a decision, a navigation target or a form field from page text
(`tests/test_injection_policy.py`).

### 6.2 Untrusted web content and malicious job descriptions

- Threat: A site may contain deceptive job ads, fake career pages, or malicious content designed to influence the agent.
- Attack scenario: The agent follows a fake application flow or extracts malicious text and uses it to generate unsafe actions.
- Impact: phishing, fake applications, unsafe navigation, credential theft.
- Mitigation:
  - allowlist applicant domains and trusted job sources
  - compare hostnames against an approved list
  - reject suspicious redirects and unknown domains
  - normalize extracted job text before using it in matching or generation logic
- Implementation location:
  - planned browser runtime policy
  - planned job source adapter validation layer
- Verification/test:
  - test fake domains and redirect chains
  - validate domain block rules
- Status: implemented — `src/security/allowlist.py` (exact host match, blocked internal and
metadata hosts) is enforced at the API boundary, in the browser adapter before and after
the navigation, and in the adapter host selection (`tests/test_allowlist.py`).

### 6.3 Credential protection

- Threat: Credentials, cookies, API keys, or tokens are exposed to prompts, logs, browser traces, or generated summaries.
- Attack scenario: A browser automation script logs a page state containing secrets or a model includes a token in a prompt.
- Impact: account takeover, unauthorized job application, exposure of private data.
- Mitigation:
  - store secrets only in environment variables or a secure secret manager
  - never log raw credentials or cookies
  - redact sensitive values in audit logs
  - keep browser sessions isolated and ephemeral by default
  - do not embed session data in prompts
- Implementation location:
  - `src/config/settings.py`
  - future secret manager integration
  - future browser automation layer and audit logging
- Verification/test:
  - secret redaction tests
  - log sanitization tests
  - simulated browser payload sanitization checks
- Status: implemented for the runtime layer — `src/security/redaction.py` drops credential-like
keys and masks personal data in every audit row, and `src/core/logging.py` masks emails
and phone numbers in every log record. The secret store itself is still a deployment
concern (6.14).

### 6.4 Browser session isolation

- Threat: A malicious page or a stale session contaminates another browser context or user workflow.
- Attack scenario: cookies or local storage from one job application session are reused in another session.
- Impact: cross-site leakage, wrong account access, unauthorized application actions.
- Mitigation:
  - create isolated browser contexts per job application workflow
  - separate persistent state, cookies, and temporary storage by task
  - clear ephemeral storage after completion or failure
  - never reuse a session across unrelated workflows without explicit authorization
- Implementation location:
  - `src/applications/fake_ats_adapter.py` (one browser and one context per submission)
  - planned browser runtime (WS-08)
- Verification/test:
  - session isolation unit and integration tests
  - verify cookies are not shared between contexts
- Status: partial — each submission gets its own browser and context, and the session is torn
  down with it; persistent profiles and cross-session isolation are WS-08's job

### 6.5 Domain allowlisting

- Threat: The agent navigates to attacker-controlled domains or data-harvesting pages.
- Attack scenario: A malicious page redirects the agent to a fake login or phishing site while the flow is in progress.
- Impact: credential theft, fake applications, unauthorized data extraction.
- Mitigation:
  - define an explicit allowlist of trusted domains
  - reject navigation to non-allowlisted domains by default
  - validate redirect targets before continuing
  - require a policy decision before visiting unapproved hosts
- Implementation location:
  - planned browser automation policy
  - future HTTP client and fetch layer
- Verification/test:
  - denylist/allowlist tests for navigation and fetch calls
  - redirect policy tests
- Status: implemented — see 6.2. The check runs before the navigation and the URL the browser
ended up on is checked again afterwards, so a redirect off the allowlist fails the
submission with `status="unsafe_navigation"`.

### 6.6 MCP tool permissions and least privilege

- Threat: An MCP tool that can search or fetch data is also used to submit, modify, or leak credentials.
- Attack scenario: a broad tool contract is over-permissive and allows unapproved actions.
- Impact: dangerous automation, data leakage, manipulation of workflows.
- Mitigation:
  - grant only the minimum capability required for each action
  - separate read/search tools from submit/modify tools
  - enforce capability boundaries in code and runtime policy
  - avoid exposing browser automation and account actions globally
- Implementation location:
  - Cursor MCP configuration
  - future runtime MCP client layer
  - future permissions registry
- Verification/test:
  - permission matrix tests
  - call-surface validation for tool contracts
- Status: implemented for the runtime layer — `src/security/registry_setup.py` maps every
adapter to its capabilities, the submit and verify nodes refuse an adapter that holds no
such capability, and the adapters themselves refuse a submit they were not granted
(`tests/test_permissions.py`).

### 6.7 CAPTCHA and MFA restrictions

- Threat: The automation attempts to bypass anti-bot controls or multi-factor checks.
- Attack scenario: the browser automation tries to solve CAPTCHA or bypass MFA to complete a form or login.
- Impact: policy violation, account lockout, legal/security breach, unreliable automation.
- Mitigation:
  - explicitly block CAPTCHA bypass or automated solving
  - stop on MFA challenge and request human intervention
  - do not pursue flows that require prohibited or unsafe actions
  - maintain a blocked action list for prohibited automation behavior
- Implementation location:
  - planned browser automation policy
  - future job-application workflow rules
- Verification/test:
  - challenge detection tests
  - fail-safe tests for MFA/CAPTCHA states
- Status: implemented — `src/security/page_guards.py` detects the challenge markers on the
page before any form interaction, and the flow stops with
`status="blocked_human_review"`. The agent never attempts to solve a challenge
(`tests/test_page_guards.py`, `tests/test_evidence.py`).

### 6.8 File upload security

- Threat: Malicious resume files or disguised documents are uploaded to job portals.
- Attack scenario: a PDF, DOCX, or other file contains embedded scripts, malware, or malicious metadata.
- Impact: malware execution, malicious content injection, data leakage, system compromise.
- Mitigation:
  - validate file type, extension, and size
  - scan for known malicious patterns before upload
  - sanitize metadata and strip extraneous fields when possible
  - store uploads in a controlled location with access restrictions
- Implementation location:
  - planned resume upload API and file processing layer
- Verification/test:
  - blocked file-type tests
  - oversize file tests
  - malicious PDF/office file simulators
- Status: implemented for type, size and real-file structure — `src/api/validation.py`
accepts only `.docx`/`.txt`/`.md` up to 5 MB, requires a real ZIP that `python-docx` can
open, requires UTF-8 for text, and stores the file under a generated name.
**Malware scanning is still not implemented** (`tests/test_upload_validation.py`).

### 6.9 SSRF and network risks

- Threat: A remote page or tool fetches internal resources or metadata endpoints.
- Attack scenario: the agent follows an untrusted URL to 127.0.0.1, localhost, or metadata endpoints.
- Impact: access to internal services, credential leakage, unintended data access.
- Mitigation:
  - block private and loopback addresses
  - block metadata endpoints and internal IPs
  - validate allowed domains before network access
  - use a strict outbound network policy
- Implementation location:
  - planned HTTP client, fetch layer, and browser policy
- Verification/test:
  - SSRF blocklist tests
  - internal IP and localhost attempt tests
- Status: implemented — the job-source HTTP client resolves every address of a hostname and
refuses private, loopback, link-local and metadata targets, and the browser layer blocks
the same hosts by literal (`tests/test_http_client.py`, `tests/test_allowlist.py`).

### 6.10 Resume privacy and PII handling

- Threat: Candidate resumes contain personal data, work history, address data, phone numbers, email addresses, or other sensitive PII.
- Attack scenario: PII is exposed in logs, prompts, or telemetry without protection.
- Impact: privacy breach, identity exposure, data loss, compliance risk.
- Mitigation:
  - minimize PII sent to LLMs and external systems
  - redact sensitive fields before logs and summaries
  - store resumes in restricted access storage
  - define explicit retention rules and deletion flows
- Implementation location:
  - planned resume processing service
  - database design and storage policy
- Verification/test:
  - redaction tests for email, phone, and address fields
  - retention tests
- Status: partially implemented — personal data is masked in the audit trail and in every log
record, and the approval summary lists the prepared field *names* rather than the
candidate's values. The stored resume itself is still in cleartext and the retention
policy is SEC-15.

### 6.11 Logging and audit trails

- Threat: Useful operational data is insufficient, missing, or includes secrets, leading to loss of accountability.
- Attack scenario: a failed or harmful browser submission cannot be reconstructed because the system never records the action or logs the wrong data.
- Impact: inability to investigate failures, difficulty auditing compliance, unsafe replay of actions.
- Mitigation:
  - record timestamp, workflow ID, tool name, domain target, action type, and outcome
  - redact secrets and sensitive user data
  - keep audit logs in append-only storage
  - log job search, resume parse, match, browser action, verification, and application state changes
- Implementation location:
  - `.cursor/hooks/audit_mcp.py`
  - future application event system
- Verification/test:
  - audit log generation tests
  - secret redaction tests
  - event ordering tests
- Status: implemented — `src/security/audit.py` writes an append-only `audit_events` row for
every resume upload, job search, match, prepare, approve, reject, submit and verify, and
for every guard trip. There is no update or delete path (`tests/test_audit.py`).

### 6.12 Human approval and submission authorization

- Threat: A malicious or faulty agent submits an application without explicit user approval.
- Attack scenario: The workflow auto-submits to a job and the user never reviews the final application or match quality.
- Impact: unauthorized application attempts, misleading submissions, data and time waste.
- Mitigation:
  - require explicit human confirmation before submitting
  - display the final application details, job match score, resume version, and answers
  - log the approval token and approver identity
  - require a second check before irreversible browser submission
- Implementation location:
  - planned workflow and application approval layer
- Verification/test:
  - approval gate tests
  - blocked auto-submit tests
- Status: implemented — the flow is two-phase. `POST /api/applications/prepare` records an
approval request; only `POST /api/applications/{id}/approve` executes, and it records the
approver, the reason and the time. The default policy is `REQUIRE_APPROVAL`, the
in-graph approval node fails closed, and `AUTO_SUBMIT` is defined but unreachable
(`tests/test_approval_flow.py`, `tests/test_submit_api.py`).

### 6.13 Failure handling and unsafe-fallback behavior

- Threat: A failed flow continues in an unsafe or deceptive state.
- Attack scenario: a browser page loads an unexpected state and the agent still proceeds with application submission.
- Impact: incorrect applications, application to the wrong job, contract or policy violations.
- Mitigation:
  - fail closed when state is ambiguous
  - stop when unexpected navigation, unknown page structure, or unverified submission occurs
  - require a verification step before reporting success
  - maintain a retry budget and explicit failure state transitions
- Implementation location:
  - planned workflow orchestration and browser automation guardrails
- Verification/test:
  - failure-mode tests for navigation, selectors, and verification failures
- Status: implemented for the application path — every guard produces a specific status
(`permission_denied`, `unsafe_navigation`, `blocked_human_review`, `evidence_incomplete`,
`verification_failed`) instead of a generic failure, and the reason survives to the end of
the workflow (`tests/test_evidence.py::TestFailureStatusPreservation`).

### 6.14 Secret management

- Threat: secrets remain in source code, logs, environment dumps, or browser traces.
- Attack scenario: a developer commits a config file with a token or a script prints a session value to logs.
- Impact: account compromise, unauthorized automation, leakage of personal data.
- Mitigation:
  - keep secrets in `.env` or a secure secret manager
  - provide `.env.example` as a non-secret template only
  - install secret scanning in CI
  - never print secrets in logs or prompts
  - rotate compromised values when necessary
- Implementation location:
  - `.env.example`
  - `src/config/settings.py`
  - planned CI secret scanning and deployment security
- Verification/test:
  - secret scanner tests
  - redaction tests
- Status: partially implemented via env var pattern; secret scanning and secure secret-store integration are still planned

### 6.15 Data retention and deletion

- Threat: resumes, personal data, application logs, and browser session artifacts remain too long, creating privacy risk.
- Attack scenario: a stale resume, browser session, or application record persists long after the user has moved on.
- Impact: privacy exposure, storage bloat, compliance issues.
- Mitigation:
  - define data retention windows for resumes, logs, and browser artifacts
  - provide user-driven deletion or purge flows
  - store only minimal required records
  - classify data as active, archive, or purge-worthy
- Implementation location:
  - planned storage layer and lifecycle policy
- Verification/test:
  - retention policy tests
  - purge behavior tests
- Status: planned

## 7. Browser automation security policy

The runtime browser layer must implement the following controls before any browser-based application submission is enabled.

### Browser automation allow/block policy

Allow list examples:

- approved job boards
- approved ATS domains
- company career pages explicitly user-approved
- known employer domains from a verified user preference list

Block list examples:

- localhost and internal IPs
- localhost metadata endpoints
- unknown domains not on the explicit allowlist
- fake or suspicious redirect targets
- domains with certificate or TLS anomalies
- payment, phishing, or untrusted third-party form hosts

### Runtime browser requirements

- isolated browser contexts per job application task
- no credential reuse across unrelated tasks
- no hidden or background credential prompts
- no CAPTCHA bypass or MFA spoofing
- no navigation to pages outside approved domains
- stop flow if unexpected redirect or page structure is detected
- require approval before any irreversible action

## 8. MCP security policy

The repo currently has a Cursor Playwright MCP configured in `.cursor/mcp.json`.

This is a development-time capability and must not be mistaken for the runtime application architecture.

### Runtime MCP/Tool contract rules

- tools must be narrow and explicit
- read/search tools must not be equivalent to submit/write tools
- browser automation tool access must be restricted to approved domains and flows
- prompts must not include secrets
- logs must redact credentials and cookies
- tool invocations must record the tool name, action, and timestamp for auditability

## 9. Security requirements for resume handling

- uploaded resumes are untrusted files
- validate file type and size before import
- parse only the necessary text needed for profile extraction
- redact or minimize PII before prompts or logs
- store resume content with restricted access
- reject malformed or suspicious documents
- allow the user to review extracted profile fields before use in job matching or application flows

## 10. Security requirements for application submission

Before browser submission is implemented, the following checks must be enforced:

1. domain is approved
2. page is the expected target domain and flow
3. required fields are identified and validated
4. user approval is received
5. submission is the final step and not an intermediate action
6. submission verification is performed after the action occurs
7. failure or ambiguity triggers a safe stop
8. evidence is recorded before claiming success

## 11. Operational guidance and living-document requirement

This file is intentionally a living document. Any future change must update the control register and record:

- the control name
- the threat it mitigates
- where it is implemented
- whether it is allowlisted or blocked
- how it is tested
- whether it is implemented, planned, or rejected

When a new feature is added, the relevant section must be updated with:

- allow list entries
- block list entries
- permitted domains
- blocked domains
- risk classification
- verification status
- failing conditions

Example update pattern:

```text
Control: Browser domain allowlist
Threat: malicious redirect to fake ATS page
Implemented in: src/browser/policy.py
Allow-list: jobs.example.com, careers.company.com
Block-list: localhost, 127.0.0.1, metadata.google.internal
Test: domain_redirect_policy_test.py
Status: planned
```

## 12. Current security status summary

### Implemented

- developer-time Cursor guardrails
- environment-variable config pattern
- basic logging configuration (with PII masking)
- Playwright MCP development-time integration
- audit hook scripts for MCP operations and Python formatting
- browser runtime domain allowlist and internal-host blocking
- adapter permission model (prepare / submit / verify)
- two-phase human approval gate with a persisted decision
- submission verification with screenshot, trace and an evidence check
- resume file validation and PII masking in logs and audit rows
- SSRF protections and prompt-injection filters in the runtime app logic
- append-only runtime audit events
- API abuse controls: a per-client rate limit, a request-body cap, a
  concurrency gate on the expensive endpoints, and the interactive API
  docs disabled outside development (SEC-17, WS-12)
- corpus and embedding-budget bounds: the fake-job screen, the admission
  control, the bounded embedding cache, and the paged corpus scan
  (SEC-18, WS-12)
- stored-payload neutralization: board HTML is neutralized at the
  contract, and every response carries the hardening headers
  (SEC-19, WS-12)
- a nonce-fenced prompt boundary, the injection strip on every bullet,
  the exact job-title check, and PII minimisation before the prompt
  (SEC-20, WS-12)
- path containment for request-supplied files, the zip-bomb guard, and
  the type-safe board-payload accessor (SEC-21, WS-12)

### Planned

- secure browser session handling beyond one context per submission
- malware scanning of uploads
- retention and purge policy
- production secret vault integration
- authentication on the API itself (SEC-23 / WS-13 A1) — the rate limit
  bounds abuse; it does not identify a caller. The **tenant isolation
  mechanism** (SEC-22) has landed and is tested, but the identity that
  keys it does not exist yet, so the API is still effectively a
  single-operator surface and says so.

### Not yet implemented

- browser submission workflow for a real ATS (the fake ATS only)
- end-to-end verification and replay capability
- environment policy enforcement and production deployment protections

## 13. Final security statement

This system must not treat website content as trusted operational instruction. Browser automation must be constrained to approved domains, isolated sessions, explicit human approval, and evidence-based verification. Until those controls exist, the application submission layer must remain out of scope.

## 14. Autonomous submission: security preconditions

Before any live autonomous submission is enabled, the following security preconditions must be met and recorded in this living document:

- `Domain allowlist` implemented and tested; any runtime navigation to non-allowlisted hosts must fail the submission node.
- `MCP permission registry` implemented mapping `read`, `prepare`, `submit`, and `verify` capabilities per adapter.
- `Evidence capture` implemented for every submission (screenshot, navigation trace, parsed confirmation id), persisted in an append-only audit store.
- `Human approval` default enforced: `REQUIRE_APPROVAL` unless the user explicitly configures otherwise.
- `CAPTCHA/MFA detection` and stop behavior implemented and verified.
- `File upload validation` and malware scanning enabled for all outgoing uploads.
- `SSRF` and internal-host blocking enforced for all fetches and form actions.

Additions to the control register must include the implementation location (file path), allow/block list values, and associated tests. This ensures that the autonomous submission capability is gated by verifiable, tested security controls.

### 14.1 Precondition status (WS-06, 2026-10-21)

| Precondition | Status | Where | Verified by |
|---|---|---|---|
| Domain allowlist | **Met** | `src/security/allowlist.py`; enforced in `src/api/routes/applications.py` and `src/applications/fake_ats_adapter.py` | `tests/test_allowlist.py`, live run of `scripts/verify_ws06.py` |
| Permission registry (read / prepare / submit / verify) | **Met** | `src/security/permissions.py`, `src/security/registry_setup.py` | `tests/test_permissions.py` |
| Evidence capture + append-only persistence | **Met** | `src/applications/evidence.py`, `src/applications/fake_ats_adapter.py`, `src/db/audit.py` | `tests/test_evidence.py`, `tests/test_audit.py` |
| Human approval default (`REQUIRE_APPROVAL`) | **Met** | `src/security/policy.py`, `src/db/approval.py`, `src/api/routes/applications.py` | `tests/test_approval_flow.py`, `tests/test_submit_api.py`, `tests/test_policy.py` |
| CAPTCHA/MFA detection and stop | **Met** | `src/security/page_guards.py` | `tests/test_page_guards.py`, live run |
| File upload validation | **Met** (type, size, real-file check; **malware scanning is not implemented**) | `src/api/validation.py` | `tests/test_upload_validation.py` |
| SSRF and internal-host blocking | **Met** | `src/jobs/http_client.py`, `src/security/allowlist.py` | `tests/test_http_client.py`, `tests/test_allowlist.py` |

**Allow list (browser navigation and application targets).** Configured by `ALLOWED_DOMAINS`; the
default is `greenhouse.io, lever.co, workday.com, ashbyhq.com, smartrecruiters.com, icims.com`.
Matching is **exact**: a host is allowed when it is the domain or a sub-domain of it
(`host == domain` or `host.endswith("." + domain)`), so `evil-greenhouse.io.attacker.com` is
refused. A local host is admitted **only** when `APP_ENV=development`, and only for the local
fake ATS.

**Block list.** Loopback (`localhost`, `127.0.0.0/8`, `::1`), link-local (`169.254.0.0/16`,
`fe80::/10`), RFC 1918 private ranges, CGNAT (`100.64.0.0/10`), and the cloud metadata
endpoints (`169.254.169.254`, `169.254.170.2`, `100.100.100.200`, `metadata.google.internal`).

**Remaining gaps (explicitly not covered by WS-06).** Malware scanning of uploaded files
(the validator checks type, size and real-file structure only), data retention and purge
(SEC-15), and PII minimisation inside stored resumes (SEC-12). Browser session isolation
(SEC-07) was closed by WS-08: every run now gets an explicit, fresh browser context, and two
consecutive runs are proven to share neither a cookie nor browser storage
(`tests/test_isolation.py`, `scripts/verify_ws08.py`).

**Live verification.** `scripts/verify_ws06.py` runs the whole flow against a real HTTP server
and a real Chromium browser: 12/12 checks passed on 2026-10-21 (allowlist refusal, prepare →
approve → submit → verify with three evidence artifacts on disk, the removed single-call
submit route, the CAPTCHA stop, the permission denial, and the audit trail).
