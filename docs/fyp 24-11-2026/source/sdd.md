# 1 Introduction

## 1.1 Purpose and scope

JobPilot helps a candidate decide which jobs to pursue and what information to send. This software design description covers commit `7190151`, dated 22 November 2026. It describes the React console, the Python service and worker, and the records that connect a candidate's source document to an application decision. The design stops at a different point for a real employer than it does for the local test employer.

A match is a recommendation. A prepared application is a packet for review. Approval authorizes work on that packet; it does not establish that an employer received it. The local fake applicant tracking system (ATS) supports a complete submission and verification exercise. On a real board the pilot has permission to prepare only. The evidence for that distinction is given in sections 5.6 and 8.3.

# 2 System overview

## 2.1 People, inputs and decisions

The candidate uploads a résumé, checks the extracted facts, and supplies answers that the document cannot establish. A corpus refresh collects publicly available postings independently of any one candidate. Discover ranks those stored postings for a selected profile. The candidate can open a result in Studio, review a proposed change against the original, and prepare a packet. A separate decision records who approved or rejected it. If an interview or offer follows, a person records that outcome in Tracker.

An administrator looks after the shared corpus and worker, including recovery after an interruption. The administrator's queue controls do not confer the ability to make an application decision in another candidate's name. Job boards supply listing and form data. A configured language model helps extract listing facts and draft text; it has no authority to grant approval, report an employer decision or operate a browser.

## 2.2 Design choices

The system keeps one shared copy of a posting and private records of each candidate's matches. This lets two people search the same corpus without sharing a résumé or a search history. Fetching and ranking are separate operations: a search can proceed while a board is down, although its results are only as current as the stored listings. Keeping source facts separate from drafts also gives the reviewer something independent against which to check a proposed claim.

# 3 System architecture

## 3.1 Package boundaries

The backend is a modular monolith. The HTTP routes obtain the caller's identity and validate requests. Domain packages implement parsing, matching, drafting and form preparation. The database package supplies access to stored records; the security package supplies checks that both routes and workers can call. Keeping the adapter registry outside the route layer lets the API select an adapter by URL and the worker resolve the same adapter by its recorded name.

@figure packages

## 3.2 Runtime components

FastAPI serves requests. Short operations, such as reading a profile or ranking stored jobs, return a result directly. A refresh or approved submission returns a durable run identifier; another process performs the work. LangGraph expresses the job-processing stages and the branches of the application workflow. It does not provide the durable worker queue. SQL records which work remains even after the request, browser tab or worker process ends.

@figure components

## 3.3 Deployment and trust boundaries

The React application runs in the operator's browser and calls the API over HTTP. The API and the separately supervised worker share the relational database and configured data directories. The repository supports SQLite for local use and a PostgreSQL queue claim path. In the queued deployment the worker writes the Chroma job index and search reads it. A worker may also open an isolated Playwright browser context. This is the Python runtime client; development tools used to inspect a screen do not participate in an application run.

@figure deployment

Browser sessions use an HttpOnly cookie; state-changing cookie-authenticated requests require the matching CSRF token. Scripts can use the separate bearer-token transport. The server derives the user scope from the authenticated principal. For private resources an ordinary caller gets the same not-found response for a foreign identifier as for a missing one. A file download also requires an allowed, resolved path: knowledge of a document identifier or filename alone grants no access.

Listings, uploaded text and form labels are untrusted input. Model prompts delimit untrusted content, mask identifying information where applicable and validate structured output. Outbound requests and browser navigation have destination checks; an unexpected destination or a CAPTCHA or MFA challenge stops the browser flow. Request-size, concurrency, rate and work limits bound what a caller can trigger. These controls reduce exposure; text filtering does not certify the truth of a posting or every sentence a model writes.

# 4 Data design

