export interface paths {
  "/": {
    parameters: {
      query?: never
      header?: never
      path?: never
      cookie?: never
    }
    /** Root */
    get: operations["root__get"]
    put?: never
    post?: never
    delete?: never
    options?: never
    head?: never
    patch?: never
    trace?: never
  }
  "/api/applications": {
    parameters: {
      query?: never
      header?: never
      path?: never
      cookie?: never
    }
    /**
     * List Applications
     * @description List the tracked applications, newest first.
     *
     *     Only the caller's own applications are listed. The listing and the
     *     total both go through the scoped accessors, so a total that counted
     *     other users' rows — and a list that showed them — are both
     *     impossible by construction rather than by a check somebody has to
     *     remember.
     *
     *     Args:
     *         db: The request-scoped database session.
     *         scope: The caller's access scope.
     *         status: Filter by one or more statuses (repeat the parameter, or
     *             pass a comma-separated list).
     *         profile_id: Filter by the candidate profile.
     *         limit: The page size (at most 200).
     *         offset: How many applications to skip.
     *
     *     Returns:
     *         The page of applications and the total number that matched.
     */
    get: operations["list_applications_api_applications_get"]
    put?: never
    post?: never
    delete?: never
    options?: never
    head?: never
    patch?: never
    trace?: never
  }
  "/api/applications/{application_id}": {
    parameters: {
      query?: never
      header?: never
      path?: never
      cookie?: never
    }
    /**
     * Get Application
     * @description Return a tracked application with its full history.
     *
     *     Raises:
     *         HTTPException 404: the application is unknown.
     */
    get: operations["get_application_api_applications__application_id__get"]
    put?: never
    post?: never
    delete?: never
    options?: never
    head?: never
    patch?: never
    trace?: never
  }
  "/api/applications/{application_id}/evidence": {
    parameters: {
      query?: never
      header?: never
      path?: never
      cookie?: never
    }
    /**
     * List Application Evidence
     * @description The evidence records of one tracked application.
     *
     *     The evidence rows are the record of what happened: the confirmation text
     *     the page showed, the status the adapter reported, and the paths of the
     *     artifacts. The tracking API answers with the application's *history*, not
     *     with its evidence, so the console cannot show a past submission's
     *     confirmation text without this.
     *
     *     Args:
     *         application_id: The tracked application.
     *         db: The request-scoped database session.
     *         scope: The caller's access scope.
     *
     *     Returns:
     *         The evidence records, newest first.
     *
     *     Raises:
     *         HTTPException 404: The application is unknown.
     */
    get: operations["list_application_evidence_api_applications__application_id__evidence_get"]
    put?: never
    post?: never
    delete?: never
    options?: never
    head?: never
    patch?: never
    trace?: never
  }
  "/api/applications/{application_id}/evidence/{filename}": {
    parameters: {
      query?: never
      header?: never
      path?: never
      cookie?: never
    }
    /**
     * Download Evidence
     * @description Download one evidence artifact of a tracked application.
     *
     *     Args:
     *         application_id: The tracked application the artifact belongs to.
     *         filename: The artifact's file name (the screenshot or the trace).
     *         db: The request-scoped database session.
     *
     *     Returns:
     *         The artifact file.
     *
     *     Raises:
     *         HTTPException 400: The file name is not a plain file name.
     *         HTTPException 404: The application, or the artifact, is unknown.
     */
    get: operations["download_evidence_api_applications__application_id__evidence__filename__get"]
    put?: never
    post?: never
    delete?: never
    options?: never
    head?: never
    patch?: never
    trace?: never
  }
  "/api/applications/{application_id}/status": {
    parameters: {
      query?: never
      header?: never
      path?: never
      cookie?: never
    }
    get?: never
    put?: never
    post?: never
    delete?: never
    options?: never
    head?: never
    /**
     * Update Application Status
     * @description Record a human outcome on a tracked application.
     *
     *     The status machine decides whether the move is legal, and the actor rule
     *     decides whether the caller may make it: a human outcome needs a human
     *     identity, so the agent can never record an offer it was not told about.
     *
     *     Args:
     *         application_id: The application to move.
     *         req: The status, the actor, and an optional note.
     *         db: The request-scoped database session.
     *
     *     Returns:
     *         The updated application, with its history.
     *
     *     Raises:
     *         HTTPException 400: the status is not a known status.
     *         HTTPException 403: the actor may not set this status.
     *         HTTPException 404: the application is unknown.
     *         HTTPException 409: the move is not a legal transition.
     */
    patch: operations["update_application_status_api_applications__application_id__status_patch"]
    trace?: never
  }
  "/api/applications/{approval_id}/approve": {
    parameters: {
      query?: never
      header?: never
      path?: never
      cookie?: never
    }
    get?: never
    put?: never
    /**
     * Approve Application
     * @description Approve a prepared application and execute it.
     *
     *     The decision is recorded with the approver's identity and the time. The
     *     payload that is executed is the persisted one.
     *
     *     Args:
     *         approval_id: The approval request to approve.
     *         req: The decision (approver identity and optional reason).
     *         db: The request-scoped database session.
     *
     *     Returns:
     *         The result of the execution, with its evidence.
     *
     *     Raises:
     *         HTTPException 403: The policy forbids executing the application.
     *         HTTPException 404: The approval request is unknown.
     *         HTTPException 409: The request was already decided.
     */
    post: operations["approve_application_api_applications__approval_id__approve_post"]
    delete?: never
    options?: never
    head?: never
    patch?: never
    trace?: never
  }
  "/api/applications/{approval_id}/reject": {
    parameters: {
      query?: never
      header?: never
      path?: never
      cookie?: never
    }
    get?: never
    put?: never
    /**
     * Reject Application
     * @description Reject a prepared application. Nothing is submitted.
     *
     *     Args:
     *         approval_id: The approval request to reject.
     *         req: The decision (approver identity and optional reason).
     *         db: The request-scoped database session.
     *
     *     Returns:
     *         A response describing the rejection.
     *
     *     Raises:
     *         HTTPException 404: The approval request is unknown.
     *         HTTPException 409: The request was already decided.
     */
    post: operations["reject_application_api_applications__approval_id__reject_post"]
    delete?: never
    options?: never
    head?: never
    patch?: never
    trace?: never
  }
  "/api/applications/approvals/{approval_id}": {
    parameters: {
      query?: never
      header?: never
      path?: never
      cookie?: never
    }
    /**
     * Get Approval
     * @description Return the stored state of an approval request.
     *
     *     The path is ``/approvals/{id}`` because ``/api/applications/{id}`` is the
     *     *tracked application* (WS-07). Two different resources cannot share one
     *     path shape.
     */
    get: operations["get_approval_api_applications_approvals__approval_id__get"]
    put?: never
    post?: never
    delete?: never
    options?: never
    head?: never
    patch?: never
    trace?: never
  }
  "/api/applications/prepare": {
    parameters: {
      query?: never
      header?: never
      path?: never
      cookie?: never
    }
    get?: never
    put?: never
    /**
     * Prepare Application
     * @description Prepare an application and record it for human approval.
     *
     *     Nothing is submitted by this call. The prepared payload is persisted as an
     *     approval request so that the approval decision and the submitted payload
     *     are the same thing.
     *
     *     Args:
     *         req: The application details.
     *         db: The request-scoped database session.
     *
     *     Returns:
     *         The approval id, the workflow id, and a summary of what will be
     *         submitted.
     *
     *     Raises:
     *         HTTPException 400: The URL is not on the domain allowlist, or no
     *             adapter supports it.
     *         HTTPException 403: The configured policy forbids the operation.
     */
    post: operations["prepare_application_api_applications_prepare_post"]
    delete?: never
    options?: never
    head?: never
    patch?: never
    trace?: never
  }
  "/api/audit": {
    parameters: {
      query?: never
      header?: never
      path?: never
      cookie?: never
    }
    /**
     * List Audit Events
     * @description The caller's own audit rows, newest first.
     *
     *     Args:
     *         db: The request-scoped database session.
     *         scope: The caller's access scope.
     *         limit: How many rows to return (at most 500).
     *
     *     Returns:
     *         The rows, and how many there are.
     */
    get: operations["list_audit_events_api_audit_get"]
    put?: never
    post?: never
    delete?: never
    options?: never
    head?: never
    patch?: never
    trace?: never
  }
  "/api/auth/cookie/login": {
    parameters: {
      query?: never
      header?: never
      path?: never
      cookie?: never
    }
    get?: never
    put?: never
    /** Auth:Cookie.Login */
    post: operations["auth_cookie_login_api_auth_cookie_login_post"]
    delete?: never
    options?: never
    head?: never
    patch?: never
    trace?: never
  }
  "/api/auth/cookie/logout": {
    parameters: {
      query?: never
      header?: never
      path?: never
      cookie?: never
    }
    get?: never
    put?: never
    /** Auth:Cookie.Logout */
    post: operations["auth_cookie_logout_api_auth_cookie_logout_post"]
    delete?: never
    options?: never
    head?: never
    patch?: never
    trace?: never
  }
  "/api/auth/forgot-password": {
    parameters: {
      query?: never
      header?: never
      path?: never
      cookie?: never
    }
    get?: never
    put?: never
    /** Reset:Forgot Password */
    post: operations["reset_forgot_password_api_auth_forgot_password_post"]
    delete?: never
    options?: never
    head?: never
    patch?: never
    trace?: never
  }
  "/api/auth/me": {
    parameters: {
      query?: never
      header?: never
      path?: never
      cookie?: never
    }
    /**
     * Read Me
     * @description The authenticated principal.
     *
     *     This is the endpoint that turns "the caller is anonymous" into "the
     *     caller is somebody", and it is the one the console calls first.
     */
    get: operations["read_me_api_auth_me_get"]
    put?: never
    post?: never
    /**
     * Request Account Deletion
     * @description Request the deletion of the caller's account.
     *
     *     **This is the reversible half.** The account is deactivated and every
     *     session is ended, so it cannot authenticate and cannot resolve its
     *     resources any more. The irreversible half — the purge of the rows
     *     and the files — is Phase D's job, and it is deliberately not done
     *     from an HTTP request: a purge that runs on a click is a purge that
     *     runs on a mistake.
     */
    delete: operations["request_account_deletion_api_auth_me_delete"]
    options?: never
    head?: never
    /**
     * Update Me
     * @description Change the caller's own e-mail, password or display name.
     *
     *     A password change ends the caller's **other** sessions: the session
     *     the change was made from stays, every other one goes. That is the
     *     point of changing a password.
     */
    patch: operations["update_me_api_auth_me_patch"]
    trace?: never
  }
  "/api/auth/register": {
    parameters: {
      query?: never
      header?: never
      path?: never
      cookie?: never
    }
    get?: never
    put?: never
    /** Register:Register */
    post: operations["register_register_api_auth_register_post"]
    delete?: never
    options?: never
    head?: never
    patch?: never
    trace?: never
  }
  "/api/auth/request-verify-token": {
    parameters: {
      query?: never
      header?: never
      path?: never
      cookie?: never
    }
    get?: never
    put?: never
    /** Verify:Request-Token */
    post: operations["verify_request_token_api_auth_request_verify_token_post"]
    delete?: never
    options?: never
    head?: never
    patch?: never
    trace?: never
  }
  "/api/auth/reset-password": {
    parameters: {
      query?: never
      header?: never
      path?: never
      cookie?: never
    }
    get?: never
    put?: never
    /** Reset:Reset Password */
    post: operations["reset_reset_password_api_auth_reset_password_post"]
    delete?: never
    options?: never
    head?: never
    patch?: never
    trace?: never
  }
  "/api/auth/sessions": {
    parameters: {
      query?: never
      header?: never
      path?: never
      cookie?: never
    }
    /**
     * Read Sessions
     * @description The caller's live sessions.
     *
     *     The token itself is **not** returned — only a short prefix of it, so
     *     the operator can tell two sessions apart in a list without the list
     *     being a set of credentials.
     */
    get: operations["read_sessions_api_auth_sessions_get"]
    put?: never
    post?: never
    delete?: never
    options?: never
    head?: never
    patch?: never
    trace?: never
  }
  "/api/auth/sessions/{token}": {
    parameters: {
      query?: never
      header?: never
      path?: never
      cookie?: never
    }
    get?: never
    put?: never
    post?: never
    /**
     * Revoke One Session
     * @description End one session of the caller.
     *
     *     A token that is not the caller's is **not found** — the same answer
     *     as a token that does not exist, so the endpoint is not an existence
     *     oracle.
     */
    delete: operations["revoke_one_session_api_auth_sessions__token__delete"]
    options?: never
    head?: never
    patch?: never
    trace?: never
  }
  "/api/auth/sessions/revoke": {
    parameters: {
      query?: never
      header?: never
      path?: never
      cookie?: never
    }
    get?: never
    put?: never
    /**
     * Revoke Every Session
     * @description End **every** session of the caller, including this one.
     *
     *     This is "log me out everywhere", and the caller ends up logged out —
     *     which is the point.
     */
    post: operations["revoke_every_session_api_auth_sessions_revoke_post"]
    delete?: never
    options?: never
    head?: never
    patch?: never
    trace?: never
  }
  "/api/auth/sessions/revoke-others": {
    parameters: {
      query?: never
      header?: never
      path?: never
      cookie?: never
    }
    get?: never
    put?: never
    /**
     * Revoke The Other Sessions
     * @description End every session of the caller **except** the current one.
     */
    post: operations["revoke_the_other_sessions_api_auth_sessions_revoke_others_post"]
    delete?: never
    options?: never
    head?: never
    patch?: never
    trace?: never
  }
  "/api/auth/token/login": {
    parameters: {
      query?: never
      header?: never
      path?: never
      cookie?: never
    }
    get?: never
    put?: never
    /** Auth:Bearer.Login */
    post: operations["auth_bearer_login_api_auth_token_login_post"]
    delete?: never
    options?: never
    head?: never
    patch?: never
    trace?: never
  }
  "/api/auth/token/logout": {
    parameters: {
      query?: never
      header?: never
      path?: never
      cookie?: never
    }
    get?: never
    put?: never
    /** Auth:Bearer.Logout */
    post: operations["auth_bearer_logout_api_auth_token_logout_post"]
    delete?: never
    options?: never
    head?: never
    patch?: never
    trace?: never
  }
  "/api/auth/verify": {
    parameters: {
      query?: never
      header?: never
      path?: never
      cookie?: never
    }
    get?: never
    put?: never
    /** Verify:Verify */
    post: operations["verify_verify_api_auth_verify_post"]
    delete?: never
    options?: never
    head?: never
    patch?: never
    trace?: never
  }
  "/api/documents": {
    parameters: {
      query?: never
      header?: never
      path?: never
      cookie?: never
    }
    /**
     * List Documents
     * @description The caller's documents, newest first.
     *
     *     Args:
     *         db: The request-scoped database session.
     *         scope: The caller's access scope.
     *
     *     Returns:
     *         The documents and how many there are.
     */
    get: operations["list_documents_api_documents_get"]
    put?: never
    post?: never
    delete?: never
    options?: never
    head?: never
    patch?: never
    trace?: never
  }
  "/api/documents/{document_id}/download": {
    parameters: {
      query?: never
      header?: never
      path?: never
      cookie?: never
    }
    /**
     * Download Document
     * @description Download one of the caller's documents.
     *
     *     Args:
     *         document_id: The document's id (``profile-<id>`` or ``tailored-<id>``).
     *         db: The request-scoped database session.
     *         scope: The caller's access scope.
     *
     *     Returns:
     *         The file.
     *
     *     Raises:
     *         HTTPException 404: The document is unknown, or its file is gone.
     */
    get: operations["download_document_api_documents__document_id__download_get"]
    put?: never
    post?: never
    delete?: never
    options?: never
    head?: never
    patch?: never
    trace?: never
  }
  "/api/health": {
    parameters: {
      query?: never
      header?: never
      path?: never
      cookie?: never
    }
    /** Health Check */
    get: operations["health_check_api_health_get"]
    put?: never
    post?: never
    delete?: never
    options?: never
    head?: never
    patch?: never
    trace?: never
  }
  "/api/jobs/{job_id}": {
    parameters: {
      query?: never
      header?: never
      path?: never
      cookie?: never
    }
    /**
     * Get Job
     * @description Return one stored job listing (canonical ``{source}:{id}`` key).
     *
     *     WS-15: this route needs a credential like every other reading route.
     *     The corpus is shared (the listings are public board data, so there is
     *     no tenant to filter on), but an open read of the whole corpus is an
     *     open enumeration of it, and the route was the only one left that
     *     answered without asking who was asking.
     */
    get: operations["get_job_api_jobs__job_id__get"]
    put?: never
    post?: never
    delete?: never
    options?: never
    head?: never
    patch?: never
    trace?: never
  }
  "/api/jobs/refresh": {
    parameters: {
      query?: never
      header?: never
      path?: never
      cookie?: never
    }
    get?: never
    put?: never
    /**
     * Refresh Jobs Endpoint
     * @description Run the decoupled daily refresh: boards → normalize → dedup → persist → embed.
     *
     *     Idempotent and resumable: only new or changed listings cost embedding
     *     requests (content-hash cache), and a daily-quota stop (``quota_exhausted``)
     *     leaves everything persisted for the next run. This can take minutes with
     *     real boards — scheduled runs should use ``scripts/refresh_jobs.py``.
     *
     *     WS-15: this route needs a credential. It is the most expensive
     *     operation in the system — it walks every board and embeds the corpus —
     *     and it was the one state-changing route that anyone who could reach the
     *     port could call, in a loop, at the rate limit's pace.
     */
    post: operations["refresh_jobs_endpoint_api_jobs_refresh_post"]
    delete?: never
    options?: never
    head?: never
    patch?: never
    trace?: never
  }
  "/api/jobs/search": {
    parameters: {
      query?: never
      header?: never
      path?: never
      cookie?: never
    }
    get?: never
    put?: never
    /**
     * Search Jobs
     * @description Match one stored profile against the persisted corpus (store-only, FU-1).
     *
     *     Zero board fetches: listings come from the ``jobs`` table, semantics from
     *     the vector store (one query-embedding request for the candidate text).
     *     Match rows are persisted for the returned results so history survives
     *     restarts. Listings without vectors yet (backfill in flight) score without
     *     semantics and flip ``degraded``.
     */
    post: operations["search_jobs_api_jobs_search_post"]
    delete?: never
    options?: never
    head?: never
    patch?: never
    trace?: never
  }
  "/api/profiles/{profile_id}/matches": {
    parameters: {
      query?: never
      header?: never
      path?: never
      cookie?: never
    }
    /**
     * Get Profile Matches
     * @description Persisted match history for one profile, oldest first.
     */
    get: operations["get_profile_matches_api_profiles__profile_id__matches_get"]
    put?: never
    post?: never
    delete?: never
    options?: never
    head?: never
    patch?: never
    trace?: never
  }
  "/api/resumes": {
    parameters: {
      query?: never
      header?: never
      path?: never
      cookie?: never
    }
    get?: never
    put?: never
    /**
     * Upload Resume
     * @description Parse and persist an uploaded resume (DOCX/TXT/MD, <= 5 MB).
     *
     *     Returns the generated ``profile_id`` plus the deterministic validation
     *     warnings from the Phase-2 validation step. The upload is rejected with
     *     HTTP 400 for a disallowed extension, an oversized file, a file that is not
     *     a real document, or a file that cannot be parsed.
     */
    post: operations["upload_resume_api_resumes_post"]
    delete?: never
    options?: never
    head?: never
    patch?: never
    trace?: never
  }
  "/api/resumes/{profile_id}": {
    parameters: {
      query?: never
      header?: never
      path?: never
      cookie?: never
    }
    /**
     * Get Resume
     * @description Return the stored profile JSON for one uploaded resume.
     */
    get: operations["get_resume_api_resumes__profile_id__get"]
    put?: never
    post?: never
    delete?: never
    options?: never
    head?: never
    patch?: never
    trace?: never
  }
  "/api/tailor": {
    parameters: {
      query?: never
      header?: never
      path?: never
      cookie?: never
    }
    get?: never
    put?: never
    /**
     * Tailor Resume Endpoint
     * @description Tailor a resume for one job, render it and report on it.
     *
     *     Returns 404 when the profile or the job is unknown, and 503 when the
     *     language model is unavailable. A factuality violation is reported inside
     *     the 200 response, never as an error.
     */
    post: operations["tailor_resume_endpoint_api_tailor_post"]
    delete?: never
    options?: never
    head?: never
    patch?: never
    trace?: never
  }
  "/api/tailored/{tailoring_id}": {
    parameters: {
      query?: never
      header?: never
      path?: never
      cookie?: never
    }
    /**
     * Get Tailored
     * @description Return one stored tailoring record with its reports and file path.
     */
    get: operations["get_tailored_api_tailored__tailoring_id__get"]
    put?: never
    post?: never
    delete?: never
    options?: never
    head?: never
    patch?: never
    trace?: never
  }
  "/api/tailored/{tailoring_id}/download": {
    parameters: {
      query?: never
      header?: never
      path?: never
      cookie?: never
    }
    /**
     * Download Tailored Docx
     * @description Download the DOCX rendered for one tailoring.
     *
     *     Args:
     *         tailoring_id: The tailoring record whose DOCX is wanted.
     *         db: The request-scoped database session.
     *
     *     Returns:
     *         The DOCX file.
     *
     *     Raises:
     *         HTTPException 404: The tailoring, or its rendered file, is unknown.
     */
    get: operations["download_tailored_docx_api_tailored__tailoring_id__download_get"]
    put?: never
    post?: never
    delete?: never
    options?: never
    head?: never
    patch?: never
    trace?: never
  }
}
export type webhooks = Record<string, never>
export interface components {
  schemas: {
    /**
     * ApplicationDetailResponse
     * @description A tracked application with its full, ordered history.
     */
    ApplicationDetailResponse: {
      /** Adapter Name */
      adapter_name: string
      /** Application Url */
      application_url?: string | null
      /** Approval Id */
      approval_id?: string | null
      /** Company Name */
      company_name: string
      /**
       * Created At
       * Format: date-time
       */
      created_at: string
      /** Events */
      events?: components["schemas"]["ApplicationEventResponse"][]
      /** Id */
      id: string
      /** Job Id */
      job_id: string
      /** Job Title */
      job_title: string
      /** Job Url */
      job_url: string
      /** Notes */
      notes?: string | null
      /** Profile Id */
      profile_id?: string | null
      /** Status */
      status: string
      /** Submitted At */
      submitted_at?: string | null
      /** Tailored Resume Id */
      tailored_resume_id?: string | null
      /**
       * Updated At
       * Format: date-time
       */
      updated_at: string
      /** Verified At */
      verified_at?: string | null
      /** Workflow Id */
      workflow_id: string
    }
    /**
     * ApplicationEventResponse
     * @description One entry in an application's history.
     */
    ApplicationEventResponse: {
      /** Actor */
      actor: string
      /** Event Type */
      event_type: string
      /** From Status */
      from_status?: string | null
      /** Id */
      id: number
      /** Metadata */
      metadata?: {
        [key: string]: unknown
      }
      /**
       * Recorded At
       * Format: date-time
       */
      recorded_at: string
      /** To Status */
      to_status?: string | null
    }
    /**
     * ApplicationListResponse
     * @description A page of tracked applications.
     */
    ApplicationListResponse: {
      /** Items */
      items: components["schemas"]["ApplicationSummary"][]
      /** Limit */
      limit: number
      /** Offset */
      offset: number
      /** Total */
      total: number
    }
    /**
     * ApplicationPrepareRequest
     * @description Request body for preparing an application for review.
     */
    ApplicationPrepareRequest: {
      /**
       * Candidate Name
       * @description Full name of the candidate
       */
      candidate_name: string
      /**
       * Company Name
       * @description Company name
       */
      company_name: string
      /**
       * Cover Letter
       * @description Cover letter text or path
       */
      cover_letter?: string | null
      /**
       * Custom Fields
       * @description Additional form fields
       */
      custom_fields?: {
        [key: string]: unknown
      }
      /**
       * Email
       * @description Email address
       */
      email: string
      /**
       * Job Title
       * @description Job title from the posting
       */
      job_title: string
      /**
       * Job Url
       * @description URL of the job posting
       */
      job_url: string
      /**
       * Phone
       * @description Phone number
       */
      phone: string
      /**
       * Profile Id
       * @description Candidate profile this application belongs to
       */
      profile_id?: string | null
      /**
       * Resume Path
       * @description File path to candidate resume
       */
      resume_path?: string | null
      /**
       * Tailored Resume Id
       * @description Tailored resume used for this application
       */
      tailored_resume_id?: string | null
    }
    /**
     * ApplicationPrepareResponse
     * @description Response body for a prepared application.
     */
    ApplicationPrepareResponse: {
      /**
       * Adapter Name
       * @description Name of the adapter used
       */
      adapter_name: string
      /**
       * Application Id
       * @description Id of the tracked application (WS-07)
       */
      application_id?: string | null
      /**
       * Approval Id
       * @description Id of the approval request
       */
      approval_id: string
      prepared_summary: components["schemas"]["PreparedSummary"]
      /**
       * Status
       * @description awaiting_approval
       */
      status: string
      /**
       * Workflow Id
       * @description Unique workflow execution ID
       */
      workflow_id: string
    }
    /**
     * ApplicationSummary
     * @description A tracked application, without its history.
     */
    ApplicationSummary: {
      /** Adapter Name */
      adapter_name: string
      /** Application Url */
      application_url?: string | null
      /** Approval Id */
      approval_id?: string | null
      /** Company Name */
      company_name: string
      /**
       * Created At
       * Format: date-time
       */
      created_at: string
      /** Id */
      id: string
      /** Job Id */
      job_id: string
      /** Job Title */
      job_title: string
      /** Job Url */
      job_url: string
      /** Notes */
      notes?: string | null
      /** Profile Id */
      profile_id?: string | null
      /** Status */
      status: string
      /** Submitted At */
      submitted_at?: string | null
      /** Tailored Resume Id */
      tailored_resume_id?: string | null
      /**
       * Updated At
       * Format: date-time
       */
      updated_at: string
      /** Verified At */
      verified_at?: string | null
      /** Workflow Id */
      workflow_id: string
    }
    /**
     * ApprovalDecisionRequest
     * @description A human decision on a prepared application.
     *
     *     **The approver is the authenticated principal, not this field**
     *     (WS-14 · A2, threat T2). The field is still accepted so that an older
     *     client keeps working, but its value is **ignored**: a caller cannot
     *     approve an application *as somebody else* by naming them. When a
     *     body carries an approver that is not the caller, the fact is audited.
     *
     *     The field is optional because it is no longer the source of truth.
     */
    ApprovalDecisionRequest: {
      /**
       * Approver
       * @description Ignored. The approver is the authenticated principal.
       */
      approver?: string | null
      /**
       * Reason
       * @description Why the application was approved or rejected
       */
      reason?: string | null
    }
    /**
     * ApprovalDecisionResponse
     * @description Response body for an approval decision.
     */
    ApprovalDecisionResponse: {
      /** Adapter Name */
      adapter_name: string
      /** Approval Id */
      approval_id: string
      /** Evidence */
      evidence?: {
        [key: string]: unknown
      } | null
      /** Message */
      message: string
      /** Metadata */
      metadata?: {
        [key: string]: unknown
      } | null
      /** Status */
      status: string
      /** Success */
      success: boolean
      /** Workflow Id */
      workflow_id: string
    }
    /**
     * ApprovalStatusResponse
     * @description The stored state of an approval request.
     */
    ApprovalStatusResponse: {
      /** Adapter Name */
      adapter_name: string
      /** Approval Id */
      approval_id: string
      /** Approver */
      approver?: string | null
      /** Company Name */
      company_name: string
      /**
       * Created At
       * Format: date-time
       */
      created_at: string
      /** Decided At */
      decided_at?: string | null
      /** Decision Reason */
      decision_reason?: string | null
      /** Job Title */
      job_title: string
      /** Job Url */
      job_url: string
      /** Message */
      message?: string | null
      /** Status */
      status: string
      /** Success */
      success?: boolean | null
      /** Workflow Id */
      workflow_id: string
    }
    /**
     * AtsReport
     * @description Deterministic ATS analysis of one tailored resume.
     */
    AtsReport: {
      /** Format Risks */
      format_risks?: string[]
      keyword_coverage: components["schemas"]["KeywordCoverage"]
      /** Notes */
      notes?: string[]
      /**
       * Score
       * @default 0
       */
      score: number
      /** Section Completeness */
      section_completeness: {
        [key: string]: boolean
      }
      /**
       * Title Alignment
       * @default 0
       */
      title_alignment: number
    }
    /** BearerResponse */
    BearerResponse: {
      /** Access Token */
      access_token: string
      /** Token Type */
      token_type: string
    }
    /** Body_auth_bearer_login_api_auth_token_login_post */
    Body_auth_bearer_login_api_auth_token_login_post: {
      /** Client Id */
      client_id?: string | null
      /**
       * Client Secret
       * Format: password
       */
      client_secret?: string | null
      /** Grant Type */
      grant_type?: string | null
      /**
       * Password
       * Format: password
       */
      password: string
      /**
       * Scope
       * @default
       */
      scope: string
      /** Username */
      username: string
    }
    /** Body_auth_cookie_login_api_auth_cookie_login_post */
    Body_auth_cookie_login_api_auth_cookie_login_post: {
      /** Client Id */
      client_id?: string | null
      /**
       * Client Secret
       * Format: password
       */
      client_secret?: string | null
      /** Grant Type */
      grant_type?: string | null
      /**
       * Password
       * Format: password
       */
      password: string
      /**
       * Scope
       * @default
       */
      scope: string
      /** Username */
      username: string
    }
    /** Body_reset_forgot_password_api_auth_forgot_password_post */
    Body_reset_forgot_password_api_auth_forgot_password_post: {
      /**
       * Email
       * Format: email
       */
      email: string
    }
    /** Body_reset_reset_password_api_auth_reset_password_post */
    Body_reset_reset_password_api_auth_reset_password_post: {
      /** Password */
      password: string
      /** Token */
      token: string
    }
    /** Body_upload_resume_api_resumes_post */
    Body_upload_resume_api_resumes_post: {
      /** File */
      file: string
    }
    /** Body_verify_request_token_api_auth_request_verify_token_post */
    Body_verify_request_token_api_auth_request_verify_token_post: {
      /**
       * Email
       * Format: email
       */
      email: string
    }
    /** Body_verify_verify_api_auth_verify_post */
    Body_verify_verify_api_auth_verify_post: {
      /** Token */
      token: string
    }
    /**
     * CandidateProfile
     * @description Structured candidate profile produced by the resume parser.
     */
    CandidateProfile: {
      /** Achievements */
      achievements?: string[]
      /** Certifications */
      certifications?: string[]
      /** Education */
      education?: components["schemas"]["EducationEntry"][]
      /** Experience */
      experience?: components["schemas"]["ExperienceEntry"][]
      personal_information?: components["schemas"]["PersonalInformation"]
      /** Projects */
      projects?: components["schemas"]["ProjectEntry"][]
      /** Skill Categories */
      skill_categories?: {
        [key: string]: string[]
      }
      /** Skills */
      skills?: string[]
      /**
       * Summary
       * @default
       */
      summary: string
      work_preferences?: components["schemas"]["WorkPreferences"]
    }
    /** EducationEntry */
    EducationEntry: {
      /**
       * Dates
       * @default
       */
      dates: string
      /**
       * Degree
       * @default
       */
      degree: string
      /** Details */
      details?: string[]
      /**
       * Gpa
       * @default
       */
      gpa: string
      /**
       * Institution
       * @default
       */
      institution: string
    }
    /** ErrorModel */
    ErrorModel: {
      /** Detail */
      detail:
        | string
        | {
            [key: string]: string
          }
    }
    /** ExperienceEntry */
    ExperienceEntry: {
      /** Bullets */
      bullets?: string[]
      /**
       * Company
       * @default
       */
      company: string
      /**
       * Dates
       * @default
       */
      dates: string
      /**
       * Title
       * @default
       */
      title: string
      /** Years */
      years?: number | null
    }
    /**
     * FactualityReport
     * @description Deterministic validation outcome for a tailored resume.
     */
    FactualityReport: {
      /** Passed */
      passed: boolean
      /** Removed Experience */
      removed_experience?: string[]
      /** Removed Projects */
      removed_projects?: string[]
      /** Removed Skills */
      removed_skills?: string[]
      /** Violations */
      violations?: string[]
    }
    /** HTTPValidationError */
    HTTPValidationError: {
      /** Detail */
      detail?: components["schemas"]["ValidationError"][]
    }
    /**
     * JobInsights
     * @description Facts extracted from one job listing.
     *
     *     Every field is listing-derived: the deterministic grounding filter in this
     *     module removes anything the listing does not support.
     */
    JobInsights: {
      /**
       * Culture Flags
       * @description Explicit culture statements from the listing.
       */
      culture_flags?: string[]
      /**
       * Responsibilities
       * @description Responsibilities, near-verbatim from the description.
       */
      responsibilities?: string[]
      /**
       * Seniority Signals
       * @description Explicit seniority statements from the listing.
       */
      seniority_signals?: string[]
      /**
       * Summary
       * @description One grounded sentence about the role.
       * @default
       */
      summary: string
      /**
       * Tech Stack
       * @description Technologies named in the listing.
       */
      tech_stack?: string[]
    }
    /**
     * JobListing
     * @description Normalized job listing from any source.
     */
    JobListing: {
      /** Application Url */
      application_url?: string | null
      /** Company */
      company: string
      /** Company Url */
      company_url?: string | null
      /** Currency */
      currency?: string | null
      /** Description */
      description?: string | null
      /** Education Requirements */
      education_requirements?: string | null
      /** Employment Type */
      employment_type?: string | null
      /** Experience Requirements */
      experience_requirements?: string | null
      /** Id */
      id: string
      /** Location */
      location?: string | null
      /** Metadata */
      metadata?: {
        [key: string]: unknown
      }
      /** Posted At */
      posted_at?: string | null
      /** Preferred Skills */
      preferred_skills?: string[]
      /** Remote Policy */
      remote_policy?: string | null
      /** Required Skills */
      required_skills?: string[]
      /** Salary */
      salary?: string | null
      /** Seniority */
      seniority?: string | null
      /** Source */
      source: string
      /** Source Job Id */
      source_job_id?: string | null
      /** Title */
      title: string
    }
    /**
     * JobMatchPair
     * @description One (listing, match result) pair flowing through match/rank.
     */
    JobMatchPair: {
      job: components["schemas"]["JobListing"]
      match: components["schemas"]["JobMatchResult"]
    }
    /**
     * JobMatchResult
     * @description Result of matching a candidate profile against a job listing.
     */
    JobMatchResult: {
      /** Experience Score */
      experience_score: number
      /**
       * Explanation
       * @default
       */
      explanation: string
      /** Location Score */
      location_score: number
      /** Matched Requirements */
      matched_requirements?: string[]
      /** Missing Requirements */
      missing_requirements?: string[]
      /** Overall Score */
      overall_score: number
      /** Preference Score */
      preference_score: number
      /** Semantic Score */
      semantic_score: number
      /** Seniority Score */
      seniority_score: number
      /** Skill Score */
      skill_score: number
    }
    /**
     * JobRefreshResponse
     * @description Summary of one decoupled refresh run (FU-1).
     */
    JobRefreshResponse: {
      /** Degraded Embedding */
      degraded_embedding: boolean
      /** Embedding Documents Planned */
      embedding_documents_planned: number
      /** Embedding Requests Planned */
      embedding_requests_planned: number
      /** Embedding Requests Used */
      embedding_requests_used: number
      /** Quota Exhausted */
      quota_exhausted: boolean
      /** Source Errors */
      source_errors?: {
        [key: string]: string
      }
      stats: components["schemas"]["JobRefreshStats"]
    }
    /**
     * JobRefreshStats
     * @description Pipeline counters for one daily refresh run (FU-1).
     */
    JobRefreshStats: {
      /**
       * Admission Capped
       * @default 0
       */
      admission_capped: number
      /**
       * Deduped
       * @default 0
       */
      deduped: number
      /**
       * Dropped
       * @default 0
       */
      dropped: number
      /**
       * Embedded
       * @default 0
       */
      embedded: number
      /**
       * Found
       * @default 0
       */
      found: number
      /**
       * Persisted
       * @default 0
       */
      persisted: number
      /**
       * Screened Out
       * @default 0
       */
      screened_out: number
    }
    /**
     * JobSearchRequest
     * @description Request body for a store-only job search (FU-1).
     */
    JobSearchRequest: {
      /**
       * Location
       * @description Optional case-insensitive location substring filter
       */
      location?: string | null
      /**
       * Profile Id
       * @description Id returned by POST /api/resumes
       */
      profile_id: string
      /**
       * Query
       * @description Optional client-side corpus filter (ANY token in title+description)
       */
      query?: string | null
      /**
       * Top N
       * @description Size of the ranked slice (clamped server-side)
       * @default 10
       */
      top_n: number
    }
    /**
     * JobSearchResponse
     * @description Ranked matches plus pipeline outcome details.
     */
    JobSearchResponse: {
      /**
       * Degraded
       * @default false
       */
      degraded: boolean
      /** Profile Id */
      profile_id: string
      /** Results */
      results: components["schemas"]["JobMatchPair"][]
      /** Source Errors */
      source_errors?: {
        [key: string]: string
      }
      stats: components["schemas"]["JobSearchStats"]
    }
    /**
     * JobSearchStats
     * @description Pipeline counters for one search run.
     */
    JobSearchStats: {
      /**
       * Deduped
       * @default 0
       */
      deduped: number
      /**
       * Dropped
       * @default 0
       */
      dropped: number
      /**
       * Found
       * @default 0
       */
      found: number
      /**
       * Persisted
       * @default 0
       */
      persisted: number
      /**
       * Stored
       * @default 0
       */
      stored: number
    }
    /**
     * KeywordCoverage
     * @description How much of the job's stated keyword surface the resume actually shows.
     */
    KeywordCoverage: {
      /**
       * Preferred Coverage
       * @default 0
       */
      preferred_coverage: number
      /** Preferred Hit */
      preferred_hit?: string[]
      /** Preferred Missing */
      preferred_missing?: string[]
      /**
       * Required Coverage
       * @default 0
       */
      required_coverage: number
      /** Required Hit */
      required_hit?: string[]
      /** Required Missing */
      required_missing?: string[]
    }
    /**
     * MatchesHistoryResponse
     * @description Persisted matches for one profile (history across searches).
     */
    MatchesHistoryResponse: {
      /** Matches */
      matches: {
        [key: string]: unknown
      }[]
      /** Profile Id */
      profile_id: string
    }
    /** PersonalInformation */
    PersonalInformation: {
      /**
       * Email
       * @default
       */
      email: string
      /**
       * Location
       * @default
       */
      location: string
      /**
       * Name
       * @default
       */
      name: string
      /**
       * Phone
       * @default
       */
      phone: string
      /**
       * Title
       * @default
       */
      title: string
      /**
       * Website
       * @default
       */
      website: string
    }
    /**
     * PreparedSummary
     * @description What a human is asked to review before approving.
     *
     *     The prepared field *names* are listed, not their values: the values are
     *     the candidate's personal data and the reviewer does not need them echoed
     *     back to make a decision. The same holds for the profile facts (WS-08):
     *     their *names* say what the agent may answer a form question with.
     */
    PreparedSummary: {
      /** Adapter Name */
      adapter_name: string
      /** Company Name */
      company_name: string
      /** Field Names */
      field_names?: string[]
      /** Job Title */
      job_title: string
      /** Job Url */
      job_url: string
      /** Profile Fact Names */
      profile_fact_names?: string[]
      /**
       * Requires Manual Review
       * @default false
       */
      requires_manual_review: boolean
      /** Resume Path */
      resume_path?: string | null
    }
    /** ProjectEntry */
    ProjectEntry: {
      /** Bullets */
      bullets?: string[]
      /** Name */
      name: string
      /**
       * Subtitle
       * @default
       */
      subtitle: string
      /**
       * Tech
       * @default
       */
      tech: string
    }
    /**
     * ResumeProfileResponse
     * @description Stored profile response.
     */
    ResumeProfileResponse: {
      profile: components["schemas"]["CandidateProfile"]
      /** Profile Id */
      profile_id: string
    }
    /**
     * ResumeUploadResponse
     * @description Response for a successful upload.
     */
    ResumeUploadResponse: {
      profile: components["schemas"]["CandidateProfile"]
      /**
       * Profile Id
       * @description Id to use for job searches
       */
      profile_id: string
      /** Warnings */
      warnings?: string[]
    }
    /**
     * StatusUpdateRequest
     * @description A human outcome for a tracked application.
     *
     *     **The actor is the authenticated principal, not this field**
     *     (WS-14 · Phase A2, threat T2). The field is still accepted so that
     *     an older client keeps working, but its value is **ignored**: a
     *     caller cannot record an outcome *as somebody else* by naming them.
     *     The actor rule that a human outcome must be set by a human is now
     *     checked against the session, which is where the truth is.
     */
    StatusUpdateRequest: {
      /**
       * Actor
       * @description Ignored. The actor is the authenticated principal.
       */
      actor?: string | null
      /**
       * Notes
       * @description A note stored with the application
       */
      notes?: string | null
      /**
       * Status
       * @description The status to move to
       */
      status: string
    }
    /**
     * StoredTailoringResponse
     * @description A stored tailoring record (adds the creation time).
     */
    StoredTailoringResponse: {
      ats_report: components["schemas"]["AtsReport"]
      /** Created At */
      created_at: string
      /** Docx Path */
      docx_path: string
      factuality: components["schemas"]["FactualityReport"]
      insights: components["schemas"]["JobInsights"]
      /** Job Id */
      job_id: string
      /** Profile Id */
      profile_id: string
      tailored: components["schemas"]["TailoredResume"]
      /** Tailoring Id */
      tailoring_id: string
    }
    /**
     * TailoredExperience
     * @description One experience entry as it should appear in the tailored resume.
     */
    TailoredExperience: {
      /**
       * Bullets
       * @description Achievement bullets rephrased from profile facts only.
       */
      bullets: string[]
      /**
       * Company
       * @description Company name, copied exactly from the profile.
       */
      company: string
      /**
       * Title
       * @description Job title, copied exactly from the profile.
       */
      title: string
    }
    /**
     * TailoredProject
     * @description One project entry as it should appear in the tailored resume.
     */
    TailoredProject: {
      /**
       * Bullets
       * @description Project bullets rephrased from profile facts only.
       */
      bullets: string[]
      /**
       * Name
       * @description Project name, copied exactly from the profile.
       */
      name: string
    }
    /**
     * TailoredResume
     * @description Tailored resume content produced from profile facts only.
     */
    TailoredResume: {
      /**
       * Cover Letter
       * @description Short cover letter draft using profile facts only.
       */
      cover_letter: string
      /** Experience */
      experience: components["schemas"]["TailoredExperience"][]
      /**
       * Highlighted Skills
       * @description Skills drawn from the profile that match the job.
       */
      highlighted_skills: string[]
      /**
       * Projects
       * @description Profile projects relevant to the job (use instead of invented employment).
       */
      projects?: components["schemas"]["TailoredProject"][]
      /**
       * Summary
       * @description Short professional summary using profile facts only.
       */
      summary: string
    }
    /**
     * TailorRequest
     * @description Request body for a tailoring run.
     */
    TailorRequest: {
      /**
       * Job Id
       * @description Canonical job id (source:id)
       */
      job_id: string
      /**
       * Profile Id
       * @description Id returned by POST /api/resumes
       */
      profile_id: string
    }
    /**
     * TailorResponse
     * @description The tailoring result, its reports and the rendered file path.
     */
    TailorResponse: {
      ats_report: components["schemas"]["AtsReport"]
      /** Docx Path */
      docx_path: string
      factuality: components["schemas"]["FactualityReport"]
      insights: components["schemas"]["JobInsights"]
      /** Job Id */
      job_id: string
      /** Profile Id */
      profile_id: string
      tailored: components["schemas"]["TailoredResume"]
      /** Tailoring Id */
      tailoring_id: string
    }
    /**
     * UserCreate
     * @description What a registration may specify.
     */
    UserCreate: {
      /**
       * Email
       * Format: email
       */
      email: string
      /** Full Name */
      full_name?: string | null
      /**
       * Is Active
       * @default true
       */
      is_active: boolean | null
      /**
       * Is Superuser
       * @default false
       */
      is_superuser: boolean | null
      /**
       * Is Verified
       * @default false
       */
      is_verified: boolean | null
      /** Password */
      password: string
    }
    /**
     * UserRead
     * @description The public view of an account.
     */
    UserRead: {
      /**
       * Email
       * Format: email
       */
      email: string
      /** Full Name */
      full_name?: string | null
      /** Id */
      id: string
      /**
       * Is Active
       * @default true
       */
      is_active: boolean
      /**
       * Is Superuser
       * @default false
       */
      is_superuser: boolean
      /**
       * Is Verified
       * @default false
       */
      is_verified: boolean
    }
    /**
     * UserUpdate
     * @description What a user may change about their own account.
     *
     *     Declared from :class:`~fastapi_users.schemas.CreateUpdateDictModel`
     *     rather than from ``BaseUserUpdate`` so that ``is_active``,
     *     ``is_superuser`` and ``is_verified`` are **not fields at all**. The
     *     endpoint this schema serves is "me": a user may change their own
     *     e-mail and their own password, and nothing else. With
     *     ``extra="forbid"`` a request that tries to promote itself is refused
     *     with a 422 instead of being quietly dropped.
     */
    UserUpdate: {
      /** Email */
      email?: string | null
      /** Full Name */
      full_name?: string | null
      /** Password */
      password?: string | null
    }
    /** ValidationError */
    ValidationError: {
      /** Context */
      ctx?: Record<string, never>
      /** Input */
      input?: unknown
      /** Location */
      loc: (string | number)[]
      /** Message */
      msg: string
      /** Error Type */
      type: string
    }
    /**
     * WorkPreferences
     * @description Work preferences the resume explicitly states.
     *
     *     Every field stays ``None``/empty unless the document states it — the
     *     parser never infers or invents preferences. ``min_salary`` and
     *     ``work_authorization`` are kept verbatim and parsed on demand.
     */
    WorkPreferences: {
      /** Employment Types */
      employment_types?: string[]
      /** Min Salary */
      min_salary?: string | null
      /** Preferred Locations */
      preferred_locations?: string[]
      /** Remote Preference */
      remote_preference?: string | null
      /** Work Authorization */
      work_authorization?: string | null
    }
  }
  responses: never
  parameters: never
  requestBodies: never
  headers: never
  pathItems: never
}
export type $defs = Record<string, never>
export interface operations {
  root__get: {
    parameters: {
      query?: never
      header?: never
      path?: never
      cookie?: never
    }
    requestBody?: never
    responses: {
      /** @description Successful Response */
      200: {
        headers: {
          [name: string]: unknown
        }
        content: {
          "application/json": {
            [key: string]: string
          }
        }
      }
    }
  }
  list_applications_api_applications_get: {
    parameters: {
      query?: {
        limit?: number
        offset?: number
        profile_id?: string | null
        status?: string[] | null
      }
      header?: never
      path?: never
      cookie?: never
    }
    requestBody?: never
    responses: {
      /** @description Successful Response */
      200: {
        headers: {
          [name: string]: unknown
        }
        content: {
          "application/json": components["schemas"]["ApplicationListResponse"]
        }
      }
      /** @description Validation Error */
      422: {
        headers: {
          [name: string]: unknown
        }
        content: {
          "application/json": components["schemas"]["HTTPValidationError"]
        }
      }
    }
  }
  get_application_api_applications__application_id__get: {
    parameters: {
      query?: never
      header?: never
      path: {
        application_id: string
      }
      cookie?: never
    }
    requestBody?: never
    responses: {
      /** @description Successful Response */
      200: {
        headers: {
          [name: string]: unknown
        }
        content: {
          "application/json": components["schemas"]["ApplicationDetailResponse"]
        }
      }
      /** @description Validation Error */
      422: {
        headers: {
          [name: string]: unknown
        }
        content: {
          "application/json": components["schemas"]["HTTPValidationError"]
        }
      }
    }
  }
  list_application_evidence_api_applications__application_id__evidence_get: {
    parameters: {
      query?: never
      header?: never
      path: {
        application_id: string
      }
      cookie?: never
    }
    requestBody?: never
    responses: {
      /** @description Successful Response */
      200: {
        headers: {
          [name: string]: unknown
        }
        content: {
          "application/json": {
            [key: string]: unknown
          }
        }
      }
      /** @description Validation Error */
      422: {
        headers: {
          [name: string]: unknown
        }
        content: {
          "application/json": components["schemas"]["HTTPValidationError"]
        }
      }
    }
  }
  download_evidence_api_applications__application_id__evidence__filename__get: {
    parameters: {
      query?: never
      header?: never
      path: {
        application_id: string
        filename: string
      }
      cookie?: never
    }
    requestBody?: never
    responses: {
      /** @description Successful Response */
      200: {
        headers: {
          [name: string]: unknown
        }
        content: {
          "application/json": unknown
        }
      }
      /** @description Validation Error */
      422: {
        headers: {
          [name: string]: unknown
        }
        content: {
          "application/json": components["schemas"]["HTTPValidationError"]
        }
      }
    }
  }
  update_application_status_api_applications__application_id__status_patch: {
    parameters: {
      query?: never
      header?: never
      path: {
        application_id: string
      }
      cookie?: never
    }
    requestBody: {
      content: {
        "application/json": components["schemas"]["StatusUpdateRequest"]
      }
    }
    responses: {
      /** @description Successful Response */
      200: {
        headers: {
          [name: string]: unknown
        }
        content: {
          "application/json": components["schemas"]["ApplicationDetailResponse"]
        }
      }
      /** @description Validation Error */
      422: {
        headers: {
          [name: string]: unknown
        }
        content: {
          "application/json": components["schemas"]["HTTPValidationError"]
        }
      }
    }
  }
  approve_application_api_applications__approval_id__approve_post: {
    parameters: {
      query?: never
      header?: never
      path: {
        approval_id: string
      }
      cookie?: never
    }
    requestBody: {
      content: {
        "application/json": components["schemas"]["ApprovalDecisionRequest"]
      }
    }
    responses: {
      /** @description Successful Response */
      200: {
        headers: {
          [name: string]: unknown
        }
        content: {
          "application/json": components["schemas"]["ApprovalDecisionResponse"]
        }
      }
      /** @description Validation Error */
      422: {
        headers: {
          [name: string]: unknown
        }
        content: {
          "application/json": components["schemas"]["HTTPValidationError"]
        }
      }
    }
  }
  reject_application_api_applications__approval_id__reject_post: {
    parameters: {
      query?: never
      header?: never
      path: {
        approval_id: string
      }
      cookie?: never
    }
    requestBody: {
      content: {
        "application/json": components["schemas"]["ApprovalDecisionRequest"]
      }
    }
    responses: {
      /** @description Successful Response */
      200: {
        headers: {
          [name: string]: unknown
        }
        content: {
          "application/json": components["schemas"]["ApprovalDecisionResponse"]
        }
      }
      /** @description Validation Error */
      422: {
        headers: {
          [name: string]: unknown
        }
        content: {
          "application/json": components["schemas"]["HTTPValidationError"]
        }
      }
    }
  }
  get_approval_api_applications_approvals__approval_id__get: {
    parameters: {
      query?: never
      header?: never
      path: {
        approval_id: string
      }
      cookie?: never
    }
    requestBody?: never
    responses: {
      /** @description Successful Response */
      200: {
        headers: {
          [name: string]: unknown
        }
        content: {
          "application/json": components["schemas"]["ApprovalStatusResponse"]
        }
      }
      /** @description Validation Error */
      422: {
        headers: {
          [name: string]: unknown
        }
        content: {
          "application/json": components["schemas"]["HTTPValidationError"]
        }
      }
    }
  }
  prepare_application_api_applications_prepare_post: {
    parameters: {
      query?: never
      header?: never
      path?: never
      cookie?: never
    }
    requestBody: {
      content: {
        "application/json": components["schemas"]["ApplicationPrepareRequest"]
      }
    }
    responses: {
      /** @description Successful Response */
      200: {
        headers: {
          [name: string]: unknown
        }
        content: {
          "application/json": components["schemas"]["ApplicationPrepareResponse"]
        }
      }
      /** @description Validation Error */
      422: {
        headers: {
          [name: string]: unknown
        }
        content: {
          "application/json": components["schemas"]["HTTPValidationError"]
        }
      }
    }
  }
  list_audit_events_api_audit_get: {
    parameters: {
      query?: {
        limit?: number
      }
      header?: never
      path?: never
      cookie?: never
    }
    requestBody?: never
    responses: {
      /** @description Successful Response */
      200: {
        headers: {
          [name: string]: unknown
        }
        content: {
          "application/json": {
            [key: string]: unknown
          }
        }
      }
      /** @description Validation Error */
      422: {
        headers: {
          [name: string]: unknown
        }
        content: {
          "application/json": components["schemas"]["HTTPValidationError"]
        }
      }
    }
  }
  auth_cookie_login_api_auth_cookie_login_post: {
    parameters: {
      query?: never
      header?: never
      path?: never
      cookie?: never
    }
    requestBody: {
      content: {
        "application/x-www-form-urlencoded": components["schemas"]["Body_auth_cookie_login_api_auth_cookie_login_post"]
      }
    }
    responses: {
      /** @description Successful Response */
      200: {
        headers: {
          [name: string]: unknown
        }
        content: {
          "application/json": unknown
        }
      }
      /** @description No Content */
      204: {
        headers: {
          [name: string]: unknown
        }
        content?: never
      }
      /** @description Bad Request */
      400: {
        headers: {
          [name: string]: unknown
        }
        content: {
          "application/json": components["schemas"]["ErrorModel"]
        }
      }
      /** @description Validation Error */
      422: {
        headers: {
          [name: string]: unknown
        }
        content: {
          "application/json": components["schemas"]["HTTPValidationError"]
        }
      }
    }
  }
  auth_cookie_logout_api_auth_cookie_logout_post: {
    parameters: {
      query?: never
      header?: never
      path?: never
      cookie?: never
    }
    requestBody?: never
    responses: {
      /** @description Successful Response */
      200: {
        headers: {
          [name: string]: unknown
        }
        content: {
          "application/json": unknown
        }
      }
      /** @description No Content */
      204: {
        headers: {
          [name: string]: unknown
        }
        content?: never
      }
      /** @description Missing token or inactive user. */
      401: {
        headers: {
          [name: string]: unknown
        }
        content?: never
      }
    }
  }
  reset_forgot_password_api_auth_forgot_password_post: {
    parameters: {
      query?: never
      header?: never
      path?: never
      cookie?: never
    }
    requestBody: {
      content: {
        "application/json": components["schemas"]["Body_reset_forgot_password_api_auth_forgot_password_post"]
      }
    }
    responses: {
      /** @description Successful Response */
      202: {
        headers: {
          [name: string]: unknown
        }
        content: {
          "application/json": unknown
        }
      }
      /** @description Validation Error */
      422: {
        headers: {
          [name: string]: unknown
        }
        content: {
          "application/json": components["schemas"]["HTTPValidationError"]
        }
      }
    }
  }
  read_me_api_auth_me_get: {
    parameters: {
      query?: never
      header?: never
      path?: never
      cookie?: never
    }
    requestBody?: never
    responses: {
      /** @description Successful Response */
      200: {
        headers: {
          [name: string]: unknown
        }
        content: {
          "application/json": components["schemas"]["UserRead"]
        }
      }
    }
  }
  request_account_deletion_api_auth_me_delete: {
    parameters: {
      query?: never
      header?: never
      path?: never
      cookie?: never
    }
    requestBody?: never
    responses: {
      /** @description Successful Response */
      200: {
        headers: {
          [name: string]: unknown
        }
        content: {
          "application/json": {
            [key: string]: unknown
          }
        }
      }
    }
  }
  update_me_api_auth_me_patch: {
    parameters: {
      query?: never
      header?: never
      path?: never
      cookie?: never
    }
    requestBody: {
      content: {
        "application/json": components["schemas"]["UserUpdate"]
      }
    }
    responses: {
      /** @description Successful Response */
      200: {
        headers: {
          [name: string]: unknown
        }
        content: {
          "application/json": components["schemas"]["UserRead"]
        }
      }
      /** @description Validation Error */
      422: {
        headers: {
          [name: string]: unknown
        }
        content: {
          "application/json": components["schemas"]["HTTPValidationError"]
        }
      }
    }
  }
  register_register_api_auth_register_post: {
    parameters: {
      query?: never
      header?: never
      path?: never
      cookie?: never
    }
    requestBody: {
      content: {
        "application/json": components["schemas"]["UserCreate"]
      }
    }
    responses: {
      /** @description Successful Response */
      201: {
        headers: {
          [name: string]: unknown
        }
        content: {
          "application/json": components["schemas"]["UserRead"]
        }
      }
      /** @description Bad Request */
      400: {
        headers: {
          [name: string]: unknown
        }
        content: {
          "application/json": components["schemas"]["ErrorModel"]
        }
      }
      /** @description Validation Error */
      422: {
        headers: {
          [name: string]: unknown
        }
        content: {
          "application/json": components["schemas"]["HTTPValidationError"]
        }
      }
    }
  }
  verify_request_token_api_auth_request_verify_token_post: {
    parameters: {
      query?: never
      header?: never
      path?: never
      cookie?: never
    }
    requestBody: {
      content: {
        "application/json": components["schemas"]["Body_verify_request_token_api_auth_request_verify_token_post"]
      }
    }
    responses: {
      /** @description Successful Response */
      202: {
        headers: {
          [name: string]: unknown
        }
        content: {
          "application/json": unknown
        }
      }
      /** @description Validation Error */
      422: {
        headers: {
          [name: string]: unknown
        }
        content: {
          "application/json": components["schemas"]["HTTPValidationError"]
        }
      }
    }
  }
  reset_reset_password_api_auth_reset_password_post: {
    parameters: {
      query?: never
      header?: never
      path?: never
      cookie?: never
    }
    requestBody: {
      content: {
        "application/json": components["schemas"]["Body_reset_reset_password_api_auth_reset_password_post"]
      }
    }
    responses: {
      /** @description Successful Response */
      200: {
        headers: {
          [name: string]: unknown
        }
        content: {
          "application/json": unknown
        }
      }
      /** @description Bad Request */
      400: {
        headers: {
          [name: string]: unknown
        }
        content: {
          "application/json": components["schemas"]["ErrorModel"]
        }
      }
      /** @description Validation Error */
      422: {
        headers: {
          [name: string]: unknown
        }
        content: {
          "application/json": components["schemas"]["HTTPValidationError"]
        }
      }
    }
  }
  read_sessions_api_auth_sessions_get: {
    parameters: {
      query?: never
      header?: never
      path?: never
      cookie?: never
    }
    requestBody?: never
    responses: {
      /** @description Successful Response */
      200: {
        headers: {
          [name: string]: unknown
        }
        content: {
          "application/json": {
            [key: string]: unknown
          }
        }
      }
    }
  }
  revoke_one_session_api_auth_sessions__token__delete: {
    parameters: {
      query?: never
      header?: never
      path: {
        token: string
      }
      cookie?: never
    }
    requestBody?: never
    responses: {
      /** @description Successful Response */
      200: {
        headers: {
          [name: string]: unknown
        }
        content: {
          "application/json": {
            [key: string]: unknown
          }
        }
      }
      /** @description Validation Error */
      422: {
        headers: {
          [name: string]: unknown
        }
        content: {
          "application/json": components["schemas"]["HTTPValidationError"]
        }
      }
    }
  }
  revoke_every_session_api_auth_sessions_revoke_post: {
    parameters: {
      query?: never
      header?: never
      path?: never
      cookie?: never
    }
    requestBody?: never
    responses: {
      /** @description Successful Response */
      200: {
        headers: {
          [name: string]: unknown
        }
        content: {
          "application/json": {
            [key: string]: unknown
          }
        }
      }
    }
  }
  revoke_the_other_sessions_api_auth_sessions_revoke_others_post: {
    parameters: {
      query?: never
      header?: never
      path?: never
      cookie?: never
    }
    requestBody?: never
    responses: {
      /** @description Successful Response */
      200: {
        headers: {
          [name: string]: unknown
        }
        content: {
          "application/json": {
            [key: string]: unknown
          }
        }
      }
    }
  }
  auth_bearer_login_api_auth_token_login_post: {
    parameters: {
      query?: never
      header?: never
      path?: never
      cookie?: never
    }
    requestBody: {
      content: {
        "application/x-www-form-urlencoded": components["schemas"]["Body_auth_bearer_login_api_auth_token_login_post"]
      }
    }
    responses: {
      /** @description Successful Response */
      200: {
        headers: {
          [name: string]: unknown
        }
        content: {
          /**
           * @example {
           *       "access_token": "eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9.eyJ1c2VyX2lkIjoiOTIyMWZmYzktNjQwZi00MzcyLTg2ZDMtY2U2NDJjYmE1NjAzIiwiYXVkIjoiZmFzdGFwaS11c2VyczphdXRoIiwiZXhwIjoxNTcxNTA0MTkzfQ.M10bjOe45I5Ncu_uXvOmVV8QxnL-nZfcH96U90JaocI",
           *       "token_type": "bearer"
           *     }
           */
          "application/json": components["schemas"]["BearerResponse"]
        }
      }
      /** @description Bad Request */
      400: {
        headers: {
          [name: string]: unknown
        }
        content: {
          "application/json": components["schemas"]["ErrorModel"]
        }
      }
      /** @description Validation Error */
      422: {
        headers: {
          [name: string]: unknown
        }
        content: {
          "application/json": components["schemas"]["HTTPValidationError"]
        }
      }
    }
  }
  auth_bearer_logout_api_auth_token_logout_post: {
    parameters: {
      query?: never
      header?: never
      path?: never
      cookie?: never
    }
    requestBody?: never
    responses: {
      /** @description Successful Response */
      200: {
        headers: {
          [name: string]: unknown
        }
        content: {
          "application/json": unknown
        }
      }
      /** @description Missing token or inactive user. */
      401: {
        headers: {
          [name: string]: unknown
        }
        content?: never
      }
    }
  }
  verify_verify_api_auth_verify_post: {
    parameters: {
      query?: never
      header?: never
      path?: never
      cookie?: never
    }
    requestBody: {
      content: {
        "application/json": components["schemas"]["Body_verify_verify_api_auth_verify_post"]
      }
    }
    responses: {
      /** @description Successful Response */
      200: {
        headers: {
          [name: string]: unknown
        }
        content: {
          "application/json": components["schemas"]["UserRead"]
        }
      }
      /** @description Bad Request */
      400: {
        headers: {
          [name: string]: unknown
        }
        content: {
          "application/json": components["schemas"]["ErrorModel"]
        }
      }
      /** @description Validation Error */
      422: {
        headers: {
          [name: string]: unknown
        }
        content: {
          "application/json": components["schemas"]["HTTPValidationError"]
        }
      }
    }
  }
  list_documents_api_documents_get: {
    parameters: {
      query?: never
      header?: never
      path?: never
      cookie?: never
    }
    requestBody?: never
    responses: {
      /** @description Successful Response */
      200: {
        headers: {
          [name: string]: unknown
        }
        content: {
          "application/json": {
            [key: string]: unknown
          }
        }
      }
    }
  }
  download_document_api_documents__document_id__download_get: {
    parameters: {
      query?: never
      header?: never
      path: {
        document_id: string
      }
      cookie?: never
    }
    requestBody?: never
    responses: {
      /** @description Successful Response */
      200: {
        headers: {
          [name: string]: unknown
        }
        content: {
          "application/json": unknown
        }
      }
      /** @description Validation Error */
      422: {
        headers: {
          [name: string]: unknown
        }
        content: {
          "application/json": components["schemas"]["HTTPValidationError"]
        }
      }
    }
  }
  health_check_api_health_get: {
    parameters: {
      query?: never
      header?: never
      path?: never
      cookie?: never
    }
    requestBody?: never
    responses: {
      /** @description Successful Response */
      200: {
        headers: {
          [name: string]: unknown
        }
        content: {
          "application/json": {
            [key: string]: string
          }
        }
      }
    }
  }
  get_job_api_jobs__job_id__get: {
    parameters: {
      query?: never
      header?: never
      path: {
        job_id: string
      }
      cookie?: never
    }
    requestBody?: never
    responses: {
      /** @description Successful Response */
      200: {
        headers: {
          [name: string]: unknown
        }
        content: {
          "application/json": {
            [key: string]: unknown
          }
        }
      }
      /** @description Validation Error */
      422: {
        headers: {
          [name: string]: unknown
        }
        content: {
          "application/json": components["schemas"]["HTTPValidationError"]
        }
      }
    }
  }
  refresh_jobs_endpoint_api_jobs_refresh_post: {
    parameters: {
      query?: never
      header?: never
      path?: never
      cookie?: never
    }
    requestBody?: never
    responses: {
      /** @description Successful Response */
      200: {
        headers: {
          [name: string]: unknown
        }
        content: {
          "application/json": components["schemas"]["JobRefreshResponse"]
        }
      }
    }
  }
  search_jobs_api_jobs_search_post: {
    parameters: {
      query?: never
      header?: never
      path?: never
      cookie?: never
    }
    requestBody: {
      content: {
        "application/json": components["schemas"]["JobSearchRequest"]
      }
    }
    responses: {
      /** @description Successful Response */
      200: {
        headers: {
          [name: string]: unknown
        }
        content: {
          "application/json": components["schemas"]["JobSearchResponse"]
        }
      }
      /** @description Validation Error */
      422: {
        headers: {
          [name: string]: unknown
        }
        content: {
          "application/json": components["schemas"]["HTTPValidationError"]
        }
      }
    }
  }
  get_profile_matches_api_profiles__profile_id__matches_get: {
    parameters: {
      query?: never
      header?: never
      path: {
        profile_id: string
      }
      cookie?: never
    }
    requestBody?: never
    responses: {
      /** @description Successful Response */
      200: {
        headers: {
          [name: string]: unknown
        }
        content: {
          "application/json": components["schemas"]["MatchesHistoryResponse"]
        }
      }
      /** @description Validation Error */
      422: {
        headers: {
          [name: string]: unknown
        }
        content: {
          "application/json": components["schemas"]["HTTPValidationError"]
        }
      }
    }
  }
  upload_resume_api_resumes_post: {
    parameters: {
      query?: never
      header?: never
      path?: never
      cookie?: never
    }
    requestBody: {
      content: {
        "multipart/form-data": components["schemas"]["Body_upload_resume_api_resumes_post"]
      }
    }
    responses: {
      /** @description Successful Response */
      200: {
        headers: {
          [name: string]: unknown
        }
        content: {
          "application/json": components["schemas"]["ResumeUploadResponse"]
        }
      }
      /** @description Validation Error */
      422: {
        headers: {
          [name: string]: unknown
        }
        content: {
          "application/json": components["schemas"]["HTTPValidationError"]
        }
      }
    }
  }
  get_resume_api_resumes__profile_id__get: {
    parameters: {
      query?: never
      header?: never
      path: {
        profile_id: string
      }
      cookie?: never
    }
    requestBody?: never
    responses: {
      /** @description Successful Response */
      200: {
        headers: {
          [name: string]: unknown
        }
        content: {
          "application/json": components["schemas"]["ResumeProfileResponse"]
        }
      }
      /** @description Validation Error */
      422: {
        headers: {
          [name: string]: unknown
        }
        content: {
          "application/json": components["schemas"]["HTTPValidationError"]
        }
      }
    }
  }
  tailor_resume_endpoint_api_tailor_post: {
    parameters: {
      query?: never
      header?: never
      path?: never
      cookie?: never
    }
    requestBody: {
      content: {
        "application/json": components["schemas"]["TailorRequest"]
      }
    }
    responses: {
      /** @description Successful Response */
      200: {
        headers: {
          [name: string]: unknown
        }
        content: {
          "application/json": components["schemas"]["TailorResponse"]
        }
      }
      /** @description Validation Error */
      422: {
        headers: {
          [name: string]: unknown
        }
        content: {
          "application/json": components["schemas"]["HTTPValidationError"]
        }
      }
    }
  }
  get_tailored_api_tailored__tailoring_id__get: {
    parameters: {
      query?: never
      header?: never
      path: {
        tailoring_id: string
      }
      cookie?: never
    }
    requestBody?: never
    responses: {
      /** @description Successful Response */
      200: {
        headers: {
          [name: string]: unknown
        }
        content: {
          "application/json": components["schemas"]["StoredTailoringResponse"]
        }
      }
      /** @description Validation Error */
      422: {
        headers: {
          [name: string]: unknown
        }
        content: {
          "application/json": components["schemas"]["HTTPValidationError"]
        }
      }
    }
  }
  download_tailored_docx_api_tailored__tailoring_id__download_get: {
    parameters: {
      query?: never
      header?: never
      path: {
        tailoring_id: string
      }
      cookie?: never
    }
    requestBody?: never
    responses: {
      /** @description Successful Response */
      200: {
        headers: {
          [name: string]: unknown
        }
        content: {
          "application/json": unknown
        }
      }
      /** @description Validation Error */
      422: {
        headers: {
          [name: string]: unknown
        }
        content: {
          "application/json": components["schemas"]["HTTPValidationError"]
        }
      }
    }
  }
}
