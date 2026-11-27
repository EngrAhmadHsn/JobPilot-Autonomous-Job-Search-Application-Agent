# 1 Introduction

## 1.1 Purpose

This Software Design Document describes the architecture and design of JARVIS, the Job Application and Resume Vetting Intelligent System. It states how the system is decomposed, what each part owns, how the parts exchange data, and how the design answers the requirements in the Software Requirements Specification, Version 3.0. It describes revision `7190151` of 22 November 2026.

It is written for two readers. A maintainer who has to change the system uses it to find the module that owns a behaviour, the records it reads and writes, and the test that holds it in place. A supervisor uses it to check that the design answers the requirements and that the security decisions were taken deliberately. The document records what the code does, including the limits of what has been demonstrated.

Two things in this edition deserve attention before the design. On a real employer's site the adapter prepares the form and hands the browser to a person; it holds no submit capability, so the stop is a property of the permission model rather than of a prompt instruction. The figures have also been redrawn in the university's monochrome style, and the console plates have been replaced with captures of the current interface.

## 1.2 Scope

The document covers the whole system: the Python backend, its relational and vector stores, the separately supervised worker and the browser automation that fills an employer's form, and the React operator console that a person drives. It covers the flows that carry the product's value: refreshing the job corpus from public job-board APIs, ranking that corpus against a candidate's profile, tailoring a résumé with validation, and preparing, deciding and executing an application packet. The local fake applicant tracking system (ATS) is the only target for an executable submission and its verification.

The design assumes the project goals in the plan: a modular monolith rather than a set of services, deterministic code rather than model reasoning wherever a rule can be written down, and a recorded human decision before anything irreversible. It does not describe the deployment topology beyond what the code already assumes, and it does not cover the fake applicant tracking system's internal pages, which exist only to exercise the browser layer.

A match is a recommendation. A prepared application is a packet for review. An approval authorizes work on that packet; it does not establish that an employer received anything. Sections 5.9 and 8.4 give the evidence for that distinction.

## 1.3 Overview

Chapter 2 sets the system boundary and the responsibilities that the rest of the document assumes. Chapter 3 gives the architecture: the layers, the decomposition into components, the deployment and the decisions behind all three. Chapter 4 describes the stored data, its provenance, its dictionary and its retention. Chapter 5 follows the components through intake, refresh, ranking, tailoring and the application workflow, one subsection per significant function. Chapter 6 gives the human interface design, with the console plates taken from a running instance. Chapter 7 traces each requirement to a design responsibility and an evidence key. Chapter 8 holds the route indexes, the dated evidence and the specialist views that would interrupt the narrative.

Figures are numbered in one sequence that includes the console plates, and a reference such as Figure {fig:packages} resolves to the number printed beneath the image. Each diagram is drawn from the models, migrations or transition tables rather than from prose, and its caption names the view it provides. A citation of a test or an evaluation names a place to look. It does not assert that the check was run for this edition, and section 8.4 states which records exist and when they were produced.

## 1.4 Reference material

- Software Requirements Specification, Version 3.0, docs/SRS.docx. Project repository.
- Project plan, docs/PROJECT_PLAN.md. Project repository.
- Architecture document, docs/ARCHITECTURE.md. Project repository.
- Security model, threat model and control register, docs/SECURITY.md. Project repository.
- Implementation roadmap and the workstream documents, docs/implementation/. Project repository.
- Operator console guide, frontend/README.md. Project repository.
- Operations runbook, docs/RUNBOOK.md. Project repository.
- Evaluation baseline, docs/evaluations/report-2026-10-21.md. Project repository.
- IEEE Std 830-1998, Recommended Practice for Software Requirements Specifications. IEEE.
- Ian Sommerville, Software Engineering, Tenth Edition. Pearson.

## 1.5 Definitions and acronyms

| Term | Meaning |
| --- | --- |
| Adapter | A module that maps one external source or site to a common interface. |
| Answer library | The answers a candidate has confirmed for one application, stored per owner, application and question key. |
| Approval record | The stored copy of a prepared packet, its payload and its question plan, and the decision taken on it. |
| Attempt marker | The durable record a worker writes immediately before it calls an adapter's submit capability. |
| ATS | Applicant tracking system, the software an employer uses to receive applications. |
| Bounded | A limit the system enforces rather than assumes, such as a request size, a rate, a queue depth or a daily budget. |
| BM25 | The lexical ranking function the search uses over posting text. |
| BYOK | Bring your own key: a model credential an account stores for its own calls. |
| Cache miss | A text whose vector is not in the embedding cache. Only a miss costs an embedding. |
| Capability | A permission, prepare, submit or verify, granted to one adapter by name in the registry. |
| Chroma | The vector store that holds one vector per corpus listing. |
| Circuit breaker | Per-connection state that fails fast after repeated provider failures. |
| Corpus | The set of job listings stored in the database and shared by every account. |
| CSRF | Cross-site request forgery, an attack that makes a browser send a state-changing request it did not intend. |
| Degraded scoring | What search reports when some listings have no usable vector: the missing weight stays in the denominator, contributes zero, and the coverage is stated. |
| Evidence | The confirmation text, screenshot, action trace and status stored for a submission attempt. |
| Evidence key | The E-numbered pointer the requirements matrix uses for a source file, a test specification or a dated evaluation. |
| Eviction | The removal of the listings a refresh has not seen for the longest, so that the corpus cap is a window and not a one-way door. |
| Factuality report | The record of everything the validator removed from a tailored résumé, with the reason for each removal. |
| Fail closed | The rule that an ambiguous or unproven condition stops the run rather than lets it continue. |
| Fake ATS | The local fixture that is the only target where a complete submission and its verification were exercised. |
| Fence | The nonce-delimited block that separates untrusted text inside a prompt from the instructions around it. |
| JARVIS | The Job Application and Resume Vetting Intelligent System, the name this document uses for the whole system. |
| Lease | The claim token a worker holds on a work item; renewal and settlement must carry the current token. |
| nDCG | Normalized discounted cumulative gain, the ranking quality metric the evaluation reports at rank ten. |
| Packet | A prepared application: the resolved inputs, facts and document references stored for review. |
| Personal credential | A model-provider key stored encrypted for one account. |
| PII | Personally identifiable information. |
| Principal | The thing an action is attributed to, recorded as a kind and an identifier. |
| Question plan | The board's questions for one posting, stored with the packet in the order the board asked them. |
| Run | A durable record of accepted background work, with item counters and an event history. |
| Session | A server-side row that records a signed-in account, so a session can be ended at once. |
| Sponsorship register | The table of employers known to have sponsored visas; a finding there is evidence, not a promise for a role. |
| Studio | The console workspace where a draft is compared with the original and edited. |
| submission.uncertain | The escalation recorded when an attempt marker exists and no durable outcome does; a person reconciles it. |
| Tenant | One account and everything it owns. |
| Tracker | The console view of recorded applications and their histories. |
| Worker | The separately supervised process that claims work items under a lease, and the only part of the system that opens a browser. |
| Work item | One unit of durable work, with a work type, a content hash, a model identity and a lease. |

# 2 System overview

## 2.1 People, inputs and decisions

The system is a Python service that turns a candidate's résumé into a shortlist of jobs and, with a recorded human decision, into a prepared application packet. It has four parts. The operator console is the person's side: a React application in its own package that shows what the agent has read, what it has decided, and what it needs a person to do next. The REST API is the machine's side: a FastAPI application that authenticates the caller, resolves what that caller may read, validates what arrives, records decisions and queues accepted work. The worker is a separate supervised process that claims that work under a lease, carries it out within its adapter's permissions, and is the only part of the system that opens a browser. The domain modules do the actual thinking, and they do it in code: a refresh that collects and normalizes job listings, a matcher that scores stored listings against a profile, a tailorer that writes a job-specific résumé and then checks it, and a workflow that prepares an application, waits for a person's decision and, for the local fake ATS only, submits and verifies. The stores hold the state: a relational database for everything that belongs to a person and for the shared corpus, a vector store for the meaning of the job descriptions, and a directory tree for the files.

The candidate uploads a résumé, checks the extracted facts, and supplies answers that the document cannot establish. A corpus refresh collects publicly available postings independently of any one candidate. Discover ranks those stored postings for a selected profile. The candidate can open a result in Studio, review a proposed change against the original, and prepare a packet. A separate decision records who approved or rejected it. If an interview or an offer follows, a person records that outcome in Tracker.

An administrator looks after the shared corpus and the worker, including recovery after an interruption. Operational access of that kind does not extend to making an application decision in another candidate's name. Job boards supply listing and form data. A configured language model helps extract listing facts and draft text. Neither a board nor a model adds authority to the actions the design permits; section 2.2 states what each party owns and why.

## 2.2 Four parties and their responsibilities

Four parties appear in every flow, and confusing them is the commonest way to misread the system. The candidate is the person whose documents and decisions are at stake. The API is the service that authenticates a request, validates it, records a decision and returns an answer. The worker is a separate process that carries out accepted background work under a lease, and it is the only part of the system that opens a browser. The employer owns the form, any verification challenge and the final receipt.

| Party | Owns | May not |
| --- | --- | --- |
| Candidate | The résumé, the confirmed answers, the drafts and every approval decision | Approve another account's packet, or require the system to answer an unknown eligibility question |
| API | Authenticated access, validation, the decision record and queued work | Fill a form, press a button or claim an outcome |
| Worker | Claiming work, running the approved adapter, recording evidence and settling the lease | Act without an approval, act beyond its adapter's capability or retry a possible submission blindly |
| Employer | The form, any verification challenge and whether an application was received | Grant the agent any authority by publishing a page |

Two boundaries shape the design. The first is between the system and the web. Job listings and employer application pages are untrusted input. They arrive as data, they are never executed as instructions, and a text taken from them is fenced inside a nonce-delimited block before it reaches a prompt. The second boundary is between accounts. Every row that belongs to a person carries the account that owns it, and the data layer is the only place that reads such a row, so a route cannot leak another account's data by forgetting a check.

The system reports what it did rather than what it intended to do. A refresh that lost a job board returns the board's name in the report. A search that cannot read every vector reports degraded scoring and the coverage it did measure. An application that could not be verified returns no success. Nothing in the product claims more than it can show.

The division matters most at the moment of acceptance. A 202 response proves exactly one thing: the API accepted the request and committed the record that corresponds to it. It proves nothing about a form being filled, a button being pressed or a receipt existing. On an executable local case the response carries a run identifier, and the worker acts afterwards, in another process and often in another session. Only the worker's recorded evidence, such as the confirmation page it checked and the files it stored, supports the stronger claim, and that claim holds only inside the fixture.

A job board and a language model cannot grant authority to operate a browser. A board publishes a form because it wants applications, and that intention is not a permission conferred on this system. A model produces text on request; its output cannot widen its own authority, choose a destination or become an answer on the candidate's behalf. Authority here comes from three sources only: a recorded decision by an authenticated person, an allowed destination, and an adapter that holds the capability at the point of the call. Nothing else adds to it.

An administrator is a candidate with additional operational access. That access covers the corpus, the worker and the recovery of an interrupted run. It does not extend to approving a packet in someone else's name, and the routes enforce the difference rather than relying on which controls the console happens to display.

## 2.3 Design choices

