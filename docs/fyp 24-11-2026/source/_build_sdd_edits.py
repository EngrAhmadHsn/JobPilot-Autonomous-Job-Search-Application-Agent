"""Build the SDD edit map: original voice, current system, original slots."""

import json
from pathlib import Path

P = {}


def para(i, text):
    P[str(i)] = text


para(
    100,
    "This Software Design Document describes the architecture and design of the Autonomous AI Job Application Agent, known in the console as JobPilot. It states how the system is divided, what each part owns, how parts exchange data and how the design answers the requirements in the Software Requirements Specification, Version 3.0. It describes revision 7190151 of 22 November 2026. Work in the tree after that revision is identified where it affects the design.",
)
para(
    101,
    "A maintainer uses this document to find the module that owns a behaviour, the data it reads and writes, and the test that holds it in place. A supervisor uses it to check that the design answers the requirements and that the security decisions were made deliberately. The document records what the code does, including the limits of what has been demonstrated.",
)
para(
    103,
    "The document covers the Python backend, its relational and vector stores, the supervised worker and browser automation, and the React operator console. It covers the flows that carry the product: refreshing the job corpus, ranking stored jobs against a profile, tailoring and validating a resume, and preparing a packet for a person to decide on. The local fake ATS is the only target for executable submission and verification.",
)
para(
    104,
    "The design follows the project goals: a modular monolith, deterministic code where a rule can be written down, and a recorded human decision before any executable run. It keeps two boundaries explicit. Approval returns a run identifier rather than a result, and a real-board pilot can prepare fields without gaining permission to submit.",
)
para(
    106,
    "Section 2 gives the system overview. Section 3 gives the architecture and the reasoning behind it. Section 4 gives the data design. Section 5 gives the component design. Section 6 gives the interface design with captures from a running console. Section 7 traces requirements to components and evidence. Section 8 holds the appendices.",
)
para(108, "Software Requirements Specification, Version 3.0, docs/SRS.docx. Project repository.")
para(
    112,
    "Implementation roadmap and workstream documents, docs/implementation/. Project repository.",
)
para(
    115,
    "Evaluation baseline, docs/evaluations/report-2026-11-21.md; offline ranking fixture, docs/evaluations/ws21-report.md. Project repository.",
)
para(
    121,
    "The system is a Python service that turns a candidate's resume into a shortlist of jobs and, where an adapter has permission, into an application. It has four parts. The console is the person's side: a React application that calls the API. The API authenticates the caller, validates requests and writes records. The worker claims durable items from the database and performs refresh, embedding and approved runs. The stores hold the shared corpus, private records and derived vectors. A decision and the work it authorizes are separate records.",
)
para(
    122,
    "Two boundaries shape the design. Job listings and employer pages are untrusted input and are treated as data, never instructions. A text take from a page cannot choose a tool, a destination or a form answer. The second boundary is capability: the adapter registry grants prepare, submit and verify separately, and a method's presence does not grant the right to call it. The Greenhouse and Lever adapters hold prepare only; the local fake ATS holds all three.",
)
para(
    123,
    "The system reports what it did. A refresh names a failed source. A search sets a degraded flag when vectors are missing and states the reduced coverage. A 202 from approval means work was queued. A submission is reported only when the adapter's confirmation and required artifacts are present; otherwise the case goes to a person as uncertain. A run identifier is not an employer receipt.",
)

