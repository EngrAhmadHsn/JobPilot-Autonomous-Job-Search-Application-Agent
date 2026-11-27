# 1 Introduction

## 1.1 Purpose

A candidate can spend an afternoon comparing vacancies only to discover, at the application form, that a required answer is missing. JobPilot helps the candidate make two decisions earlier: whether a role fits their background, and whether the information prepared for the employer is accurate. The candidate remains responsible for what they send.

This specification describes revision `7190151` of the Autonomous AI Job Application Agent, called JobPilot in the console. It is the requirements baseline for the final-year project, dated 22 November 2026. The companion Software Design Document (SDD) traces the functional requirement identifiers to components and evidence. Later development is outside this baseline.

## 1.2 Scope

A signed-in candidate can upload a résumé, inspect the extracted profile, search stored jobs, compare a tailored draft with the source, review application questions and follow recorded outcomes. An administrator operates the shared job corpus and the worker that processes background work. JobPilot does not predict the likelihood of an offer, verify a candidate’s qualifications with an employer or synchronise recruiting decisions from an employer’s system.

The local fake applicant tracking system (ATS) accepts test applications. A separate Greenhouse pilot can inspect a live form and prepare supported controls for a person to review. The adapter has no permission to submit. The live pilot supplied no evidence that an employer accepted an application. This distinction applies wherever the requirements use the word “submission”.

## 1.3 Terms and conventions

| Term | Meaning in this project |
| --- | --- |
| Candidate profile | The facts extracted from an uploaded résumé. An absent fact remains unknown. |
| Application profile | Answers and preferences the candidate supplies separately, such as the countries in which they may work. |
| Corpus | The shared collection of stored job listings. A refresh updates it; a search reads it. |
| Match | A score and explanation for one profile and one posting. It is a recommendation, not an interview prediction. |
| Review packet | The prepared application inputs, document references and question plan that the candidate is asked to inspect. |
| Approval | A recorded decision by an authenticated person about a particular packet. |
| Run | A unit of background work with its own identifier. A queued run has no submission result. |
| Evidence | The records and artifacts used to check what an adapter observed, such as a confirmation and a screenshot. |
| Factuality report | The validator’s account of unsupported changes it found. A clean report is not independent verification of every sentence. |

In the register, Implemented means the baseline contains the stated behavior. Limited identifies a restriction or difference described by the acceptance check. Deferred means the baseline does not meet the requirement. An acceptance check tells a reviewer what to observe. It does not claim that a fresh test was run for this edition.

## 1.4 References and reading order

The project architecture, security register and operating instructions are in `docs/ARCHITECTURE.md`, `docs/SECURITY.md` and `docs/RUNBOOK.md` at the named revision. Workstreams 32, 45 and 47 document the assist pilot, application questions and Studio editing. Workstream 49 records the most recent baseline verification and its limits. Chapter 2 sets the boundary; chapter 3 contains the interface contracts, requirement register, use cases and quality criteria.

# 2 Overall description

## 2.1 Product perspective

JobPilot sits between a candidate’s private records and several outside services. A job board supplies public listing data; it does not receive a résumé when the candidate searches. A configured model provider may supply draft wording. Neither a listing nor model output can grant permission to operate a browser. Figure {fig:context} separates these exchanges from the candidate’s decision.

@figure context

## 2.2 Product functions

Discovery, ranking and drafting can each produce a useful result without starting an application. A candidate can reject an inaccurate draft, download a document, or leave a vacancy unpursued. If they request preparation, the next result is a review packet. The conditions for sending a test application depend on the selected adapter as well as the decision on that packet.

@figure function-scope

## 2.3 Users and responsibilities

The candidate owns the résumé, confirmed answers, drafts and case history. They decide whether to accept proposed wording and record later outcomes, including an interview or withdrawal. The administrator can inspect platform operations and recover eligible interrupted runs. Administrative access to operations is not permission to approve another candidate’s packet. An employer controls its form, verification challenges and final receipt.

