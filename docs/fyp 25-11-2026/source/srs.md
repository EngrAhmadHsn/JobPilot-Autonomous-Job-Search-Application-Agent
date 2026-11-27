# 1 Introduction

This document specifies what JARVIS must do. It states requirements and avoids design. The design lives in the companion Software Design Document of this edition and in the workstream records listed in section 1.5.

## 1.1 Purpose

A candidate can spend an afternoon comparing vacancies only to discover, at the application form, that a required answer is missing. JARVIS moves two of those decisions earlier: whether a role fits the candidate's record, and whether the information prepared for an employer matches that record. The candidate still decides what to send.

This specification describes JARVIS, the Job Application and Resume Vetting Intelligent System, at revision `7190151`, dated 22 November 2026. The document is the requirements baseline for the final-year project, and the companion Software Design Document (SDD) traces each functional requirement to a component and to evidence a reader can inspect.

The specification serves two readers: the project supervisor, who reviews and approves the requirements, and the developer, who designs, builds and tests against them. Every requirement in the register carries an identifier, a status and an acceptance check, so a reader can separate behaviour the baseline contains from behaviour it lacks or meets only partly.

Two things in this edition deserve a reader's attention before the requirements. First, the system prepares applications and, on a real employer's site, hands the browser to a person. It does not submit there, because the adapter that would have to do it holds no permission to submit. Second, several figures were redrawn for this edition in the same monochrome style as the university templates, and the earlier console screenshots were replaced with captures of the current interface.

## 1.2 Scope

A signed-in candidate can upload a résumé, inspect the extracted profile, search stored jobs, compare a tailored draft with its source, review application questions, and follow recorded outcomes. An administrator looks after the shared job corpus and the worker that carries out background work. JARVIS does not predict the likelihood of an offer, does not check a candidate's qualifications with an employer, and does not synchronise recruiting decisions from an employer's system.

The local fake applicant tracking system (ATS) accepts test applications from end to end. A separate Greenhouse pilot can open a live form and prepare the controls it can support, then stop and hand the browser to a person. That adapter has no submit capability at all, so the stop is enforced by the permission model rather than by a prompt instruction. No live employer has received an application from this system, and no evidence of one exists in the repository.

The word "submission" therefore carries two meanings in this document, and the register states which one each requirement uses. Where a requirement concerns the local fixture, a complete submission and verification exercise is supported. Where it concerns a real board, the correct outcome is a prepared form and a human handover.

The product does not scrape web pages, does not use LinkedIn, and does not attempt to solve or bypass CAPTCHA or multi-factor authentication. It does not return one account's data to another account, and the console holds no credential of its own. Accounts exist because a person registered them: the system seeds no default account, password or administrator.

The goals are to cut the effort of finding and applying to suitable jobs, to keep every claim in a tailored document traceable to the candidate's own record, to keep every external action auditable, and to keep one account's records out of another account's reach.

## 1.3 Terms and conventions

The table below fixes the vocabulary used throughout this specification. A term that names a failure, such as `needs_human` or `submission.uncertain`, is written the way the system writes it, because the console and the audit records use those exact strings.

| Term | Meaning in this project |
| --- | --- |
| Adapter | A module that maps one external source or site to a common interface. |
| Admission control | The per-source, per-refresh and corpus limits that decide how many listings one refresh may admit. |
| Alembic | The database migration tool the project uses. |
| Application profile | Answers and preferences the candidate supplies separately, such as the countries in which they may work. |
| Argon2 | The password hashing function the identity layer uses. |
| ATS | Applicant tracking system, the software an employer uses to receive applications. "ATS analysis" estimates how well a document passes keyword screening. |
| Audit event | An append-only record of an action, attributed to a principal of kind user, agent or system, with the action, the resource and the outcome. |
| Approval | A recorded decision by an authenticated person about one particular packet. |
| Bearer token | A credential a script sends in the Authorization header instead of relying on a browser cookie. |
| BYOK | Bring your own key: a model-provider credential an account registers for itself, stored encrypted and never returned in the clear. |
| Candidate profile | The facts extracted from an uploaded résumé. An absent fact remains unknown. |
| CAPTCHA | A challenge meant to separate people from automated clients. The system stops at one instead of answering it. |
| Chroma | The embedded vector database that stores listing embeddings. |
| Circuit breaker | A per-provider switch that opens after repeated failures and pauses calls for a cooldown. |
| Corpus | The shared collection of stored job listings. A refresh writes it; a search reads it. |
| Corpus eviction | The removal of the listings a refresh has not seen for the longest, so that the corpus cap is a window rather than a one-way door. |
| Coverage | The share of a match's weight that came from measured evidence rather than from unknown states. A score and its coverage are reported together. |
| CSRF | Cross-site request forgery. A state-changing, cookie-authenticated request must echo the CSRF cookie in the `X-CSRF-Token` header. |
| CSP | Content Security Policy, the browser rule set that decides which scripts a page may run. |
| Degradation | A reduced result that is still returned, with the reduction disclosed, such as degraded ranking when vectors are missing. |
| Evidence | Records and artifacts used to check what an adapter observed, such as a confirmation page and a screenshot. |
| Evidence key | The numbered label in the SDD's trace that names a source file, a test specification or a dated evaluation. |
| Fake ATS | The local test employer site. It is the only target where a complete submission and its verification were exercised. |
| Factuality report | The validator's account of the changes it refused to keep. A clean report is not independent verification of every sentence. |
| JARVIS | The Job Application and Resume Vetting Intelligent System, the name this document uses for the whole system. |
| Lease | A time-boxed claim a worker holds on a work item. A commit that arrives after the lease was reclaimed is refused. |
| LLM | Large language model. |
| Mailbox | The local directory that receives password-reset and verification tokens in place of an e-mail provider. |
| Match | A score and an explanation for one profile and one posting. It is a recommendation, not a forecast of an employer's response. |
| MFA | Multi-factor authentication. The system never answers an MFA challenge. |
| Nonce fence | The marker that separates untrusted text inside a prompt from the instructions around it. |
| Operator console | The React application in the frontend package that drives the API on a signed-in person's behalf. |
| Owner scope | The authenticated principal together with the rules that decide which rows that principal may read. A foreign row reads as missing, not as forbidden. |
| PII | Personally identifiable information. |
| Principal | The thing an action is attributed to, recorded as a kind and an identifier. |
| Purge | The retention operation that removes records and files past their window. It cannot be undone. |
| Question plan | The ordered set of an employer's form controls, the grounded answers prepared for them, and the questions still unresolved. |
| Refresh | The durable job that fetches boards, stores listings and embeds new text. |
| Retention | The age at which a record or a file is purged, and the cascade that removes what depends on it. |
| Review packet | The prepared application inputs, the document references and the question plan that the candidate is asked to inspect. |
| Run | A unit of background work with its own identifier. A queued run has no submission result. |
| Score state | The information situation of one score component: measured, unknown or not applicable. Unknown contributes zero and keeps its weight in the denominator. |
| Session | A server-side row in `access_tokens` that records a signed-in account, so a session can be ended at once. |
| Sponsor | An employer entry in an imported visa-sponsorship register. The register says who appears in it, never who qualifies. |
| SRS | Software Requirements Specification. |
| SSRF | Server-side request forgery, an attack that makes a server call internal addresses. |
| Studio | The console screen where a tailored draft is edited; every saved edit is revalidated against the profile. |
| Tenant | One account and everything it owns. |
| Tracker | The console area that shows each application case and its ordered history. |
| Work item | A unit of a run that a worker claims under a lease and either commits or returns to the queue. |
| Work queue | The durable tables that hold runs and work items, so accepted work survives a process restart. |
| Worker | The process that claims queued work, runs the permitted adapter and records the result. |

In the register, Implemented means the baseline contains the stated behaviour. Limited names a restriction or a difference that the acceptance check describes. Deferred means the baseline does not meet the requirement. An acceptance check tells a reviewer what to observe; it does not claim that a fresh test was run for this edition.

## 1.4 Roles and responsibilities

Four parties appear throughout the requirements, and confusing them is the commonest way to misread the system. The candidate is the person whose documents and decisions are at stake. The API is the service that authenticates a request, validates it, records a decision and returns an answer. The worker is a separate process that carries out accepted background work under a lease, and it is the only part of the system that opens a browser. The employer owns the form, the verification challenges and the final receipt.

The division matters because a successful call to the API proves only that the API accepted the request. On an executable local case it returns HTTP 202 with a run identifier, and the worker acts afterwards. Nothing in that exchange shows that a form was filled or that a page was seen. Only the worker's recorded evidence, such as the confirmation it checked and the files it stored, can support the stronger claim, and only within the boundary of the fixture.

| Party | Owns | May not |
| --- | --- | --- |
| Candidate | The résumé, confirmed answers, drafts, and every approval decision | Approve another account's packet, or ask the system to answer unknown eligibility questions |
| API | Authenticated access, validation, the decision record, queued work | Fill a form, press a button, or claim an outcome |
| Worker | Claiming work, running the approved adapter, recording evidence, settling the lease | Act without an approval, act outside its adapter's capability, or retry a possible submission blindly |
| Employer | The form itself, challenges, and whether an application was received | Grant the agent any authority by publishing a page |

An administrator is a candidate with additional operational access. That access covers the corpus, the worker and recovery of an interrupted run. It does not extend to approving a packet in someone else's name.

## 1.5 References

The documents and specifications below are the ones this document relies on. Paths are relative to the project repository at revision `7190151`.

The architecture, security register and operating instructions are `docs/ARCHITECTURE.md`, `docs/SECURITY.md` and `docs/RUNBOOK.md` at the named revision. The workstream record is `docs/implementation/`, and the entries that bear most directly on this document are WS-32 for the assist pilot, WS-45 for per-application questions, WS-47 for Studio editing, and WS-49 for the last measured verification and its limits.

- IEEE Std 830-1998, Recommended Practice for Software Requirements Specifications. IEEE.
- RFC 6265, HTTP State Management Mechanism. IETF.
- Project plan, `docs/PROJECT_PLAN.md`. Project repository.
- Architecture document, `docs/ARCHITECTURE.md`. Project repository.
- Security model, threat model and control register, `docs/SECURITY.md`. Project repository.
- Operations runbook, `docs/RUNBOOK.md`. Project repository.
- Software Design Document of this edition, `sdd.md` in the same source directory, which traces each requirement to a component and to an evidence key.
- Implementation records, `docs/implementation/`, in particular WS-32 for the assist pilot, WS-45 for per-application questions, WS-47 for Studio editing and WS-49 for the last measured verification and its limits.
- Continuous integration workflow, `.github/workflows/ci.yml`. Project repository.
- Evaluation records, `docs/evaluations/`, in particular the WS-32 assist pilot of 15 November 2026.
- Operator console guide, `frontend/README.md`. Project repository.
- Greenhouse Job Board API. Greenhouse Software. https://developers.greenhouse.io/job-board.html
- Lever Postings API. Lever. https://github.com/lever/postings-api
- Ashby public job posting API. Ashby. https://developers.ashbyhq.com/
- Remotive API documentation and terms. Remotive. https://remotive.com/api-documentation
- EmbeddingGemma model card. Google. https://ai.google.dev/gemma/docs/embeddinggemma/model_card_2
- Gemini API documentation. Google. https://ai.google.dev/gemini-api/docs
- FastAPI documentation. https://fastapi.tiangolo.com
- fastapi-users documentation. https://fastapi-users.github.io/fastapi-users/
- LangGraph documentation. LangChain. https://langchain-ai.github.io/langgraph/
- Chroma documentation. https://docs.trychroma.com
- Playwright for Python documentation. Microsoft. https://playwright.dev/python/