The system keeps one shared copy of a posting and private records of each candidate's matches. This lets two people search the same corpus without sharing a résumé or a search history. Fetching and ranking are separate operations: a search can proceed while a board is down, although its results are only as current as the stored listings. Keeping source facts separate from drafts also gives the reviewer something independent against which to check a proposed claim.

The corpus is also the reason the search is cheap and repeatable. Ranking reads stored rows and a local index, so a search spends no network budget and no embedding budget on the query path beyond the candidate's own text, and two searches over the same corpus and the same profile produce the same order. The price is freshness, and the source timestamp on each listing states it rather than hiding it.

## 2.4 The life of one application

One path through the system shows where each part acts. The candidate uploads a résumé; intake validates the file, parses it into a profile and stores both under the account. The candidate confirms what the document cannot establish: work preferences, eligibility by country, and the answers the employer's questions will need. A refresh, on its own schedule, collects postings from the configured boards into the shared corpus.

The candidate opens Discover, which ranks the stored corpus for the selected profile and explains each score. For one result the candidate opens Studio, which proposes wording grounded in the résumé, shows the factuality and ATS reports, and lets the candidate compare and edit before saving. From the same result the candidate prepares a packet: the system checks the destination, builds the payload, stores the employer's questions and stops.

Review shows the packet, the questions and the proposed answers. The candidate answers what the document cannot supply and approves or rejects. An approval returns 202 with a run identifier; the worker then acts, and only the local fake ATS accepts an executable run. The worker fills the form with grounded facts, records the confirmation text, the screenshot and the trace, and settles the lease. Tracker shows the recorded application and its history, and a person records any later outcome, such as an interview or a rejection, in their own name. On a real employer's site the path ends earlier by design: the adapter prepares and hands the browser back, and no submission exists to verify.

# 3 System architecture

## 3.1 Architectural design

The backend is a modular monolith. The HTTP routes obtain the caller's identity and validate requests. Domain packages implement parsing, matching, drafting and form preparation. The database package supplies access to stored records; the security package supplies checks that both routes and workers can call. Keeping the adapter registry outside the route layer lets the API select an adapter by URL and the worker resolve the same adapter by its recorded name.

The separation that matters runs between the layers, because the layers have different reasons to change. The presentation layer is the console and the command-line scripts. The interface layer is the HTTP surface, the identity machinery and the workflow orchestration. The domain layer holds the behaviour that the product is actually for, and it is the only layer that knows what a job listing, a candidate profile or a match means. The infrastructure layer holds the things the domain layer asks for: the database, the vector store, the file system, the security controls and the logging.

Figure {fig:packages} shows the packages and the direction of the dependencies between them. A domain package may call another domain package and the infrastructure packages; it does not import from the interface layer and does not know that HTTP exists. The interface layer may call the domain layer and the infrastructure layer; it contains no business rules. The console is a separate package with its own toolchain and tests, and the API is the only contract the two sides share. The console's API types are generated from the API's OpenAPI description, so a route that changes shape before the console regenerates breaks the console's build rather than its screen.

@figure packages

## 3.2 Runtime components and decomposition

FastAPI serves requests. Short operations, such as reading a profile or ranking stored jobs, return a result directly. A refresh or approved submission returns a durable run identifier; another process performs the work. LangGraph expresses the job-processing stages and the branches of the application workflow. It does not provide the durable worker queue. SQL records which work remains even after the request, browser tab or worker process ends.

Figure {fig:components} shows the same arrangement as components and calls. The API writes a work item and returns its identifier. The worker claims the item under a lease token, calls the domain executor and settles the item under the same token. A stale worker cannot settle work that another process has claimed.

@figure components

The decomposition has three views, and each answers a question the others cannot. The class diagrams in section 4.1 are the vocabulary the code is written in. The object diagram in section 4.1 is one moment in time, and it shows values rather than types. The sequence, activity and state diagrams in section 5 are the behaviour, one per significant flow.

The class views carry the product's vocabulary. The domain classes relate the candidate, the listing and the match. The drafting classes carry the tailored résumé and its reports. The adapter contracts carry the application requests, the prepared packet, the result and the evidence. Two of these records deserve their sentences. The factuality report is not a note on the tailored résumé; it is the record of everything the validator took out of it, and it is what the console shows beside the draft. The capability an adapter exercises is granted by the registry, not inherited from its class, and section 4.1 draws the grant as part of the contract.

The object view answers the question a class diagram cannot: what the system actually holds at a given moment. One signed-in account, the profile parsed from its résumé, a listing from the corpus with the match scored against that profile, a draft that was written and then checked, and the approval record waiting for a person. Section 4.1 draws that moment as three identifiers, each of which lets the console retrieve one thing independently of the others.

The flows are where the parts act. The job refresh is the busiest. A scheduler or a person queues it, the worker claims it, and the executor asks each board for everything it publishes, then filters, deduplicates, screens for machine-generated text, admits within the configured limits, stores, and embeds. The embedding step costs time, so it only pays for the texts the cache does not already hold, and it stops at a daily budget with a resumable partial result. Sections 5.2 and 5.3 follow it, as sequences and as an activity.

The application flow carries the risk, so it is the one with the most steps. Preparing an application writes down exactly what would be sent and stops. A person reads it and decides. The decision is what the system then executes, which is why the approved payload is stored and submitted rather than rebuilt. The flow is a graph rather than a straight line, because a person and a browser can both go wrong, and the approval gate fails closed: with no recorded decision the run routes away from submit. Section 5.6 follows it.

The tailoring pipeline is a third flow. The model writes the text and the validator decides what may stay. A violation is not an error: the run succeeds with the violation report attached, and the console shows both. Section 5.10 follows it.

The data-flow view in section 5.1 shows the same system from the data's point of view. The candidate supplies a résumé; the job boards supply listings; the model provider supplies draft text; only the local test employer receives a prepared packet. Between them sit the processes, and three stores hold everything that must survive a restart: the relational database, the vector store and the directory tree.

## 3.3 Deployment and trust boundaries

The React application runs in the operator's browser and calls the API over HTTP. The API and the separately supervised worker share the relational database and configured data directories. The repository supports SQLite for local use and a PostgreSQL queue claim path. In the queued deployment the worker writes the Chroma job index and search reads it. A worker may also open an isolated Playwright browser context. This is the Python runtime client; development tools used to inspect a screen do not participate in an application run.

Figure {fig:deployment} shows the local arrangement: one host, two processes and a loopback fixture. Figure {fig:deployment-queued} shows the arrangement that the queue claim path supports. The console is served as static files, the API and a supervised worker run as independent processes, and PostgreSQL carries both the records and the queue. Chroma remains a directory on storage shared by the two processes, and the worker alone opens a browser context. Moving the queue into the database changes the claim mechanism and not the design: a claimant skips rows another has locked, and the same lease token still fences settlement. Neither arrangement supplies per-tenant storage encryption, so the data volume needs the protection of the host.

@figure deployment

@figure deployment-queued

Browser sessions use an HttpOnly cookie; state-changing cookie-authenticated requests require the matching CSRF token. Scripts can use the separate bearer-token transport. The server derives the user scope from the authenticated principal. For private resources an ordinary caller gets the same not-found response for a foreign identifier as for a missing one. A file download also requires an allowed, resolved path: knowledge of a document identifier or filename alone grants no access.

Listings, uploaded text and form labels are untrusted input. Model prompts delimit untrusted content, mask identifying information where applicable and validate structured output. Outbound requests and browser navigation have destination checks; an unexpected destination or a CAPTCHA or MFA challenge stops the browser flow. Request-size, concurrency, rate and work limits bound what a caller can trigger. These controls reduce exposure; text filtering does not certify the truth of a posting or every sentence a model writes.

The two processes share one revision of the schema: both run the same chain of Alembic migrations, so a deployment that starts from a file and one that starts from a server do not fork the schema. The worker records a heartbeat so an operator can see whether the process that should be claiming work is alive. A responsive API alone is not evidence that queued work is progressing.

## 3.4 Design rationale

The backend is one deployable unit because the work fits on one machine. Refresh, ranking and tailoring complete without coordination between services, and splitting them would add deployment and failure modes without changing a result. The separation that earns its place is the worker's, since long-running work needs its own lifecycle and must outlive the request that started it. The queue lives in the same database, but the claim path is written for both SQLite and PostgreSQL so that recovery behaves the same way in either.

A set of services was rejected because the work does not need one. The heavy operations are a daily refresh and a search over a corpus of several thousand listings, and both finish in about a minute on one machine. Splitting the system would add a network hop to every call, a second deployment to keep alive, and a distributed failure mode that the project does not have the resources to diagnose. The one place a second process was wanted, the browser that fills an employer's form, is already a separate process because the browser is a separate program.

Business logic stays in code rather than in prompts. A model writes prose and is unreliable at counting, ordering and remembering. The scorer applies fixed weights to numeric components, the registry grants capabilities, and the validator compares structured claims with the stored profile. A model may propose text; its response cannot authorize its own use. This is the decision with the widest consequences. The model writes a tailored résumé and a deterministic validator then checks every skill, employer, project and year claim against the profile and removes what the profile does not support. The same rule decides the rest of the system: the matcher is eight arithmetic scorers, the ATS report is a weighted sum over four components, the form contract answers only questions it can ground in a stored fact, and the refresh drops a listing that lacks an identifier, a title or a company. In each case the model is a source of text and the code is the authority.

A workflow library carries the application path because that path has state, branches, retries and an approval gate. Ranked search does not: it is a deterministic sequence of function calls, and expressing it as a graph would add machinery without adding a decision. The library supplies none of the durable queueing or lease fencing, which the database owns, so recovery does not depend on a graph object remaining in memory. The split follows the rule the plan set: a graph earns its cost when there is state, branching, retries or a gate, and the application flow has all four while the refresh has none.

Work is queued rather than executed inside the request because the two operations that matter most take longer than a request should. A refresh over thousands of listings, and a browser session that fills a form and waits for a confirmation page, can each outlive the HTTP connection that asked for them. Writing the work first means an interrupted browser, a closed tab or a dead worker leaves a record another process can pick up, and the API answers 202 with a run identifier instead of holding a connection open against an uncertain duration.

Matching reads the stored corpus and contacts no board. The search therefore has no source errors and no network failure path, its ranking is deterministic for the same stored inputs, and one refresh serves every account that searches afterwards. The price is freshness, and the listing's source timestamp states how current it is rather than hiding it.

Listings are stored once and shared; matches are stored per account. A shared corpus is what makes a bounded refresh affordable, and per-account views are what keep two people's searches from sharing a résumé or a history. The corpus cap evicts rather than refuses, and one refresh may evict only a bounded number, so a flood from one board cannot empty the corpus in a single run.

The default embedding model runs locally on the CPU. The earlier cloud tier allowed twenty requests a day, which a refresh over thousands of listings exhausts at once, and a local model also keeps corpus text on the host. Its input is capped at 16,000 characters, raised from the earlier 8,000, and its batches to eight texts, which is why admission control counts cache misses rather than listings. A throughput figure for a different machine would describe hardware that has not been measured.