@figure use-cases

## 2.4 Operating conditions and assumptions

The console requires a browser and an authenticated connection to the API. Local search needs a populated corpus and a stored profile. It can still return results when semantic evidence is missing, provided the response discloses the reduced coverage. A fresh corpus needs access to its configured public sources. Draft generation needs a configured model provider; saving supported edits to an existing draft does not require a new model call.

The API and background worker must have access to the same configured records and private artifact storage. A responsive API does not prove the worker is available. A closed posting, an inaccessible board or an unsupported field can make preparation incomplete. Unknown answers, particularly work eligibility, are for the candidate to resolve. Deployment and recovery details are in the SDD.

# 3 Specific requirements

## 3.1 External interfaces

| Interface | Contract a reviewer can observe |
| --- | --- |
| Candidate and console | The browser displays account-scoped results, unresolved questions and status. It distinguishes request acceptance, errors and verified evidence. |
| Console and service | The HTTP API publishes its schema. Protected calls carry the authenticated session or a permitted bearer token. A state-changing browser request using a cookie also needs a matching CSRF token. |
| Public job sources | Refresh reads configured Greenhouse, Lever, Ashby and Remotive endpoints. A stored search must not repeat that collection step. |
| Model and local embedding engine | A configured provider can generate structured text. The baseline uses local embeddings for search. Missing vectors do not establish a poor semantic match. |
| Application adapter | The target must be allowed and the adapter must hold permission for the requested action. A real-board handoff is not an application receipt. |
| Files and storage | The service accepts documented résumé formats and returns private documents and evidence only to an entitled caller. It has no special-purpose hardware interface. |

The route table in the project `README.md` and the OpenAPI schema define exact paths and verbs. In particular, deciding a packet uses an approval ID; opening its case history or saved questions uses the application ID. Operations uses a run ID. Interchanging those identifiers is not a supported shortcut.

## 3.2 Functional requirements

### 3.2.1 Résumé intake and profile extraction

An unreadable document is different from a readable document with no education section. Intake must explain which occurred. It must not manufacture profile content to fill an empty section.

@requirements 1

### 3.2.2 Job discovery and refresh

Refresh updates a shared corpus. It can outlive the browser request, so acceptance and completion are reported separately. A listing that has not changed should not consume embedding work again.

@requirements 2

### 3.2.3 Matching, ranking and search

The score combines semantic, lexical, skill, experience, seniority, location, preference and role evidence. A missing value and a known mismatch can both lower a score, but the explanation must tell the candidate which occurred.

@requirements 3

### 3.2.4 Tailoring and document analysis

Studio produces a draft for one profile and one job. A higher keyword count is no reason to add a skill the source does not support. An edit must pass back through the document checks before the new deliverable is presented.

@requirements 4

### 3.2.5 Application preparation and decisions

A successful decision request returns HTTP 202 and identifies queued work. It does not show that the worker has filled a field, clicked Submit or obtained a receipt. The rows below distinguish those events, the capabilities required for each, and the evidence expected after execution.

@requirements 5

### 3.2.6 Application tracking

A tracker entry shows the recorded history of a case. A person can report a later interview or offer. The application does not infer an employer’s decision from elapsed time or from the absence of a reply.

@requirements 6

@figure application-state

### 3.2.7 Evaluation

A score from a labelled teaching fixture is useful for comparing two versions of the ranker. It is not a measured success rate on live vacancies. Reproducibility requires the dataset and provider settings alongside the metric.

@requirements 7

### 3.2.8 Identity and account lifecycle

Registration, sign-in, sign-out and deletion affect different records. Closing a browser tab is not a request to delete the account or its documents.

@requirements 8

### 3.2.9 Authorization and account isolation

A caller must not learn whether another candidate owns a guessed record. This applies to details, listings of private records, revisions and downloadable files, not just to the navigation entries the console displays.