## 1.6 Overview

Section 2 describes the product in plain language: what it is, what surrounds it, who uses it, what constrains it and what it assumes. That chapter suits the supervisor and any reader meeting the system for the first time. Section 3 holds the specific requirements and suits the developer and the tester: the external interface contracts, the requirement register in twelve groups, the use cases, the observable objects, the data requirements, the quality attributes, the inverse requirements, the design constraints, and a closing record of the acceptance evidence and the working tree.

Requirement identifiers use the prefix FR for functional and NFR for non-functional requirements. A functional requirement's group number matches the sub-section that introduces it, so FR-5.x rows sit under section 3.2.5. The sub-sections of 3.2 follow one shape: an introduction, the inputs, the processing steps, the outputs and the error handling. The SDD takes each register row further, to the component that owns the behaviour and to the evidence a reviewer can inspect.

Chapter 2 sets the system boundary. Chapter 3 holds the interface contracts, the requirement register, the use cases and the quality criteria. A reader who wants only the measurable part can start at section 3.2 and follow the register tables; a reader who wants the boundary first should read chapter 2 in order.

# 2 Overall description

This section gives the background for the requirements in chapter 3. It states no testable requirement.

## 2.1 Product perspective

JARVIS sits between a candidate's private records and several outside services. A job board supplies public listing data; it receives nothing when the candidate searches. A configured model provider may supply draft wording. Neither a listing nor model output can grant permission to operate a browser. Figure {fig:context} separates these exchanges from the candidate's decision, and the two application targets at the bottom of the diagram are the clearest thing to notice: only the left-hand path is drawn with an approved submit.

@figure context

The product is a modular monolith: one Python package, one relational database and two processes with different lifetimes. The API process serves requests, validates input and records decisions. The worker process claims accepted background work from a durable queue and is the only part of the system that opens a browser. The operator console is a React package beside them that talks to the API over HTTP.

Commercial tools such as Simplify, Teal and LazyApply autofill forms, track applications or send applications in bulk. This product differs in four ways. It collects jobs only from documented public APIs. It checks every tailored claim against the candidate's own record. It requires a recorded human approval and stored evidence before it reports a submission, and on a real board it never reports one at all. And it keeps one account's records out of another account's reach, so a shared deployment is safe.

### 2.1.1 Operations

- Interactive operation. The candidate signs in to the console, uploads a résumé, searches and reviews results, prepares applications and records outcomes. The console holds no credential of its own; the session cookie and the CSRF token are the browser's business.
- Unattended operation. A scheduler or an administrator starts a corpus refresh about once a day; Remotive asks API users to fetch at most about four times a day. The refresh returns immediately with a run identifier, and a worker process performs the fetches afterwards from the durable queue.
- Data processing. The refresh embeds only the texts the embedding cache does not already hold. The worker checkpoints a run in batches of work items, so an interrupted run keeps completed work and resumes with the outstanding part.
- Backup and recovery. The operator backs up the database and the `data/` directory. The vector index can be rebuilt by deleting its directory and running the refresh again, or reconciled against the database by an administrator. The purge command removes records and files past their retention window, and it cannot be undone. A run that died mid-flight becomes recoverable, and recovering it is an administrator's explicit act.

### 2.1.2 Site adaptation requirements

Before first use the operator must install Python 3.13, install the Chromium browser for Playwright, copy `.env.example` to `.env` and set the board lists, and run the database migrations. The first refresh downloads the local embedding model weights, about 300 MiB, and caches them. Draft generation needs a model provider: a platform key in the server environment, or a personal key the account registers, stored encrypted.

A production start refuses to run unless the CORS origins are declared and not wildcarded, the signing secret is at least 32 characters, the session cookie is marked Secure, the submission policy is declared, and the debug flag is off. A PostgreSQL deployment needs a database created and its URL set in `DATABASE_URL`; SQLite is the development default and both use the same migrations.

The worker is started beside the API with `scripts/run_worker.py` and must share the configured database and the private artifact storage. The console is a separate package: it needs its own install and a build step, and it reads only `VITE_API_BASE_URL` and the development proxy target.

## 2.2 Product functions

Discovery, ranking and drafting each produce a useful result without starting an application. A candidate can reject an inaccurate draft, download a document, or leave a vacancy unpursued. If they ask for preparation, the next result is a review packet rather than an application. The conditions for actually sending something depend on the selected adapter as much as on the decision about the packet.

Figure {fig:function-scope} groups the functions by what they can do. The upper band is ordinary product work. The lower band is the submission boundary, split between the local fixture, which can complete an application, and the live pilot, which cannot.

@figure function-scope

The stages below summarise the workflow. Security properties, identity, isolation, retention and auditing are not a stage of their own: they apply to every stage.

- Résumé intake: parse an upload into a validated candidate profile and store it under the uploader's account.
- Job discovery: collect listings from four public sources, normalize them, merge duplicates, screen machine-generated entries, apply admission limits and index the new text.
- Matching and search: rank stored listings for a profile with an explained eight-component score and report the evidence behind it.
- Tailoring and document analysis: draft a job-specific résumé and cover letter from profile facts, validate them, score keyword coverage and render a document. Studio edits revalidate the changed text.
- Application preparation and decisions: build a review packet with a question plan, wait for a recorded decision, then let the worker act within the adapter's granted capability and verify what it did.
- Application tracking: record each status change as an attributed event in an append-only history.
- Evaluation: measure extraction, ranking, factuality, lifecycle, browser and security behaviour against golden datasets, and gate the numbers against thresholds.
- Identity and access: register an account, sign in, keep a server-side session and end it.
- Isolation and retention: keep each account's rows and files to itself, purge what has aged out, and anonymize the audit rows of a deleted account.
- Operator console: drive these functions from a browser, with separate operations screens for the administrator's view of the corpus, the queue and the workers.

## 2.3 Users and responsibilities

The candidate owns the résumé, the confirmed answers, the drafts and the case history. They decide whether to accept proposed wording, and they record later outcomes such as an interview or a withdrawal. The administrator inspects platform operations and can recover eligible interrupted runs. An employer controls its form, any verification challenge and the final receipt.

Figure {fig:use-cases} shows the two human actors and the scheduler that may request a corpus refresh. The recovery use case sits with the administrator alone, which is deliberate: a worker that dies mid-run must not be replaced silently by whichever process polls next.

@figure use-cases

The main user is the candidate, a technical user who is comfortable with REST tools and a command line. Every capability works through documented HTTP endpoints and scripts with readable error messages, and the console presents the same capabilities without requiring a terminal. In early versions the candidate is also the approver, which makes the approval step a deliberate pause rather than a formality. The console has to explain the system's state in words rather than in status codes, and it must never show a success the server did not return.

A second person may hold an account of their own, and no account can see another's records, files or history. An administrator's extra reach covers operations, not other people's packets. A maintainer extends adapters and scorers, and needs clear module boundaries and a test suite that runs without a network.

## 2.4 Operating conditions and assumptions

The console needs a browser and an authenticated connection to the API. Local search needs a populated corpus and a stored profile. It can still answer when semantic evidence is missing, provided the response discloses the reduced coverage. A fresh corpus needs reachable public sources. Draft generation needs a configured model provider, while saving supported edits to an existing draft does not require a new model call.

The API and the worker must share the configured database and the private artifact storage. A responsive API does not prove that the worker is available. A closed posting, an unreachable board or an unsupported field can leave preparation incomplete. Unknown answers, work eligibility above all, are for the candidate to settle. Deployment and recovery are described in the SDD.

## 2.5 General constraints

- Terms of service. Only documented, key-less public job-board APIs may supply listings. Remotive requires credit and a link back to the original listing.
- Safety. Submission is irreversible. Approval, evidence and fail-closed behaviour are mandatory before any real-site use, and no real-board adapter holds the submit capability at all.
- Security and privacy. Web content is untrusted data. Secrets and PII stay out of prompts and logs. Gemini-path model calls disable provider-side storage, and personal provider keys are stored encrypted and returned only masked.
- Audit. Every external action must leave a record, attributed to a principal.
- Language and libraries. The runtime is Python 3.13 with FastAPI, Pydantic, LangGraph, SQLAlchemy, fastapi-users and Playwright. The console is React 19 with Vite and TypeScript.
- Quotas. The default embedder is local and quota-free. A configured Gemini embedding path carries its provider's quota, and a tenant may not spend more than its fair share of the daily embedding budget.
- Memory. Local embedding batches stay at 8 texts because larger batches exhausted memory in testing. The embedder halves its batch when the ONNX runtime cannot allocate.
- Scope of automation. The system may not bypass CAPTCHA, MFA or anti-bot controls.
- Resource bounds. A request body may not exceed 8 MiB, a client may not exceed 60 requests a minute, the process may not hold 64 requests in flight, a refresh may not embed more than 2,000 cache misses or 5,000 misses a day, and admission caps bound the listings one refresh may add.
- Deployment. The product runs as one API process and at least one worker process against one relational database. A single SQLite file is the development store, and PostgreSQL is the deployment store.

## 2.6 Assumptions and dependencies

- The listed job-board endpoints keep their current response shapes. A change requires an adapter update.
- The operator curates the boards to watch. The product does not discover companies.
- The candidate supplies a résumé in DOCX, TXT or MD format, or a PDF with a readable text layer. A scanned PDF has no text layer to read.
- The embedding model weights download once and stay cached.
- A model provider key is available for tailoring, either the platform's or the account's own. Search, matching and the console work without one.
- SQLite serves development and PostgreSQL serves deployment, both through the same migrations.
- The signing secret and the domain allowlist are set by the operator before a production start.
- The console is served as static files behind the same origin as the API, or is pointed at an absolute API URL.
- Password-reset and verification tokens are written to a local mailbox directory. An SMTP provider replaces that in a later release.
- The API and the worker share the database and the artifact storage. Queued work is durable, but a stopped worker means nothing is executing, whatever the API reports.