## 4.1 Domain objects and provenance

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
| `users` | `id` string; `hashed_password` string | Account identity and password verifier |
| `access_tokens` | `user_id` string | Server-side session belongs to this account |
| `candidate_profiles` | `profile_json`, `application_json` JSON | Parsed facts and separately confirmed answers |
| `candidate_eeo` | `profile_id` string; `data` JSON | Isolated voluntary equal-opportunity selections |
| `llm_credentials` | `owner_id` key; `encrypted_key` string | One stored provider credential per account |
| `jobs` | `id` string; `content_version` string | Canonical listing and its content revision |
| `job_boards` | `slug` string; `last_ok_at` datetime | Board identity and last successful contact |
| `form_questions` | `label` string; `times_seen` integer | Board question and observation count, not an answer |
| `visa_sponsors` | `name_normalized`, `country` strings | Employer register entry; not a promise for a role |
| `job_matches` | `profile_id`, `job_id` strings; `scores` JSON | Owner's recorded match for a listing |
| `tailored_resumes` | `tailored` JSON; `edited_at` datetime | Draft content and time of a saved edit |

@figure account-erd

## 4.3 Data dictionary: decisions, evidence and work

The approval identifier addresses a decision. The application identifier addresses a history and its answers. A workflow or correlation identifier connects related actions across components; an individual work item's lease token identifies a particular worker claim. None of these identifiers substitutes for the authenticated account.

| Record | Selected field and type | Meaning |
| --- | --- | --- |
| `approval_requests` | `payload`, `form_questions` JSON | Prepared packet and its question plan |
| `approval_requests` | `expires_at` datetime; `profile_version` string | Review window and digest of prepared facts |
| `applications` | `approval_id`, `status` strings | Tracked case and current lifecycle stage |
| `application_answers` | `question_key`, `answer_text` strings | Upsert by owner, application and question |
| `application_events` | `actor`, `from_status`, `to_status` strings | Attributed history, ordered by event ID |
| `application_evidence` | `workflow_id`, `screenshot_path`, `trace_path` strings | Attempt evidence and artifact references |
| `audit_events` | `actor_kind`, `actor_id`, `action`, `outcome` strings | Attributable operational or security action |
| `job_runs` | `status` string; item counters integers | Work accepted and checkpointed in SQL |
| `job_work_items` | `lease_token` string; `next_attempt_at` datetime | Current claim and retry eligibility |
| `job_run_events` | `run_id`, `event` strings; `at` datetime | Run history, including recovery |
| `worker_heartbeats` | `last_heartbeat_at` datetime | Last evidence that the process checked in |
| `circuit_breakers` | `name`, `state` strings | Shared dependency state when configured |

@figure workflow-erd

## 4.4 Storage, access and retention

SQL is authoritative for listings, decisions and outstanding work. Chroma holds a rebuildable projection identified by job, content hash and embedding model identity. A missing vector reduces what search can measure; it does not delete the job. Conversely, a leftover vector cannot create a listing. Reconciliation compares the two stores because a SQL commit and a vector write cannot form one database transaction.

@figure storage

New uploads, tailored copies and evidence files live under `data/users/{user_id}/`, in `resumes`, `tailored` and `evidence` respectively. The original remains available when Studio writes a deliverable. Production operators must protect the underlying storage and backups: directory separation is not disk encryption, and screenshots and traces may contain personal information. The scheduled purge in `src/retention.py` and `scripts/purge_expired.py` enforces configured retention windows and anonymizes retained audit records on account purge. The API process does not schedule that task itself.

# 5 Component design

## 5.1 Intake and information flow

The upload path checks type, size and file structure, assigns a server-side name and parses the document into sections. The parser supports DOCX, TXT, Markdown and PDFs with a readable text layer. A scan without text, a password-protected PDF, a broken text encoding and an unreadable file produce distinct refusals. Other missing résumé sections remain empty and validation can return warnings. An operator can correct confirmed application answers without rewriting what the source document said.

@figure data-flow

## 5.2 Refresh acceptance and worker ownership