@requirements 9

### 3.2.10 Storage, retention and deletion

Private files and shared job records have different retention needs. The service must confine private paths and distinguish removing candidate material from retaining an anonymised audit event.

@requirements 10

### 3.2.11 Operator console

The console provides a place to inspect the source, score explanation, proposed draft and decision. When a request fails, it must not replace a missing value with a successful outcome or imply that no work exists.

@requirements 11

### 3.2.12 Resource limits and untrusted content

The service must limit the work a request can start. Web content and uploaded text remain data even if they contain instructions. Refusing an unsafe destination is preferable to repeating the request through a different channel.

@requirements 12

## 3.3 Use cases

| ID / primary actor | Normal course | Alternative or failure |
| --- | --- | --- |
| UC-1 · Candidate: upload a résumé | Select a supported file while signed in. The service validates it, stores the source and returns extracted fields and warnings. | Reject an unreadable file; ask for a text-based PDF or another supported format when no usable text exists. |
| UC-2 · Authorized requester: refresh jobs | Request a refresh, retain the run ID and inspect progress and source results. The worker writes eligible changes. | Report a failed source or interrupted work. An authorized administrator can resume an eligible recoverable run. |
| UC-3 · Candidate: search ranked jobs | Select a stored profile, set filters and inspect a result’s score breakdown against the posting. | An empty selection produces no invented results. Missing semantic evidence is disclosed. |
| UC-4 · Candidate: tailor a résumé | Select a vacancy and owned source, request a draft, compare changed wording and inspect the validation reports before download. | Surface a provider failure or unsupported claim. Keep the original when layout preservation is unavailable or an edit is declined. |
| UC-5 · Candidate: review and decide | Inspect a prepared packet and its questions. On an executable local test case, approval records the decision and returns a run ID; later evidence determines the outcome. | Reject, re-prepare, or stop on a blocking question. A real-board pilot stops for a person. An uncertain prior attempt requires reconciliation. |
| UC-6 · Candidate: record an outcome | Open an owned case and select a permitted transition. Record the actor and prior and new states in its history. | Reject an invalid transition or a request that targets another account. A manually recorded outcome is not an employer receipt. |
| UC-7 · Candidate: create an account and sign in | Register, authenticate and open the protected console. Sign-out ends the session. | A refused credential does not establish a session. Public entry points remain reachable. |
| UC-8 · Candidate or administrator: use the console | Move between Home, Discover, Studio, Review and Tracker. An administrator can also inspect platform operations. | Display a retryable service failure separately from a refused identity. A hidden control is not an authorization check. |

## 3.4 Classes and observable objects

| Object | Identity or observable content | Why the distinction matters |
| --- | --- | --- |
| CandidateProfile / ApplicationProfile | Extracted qualifications versus separately stated preferences and answers | An answer confirmed by the candidate need not appear on their résumé. |
| JobListing / JobMatchResult | A shared vacancy versus a profile-specific assessment | Two candidates can receive different scores for the same posting. |
| TailoredResume / FactualityReport | Proposed text and the result of checking it against the source | A generated document can exist even when the report identifies a removed claim. |
| Application request / result | The prepared inputs versus the outcome of a permitted adapter action | Successful preparation does not show employer receipt. |
| Application / ApplicationEvent | A case and its chronological record of attributed changes | A manually entered interview or offer is distinguishable from an automated observation. |
| User / Session / UserScope | An account, one authentication session and its permitted data scope | Signing out ends a session; it does not remove the account. |
| Document library entry | A reference to an owned original or generated document | The candidate can distinguish the uploaded file from a tailored copy. |

## 3.5 Nonfunctional requirements

### 3.5.1 Performance and resource use