# 3 Specific requirements

Every requirement below has an identifier and a status in the register: Implemented means the baseline at revision `7190151` contains the stated behaviour, Limited names a restriction or a difference that the acceptance check describes, and Deferred means the baseline does not meet it. Each row names a design responsibility and an evidence path. A reference to a test or evidence path is a place to look, never an assertion that it was run for this edition. The SDD traces every row to the component that owns the behaviour.

## 3.1 External interfaces

| Interface | Contract a reviewer can observe |
| --- | --- |
| Candidate and console | The browser shows account-scoped results, unresolved questions and status. It distinguishes an accepted request from an error and from verified evidence. |
| Console and service | The HTTP API publishes its schema. Protected calls carry the authenticated session or a permitted bearer token. A state-changing browser request that uses a cookie also needs a matching CSRF token. |
| Public job sources | Refresh reads the configured Greenhouse, Lever, Ashby and Remotive endpoints. A stored search must not repeat that collection step. |
| Model and local embedding engine | A configured provider can generate structured text, and the baseline uses a local embedding model for search. A missing vector does not establish a poor semantic match. |
| Application adapter | The target must be allowed and the adapter must hold permission for the requested action. A real-board handover is not an application receipt. |
| Files and storage | The service accepts the documented résumé formats and returns private documents and evidence only to an entitled caller. It has no special-purpose hardware interface. |

The route table in the project `README.md` and the OpenAPI schema give the exact paths and verbs. Three identifiers are easy to confuse: deciding a packet uses an approval ID, opening its case history or its saved questions uses an application ID, and inspecting background work uses a run ID. Substituting one for another is not a supported shortcut.

### 3.1.1 System interfaces

The systems below are the ones the product talks to. Each row names the contract the product actually exercises.

| System | Interface used by the product |
| --- | --- |
| Greenhouse | GET `boards-api.greenhouse.io/v1/boards/{token}/jobs`, with `content=true` or a per-job fetch. JSON. |
| Lever | GET `api.lever.co/v0/postings/{company}?mode=json`. JSON list. |
| Ashby | GET `api.ashbyhq.com/posting-api/job-board/{org}`. JSON. |
| Remotive | GET `remotive.com/api/remote-jobs?search={query}`. JSON. |
| Model provider | The Gemini path through google-genai for structured draft output with provider-side storage disabled, or an OpenAI-compatible chat endpoint behind the same seam. The fallback chain adds Groq, TokenHarbor and Pollinations when their keys are set. An account may register its own key under BYOK. |
| Local embedding model | EmbeddingGemma-2 int8 through fastembed, run on the CPU at 768 dimensions. The default provider, with no quota. |
| Employer application sites | Browser sessions through Playwright, limited to allowlisted domains. Only the local fake ATS accepts submissions. The Greenhouse assist adapter prepares a form and stops before the submit control. |
| Visa-sponsorship registers | Imported CSV exports from the USCIS H-1B Employer Data Hub and the UK Home Office register of licensed sponsors. Read-only reference data, replaced per source and year on re-import. |
| Operator console | A static bundle served by the same deployment, calling the REST API over HTTP(S) with the session cookie. |

### 3.1.2 User interfaces

The product exposes its operations through a REST API that carries JSON. The OpenAPI schema is generated from the application and served at `/docs` in development only. Errors return an explicit HTTP status code with a descriptive detail message. Background work is accepted by the API and executed by the worker; operational one-off tasks live in command-line scripts. The table lists the routes a candidate or administrator exercises; the route table in `README.md` is checked against the running application by the test suite, so a route added without a row there fails the build.

| Endpoint | Purpose | Credential |
| --- | --- | --- |
| GET `/` | Service status. | Public |
| GET `/api/health` | Service status. | Public |
| GET `/api/health/live` | Liveness: the API process is alive. | Public |
| GET `/api/health/ready` | Readiness: the database answers and worker heartbeats are reported. | Public |
| POST `/api/auth/register` | Create an account. | Public |
| POST `/api/auth/cookie/login` | Sign in and set the session cookie. | Public |
| POST `/api/auth/token/login` | Sign in and return a bearer token. | Public |
| POST `/api/auth/cookie/logout` | End the cookie session. | Session |
| POST `/api/auth/token/logout` | End the bearer session. | Bearer |
| POST `/api/auth/forgot-password` | Request a password-reset token. | Public |
| POST `/api/auth/reset-password` | Set a new password with a reset token. | Public |
| POST `/api/auth/request-verify-token` | Request an e-mail verification token. | Public |
| POST `/api/auth/verify` | Verify the account with the verification token. | Public |
| GET `/api/auth/me` | The authenticated principal. | Session or bearer |
| PATCH `/api/auth/me` | Change the caller's own e-mail, password or name. | Session or bearer |
| DELETE `/api/auth/me` | Deactivate the account and end its sessions. | Session or bearer |
| GET `/api/auth/sessions` | The caller's live sessions, shown with token prefixes only. | Session or bearer |
| POST `/api/auth/sessions/revoke` | End every session of the caller. | Session or bearer |
| POST `/api/auth/sessions/revoke-others` | End every session except the current one. | Session or bearer |
| DELETE `/api/auth/sessions/{token}` | End one session of the caller. | Session or bearer |
| GET `/api/audit` | The caller's own audit trail. | Session or bearer |
| POST `/api/resumes` | Upload a résumé and return a validated profile. | Session or bearer |
| GET `/api/resumes/{profile_id}` | Read a stored profile. | Session or bearer |
| GET `/api/profiles/{profile_id}/matches` | Read the match history. | Session or bearer |
| GET `/api/profiles/{profile_id}/application-profile` | Read the confirmed application profile. | Session or bearer |
| PUT `/api/profiles/{profile_id}/application-profile` | Replace the confirmed application profile. | Session or bearer |
| GET `/api/profiles/{profile_id}/eeo` | Read the voluntary EEO selections. | Session or bearer |
| PUT `/api/profiles/{profile_id}/eeo` | Store EEO selections, opt-in required. | Session or bearer |
| DELETE `/api/profiles/{profile_id}/eeo` | Delete the EEO selections. | Session or bearer |
| GET `/api/profiles/{profile_id}/question-gaps` | The questions boards ask that the profile cannot answer, ranked by frequency. | Session or bearer |
| GET `/api/profiles/countries` | The countries a profile may name for work eligibility. | Session or bearer |
| GET `/api/profiles/employer-answers` | List the caller's saved employer answers. | Session or bearer |
| PUT `/api/profiles/employer-answers/{answer_id}` | Edit one saved employer answer. | Session or bearer |
| DELETE `/api/profiles/employer-answers/{answer_id}` | Remove one saved employer answer. | Session or bearer |
| POST `/api/jobs/refresh` | Accept a durable corpus refresh; returns HTTP 202 and a run ID. | Session or bearer |
| POST `/api/jobs/search` | Rank the stored corpus for a profile. | Session or bearer |
| GET `/api/jobs/{job_id}` | Read one stored listing. | Session or bearer |
| GET `/api/jobs/suggest` | Autocomplete the query field from stored titles. | Session or bearer |
| GET `/api/jobs/locations` | The distinct locations the corpus carries, with counts. | Session or bearer |
| GET `/api/jobs/sources` | The source registry and its freshness. Shared like the corpus. | Session or bearer |
| GET `/api/jobs/{job_id}/application-form` | Read a supported employer form and the caller's saved answers. | Session or bearer |
| PUT `/api/jobs/{job_id}/application-form/answers` | Save answers against the posting's current question versions. | Session or bearer |
| POST `/api/tailor` | Tailor a résumé for a job, with a factuality report. | Session or bearer |
| GET `/api/tailored/{tailoring_id}` | Read a stored tailoring run. | Session or bearer |
| PUT `/api/tailored/{tailoring_id}` | Save a Studio edit, revalidated in place. | Session or bearer |
| GET `/api/tailored/{tailoring_id}/download` | Download the rendered document of a tailoring. | Session or bearer |
| GET `/api/documents` | The caller's document library. | Session or bearer |
| GET `/api/documents/{document_id}/download` | Download one of the caller's documents. | Session or bearer |
| GET `/api/llm/credentials` | The caller's provider connections, masked. | Session or bearer |
| POST `/api/llm/credentials` | Add a stored connection without putting it in use. | Session or bearer |
| PUT `/api/llm/credentials` | Register or replace the connection in use. | Session or bearer |
| PATCH `/api/llm/credentials/{credential_id}` | Edit one connection, keeping its key unless replaced. | Session or bearer |
| POST `/api/llm/credentials/{credential_id}/activate` | Make one stored connection the one requests spend. | Session or bearer |
| DELETE `/api/llm/credentials/{credential_id}` | Remove one stored connection. | Session or bearer |
| DELETE `/api/llm/credentials` | Remove the connection in use. Idempotent. | Session or bearer |
| POST `/api/llm/credentials/test` | Exercise a connection with one small, billable call. | Session or bearer |
| POST `/api/applications/prepare` | Save a review for a stored posting or prepare the two-phase flow. | Session or bearer |
| GET `/api/applications/{application_id}/posting-review` | Reopen the caller's saved real-posting review. | Session or bearer |
| POST `/api/applications/{application_id}/authorize-fill` | Authorize one fill-only local session; no worker run. | Session or bearer |
| POST `/api/applications/{approval_id}/approve` | Record a human approval and queue the work; returns HTTP 202 and a run ID. | Session or bearer |
| POST `/api/applications/{approval_id}/reject` | Record a human rejection. | Session or bearer |
| GET `/api/applications/approvals/{approval_id}` | Read the state of an approval request. | Session or bearer |
| GET `/api/applications` | List the tracked applications. | Session or bearer |
| GET `/api/applications/{application_id}` | Read one application and its events. | Session or bearer |
| PATCH `/api/applications/{application_id}/status` | Change an application status. | Session or bearer |
| GET `/api/applications/{application_id}/questions` | Read the packet's questions with saved answers folded in. | Session or bearer |
| GET `/api/applications/{application_id}/answers` | Read the answers saved for an application. | Session or bearer |
| PUT `/api/applications/{application_id}/answers` | Save answers a human gave; EEO and attestation refused. | Session or bearer |
| GET `/api/applications/{application_id}/evidence` | Read the evidence records of an application. | Session or bearer |
| GET `/api/applications/{application_id}/evidence/{filename}` | Download one evidence artifact. | Session or bearer |
| GET `/api/runs` | The caller's durable execution history. | Session or bearer |
| GET `/api/runs/{run_id}` | One run's state, checkpoints and item summary. | Session or bearer |
| GET `/api/admin/overview` | Platform-wide aggregates. | Superuser |
| GET `/api/admin/runs` | Every durable run, filtered by type or status. | Superuser |
| GET `/api/admin/runs/{run_id}` | One run of any type, with its checkpoint. | Superuser |
| GET `/api/admin/embedding-runs` | Platform embedding runs. | Superuser |
| GET `/api/admin/embedding-runs/{run_id}` | One embedding run's detail. | Superuser |
| POST `/api/admin/embedding-runs/{run_id}/resume` | Resume outstanding embedding work. | Superuser |
| POST `/api/admin/embedding-runs/{run_id}/cancel` | Cancel a run safely. | Superuser |
| POST `/api/admin/embeddings/reconcile` | Queue a SQL and Chroma reconciliation. | Superuser |
| GET `/api/admin/jobs/metrics` | Queue, worker, breaker and budget metrics. | Superuser |
| GET `/api/admin/health/workers` | Worker liveness and queue shape. | Superuser |
| POST `/api/admin/workers` | Start a background worker process, bounded. | Superuser |
| POST `/api/admin/workers/{worker_id}/stop` | Ask a worker to finish its batch and exit. | Superuser |