The real-board adapters hold no submit capability because the stop must not depend on a model's obedience or on a configuration's absence. The registry grants capabilities by name: the fake ATS holds prepare, submit and verify, the assist pilot and the Greenhouse and Lever adapters hold prepare only, and every adapter also refuses, in its own code, a call its grant does not cover. An approval authorizes work; it cannot widen a grant. The stop is therefore a property of the permission model, and the tests can hold it in place.

A lease fences each claim because two failure modes are otherwise unavoidable. Without a claim record, two workers could take the same item, or a dead worker could leave an item stuck in progress forever. The lease token is written with the claim, renewed while the work continues, and required again at settlement, so a stale worker cannot overwrite a result after another worker has taken the item. A lease that expires with work outstanding is not retried blindly: the reaper marks the run recoverable, and an administrator resumes it.

The database was chosen for the same reason the architecture was. SQLite is a file, so a student can copy the project directory and the history is with it. PostgreSQL serves the queued deployment, and both run the same Alembic revisions, so the schema does not fork between them.

Authorization was placed in the data layer rather than in the routes, and this is the one decision the live tests forced. A route that queries a user-scoped table directly is a route that has to remember to add a filter, and a mechanical check found five that did not. Moving the filter into the accessor means the route cannot get it wrong, because there is no way to ask for the row without it. The cost is that the scope must be resolved before the query is built, which is why every protected route takes the scope as a dependency and no route reads an account identifier from the request.

A foreign resource answers with 404 and a body identical to a missing one, rather than 403. A 403 tells the caller that the identifier exists and belongs to somebody else, which is an existence oracle over another account's records. The 404 costs a little more work at the call site and removes the oracle entirely.

The console remains outside the runtime process. It has its own package, build and test suite, so a change to a screen does not require a change to the service, and the interface cannot reach into a Python module for data that the API would have refused.

# 4 Data design

## 4.1 Data description and domain objects

The information domain splits into four kinds of record, and each is stored the way its own access pattern demands. The shared job corpus is a set of rows that every account may read, so it carries no owner. The candidate's own records, the profiles, the confirmed answers, the matches, the tailored résumés, the applications, the events, the evidence, the approvals and the stored credentials all belong to one account and carry it. The operational records, the runs, the work items, the run events, the heartbeats and the breakers, belong to the platform, and a run records the account that asked for its work when there is one. The sessions belong to the account that opened them. The vectors are not rows at all; they live in a separate store because they are searched by meaning rather than by key.

Every user-scoped table has the same three columns for the same three reasons. The `owner_id` column is not null, because a record with no owner cannot be read safely. It is indexed, because the only query that matters is the one that filters by it. And it is set by the accessor rather than by the caller, because a caller that sets it is a caller that can get it wrong. The constraint is enforced in the database as well as in the code, so a row inserted outside the accessor cannot exist without an owner.

The logical view names the entities and their relationships without committing to columns or keys. Figure {fig:er-overview} is that view. The feature worth noticing is at its centre: an application case descends from a review packet and never directly from a listing, and a packet in turn descends from a draft and a profile. A listing can be assessed many times, by many accounts, without any of those assessments becoming an application.

@figure er-overview

`CandidateProfile` holds document-derived contact details, skills, experience, education and projects. Dated experience entries retain their original employer and title. The separate `ApplicationProfile` records what the candidate states about preferences and eligibility. An unanswered work-authorization question remains unknown; silence is not a negative answer. A `JobListing` has its own source identity. `JobMatchResult` relates the two inputs through scores, missing evidence and an explanation without modifying either input.

@figure domain-classes

`TailoredResume` is proposed wording for one profile and job. The factuality report records what the validator removed. The ATS report describes how the delivered document reads against this posting, while the render report says whether the editor could preserve the source format. These answer different review questions: a well-formatted résumé can still contain an unsupported claim.

@figure drafting-classes

`ApplicationRequest` contains proposed application inputs. `PreparedApplication` carries resolved fields, profile facts and references to documents for review. The approval record stores the packet. `ApplicationResult` carries the adapter's status and may carry `SubmissionEvidence`; neither a result object nor an approval identifier is the tracked application itself.

@figure application-classes

For example, after a candidate approves a packet for a fake-ATS job, its approval can read `approved`, its new run `QUEUED`, and its tracked application `awaiting_approval`. The last value is possible because tracking has no separate queued stage. The three identifiers let the console retrieve the decision, the work and the subsequent evidence independently. This is an example of a valid interval between writes, not a recorded submission.

@figure object-example

## 4.2 Data dictionary: account and corpus

The following dictionary gives selected physical fields and their meanings. A relationship expressed by an identifier is a logical link unless the schema declares a database constraint. Ownership checks still apply when following a link. The corpus tables contain shared observations; the profile, match and draft tables contain information about an individual account.

| Record | Selected field and type | Meaning |
| --- | --- | --- |
| `users` | `id` string; `hashed_password` string | Account identity; the password is stored only as an Argon2 hash, beside the flags that decide what the account may do |
| `access_tokens` | `user_id` string | Server-side session belongs to this account; the token is the primary key and the secret, and ending the row ends the session at once |
| `candidate_profiles` | `profile_json`, `application_json` JSON | Parsed facts and separately confirmed answers, stored with the uploaded file's path so the file and the record describing it age out together |
| `candidate_eeo` | `profile_id` string; `data` JSON | Isolated voluntary equal-opportunity selections |
| `llm_credentials` | `owner_id` key; `encrypted_key` string | One stored provider credential per account; a read returns a mask, never the key |
| `jobs` | `id` string; `content_version` string | The shared corpus, one row per canonical identifier; holds the source, the company's details, the description, the structured skills, the salary, the seniority and the date the listing was last seen, which is what makes eviction possible |
| `job_boards` | `slug` string; `last_ok_at` datetime | Board identity and last successful contact |
| `form_questions` | `label` string; `times_seen` integer | Board question and observation count, not an answer |
| `visa_sponsors` | `name_normalized`, `country` strings | Employer register entry; not a promise for a role |
| `job_matches` | `profile_id`, `job_id` strings; `scores` JSON | Owner's recorded match for a listing, with the eight component scores, their states and the explanation |
| `tailored_resumes` | `tailored` JSON; `edited_at` datetime | Draft content, its factuality, ATS and render reports, the deliverable's path, and the time of a saved edit |
| `employer_answers` | `owner_id`, `job_id` keys; `answer` JSON | One saved answer for one posting's form field, kept for reuse at the next preparation |
| `local_fill_grants` | `application_id`, `owner_id` keys; `expires_at` datetime | The record that authorizes one fill-only helper pass on a stored packet, and whether it was used |

@figure account-erd

An account anchors a small set of rows, and the set divides into what can be withdrawn and what cannot. Sessions and a personal model credential hang directly from the user: signing out ends a session, and deleting the stored key removes the credential, neither of which touches a document. The candidate profile and its voluntary equal-opportunity record describe the person and survive a withdrawn session, so they end only with the account-deletion path. Every private row names its owner in an `owner_id` column, and an accessor checks that column before a row is read. Audit events name an actor rather than owning data, which is how an anonymised record can outlive the account it describes.

@figure identity-classes

## 4.3 Data dictionary: decisions, evidence and work

The approval identifier addresses a decision. The application identifier addresses a history and its answers. A workflow or correlation identifier connects related actions across components; an individual work item's lease token identifies a particular worker claim. None of these identifiers substitutes for the authenticated account.

| Record | Selected field and type | Meaning |
| --- | --- | --- |
| `approval_requests` | `payload`, `form_questions` JSON | Prepared packet and its question plan; the payload is the exact content the person reviewed, and it is what the worker executes |
| `approval_requests` | `expires_at` datetime; `profile_version` string | Review window and digest of prepared facts |
| `applications` | `approval_id`, `status` strings | Tracked case and current lifecycle stage |
| `application_answers` | `question_key`, `answer_text` strings | Upsert by owner, application and question |
| `application_events` | `actor`, `from_status`, `to_status` strings | Append-only history; the auto-incrementing identifier is the order, the events are read in append order and never reordered by timestamp |
| `application_evidence` | `workflow_id`, `screenshot_path`, `trace_path` strings | Attempt evidence and artifact references: the confirmation text, the screenshot, the ordered trace and the status, linked to the application |
| `audit_events` | `actor_kind`, `actor_id`, `action`, `outcome` strings | Attributable operational or security action; the store is append-only, and a deleted account's rows are anonymized rather than removed |
| `job_runs` | `status` string; item counters integers | Work accepted and checkpointed in SQL |
| `job_work_items` | `lease_token` string; `next_attempt_at` datetime | Current claim and retry eligibility |
| `job_run_events` | `run_id`, `event` strings; `at` datetime | Run history, including recovery |
| `worker_heartbeats` | `last_heartbeat_at` datetime | Last evidence that the process checked in |
| `circuit_breakers` | `name`, `state` strings | Shared dependency state when configured |

@figure workflow-erd

## 4.4 Storage, access and retention

SQL is authoritative for listings, decisions and outstanding work. Chroma holds a rebuildable projection identified by job, content hash and embedding model identity. A missing vector reduces what search can measure; it does not delete the job. Conversely, a leftover vector cannot create a listing. Reconciliation compares the two stores because a SQL commit and a vector write cannot form one database transaction.

@figure storage

The vectors are stored in one Chroma collection, in cosine space. The model identity and the dimension are saved with the collection, because two embedding spaces cannot be compared, and opening the store with a different model raises an error that explains how to rebuild it rather than returning nonsense similarities.

The embedding cache is a separate SQLite file keyed by a hash of the model, the dimension and the text. It is the reason a second refresh over unchanged listings costs nothing. The cache holds corpus vectors only: a candidate's query vector is computed fresh and never written, because a cache hit on an identical profile would tell a second account that somebody else had submitted the same text. The cache is bounded and evicts its oldest entries at the configured limit.

The corpus row and the vector carry the same canonical identifier, so the two stores are never allowed to disagree silently. A missing vector means the listing has not been embedded yet or the store was unreadable, and search says which rather than treating both as the same absence.

New uploads, tailored copies and evidence files live under `data/users/{user_id}/`, in `resumes`, `tailored` and `evidence` respectively. The original remains available when Studio writes a deliverable. Production operators must protect the underlying storage and backups: directory separation is not disk encryption, and screenshots and traces may contain personal information. The scheduled purge in `src/retention.py` and `scripts/purge_expired.py` enforces configured retention windows and anonymizes retained audit records on account purge. The API process does not schedule that task itself.

The files follow the accounts, and the containment check asks whether the resolved path is inside the caller's own directory. The check runs on the resolved path rather than the path as written, so a name that walks out of the directory, through a symlink or a relative segment, is refused after resolution rather than before it.

# 5 Component design

This section takes each significant function in turn and states the algorithm it runs. The pseudocode names the real functions and the real data. Where a function has a decision that matters, the decision is written out; where it does not, the line is left out.

## 5.1 Intake and information flow

The upload path checks type, size and file structure, assigns a server-side name and parses the document into sections. The parser supports DOCX, TXT, Markdown and PDFs with a readable text layer. A scan without text, a password-protected PDF, a broken text encoding and an unreadable file produce distinct refusals. Other missing résumé sections remain empty and validation can return warnings. An operator can correct confirmed application answers without rewriting what the source document said.

if the suffix is .docx: read the paragraphs and mark the list-styled ones

if the suffix is .txt or .md: read the lines and mark the ones that start with a bullet