`POST /api/jobs/refresh` accepts background work and returns HTTP 202. An active refresh can satisfy a repeated request because the corpus is shared. The run's `owner_id` identifies the requester; scheduled platform runs may have no user owner. Ordinary users can inspect their own runs. The worker's `lease_owner` identifies a process temporarily entitled to do work, not a person entitled to read another user's data.

@figure refresh-sequence

A worker claims eligible items in priority order. PostgreSQL skips rows locked by another claimant; SQLite uses a conditional update and checks whether it changed the row. Each successful claim gets a fresh token. Renewal and settlement use that token, so an old worker cannot overwrite a result after another worker takes the item. If a lease expires with unfinished work, the reaper can mark the run `RECOVERABLE`. An administrator can resume outstanding items without repeating completed embeddings. Retryable failures have a next-attempt time; permanent failures and exhausted budgets remain visible in run state.

## 5.3 Listing admission and indexing

Refresh reads the configured Greenhouse, Lever, Ashby and Remotive sources through guarded clients. It records errors per source, drops incomplete listings and screens the batch before spending embedding resources. Within one source, deduplication prefers its job identifier, then its application URL, then title and company. A separate cross-source pass compares normalized company, title and location and keeps the first source's canonical identity. Matching by title alone would merge distinct vacancies at different locations.

@figure refresh-activity

For admitted changes, the worker commits the listing and its planned embedding work together. A work item's identity includes the run, job, work type, content hash, model and dimension. The embedding handler upserts the vector and checks the stored version before marking the item complete. If it dies after the vector write, repeating that write under the same job identity is safe. If Chroma is unavailable, SQL can retain the job and record the outstanding work. That recovery rule is suitable for indexing; it would be unsafe for sending an application.

## 5.4 Store-only matching

`search_stored_jobs` in `src/graph/job_executor.py` ranks SQL listings for a stored profile. It makes no job-board request. Query tokens, location and workplace narrow the candidate set before ranking. The lexical index uses the full corpus for its term statistics, so narrowing a location does not redefine a keyword's rarity. The engine computes numeric scores for eligible listings, orders by descending score then job ID, and builds full explanations only for the returned slice. The API stores returned matches under the caller's profile.

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

The names and defaults come from `src/matching/weights.py`. `src/matching/scores.py` divides the weighted score sum by the sum of applicable weights. An unknown component earns zero but keeps its weight; only `NOT_APPLICABLE` leaves the denominator. For example, with all eight applicable, a job with a missing vector can earn at most 87 out of 100 even if the other seven score 100. `evidence_coverage` is the measured share of the counted weight. A low measurement and an unknown value can therefore be distinguished in the explanation.

The skill scorer gives a preferred skill half the weight of a required one and dampens very short lists. The experience scorer counts overlapping dated intervals once. A classified role mismatch that triggers the cap limits the blended score to 25; the result reports that cap. With no usable vector, the default search keeps the job, distinguishes pending from unavailable embeddings and reports reduced semantic coverage. A caller may explicitly request indexed jobs only. A sponsorship-register finding is separate evidence; voluntary equal-opportunity data never enters the score.

## 5.5 Preparation, approval and execution

Preparation checks the target and adapter, confines any résumé path to the caller's storage, and builds a packet from supplied inputs and grounded facts. It stores the question plan with the approval so Review can display the questions this packet actually used, even if the employer changes the form. The row carries a fact digest and an expiry. Re-preparing for the same owner and job URL can carry forward eligible saved answers. No browser submission follows from preparing or saving an answer.

@figure approval-sequence

The decision endpoint resolves the approver from the session, loads the owned pending record and checks expiry, policy and posting liveness where supported. A known closed posting blocks approval; an unreachable board is not proof of closure. The approve path commits the decision and queued work together. If the queue is full, it rolls back and the approval stays pending. A 202 response gives the caller a run ID. Rejecting the packet records a decision without enqueuing submission.