The console calls these endpoints with `credentials: include` on every request, and adds the `X-CSRF-Token` header on every unsafe request. It stores no token of its own. The development server proxies `/api` to the backend, so the browser makes a same-origin request. The client refuses a declared response length above 8 MiB and checks the decoded length of an undeclared one.

### 3.1.3 Hardware interfaces

The system has no hardware interface requirements. The local embedding model runs on the CPU, and the browser automation needs the Chromium installation that Playwright manages. No camera, microphone, printer or other device is required or touched.

### 3.1.4 Software interfaces

The project plan sets the components below. The minimums are the declared constraints in `pyproject.toml` and in the console's `package.json`.

| Name | Declared minimum | Purpose |
| --- | --- | --- |
| Python | 3.13 | Runtime. |
| FastAPI, Pydantic | 0.141.1, 2.13.5 | REST API and data models. |
| fastapi-users, pwdlib | 15.0.0, 0.3.0 | Identity, Argon2 hashing, cookie and bearer transports. |
| LangGraph | 1.2.11 | Application and job-search workflows. |
| SQLAlchemy, Alembic | 2.0.52, 1.16.0 | Persistence and migrations. SQLite for development, PostgreSQL for deployment. |
| ChromaDB | 1.0 | Vector store, cosine space. |
| fastembed | 0.9.0 | Local EmbeddingGemma-2 int8 embedding. |
| google-genai | 2.25.0 | Model client for the Gemini path. |
| httpx | 0.28.1 | Job-source HTTP client. |
| Playwright | 1.51.0 | Browser automation. |
| python-docx | 1.1.0 | Résumé parsing and rendering. |
| React, Vite, TypeScript | 19.3, 8, 5.9 | Operator console: screens, build and types. |

### 3.1.5 Communications interfaces

The product calls job-board and model endpoints over HTTPS. It sends GET requests to job boards, does not follow redirects, and sets a User-Agent that identifies the agent. A source URL is resolved and screened before it is contacted, and a destination that fails the check is refused rather than reached by another route.

Its own API uses HTTP with JSON. Cross-origin access follows an explicit `CORS_ORIGINS` list, which defaults to the three local development origins and must be declared and not wildcarded in production. A browser session travels in an HttpOnly, SameSite=Lax cookie, marked Secure in production; a script may use a bearer token instead. An unsafe request that carries the session cookie must echo the CSRF cookie in the `X-CSRF-Token` header. The console bundle runs under a Content Security Policy that allows scripts only from its own origin plus one approved inline bootstrap. The worker talks to the database and, through its adapters, to the same screened endpoints. The product defines no custom protocol.

## 3.2 Functional requirements

Each area below follows one shape: an introduction, the inputs, the processing steps, the outputs and the error handling. The register table in each area holds the testable rows. The step tables name what the system does in the order it does it, so a reader can see where a refusal happens before a claim is made.

### 3.2.1 Résumé intake and profile extraction

#### Introduction

This area turns an uploaded document into a validated candidate profile and stores it under the uploader's account.

An unreadable document differs from a readable document with no education section, and intake must say which occurred. It must not invent profile content to fill an empty section. Figure {fig:upload-sequence} follows one upload from the console to storage. The two refusal branches are the part worth noticing: a file rejected at validation is never written, and a file that passes validation but fails to parse is removed before the request returns. Either way the refusal names its cause and leaves no profile behind.

@figure upload-sequence

#### Inputs

A multipart file with extension `.docx`, `.txt`, `.md` or `.pdf`, at most 5 MiB within the request limit, sent by an authenticated account. A profile identifier for later retrieval. Separate inputs carry the confirmed application profile, the work-eligibility answers per country and the voluntary EEO selections, none of which are read off the document.

#### Processing

| Step | Action |
| --- | --- |
| 1 | Validate the upload: extension, size, real-document structure and archive bounds, before the file is stored. |
| 2 | Store the source file under a server-generated name inside the caller's own directory. |
| 3 | Parse DOCX, TXT or MD, or read a text-layer PDF, into named fields, keeping the candidate's own wording. |
| 4 | Extract work preferences only from explicit statements in the document. |
| 5 | Validate the profile, produce named warnings, and leave an absent section empty rather than invented. |
| 6 | Persist the profile row under the caller's owner ID and return its identifier. |
| 7 | On a parse failure after validation, delete the stored file, refuse the request and name the cause. |

@requirements 1

#### Outputs

The profile identifier, the warnings and the full profile as JSON. A document-library entry for the upload. An audit event for the upload.

#### Error handling

A validation failure returns HTTP 400 with the cause named. An unknown identifier returns HTTP 404, and a profile that belongs to another account returns the same 404 a missing one would. A PDF without a readable text layer is refused with its reason; there is no OCR. Logs record sizes and counts, never résumé content.

### 3.2.2 Job discovery and refresh

#### Introduction

This area collects listings from the public APIs into one shared corpus and its vector index, as durable background work.

Refresh updates a shared corpus and can outlive the browser request, so acceptance and completion are reported separately. A listing that has not changed should not consume embedding work a second time.

#### Inputs

Board lists in `GREENHOUSE_BOARDS`, `LEVER_COMPANIES` and `ASHBY_ORGS`. A refresh trigger through POST `/api/jobs/refresh` or `scripts/refresh_jobs.py`, sent by an authenticated account or the scheduler.

#### Processing

| Step | Action |
| --- | --- |
| 1 | Read the configured board lists and the source registry. The LinkedIn adapter stays unregistered. |
| 2 | Build each request URL from the adapter's host constant and a validated board identifier, and screen the resolved address before connecting. |
| 3 | Fetch with pacing and bounded retries; record a failing source by name and continue with the rest. |
| 4 | Normalize each accepted posting to a canonical listing; drop a posting without an identifier, title or company. |
| 5 | Merge cross-source equivalents without merging two distinct identifiers from the same source. |
| 6 | Screen likely machine-generated entries and count what was dropped. |
| 7 | Apply the admission limits per source, per refresh and across the corpus, and count what was turned away. |
| 8 | At the corpus cap, evict the eligible listings not seen for the longest. |
| 9 | Upsert the admitted listings and queue embedding work only for new or changed text. |
| 10 | Execute the run in the worker: claim work items under a lease, embed by cache miss within the budget, and checkpoint completed batches. |
| 11 | Settle the run with counts, per-source errors and the flags that name any reduction. |

@requirements 2

#### Outputs

A run identifier and progress views while the work executes. A refresh report with counts for found, screened-out, admission-capped, persisted and embedded listings, a map of source errors, the embedding work planned and used, and the flags `quota_exhausted` and `degraded_embedding` where they apply.

#### Error handling

A failing source is named and the others continue; the run does not fail for it. An embedding quota stop pauses the run and leaves the outstanding work identifiable and resumable. A vector-store failure keeps the rows and marks the run's embedding degraded. Closing the browser does not cancel the stored work items, and a RECOVERABLE run is resumed by an administrator, never adopted by a polling worker.

### 3.2.3 Matching, ranking and search

#### Introduction

This area ranks stored listings for a profile and explains each score. The score combines eight components, and the explanation must let the candidate tell a measured low score from missing evidence.

The score combines semantic, lexical, skill, experience, seniority, location, preference and role evidence. A missing value and a known mismatch can both lower a score, but the explanation must tell the candidate which of the two occurred. Figure {fig:data-flow} follows the data rather than the calls: the profile and the listing meet only inside the scoring step, and the result belongs to the account that asked for it.

@figure data-flow

#### Inputs

A profile identifier, an optional query, an optional location and workplace filter, and `top_n` (default 10, maximum 50). No network request to a job source is an input: the search reads the stored corpus only.

#### Processing

| Step | Action |
| --- | --- |
| 1 | Load the stored profile and the stored corpus, and apply the query, location and workplace filters before ranking. |
| 2 | Read the semantic channel from the vector store. A missing vector is an unknown state, not a low score. |
| 3 | Score eight components: semantic, lexical, skill, experience, seniority, location, preference and role. |
| 4 | Blend the components with the configured weights on a fixed denominator, so an unknown component contributes zero and keeps its weight. |
| 5 | Cap a classified hard role mismatch at 25 overall. |
| 6 | Rank by overall score, keep the top results, and store one match row per result under the caller's owner ID. |
| 7 | Return each result with its component scores, states, matched and missing skills, coverage and a readable explanation. |

The default weights are semantic 0.13, lexical 0.08, skill 0.22, experience 0.17, seniority 0.08, location 0.09, preference 0.08 and role 0.15. An override must name all eight components, must be positive, and must sum to 1.0 within 0.01; startup refuses an override that does not. The lexical component is BM25 over the posting text, and the role component compares the posting's classified job family with the candidate's stated targets.

@requirements 3

#### Outputs

Ranked job and match pairs with component scores, component states, matched skills, missing skills, coverage and the explanation. Search statistics, an empty `source_errors` map, and the `degraded` flag whenever evidence was missing. Match history rows linked to the profile.

#### Error handling

An unknown profile and a foreign profile both return HTTP 404 with the same body. Missing vectors or a vector-store failure return HTTP 200 with the degraded disclosure, and the caller may ask for indexed jobs only. An empty corpus returns an empty result set without invented entries.

### 3.2.4 Tailoring and document analysis

#### Introduction

This area drafts job-specific documents from profile facts, checks them, and lets the owner edit the saved result.

Studio produces a draft for one profile and one job. A higher keyword count is no reason to add a skill the source does not support. An edit must pass back through the document checks before the new deliverable is presented.

#### Inputs

A profile and a listing, selected by profile identifier and job identifier. For a Studio edit, the saved draft and the owner's new text for the supported sections.

#### Processing

