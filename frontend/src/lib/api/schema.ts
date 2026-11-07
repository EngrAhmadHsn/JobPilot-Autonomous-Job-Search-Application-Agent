export interface paths {
    "/": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Root */
        get: operations["root__get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/admin/embedding-runs": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * List Embedding Runs
         * @description The platform's embedding executions, newest first.
         *
         *     This is the screen an administrator opens after an interruption: it shows
         *     recoverable runs, paused runs, permanent failures and healthy history.
         */
        get: operations["list_embedding_runs_api_admin_embedding_runs_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/admin/embedding-runs/{run_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Read Embedding Run
         * @description One embedding run: progress, checkpoint, quota reason and failures.
         */
        get: operations["read_embedding_run_api_admin_embedding_runs__run_id__get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/admin/embedding-runs/{run_id}/cancel": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Cancel Embedding Run
         * @description Stop a run without deleting its history (safe cancellation).
         */
        post: operations["cancel_embedding_run_api_admin_embedding_runs__run_id__cancel_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/admin/embedding-runs/{run_id}/resume": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Resume Embedding Run
         * @description Resume the **outstanding** work of an interrupted embedding run.
         *
         *     The administrator's identity is the authenticated principal (never a
         *     request field), the run must be in a resumable state, the embedding model
         *     and dimension must match the current provider, completed work is never
         *     requeued, and a concurrent resume loses the conditional update. The
         *     action is audited and returns the same durable run id.
         */
        post: operations["resume_embedding_run_api_admin_embedding_runs__run_id__resume_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/admin/embeddings/reconcile": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Reconcile Embeddings
         * @description Enqueue a reconciliation of the SQL corpus against the vector index.
         *
         *     The worker detects missing/stale vectors, orphan vectors, interrupted
         *     items and inconsistent completion flags, repairs what it can safely
         *     repair, and records the counts on the run. It never rebuilds completed
         *     work unnecessarily.
         */
        post: operations["reconcile_embeddings_api_admin_embeddings_reconcile_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/admin/health/workers": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Read Worker Health
         * @description Whether the background worker is alive — which the API cannot infer.
         *
         *     A process that answers HTTP requests says nothing about whether any
         *     worker is draining the queue. This endpoint reads the heartbeats and the
         *     queue's shape, and is deliberately separate from the API's own
         *     readiness.
         */
        get: operations["read_worker_health_api_admin_health_workers_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/admin/jobs/metrics": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Read Job Metrics
         * @description Queue, worker, breaker and embedding-budget metrics.
         *
         *     The numbers the brief asks an operator to be able to see: pending and
         *     running work, stale leases, retry backlog, the oldest pending item's age,
         *     worker heartbeat age, breaker states, and today's embedding spend.
         */
        get: operations["read_job_metrics_api_admin_jobs_metrics_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/admin/overview": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Read Overview
         * @description Platform-wide counts, for the administration screen.
         *
         *     Every figure is a live count over the platform's own tables. Nothing is
         *     cached, sampled or estimated: an administrator looking at this screen is
         *     looking at the database.
         */
        get: operations["read_overview_api_admin_overview_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/admin/runs": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * List All Runs
         * @description Every durable run on the platform, newest first.
         *
         *     The embedding-runs listing above is the recovery surface for one kind of
         *     work; this one is the platform's whole queue, which is what an operator
         *     needs when a refresh, a reconciliation and an embedding pass are all in
         *     flight — or when a queued run is not moving because no worker is running.
         *
         *     Filters are optional and applied by the data layer, not by the route.
         */
        get: operations["list_all_runs_api_admin_runs_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/admin/runs/{run_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Read Any Run
         * @description One run of any type, with its checkpoint, counters and events.
         */
        get: operations["read_any_run_api_admin_runs__run_id__get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/applications": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
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
        get: operations["list_applications_api_applications_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/applications/{application_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Get Application
         * @description Return a tracked application with its full history.
         *
         *     Raises:
         *         HTTPException 404: the application is unknown.
         */
        get: operations["get_application_api_applications__application_id__get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/applications/{application_id}/evidence": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
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
        get: operations["list_application_evidence_api_applications__application_id__evidence_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/applications/{application_id}/evidence/{filename}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
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
        get: operations["download_evidence_api_applications__application_id__evidence__filename__get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/applications/{application_id}/status": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
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
        patch: operations["update_application_status_api_applications__application_id__status_patch"];
        trace?: never;
    };
    "/api/applications/{approval_id}/approve": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
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
        post: operations["approve_application_api_applications__approval_id__approve_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/applications/{approval_id}/reject": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
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
        post: operations["reject_application_api_applications__approval_id__reject_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/applications/approvals/{approval_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Get Approval
         * @description Return the stored state of an approval request.
         *
         *     The path is ``/approvals/{id}`` because ``/api/applications/{id}`` is the
         *     *tracked application* (WS-07). Two different resources cannot share one
         *     path shape.
         */
        get: operations["get_approval_api_applications_approvals__approval_id__get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/applications/prepare": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
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
        post: operations["prepare_application_api_applications_prepare_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/audit": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
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
        get: operations["list_audit_events_api_audit_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/auth/cookie/login": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Auth:Cookie.Login */
        post: operations["auth_cookie_login_api_auth_cookie_login_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/auth/cookie/logout": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Auth:Cookie.Logout */
        post: operations["auth_cookie_logout_api_auth_cookie_logout_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/auth/forgot-password": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Reset:Forgot Password */
        post: operations["reset_forgot_password_api_auth_forgot_password_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/auth/me": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Read Me
         * @description The authenticated principal.
         *
         *     This is the endpoint that turns "the caller is anonymous" into "the
         *     caller is somebody", and it is the one the console calls first.
         */
        get: operations["read_me_api_auth_me_get"];
        put?: never;
        post?: never;
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
        delete: operations["request_account_deletion_api_auth_me_delete"];
        options?: never;
        head?: never;
        /**
         * Update Me
         * @description Change the caller's own e-mail, password or display name.
         *
         *     A password change ends the caller's **other** sessions: the session
         *     the change was made from stays, every other one goes. That is the
         *     point of changing a password.
         */
        patch: operations["update_me_api_auth_me_patch"];
        trace?: never;
    };
    "/api/auth/register": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Register:Register */
        post: operations["register_register_api_auth_register_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/auth/request-verify-token": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Verify:Request-Token */
        post: operations["verify_request_token_api_auth_request_verify_token_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/auth/reset-password": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Reset:Reset Password */
        post: operations["reset_reset_password_api_auth_reset_password_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/auth/sessions": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Read Sessions
         * @description The caller's live sessions.
         *
         *     The token itself is **not** returned — only a short prefix of it, so
         *     the operator can tell two sessions apart in a list without the list
         *     being a set of credentials.
         */
        get: operations["read_sessions_api_auth_sessions_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/auth/sessions/{token}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        post?: never;
        /**
         * Revoke One Session
         * @description End one session of the caller.
         *
         *     A token that is not the caller's is **not found** — the same answer
         *     as a token that does not exist, so the endpoint is not an existence
         *     oracle.
         */
        delete: operations["revoke_one_session_api_auth_sessions__token__delete"];
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/auth/sessions/revoke": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Revoke Every Session
         * @description End **every** session of the caller, including this one.
         *
         *     This is "log me out everywhere", and the caller ends up logged out —
         *     which is the point.
         */
        post: operations["revoke_every_session_api_auth_sessions_revoke_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/auth/sessions/revoke-others": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Revoke The Other Sessions
         * @description End every session of the caller **except** the current one.
         */
        post: operations["revoke_the_other_sessions_api_auth_sessions_revoke_others_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/auth/token/login": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Auth:Bearer.Login */
        post: operations["auth_bearer_login_api_auth_token_login_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/auth/token/logout": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Auth:Bearer.Logout */
        post: operations["auth_bearer_logout_api_auth_token_logout_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/auth/verify": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Verify:Verify */
        post: operations["verify_verify_api_auth_verify_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/documents": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
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
        get: operations["list_documents_api_documents_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/documents/{document_id}/download": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
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
        get: operations["download_document_api_documents__document_id__download_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/health": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Health Check
         * @description The original liveness answer, kept for compatibility.
         */
        get: operations["health_check_api_health_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/health/live": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Liveness
         * @description Is the API process alive? The cheapest possible answer.
         */
        get: operations["liveness_api_health_live_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/health/ready": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Readiness
         * @description Can the API serve its essential operations right now?
         *
         *     ``essential`` means: the database answers. The worker's heartbeat is
         *     reported next to it, and an unhealthy worker is flagged — but it does
         *     not make the *API* unready, because reads and searches still work while
         *     a worker is being restarted. The administration endpoint
         *     (``GET /api/admin/health/workers``) is where worker liveness is an
         *     alert.
         */
        get: operations["readiness_api_health_ready_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/jobs/{job_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
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
        get: operations["get_job_api_jobs__job_id__get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/jobs/refresh": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Refresh Jobs Endpoint
         * @description Accept a corpus refresh as **durable background work** (WS-18).
         *
         *     The request no longer performs the refresh. It writes a ``job_runs`` row
         *     and responds ``202`` with that row's id, so closing the browser, losing
         *     the connection, or restarting the API cannot lose the accepted work. The
         *     separate worker executes it; ``GET /api/runs/{run_id}`` reports progress
         *     from persistent state.
         *
         *     A refresh that is already queued or running is returned instead of
         *     duplicated: two clicks are one refresh.
         *
         *     WS-15: this route needs a credential. It is the most expensive
         *     operation in the system, and the queue (not the request) now bounds it.
         */
        post: operations["refresh_jobs_endpoint_api_jobs_refresh_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/jobs/search": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
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
        post: operations["search_jobs_api_jobs_search_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/profiles/{profile_id}/application-profile": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Get Application Profile
         * @description Return the user-confirmed application profile (empty when never set).
         */
        get: operations["get_application_profile_api_profiles__profile_id__application_profile_get"];
        /**
         * Put Application Profile
         * @description Replace the user-confirmed application profile (validated, bounded).
         *
         *     The body is a full :class:`ApplicationProfile`; Pydantic validation caps
         *     every list and range, so an oversized or malformed body is a 422 before it
         *     reaches the database.
         */
        put: operations["put_application_profile_api_profiles__profile_id__application_profile_put"];
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/profiles/{profile_id}/eeo": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Get Eeo
         * @description Return the stored EEO selections (all-unset when never provided).
         */
        get: operations["get_eeo_api_profiles__profile_id__eeo_get"];
        /**
         * Put Eeo
         * @description Upsert the voluntary EEO selections for a profile.
         *
         *     The values are never echoed to logs and never audited (only the fact that a
         *     write happened, and which fields were present, is recorded). Storing the
         *     values requires ``opt_in``.
         */
        put: operations["put_eeo_api_profiles__profile_id__eeo_put"];
        post?: never;
        /**
         * Delete Eeo
         * @description Delete a profile's EEO row outright (a real delete, not a soft flag).
         */
        delete: operations["delete_eeo_api_profiles__profile_id__eeo_delete"];
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/profiles/{profile_id}/matches": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Get Profile Matches
         * @description Persisted match history for one profile, oldest first.
         */
        get: operations["get_profile_matches_api_profiles__profile_id__matches_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/resumes": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Upload Resume
         * @description Parse and persist an uploaded resume (DOCX/TXT/MD, <= 5 MB).
         *
         *     Returns the generated ``profile_id`` plus the deterministic validation
         *     warnings from the Phase-2 validation step. The upload is rejected with
         *     HTTP 400 for a disallowed extension, an oversized file, a file that is not
         *     a real document, or a file that cannot be parsed.
         */
        post: operations["upload_resume_api_resumes_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/resumes/{profile_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Get Resume
         * @description Return the stored profile JSON for one uploaded resume.
         */
        get: operations["get_resume_api_resumes__profile_id__get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/runs": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * List Runs
         * @description The caller's own execution history (newest first).
         *
         *     An ordinary account sees the runs it requested; an administrator sees
         *     every run, including the platform's. A platform run has no owner, so it
         *     is never returned to an ordinary caller.
         */
        get: operations["list_runs_api_runs_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/runs/{run_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Get Run
         * @description One run's persistent state, checkpoints and item summary.
         *
         *     A foreign run and a missing one answer the same 404, so the route is not
         *     an existence oracle.
         */
        get: operations["get_run_api_runs__run_id__get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/tailor": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Tailor Resume Endpoint
         * @description Tailor a resume for one job, render it and report on it.
         *
         *     Returns 404 when the profile or the job is unknown, and 503 when the
         *     language model is unavailable. A factuality violation is reported inside
         *     the 200 response, never as an error.
         */
        post: operations["tailor_resume_endpoint_api_tailor_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/tailored/{tailoring_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Get Tailored
         * @description Return one stored tailoring record with its reports and file path.
         */
        get: operations["get_tailored_api_tailored__tailoring_id__get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/tailored/{tailoring_id}/download": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
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
        get: operations["download_tailored_docx_api_tailored__tailoring_id__download_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
}
export type webhooks = Record<string, never>;
export interface components {
    schemas: {
        /**
         * AdminRunDetailResponse
         * @description One execution, with its checkpoints and item summary.
         */
        AdminRunDetailResponse: {
            /** Run */
            run: {
                [key: string]: unknown;
            };
        };
        /**
         * AdminRunsResponse
         * @description Platform-level embedding executions.
         */
        AdminRunsResponse: {
            /** Count */
            count: number;
            /** Runs */
            runs: {
                [key: string]: unknown;
            }[];
        };
        /**
         * ApplicationAnswers
         * @description The answers a form asks for, grounded in user-confirmed values.
         */
        ApplicationAnswers: {
            compensation?: components["schemas"]["Compensation"];
            notice?: components["schemas"]["NoticePeriod"];
            work_authorization?: components["schemas"]["WorkAuthorizationInfo"];
        };
        /**
         * ApplicationDetailResponse
         * @description A tracked application with its full, ordered history.
         */
        ApplicationDetailResponse: {
            /** Adapter Name */
            adapter_name: string;
            /** Application Url */
            application_url?: string | null;
            /** Approval Id */
            approval_id?: string | null;
            /** Company Name */
            company_name: string;
            /**
             * Created At
             * Format: date-time
             */
            created_at: string;
            /** Events */
            events?: components["schemas"]["ApplicationEventResponse"][];
            /** Id */
            id: string;
            /** Job Id */
            job_id: string;
            /** Job Title */
            job_title: string;
            /** Job Url */
            job_url: string;
            /** Notes */
            notes?: string | null;
            /** Profile Id */
            profile_id?: string | null;
            /** Status */
            status: string;
            /** Submitted At */
            submitted_at?: string | null;
            /** Tailored Resume Id */
            tailored_resume_id?: string | null;
            /**
             * Updated At
             * Format: date-time
             */
            updated_at: string;
            /** Verified At */
            verified_at?: string | null;
            /** Workflow Id */
            workflow_id: string;
        };
        /**
         * ApplicationEventResponse
         * @description One entry in an application's history.
         */
        ApplicationEventResponse: {
            /** Actor */
            actor: string;
            /** Event Type */
            event_type: string;
            /** From Status */
            from_status?: string | null;
            /** Id */
            id: number;
            /** Metadata */
            metadata?: {
                [key: string]: unknown;
            };
            /**
             * Recorded At
             * Format: date-time
             */
            recorded_at: string;
            /** To Status */
            to_status?: string | null;
        };
        /**
         * ApplicationListResponse
         * @description A page of tracked applications.
         */
        ApplicationListResponse: {
            /** Items */
            items: components["schemas"]["ApplicationSummary"][];
            /** Limit */
            limit: number;
            /** Offset */
            offset: number;
            /** Total */
            total: number;
        };
        /**
         * ApplicationPrepareRequest
         * @description Request body for preparing an application for review.
         */
        ApplicationPrepareRequest: {
            /**
             * Candidate Name
             * @description Full name of the candidate
             */
            candidate_name: string;
            /**
             * Company Name
             * @description Company name
             */
            company_name: string;
            /**
             * Cover Letter
             * @description Cover letter text or path
             */
            cover_letter?: string | null;
            /**
             * Custom Fields
             * @description Additional form fields
             */
            custom_fields?: {
                [key: string]: unknown;
            };
            /**
             * Email
             * @description Email address
             */
            email: string;
            /**
             * Job Title
             * @description Job title from the posting
             */
            job_title: string;
            /**
             * Job Url
             * @description URL of the job posting
             */
            job_url: string;
            /**
             * Phone
             * @description Phone number
             */
            phone: string;
            /**
             * Profile Id
             * @description Candidate profile this application belongs to
             */
            profile_id?: string | null;
            /**
             * Resume Path
             * @description File path to candidate resume
             */
            resume_path?: string | null;
            /**
             * Tailored Resume Id
             * @description Tailored resume used for this application
             */
            tailored_resume_id?: string | null;
        };
        /**
         * ApplicationPrepareResponse
         * @description Response body for a prepared application.
         */
        ApplicationPrepareResponse: {
            /**
             * Adapter Name
             * @description Name of the adapter used
             */
            adapter_name: string;
            /**
             * Application Id
             * @description Id of the tracked application (WS-07)
             */
            application_id?: string | null;
            /**
             * Approval Id
             * @description Id of the approval request
             */
            approval_id: string;
            prepared_summary: components["schemas"]["PreparedSummary"];
            /**
             * Status
             * @description awaiting_approval
             */
            status: string;
            /**
             * Workflow Id
             * @description Unique workflow execution ID
             */
            workflow_id: string;
        };
        /**
         * ApplicationProfile
         * @description The user-confirmed application profile (kept separate from the résumé).
         *
         *     ``confirmed_fields`` lists the dotted paths the user explicitly confirmed,
         *     so a caller can tell a *confirmed* value from an imported one and label a
         *     form answer's provenance honestly.
         */
        ApplicationProfile: {
            answers?: components["schemas"]["ApplicationAnswers"];
            /** Confirmed Fields */
            confirmed_fields?: string[];
            preferences?: components["schemas"]["JobSearchPreferences"];
            professional?: components["schemas"]["ProfessionalInfo"];
        };
        /**
         * ApplicationProfileResponse
         * @description The stored application profile for one résumé profile.
         */
        ApplicationProfileResponse: {
            application_profile: components["schemas"]["ApplicationProfile"];
            /** Profile Id */
            profile_id: string;
        };
        /**
         * ApplicationSummary
         * @description A tracked application, without its history.
         */
        ApplicationSummary: {
            /** Adapter Name */
            adapter_name: string;
            /** Application Url */
            application_url?: string | null;
            /** Approval Id */
            approval_id?: string | null;
            /** Company Name */
            company_name: string;
            /**
             * Created At
             * Format: date-time
             */
            created_at: string;
            /** Id */
            id: string;
            /** Job Id */
            job_id: string;
            /** Job Title */
            job_title: string;
            /** Job Url */
            job_url: string;
            /** Notes */
            notes?: string | null;
            /** Profile Id */
            profile_id?: string | null;
            /** Status */
            status: string;
            /** Submitted At */
            submitted_at?: string | null;
            /** Tailored Resume Id */
            tailored_resume_id?: string | null;
            /**
             * Updated At
             * Format: date-time
             */
            updated_at: string;
            /** Verified At */
            verified_at?: string | null;
            /** Workflow Id */
            workflow_id: string;
        };
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
            approver?: string | null;
            /**
             * Reason
             * @description Why the application was approved or rejected
             */
            reason?: string | null;
        };
        /**
         * ApprovalDecisionResponse
         * @description Response body for an approval decision.
         */
        ApprovalDecisionResponse: {
            /** Adapter Name */
            adapter_name: string;
            /** Approval Id */
            approval_id: string;
            /** Evidence */
            evidence?: {
                [key: string]: unknown;
            } | null;
            /** Message */
            message: string;
            /** Metadata */
            metadata?: {
                [key: string]: unknown;
            } | null;
            /** Status */
            status: string;
            /** Success */
            success: boolean;
            /** Workflow Id */
            workflow_id: string;
        };
        /**
         * ApprovalStatusResponse
         * @description The stored state of an approval request.
         */
        ApprovalStatusResponse: {
            /** Adapter Name */
            adapter_name: string;
            /** Approval Id */
            approval_id: string;
            /** Approver */
            approver?: string | null;
            /** Company Name */
            company_name: string;
            /**
             * Created At
             * Format: date-time
             */
            created_at: string;
            /** Decided At */
            decided_at?: string | null;
            /** Decision Reason */
            decision_reason?: string | null;
            /** Job Title */
            job_title: string;
            /** Job Url */
            job_url: string;
            /** Message */
            message?: string | null;
            /** Status */
            status: string;
            /** Success */
            success?: boolean | null;
            /** Workflow Id */
            workflow_id: string;
        };
        /**
         * AtsReport
         * @description Deterministic ATS analysis of one tailored resume.
         */
        AtsReport: {
            /** Format Risks */
            format_risks?: string[];
            keyword_coverage: components["schemas"]["KeywordCoverage"];
            /** Notes */
            notes?: string[];
            /**
             * Score
             * @default 0
             */
            score: number;
            /** Section Completeness */
            section_completeness: {
                [key: string]: boolean;
            };
            /**
             * Title Alignment
             * @default 0
             */
            title_alignment: number;
        };
        /** BearerResponse */
        BearerResponse: {
            /** Access Token */
            access_token: string;
            /** Token Type */
            token_type: string;
        };
        /** Body_auth_bearer_login_api_auth_token_login_post */
        Body_auth_bearer_login_api_auth_token_login_post: {
            /** Client Id */
            client_id?: string | null;
            /**
             * Client Secret
             * Format: password
             */
            client_secret?: string | null;
            /** Grant Type */
            grant_type?: string | null;
            /**
             * Password
             * Format: password
             */
            password: string;
            /**
             * Scope
             * @default
             */
            scope: string;
            /** Username */
            username: string;
        };
        /** Body_auth_cookie_login_api_auth_cookie_login_post */
        Body_auth_cookie_login_api_auth_cookie_login_post: {
            /** Client Id */
            client_id?: string | null;
            /**
             * Client Secret
             * Format: password
             */
            client_secret?: string | null;
            /** Grant Type */
            grant_type?: string | null;
            /**
             * Password
             * Format: password
             */
            password: string;
            /**
             * Scope
             * @default
             */
            scope: string;
            /** Username */
            username: string;
        };
        /** Body_reset_forgot_password_api_auth_forgot_password_post */
        Body_reset_forgot_password_api_auth_forgot_password_post: {
            /**
             * Email
             * Format: email
             */
            email: string;
        };
        /** Body_reset_reset_password_api_auth_reset_password_post */
        Body_reset_reset_password_api_auth_reset_password_post: {
            /** Password */
            password: string;
            /** Token */
            token: string;
        };
        /** Body_upload_resume_api_resumes_post */
        Body_upload_resume_api_resumes_post: {
            /** File */
            file: string;
        };
        /** Body_verify_request_token_api_auth_request_verify_token_post */
        Body_verify_request_token_api_auth_request_verify_token_post: {
            /**
             * Email
             * Format: email
             */
            email: string;
        };
        /** Body_verify_verify_api_auth_verify_post */
        Body_verify_verify_api_auth_verify_post: {
            /** Token */
            token: string;
        };
        /**
         * CandidateProfile
         * @description Structured candidate profile produced by the resume parser.
         *
         *     WS-20 adds ``application_profile``: the **user-confirmed** application
         *     answers and job-search preferences, kept separate from the résumé-derived
         *     fields above. It is empty by default, so older stored profiles validate
         *     unchanged; the persisted copy lives in its own column
         *     (``candidate_profiles.application_json``), not inside this JSON blob.
         */
        CandidateProfile: {
            /** Achievements */
            achievements?: string[];
            application_profile?: components["schemas"]["ApplicationProfile"];
            /** Certifications */
            certifications?: string[];
            /** Education */
            education?: components["schemas"]["EducationEntry"][];
            /** Experience */
            experience?: components["schemas"]["ExperienceEntry"][];
            personal_information?: components["schemas"]["PersonalInformation"];
            /** Projects */
            projects?: components["schemas"]["ProjectEntry"][];
            /** Skill Categories */
            skill_categories?: {
                [key: string]: string[];
            };
            /** Skills */
            skills?: string[];
            /**
             * Summary
             * @default
             */
            summary: string;
            work_preferences?: components["schemas"]["WorkPreferences"];
        };
        /**
         * Compensation
         * @description Expected **and** current compensation, each with currency and period.
         *
         *     Expected salary is not current salary. Keeping them in separate fields is
         *     what stops "desired salary" from being answered with a past paycheque.
         */
        Compensation: {
            /** Current Currency */
            current_currency?: string | null;
            /** Current Period */
            current_period?: string | null;
            /** Current Salary */
            current_salary?: number | null;
            /** Expected Currency */
            expected_currency?: string | null;
            /** Expected Period */
            expected_period?: string | null;
            /** Expected Salary */
            expected_salary?: number | null;
        };
        /** EducationEntry */
        EducationEntry: {
            /**
             * Dates
             * @default
             */
            dates: string;
            /**
             * Degree
             * @default
             */
            degree: string;
            /** Details */
            details?: string[];
            /**
             * Gpa
             * @default
             */
            gpa: string;
            /**
             * Institution
             * @default
             */
            institution: string;
        };
        /**
         * EeoProfile
         * @description Owner-scoped voluntary self-identification data.
         *
         *     Every field is ``None`` until the user answers. A field set to
         *     :data:`DECLINED` records an explicit "prefer not to answer" — which is
         *     **not** the same as leaving it unanswered, and is never auto-selected.
         *     ``opt_in`` must be true for the data to be stored at all.
         */
        EeoProfile: {
            /** Disability */
            disability?: string | null;
            /** Gender */
            gender?: string | null;
            /**
             * Opt In
             * @default false
             */
            opt_in: boolean;
            /** Race Ethnicity */
            race_ethnicity?: string | null;
            /** Veteran Status */
            veteran_status?: string | null;
        };
        /**
         * EeoResponse
         * @description The stored EEO selections for one profile (empty when unset).
         */
        EeoResponse: {
            eeo: components["schemas"]["EeoProfile"];
            /** Profile Id */
            profile_id: string;
        };
        /** ErrorModel */
        ErrorModel: {
            /** Detail */
            detail: string | {
                [key: string]: string;
            };
        };
        /** ExperienceEntry */
        ExperienceEntry: {
            /** Bullets */
            bullets?: string[];
            /**
             * Company
             * @default
             */
            company: string;
            /**
             * Dates
             * @default
             */
            dates: string;
            /**
             * Title
             * @default
             */
            title: string;
            /** Years */
            years?: number | null;
        };
        /**
         * FactualityReport
         * @description Deterministic validation outcome for a tailored resume.
         */
        FactualityReport: {
            /** Passed */
            passed: boolean;
            /** Removed Experience */
            removed_experience?: string[];
            /** Removed Projects */
            removed_projects?: string[];
            /** Removed Skills */
            removed_skills?: string[];
            /** Violations */
            violations?: string[];
        };
        /** HTTPValidationError */
        HTTPValidationError: {
            /** Detail */
            detail?: components["schemas"]["ValidationError"][];
        };
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
            culture_flags?: string[];
            /**
             * Responsibilities
             * @description Responsibilities, near-verbatim from the description.
             */
            responsibilities?: string[];
            /**
             * Seniority Signals
             * @description Explicit seniority statements from the listing.
             */
            seniority_signals?: string[];
            /**
             * Summary
             * @description One grounded sentence about the role.
             * @default
             */
            summary: string;
            /**
             * Tech Stack
             * @description Technologies named in the listing.
             */
            tech_stack?: string[];
        };
        /**
         * JobListing
         * @description Normalized job listing from any source.
         */
        JobListing: {
            /** Application Url */
            application_url?: string | null;
            /** Company */
            company: string;
            /** Company Url */
            company_url?: string | null;
            /** Currency */
            currency?: string | null;
            /** Description */
            description?: string | null;
            /** Education Requirements */
            education_requirements?: string | null;
            /** Employment Type */
            employment_type?: string | null;
            /** Experience Requirements */
            experience_requirements?: string | null;
            /** Id */
            id: string;
            /** Location */
            location?: string | null;
            /** Metadata */
            metadata?: {
                [key: string]: unknown;
            };
            /** Posted At */
            posted_at?: string | null;
            /** Preferred Skills */
            preferred_skills?: string[];
            /** Remote Policy */
            remote_policy?: string | null;
            /** Required Skills */
            required_skills?: string[];
            /** Salary */
            salary?: string | null;
            /** Seniority */
            seniority?: string | null;
            /** Source */
            source: string;
            /** Source Job Id */
            source_job_id?: string | null;
            /** Title */
            title: string;
        };
        /**
         * JobMatchPair
         * @description One (listing, match result) pair flowing through match/rank.
         */
        JobMatchPair: {
            job: components["schemas"]["JobListing"];
            match: components["schemas"]["JobMatchResult"];
        };
        /**
         * JobMatchResult
         * @description Result of matching a candidate profile against a job listing.
         *
         *     Every component score is 0-100 and, in the WS-20 policy, only meaningful
         *     when the corresponding entry in ``component_states`` is a *measured* state.
         *     An unknown component carries ``0.0`` — it is never presented as a match —
         *     and its reason appears in ``notes``. ``evidence_coverage`` says how much of
         *     the overall score rests on real information, so a score and its coverage
         *     are always readable together.
         */
        JobMatchResult: {
            /** Component States */
            component_states?: {
                [key: string]: string;
            };
            /**
             * Evidence Coverage
             * @default 0
             */
            evidence_coverage: number;
            /** Experience Score */
            experience_score: number;
            /**
             * Explanation
             * @default
             */
            explanation: string;
            /**
             * Lexical Score
             * @default 0
             */
            lexical_score: number;
            /** Location Score */
            location_score: number;
            /** Matched Keywords */
            matched_keywords?: string[];
            /** Matched Requirements */
            matched_requirements?: string[];
            /** Missing Keywords */
            missing_keywords?: string[];
            /** Missing Requirements */
            missing_requirements?: string[];
            /** Notes */
            notes?: string[];
            /** Overall Score */
            overall_score: number;
            /** Preference Score */
            preference_score: number;
            /** Semantic Score */
            semantic_score: number;
            /** Seniority Score */
            seniority_score: number;
            /** Skill Score */
            skill_score: number;
        };
        /**
         * JobSearchPreferences
         * @description Where and how the candidate wants to work (user-stated only).
         */
        JobSearchPreferences: {
            /** Employment Types */
            employment_types?: string[];
            /** Preferred Locations */
            preferred_locations?: string[];
            /** Remote Preference */
            remote_preference?: string | null;
            /** Willing To Relocate */
            willing_to_relocate?: boolean | null;
        };
        /**
         * JobSearchRequest
         * @description Request body for a store-only job search (FU-1).
         */
        JobSearchRequest: {
            /**
             * Location
             * @description Optional case-insensitive location substring filter
             */
            location?: string | null;
            /**
             * Only Embedded
             * @description WS-20: return only listings with a verified vector. Off by default — a pending listing stays visible (it may still match lexically) but earns no semantic credit.
             * @default false
             */
            only_embedded: boolean;
            /**
             * Profile Id
             * @description Id returned by POST /api/resumes
             */
            profile_id: string;
            /**
             * Query
             * @description Optional client-side corpus filter (ANY token in title+description)
             */
            query?: string | null;
            /**
             * Top N
             * @description Size of the ranked slice (clamped server-side)
             * @default 10
             */
            top_n: number;
        };
        /**
         * JobSearchResponse
         * @description Ranked matches plus pipeline outcome details.
         */
        JobSearchResponse: {
            /**
             * Degraded
             * @default false
             */
            degraded: boolean;
            /** Profile Id */
            profile_id: string;
            /** Results */
            results: components["schemas"]["JobMatchPair"][];
            /**
             * Semantic Coverage
             * @default 100
             */
            semantic_coverage: number;
            /** Source Errors */
            source_errors?: {
                [key: string]: string;
            };
            stats: components["schemas"]["JobSearchStats"];
        };
        /**
         * JobSearchStats
         * @description Pipeline counters for one search run.
         */
        JobSearchStats: {
            /**
             * Deduped
             * @default 0
             */
            deduped: number;
            /**
             * Dropped
             * @default 0
             */
            dropped: number;
            /**
             * Found
             * @default 0
             */
            found: number;
            /**
             * Persisted
             * @default 0
             */
            persisted: number;
            /**
             * Semantic Covered
             * @default 0
             */
            semantic_covered: number;
            /**
             * Stored
             * @default 0
             */
            stored: number;
        };
        /**
         * KeywordCoverage
         * @description How much of the job's stated keyword surface the resume actually shows.
         */
        KeywordCoverage: {
            /**
             * Preferred Coverage
             * @default 0
             */
            preferred_coverage: number;
            /** Preferred Hit */
            preferred_hit?: string[];
            /** Preferred Missing */
            preferred_missing?: string[];
            /**
             * Required Coverage
             * @default 0
             */
            required_coverage: number;
            /** Required Hit */
            required_hit?: string[];
            /** Required Missing */
            required_missing?: string[];
        };
        /**
         * MatchesHistoryResponse
         * @description Persisted matches for one profile (history across searches).
         */
        MatchesHistoryResponse: {
            /** Matches */
            matches: {
                [key: string]: unknown;
            }[];
            /** Profile Id */
            profile_id: string;
        };
        /**
         * NoticePeriod
         * @description Notice period and availability, with zero meaning "immediate".
         */
        NoticePeriod: {
            /** Available From */
            available_from?: string | null;
            /** Immediate */
            immediate?: boolean | null;
            /** Notice Days */
            notice_days?: number | null;
        };
        /** PersonalInformation */
        PersonalInformation: {
            /**
             * Email
             * @default
             */
            email: string;
            /**
             * Location
             * @default
             */
            location: string;
            /**
             * Name
             * @default
             */
            name: string;
            /**
             * Phone
             * @default
             */
            phone: string;
            /**
             * Title
             * @default
             */
            title: string;
            /**
             * Website
             * @default
             */
            website: string;
        };
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
            adapter_name: string;
            /** Company Name */
            company_name: string;
            /** Field Names */
            field_names?: string[];
            /** Job Title */
            job_title: string;
            /** Job Url */
            job_url: string;
            /** Profile Fact Names */
            profile_fact_names?: string[];
            /**
             * Requires Manual Review
             * @default false
             */
            requires_manual_review: boolean;
            /** Resume Path */
            resume_path?: string | null;
        };
        /**
         * ProfessionalInfo
         * @description Confirmed professional facts (supplement the résumé, never invent).
         */
        ProfessionalInfo: {
            /** Current Title */
            current_title?: string | null;
            /** Linkedin Url */
            linkedin_url?: string | null;
            /** Portfolio Url */
            portfolio_url?: string | null;
            /** Seniority Level */
            seniority_level?: string | null;
            /** Skill Experience Years */
            skill_experience_years?: {
                [key: string]: number;
            };
            /** Total Experience Years */
            total_experience_years?: number | null;
        };
        /** ProjectEntry */
        ProjectEntry: {
            /** Bullets */
            bullets?: string[];
            /** Name */
            name: string;
            /**
             * Subtitle
             * @default
             */
            subtitle: string;
            /**
             * Tech
             * @default
             */
            tech: string;
        };
        /**
         * ResumeProfileResponse
         * @description Stored profile response.
         */
        ResumeProfileResponse: {
            profile: components["schemas"]["CandidateProfile"];
            /** Profile Id */
            profile_id: string;
        };
        /**
         * ResumeRunRequest
         * @description The resume body.
         *
         *     Deliberately empty: the administrator's identity comes from the session,
         *     and the model/dimension are validated against the server's own
         *     configuration. A request field that could name another principal, a
         *     different embedding space, or a larger budget would be a bypass.
         */
        ResumeRunRequest: Record<string, never>;
        /**
         * ResumeUploadResponse
         * @description Response for a successful upload.
         */
        ResumeUploadResponse: {
            profile: components["schemas"]["CandidateProfile"];
            /**
             * Profile Id
             * @description Id to use for job searches
             */
            profile_id: string;
            /** Warnings */
            warnings?: string[];
        };
        /**
         * RunAcceptedResponse
         * @description A durable run the API has accepted (WS-18).
         *
         *     This is the refresh contract now: ``202 Accepted`` and a persistent id.
         *     The caller polls ``GET /api/runs/{run_id}`` (or the administration
         *     endpoints) for the actual state. ``existing`` is true when an active
         *     refresh was already queued and this request joined it instead of
         *     starting a second one.
         */
        RunAcceptedResponse: {
            /** Correlation Id */
            correlation_id: string;
            /**
             * Created At
             * Format: date-time
             */
            created_at: string;
            /**
             * Existing
             * @default false
             */
            existing: boolean;
            /** Job Type */
            job_type: string;
            /** Run Id */
            run_id: string;
            /** Status */
            status: string;
        };
        /**
         * RunActionResponse
         * @description The answer to a recovery or cancellation request.
         */
        RunActionResponse: {
            /** Job Type */
            job_type: string;
            /**
             * Queued
             * @default true
             */
            queued: boolean;
            /** Run Id */
            run_id: string;
            /** Status */
            status: string;
        };
        /**
         * RunDetailResponse
         * @description One run, with its checkpoints and item summary.
         */
        RunDetailResponse: {
            /** Run */
            run: {
                [key: string]: unknown;
            };
        };
        /**
         * RunsListResponse
         * @description The caller's own execution history.
         */
        RunsListResponse: {
            /** Count */
            count: number;
            /** Runs */
            runs: {
                [key: string]: unknown;
            }[];
        };
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
            actor?: string | null;
            /**
             * Notes
             * @description A note stored with the application
             */
            notes?: string | null;
            /**
             * Status
             * @description The status to move to
             */
            status: string;
        };
        /**
         * StoredTailoringResponse
         * @description A stored tailoring record (adds the creation time).
         */
        StoredTailoringResponse: {
            ats_report: components["schemas"]["AtsReport"];
            /** Created At */
            created_at: string;
            /** Docx Path */
            docx_path: string;
            factuality: components["schemas"]["FactualityReport"];
            insights: components["schemas"]["JobInsights"];
            /** Job Id */
            job_id: string;
            /** Profile Id */
            profile_id: string;
            tailored: components["schemas"]["TailoredResume"];
            /** Tailoring Id */
            tailoring_id: string;
        };
        /**
         * TailoredExperience
         * @description One experience entry as it should appear in the tailored resume.
         */
        TailoredExperience: {
            /**
             * Bullets
             * @description Achievement bullets rephrased from profile facts only.
             */
            bullets: string[];
            /**
             * Company
             * @description Company name, copied exactly from the profile.
             */
            company: string;
            /**
             * Title
             * @description Job title, copied exactly from the profile.
             */
            title: string;
        };
        /**
         * TailoredProject
         * @description One project entry as it should appear in the tailored resume.
         */
        TailoredProject: {
            /**
             * Bullets
             * @description Project bullets rephrased from profile facts only.
             */
            bullets: string[];
            /**
             * Name
             * @description Project name, copied exactly from the profile.
             */
            name: string;
        };
        /**
         * TailoredResume
         * @description Tailored resume content produced from profile facts only.
         */
        TailoredResume: {
            /**
             * Cover Letter
             * @description Short cover letter draft using profile facts only.
             */
            cover_letter: string;
            /** Experience */
            experience: components["schemas"]["TailoredExperience"][];
            /**
             * Highlighted Skills
             * @description Skills drawn from the profile that match the job.
             */
            highlighted_skills: string[];
            /**
             * Projects
             * @description Profile projects relevant to the job (use instead of invented employment).
             */
            projects?: components["schemas"]["TailoredProject"][];
            /**
             * Summary
             * @description Short professional summary using profile facts only.
             */
            summary: string;
        };
        /**
         * TailorRequest
         * @description Request body for a tailoring run.
         */
        TailorRequest: {
            /**
             * Job Id
             * @description Canonical job id (source:id)
             */
            job_id: string;
            /**
             * Profile Id
             * @description Id returned by POST /api/resumes
             */
            profile_id: string;
        };
        /**
         * TailorResponse
         * @description The tailoring result, its reports and the rendered file path.
         */
        TailorResponse: {
            ats_report: components["schemas"]["AtsReport"];
            /** Docx Path */
            docx_path: string;
            factuality: components["schemas"]["FactualityReport"];
            insights: components["schemas"]["JobInsights"];
            /** Job Id */
            job_id: string;
            /** Profile Id */
            profile_id: string;
            tailored: components["schemas"]["TailoredResume"];
            /** Tailoring Id */
            tailoring_id: string;
        };
        /**
         * UserCreate
         * @description What a registration may specify.
         */
        UserCreate: {
            /**
             * Email
             * Format: email
             */
            email: string;
            /** Full Name */
            full_name?: string | null;
            /**
             * Is Active
             * @default true
             */
            is_active: boolean | null;
            /**
             * Is Superuser
             * @default false
             */
            is_superuser: boolean | null;
            /**
             * Is Verified
             * @default false
             */
            is_verified: boolean | null;
            /** Password */
            password: string;
        };
        /**
         * UserRead
         * @description The public view of an account.
         */
        UserRead: {
            /**
             * Email
             * Format: email
             */
            email: string;
            /** Full Name */
            full_name?: string | null;
            /** Id */
            id: string;
            /**
             * Is Active
             * @default true
             */
            is_active: boolean;
            /**
             * Is Superuser
             * @default false
             */
            is_superuser: boolean;
            /**
             * Is Verified
             * @default false
             */
            is_verified: boolean;
        };
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
            email?: string | null;
            /** Full Name */
            full_name?: string | null;
            /** Password */
            password?: string | null;
        };
        /** ValidationError */
        ValidationError: {
            /** Context */
            ctx?: Record<string, never>;
            /** Input */
            input?: unknown;
            /** Location */
            loc: (string | number)[];
            /** Message */
            msg: string;
            /** Error Type */
            type: string;
        };
        /**
         * WorkAuthorizationInfo
         * @description Three **distinct** question families — never conflated.
         *
         *     A candidate may be ``legally_authorized`` today *and* still
         *     ``requires_sponsorship`` for a future role or transfer. Filling one from
         *     the other would be a fabricated legal answer, so they are separate fields
         *     and each is only ever set by the user.
         */
        WorkAuthorizationInfo: {
            /** Authorized Countries */
            authorized_countries?: string[];
            /** Citizenship Status */
            citizenship_status?: string | null;
            /** Legally Authorized */
            legally_authorized?: boolean | null;
            /** Requires Sponsorship */
            requires_sponsorship?: boolean | null;
            /** Status Category */
            status_category?: string | null;
        };
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
            employment_types?: string[];
            /** Min Salary */
            min_salary?: string | null;
            /** Preferred Locations */
            preferred_locations?: string[];
            /** Remote Preference */
            remote_preference?: string | null;
            /** Work Authorization */
            work_authorization?: string | null;
        };
    };
    responses: never;
    parameters: never;
    requestBodies: never;
    headers: never;
    pathItems: never;
}
export type $defs = Record<string, never>;
export interface operations {
    root__get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": {
                        [key: string]: string;
                    };
                };
            };
        };
    };
    list_embedding_runs_api_admin_embedding_runs_get: {
        parameters: {
            query?: {
                limit?: number;
                status?: string | null;
            };
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AdminRunsResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    read_embedding_run_api_admin_embedding_runs__run_id__get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                run_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AdminRunDetailResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    cancel_embedding_run_api_admin_embedding_runs__run_id__cancel_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                run_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["RunActionResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    resume_embedding_run_api_admin_embedding_runs__run_id__resume_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                run_id: string;
            };
            cookie?: never;
        };
        requestBody?: {
            content: {
                "application/json": components["schemas"]["ResumeRunRequest"] | null;
            };
        };
        responses: {
            /** @description Successful Response */
            202: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["RunActionResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    reconcile_embeddings_api_admin_embeddings_reconcile_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            202: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["RunActionResponse"];
                };
            };
        };
    };
    read_worker_health_api_admin_health_workers_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": {
                        [key: string]: unknown;
                    };
                };
            };
        };
    };
    read_job_metrics_api_admin_jobs_metrics_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": {
                        [key: string]: unknown;
                    };
                };
            };
        };
    };
    read_overview_api_admin_overview_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": {
                        [key: string]: unknown;
                    };
                };
            };
        };
    };
    list_all_runs_api_admin_runs_get: {
        parameters: {
            query?: {
                job_type?: string | null;
                limit?: number;
                status?: string | null;
            };
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AdminRunsResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    read_any_run_api_admin_runs__run_id__get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                run_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AdminRunDetailResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    list_applications_api_applications_get: {
        parameters: {
            query?: {
                limit?: number;
                offset?: number;
                profile_id?: string | null;
                status?: string[] | null;
            };
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ApplicationListResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_application_api_applications__application_id__get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                application_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ApplicationDetailResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    list_application_evidence_api_applications__application_id__evidence_get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                application_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": {
                        [key: string]: unknown;
                    };
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    download_evidence_api_applications__application_id__evidence__filename__get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                application_id: string;
                filename: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": unknown;
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    update_application_status_api_applications__application_id__status_patch: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                application_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["StatusUpdateRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ApplicationDetailResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    approve_application_api_applications__approval_id__approve_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                approval_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["ApprovalDecisionRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ApprovalDecisionResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    reject_application_api_applications__approval_id__reject_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                approval_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["ApprovalDecisionRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ApprovalDecisionResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_approval_api_applications_approvals__approval_id__get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                approval_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ApprovalStatusResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    prepare_application_api_applications_prepare_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["ApplicationPrepareRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ApplicationPrepareResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    list_audit_events_api_audit_get: {
        parameters: {
            query?: {
                limit?: number;
            };
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": {
                        [key: string]: unknown;
                    };
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    auth_cookie_login_api_auth_cookie_login_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/x-www-form-urlencoded": components["schemas"]["Body_auth_cookie_login_api_auth_cookie_login_post"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": unknown;
                };
            };
            /** @description No Content */
            204: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description Bad Request */
            400: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorModel"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    auth_cookie_logout_api_auth_cookie_logout_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": unknown;
                };
            };
            /** @description No Content */
            204: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description Missing token or inactive user. */
            401: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
        };
    };
    reset_forgot_password_api_auth_forgot_password_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["Body_reset_forgot_password_api_auth_forgot_password_post"];
            };
        };
        responses: {
            /** @description Successful Response */
            202: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": unknown;
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    read_me_api_auth_me_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["UserRead"];
                };
            };
        };
    };
    request_account_deletion_api_auth_me_delete: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": {
                        [key: string]: unknown;
                    };
                };
            };
        };
    };
    update_me_api_auth_me_patch: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["UserUpdate"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["UserRead"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    register_register_api_auth_register_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["UserCreate"];
            };
        };
        responses: {
            /** @description Successful Response */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["UserRead"];
                };
            };
            /** @description Bad Request */
            400: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorModel"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    verify_request_token_api_auth_request_verify_token_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["Body_verify_request_token_api_auth_request_verify_token_post"];
            };
        };
        responses: {
            /** @description Successful Response */
            202: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": unknown;
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    reset_reset_password_api_auth_reset_password_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["Body_reset_reset_password_api_auth_reset_password_post"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": unknown;
                };
            };
            /** @description Bad Request */
            400: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorModel"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    read_sessions_api_auth_sessions_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": {
                        [key: string]: unknown;
                    };
                };
            };
        };
    };
    revoke_one_session_api_auth_sessions__token__delete: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                token: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": {
                        [key: string]: unknown;
                    };
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    revoke_every_session_api_auth_sessions_revoke_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": {
                        [key: string]: unknown;
                    };
                };
            };
        };
    };
    revoke_the_other_sessions_api_auth_sessions_revoke_others_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": {
                        [key: string]: unknown;
                    };
                };
            };
        };
    };
    auth_bearer_login_api_auth_token_login_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/x-www-form-urlencoded": components["schemas"]["Body_auth_bearer_login_api_auth_token_login_post"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    /**
                     * @example {
                     *       "access_token": "eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9.eyJ1c2VyX2lkIjoiOTIyMWZmYzktNjQwZi00MzcyLTg2ZDMtY2U2NDJjYmE1NjAzIiwiYXVkIjoiZmFzdGFwaS11c2VyczphdXRoIiwiZXhwIjoxNTcxNTA0MTkzfQ.M10bjOe45I5Ncu_uXvOmVV8QxnL-nZfcH96U90JaocI",
                     *       "token_type": "bearer"
                     *     }
                     */
                    "application/json": components["schemas"]["BearerResponse"];
                };
            };
            /** @description Bad Request */
            400: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorModel"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    auth_bearer_logout_api_auth_token_logout_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": unknown;
                };
            };
            /** @description Missing token or inactive user. */
            401: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
        };
    };
    verify_verify_api_auth_verify_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["Body_verify_verify_api_auth_verify_post"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["UserRead"];
                };
            };
            /** @description Bad Request */
            400: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorModel"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    list_documents_api_documents_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": {
                        [key: string]: unknown;
                    };
                };
            };
        };
    };
    download_document_api_documents__document_id__download_get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                document_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": unknown;
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    health_check_api_health_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": {
                        [key: string]: string;
                    };
                };
            };
        };
    };
    liveness_api_health_live_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": {
                        [key: string]: string;
                    };
                };
            };
        };
    };
    readiness_api_health_ready_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": unknown;
                };
            };
        };
    };
    get_job_api_jobs__job_id__get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                job_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": {
                        [key: string]: unknown;
                    };
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    refresh_jobs_endpoint_api_jobs_refresh_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            202: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["RunAcceptedResponse"];
                };
            };
        };
    };
    search_jobs_api_jobs_search_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["JobSearchRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["JobSearchResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_application_profile_api_profiles__profile_id__application_profile_get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                profile_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ApplicationProfileResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    put_application_profile_api_profiles__profile_id__application_profile_put: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                profile_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["ApplicationProfile"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ApplicationProfileResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_eeo_api_profiles__profile_id__eeo_get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                profile_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["EeoResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    put_eeo_api_profiles__profile_id__eeo_put: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                profile_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["EeoProfile"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["EeoResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    delete_eeo_api_profiles__profile_id__eeo_delete: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                profile_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            204: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_profile_matches_api_profiles__profile_id__matches_get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                profile_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["MatchesHistoryResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    upload_resume_api_resumes_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "multipart/form-data": components["schemas"]["Body_upload_resume_api_resumes_post"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ResumeUploadResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_resume_api_resumes__profile_id__get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                profile_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ResumeProfileResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    list_runs_api_runs_get: {
        parameters: {
            query?: {
                limit?: number;
            };
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["RunsListResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_run_api_runs__run_id__get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                run_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["RunDetailResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    tailor_resume_endpoint_api_tailor_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["TailorRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["TailorResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_tailored_api_tailored__tailoring_id__get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                tailoring_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["StoredTailoringResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    download_tailored_docx_api_tailored__tailoring_id__download_get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                tailoring_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": unknown;
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
}