if the suffix is .pdf: read the text layer, page by page; a scan without text is refused, and no OCR runs

otherwise: refuse, and the refusal names the unsupported format

split the lines into a header and the sections; a heading is a known heading and is not a bullet, so a bullet that looks like a heading stays content

skills, categories <- read the skills section; a row of the form 'Category: a, b, c' splits into its named skills

name, title, email, phone, location, website <- read the header

education, experience, projects <- read their sections; a bullet under a section belongs to the entry above it

preferences <- read the work preferences; labelled lines first, then phrases in the summary, and the earliest phrase wins

return the profile

The parser never invents a value. A section that is missing yields an empty field and a deterministic warning, and the preferences are recorded only when the document actually states them.

Figure {fig:upload-sequence} follows one upload from the console to storage. The order of the steps is the part worth noticing: format and size checks, then the source write, then parsing, then the profile write. A file refused at validation is never written. A file that passes validation but fails to parse is removed before the request returns, so a failed upload leaves neither a profile row nor a half-parsed source for a later request to read.

@figure upload-sequence

Beyond intake the flow is one-directional. Shared listing data and private profile facts meet only inside scoring, and the result is written under the account that asked for it. Figure {fig:data-flow} follows the data rather than the calls: the candidate supplies a document, the boards supply listings, a provider may supply draft text, and only the local test employer receives a prepared packet.

@figure data-flow

## 5.2 Refresh acceptance and worker ownership

`POST /api/jobs/refresh` accepts background work and returns HTTP 202. An active refresh can satisfy a repeated request because the corpus is shared. The run's `owner_id` identifies the requester; scheduled platform runs may have no user owner. Ordinary users can inspect their own runs. The worker's `lease_owner` identifies a process temporarily entitled to do work, not a person entitled to read another user's data. Closing the browser that asked for the refresh does not cancel it: the work items are rows, and the worker reads them from the database, not from the connection.

@figure refresh-sequence

A worker claims eligible items in priority order. PostgreSQL skips rows locked by another claimant; SQLite uses a conditional update and checks whether it changed the row. Each successful claim gets a fresh token. Renewal and settlement use that token, so an old worker cannot overwrite a result after another worker takes the item. If a lease expires with unfinished work, the reaper can mark the run `RECOVERABLE`. An administrator can resume outstanding items without repeating completed embeddings. Retryable failures have a next-attempt time; permanent failures and exhausted budgets remain visible in run state. The run's event history records each claim, completion, retry and recovery request with its actor, so an operator can reconstruct what happened without guessing.

A run's status is a claim about durable work, so the transition set is small and enforced in one place. A run starts `QUEUED` and becomes `RUNNING` when a worker claims it. From `RUNNING` it can reach `COMPLETED`, `PARTIAL`, `FAILED`, `PAUSED`, `RETRY_WAIT` or `RECOVERABLE`, and only `COMPLETED` and `CANCELLED` are final. Figure {fig:run-state} draws that set. `RECOVERABLE` is derived rather than requested: the lease reaper writes it when a process stopped heartbeating with work outstanding. A run that stalls in `PAUSED`, `RETRY_WAIT`, `RECOVERABLE`, `FAILED` or `PARTIAL` is not restarted by the next process that polls; an administrator's resume returns it to the queue and the event history records who asked. The rule keeps a transient fault from becoming an unattended loop.

@figure run-state

## 5.3 Listing admission and indexing

Refresh reads the configured Greenhouse, Lever, Ashby and Remotive sources through guarded clients. It records errors per source, drops incomplete listings and screens the batch before spending embedding resources. Within one source, deduplication prefers its job identifier, then its application URL, then title and company. A separate cross-source pass compares normalized company, title and location and keeps the first source's canonical identity. Matching by title alone would merge distinct vacancies at different locations.

The executor's contract is that it never raises. A source that fails, a store that fails or a quota that runs out lowers the report and lets the run finish.

for each registered source:

queries <- empty query for that source

listings, source_errors <- search_all_detailed(queries); a failing source puts its message in source_errors and the run continues

kept <- the listings that have an id, a title and a company

unique <- deduplicate(kept), then merge_cross_source

unique, spam_verdict <- screen_listings(unique), which drops machine-generated text

if the corpus is at its cap:

evict the listings not seen for the longest, and delete their vectors; a listing from a failing source is never removed to make room

admission <- admit_listings(unique, corpus_size), under the per-source, per-refresh and corpus caps

unique <- admission.admitted

persisted <- save_jobs(unique), upserting by the canonical id; a failure here is logged and the run continues

misses <- the listings whose text is not in the embedding cache

if the daily work budget is smaller than the misses:

misses <- the first misses that fit; quota_exhausted <- true

misses <- share the remaining budget between the sources, round-robin

to_embed <- misses, then the cached listings that still fit

embedded <- store.upsert_jobs(to_embed), where only the misses cost an embedding

return the report: counts, source errors, planned and used embeddings, quota_exhausted and degraded_embedding

Two properties of this design are worth stating. The budget is denominated in cache misses, not in listings, so a run over unchanged listings costs nothing and a flood at the front of a board cannot starve the listing behind it. And the corpus cap evicts rather than refuses, so a full corpus is a window over the most recent listings instead of a door that closes.

@figure refresh-activity

For admitted changes, the worker commits the listing and its planned embedding work together. A work item's identity includes the run, job, work type, content hash, model and dimension. The embedding handler upserts the vector and checks the stored version before marking the item complete. If it dies after the vector write, repeating that write under the same job identity is safe. If Chroma is unavailable, SQL can retain the job and record the outstanding work. That recovery rule is suitable for indexing; it would be unsafe for sending an application.

## 5.4 The store-only search

`search_stored_jobs` in `src/graph/job_executor.py` ranks SQL listings for a stored profile. It makes no job-board request. Query tokens, location and workplace narrow the candidate set before ranking. The lexical index uses the full corpus for its term statistics, so narrowing a location does not redefine a keyword's rarity. The engine computes numeric scores for eligible listings, orders by descending score then job ID, and builds full explanations only for the returned slice. The API stores returned matches under the caller's profile.

rows <- read the jobs table, bounded by the corpus cap

if a query is given:

keep a job when any token of the query, of at least two characters, appears in its title or description

if a location is given:

keep a job when the location is a substring of its location

build the BM25 index over the full corpus, so the narrowed set does not redefine a keyword's rarity

similarities <- what the vector store reports for the candidate's text

degraded <- true when some job has no usable vector, or the store could not be read

for each eligible job:

score <- score_listing(job, profile, semantic_score, lexical)

rank the scores by overall, descending, then by job id

build full explanations only for the returned slice

return the top matches, the counts, the coverage and the degraded flag

The search never contacts a job source, which is why it has no source errors and no network failure path. A listing with no usable vector keeps the semantic weight in the denominator, contributes zero for it, and the report distinguishes a pending embedding from an unavailable one; the reader sees reduced coverage rather than a quietly moved weight. With no usable vector, the default search keeps the job. A caller may explicitly request indexed jobs only.

## 5.5 The match engine

The engine computes the eight components and blends them over a fixed denominator. It never touches the vector store: the semantic score arrives as an argument, which keeps the arithmetic testable without a model and keeps the engine from depending on a store. The explanation is built from the same numbers as the score, so a reader can check the arithmetic by reading the sentence.

| Component | Default weight | What the score measures |
| --- | --- | --- |
| `semantic` | 0.13 | Similarity of profile text to the indexed posting |
| `lexical` | 0.08 | BM25 relevance of candidate terms to posting text |
| `skill` | 0.22 | Required and preferred skills supported by the profile |
| `experience` | 0.17 | Stated years required against dated experience |
| `seniority` | 0.08 | Distance between candidate and job seniority levels |
| `location` | 0.09 | Posting location and work mode against preferences |
| `preference` | 0.08 | Employment type and salary against stated preferences |
| `role` | 0.15 | Occupational family against candidate target roles |

weights <- validate_weights(weights or the configured weights); this rejects an unknown component, a missing one, a non-positive one, or a total outside 1.0 +/- 0.01

skill <- (required hits + 0.5 * preferred hits) / (required + 0.5 * preferred) * 100; a listing that states no skills is unknown, not perfect, and a list shorter than two requirements damps the score as weak evidence

experience <- 100 - 25 for each year the candidate is short of; the candidate's total counts overlapping dated intervals once

seniority <- 100 - 30 for each level between the job and the candidate; both ranks come from one ladder, tried from the most senior keyword down

location <- 100 for a remote job or a preferred place;

25 when the job is on-site and the candidate wants otherwise;

55 for a hybrid job;

40 when the listing states a place the candidate did not name;

unknown when neither side states a location or a work mode

preference <- the mean of the employment-type and salary subscores; employment type is 100 for a match and 40 for a mismatch, and salary is 100 when the offer clears the floor and 25 when it does not

lexical <- BM25 relevance of the candidate's terms to the posting text

role <- the posting's classified occupational family against the candidate's targets; a classified hard mismatch caps the blended score at 25 and says so

semantic <- cosine similarity times 100, clamped to 0..100, when a vector exists

blend <- the weighted sum of the measured components, divided by the counted weight; an unknown component contributes zero and keeps its weight, and only NOT_APPLICABLE leaves the denominator

overall <- the blend, then the role cap when it applies

return the eight scores, the states, the coverage, the matched and missing requirements, and the explanation

The names and defaults come from `src/matching/weights.py`. `src/matching/scores.py` divides the weighted score sum by the sum of applicable weights. An unknown component earns zero but keeps its weight; only `NOT_APPLICABLE` leaves the denominator. For example, with all eight applicable, a job with a missing vector can earn at most 87 out of 100 even if the other seven score 100. `evidence_coverage` is the measured share of the counted weight. A low measurement and an unknown value can therefore be distinguished in the explanation.

The skill scorer gives a preferred skill half the weight of a required one and dampens very short lists. The experience scorer counts overlapping dated intervals once. A classified role mismatch that triggers the cap limits the blended score to 25; the result reports that cap. A sponsorship-register finding is separate evidence; voluntary equal-opportunity data never enters the score.

## 5.6 Preparation, approval and execution

Preparation checks the target and adapter, confines any résumé path to the caller's storage, and builds a packet from supplied inputs and grounded facts. It stores the question plan with the approval so Review can display the questions this packet actually used, even if the employer changes the form. The row carries a fact digest and an expiry. Re-preparing for the same owner and job URL can carry forward eligible saved answers. No browser submission follows from preparing or saving an answer.

@figure approval-sequence

The decision endpoint resolves the approver from the session, loads the owned pending record and checks expiry, policy and posting liveness where supported. A known closed posting blocks approval; an unreachable board is not proof of closure. The default review window is 168 hours from creation, and an expired approval returns 409 with the packet left unexecuted. The approve path commits the decision and queued work together. If the queue is full, it rolls back and the approval stays pending. A 202 response gives the caller a run ID. Rejecting the packet records a decision without enqueuing submission.

The workflow's nodes and the two branch points between them are where a person and a browser get a say.

if the state already holds a prepared application: return it unchanged

prepared <- adapter.prepare(request)

store the prepared application and return the state

on an exception: record the error in the state and re-raise

approved <- (state.approval_status is True)

return 'submit' if approved else 'reject'; the test is identity with True, so None and False both reject