| ID | Acceptance criterion and baseline qualification |
| --- | --- |
| NFR-P1 | Target: at least 95% of stored searches over 5,000 listings finish within ten seconds. Record hardware, corpus, cache state, sample count and percentile. An isolated warm query does not establish this target. |
| NFR-P2 | Instrument one search. At most one query embedding is needed on a miss; a cache hit may need none. |
| NFR-P3 | Repeat a refresh with unchanged listings whose current vectors are complete. It should request no new embeddings. An unchanged listing with missing work is a different case. |
| NFR-P4 | With the default local configuration, observe embedding batches of at most eight texts. This is a work limit, not a throughput guarantee. |
| NFR-P5 | With default budgets, limit embedding work to 2,000 misses per refresh and 5,000 per day. Exhaustion must leave remaining work identifiable. |
| NFR-P6 | With defaults, reject request bodies above 8 MiB and bound concurrent requests at 64. An endpoint may enforce a smaller file limit. |
| NFR-P7 | The earlier console targets were 15 seconds for search and 120 for tailoring. The baseline client instead allows 120 and 300 seconds respectively. A timeout is a client failure to obtain a result, not a completed operation. |

### 3.5.2 Reliability and availability

| ID | Acceptance criterion and baseline qualification |
| --- | --- |
| NFR-R1 | Record a failing source without discarding usable results from other sources. A stored search makes no source request. |
| NFR-R2 | When vector evidence is missing, keep otherwise eligible jobs and report degraded ranking unless the caller explicitly requests indexed jobs only. |
| NFR-R3 | On recovery from an embedding quota interruption, identify outstanding work and do not charge completed embeddings again. |
| NFR-R4 | For retryable provider failures, enforce the configured attempt limit, backoff and timeout. Verify model settings and token accounting without logging prompt bodies. The original target was up to three attempts. |
| NFR-R5 | Do not allow a second, hidden SDK retry policy to extend a request past the client’s time budget. Check timeout behavior independently of a successful response. |
| NFR-R6 | Preserve partial results where a useful result exists. A failed model-dependent draft or an unavailable required store must return an explicit failure rather than fabricated content. |

The FYP sets no service uptime percentage. Stored search after the corpus is prepared, local configuration and model weights permitting, has different dependencies from a fresh board refresh or a new provider-generated draft. A live API with a stopped worker must not be reported as evidence of queue progress.

### 3.5.3 Security and privacy

| ID | Acceptance criterion and baseline qualification |
| --- | --- |
| NFR-S1 | Keep deployment secrets in server configuration and personal provider credentials encrypted in their store. Neither kind belongs in model input, errors or logs. |
| NFR-S2 | Refuse production startup with a missing or wildcard CORS origin configuration. |
| NFR-S3 | Validate destinations before making outbound requests. A disallowed destination or redirect must not be contacted through a fallback. |
| NFR-S4 | Treat listing and page text as data. Embedded instructions cannot choose a tool, change a navigation target or provide an answer on the candidate’s behalf. |
| NFR-S5 | Check upload type, size and actual structure; a file named as a DOCX must contain a readable Word document. |
| NFR-S6 | Inspect emitted logs and structured audit records for credentials and unnecessary identifiers from candidate documents. Evidence files require separate access controls. |
| NFR-S7 | Before executable submission, require a recorded approval, an allowed host and a submission-capable adapter. Only the local test adapter has that capability. |
| NFR-S8 | Refuse unauthenticated access to protected routes. The acceptable count of unauthorized successes is zero; a refusal is the expected result. |
| NFR-S9 | With accounts A and B, ensure that A cannot read B’s private rows, files or history. Accept zero disclosures. |
| NFR-S10 | Compare the protected-route inventory against two-account isolation tests. Complete coverage is the target; a passing sample alone does not establish it. |
| NFR-S11 | For actions that change application or operational state, require a resolvable user or system actor. Review event coverage before claiming full attribution. |
| NFR-S12 | Refuse state-changing cookie-authenticated requests without the paired CSRF token. This criterion is separate from bearer-token authorization. |
| NFR-S13 | Target: minimise stored personal data and protect the data directory with per-tenant encryption keys. Private directories and encrypted provider keys do not demonstrate per-tenant storage encryption; this control remains open. |
| NFR-S14 | Target: scan an uploaded document for malware before storage. File-format and archive validation are not malware scanning; no completed scanner integration is claimed. |
| NFR-S15 | Keep credentials out of the console bundle. Apply the console’s content security policy to scripts, including the explicitly permitted theme bootstrap. Test delivery with the actual policy headers. |

