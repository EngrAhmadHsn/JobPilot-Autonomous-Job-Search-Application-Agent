"""Build the SRS edit map: original voice, current system, original slots."""

import json
from pathlib import Path

P = {}


def para(i, text):
    P[str(i)] = text


# Front matter and introduction
para(
    34,
    "This Software Requirements Specification describes the Autonomous AI Job Application Agent, known in the console as JobPilot. It defines the requirements for a multi-user backend service with a REST API and a supervised worker, a relational database, a local vector store and a React operator console. The product reads a candidate's resume, collects job listings from public job-board APIs, ranks them with an explained score, tailors the resume without inventing facts and prepares applications for review. An approval records a decision and queues work; a separate worker performs it. The document defines the product context, constraints, interfaces, functional requirements, use cases, data classes and quality attributes. Each requirement has an identifier, a priority and a status, so a reader can see what the current release meets and what remains open. This edition reflects revision 7190151 of 22 November 2026.",
)
para(
    108,
    "This document states what the product must do. It describes requirements rather than design. The companion Software Design Document describes how the system meets them.",
)
para(
    110,
    "This SRS defines the requirements for the Autonomous AI Job Application Agent. It serves two readers: the supervisor, who reviews the requirements, and the developer, who designs, builds and tests against them. Version 3.0 reflects revision 7190151 of 22 November 2026. Requirement identifiers are unchanged from Version 2.0 so that the trace from requirement to design and test remains readable; requirement text has been revised where the system changed.",
)
para(
    112,
    "The product is a Python backend service with a REST API, a relational database, a local vector store, a supervised worker and a React operator console that ships as a separate package. It reads a candidate's resume, collects job listings from public job-board APIs, ranks them with an explained score built from eight components, tailors the resume without inventing facts, and prepares an application packet for a person to review. A decision on that packet creates durable work. The worker then acts within the permission granted to the selected adapter.",
)
para(
    113,
    "The product will not scrape web pages, use LinkedIn, bypass CAPTCHA or multi-factor authentication, or send an application without a recorded approval decision. Approval returns a run identifier; it is not evidence that an employer received anything. The local fake applicant tracking system accepts test applications end to end. On a real Greenhouse form the pilot may prepare supported fields and hand control to the person; it has no submit capability. The product will not return one account's data to another account, and the console will hold no credential.",
)
para(
    114,
    "The goals are to reduce the work of finding suitable jobs, keep every claim in a tailored resume traceable to the candidate's own profile, make each external action auditable, and keep one account's records separate from another's. A score is an aid to a decision, not a prediction of an employer's response.",
)
para(
    116,
    "Table 1 defines the terms used throughout this specification. The definitions follow the way the system uses each term; where a word has a narrower everyday meaning, the project meaning is stated explicitly.",
)
para(
    142,
    "Section 2 describes the product in plain language for the supervisor and candidate. Section 3 holds the numbered requirements for the developer and tester. Requirement identifiers use FR for functional requirements, NFR for non-functional requirements and UC for use cases. Each requirement keeps its identifier across editions, even where the text changes, so a reader can follow it into the Software Design Document. Status is recorded on each requirement rather than promised for the whole release.",
)