if the state holds an error: return 'end'

if there is no submission result: return 'end'

if the submission did not succeed: return 'end'; a submission that failed has a reason of its own, and verifying it would flatten the reason into a generic failure

return 'verify'

if there is no prepared application: raise

if the adapter does not hold the submit capability:

return a result with status 'permission_denied' and stop; a refusal is a result, not an exception

result <- adapter.submit(prepared)

write the evidence row: confirmation text, screenshot, trace, status; a failure to write the evidence is logged, and the submission still counts

if the result succeeded: move the application to SUBMITTED

append an event to the application's history

return the state

The verify node mirrors the submit node. It checks the permission, calls the adapter, and then downgrades the result to verification failed when a required artifact is missing from disk, so success is never claimed without the files that back it.

The worker restores the reviewed payload and checks the submission policy again at execution. `PREPARE_ONLY` forbids execution and `AUTO_SUBMIT` is unavailable. Under `REQUIRE_APPROVAL`, only `fake-ats-playwright` has both `SUBMIT` and `VERIFY`. The fake adapter reads accessible labels and roles in a fresh context, uses grounded answers, and checks the confirmation page. It collects a screenshot and traces; a missing required artifact or an unrecognized confirmation prevents a verified result. Verification here establishes a fixture outcome, not an employer response.

Before calling the adapter the worker commits an attempt marker. If a stored outcome already exists, recovery uses that outcome. If the marker exists but the outcome does not, recovery records `submission.uncertain` for human investigation rather than sending again. The database cannot determine whether a remote system acted during that interval. This is a limit on replay, not a guarantee of exactly-once delivery across systems.

## 5.7 The form contract

The browser layer finds the questions on the page and asks a pure contract what to do with each. The contract is free of the browser, which is what makes it testable: it takes the form's questions and the candidate's grounded facts, and returns a plan that names a verdict for every question.

category <- classify the question's label with the fixed taxonomy

verdict <- answerable when a grounded fact answers the category, and the agent may fill it

verdict <- never_autofill for a consent, demographic or attestation question; the agent never answers it, and it is surfaced to the human at approval time

verdict <- needs_human when the form marks it required and no fact answers it, which is the verdict that stops the flow

verdict <- optional_unanswered when no fact answers it and the form does not require it

for each question on the page:

apply the saved answers for this application; a saved answer whose key or normalized label matches flips needs_human to answerable, with the answer attributed to the person, and a never_autofill verdict can never be flipped because the storage layer refuses such an answer before one could exist

return the plan, with the blocking questions marked

A required question the system cannot ground is a question for a human, not a guess. The plan separates the questions it may answer from the questions it must ask about, and the browser stops on the blocking group: a complete supported form stays open for the person rather than being submitted with holes. An answer is used only for a control the browser can operate; an unfamiliar control stops the walk rather than being guessed, because a wrong answer cannot be recovered and an unknown question can be asked.

The grounded facts come from the profile and the confirmed answers, and the taxonomy maps each category to the fact keys that can answer it, so a category added there is answerable without a second table. Consent, demographic and attestation questions are classified before any fact is consulted, and the agent's refusal is recorded as a verdict the console shows, not as silence.

## 5.8 Per-application questions and answers

Each prepared packet stores the board's question plan with the approval, so the questions the packet actually used survive even if the employer changes the form. The plan keeps the board's order, and a read shows each question with its verdict, its category and the grounded fact that answers it, if one does.

The answers are the candidate's own. An answer is stored per owner, application and question key, and reading the questions page folds the saved answers into the plan without fetching a different employer form. An eligible human answer can clear a question that blocked the packet; equal-opportunity selections and legal attestations have no answer control here, and the API refuses an attempted save with 422.

Re-preparing for the same owner and job URL can carry forward eligible saved answers, so a corrected packet does not ask the same questions twice. An answer that clears a question in Review does not guarantee that a browser can operate the corresponding widget; the browser's own walk re-derives the plan from the page it actually finds.

## 5.9 The real-board preparation boundary

The normal Greenhouse and Lever application adapters can prepare but cannot submit. The separately invoked `assist-playwright` pilot also has only `PREPARE`. Its intended handover leaves a filled browser for the human and returns `awaiting_human_submit` with success false. Unknown controls can stop the walk earlier; a challenge stops it rather than being solved. A Greenhouse contract check can identify missing required values before proceeding. It cannot certify what the live board will accept or recognize its confirmation page.

The 15 November 2026 pilot illustrates the distinction. The unmodified pilot stopped at `needs_human` before typing. On the Cloudflare form a separate instrumented pass through the same fill routine filled four fields with the shipped label lookup and nine after stripping a trailing required-field asterisk. Across seven live forms the planner left 11 to 25 controls unresolved. No one pressed Submit; employer acceptance and post-submit verification were not measured. The separate records are identified in section 8.4.

The assist adapter's grant is the whole of its authority. It holds `PREPARE` and nothing else, so its fill routine cannot end in a submission even on a complete form, and no route exists that would let a real-board packet be sent. The stop is the permission model's, not a prompt instruction.

## 5.10 Tailoring, factuality and drafting

The tailoring pipeline takes a stored job and an owned profile. Research draws facts from listing text and filters proposed facts for grounding; it does not fetch arbitrary company URLs. A model proposes wording. The validator compares structured claims with the profile, for example removing an unknown employer or a skill absent from the source and reporting the removal. A reported violation can accompany HTTP 200: the returned document contains the cleaned result. A provider failure is a separate error and supplies no replacement draft. These checks catch specified discrepancies; they are not independent verification of every sentence.

draft <- generate_structured(build_prompt(profile, job, insights), TailoredResume); the requirements and the insights go inside a nonce-fenced block capped at 20,000 characters, and the profile copy that leaves the process carries placeholder tokens, not the contact details themselves

removed_skills <- the draft skills the profile does not support

for each drafted experience entry:

if the company is not in the profile: drop the entry and record it

else if the title is not one of the candidate's own titles: blank the title and record it

for each bullet:

drop a sentence that claims more years than the profile shows

drop a sentence that carries an injected instruction

drop a sentence that carries an unresolvable placeholder

for each drafted project:

if the name is not in the profile: drop the project and record it

for each bullet: the same three removals

the summary and the cover letter: the same three removals

return the cleaned content and the factuality report

The report lists every removal and its reason, and the run still succeeds: a factuality violation is content, not an error. The removals are separate on purpose. A claim about years is a fact that contradicts the profile, so the sentence goes. An injected instruction is an attack, so the sentence goes and the attempt is recorded. An unresolvable placeholder means the validator cannot restore the identity, so the sentence carrying it goes too. The title check is an exact comparison while the company check accepts containment, because "Senior Staff Engineer" contains "Engineer" and a company name is often a suffix of another.

@figure tailoring-activity

One tailoring request may contact more than one provider without becoming more than one operation. The client walks a configured fallback chain at the provider seam, so a refused, throttled or unavailable provider is passed over inside the same logical call; the route observes one outcome, either a draft or an explicit provider failure. The client's own timeout, retry budget and circuit breaker apply once to that call rather than once per provider. Figure {fig:tailoring-sequence} shows the chain inside the call, between grounding and validation. A personal provider key is not part of the chain, so a failing personal key never spends the platform's quota, and a caller reading the response cannot tell which provider answered.

@figure tailoring-sequence

The renderer prefers to edit a copy of the source document in its supported format. If it cannot, it generates a new document and records `regenerated` and the reason. ATS analysis inspects the actual deliverable for keyword coverage, sections, title alignment and format risks. This is a local estimate, not an external ATS score. Saving section edits repeats factuality checks, rendering and ATS analysis against the stored profile and job, without asking a model to approve the edit. It updates the draft's reports and `edited_at`, not the source upload.

## 5.11 The ATS analysis

No model is involved in the estimate itself. The report is a pure function of the tailored content, the profile, the listing and the rendered file, so two runs over the same inputs give the same number.

coverage <- the required and preferred keywords the tailored text contains; a keyword counts when every content token of it is present

sections <- contact, summary, skills, experience and education; each present or not

alignment <- the overlap between the job title and the candidate's titles, with abbreviations expanded on both sides before the comparison

risks <- inspect the rendered document for tables, text boxes, images, missing standard headings, empty sections, too many fonts, and no contact line

keyword_score <- 0.45 * coverage, where a required keyword weighs 1.0 and a preferred one weighs 0.5; when the listing states no structured skills, coverage is 50, which means unknown, not perfect

section_score <- 0.20 * the proportion of the five sections that are present

alignment_score <- 0.20 * the title overlap, and 50 when the candidate has no usable title to compare

format_score <- 0.15 * (100 - 20 for each distinct risk found), and 100 when there is no rendered file to inspect, because nothing observed is not the same as no risk

score <- the weighted sum, clamped to 0..100

return the score, the four components, the risks and the notes

A keyword that the profile does not support is reported as a note, marked as supported or unsupported by the profile, and is never inserted into the résumé. The analyzer reports what is missing; it does not edit the draft.

## 5.12 Rendering the tailored document

Text and Markdown uploads keep their original format when a safe edit is possible; the editor works on a copy and leaves unsafe paragraphs and tables alone. A PDF source cannot be edited in place, so it produces a generated document identified as regenerated.

prefer to edit a copy of the source document in its supported format

if the source cannot be edited safely: generate a new document, and record 'regenerated' with the reason

write the name as a title and the job title as a subtitle, when they exist

write the contact line, when any part of it exists

for each section that has content:

write the standard heading, then the content; the headings are the ones the parser recognises, so the file reads back into the same facts

a skill line lists only the skills that are in both the tailored content and the profile; a skill the candidate does not have is never added

an experience line names the title and the company, with the dates taken from the profile entry for that company, verbatim

save to out_path and return it

The renderer omits a field it does not have rather than completing it, and the file name is built from the profile and job identifiers, sanitized, with a short hash of the job identifier appended when the sanitizing changed the identifier, so that two identifiers cannot collide. Reparsing a rendered document recovers the identity, the employers and the validated bullets on the supported layout, which is the check the tests use.

## 5.13 Scoped data access

def _owned(statement, model, scope):

if scope.is_superuser:

return statement

return statement.where(model.owner_id == scope.user_id)

This is the whole authorization mechanism. An accessor builds its statement, passes it through the filter, and executes the result. The row is never materialized without the owner predicate, so a route cannot ask for another account's row even by accident. A row that belongs to somebody else comes back as nothing, and the route turns that into a 404 with a body identical to the one a missing row produces.

The scope comes from the authenticated principal. No route reads an account identifier from a body, a header, a query parameter or a path, so there is no value for a caller to change. A superuser scope exists for the platform's own audit view and for claiming legacy rows once; no ordinary caller obtains it, and an administrator's operational access to the corpus and the worker is enforced by the admin routes, not by widening a scope over private records. A mechanical source check rejects a direct query of a governed table from a route, so the filter cannot be bypassed by writing the query somewhere the accessor does not see.

## 5.14 Sessions

The session is a row, not a signed token, which is what makes immediate revocation possible. Ending the row ends the access on the next protected request.

token_from_request(request):

the session cookie first, then the Authorization: Bearer header

list_sessions(db, user_id):

the account's sessions, newest first; the route returns only the first eight characters of each token