### 3.5.4 Maintainability and portability

| ID | Acceptance criterion and baseline qualification |
| --- | --- |
| NFR-M1 | Core automated checks use local data and provider doubles without an API key or a database server. Some HTTP tests still resolve DNS; this prevented a fully offline green run in the WS-49 record. |
| NFR-M2 | Run the project’s configured Ruff checks for Python. The repository sets its line-length convention at 100. |
| NFR-M3 | Supply a forward migration for each persistent schema change and verify it on a database with earlier migrations applied. A workstream with no schema change needs no empty revision. |
| NFR-M4 | Justify new dependencies and check the declared dependency set in CI. An installed developer environment alone is not evidence that all dependencies were declared. |
| NFR-M5 | On the configured main-branch workflow, inspect lint, tests, migration and dependency-audit results. A new execution is required before claiming the latest checks passed. |
| NFR-M6 | Cross-check the README’s route inventory and documented settings with the running API schema and configuration contract. Drift must be visible to maintainers. |
| NFR-M7 | Keep a separate console test suite and browser tests against the backend and local fixture. Report incomplete journeys separately from passes. |

The baseline targets Python 3.13 and a CPU-capable local embedding engine. The database design uses Alembic migrations; SQLite is the local default and PostgreSQL is a deployment option. Support for an option does not establish a production deployment, or that every operating-system and database combination has been tested.

## 3.6 Inverse requirements

The system must not invent qualifications, answer unknown eligibility questions, treat a posting as an instruction, scrape LinkedIn, or attempt to solve CAPTCHA or MFA. It must not seed an account, password or administrator, expose another account’s private records, keep provider secrets in the frontend, or accept unauthenticated access to protected functions. An account deletion must not silently erase the attribution history that retention rules require to remain anonymised.

A full corpus or exhausted embedding budget does not authorize unlimited new work. Capacity and eviction rules govern admission, with incomplete work disclosed. `AUTO_SUBMIT` is outside the release. A timeout, approval, button click, or absent confirmation is not proof of submission. When a worker cannot establish what happened after a possible attempt, the case goes to a person without an automatic second send.

## 3.7 Logical database requirements

The service needs distinct records for shared listings, private profiles and drafts, and account-scoped decisions and case histories. It must preserve the question plan used for a packet and the answers associated with its application. The work queue must retain enough information to distinguish a new attempt, outstanding work and a completed item. The SDD data dictionary identifies the relevant fields and distinguishes application-level references from database foreign keys.

The vector index is a derived store. A current vector must be associated with the correct listing revision, model and dimension. A mismatched or absent index must not invent or remove a relational listing. Corpus-vector caching must not persist a candidate’s private query as a shared job embedding. Private document retrieval must check ownership and permitted file location.

## 3.8 Design constraints and acceptance evidence

The API uses HTTP semantics and publishes an OpenAPI description. The console is a separate React package. The server owns identity and checks private data access in the data layer. Deterministic code owns business rules, score calculations and adapter permissions. A model may suggest text; its response cannot authorize its own use. Use UTF-8 for text interchange, documented time formats and explicit timestamps in audit records.

For the examination, three checks answer different questions. The offline ranking fixture shows how the ranker behaves on labelled examples. A browser test against the local ATS can establish a verified fixture submission. The live pilot of 15 November 2026 shows where preparation stopped and which fields a diagnostic pass could fill, but no submission or employer confirmation. The SDD evidence index identifies the records needed to repeat or inspect each check.