# Overall description
para(
    145,
    "This section gives the background for the requirements in section 3. It states no testable requirement.",
)
para(
    147,
    "Figure 1 shows the system and its boundary. The backend is a modular monolith with one Python package, a relational database and a React console in a separate package. A refresh writes jobs and work items to the database; the worker claims them and maintains the vector index. A stored search reads those records without contacting a job board. Browser automation runs in the worker only when an approved packet names an adapter with the required capability.",
)
para(
    148,
    "Commercial tools such as Simplify, Teal and LazyApply autofill forms, track applications or send applications in bulk. JobPilot uses documented public APIs for listings, checks each tailored claim against the source resume, gives the candidate the review packet and the decision, and records evidence for what it did. It does not send applications on real employer sites.",
)
para(
    152,
    "Interactive operation. The candidate signs in, uploads a resume, searches stored jobs, inspects a score and prepares an application. Review shows the stored questions and lets the candidate save an answer before deciding. The console holds no credential; the browser owns the session cookie and the CSRF token.",
)
para(
    153,
    "Unattended operation. A scheduler or an authorized caller requests a refresh. The API records a run and returns its identifier. The worker claims items, fetches listings and writes the corpus. A failed source is reported in the run; it does not stop the others.",
)
para(
    154,
    "Data processing. The refresh embeds texts that the local cache does not already hold, in batches of eight. The worker fences each lease with a token so that an old process cannot overwrite work claimed by a new one. A run may be resumed without repeating completed embeddings.",
)
para(
    155,
    "Backup and recovery. The operator backs up the database and the data directory. The vector store is a derived index that can be rebuilt from the listings and the configured model. The purge command removes records past their retention window and anonymizes the audit rows it must keep.",
)
para(
    157,
    "Before first use the operator installs Python 3.13 and the Chromium browser used by Playwright, copies .env.example to .env, sets the board lists and runs the migrations. The first refresh downloads the local embedding model. A production start also needs an explicit CORS origin list, secure cookies, a signing secret and a submission policy; the application refuses to start with a wildcard origin.",
)
para(
    159,
    "Figure 2 shows the main stages. Resume intake produces a profile. Refresh collects listings into a shared corpus. Search ranks stored listings against a profile. Tailoring proposes a draft and checks it against the source. Preparation writes a packet for review; a person decides; queued work runs only where an adapter has permission. Tracker records the outcome a person reports. Each stage can be used on its own.",
)
para(160, "The stages are summarized below.")
para(
    161,
    "Resume intake: parse a resume into a profile, report what could not be read and store the source document.",
)
para(
    162,
    "Job discovery: collect listings from Greenhouse, Lever, Ashby and Remotive, then normalize, deduplicate, screen and index them.",
)
para(
    163,
    "Matching and search: rank stored jobs with eight score components and a fixed denominator, and explain each result.",
)
para(
    164,
    "Tailoring and ATS analysis: draft a resume and cover letter from profile facts, validate the claims, inspect the rendered document and support section edits followed by fresh validation.",
)
para(
    165,
    "Application workflow: prepare a packet, answer stored questions, record a human decision and queue permitted work. Only the local fake ATS can submit and verify.",
)
para(166, "Application tracking: record status transitions with an actor and ordered events.")
para(
    167,
    "Evaluation: measure extraction, ranking, factuality and isolation against a fixed offline fixture, and keep the fixture settings beside the numbers.",
)
para(168, "Identity and access: register an account, keep a server-side session and end it.")
para(
    169,
    "Isolation and retention: keep private rows and files with their owner and purge what has aged out.",
)
para(170, "Operator console: drive these tasks from a browser without holding a secret.")
para(
    174,
    "The main user is the candidate, who is comfortable with a browser and REST tools. Every capability is available through documented HTTP endpoints and scripts with readable errors. The candidate reviews extracted facts, answers questions the resume cannot settle and decides whether to authorize an application. An administrator can inspect platform runs and worker health and resume eligible interrupted work; those rights do not include making an application decision for another account.",
)
para(175, "The constraints below bound what the product may do and how it may be operated.")
para(
    176,
    "Terms of service. Only documented, key-less public job-board APIs supply listings. Remotive requires credit and a link back to the original listing.",
)
para(
    177,
    "Safety. Submission on a real site is irreversible and remains with the person. Approval, evidence and fail-closed behavior are required before any executable run; the real-adapter pilot holds prepare permission only.",
)
para(
    178,
    "Security and privacy. Web content is untrusted data. Secrets and personal identifiers stay out of prompts and logs. A personal provider key is encrypted and used only for that account's calls.",
)
para(
    179,
    "Audit. Every external action and application decision leaves a record attributed to a principal.",
)
para(
    180,
    "Language and libraries. The runtime is Python 3.13 with FastAPI, Pydantic, LangGraph, SQLAlchemy, fastapi-users and Playwright. The console is React 19 with Vite and TypeScript.",
)
para(
    181,
    "Embedding. The local EmbeddingGemma-2 model is the default. It has an 8,000-character input limit and batches of at most eight texts. The earlier cloud embedding tier is no longer used.",
)
para(
    182,
    "Memory. Larger embedding batches exhausted memory in testing, so the local batch size stays at eight. The evaluator embeds one job at a time when filling a small gap.",
)
para(
    183,
    "Scope of automation. The system does not bypass CAPTCHA, MFA or anti-bot controls. A challenge stops the browser flow.",
)
para(
    184,
    "Resource bounds. A request may not exceed 8 MiB, a client may not exceed 60 requests a minute, the process may not hold 64 requests in flight, a refresh may not embed more than 2,000 cache misses or 5,000 in a day, and a corpus refresh may not admit more than 10,000 listings.",
)
para(
    185,
    "Deployment. The API and worker are separate processes against one relational database. SQLite is the development store; PostgreSQL is a supported deployment option. A local Chroma store keeps the job vectors and must be single-writer.",
)
para(
    187,
    "The listed job-board endpoints keep their current response shapes. A change requires an adapter update.",
)
para(188, "The operator curates the boards to watch. The product does not discover companies.")
para(
    189,
    "The candidate supplies a resume in DOCX, TXT, Markdown or a PDF with a usable text layer. A scanned PDF without text is refused.",
)
para(190, "The embedding model weights download once and stay cached on the CPU-capable host.")
para(
    191,
    "A language model provider is available for tailoring unless the candidate supplies a working personal key. Search, matching and the console work without a model call.",
)
para(
    192,
    "SQLite serves development and PostgreSQL serves deployment through the same Alembic migrations.",
)
para(
    193,
    "The signing secret, the domain allowlist and the submission policy are set by the operator before a production start.",
)
para(
    194,
    "The console is served as static files behind the same origin as the API, or is pointed at an absolute API URL.",
)
para(
    195,
    "Password-reset and verification tokens are written to a local mailbox directory in development. An SMTP provider replaces that in deployment.",
)