| Step | Action |
| --- | --- |
| 1 | Extract the job requirements from structured listing fields and skill mentions, without a model call. |
| 2 | Mask the candidate's contact details before anything is sent to a provider, and restore them locally afterwards. |
| 3 | Fence every untrusted listing block behind a fresh nonce, capped in length, so board text stays data. |
| 4 | Request a structured draft limited to profile facts; the Gemini path disables provider-side storage. |
| 5 | Validate the draft: remove unsupported skills, employers, projects and inflated years, and report each removal. |
| 6 | Compute the ATS estimate from keyword coverage, section completeness, title alignment and format safety, and list missing keywords as advice only. |
| 7 | Produce the deliverable: an in-place edit of a copy where the source is safely editable, otherwise a regenerated document identified as such. |
| 8 | Persist the result. A Studio edit revalidates factuality, ATS and deliverable on the same record without a new model call. |
| 9 | Refresh the document-library entry for the draft. |

@requirements 4

#### Outputs

The tailored summary, highlighted skills, experience entries, projects and cover letter, the factuality report, the ATS report, the grounded insights, the deliverable and its library entry.

#### Error handling

A provider failure is classified as configuration, rate limit, unavailable or invalid output, and retried only inside the configured policy. A missing key fails at once with an actionable message and never echoes the key. A factuality violation is a normal success with the report attached, not an error. A layout that cannot be edited safely keeps the original, and the response says which path was taken.

### 3.2.5 Application preparation and decisions

#### Introduction

This area prepares an application for a person's decision and, where the adapter holds the capability, executes that decision with verification. Preparation is safe everywhere; execution is granted adapter by adapter.

A successful decision request returns HTTP 202 and identifies queued work. It does not show that the worker has filled a field, clicked a button or obtained a receipt. The rows below separate those events, the capability each requires, and the evidence expected after execution.

#### Inputs

An application request: job title, company, job URL, candidate name, e-mail, phone, résumé reference, cover letter and custom fields. An approval decision from an authenticated person. Saved employer answers from the account's answer library, where the posting's questions match them.

#### Processing

| Step | Action |
| --- | --- |
| 1 | Select the permitted adapter from the job URL. A disallowed host or an unsupported URL returns HTTP 400. |
| 2 | Measure the posting's form, build the question plan, and fill only answers grounded in the profile or confirmed by the candidate. |
| 3 | Store the review packet, its exact payload and the pending approval request. The packet keeps the question plan it was prepared with. |
| 4 | Wait for the decision. An approve or reject call records the authenticated principal, the reason and the UTC time; an approval expires after its window, 168 hours by default. |
| 5 | On approval, commit the decision with its submission work item and return HTTP 202 and the run identifier. A full queue returns HTTP 503 and leaves the decision pending. |
| 6 | In the worker, re-check the policy, restore the stored payload without rebuilding it, and act only within the adapter's granted capability. |
| 7 | Capture the confirmation text, the screenshot, the ordered action trace and the browser archive where tracing succeeds. |
| 8 | Verify before claiming anything: a result with the confirmation marker becomes verified; otherwise it does not. |
| 9 | Settle the lease. A committed outcome is final and reused; an attempt marker without a durable outcome becomes `submission.uncertain` for a person to reconcile. |
| 10 | Record a sanitized audit event for prepare, approve, reject, submit and verify. |

@requirements 5

#### Outputs

An approval identifier for the decision, a run identifier for the queued work, the stored packet with its question plan, the workflow status, the recorded answers, and the evidence records with their artifacts. The approval record carries the approver, the reason and the decision time.

#### Error handling

A CAPTCHA or MFA challenge stops the run as `blocked_human_review` and is never answered. A required question with no grounded answer pauses as `needs_human`, naming the unresolved questions; nothing is guessed. An unexpected redirect after navigation stops the run. An expired approval or a posting the board marks closed returns HTTP 409, and an unreachable board is not proof of closure. An unexpected exception ends the workflow as `workflow_error`. A rejection queues no execution. The system never reports a submission it cannot verify.

### 3.2.6 Application tracking

#### Introduction

This area records the lifecycle of each application case as an attributed, append-only history.

A tracker entry shows the recorded history of a case. A person can report a later interview or an offer. The application does not infer an employer's decision from elapsed time or from the absence of a reply.

Figure {fig:application-state} draws the lifecycle that the fixture exercises and lists the remaining permitted moves beneath it. Two features are worth noticing. A failed verification returns the case to `awaiting_approval` rather than to `submitted`, and the four outcome states can be entered only by a human actor.

@figure application-state

#### Inputs

A status change request with the target status, the actor and optional notes. The lifecycle matrix is the single source of truth for what is legal.

#### Processing

| Step | Action |
| --- | --- |
| 1 | Create the case with its profile, job, workflow and approval references; leave absent references and future dates empty. |
| 2 | Validate every transition against the lifecycle matrix; refuse anything else with HTTP 409 and leave the status unchanged. |
| 3 | Append one event per transition with the actor, the prior state, the new state and metadata. Never update or delete an event. |
| 4 | Reserve interview, offer, rejected and withdrawn for a named human actor. |
| 5 | List cases with a status filter and pagination; return one case with its events in append order. |
| 6 | Link each evidence record to its case where tracking can supply the identifier. |

@requirements 6

#### Outputs

Application records with their status and ordered event history, filterable and paginated, each readable only by its owner.

#### Error handling

An illegal transition returns HTTP 409. An unknown application and one owned by another account both return HTTP 404. A machine actor that tries to record an outcome is refused. A manually recorded outcome remains a person's report, never an employer receipt.

### 3.2.7 Evaluation

#### Introduction

This area measures quality so the project can support claims with numbers and compare two versions of a component.

A score from a labelled teaching fixture is useful for comparing two versions of the ranker. It is not a measured success rate on live vacancies. Reproducing it requires the dataset and the provider settings alongside the metric.

#### Inputs

The golden datasets at `tests/evaluation/golden/`: five labeled résumés, 29 labeled postings with duplicate groups, six canned tailoring pairs and eight application scenarios. Synthetic identities only. The threshold configuration at `src/evaluation/thresholds.json`.

#### Processing

| Step | Action |
| --- | --- |
| 1 | Load the golden datasets and record their hash. |
| 2 | Run each family offline with canned model responses, and name any substitute model or channel in the report. |
| 3 | Compute the extraction metrics: field accuracy, skills F1, summary coverage and experience and education precision and recall. |
| 4 | Compute dedup precision and recall, nDCG@10, precision@5 and the role-mismatch rates. |
| 5 | Compute factuality agreement and violation recall, the ATS coverage change, lifecycle fidelity, browser completion and the security indicators. |
| 6 | Write a dated Markdown report and a JSON file with the same numbers, naming the dataset hash, the mode and the provider. |
| 7 | Apply the thresholds, name every violated bound, and exit nonzero when one fails. |

@requirements 7

#### Outputs

A dated Markdown report and a JSON file with the same numbers, plus the exit code the threshold check returns.

#### Error handling

A missing dataset or canned response stops the run with a message that names the file. A metric that was not measured is not counted as a pass.

### 3.2.8 Identity and account lifecycle

#### Introduction

This area gives each person an account, signs them in, keeps their sessions, and removes the account when they ask.

Registration, sign-in, sign-out and deletion touch different records. Closing a browser tab is not a request to delete the account or its documents. Figure {fig:identity-classes} shows which records hang from an account; the two inside the package are the ones that can be revoked without touching the candidate's documents.

@figure identity-classes

#### Inputs

An e-mail address and a password at registration and at sign-in. A session cookie or a bearer token on every later request. Explicit requests for the account and session lifecycle operations.

#### Processing

| Step | Action |
| --- | --- |
| 1 | Create an account from an e-mail address and a password, and store only the Argon2 hash. |
| 2 | Authenticate each request by session cookie or bearer token against a server-side session row. |
| 3 | Require the CSRF header on state-changing requests that carry the session cookie, and exempt bearer-only requests. |
| 4 | Set the cookie HttpOnly and SameSite=Lax, and Secure in production, refusing a production start without it. |
| 5 | List sessions with token prefixes only, and revoke one session, the others or all of them. |
| 6 | Let the holder change their own e-mail, name or password, and end the other sessions when the password changes. |
| 7 | Deliver reset and verification tokens to the mailbox directory, and never write a token to a log. |
| 8 | Deactivate the account on request, end its sessions, and hold the irreversible purge until the grace period ends. |

@requirements 8

#### Outputs

The account record, the session list with masked tokens, the mailbox file that carries a token, and an audit event for each lifecycle operation.

#### Error handling

A wrong password and an unknown e-mail return the same message, so the answer reveals nothing about which one failed. A request without a valid credential returns HTTP 401. A cookie-authenticated unsafe request without the matching CSRF header returns HTTP 403. A new installation has no account to sign into: none is seeded.

### 3.2.9 Authorization and account isolation

#### Introduction

This area decides which rows one account may read and keeps that decision in the data layer, not in each route.

A caller must not learn whether another candidate owns a record they guessed. This covers details, listings of private records, revisions and downloadable files, and not only the navigation entries the console happens to display.

#### Inputs

The authenticated principal, and the identifier of the resource being asked for.

#### Processing

| Step | Action |
| --- | --- |
| 1 | Derive the scope from the authenticated principal, never from a request body field or a query parameter. |
| 2 | Carry an indexed, non-null owner key on every user-scoped table, and leave the shared job corpus without one. |
| 3 | Read user-scoped rows only through scoped accessors that filter by the caller's owner, and refuse a route that queries those tables directly. |
| 4 | Answer a foreign record with HTTP 404 and a body byte-identical to the one a missing record produces. |
| 5 | Keep platform runs owner-optional, and let work items inherit the scope of their run. |
| 6 | Exercise every protected route with two accounts in the automated checks, and hold the zero-disclosure bar. |
| 7 | Attribute each audit event to a user, agent or system principal, and strip control characters from stored audit strings. |

@requirements 9

#### Outputs

The caller's own rows, files and history, and an audit trail the caller may read about themselves.

#### Error handling

A foreign resource returns HTTP 404 with the same bytes as a missing one, so the response reveals nothing about existence. A route that reads a user-scoped table without a scope is a test failure, not a permitted runtime shortcut.

### 3.2.10 Storage, retention and deletion

#### Introduction

This area keeps each account's files inside its own directory and removes records and files when their windows close.

Private files and shared job records have different retention needs. The service must confine private paths and distinguish removing candidate material from keeping an anonymised audit event.

#### Inputs

A retention window per class of data, and a deletion request for an account. The operator runs the purge script on a schedule; nothing purges silently in the background.

#### Processing