revoke_session(db, user_id, token):

delete where the token and the account match; the account is part of the filter, so a caller can only end its own sessions

return whether a row went; the route turns false into 404

revoke_other_sessions(db, user_id, keep_token):

delete every session except the one the request is using, which is what a password change does

Listing a session returns a prefix of the token, never the whole secret. Revoking one session requires the exact owned token; the bulk actions do not. The cookie and bearer transports reach the same routes, so a script and the console share one revocation path.

## 5.15 Retention and the deletion cascade

Retention runs per kind of record, on its own window, and the deletion cascade runs when an account is purged after its grace period.

for each kind of record, from the child to the parent:

find the rows older than the window for that kind

delete the files they point at

delete the rows; the order matters: the evidence goes before the applications, the events before the applications, the applications before the profiles

if anything was removed: write an audit row naming the counts

delete the evidence, the events, the approvals, the private answer rows, the stored model credentials, the applications, the tailored documents, the profiles, the matches and the sessions, removing each file; the private answer rows are the per-application answers, the employer answers and the fill grants

anonymize the audit rows: the owner, the actor and the resource lose the identity, and the action, the outcome and the time stay

delete the account row

remove the account's directory

write an audit row naming the counts

The purge is idempotent: every step deletes the rows that are still there and anonymizes the rows that are not anonymized yet, so running it twice changes nothing the second time. The audit rows are the deliberate exception, because a trail that can be rewritten is not a trail. Deactivation comes first and is reversible: the account cannot sign in, its sessions are ended at once, and the irreversible purge waits for the grace period to end.

## 5.16 The domain allowlist

allow_local <- the environment is development, and only the fake-ATS adapter asks for it

if the url is empty: raise

if the scheme is not http or https: raise

if there is no hostname: raise

if the host is a local address:

if allow_local: return

else: raise

if the host is an internal, carrier-grade or metadata address: raise

if the host is not on the allowlist: raise

The match is exact or a sub-domain, so a host such as evil-greenhouse.io.attacker.com does not match greenhouse.io. An empty configuration means nothing is allowed. The only escape is the local host, and both the environment and the caller decide whether it is granted, so a production deployment can never navigate to a loopback address for a real board. The check is literal and does not resolve the name; resolving it is the job-source HTTP client's job, and the navigation guard shares the address predicate without resolving hostnames either. An IP literal never matches a domain entry.

## 5.17 The model client

acquire a slot in the sliding-window limiter # it sleeps, it never refuses

check the circuit breaker for this connection; an open one refuses at once

call the provider with the request's timeout and temperature

on a rate-limit or availability error:

if the attempts are spent: raise

wait 1.0-1.5 seconds, then 2.0-2.5 seconds, and try again; a daily quota is never retried, because a daily budget does not reset in seconds

on success: record the token counts and the duration

on failure: record the error type and the duration; the record holds counts only, never the prompt, the answer or the key

The temperature reaches the provider on every call, and both the client's retry layer and the SDK's own retry layer are switched off. The live run that found this was worth recording: an SDK honoured a Retry-After header of 50,951 seconds and slept for fourteen hours inside a sixty-second timeout. The client's own schedule now caps the delay, so a provider's Retry-After can delay a retry but cannot park a worker for hours. The structured-output path validates the answer against the schema and, if it fails, repairs the JSON locally once, without spending another call; a second failure raises, and the caller sees a provider failure rather than a half-parsed draft.

The circuit breaker counts one connection's failures against that connection only. A platform key's scope is the provider's name; a personal key's scope carries the account, so one user's failing key can never open the breaker for the platform key or for another user. A permanent failure, a bad key or an invalid request, never opens a breaker, because that is a configuration error and not an outage.

## 5.18 Personal model credentials

A personal credential is stored as ciphertext under the account that owns it, and a read returns a mask, never the key. Testing the connection is a separate provider call, bounded like the heavy routes because it spends the caller's provider quota. A failing personal key does not quietly shift the call to the platform's account: the personal key is not part of the fallback chain, and a caller reading the response cannot tell which provider answered. The stored credential goes with the account when the account is purged, because there is no owner left to consent to keeping it. The console sends the key to the server and does not keep it; the key is never logged and never appears in an exception.

## 5.19 The abuse limits

Five limits bound what one caller can cost the system, and each answers with a status that says what to do next.

| Limit | Default | Refusal |
| --- | --- | --- |
| Request body | 8 MiB | 413, whether or not the body declares its length |
| Requests per minute per address | 60 | 429, with a Retry-After header |
| Requests in flight | 64 | 503, after waiting five seconds for a slot |
| Heavy routes at once | 2 | 503, refused at once with no wait |
| Custom form fields per request | 50, and 2,000 characters each | 400 |

The heavy routes are the refresh, the search, the tailoring, the credential test and the approval, because those are the ones that cost a browser, a model or a board. The rate limiter keys on the transport peer address and ignores any forwarded header, because a limit keyed on data the caller supplies is not a limit. The bucket table is bounded and evicts its least recently used entry. The admission limits on the refresh side, the per-source, per-refresh and corpus caps, are the same idea applied to what the system spends rather than what a caller sends.

## 5.20 The operator console

The console is a React application with a typed API client. The types are generated from the running API's OpenAPI description, so a route that changes shape breaks the console's build rather than its screen. There is one function per route in the client, and each carries a client-side timeout chosen from what the backend actually does: eight seconds for the identity and health reads, two minutes for a search, an upload or a preparation, five minutes for a tailoring run and an approval, and thirty seconds for a refresh.

Three kinds of person use it, for different reasons. The candidate drives the whole product path, from upload to the recorded outcome. The scheduler runs the refresh, and the maintainer runs it by hand and watches the run it produced. The same screens serve all three; the difference is which question each arrives with.

The shell is the only place the navigation exists, so on a narrow screen the bar becomes a drawer and the two are never both in the document.

The console holds no credential. It sends the session cookie the browser already has, and it echoes the CSRF cookie in a header on every unsafe request. It never updates a screen before the server has answered, so an approval that failed is never shown as approved, and a 202 shows queued work with its run identifier rather than a receipt. It renders backend text as plain text, and the lint rules forbid the routes that would not. It reads at most 8 MiB of any response, and it classifies HTTP, network, cancellation and timeout errors, honouring the Retry-After delay on a rate limit.

# 6 Human interface design

## 6.1 Overview of the user interface

The console is the whole human interface. Every screen in it exists to answer a question a person asks: what did the agent read, what did it find, what does it want from me, and what happened to my applications.

- Sign in. The console asks the server who the caller is, and shows this screen when the answer is no.
- Overview. The dashboard: what the account has recorded, what still needs a person, and where the work stands by stage.
- Resume. The uploaded résumé, the document library, and the parsed profile section by section, including the parts the agent could not read.
- Profile and Account. The confirmed preferences, eligibility and answers; identity, credentials and privacy in one place.
- Discover. The filters, the ranked results with the component scores, and the explanation behind each score.
- Job detail. One listing in full, with what the agent made of it and a way to open Studio for it.
- Studio. The job, the document to tailor, and the result: the tailored content, the factuality report and the ATS report.
- Review. The packets waiting for a decision, the exact payload that would be sent, and the approve and reject actions.
- Tracker. Every application, its status, and the ordered history of what happened to it, with the packet's questions.
- Activity and Operations. The attributed audit trail, and the runs with their item counts, errors and worker state.
- Administration. Platform run and worker inspection, and authorized recovery.

Two rules run through every screen. The console never shows a success the server did not return, and it never shows a status without saying what a person must do next: an application awaiting approval says so, a queued run says it is queued, and an interview says who to prepare for.

The public landing page and sign-in sit outside `/app`. The authenticated shell keeps the current task in view across its desktop navigation and smaller-screen drawer. Navigation follows the candidate's work: inspect source data, discover a role, prepare documents, review a packet and follow its history. Activity and Operations are separate from those decisions; administrative controls also require server authorization.

@figure nav

The dashboard shows a featured match and shortlist when stored match history supplies them, server totals for application stages, recent activity and specific items needing attention. A count for a stage comes from a filtered server total, not the length of the displayed page. An unreadable source is shown as unavailable or retryable rather than as zero work outstanding. A new candidate can start with a résumé instead of being shown sample matches.

Figure {fig:home} records the Overview screen during the console audit. It separates what the account has recorded from what still needs a person, and a zero beside verified submissions is a count for that account, not a failure of the screen. The capture was taken on an audit account against the stored corpus, so its figures describe that account at that time rather than a general population.

@plate home

The plates in this chapter are captured from a running instance: the backend on its own port, the console's development server, and a stored corpus. Each plate carries a provenance note stating when it was taken and against what, and the caption names the claim the capture supports. Where an earlier edition printed twelve screenshots in one block, this edition prints four, each attached to the section that discusses it.

## 6.2 Profile, documents and Account

Profile separates Documents, Application answers and Work preferences. The library pages through originals and tailored copies; the operator can inspect parsed source facts independently of later choices. A candidate can confirm target roles and eligibility by country. Sponsorship is an explicit answer, not an inference from a name or location. Voluntary equal employment opportunity (EEO) selections have a separate opt-in and deletion path.

Account, reachable from the account menu, separates identity, model credentials and privacy. Saving a personal model key yields a masked state; testing the connection is a separate provider call. A failing personal key does not quietly shift the call to the platform's account. The baseline Account screen has no Sessions tab, although the identity API has session-management routes.

## 6.3 Discover and job detail

Discover selects the highest-ranked result by default when there is no existing selection. A location list comes from the corpus, and workplace filters apply before the server's top-result limit. On a wide screen, results and details occupy separate panes. The selected listing exposes the score breakdown, matched and missing evidence and any sponsorship finding before the operator moves to Studio. Missing listing fields remain unknown. The source timestamp describes corpus freshness; opening a result does not contact the employer to establish that the vacancy is still open.

Figure {fig:discover} records a run in which semantic scoring was unavailable for part of the corpus. The notice above the list states that the scores are weaker than a full run, so a reader is not asked to infer it from the numbers. The notice belongs to that run; it is not a claim about the ranker's normal output.

@plate discover

## 6.4 Studio and Review

Studio keeps the original, proposed wording, cover-letter view and validation evidence alongside the chosen job. The diff lets the candidate inspect or edit a section and decide whether to save it. The keyword panel separates terms evidenced by the source from gaps. A render report indicating a regenerated document is a reason to inspect layout before downloading; it is not a claim that the source formatting survived.

Figure {fig:tailor} shows the entry view of that workspace: the profile, the jobs already matched to it, and the statement that the agent uses only what the résumé already says. Each row carries the timestamp of the stored match for that account, so the list records earlier work rather than a live query.

@plate tailor

Review shows the packet, its document choice and the employer's questions in board order. It distinguishes confirmed facts, answers supplied by the person, questions needing an answer and fields reserved for the employer's site. A blocking question disables the authorization control. The person can save an eligible answer, inspect its updated verdict, and prepare again when the packet needs to include changed facts. Approval and rejection are explicit actions. After acceptance the console displays queued work and its run ID, not a submission receipt.

Figure {fig:review} is a crop of the two explanatory cards that sit above the packet. The first states that preparing checks the target domain and builds a payload without contacting the employer; the second states that the agent cannot answer an unsupported question, bypass a challenge or submit without a human decision. The value of the crop as evidence is that the limit is stated before a person reaches the decision, and it shows interface copy rather than a submitted application.