# Specific requirements prose
para(
    198,
    "Every requirement has a unique identifier, a priority and a status. Each requirement can be checked against an implementation or a test. Workstream and follow-up labels point to the implementation documents. Identifiers are retained from Version 2.0; the text and status have been revised where the system changed. A status of Done describes the documented revision, not a fresh test run.",
)
para(201, "Table 2 lists the external systems the product calls and the interface each one uses.")
para(
    205,
    "The product exposes its operations through a REST API that accepts and returns JSON. Table 3 maps the backend routes, their purpose and the credential each requires.",
)
para(
    206,
    "OpenAPI documentation is served locally at /docs and is restricted in production. The React console calls the same API. A new route must be added to the route table before the build passes.",
)
para(
    209,
    "The console sends the browser's session cookie on every request and echoes the CSRF cookie in a header on every unsafe request. It holds no token. The development server proxies /api to the backend; the browser sees one origin.",
)
para(
    213,
    "The table gives the declared minimums from pyproject.toml and package.json. The system runs against the versions used for revision 7190151.",
)
para(
    216,
    "The product calls job-board and model endpoints over HTTPS. It sends GET requests to job boards, does not follow redirects and sets an identifying User-Agent. Its own API uses HTTP with JSON. Cross-origin access follows an explicit CORS list, and outbound hosts are checked against an allowlist before any request is sent.",
)
para(
    220,
    "Turns an uploaded resume into a profile. Traces to UC-1, tests/test_resumes_api.py, tests/test_resume_parser.py, tests/test_profile_preferences.py and tests/test_upload_validation.py. A PDF with a usable text layer is supported by FR-1.8.",
)
para(
    222,
    "A multipart file with extension .docx, .txt or .md, or a readable PDF, sent by an authenticated account. A profile identifier is used for retrieval.",
)
para(
    226,
    "profile_id, warnings and the full profile as JSON. The parsed facts remain separate from answers the candidate confirms later.",
)
para(
    228,
    "Validation failures return HTTP 400 with a cause. An unknown or foreign identifier returns HTTP 404. A file that is not a real document returns HTTP 400. Logs record sizes and counts, never document text.",
)
para(
    231,
    "Collects listings from public APIs into one corpus and its vector index. Traces to UC-2, tests/test_jobs.py, tests/test_http_client.py, tests/test_refresh_and_stored_search.py and the durable-run tests. An accepted refresh returns a run identifier; the worker performs the collection.",
)
para(
    233,
    "Board lists in GREENHOUSE_BOARDS, LEVER_COMPANIES, ASHBY_ORGS and REMOTIVE_*. A refresh is triggered through POST /api/jobs/refresh or scripts/refresh_jobs.py by an authenticated or scheduler principal.",
)
para(
    237,
    "A refresh report with counts for found, dropped, deduplicated, persisted, embedded, screened-out and admission-capped listings, a map of source errors, planned and used embedding requests and documents, and the flags quota_exhausted and degraded_embedding.",
)
para(
    239,
    "A failing source, vector store or quota limit lowers the result and names the cause in the report. It does not raise an error to the caller. Outstanding work remains claimable after an interruption.",
)
para(
    242,
    "Ranks stored listings for a profile and explains the score. Traces to UC-3, tests/test_matching.py, tests/test_chroma_store.py and tests/test_jobs_api.py. The engine uses eight components: semantic, lexical, skill, experience, seniority, location, preference and role.",
)
para(
    244,
    "A profile_id, an optional query, workplace and corpus-location filters, a skills filter, an optional target role and top_n (default 10, maximum 50).",
)
para(
    247,
    "FR-3.11 remains open. A listing that states no skills still scores a neutral value on the skill component and can outrank a listing with a partial match. The offline evaluation records this as a degraded-ranking case rather than removing it.",
)
para(
    249,
    "Ranked job and match pairs, statistics with per-component weights and scores, source_errors (empty for a store-only search), the degraded flag and a short explanation for each result.",
)
para(
    251,
    "An unknown or foreign profile returns HTTP 404. Missing vectors or a vector store failure return HTTP 200 with the degraded flag set, unless the caller asked for indexed jobs only.",
)
para(
    254,
    "Drafts job-specific resume content from profile facts and checks it. Traces to UC-4, tests/test_tailor.py, tests/test_ats.py, tests/test_render.py, tests/test_research.py and tests/test_tailored_edit.py. Saved section edits repeat the checks without another model call.",
)
para(
    256,
    "A profile, a listing and an owned document selected by profile_id and job_id. A saved edit carries the draft identifier and the edited sections.",
)
para(
    260,
    "Tailored summary, highlighted skills, experience, projects, cover letter, the factuality report, the ATS report, the grounded insights and the path of the rendered DOCX. A saved edit updates the draft and its reports while leaving the original upload intact.",
)
para(
    262,
    "The client classifies model failures as configuration, rate limit, unavailable or invalid output. A missing key fails with an actionable message and never echoes the key. A factuality violation returns HTTP 200 with the cleaned document and a report. A provider failure supplies no replacement draft.",
)
para(
    265,
    "Prepares an application packet, records a human decision and queues permitted work. Traces to UC-5, tests/test_application_workflow.py, tests/test_workflow_e2e.py, tests/test_graph_executor.py, tests/test_approval_flow.py, tests/test_evidence.py and tests/test_ws32_durable_submission.py. Approval returns HTTP 202 with a run identifier; the worker reaches a result later. Only the local fake ATS has submit and verify capabilities.",
)
para(
    267,
    "An application request with the job, candidate facts, resume path and answers, plus a stored question plan. A decision names the approver and the approval identifier.",
)
para(
    271,
    "Approval returns the run identifier, status QUEUED and success false. Evidence is retrieved later through the application and run records. The approval row carries the approver, the reason, the decision time and the reviewed payload.",
)
para(
    273,
    "A rejection ends the decision path without work. A queue refusal leaves the approval pending. A worker rechecks policy before acting. An attempt marker without a stored outcome becomes submission.uncertain and calls for human reconciliation rather than a second send. The system never reports a submission it cannot verify.",
)
para(
    276,
    "Records the lifecycle of each application as attributed events. Traces to UC-6, tests/test_tracking.py, tests/test_tracking_api.py and tests/test_ws45_answers.py. The questions page reads the saved plan and stored answers without contacting the employer.",
)
para(
    280,
    "A status change request with the target status, an authenticated actor and optional notes. An answer request carries a permitted question key and its answer.",
)
para(
    284,
    "Application records with status and ordered event history, plus the stored question plan and the answers saved for that application.",
)
para(
    286,
    "An illegal transition returns HTTP 409. An unknown or foreign application returns HTTP 404. A terminal outcome from a non-human actor is refused. EEO and attestation answers are refused with HTTP 422.",
)
para(
    289,
    "Measures quality against a fixed offline fixture so the project can support claims with numbers. Traces to tests/test_eval_runner.py and tests/test_eval_metrics.py.",
)
para(
    291,
    "Golden datasets: five profiles, 29 listings, six tailoring pairs and lexical stand-ins for embeddings and canned model drafts. All identities are synthetic. The fixture settings are recorded beside each result.",
)
para(
    295,
    "A dated Markdown report and a JSON file with the same numbers. The report names the providers and whether text or embeddings were canned.",
)
para(297, "A missing dataset or canned response stops the run with a message naming the file.")
para(
    300,
    "Gives each person an account, signs them in and lets them end a session. Traces to UC-7, tests/test_auth.py and tests/test_user_storage.py. A personal provider key can be stored encrypted and is tested separately.",
)
para(
    306,
    "The account record, the session list with only the first eight characters of each token, and a token delivered to the mailbox file in development.",
)
para(
    311,
    "Decides which rows one account may read and keeps that decision in the data layer rather than in each route. Traces to UC-8, tests/test_tenant_isolation.py and tests/test_ws14_a0_verification.py.",
)
para(317, "The caller's own rows and an audit trail the caller may read.")
para(
    322,
    "Keeps each account's files in its own directory and removes what has aged out. Traces to tests/test_retention.py, tests/test_user_storage.py and scripts/purge_expired.py.",
)
para(328, "A purge report naming the rows and files removed, and the anonymized audit rows.")
para(
    333,
    "A React application in a separate package that drives the API for a signed-in person. Traces to UC-8, tests/test_documents_api.py, frontend/src and frontend/e2e. Screens include Home, Resume, Profile, Account, Discover, job detail, Studio, Review, Tracker and its questions page, Activity and Operations.",
)
para(
    335,
    "The API's OpenAPI description and typed client. Generated types are checked into source and are regenerated deliberately rather than on every build.",
)
para(339, "The console screens, driven by the API's own responses and statuses.")
para(
    341,
    "A network failure, a timeout, an abort and each of 400, 403, 404, 409, 413, 422, 429 and 503 have their own message. A long call may be cancelled; the server keeps whatever it had already persisted.",
)
para(
    344,
    "Bounds what one caller can cost the system and keeps hostile text as data. Traces to tests/test_ws12_hardening.py and tests/test_ws15_hardening.py.",
)
para(350, "A bounded service, and a response that names the limit a request reached.")
para(
    352,
    "A limit produces a refusal whose status says what to do: 413, 429 or 503. A hostile listing is neutralized rather than refused, so one bad document does not stop a refresh.",
)
para(
    354,
    "Each use case names the actor, preconditions, main flow, exceptions and the requirements it covers. The tables keep the use-case numbers used in Version 2.0.",
)