| Step | Action |
| --- | --- |
| 1 | Keep each account's résumés, tailored documents and evidence under `data/users/{account}/`. |
| 2 | Check containment on the resolved path of every file the caller names, so a crafted name cannot escape the directory. |
| 3 | Purge a record and its files when the record passes the retention window for its class, and report the counts per class. |
| 4 | Cascade a deleting account's profiles, tailorings, applications, events, evidence, approvals and sessions after the grace period. |
| 5 | Anonymize the deleted account's audit rows instead of deleting them, keeping the action, the outcome and the time. |
| 6 | Keep candidate query vectors out of the shared persistent embedding cache. |
| 7 | Repeat a purge without changing anything the second time. |

@requirements 10

#### Outputs

A purge report naming the rows and files removed, and the anonymized audit rows. Downloads and artifacts served only to the entitled caller.

#### Error handling

A purge that finds nothing is a success and reports zero. A purge that cannot remove a file reports that file and continues with the rest. A download request outside the caller's root is refused whether or not the file exists.

### 3.2.11 Operator console

#### Introduction

This area is the React application through which a candidate does the work of the previous sections.

The console is where a candidate inspects the source, the score explanation, the proposed draft and the decision. When a request fails it must not substitute a successful-looking value, and it must not imply that no work exists.

#### Inputs

The API's OpenAPI description, generated into typed client code at build time, and the responses the API returns.

#### Processing

| Step | Action |
| --- | --- |
| 1 | Serve the bundle with the content security policy restricted to its own origin plus the approved inline bootstrap, and with nosniff, DENY framing, no referrer and a restrictive permissions policy. |
| 2 | Authenticate with the browser's session cookie and the CSRF header, and store no credential in the client. |
| 3 | Present the screens: Home, Resume, Profile, Discover with its filters, the job detail, the preparation flow, Studio, Approvals, Tracker with its case detail, questions and review pages, Account and Security, Activity, and the administrator's Operations and Admin screens. |
| 4 | Wait for the server before showing the outcome of an approve, reject, status, search, tailor or refresh call; a 202 displays a queued run, not an outcome. |
| 5 | Render backend text as text, keep external links to http and https only, and map each known status to a label and a next step. |
| 6 | Give each failure class its own message, honour the Retry-After header on a 429, and refuse a response above the read limit. |
| 7 | Offer the document library for picking an owned document, and explain an inaccessible one in words. |
| 8 | Keep the navigation usable on a narrow screen with the bottom bar and the drawer. |

@requirements 11

#### Outputs

The console screens themselves, driven by the API's own responses, with no state the server did not report.

#### Error handling

A network failure, a timeout, an abort and each of 400, 404, 409, 413, 422, 429 and 503 have their own message. A long call may be cancelled from the console, and the server keeps whatever it had already persisted. An unmapped status keeps the server's literal value with a generic explanation, never an invented outcome.

### 3.2.12 Resource limits and untrusted content

#### Introduction

This area bounds what one caller or one document can cost the system, and keeps hostile text as data.

The service must bound the work one request can start. Web content and uploaded text remain data even when they contain instructions. Refusing an unsafe destination is better than repeating the request through another channel.

#### Inputs

Every request, and every piece of text that came from a job board, a document or a model response.

#### Processing

| Step | Action |
| --- | --- |
| 1 | Reject a request body above 8 MiB with HTTP 413, declared length or not. |
| 2 | Allow an address 60 requests a minute, and answer a refusal with HTTP 429 and a Retry-After header. |
| 3 | Gate the heavy routes with a concurrency bound, returning HTTP 503 while two such requests run. |
| 4 | Cap the process at 64 in-flight requests, waiting up to five seconds for a slot before refusing with HTTP 503. |
| 5 | Fence untrusted prompt blocks behind a fresh nonce the surrounding template does not contain, each block capped. |
| 6 | Strip a recognized embedded instruction from a tailored bullet, and refuse a tailored job title the profile does not support. |
| 7 | Neutralize HTML in board text in one bounded, forward pass over at most 1,000,000 characters per call. |
| 8 | Check every caller-named file path against its authorized root after resolution, and guard a DOCX archive's entry count and declared uncompressed size before opening it. |
| 9 | Apply one forbidden-address predicate to outbound requests, and refuse a disallowed destination before connecting rather than after a redirect. |
| 10 | Serve the interactive documentation in development only. |
| 11 | Bound the persistent vector cache and evict its oldest entries at the limit. |

@requirements 12

#### Outputs

A bounded service, and refusals whose status and message name the limit a request reached.

#### Error handling

A limit produces a refusal whose status says what to do: 413 for size, 429 with Retry-After for rate, 503 for concurrency or saturation. A hostile document is neutralized rather than refused where neutralization is possible, so one bad listing does not stop a refresh.

## 3.3 Use cases

Each use case names its actor, the state the world must be in first, the normal course, the alternatives and failures, and the state the world is in afterwards. The covers line names the requirement groups the use case exercises.

### 3.3.1 UC-1 Upload a résumé

| Item | Description |
| --- | --- |
| Actor | Candidate |
| Precondition | The account is signed in and the database is migrated. |
| Main flow | 1. The candidate selects a supported file in the console and sends it. 2. The service validates the type, size and real structure before storing anything. 3. The parser extracts the fields and the validator produces named warnings for what the document does not state. 4. The service stores the source under a generated name, persists the profile, and returns the identifier, the warnings and the profile. |
| Exceptions | An unsupported, oversize, empty or corrupt file returns HTTP 400 with the cause, and nothing is stored. A file that parses but yields no usable text is refused with a suggestion of a text-based format. |
| Postcondition | The profile is retrievable by identifier by the account that uploaded it, and the document library lists the upload. |
| Covers | FR-1.1 to FR-1.11 |

### 3.3.2 UC-2 Refresh the job corpus

| Item | Description |
| --- | --- |
| Actor | Scheduler, candidate or administrator |
| Precondition | Boards are configured and the embedding provider is ready. |
| Main flow | 1. The actor starts a refresh and receives HTTP 202 with a run identifier. 2. The worker claims the run and queries each configured source. 3. The system drops incomplete postings, merges duplicates, screens machine-generated entries and applies the admission limits. 4. The system upserts the admitted listings and embeds the texts the cache does not hold, checkpointing as it goes. 5. The actor keeps the run identifier and inspects progress and the per-source results. |
| Exceptions | A failed source is named while the others continue. An exhausted quota pauses the run and leaves the outstanding work identifiable. A vector-store failure keeps the rows and marks the embedding degraded. An administrator can resume an eligible recoverable run. |
| Postcondition | The corpus and its vectors reflect the sources that answered, with the reductions disclosed in the report. |
| Covers | FR-2.1 to FR-2.17 |

### 3.3.3 UC-3 Search ranked jobs

| Item | Description |
| --- | --- |
| Actor | Candidate |
| Precondition | A profile exists and the corpus holds listings. |
| Main flow | 1. The candidate selects a stored profile, sets optional query, location and workplace filters, and sends the search. 2. The system loads and filters the stored listings; no job source is contacted. 3. The system reads the semantic channel from the vector store and scores each listing on eight components with a fixed denominator. 4. The system ranks, stores one match row per returned result, and returns the top results with component states, coverage and explanations. 5. The candidate inspects a result's score breakdown against the posting. |
| Exceptions | An unknown or foreign profile returns HTTP 404. An empty selection produces no invented results. Missing semantic evidence returns results with the degraded disclosure, unless the caller asks for indexed jobs only. |
| Postcondition | The match history holds the returned results, newest first, linked to the profile. |
| Covers | FR-3.1 to FR-3.12 |

### 3.3.4 UC-4 Tailor a résumé

| Item | Description |
| --- | --- |
| Actor | Candidate |
| Precondition | A profile and a listing exist, and a model provider is configured, platform or personal. |
| Main flow | 1. The system extracts the job requirements without a model call. 2. The system masks contacts, fences the listing text, and asks the model for a structured draft from profile facts. 3. The validator removes unsupported content and reports each removal. 4. The system computes the ATS report and produces the deliverable, editing a copy in place where safe. 5. The candidate compares the changed wording, inspects the factuality and ATS reports, and downloads. 6. A Studio edit is saved by revalidating the changed text on the same record. |
| Exceptions | A provider failure is classified and reported. Violations are removed and reported rather than raised. The original is kept when the layout cannot be preserved or an edit is declined. An unsupported claim is never inserted to raise keyword coverage. |
| Postcondition | The draft, its reports and its deliverable are stored and retrievable by the owner. |
| Covers | FR-4.1 to FR-4.13 |

### 3.3.5 UC-5 Review and decide on an application

| Item | Description |
| --- | --- |
| Actor | Candidate as approver |
| Precondition | A draft or profile exists, and the target is an allowed host with a permitted adapter. |
| Main flow | 1. The system prepares the application: it selects the adapter, builds the question plan, and stores the review packet with its exact payload. 2. The candidate inspects the packet, its questions and the answers that will be sent, and answers what only a person can answer. 3. On an executable local case, approval records the decision and returns HTTP 202 with a run identifier. 4. The worker re-checks the policy, executes within the adapter's capability, and verifies what it did. 5. The evidence decides the outcome; the status follows the lifecycle. |
| Exceptions | A rejection queues no execution and the case can be re-prepared. A CAPTCHA or MFA challenge stops as `blocked_human_review`. An unknown question stops as `needs_human`. An expired approval or a closed posting returns HTTP 409. A real-board pilot stops for a person and never submits. An uncertain earlier attempt requires reconciliation, never a second automatic send. |
| Postcondition | The packet, the decision, the run, the evidence and the audit trail exist and belong to the account. |
| Covers | FR-5.1 to FR-5.23 |

### 3.3.6 UC-6 Record an outcome

| Item | Description |
| --- | --- |
| Actor | Candidate |
| Precondition | The application case is in a state that permits the requested transition. |
| Main flow | 1. The candidate opens an owned case and selects a permitted transition. 2. The system checks the transition against the lifecycle matrix and the actor against the outcome rule. 3. The system updates the status and appends one event with the actor, the prior state and the new state. |
| Exceptions | An illegal transition returns HTTP 409. A request aimed at another account returns HTTP 404. A machine actor cannot record an outcome. |
| Postcondition | The event history is current, in append order, and unchanged by later edits. |
| Covers | FR-6.1 to FR-6.7 |

### 3.3.7 UC-7 Create an account and sign in

| Item | Description |
| --- | --- |
| Actor | New user |
| Precondition | The service runs and the migrations are applied. |
| Main flow | 1. The user sends an e-mail address and a password. 2. The system stores the account with an Argon2 hash and no seeded role. 3. The user signs in; the system records a session row and sets the session cookie. 4. The user opens the protected console, and unsafe calls carry the CSRF header. 5. Signing out ends the session at the server. |
| Exceptions | A refused credential does not create a session, and a wrong password and an unknown address return the same message. A missing or wrong CSRF header on an unsafe request returns HTTP 403. Public entry points, health and registration, remain reachable. |
| Postcondition | The session exists, the account owns nothing yet, and the registration itself is auditable. |
| Covers | FR-8.1 to FR-8.13 |