@plate review

## 6.5 Tracker and application questions

Tracker offers board, list and timeline views of recorded applications. Its four board columns group lifecycle values; they are not additional statuses. Awaiting review groups `prepared` and `awaiting_approval`. In progress holds `submitted`, pending verification. Needs you holds `verified`: there is evidence of submission and the next information must come from the person. Outcome recorded contains `interview`, `offer`, `rejected` and `withdrawn`. The transition rules require a human actor for those outcomes. A recorded rejection can be a person's decision against proceeding; its event history explains who acted.

Application detail links to evidence and to that application's questions. The questions page reads the plan saved with the packet and folds in saved answers, without fetching a different employer form. An eligible human answer can change `needs_human` to `answerable` with `answer_from` set to `you`. EEO and attestations have no answer control here; the API refuses an attempted save with 422. An answer that clears a question in Review does not guarantee that a browser can operate the corresponding widget.

## 6.6 Activity, Operations and Administration

Activity presents the account's attributed audit trail. Operations shows accepted runs, item counts, errors and the last reported worker state. Both use polling. If work is queued with no active worker, the useful action is to start or restore the worker, not to approve or request the job repeatedly. Administration provides platform run and worker inspection and authorized recovery. Liveness asks whether the API process is present; readiness checks the database and reports worker health. A responsive API alone is not evidence that queued work is progressing.

## 6.7 Screen objects and actions

The table below names the objects a person interacts with, the action each one performs, and what the console shows afterwards.

| Object | Action | Result |
| --- | --- | --- |
| Email and password fields | Submit the sign-in form | The session cookie is set and the shell replaces the sign-in screen |
| Choose a file | Pick a .docx, .pdf, .txt or .md file under 5 MB | The file is uploaded, parsed and stored; the parsed profile replaces the empty state |
| Your documents list | Choose a document, or open its file | The chosen document becomes the current profile, and every other screen works against it |
| Work preferences and eligibility | Confirm or clear a statement | The confirmed answers are stored separately from the parsed document, and silence stays unknown |
| Filters dialog | Apply the filters | The request, the removable chips and the addressable URL change together; cancelling discards the draft |
| Query, location and top N | Submit the search | The ranked matches replace the empty state, with the count and the degraded notice when it applies |
| Why this score | Expand the disclosure | The agent's reasoning appears, with the matched and missing evidence and the coverage |
| Open the job | Follow the link to a listing | The job detail screen opens with the listing and the component scores |
| Tailor for this job | Start a tailoring run | The run is reported as it happens; the tailored content and the factuality report replace the form |
| Edit a section | Save the edited section | The edit is revalidated against the profile, the reports are refreshed, and the source upload is untouched |
| Prepare the packet | Fill the prepare form and submit | The payload and its question plan are written down and the packet appears in Review |
| Approve or reject | Record the decision | The decision is stored with the identity and the time; a 202 shows the queued run and its ID, not a receipt |
| Save an answer | Record a permitted answer on the questions page | The saved answer folds into the plan and can clear a blocking question; an EEO or attestation save is refused with 422 |
| Status filter and pagination | Filter the tracked applications | The list narrows, and the total stays scoped to the account |
| A status change with a name | Record an outcome | An event is appended to the application's history, and the history shows the actor |
| Run the refresh | Start the refresh and watch the run | The report names what was found, dropped, screened, admitted, stored and embedded |

# 7 Requirements matrix

The identifiers below refer to the same requirements as the SRS, which carries the status of each. A design or test reference identifies where to inspect a control; it does not turn an unexecuted live scenario into a verified result. In particular, evidence about the local ATS must be interpreted within that test boundary.

The matrix traces every functional requirement in the register to the component that satisfies it and the evidence that holds it in place. Each row carries the requirement's own identifier, so the trace can be read beside the specification without a translation table. Adjacent rows that cite the same design responsibility and the same evidence share a row, which keeps repeated paths off the page. An evidence key names one source file, one test specification or one dated evaluation record, and the index below the matrix resolves each key to its path.

@trace

A reference to a test or an evidence path is a place to look, never an assertion that it was run for this edition. Section 8.4 states which dated records exist and when they were produced, so a reader can separate a design claim from a measurement.

The non-functional requirements are traced in the same way. The performance and reliability targets are measured by the evaluation harness in `src/evaluation/`, whose offline mode runs on fixed data with canned model responses and records the dataset identity in every report. The security targets are measured by `src/evaluation/security.py`, whose tenant-isolation metric walks an enumerated endpoint inventory with two accounts and requires zero cross-user disclosures; routes outside that inventory carry their own owner tests. The maintainability targets are held by the continuous integration job, which runs the lint, the test suite, the migration check and the dependency audit on every push, and by the golden-dataset threshold gate, which fails the build when a measured metric crosses an enabled bound. A metric that was not measured is not counted as a pass.

# 8 Appendices

This section collects the reference material a reader of this document is most likely to want beside it: the console's routes, the service's routes, the places where the rest of the design, the operations and the dated evidence are recorded, and the specialist diagrams that would interrupt the narrative.

## 8.1 Console route index

These are the named screen paths in `frontend/src/routes.tsx` at the baseline. A colon introduces a path parameter. An unmatched path redirects to `/`.

| Purpose | Console paths | Screen module |
| --- | --- | --- |
| Public entry | `/`, `/sign-in` | `landing-page.tsx`, `sign-in-screen.tsx` |
| Dashboard and intake | `/app`, `/app/resume` | `overview-screen.tsx`, `resume-screen.tsx` |
| Profile and Account | `/app/profile`, `/app/account` | `profile-screen.tsx`, `account-screen.tsx` |
| Discover and detail | `/app/matches`, `/app/matches/:jobId` | `matches-screen.tsx`, `job-detail-screen.tsx` |
| Posting preparation and saved review | `/app/matches/:jobId/prepare`, `/app/tracker/:applicationId/review` | `posting-application-screen.tsx`, `posting/posting-review-screen.tsx` |
| Studio and job draft | `/app/tailor`, `/app/tailor/:jobId` | `tailor-screen.tsx` |
| Review | `/app/approvals` | `approvals-screen.tsx` |
| Tracker and case | `/app/tracker`, `/app/tracker/:applicationId` | `tracker-screen.tsx` |
| Case questions | `/app/tracker/:applicationId/questions` | `questions-screen.tsx` |
| Activity and operations | `/app/activity`, `/app/operations`, `/app/admin` | `activity-screen.tsx`, `operations-screen.tsx`, `admin-screen.tsx` |

The saved-review row is the working tree's addition described in section 8.4: the posting-to-application path and the saved review step for a recorded case.

## 8.2 Representative HTTP routes

Prefix every path in this table with `/api`. Braced identifiers stand for values returned by the service. In particular, use the approval ID to decide a packet and the application ID to read its history. This is a task-oriented selection. The full baseline route table is in `README.md`; `tests/test_docs_accuracy.py` checks that reference against the application schema.

| Action | Method and relative path |
| --- | --- |
| Read or change identity | `GET /auth/me`, `PATCH /auth/me` |
| Upload and read source | `POST /resumes`, `GET /resumes/{profile_id}` |
| Read or replace confirmed facts | `GET`, `PUT /profiles/{profile_id}/application-profile` |
| Read document library | `GET /documents` |
| Manage a personal model key | `GET`, `PUT`, `DELETE /llm/credentials` |
| Refresh or search | `POST /jobs/refresh`, `POST /jobs/search` |
| Read a posting or locations | `GET /jobs/{job_id}`, `GET /jobs/locations` |
| Create or edit a draft | `POST /tailor`, `PUT /tailored/{tailoring_id}` |
| Retrieve the deliverable | `GET /tailored/{tailoring_id}/download` |
| Prepare a packet | `POST /applications/prepare` |
| Decide a packet | `POST /applications/{approval_id}/approve` or `/reject` on the same ID |
| Read approval state | `GET /applications/approvals/{approval_id}` |
| Read application details | `GET /applications/{application_id}` |
| Read plan or persist answers | `GET /applications/{application_id}/questions`, `PUT /applications/{application_id}/answers` |
| Inspect case evidence | `GET /applications/{application_id}/evidence` |
| Record a permitted transition | `PATCH /applications/{application_id}/status` |
| Inspect run or audit trail | `GET /runs/{run_id}`, `GET /audit` |
| Inspect workers as administrator | `GET /admin/health/workers` |
| Resume eligible work as administrator | `POST /admin/embedding-runs/{run_id}/resume` |

## 8.3 The complete API route set

Every route the service exposes at the baseline, with the module that implements it. The route reference in `README.md` is checked against the application schema by `tests/test_docs_accuracy.py`, so a route that is added without a row there fails the build; this table is the same set, arranged by area.