# Classes and objects
para(
    372,
    "The major data classes are listed below. Each entry names the requirements that use it. Stored tables and their fields are described in section 3.7.",
)
para(
    375,
    "personal_information (name, title, email, phone, location, website), summary, skills, skill_categories, education, experience (title, company, dates, bullets, years), projects, certifications, achievements, work_preferences. ApplicationProfile holds separately confirmed answers, including country-specific work eligibility, and remains distinct from extracted facts.",
)
para(
    377,
    "parse_resume(path) builds it. validate_candidate_profile(profile) returns warnings. Reference: FR-1.1 to FR-1.9, UC-1.",
)
para(
    380,
    "id, source, source_job_id, title, company, description, location, remote_policy, employment_type, salary, currency, seniority, required_skills, preferred_skills, experience_requirements, education_requirements, application_url, company_url, posted_at, last_seen_at, metadata. Employment type is absent on most live listings and is treated as unknown.",
)
para(
    385,
    "overall_score and eight component scores (semantic, lexical, skill, experience, seniority, location, preference and role, each 0 to 100), evidence_coverage, matched_requirements, missing_requirements and explanation.",
)
para(
    387,
    "calculate_match(job, profile, semantic_score, weights) builds it. validate_weights() checks overrides. The denominator contains the weights of applicable components; NOT_APPLICABLE removes a component, while an unknown value keeps its weight and scores zero. Reference: FR-3.2 to FR-3.11, UC-3.",
)
para(
    390,
    "TailoredResume: summary, highlighted_skills, experience, projects, cover_letter and edited_at. FactualityReport: passed, removed_skills, removed_experience, removed_projects and violations. ATSReport and RenderReport describe the delivered file and format preservation separately.",
)
para(
    392,
    "tailor_resume(profile, job, generate) returns the draft and reports. extract_requirements(job, skills) supplies the requirements. Saving a section edit rechecks factuality and ATS coverage before writing a new deliverable. Reference: FR-4.1 to FR-4.10, UC-4.",
)
para(
    395,
    "ApplicationRequest, PreparedApplication with a stored question plan, SubmissionEvidence (URL, confirmation text, screenshot path, trace path, status) and ApplicationResult (success, status, message, evidence, metadata). An approval identifier addresses a decision; a run identifier addresses queued work.",
)
para(
    397,
    "An adapter implements supports_url, prepare and, only where permitted, submit and verify. The registry makes capability a grant rather than an inference from a method's presence. Reference: FR-5.1 to FR-5.17, UC-5.",
)
para(
    400,
    "Application: id, owner_id, profile_id, job_id, workflow_id, approval_id, status, submitted_at, verified_at, notes. ApplicationEvent: application_id, event_type, actor, from_status, to_status, metadata, recorded_at. ApplicationAnswer: application_id, question_key and answer_text, scoped to the owner.",
)
para(
    402,
    "transition(app, to, actor, db, metadata) validates the move and appends an event. Answers are upserted by owner and question key. Reference: FR-6.1 to FR-6.7, UC-6.",
)
para(
    425,
    "The product runs as a local service with no uptime target. Upload, stored search, match history, the console, approval and tracking work without a model provider once the weights are present. A refresh needs the job boards; a new draft needs a provider; an executable submission needs the local test site. A responsive API does not prove the worker is running.",
)
para(
    431,
    "The product shall run on Python 3.13 on Windows and Linux, using the same migrations on SQLite and PostgreSQL and storing JSON columns in a portable form. The embedding model runs on CPU. The console builds on both platforms. PostgreSQL is a deployment option rather than evidence of a production installation.",
)
para(
    449,
    "The relational database uses Alembic migrations, one per workstream, through the current head. Table 4 lists the tables and their owners. Every user-scoped table carries an indexed, non-null owner_id; the shared job corpus does not. The vector store holds one Chroma collection keyed by job content, model and dimension, and a SQLite cache keyed by the hash of model, dimension and text. A candidate's query vector is never written to that cache. Recent migrations add saved application answers and the question plan stored with an approval.",
)
para(
    453,
    "Python code follows PEP 8 as enforced by ruff, with a line length of 100 and target version 3.13.",
)
para(
    457,
    "Security controls follow the register in docs/SECURITY.md. The submission preconditions in that document apply to any real-site use; the current release grants executable submission only to the local fake ATS.",
)
para(
    459,
    "Business logic lives in code rather than in prompts. A model supplies text that deterministic checks then validate.",
)
para(
    460,
    "Authorization lives in the data layer. A route may not query a user-scoped table directly, and a test enforces the rule.",
)