The worker restores the reviewed payload and checks the submission policy again at execution. `PREPARE_ONLY` forbids execution and `AUTO_SUBMIT` is unavailable. Under `REQUIRE_APPROVAL`, only `fake-ats-playwright` has both `SUBMIT` and `VERIFY`. The fake adapter reads accessible labels and roles in a fresh context, uses grounded answers, and checks the confirmation page. It collects a screenshot and traces; a missing required artifact or an unrecognized confirmation prevents a verified result. Verification here establishes a fixture outcome, not an employer response.

Before calling the adapter the worker commits an attempt marker. If a stored outcome already exists, recovery uses that outcome. If the marker exists but the outcome does not, recovery records `submission.uncertain` for human investigation rather than sending again. The database cannot determine whether a remote system acted during that interval. This is a limit on replay, not a guarantee of exactly-once delivery across systems.

## 5.6 Real-board preparation boundary

The normal Greenhouse and Lever application adapters can prepare but cannot submit. The separately invoked `assist-playwright` pilot also has only `PREPARE`. Its intended handover leaves a filled browser for the human and returns `awaiting_human_submit` with success false. Unknown controls can stop the walk earlier; a challenge stops it rather than being solved. A Greenhouse contract check can identify missing required values before proceeding. It cannot certify what the live board will accept or recognize its confirmation page.

The 15 November 2026 pilot illustrates the distinction. The unmodified pilot stopped at `needs_human` before typing. On the Cloudflare form a separate instrumented pass through the same fill routine filled four fields with the shipped label lookup and nine after stripping a trailing required-field asterisk. Across seven live forms the planner left 11 to 25 controls unresolved. No one pressed Submit; employer acceptance and post-submit verification were not measured. The separate records are identified in section 8.3.

## 5.7 Drafting, editing and validation

The tailoring pipeline takes a stored job and an owned profile. Research draws facts from listing text and filters proposed facts for grounding; it does not fetch arbitrary company URLs. A model proposes wording. The validator compares structured claims with the profile, for example removing an unknown employer or a skill absent from the source and reporting the removal. A reported violation can accompany HTTP 200: the returned document contains the cleaned result. A provider failure is a separate error and supplies no replacement draft. These checks catch specified discrepancies; they are not independent verification of every sentence.

@figure tailoring-activity

The renderer prefers to edit a copy of the source document in its supported format. If it cannot, it generates a new document and records `regenerated` and the reason. ATS analysis inspects the actual deliverable for keyword coverage, sections, title alignment and format risks. This is a local estimate, not an external ATS score. Saving section edits repeats factuality checks, rendering and ATS analysis against the stored profile and job, without asking a model to approve the edit. It updates the draft's reports and `edited_at`, not the source upload.

# 6 Human interface design

## 6.1 Navigation and dashboard

The public landing page and sign-in sit outside `/app`. The authenticated shell keeps the current task in view across its desktop navigation and smaller-screen drawer. Navigation follows the candidate's work: inspect source data, discover a role, prepare documents, review a packet and follow its history. Activity and Operations are separate from those decisions; administrative controls also require server authorization.

@figure nav

The dashboard shows a featured match and shortlist when stored match history supplies them, server totals for application stages, recent activity and specific items needing attention. A count for a stage comes from a filtered server total, not the length of the displayed page. An unreadable source is shown as unavailable or retryable rather than as zero work outstanding. A new candidate can start with a résumé instead of being shown sample matches.

## 6.2 Profile, documents and Account

Profile separates Documents, Application answers and Work preferences. The library pages through originals and tailored copies; the operator can inspect parsed source facts independently of later choices. A candidate can confirm target roles and eligibility by country. Sponsorship is an explicit answer, not an inference from a name or location. Voluntary equal employment opportunity (EEO) selections have a separate opt-in and deletion path.

Account, reachable from the account menu, separates identity, model credentials and privacy. Saving a personal model key yields a masked state; testing the connection is a separate provider call. A failing personal key does not quietly shift the call to the platform's account. The baseline Account screen has no Sessions tab, although the identity API has session-management routes.