### 3.3.8 UC-8 Work in the operator console

| Item | Description |
| --- | --- |
| Actor | Signed-in candidate; administrator for operations |
| Precondition | The account is signed in and the console bundle is served. |
| Main flow | 1. The candidate opens the console and moves between Home, Discover, Studio, Review and Tracker. 2. The candidate uploads, searches, tailors, prepares and decides as in UC-1 to UC-5. 3. The candidate follows each case in the Tracker and reads its evidence. 4. An administrator inspects platform operations: the corpus, the queue, the workers and a recoverable run. |
| Exceptions | A retryable service failure is shown separately from a refused identity, with the Retry-After delay honoured on a 429. A document that is not the caller's is explained without revealing the other owner's data. A hidden control is not an authorization check; the server decides. |
| Postcondition | The profile, tailoring, decision, case and evidence are recorded against the account, and nothing is displayed that the server did not return. |
| Covers | FR-11.1 to FR-11.16, FR-9.1 to FR-9.8, UC-1 to UC-6 |

## 3.4 Classes and observable objects

The object pairs below are kept apart on purpose: each row of the table is a distinction the system actually maintains, and confusing one side with the other is how a system starts claiming outcomes it cannot prove.

| Object | Identity or observable content | Why the distinction matters |
| --- | --- | --- |
| CandidateProfile and ApplicationProfile | Extracted qualifications, kept apart from separately stated preferences and answers | An answer the candidate confirms need not appear on their résumé. |
| JobListing and JobMatchResult | A shared vacancy, kept apart from a profile-specific assessment | Two candidates can receive different scores for the same posting. |
| TailoredResume and FactualityReport | Proposed text, kept apart from the result of checking it against the source | A generated document can exist even when its report records a removed claim. |
| ApplicationRequest and ApplicationResult | The prepared inputs, kept apart from the outcome of a permitted adapter action | Successful preparation says nothing about employer receipt. |
| Application and ApplicationEvent | A case, kept apart from its chronological record of attributed changes | A reported interview is distinguishable from an automated observation. |
| User, Session and UserScope | An account, one authentication session, and the data scope that session permits | Signing out ends a session; it does not remove the account. |
| Document library entry | A reference to an owned original or a generated document | The candidate can tell an upload from a tailored copy. |

The sub-sections below describe each major object with its attributes and the functions that build or act on it. The field names are the ones the code uses.

### 3.4.1 CandidateProfile

#### Attributes

personal_information (name, title, email, phone, location, website), summary, skills, skill_categories, education (degree, institution, dates, gpa, details), experience (title, company, dates, bullets, years), projects (name, subtitle, tech, bullets), certifications, achievements, work_preferences (remote_preference, preferred_locations, min_salary, work_authorization, employment_types), application_profile, warnings.

#### Functions

`parse_resume(path)` builds it from a stored document. `validate_candidate_profile(profile)` returns the named warnings. The application profile holds the answers the candidate confirms separately, such as per-country work eligibility and the voluntary EEO selections, and those answers never flow back into the extracted document. Reference: FR-1.1 to FR-1.11, UC-1.

### 3.4.2 JobListing

#### Attributes

id, source, source_job_id, title, company, description, location, remote_policy, employment_type, salary, currency, seniority, required_skills, preferred_skills, experience_requirements, education_requirements, application_url, company_url, posted_at, metadata. The stored row adds last_seen_at, the freshness column eviction reads.

#### Functions

The four board adapters implement discovery over their public endpoints and a per-job fetch. `deduplicate()` and the cross-source merge act on lists of listings before storage; the description and title are neutralized and capped before a listing is constructed at all. Reference: FR-2.1 to FR-2.17, UC-2.

### 3.4.3 JobMatchResult

#### Attributes

overall_score, semantic_score, lexical_score, skill_score, experience_score, seniority_score, location_score, preference_score, role_score (each 0 to 100), role_family, role_family_confidence, role_targets, role_capped, evidence_coverage, component_states, notes, matched_requirements, missing_requirements, matched_keywords, missing_keywords, sponsor_status, sponsor_note, explanation.

#### Functions

`calculate_match(job, profile, semantic_score, weights)` builds it. `validate_weights()` accepts only a complete, positive, eight-component set summing to 1.0 within tolerance. `blend()` applies the fixed-denominator rule, so an unknown component contributes zero and keeps its weight, and the coverage says how much of the score was measured. A classified hard role mismatch caps the overall score at 25. Reference: FR-3.2 to FR-3.12, UC-3.

### 3.4.4 TailoredResume and FactualityReport

#### Attributes

TailoredResume: summary, highlighted_skills, experience, projects, cover_letter. FactualityReport: passed, removed_skills, removed_experience, removed_projects, violations. The stored row adds the ATS report, the grounded insights and the deliverable path.

#### Functions

`tailor_resume(profile, job, generate)` returns both objects. `extract_requirements(job, skills)` supplies the requirements without a model call. `analyze_ats(tailored, job, profile)` computes the keyword, section, title and format estimate. `deliver_tailored_resume()` renders or edits the deliverable, and `edit_tailored()` revalidates a Studio edit on the same record. Reference: FR-4.1 to FR-4.13, UC-4.

### 3.4.5 Application request and result

#### Attributes

ApplicationRequest (job_title, company_name, job_url, candidate_name, email, phone, resume_path, cover_letter, custom_fields, profile_facts), PreparedApplication (request, prepared_fields, resume_path, cover_letter, prepared_at, requires_manual_review, workflow_id, owner_id), SubmissionEvidence (url, confirmation_text, screenshot_path, trace_path, status), ApplicationResult (success, status, message, evidence, metadata).

#### Functions

An adapter implements `supports_url`, `prepare` and `verify`, and implements `submit` only where the permission registry has granted the capability. The prepared application is stored as the packet, and the worker restores it rather than rebuilding it. Reference: FR-5.1 to FR-5.23, UC-5.

### 3.4.6 Application and ApplicationEvent

#### Attributes

Application: id, owner_id, profile_id, job_id, workflow_id, approval_id, status, submitted_at, verified_at, notes. ApplicationEvent: application_id, event_type, actor, from_status, to_status, metadata, recorded_at.

#### Functions

`transition(app, to, actor, db, metadata)` validates the move against the lifecycle matrix, refuses an illegal one, and appends the event. History reads return events in append order by increasing event ID, never reordered by timestamp. Reference: FR-6.1 to FR-6.7, UC-6.

### 3.4.7 User and Session

#### Attributes

User: id, email, hashed_password, full_name, is_active, is_superuser, is_verified, created_at, updated_at. Session: a row in access_tokens (token, user_id, created_at). There is no separate session table: a session is an owned token row.

#### Functions

The user manager creates and authenticates an account and stores only the Argon2 hash. The session store issues, lists with prefixes, and revokes one, the others or all. Deactivation ends every session at once; the purge follows after the grace period. Reference: FR-8.1 to FR-8.13, UC-7.

### 3.4.8 UserScope

#### Attributes

user_id, is_superuser. Those two fields are the whole contract: whose data may be touched, and whether the platform's operational view may look across owners.

#### Functions

`current_scope()` resolves the authenticated principal into a scope, ignoring any owner the request body or query might name. The scoped accessors in the data layer take that scope and return only the caller's rows; `owns(owner_id)` decides the per-row question. Reference: FR-9.1 to FR-9.8, UC-8.

### 3.4.9 DocumentLibraryEntry

#### Attributes

id (profile-{id} or tailored-{id}), kind (resume or tailored), title, created_at, size.

#### Functions

The library is computed as the union of the caller's profiles and tailorings; it is not a table of its own, so an entry cannot exist without the record it references. The picker returns the selected entry, and the profile it names, to the next action. Reference: FR-11.7, FR-11.8.

## 3.5 Data requirements

The system needs separate records for shared listings, for private profiles and drafts, and for account-scoped decisions and case histories. A packet must keep the question plan it was prepared with, and a case must keep the answers associated with it. The work queue must retain enough to distinguish a new attempt from outstanding work and from completed work.

Figure {fig:er-overview} is the logical view: it names the entities and their relationships without committing to columns or keys. The single feature worth noticing is at the centre. An application case descends from a review packet, never directly from a listing, and a packet in turn descends from a draft.

@figure er-overview

The relational database is managed with Alembic migrations from a single head. Every user-scoped table carries an indexed, non-null owner column, and the shared tables, the job corpus and the imported sponsor registers, carry none. Sessions are owned token rows.

The vector index is a derived store. A current vector must be associated with the correct listing revision, model and dimension. A mismatched or absent index must not invent a relational listing, and it must not remove one. Corpus caching must never persist a candidate's private query as a shared job embedding. Opening the collection with a different model or dimension raises an error that explains how to rebuild, and a disk cache keyed by the model, the dimension and a hash of the text holds corpus vectors and the daily work counter.

| Table | Key fields | Owner |
| --- | --- | --- |
| jobs | id (canonical), source, source_job_id, listing fields, neutralized description, skill lists, last_seen_at | Shared |
| job_boards | board identity, source, freshness of the last completed refresh | Shared |
| form_questions | posting identity, question text, control type, versions | Shared |
| visa_sponsors | name_normalized, name_raw, source, country, year, approvals, denials | Shared |
| users | id, email, hashed_password, full_name, is_active, is_superuser, is_verified | Principal |
| access_tokens | token, user_id, created_at | Principal |
| candidate_profiles | id, owner_id, profile fields, profile_json, file_path, created_at | Per account |
| candidate_eeo | owner_id, profile_id, opt-in selections, updated_at | Per account |
| job_matches | id, owner_id, profile_id, job_id, component scores, explanation, created_at | Per account |
| tailored_resumes | id, owner_id, profile_id, job_id, tailored, factuality, ats_report, insights, docx_path | Per account |
| approval_requests | id, owner_id, workflow_id, adapter_name, job_url, payload, status, approver, reason, decision time, result | Per account |
| applications | id, owner_id, profile_id, job_id, workflow_id, approval_id, status, timestamps | Per account |
| application_events | id, owner_id, application_id, event_type, actor, from_status, to_status, recorded_at | Per account |
| application_evidence | id, owner_id, workflow_id, application_id, job_url, status, screenshot_path, trace_path | Per account |
| application_answers | application_id, question key, saved answer, updated_at | Per account |
| employer_answers | owner_id, question key, reusable answer, employer and role grouping | Per account |
| local_fill_grants | owner_id, review reference, grant record for one fill-only session | Per account |
| llm_credentials | owner_id, encrypted credential, provider, mask, active flag | Per account |
| job_runs | id, run type, status, checkpoint, lease owner, lease expiry | System, owner-optional |
| job_work_items | run reference, item payload, status, lease token, attempt count | Inherited from run |
| job_run_events | run reference, event type, metadata, recorded_at | System |
| worker_heartbeats | worker identity, beat time, queue shape | System |
| circuit_breakers | provider identity, state, opened at | System |
| audit_events | id, owner_id, recorded_at, actor, actor_kind, actor_id, action, resource, outcome, metadata | Per account, anonymized on deletion |