T = {}
# Revision history and tables whose text changed
T["0"] = {"2|3": "Requirements revised for the current system (revision 7190151)."}
T["2"] = {
    "1|1": "A module that maps one external source or site to a common interface.",
    "5|1": "The signed, reviewed packet stored for one approval decision.",
    "14|1": "A model-supplied draft for one profile and one job.",
    "19|1": "The record of unsupported claims the validator removed from a draft.",
    "21|1": "A question saved with a prepared application and answered by its owner.",
    "22|1": "A stored decision on one packet, with payload, approver and decision time.",
    "23|1": "A durable unit of work with status, owner, attempts and events.",
    "24|1": "A claim on a work item, fenced by a token so an old worker cannot settle it.",
    "25|1": "Local fake ATS, which can submit and verify test applications.",
    "26|1": "External ATS adapter that may prepare but not submit on a real site.",
    "27|1": "A score with explanation for one owned profile and one listing.",
    "28|1": "The local vector index, rebuilt from jobs when its model or dimension changes.",
}
T["6"] = {
    "9|1": "The system shall parse a resume with a readable text layer and shall refuse a scan with no text."
}
T["8"] = {
    "2|1": "The system shall score eight components: semantic, lexical, skill, experience, seniority, location, preference and role.",
    "4|1": "The system shall divide the weighted sum by the sum of applicable weights, removing a component only when it is NOT_APPLICABLE.",
    "9|1": "The system shall keep a listing whose vector is missing and mark the result degraded unless the caller asks for indexed jobs only.",
}
T["10"] = {
    "2|1": "The system shall keep preparation, approval, queued execution, submission and verification as separate steps.",
    "3|1": "The system shall return HTTP 202, status QUEUED and a run identifier when a decision is accepted.",
    "4|1": "The system shall grant submit and verify only to adapters whose registry entry carries those capabilities.",
    "5|1": "The system shall treat a missing confirmation or artifact as failed verification and never report success.",
    "8|1": "The system shall store an attempt marker before calling the adapter so recovery cannot send twice after a possible acceptance.",
    "9|1": "The system shall escalate an attempt with no stored outcome as submission.uncertain for human review.",
    "11|1": "The system shall store the question plan used by a packet so Review does not depend on a later employer form.",
    "12|1": "The system shall accept an answer only when it is permitted, owned and scoped to the saved question revision.",
}
T["11"] = {
    "2|1": "The system shall allow only the transitions in the application lifecycle and require a human actor for terminal outcomes.",
    "5|1": "The system shall keep application questions and their saved answers with the application rather than re-reading the employer site.",
}
T["16"] = {
    "1|1": "The console shall present Home, Resume, Profile, Account, Discover, job detail, Studio, Review, Tracker with question detail, Activity and Operations.",
    "4|1": "The console shall include a Studio diff and save section edits that are revalidated against the source profile and job.",
    "5|1": "The console shall show queued status with a run identifier after approval, not a submission receipt.",
}
T["26"] = {
    "1|1": "Target: at least 95% of store-only searches over 5,000 listings shall finish within ten seconds, reported with hardware, cache state and percentile."
}
T["28"] = {
    "7|1": "Submission shall require an adapter with the submit capability, an allowlisted host and a recorded approval.",
    "13|1": "Target: personal data shall be minimised and stored with per-tenant encryption. Directory separation alone does not meet this requirement.",
    "14|1": "Target: an uploaded file shall be scanned for malware before storage. Format validation alone does not meet this requirement.",
}
T["30"] = {
    "10|1": "application_answers; application id, question key and answer text; Principal; Done",
    "11|1": "approval_requests form_questions; stored question plan for the reviewed packet; Principal; Done",
}

out = {"paragraphs": P, "tables": T}
Path(".scratch/fyp-20261125/edits").mkdir(parents=True, exist_ok=True)
Path(".scratch/fyp-20261125/edits/srs-edits.json").write_text(
    json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
)
print("SRS edits:", len(P), "paragraphs,", sum(len(v) for v in T.values()), "cells")