para(
    126,
    "The backend is a modular monolith with one Python package, an API process, a worker process and one relational database. The layers have different reasons to change. Routes translate HTTP into calls and enforce authentication. Domain modules own parsing, ranking, drafting, form preparation and transition rules. Infrastructure modules own storage, model clients and browser automation. Figure 1 shows the packages and the dependency direction between layers.",
)
para(
    129,
    "A domain module may call another domain module and the infrastructure, but it may not import from the interface layer or know that HTTP exists. The security package sits below both routes and worker: the same policy check runs in the request that records a decision and again in the worker before it acts. Authorization in the data layer keeps access rules in one place rather than in every route.",
)
para(
    130,
    "The console is a separate package with its own toolchain and tests. The API is the boundary between them. Typed client code is generated deliberately from the OpenAPI description and checked in; the build does not regenerate it from a running development server.",
)
para(
    131,
    "Figure 2 shows the same system as components and calls. The API writes work items and returns identifiers. The worker claims an item under a lease token, calls a domain executor and settles the item under the same token. The stores hold jobs, decisions, runs and vectors. A stale worker cannot settle work that another process has claimed.",
)
para(
    135,
    "The class diagrams give the vocabulary used in code, the object diagram shows one moment, and the sequence, activity and state diagrams show behavior. The diagrams are drawn from the models, migrations and transitions rather than from prose, and their captions name the view they provide.",
)
para(
    136,
    "Figure 3 shows the candidate, the listing and the match. The candidate profile holds facts parsed from a resume; the application profile holds answers the candidate confirms later. A JobMatchResult keeps eight component scores and an explanation without changing either input.",
)
para(
    139,
    "Figure 4 shows what tailoring produces. The factuality report is the record of claims the validator removed. The ATS report measures the delivered file against the listing, and the render report says whether format preservation succeeded. A saved edit updates the draft and repeats both checks while leaving the original upload in place.",
)
para(
    142,
    "Figure 5 shows the application request, prepared packet, adapter result and evidence. The approval record is a stored table with the reviewed payload and question plan, not a value passed through the graph. The graph carries the decision state into the worker; the persisted record is what execution restores.",
)
para(
    145,
    "Figure 6 shows one moment part way through a run: an account, its parsed profile, a listing with a scored match, a tailored draft with reports, and an approval whose run is queued. The three identifiers let the console read the decision, the work and the tracked case independently. No submission evidence exists at that moment.",
)
para(
    148,
    "The refresh asks each configured board for its listings, filters incomplete rows, deduplicates them, screens machine-generated text and applies admission limits before writing to SQL. The API commits a run and work items and returns 202. The worker claims items, embeds cache misses in batches of eight and keeps the vector index consistent with the rows. A failed source is reported without stopping the others.",
)
para(
    151,
    "Figure 8 shows the refresh as an activity. The two gates that decide cost are the corpus cap, which evicts listings not seen for the longest, and the embedding budget, which counts cache misses per refresh and per day. A run interrupted at the budget leaves its remaining work claimable rather than marking the job complete.",
)
para(
    154,
    "Preparation writes a packet with the reviewed payload and the question plan. A person reads it and decides. The decision write and its queued work commit together, and the API returns 202 with a run identifier. Later, the worker restores the approved packet, checks policy again and calls the adapter. Only the local fake ATS can submit and verify; a real-board handoff leaves the irreversible action with the person.",
)
para(
    157,
    "Figure 10 shows tailoring as an activity. The model proposes text and the validator removes claims the profile does not support. A violation is content: the run returns HTTP 200 with the cleaned draft and the report. A provider failure is an error and supplies no draft. Saving a section edit repeats validation and rendering without another model call.",
)
para(
    160,
    "The application workflow branches because people and browsers can stop. The approval node fails closed when no decision is recorded. The submit node returns permission_denied as a result when the adapter lacks the capability. An attempt marker is committed before the adapter call; a marker without an outcome becomes submission.uncertain and is escalated rather than replayed.",
)
para(
    163,
    "Figure 12 follows the data. The candidate supplies a resume, boards supply listings and a provider may supply draft text. The worker writes SQL and vectors. The local test ATS receives one approved packet and returns confirmation records. A real-board pilot stops before the submit control. Tracker records the outcome a person later reports; no employer system pushes status back into JobPilot.",
)
para(
    166,
    "The stored data has three shapes. SQL holds the shared corpus and account-owned decisions and cases. Chroma holds a rebuildable vector projection keyed by job, content version, model and dimension. Files under data/users/{account id}/ hold originals, tailored copies and evidence. An owner predicate applies to private rows; a resolved path check applies to files.",
)
para(
    168,
    "The project style was fixed before the code was written. A modular monolith suits a final-year project with one shared corpus and a worker that can run beside the API. The reason is operational simplicity: one database to migrate and one codebase to explain, with the worker separated where long-running work needs its own lifecycle.",
)
para(
    169,
    "A set of services was not adopted. Refresh and stored search finish on one machine, and splitting them would add deployment and failure modes without changing the result. The durable queue lives in the same database, but the claim path is written for both SQLite and PostgreSQL so a deployment can keep the same recovery behavior.",
)
para(
    170,
    "Business logic stays in code rather than prompts. A model writes text and is poor at counting, checking and remembering. The validator compares structured claims with the profile, the scorer applies fixed weights to numeric components, and the registry grants capabilities. The model cannot widen its own authority.",
)
para(
    171,
    "A workflow library is used where state and branching justify it. The application flow has approval, branch points and recovery, so it is a graph. Job search is a deterministic sequence of functions. Durable queueing and lease fencing are not supplied by the graph library; the database owns them.",
)
para(
    172,
    "SQLite keeps a student's deployment in a file; PostgreSQL is a documented option, not evidence of a production installation. Both run the same Alembic migrations. A recent revision adds per-application answers and the question plan stored with an approval, so the schema continues to follow workstreams without rewriting earlier revisions.",
)
para(
    173,
    "Authorization lives in the data layer. An accessor takes a scope built from the authenticated principal and applies the owner predicate before a row is materialized. A test walks routes for direct queries of user-scoped tables so a new route cannot quietly bypass the rule.",
)
para(
    174,
    "A foreign resource returns 404 with the same body as a missing one. A 403 would confirm that an identifier exists and belongs to somebody else. The same rule applies to private files and evidence: the decision is made from the authenticated scope, not from a value in the request.",
)
para(
    175,
    "The local EmbeddingGemma-2 model is the default because the earlier cloud embedding tier allowed twenty requests a day and a refresh handles thousands of listings. The local model runs on CPU with an 8,000-character input limit and batches of eight. The API provider remains an alternative in configuration, with its own usage limits.",
)
para(
    176,
    "The console stayed out of the runtime process. It has its own package, tests and build, so a screen change does not require a backend change. The API is the only contract both sides share.",
)
para(
    179,
    "The information domain has four kinds of record. The job corpus is shared and has no owner. Profiles, drafts, applications and answers belong to one account. Runs and work items describe outstanding work and carry an owner where a person requested them. Evidence records attach to an application and to a workflow attempt.",
)
para(
    180,
    "Every user-scoped table carries owner_id. The column is not null because a record without an owner cannot be read safely, and it is indexed because access always filters on it. Scoped accessors apply the filter before a row is read. Shared tables keep their source identifiers instead.",
)
para(
    181,
    "Vectors live in one Chroma collection in cosine space. The model identity and dimension are stored with the collection; opening it with a different configuration raises an error that explains how to rebuild. A query embedding is never persisted there.",
)
para(
    182,
    "The cache is a SQLite file keyed by the hash of model, dimension and corpus text. It makes a second refresh over unchanged listings cheap and holds corpus vectors only. A daily budget bounds new embedding work, and a run that reaches it leaves identifiable work for a later claim.",
)
para(
    183,
    "Figure 13 and Figure 14 split the relational schema because all tables with their columns do not fit on one readable page. The first shows account-owned records, including application answers and the question plan stored with an approval. The second shows the shared corpus and the run and application lifecycle tables.",
)
para(
    188,
    "Files follow accounts under data/users/{account id}/, with resumes, tailored drafts and evidence in separate directories. A resolved path must stay inside the caller's own directory. Directory separation is not encryption; backups and evidence files need the protection of the underlying storage.",
)