Private document retrieval must check both ownership and the permitted file location, and it must do so on the resolved path. The SDD gives the physical tables, the selected columns and the distinction between an application-level reference and a database foreign key.

## 3.6 Nonfunctional requirements

### 3.6.1 Performance and resource use

The targets below apply to a single installation on a development laptop. Each criterion names what a reviewer must record, because a number without its hardware, corpus and cache context supports nothing.

| ID | Acceptance criterion and baseline qualification |
| --- | --- |
| NFR-P1 | Target: at least 95% of stored searches over 5,000 listings finish within ten seconds. Record the hardware, the corpus, the cache state, the sample count and the percentile. One warm query does not establish this target. |
| NFR-P2 | Instrument one search. At most one query embedding is needed on a miss, and a cache hit may need none. |
| NFR-P3 | Repeat a refresh over unchanged listings whose vectors are complete. It should request no new embeddings. An unchanged listing with missing work is a different case. |
| NFR-P4 | With the default local configuration, observe embedding batches of at most eight texts. This is a work limit, not a throughput promise. |
| NFR-P5 | With default budgets, limit embedding work to 2,000 misses per refresh and 5,000 per day. Exhausting a budget must leave the remaining work identifiable. |
| NFR-P6 | With defaults, reject request bodies above 8 MiB and bound concurrent requests at 64. An individual endpoint may enforce a smaller file limit. |
| NFR-P7 | The earlier console targets were 15 seconds for search and 120 for tailoring. The baseline client allows 120 and 300 seconds respectively. A timeout is a failure to obtain a result, not a completed operation. |

### 3.6.2 Reliability and availability

| ID | Acceptance criterion and baseline qualification |
| --- | --- |
| NFR-R1 | Record a failing source without discarding usable results from the others. A stored search makes no source request at all. |
| NFR-R2 | When vector evidence is missing, keep otherwise eligible jobs and report degraded ranking, unless the caller explicitly asks for indexed jobs only. |
| NFR-R3 | After an embedding quota interruption, identify the outstanding work and do not charge completed embeddings twice. |
| NFR-R4 | For retryable provider failures, enforce the configured attempt limit, backoff and timeout. Check model settings and token accounting without logging prompt bodies. The original target was up to three attempts. |
| NFR-R5 | A second, hidden retry policy inside the client library must not extend a request past its budget. Check timeout behaviour independently of a successful response. |
| NFR-R6 | Preserve partial results where a useful result exists. A failed model-dependent draft, or an unavailable required store, must return an explicit failure rather than invented content. |

This project sets no service uptime percentage. A stored search over a prepared corpus, local configuration and model weights permitting, has different dependencies from a fresh board refresh or a new provider-generated draft. A live API with a stopped worker is not evidence that queued work is progressing.

Résumé upload, stored search, match history, the console, approval and tracking work without network access once the model weights and the first refresh exist. A fresh refresh needs the job boards, drafting needs the model provider, and a browser action needs the target site and the worker. Queued work survives a restart; nothing else in this list claims to.

### 3.6.3 Security and privacy

| ID | Acceptance criterion and baseline qualification |
| --- | --- |
| NFR-S1 | Keep deployment secrets in server configuration, and personal provider credentials encrypted in their store. Neither belongs in model input, in errors or in logs. |
| NFR-S2 | Refuse to start in production with a missing or wildcard CORS origin configuration. |
| NFR-S3 | Validate a destination before making a request to it. A disallowed destination, or a redirect to one, must not be contacted through a fallback. |
| NFR-S4 | Treat listing and page text as data. Embedded instructions cannot choose a tool, change a navigation target, or supply an answer on the candidate's behalf. |
| NFR-S5 | Check the upload type, size and actual structure. A file named as a DOCX must contain a readable Word document. |
| NFR-S6 | Inspect emitted logs and audit records for credentials and for unnecessary identifiers taken from candidate documents. Evidence files need their own access control. |
| NFR-S7 | Before executable submission, require a recorded approval, an allowed host and an adapter that can submit. Only the local test adapter holds that capability. |
| NFR-S8 | Refuse unauthenticated access to protected routes. The acceptable number of successes is zero; a refusal is the expected result. |
| NFR-S9 | With accounts A and B, ensure that A cannot read B's private rows, files or history. Accept zero disclosures. |
| NFR-S10 | Compare the protected-route inventory against two-account isolation tests. Complete coverage is the target; a passing sample does not establish it. |
| NFR-S11 | For any action that changes application or operational state, require a resolvable user or system actor. Review event coverage before claiming full attribution. |
| NFR-S12 | Refuse a state-changing, cookie-authenticated request that lacks the paired CSRF token. This criterion is separate from bearer-token authorization. |
| NFR-S13 | Target: minimise stored personal data and protect the data directory with per-tenant encryption keys. Private directories and encrypted provider keys do not demonstrate per-tenant storage encryption, and this control remains open. |
| NFR-S14 | Target: scan an uploaded document for malware before storing it. File-format and archive validation are not malware scanning, and no completed scanner integration is claimed. |
| NFR-S15 | Keep credentials out of the console bundle. Apply the console's content security policy to scripts, including the explicitly permitted theme bootstrap, and test delivery with the real headers. |

### 3.6.4 Maintainability and portability

| ID | Acceptance criterion and baseline qualification |
| --- | --- |
| NFR-M1 | Core automated checks use local data and provider doubles, without an API key or a database server. Some HTTP tests still resolve DNS, which is why the WS-49 record reported a small number of failures rather than a clean offline run. |
| NFR-M2 | Run the project's configured Ruff checks for Python. The repository sets its line length at 100. |
| NFR-M3 | Supply a forward migration for each persistent schema change and verify it on a database where the earlier migrations are applied. A workstream with no schema change needs no empty revision. |
| NFR-M4 | Justify each new dependency and check the declared dependency set in CI. An installed developer environment is not evidence that every dependency is declared. |
| NFR-M5 | On the configured main-branch workflow, inspect the lint, test, migration and dependency-audit results. Claiming that the latest checks passed requires a new execution. |
| NFR-M6 | Cross-check the README route inventory and the documented settings against the running schema and the configuration contract. Drift must be visible to maintainers. |
| NFR-M7 | Keep a separate console test suite, and run browser tests against the backend and the local fixture. Report an incomplete journey separately from a pass. |

The baseline targets Python 3.13 and a CPU-capable local embedding engine. The schema is managed with Alembic migrations; SQLite is the local default and PostgreSQL is the deployment option. Supporting an option does not establish a production deployment, nor that every combination of operating system and database has been tested.

## 3.7 Inverse requirements

The system must not invent qualifications, answer an unknown eligibility question, treat a posting as an instruction, scrape LinkedIn, or attempt to solve a CAPTCHA or an MFA challenge. It must not seed an account, a password or an administrator; expose another account's private records; keep provider secrets in the frontend bundle; or accept unauthenticated access to a protected function. Deleting an account must not silently erase the attribution that the retention rules require to survive in anonymised form.

A full corpus or an exhausted embedding budget does not authorize unlimited new work. Capacity and eviction rules govern admission, and incomplete work is disclosed. `AUTO_SUBMIT` is outside this release. A timeout, an approval, a button click or an absent confirmation is not proof of submission. When a worker cannot establish what happened after a possible attempt, the case goes to a person without a second automatic send.

The list below states the refusals in the form a test can check. Each is a requirement in its own right, not a restatement.

- The system shall not execute a submission without a recorded approval decision by an authenticated person.
- The system shall not send a form on a real employer's site: no real-board adapter is granted the submit capability, and an approval cannot grant it.
- The system shall not add a skill, employer, title, date, degree or metric that the profile lacks.
- The system shall not scrape web pages or call LinkedIn.
- The system shall not attempt to solve or bypass CAPTCHA or MFA.
- The system shall not send credentials, cookies or API keys to a language model.
- The system shall not report a submission without evidence supporting it.
- The system shall not return one account's rows, files or audit trail to another account.
- The system shall not answer a protected request without a credential.
- The system shall not accept a state-changing request that carries the session cookie and no matching CSRF header.
- The system shall not delete an audit row when an account is deleted; it shall anonymize it.
- The system shall not let the console hold a secret or a token.
- The system shall not let a refresh embed more than the daily budget allows.
- The system shall not let a full corpus stop a refresh; it shall evict the listings it has not seen for the longest.
- The system shall not seed a default account, password or administrator.
- The system shall not silently adopt a recoverable run; recovery is an administrator's explicit act.

## 3.8 Design constraints

The API uses HTTP semantics and publishes an OpenAPI description. The console is a separate React package. The server owns identity and checks private data access in the data layer. Deterministic code owns business rules, score arithmetic and adapter permissions. A model may propose text; its response cannot authorize its own use. Text interchange uses UTF-8, with documented time formats and explicit timestamps in audit records.

### 3.8.1 Standards compliance

- Python code follows PEP 8 as enforced by Ruff, with line length 100 and target version 3.13.
- The API follows HTTP semantics and publishes an OpenAPI description; the README route table is checked against the running application, so undocumented routes fail the suite.
- Timestamps use ISO 8601 in UTC.
- Text files use UTF-8.
- Security controls follow the register in `docs/SECURITY.md`, and the submission preconditions gate any real-site use.
- Embedding use follows the model card, which forbids the fp16 variant.
- Business logic lives in code rather than in prompts. A model supplies text that a deterministic check then verifies.
- Authorization lives in the data layer. A route may not query a user-scoped table directly, and a test enforces the rule.
- The console is a separate package with its own toolchain, and the backend is not restructured to suit it.

## 3.9 Acceptance evidence and the state of the working tree

Three checks answer three different questions, and a reader should keep them apart. The offline ranking fixture shows how the ranker behaves on labelled examples. A browser test against the local ATS can establish a verified fixture submission. The live pilot of 15 November 2026 shows where preparation stopped and which fields a diagnostic pass could fill; it records no submission and no employer confirmation. The SDD evidence index names the records needed to repeat or inspect each check.

Work in progress in the working tree after `7190151` is outside this baseline and is described here so that a reader is not misled by a document that looks more complete than the commit it cites. That work adds optional tailoring to the posting-to-application path, typed question forms, a scoped answer library, a saved review step, and a fill-only local helper with its own grant record. It changes the console and the API surface, and its automated checks had not been reviewed for this edition. None of it alters the submission boundary: the fill-only helper still hands the browser to a person. A later edition should either promote that work into the baseline and register it, or remove it from the tree.