## 6.3 Discover and job detail

Discover selects the highest-ranked result by default when there is no existing selection. A location list comes from the corpus, and workplace filters apply before the server's top-result limit. On a wide screen, results and details occupy separate panes. The selected listing exposes the score breakdown, matched and missing evidence and any sponsorship finding before the operator moves to Studio. Missing listing fields remain unknown. The source timestamp describes corpus freshness; opening a result does not contact the employer to establish that the vacancy is still open.

@plate discover

## 6.4 Studio and Review

Studio keeps the original, proposed wording, cover-letter view and validation evidence alongside the chosen job. The diff lets the candidate inspect or edit a section and decide whether to save it. The keyword panel separates terms evidenced by the source from gaps. A render report indicating a regenerated document is a reason to inspect layout before downloading; it is not a claim that the source formatting survived.

Review shows the packet, its document choice and the employer's questions in board order. It distinguishes confirmed facts, answers supplied by the person, questions needing an answer and fields reserved for the employer's site. A blocking question disables the authorization control. The person can save an eligible answer, inspect its updated verdict, and prepare again when the packet needs to include changed facts. Approval and rejection are explicit actions. After acceptance the console displays queued work and its run ID, not a submission receipt.

@plate review

## 6.5 Tracker and application questions

Tracker offers board, list and timeline views of recorded applications. Its four board columns group lifecycle values; they are not additional statuses. Awaiting review groups `prepared` and `awaiting_approval`. In progress holds `submitted`, pending verification. Needs you holds `verified`: there is evidence of submission and the next information must come from the person. Outcome recorded contains `interview`, `offer`, `rejected` and `withdrawn`. The transition rules require a human actor for those outcomes. A recorded rejection can be a person's decision against proceeding; its event history explains who acted.

Application detail links to evidence and to that application's questions. The questions page reads the plan saved with the packet and folds in saved answers, without fetching a different employer form. An eligible human answer can change `needs_human` to `answerable` with `answer_from` set to `you`. EEO and attestations have no answer control here; the API refuses an attempted save with 422. An answer that clears a question in Review does not guarantee that a browser can operate the corresponding widget.

## 6.6 Activity, Operations and Administration

Activity presents the account's attributed audit trail. Operations shows accepted runs, item counts, errors and the last reported worker state. Both use polling. If work is queued with no active worker, the useful action is to start or restore the worker, not to approve or request the job repeatedly. Administration provides platform run and worker inspection and authorized recovery. Liveness asks whether the API process is present; readiness checks the database and reports worker health. A responsive API alone is not evidence that queued work is progressing.

# 7 Requirements matrix

The identifiers below refer to the same requirements as the SRS. A design or test reference identifies where to inspect a control; it does not turn an unexecuted live scenario into a verified result. In particular, evidence about the local ATS must be interpreted within that test boundary.

@trace

# 8 Appendices

## 8.1 Console route index

These are the named screen paths in `frontend/src/routes.tsx` at the baseline. A colon introduces a path parameter. An unmatched path redirects to `/`.

| Purpose | Console paths |
| --- | --- |
| Public entry | `/`, `/sign-in` |
| Dashboard and intake | `/app`, `/app/resume` |
| Profile and Account | `/app/profile`, `/app/account` |
| Discover and detail | `/app/matches`, `/app/matches/:jobId` |
| Studio and job draft | `/app/tailor`, `/app/tailor/:jobId` |
| Review | `/app/approvals` |
| Tracker and case | `/app/tracker`, `/app/tracker/:applicationId` |
| Case questions | `/app/tracker/:applicationId/questions` |
| Activity and operations | `/app/activity`, `/app/operations`, `/app/admin` |

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

## 8.3 Technical references and dated evidence