para(
    192,
    "The tables below describe the stored entities. Migrations add columns and tables in the order the workstreams were delivered, and each forward step is checked against an earlier database.",
)
para(
    194,
    "Three kinds of state sit outside the relational tables: the Chroma vector collection, the embedding cache and the private files under each account's directory. A missing vector lowers measurable semantic coverage; it does not remove a job row or invent an embedding.",
)

para(
    198,
    "The refresh touches every part of the system: sources, normalizer, deduplicator, spam screen, admission control, database, vector store and embedding provider. The API records the run and returns 202; the worker performs the steps below under a lease token. A failing source adds an error to the report and the run continues.",
)
para(
    221,
    "Two properties matter here. The budget counts cache misses rather than listings, so an unchanged corpus costs no new embeddings and a burst at the front of a board cannot starve later sources. An interrupted run can resume because completed work items settle separately.",
)
para(
    238,
    "The search never contacts a job source, so it has no source error or network failure path. The scorer divides the weighted sum by the weights of applicable components. A vector that is absent or unavailable lowers coverage, and the response says so. An explicit query for indexed jobs only excludes the rest.",
)
para(
    256,
    "The engine never reads the vector store; the semantic score arrives as an argument. The denominator contains the weights of applicable components. NOT_APPLICABLE removes a component; an unknown value keeps its weight and scores zero. The explanation is built from those distinctions rather than from the total alone.",
)
para(
    271,
    "A section missing from the resume yields an empty field and a warning. Preferences are recorded only when the document states them. A PDF without a text layer is refused because the project does not perform OCR.",
)
para(
    288,
    "The report names each removal and its reason, and the run still succeeds. Unsupported years and injected instructions are different cases: one contradicts the profile, the other is text treated as a command. Both are removed and reported.",
)
para(
    303,
    "No model is involved in ATS analysis. The score is a pure function of the tailored content, the profile, the listing and the rendered file. It is a local estimate of how a document reads, not a score returned by an employer's system.",
)
para(
    316,
    "The renderer omits a field it does not have. It writes only skills present in both the tailored content and the profile, and it uses dates from the profile. A file name is sanitized, with a hash appended when the sanitizing changed the identifier.",
)
para(
    318,
    "The application has five nodes and two branch points. The decision and the queued work are written together, so the worker can restore the packet that a person reviewed. The worker checks policy again before acting.",
)
para(
    342,
    "The verify node mirrors submit: it checks permission and downgrades the result to verification_failed when confirmation or an artifact is missing. On success it moves the case to VERIFIED. A missing outcome after a possible adapter call becomes submission.uncertain and needs human reconciliation.",
)
para(
    372,
    "A required field the system cannot ground is a question for a person, not a guess. The plan separates answered fields, skipped fields and fields that must be asked about. Saving an answer updates the plan verdict; it does not promise that a browser can operate the corresponding widget.",
)
para(
    378,
    "This is the whole authorization mechanism. Every accessor applies the owner predicate before a row is read, so a route cannot ask for another account's data by changing an identifier. Superuser scope is explicit and is checked at the same layer.",
)
para(
    379,
    "The scope comes from the authenticated principal. No route reads an account identifier from a body, header, query or path to decide ownership.",
)
para(
    408,
    "The purge is idempotent: a second run changes nothing. Audit rows are the deliberate exception to deletion; they are anonymized so that the action, outcome and time remain without the identity. The API process does not schedule the purge; an operator runs the script or an external scheduler does.",
)
para(
    419,
    "The allowlist match is exact or by sub-domain, so a host such as evil-greenhouse.io.attacker.com does not match greenhouse.io. An empty configuration allows nothing. Local addresses are allowed only in development, and browser navigation is rechecked against the same rule.",
)
para(
    430,
    "The temperature reaches the provider on each call, and both the client's and SDK's retry layers are controlled in one place. Usage records keep counts and durations, never the prompt, answer or key. The earlier SDK retry could make a call sleep past the client's timeout, so the behavior is tested directly.",
)
para(
    432, "Five limits bound what one caller can cost the system. Each refusal says what to do next."
)
para(
    434,
    "The heavy routes are refresh, search, tailoring and approval. The rate limiter keys on the transport peer address and ignores forwarded headers by default. A queued approval is bounded by the queue as well as by the request limit.",
)
para(
    436,
    "The console is a React application with a typed API client. It sends the browser's session cookie and echoes the CSRF cookie on unsafe requests. A failure leaves the last confirmed server state on screen. The current console includes Home, Resume, Profile, Account, Discover, Studio, Review, Tracker with a questions page, Activity and Operations.",
)
para(
    437,
    "Figure 16 shows who uses the system: the candidate, the scheduler that requests a refresh, and the maintainer who inspects runs and worker health. An administrator's visibility into runs does not carry approval rights over another account's packet.",
)
para(
    440,
    "Figure 17 is the console screen map. Navigation lives in the shell; a narrow screen uses a drawer. The map follows the work: inspect source data, discover a role, prepare documents, review a packet and follow its history. Activity and Operations sit outside that path.",
)
para(
    443,
    "The console holds no credential. It reads status from the API and does not show a success the server did not return. After approval it shows queued status and the run identifier, then later evidence or an uncertain result that needs a person.",
)
para(
    446,
    "The console is the whole human interface. Its screens answer the questions a person asks: what the agent read, what it found, what it wants from me and what happened to the applications.",
)
para(
    447,
    "Sign in. The console asks the server who the caller is and shows this screen when the answer is no.",
)
para(
    448,
    "Resume. The uploaded document, the document library and the parsed profile section by section, including fields the agent could not read.",
)
para(
    449,
    "Discover. Filters, ranked results and the eight component scores, with the matched and missing evidence behind each score.",
)
para(
    450,
    "Job detail. One listing in full, with what the agent made of it and a way to tailor a resume for it.",
)
para(
    451,
    "Studio. The job, the chosen document, the diff, the cover letter, the factuality and ATS reports, and the saved edits revalidated against the original.",
)
para(
    452,
    "Review. The packet, the stored questions and the decision. Answers can be saved before approval; the response after approval shows queued work and a run identifier.",
)
para(453, "Tracker. Applications by status, their history and the questions saved for each case.")
para(
    454, "Operations. Accepted runs, work counts, source errors and the last reported worker state."
)
para(
    455,
    "Two rules run through every screen. The console shows only what the server returned, and it pairs each status with the next action: queued work names its run, an uncertain result asks for review, and a later interview asks the person to record it.",
)
para(
    457,
    "The captures below come from a recorded run of the console against a development backend and corpus. They show implemented screens; some identifying details are covered. A capture is evidence of a screen at that time, not proof that an application reached an employer.",
)
para(
    486,
    "The matrix traces each functional requirement in the Software Requirements Specification to the component that satisfies it and the evidence that a reader can inspect. Identifiers are retained from Version 2.0; the design column names the current module. A test reference is a place to look, not a claim that the suite was run for this edition.",
)
para(
    488,
    "Non-functional requirements are traced in the same way. The offline evaluation fixture holds ranking numbers with its provider settings, the security tests hold isolation and refusal cases, and the durable-run tests hold queue and recovery behavior. Historical test counts belong to the dated record that reported them.",
)
para(
    492,
    "Every route the service exposes is listed here with the module that implements it. The route table test compares this list with the application, so a new route without a row fails the build. Recent routes cover per-application questions, tailored-document edits and worker inspection.",
)
para(
    497,
    "The security model, threat model and control register are in docs/SECURITY.md. The register names each control, the threat it mitigates, where it lives and the test that checks it.",
)
para(
    499,
    "The workstream documents in docs/implementation/ hold the plan and execution record. WS-32 records the approval boundary and live pilot; WS-45 records saved questions; WS-47 records Studio editing; WS-49 records the last sprint verification and what it left open.",
)