| Route | Purpose | Implemented by |
| --- | --- | --- |
| GET /api/health | Service status | src/api/routes/health.py |
| GET /api/health/live | Liveness of the API process | src/api/routes/health.py |
| GET /api/health/ready | Readiness of the database and worker | src/api/routes/health.py |
| POST /api/auth/register | Create an account | src/auth/routes.py (fastapi-users) |
| POST /api/auth/cookie/login | Sign in and set the session cookie | src/auth/routes.py (fastapi-users) |
| POST /api/auth/cookie/logout | End the cookie session | src/auth/routes.py (fastapi-users) |
| POST /api/auth/token/login | Sign in and return a bearer token | src/auth/routes.py (fastapi-users) |
| POST /api/auth/token/logout | End the bearer session | src/auth/routes.py (fastapi-users) |
| POST /api/auth/forgot-password | Request a password-reset token | src/auth/routes.py (fastapi-users) |
| POST /api/auth/reset-password | Set a new password with a reset token | src/auth/routes.py (fastapi-users) |
| POST /api/auth/request-verify-token | Request an e-mail verification token | src/auth/routes.py (fastapi-users) |
| POST /api/auth/verify | Verify the account with the verification token | src/auth/routes.py (fastapi-users) |
| GET /api/auth/me | The authenticated principal | src/auth/routes.py |
| PATCH /api/auth/me | Change the caller's own e-mail, password or name | src/auth/routes.py |
| DELETE /api/auth/me | Deactivate the account and end its sessions | src/auth/routes.py |
| GET /api/auth/sessions | The caller's live sessions, without their tokens | src/auth/routes.py |
| POST /api/auth/sessions/revoke | End every session of the caller | src/auth/routes.py |
| POST /api/auth/sessions/revoke-others | End every session except the current one | src/auth/routes.py |
| DELETE /api/auth/sessions/{token} | End one session of the caller | src/auth/routes.py |
| GET /api/audit | The caller's own audit trail | src/api/routes/audit.py |
| POST /api/resumes | Upload a resume and return a validated profile | src/api/routes/resumes.py |
| GET /api/resumes/{profile_id} | Read a stored profile | src/api/routes/resumes.py |
| GET /api/profiles/{profile_id}/application-profile | Read the confirmed preferences and eligibility | src/api/routes/profile_answers.py |
| PUT /api/profiles/{profile_id}/application-profile | Replace the confirmed preferences and eligibility | src/api/routes/profile_answers.py |
| GET /api/profiles/{profile_id}/eeo | Read the voluntary equal-opportunity record | src/api/routes/profile_answers.py |
| PUT /api/profiles/{profile_id}/eeo | Save the voluntary equal-opportunity record | src/api/routes/profile_answers.py |
| DELETE /api/profiles/{profile_id}/eeo | Delete the voluntary equal-opportunity record | src/api/routes/profile_answers.py |
| GET /api/profiles/{profile_id}/question-gaps | The questions the stored facts cannot yet answer | src/api/routes/profile_answers.py |
| GET /api/profiles/countries | The countries the eligibility answers accept | src/api/routes/profile_answers.py |
| GET /api/profiles/{profile_id}/matches | Read the profile's match history | src/api/routes/jobs.py |
| GET /api/profiles/employer-answers | Saved posting-form answers | src/api/routes/posting_applications.py |
| PUT /api/profiles/employer-answers/{answer_id} | Save one posting-form answer | src/api/routes/posting_applications.py |
| DELETE /api/profiles/employer-answers/{answer_id} | Delete one posting-form answer | src/api/routes/posting_applications.py |
| GET /api/documents | The caller's document library | src/api/routes/documents.py |
| GET /api/documents/{document_id}/download | Download one of the caller's documents | src/api/routes/documents.py |
| POST /api/jobs/refresh | Queue a refresh and return a run identifier | src/api/routes/jobs.py |
| POST /api/jobs/search | Rank the stored corpus for a profile | src/api/routes/jobs.py |
| GET /api/jobs/{job_id} | Read one stored listing | src/api/routes/jobs.py |
| GET /api/jobs/locations | The distinct locations the corpus carries | src/api/routes/jobs.py |
| GET /api/jobs/suggest | Ranked suggestions for one profile | src/api/routes/jobs.py |
| GET /api/jobs/sources | The configured sources and their last contact | src/api/routes/jobs.py |
| GET /api/jobs/{job_id}/application-form | The stored form observations for a posting | src/api/routes/posting_applications.py |
| PUT /api/jobs/{job_id}/application-form/answers | Save answers for a posting's form | src/api/routes/posting_applications.py |
| GET /api/runs | The caller's runs | src/api/routes/jobs.py |
| GET /api/runs/{run_id} | Read one run and its progress | src/api/routes/jobs.py |
| POST /api/tailor | Tailor a resume for a job, with its reports | src/api/routes/tailoring.py |
| GET /api/tailored/{tailoring_id} | Read a stored tailoring run | src/api/routes/tailoring.py |
| PUT /api/tailored/{tailoring_id} | Save an edit and revalidate the draft | src/api/routes/tailoring.py |
| GET /api/tailored/{tailoring_id}/download | Download the deliverable of a tailoring | src/api/routes/artifacts.py |
| POST /api/applications/prepare | Check the target, select the adapter, create an approval request | src/api/routes/applications.py |
| POST /api/applications/{approval_id}/approve | Record a human approval and queue the run | src/api/routes/applications.py |
| POST /api/applications/{approval_id}/reject | Record a human rejection | src/api/routes/applications.py |
| GET /api/applications/approvals/{approval_id} | Read the state of an approval request | src/api/routes/applications.py |
| GET /api/applications | List the tracked applications | src/api/routes/tracking.py |
| GET /api/applications/{application_id} | Read one application and its events | src/api/routes/tracking.py |
| PATCH /api/applications/{application_id}/status | Change an application status | src/api/routes/tracking.py |
| GET /api/applications/{application_id}/questions | Read the stored question plan with saved answers | src/api/routes/applications.py |
| GET /api/applications/{application_id}/answers | Read the saved answers | src/api/routes/applications.py |
| PUT /api/applications/{application_id}/answers | Save permitted answers for the application | src/api/routes/applications.py |
| GET /api/applications/{application_id}/posting-review | Read the saved review state | src/api/routes/applications.py |
| POST /api/applications/{application_id}/authorize-fill | Authorize one fill-only helper pass | src/api/routes/applications.py |
| GET /api/applications/{application_id}/evidence | Read the evidence records of an application | src/api/routes/artifacts.py |
| GET /api/applications/{application_id}/evidence/{filename} | Download one evidence artifact | src/api/routes/artifacts.py |
| GET /api/llm/credentials | Whether a personal credential is stored | src/api/routes/llm_credentials.py |
| POST /api/llm/credentials | Store a personal credential | src/api/routes/llm_credentials.py |
| PUT /api/llm/credentials | Replace the stored credential | src/api/routes/llm_credentials.py |
| PATCH /api/llm/credentials/{credential_id} | Update a stored credential | src/api/routes/llm_credentials.py |
| POST /api/llm/credentials/test | Test the platform connection | src/api/routes/llm_credentials.py |
| POST /api/llm/credentials/{credential_id}/test | Test a stored connection | src/api/routes/llm_credentials.py |
| POST /api/llm/credentials/{credential_id}/activate | Set a stored connection active | src/api/routes/llm_credentials.py |
| DELETE /api/llm/credentials | Remove the stored credential | src/api/routes/llm_credentials.py |
| DELETE /api/llm/credentials/{credential_id} | Remove one stored connection | src/api/routes/llm_credentials.py |
| GET /api/admin/overview | The platform overview | src/api/routes/admin.py |
| GET /api/admin/jobs/metrics | Corpus and index statistics | src/api/routes/admin.py |
| GET /api/admin/health/workers | Inspect workers | src/api/routes/admin.py |
| POST /api/admin/workers | Register a worker process | src/api/routes/admin.py |
| POST /api/admin/workers/{worker_id}/stop | Mark a worker stopped | src/api/routes/admin.py |
| GET /api/admin/runs | The platform runs | src/api/routes/admin.py |
| GET /api/admin/runs/{run_id} | One platform run in detail | src/api/routes/admin.py |
| GET /api/admin/embedding-runs | The embedding runs | src/api/routes/admin.py |
| GET /api/admin/embedding-runs/{run_id} | One embedding run in detail | src/api/routes/admin.py |
| POST /api/admin/embedding-runs/{run_id}/cancel | Cancel an embedding run | src/api/routes/admin.py |
| POST /api/admin/embedding-runs/{run_id}/resume | Resume eligible work | src/api/routes/admin.py |

## 8.4 Technical references and dated evidence

Three checks answer three different questions, and a reader should keep them apart. The offline ranking fixture shows how the ranker behaves on labelled examples. A browser test against the local fake ATS can establish a verified fixture submission. The live pilot of 15 November 2026 shows where preparation stopped and which fields a diagnostic pass could fill; it records no submission and no employer confirmation. The records below name the source of each check, so a reader can repeat one or decline to generalise from it.

For operating and deployment decisions, consult `docs/ARCHITECTURE.md`, `docs/SECURITY.md` and `docs/RUNBOOK.md` at `7190151`. The security document carries the threat model and the control register, which names each control, the threat it mitigates, where it is implemented and the test that proves it. The table and column definitions are in `src/db/` and `migrations/versions/`; revision `d3e4f5a6b7c8` adds the approval's stored question plan. The workstream documents in `docs/implementation/` hold the plan and the execution record for each unit of delivery. Representative implementation tests are `tests/test_tenant_isolation_api.py` for scoped access, `tests/test_durable_queue.py` and `tests/test_worker_recovery.py` for claims and recovery, and `tests/test_ws32_durable_submission.py` for submission replay. `tests/test_ws45_questions_page.py` covers the saved plan; `tests/test_tailored_edit.py` covers revalidation after an edit.

The 21 October 2026 browser record in `docs/implementation/08-browser-automation.md` reports 25 of 25 checks against the controlled fake ATS. It exercised a real browser against local forms. The WS-21 ranking evaluation of 8 November 2026, recorded in `docs/evaluations/ws21-report.md`, used five profiles, 29 listings, six tailoring pairs, canned drafts and a lexical stand-in for semantic embeddings. It measured nDCG at ten of 0.8240 and precision at five of 0.4000. Neither number measures a live model's accuracy or a candidate's chance of an interview.

For the 15 November 2026 live pilot, `docs/evaluations/ws32-pilot-2026-11-15/01_pilot_as_is.json` records the early stop; `02_fill_star_normalised.json` in that directory records the instrumented fill. `03_liveness.json` records three closed postings among twelve probed, despite a final HTTP 200 after redirection. `04_planner_unresolved.json` records the seven-form planner comparison. The interpretation and outstanding confirmation check are in `docs/implementation/32-submission-readiness.md`, section 5.5.

On 21 November 2026, `docs/implementation/49-sprint-cleanup-and-ledger.md` recorded an isolated API, database copy, console and fake ATS. Saving an answer returned 200 and cleared the recorded sponsorship blocker; an EEO answer returned 422 and a cookie-authenticated write without the CSRF header returned 403. The automated layout sweep passed its checks in 84 of 84 surface and viewport combinations. The ledger reports 407 passing frontend tests and a backend result of 2,256 passed, eight skipped and 16 failed, attributing the failures to DNS resolution in `tests/test_jobs.py`. The long smoke journey and suggestions specification were not reverified to green; manual frame comparison, the per-screen state matrix and keyboard focus return remained open. These are dated observations, not a claim about a later checkout or a full accessibility assessment.

The working tree has moved on since `7190151`. After that revision it adds optional tailoring to the posting-to-application path, typed question forms, a scoped answer library, a saved review step, and a fill-only local helper with its own grant record. That work changes the console and the API surface, and its automated checks were not reviewed for this edition, so no statement in this document should be read as a result for it. None of it moves the submission boundary: the fill-only helper still stops and hands the browser to a person.

## 8.5 Internal composition of execution

The worker's internal parts divide claiming, dispatch, handling and settlement. For an application run, the handler resolves the approved packet and adapter; for an embedding run it resolves a job version and projection. Both return to lease-checked settlement. Only the application handler must first establish whether a previous attempt could already have reached its destination.

@figure composite

## 8.6 Communication for a fake-ATS approval

The numbered messages follow one authorized local run. The decision write and enqueue precede the response to the browser. Worker messages then cross the adapter boundary; later reads obtain run state and evidence. The message numbers distinguish the caller's 202 response from the worker's later evidence record. Once the queue transaction commits, the API need not wait for the worker; the caller and worker can continue independently.

@figure communication

## 8.7 Interaction overview

Preparation, human decision, execution and observation can occur in different sessions. Rejection ends the decision path without a worker submission. An accepted fake-ATS run leads to observation of its result; a live assist handover leaves the irreversible action with the person. Returning to Tracker is an observation, not another execution request. The view uses activity notation with reference-style nodes, because PlantUML has no dedicated interaction-overview syntax; the label on each node names the fragment it stands for.

@figure interaction-overview

## 8.8 Claim and lease timing

The timing view uses ordinal positions, not measured seconds. A first claim obtains a token; expiry and recovery can make the item eligible for a new claim. Once a second token is current, settlement carrying the first token cannot advance the checkpoint. The intervals in this view set no performance target or lease duration.

@figure timing

## 8.9 Local modeling conventions

The stereotypes in this profile are documentary labels for roles within JARVIS. They help distinguish, for example, a boundary that receives a request from a component that enforces policy or stores evidence. They are local to these diagrams. A stereotype neither grants a runtime capability nor establishes that a security control passed a test.

@figure profile