For operating and deployment decisions, consult `docs/ARCHITECTURE.md`, `docs/SECURITY.md` and `docs/RUNBOOK.md` at `7190151`. The table and column definitions are in `src/db/` and `migrations/versions/`; revision `d3e4f5a6b7c8` adds the approval's stored question plan. Representative implementation tests are `tests/test_tenant_isolation_api.py` for scoped access, `tests/test_durable_queue.py` and `tests/test_worker_recovery.py` for claims and recovery, and `tests/test_ws32_durable_submission.py` for submission replay. `tests/test_ws45_questions_page.py` covers the saved plan; `tests/test_tailored_edit.py` covers revalidation after an edit.

The 21 October 2026 browser record in `docs/implementation/08-browser-automation.md` reports 25 of 25 checks against the controlled fake ATS. It exercised a real browser against local forms. The WS-21 ranking evaluation of 8 November 2026, recorded in `docs/evaluations/ws21-report.md`, used five profiles, 29 listings, six tailoring pairs, canned drafts and a lexical stand-in for semantic embeddings. It measured nDCG at ten of 0.8240 and precision at five of 0.4000. Neither number measures a live model's accuracy or a candidate's chance of an interview.

For the 15 November 2026 live pilot, `docs/evaluations/ws32-pilot-2026-11-15/01_pilot_as_is.json` records the early stop; `02_fill_star_normalised.json` in that directory records the instrumented fill. `03_liveness.json` records three closed postings among twelve probed, despite a final HTTP 200 after redirection. `04_planner_unresolved.json` records the seven-form planner comparison. The interpretation and outstanding confirmation check are in `docs/implementation/32-submission-readiness.md`, section 5.5.

On 21 November 2026, `docs/implementation/49-sprint-cleanup-and-ledger.md` recorded an isolated API, database copy, console and fake ATS. Saving an answer returned 200 and cleared the recorded sponsorship blocker; an EEO answer returned 422 and a cookie-authenticated write without the CSRF header returned 403. The automated layout sweep passed its checks in 84 of 84 surface and viewport combinations. The ledger reports 407 passing frontend tests and a backend result of 2,256 passed, eight skipped and 16 failed, attributing the failures to DNS resolution in `tests/test_jobs.py`. The long smoke journey and suggestions specification were not reverified to green; manual frame comparison, the per-screen state matrix and keyboard focus return remained open. These are dated observations, not a claim about a later checkout or a full accessibility assessment.

## 8.4 Internal composition of execution

The worker's internal parts divide claiming, dispatch, handling and settlement. For an application run, the handler resolves the approved packet and adapter; for an embedding run it resolves a job version and projection. Both return to lease-checked settlement. Only the application handler must first establish whether a previous attempt could already have reached its destination.

@figure composite

## 8.5 Communication for a fake-ATS approval

The numbered messages follow one authorized local run. The decision write and enqueue precede the response to the browser. Worker messages then cross the adapter boundary; later reads obtain run state and evidence. The message numbers distinguish the caller’s 202 response from the worker’s later evidence record. Once the queue transaction commits, the API need not wait for the worker; the caller and worker can continue independently.

@figure communication

## 8.6 Interaction overview

Preparation, human decision, execution and observation can occur in different sessions. Rejection ends the decision path without a worker submission. An accepted fake-ATS run leads to observation of its result; a live assist handover leaves the irreversible action with the person. Returning to Tracker is an observation, not another execution request.

@figure interaction-overview

## 8.7 Claim and lease timing

The timing view uses ordinal positions, not measured seconds. A first claim obtains a token; expiry and recovery can make the item eligible for a new claim. Once a second token is current, settlement carrying the first token cannot advance the checkpoint. The intervals in this view set no performance target or lease duration.

@figure timing

## 8.8 Local modeling conventions

The stereotypes in this profile are documentary labels for roles within JobPilot. They help distinguish, for example, a boundary that receives a request from a component that enforces policy or stores evidence. They are local to these diagrams. A stereotype neither grants a runtime capability nor establishes that a security control passed a test.

@figure profile