T = {
    "0": {"2|3": "Design updated for revision 7190151 (22 November 2026)."},
    "2": {
        "3|1": "A queued unit of work with a status, owner, attempts and events.",
        "4|1": "A per-item claim fenced by a token so an old worker cannot settle it.",
        "5|1": "A module that maps one external site to prepare, submit and verify capabilities.",
        "6|1": "The stored packet, payload and question plan a person reviews.",
        "8|1": "A score with explanation for one owned profile and one listing.",
        "19|1": "The local fake ATS, which is the only adapter with submit and verify permission.",
    },
    "3": {
        "1|1": "Relational table | The shared corpus of job listings, one row per canonical identifier.",
        "9|1": "Relational table | Saved answers keyed by application and question revision; owner scoped.",
        "10|1": "Relational table | Approval decisions with payload, approver and stored question plan.",
        "11|1": "Relational table | Durable runs and work items with leases, attempts and events.",
    },
    "4": {"5|1": "64 simultaneous requests | 503 with Retry-After, bounded by the queue"},
    "5": {
        "3|1": "Select filters or a result | The ranked list updates from stored data, with no board request.",
        "4|1": "Open a result | The detail shows eight component scores, matched evidence and gaps.",
        "5|1": "Open Studio and edit a section | Save rechecks factuality and ATS coverage, then writes a new deliverable.",
        "6|1": "Answer a stored question in Review | The answer is saved for that application and the blocker can clear.",
        "7|1": "Approve a packet | HTTP 202 with a run identifier; no submission is claimed.",
        "9|1": "Open a case question page | The saved plan and answers are read without contacting the employer.",
    },
    "6": {
        "1|1": "FR-1.1 to FR-1.9 | src/api/routes/resumes.py, src/resume/, src/db/ | tests/test_resumes_api.py, tests/test_resume_parser.py",
        "2|1": "FR-2.1 to FR-2.15 | src/jobs/, src/graph/job_executor.py, src/db/ | tests/test_jobs.py, tests/test_durable_queue.py",
        "3|1": "FR-3.1 to FR-3.11 | src/matching/, src/graph/job_executor.py | tests/test_matching.py, tests/test_jobs_api.py",
        "5|1": "FR-5.1 to FR-5.17 | src/applications/, src/runs/ | tests/test_application_workflow.py, tests/test_ws32_durable_submission.py",
        "6|1": "FR-6.1 to FR-6.7 | src/db/applications.py, src/api/routes/tracking.py | tests/test_tracking_api.py, tests/test_ws45_answers.py",
        "8|1": "FR-8.1 to FR-8.12 | src/auth/, src/api/routes/auth.py | tests/test_auth.py",
        "11|1": "FR-11.1 to FR-11.12 | frontend/src/ | frontend/src/screens/*.test.tsx, frontend/e2e/",
        "12|1": "FR-12.1 to FR-12.12 | src/api/middleware.py, src/security/ | tests/test_ws12_hardening.py, tests/test_ws15_hardening.py",
    },
    "8": {
        "1|1": "/resume | Resume and document library | frontend/src/screens/resume-screen.tsx",
        "2|1": "/matches | Discover | frontend/src/screens/matches-screen.tsx",
        "3|1": "/app/profile | Profile | frontend/src/screens/profile-screen.tsx",
        "4|1": "/app/account | Account and model credentials | frontend/src/screens/account-screen.tsx",
        "5|1": "/approvals | Review | frontend/src/screens/approvals-screen.tsx",
        "6|1": "/tracker | Tracker | frontend/src/screens/tracker-screen.tsx",
        "7|1": "/tracker/:applicationId/questions | Case questions | frontend/src/screens/question-page.tsx",
        "8|1": "/activity | Activity | frontend/src/screens/activity-screen.tsx",
        "9|1": "/operations | Operations | frontend/src/screens/operations-screen.tsx",
    },
}

out = {"paragraphs": P, "tables": T}
Path(".scratch/fyp-20261125/edits").mkdir(parents=True, exist_ok=True)
Path(".scratch/fyp-20261125/edits/sdd-edits.json").write_text(
    json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
)
print("SDD edits:", len(P), "paragraphs,", sum(len(v) for v in T.values()), "cells")
