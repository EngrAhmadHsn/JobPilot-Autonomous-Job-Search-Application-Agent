/**
 * One function per API route.
 *
 * The routes, the request bodies and the response shapes all come from the
 * generated OpenAPI schema — this file only says **where** each call goes
 * and **how long** the console is willing to wait for it.
 *
 * The timeouts are chosen from what the backend actually does (the tailoring
 * run is ~80 s, the corpus refresh takes minutes, a search is ~10 s) and
 * they are the *client's* bound, not the server's: the server may still be
 * working after the console gave up, and the console says so.
 */
import { request, requestForm } from "./client"
import type {
  ApplicationDetail,
  DocumentRecord,
  ApplicationEvidenceRecord,
  ApplicationList,
  ApplicationPrepareRequest,
  ApplicationPrepareResponse,
  ApprovalDecisionRequest,
  ApprovalDecisionResponse,
  ApprovalStatus,
  Health,
  Identity,
  JobDetail,
  JobRefreshResponse,
  JobSearchRequest,
  JobSearchResponse,
  MatchesHistory,
  ResumeProfileResponse,
  ResumeUploadResponse,
  StatusUpdateRequest,
  StoredTailoring,
  TailorRequest,
  TailorResponse,
} from "./types"

export interface ListApplicationsParams {
  status?: string[]
  profile_id?: string
  limit?: number
  offset?: number
}

export const api = {
  /** Is the API up? */
  health: (signal?: AbortSignal) =>
    request<Health>("/api/health", { signal, timeoutMs: 8_000 }),

  /**
   * The authenticated principal.
   *
   * A 401 is the answer for a caller with no session, so the console
   * asks this on every load and shows the sign-in screen when it is
   * refused.
   */
  identity: (signal?: AbortSignal) =>
    request<Identity>("/api/auth/me", { signal, timeoutMs: 8_000 }),

  /**
   * Sign in.
   *
   * The session is an `HttpOnly` cookie the server sets, so there is
   * nothing to hold in JavaScript — the request carries the credentials
   * and the response carries a cookie.
   */
  signIn: (email: string, password: string, signal?: AbortSignal) =>
    requestForm(
      "/api/auth/cookie/login",
      { username: email, password },
      signal
    ),

  /** End the session, server-side. */
  signOut: (signal?: AbortSignal) =>
    request<void>("/api/auth/cookie/logout", {
      method: "POST",
      signal,
      timeoutMs: 8_000,
    }),

  /** Create an account. */
  createAccount: (email: string, password: string, signal?: AbortSignal) =>
    request<Identity>("/api/auth/register", {
      method: "POST",
      json: { email, password },
      signal,
      timeoutMs: 15_000,
    }),

  /** Upload a resume (DOCX/TXT/MD, <= 5 MB) and get the parsed profile. */
  uploadResume: (file: File, signal?: AbortSignal) => {
    const formData = new FormData()
    formData.append("file", file)
    return request<ResumeUploadResponse>("/api/resumes", {
      method: "POST",
      formData,
      signal,
      timeoutMs: 120_000,
    })
  },

  /** The stored profile for one upload. */
  getResume: (profileId: string, signal?: AbortSignal) =>
    request<ResumeProfileResponse>(
      `/api/resumes/${encodeURIComponent(profileId)}`,
      {
        signal,
        timeoutMs: 20_000,
      }
    ),

  /** Match the stored profile against the persisted job corpus. */
  searchJobs: (body: JobSearchRequest, signal?: AbortSignal) =>
    request<JobSearchResponse>("/api/jobs/search", {
      method: "POST",
      json: body,
      signal,
      timeoutMs: 120_000,
    }),

  /** One stored job listing. */
  getJob: (jobId: string, signal?: AbortSignal) =>
    request<JobDetail>(`/api/jobs/${encodeURIComponent(jobId)}`, {
      signal,
      timeoutMs: 20_000,
    }),

  /** The persisted match history for one profile. */
  getProfileMatches: (profileId: string, signal?: AbortSignal) =>
    request<MatchesHistory>(
      `/api/profiles/${encodeURIComponent(profileId)}/matches`,
      {
        signal,
        timeoutMs: 30_000,
      }
    ),

  /** Tailor the profile's resume for one job (~80 s). */
  tailor: (body: TailorRequest, signal?: AbortSignal) =>
    request<TailorResponse>("/api/tailor", {
      method: "POST",
      json: body,
      signal,
      timeoutMs: 300_000,
    }),

  /** One stored tailoring record. */
  getTailored: (tailoringId: string, signal?: AbortSignal) =>
    request<StoredTailoring>(
      `/api/tailored/${encodeURIComponent(tailoringId)}`,
      {
        signal,
        timeoutMs: 30_000,
      }
    ),

  /** Prepare an application for review. Nothing is submitted. */
  prepareApplication: (body: ApplicationPrepareRequest, signal?: AbortSignal) =>
    request<ApplicationPrepareResponse>("/api/applications/prepare", {
      method: "POST",
      json: body,
      signal,
      timeoutMs: 120_000,
    }),

  /** Approve a prepared application and execute the persisted payload. */
  approve: (
    approvalId: string,
    body: ApprovalDecisionRequest,
    signal?: AbortSignal
  ) =>
    request<ApprovalDecisionResponse>(
      `/api/applications/${encodeURIComponent(approvalId)}/approve`,
      { method: "POST", json: body, signal, timeoutMs: 300_000 }
    ),

  /** Reject a prepared application. Nothing is submitted. */
  reject: (
    approvalId: string,
    body: ApprovalDecisionRequest,
    signal?: AbortSignal
  ) =>
    request<ApprovalDecisionResponse>(
      `/api/applications/${encodeURIComponent(approvalId)}/reject`,
      { method: "POST", json: body, signal, timeoutMs: 60_000 }
    ),

  /** The stored state of an approval request. */
  getApproval: (approvalId: string, signal?: AbortSignal) =>
    request<ApprovalStatus>(
      `/api/applications/approvals/${encodeURIComponent(approvalId)}`,
      {
        signal,
        timeoutMs: 30_000,
      }
    ),

  /** A page of tracked applications. */
  listApplications: (params: ListApplicationsParams, signal?: AbortSignal) =>
    request<ApplicationList>("/api/applications", {
      query: {
        status: params.status,
        profile_id: params.profile_id,
        limit: params.limit,
        offset: params.offset,
      },
      signal,
      timeoutMs: 30_000,
    }),

  /** One tracked application with its full, ordered history. */
  getApplication: (applicationId: string, signal?: AbortSignal) =>
    request<ApplicationDetail>(
      `/api/applications/${encodeURIComponent(applicationId)}`,
      {
        signal,
        timeoutMs: 30_000,
      }
    ),

  /** Record a human outcome on a tracked application. */
  updateApplicationStatus: (
    applicationId: string,
    body: StatusUpdateRequest,
    signal?: AbortSignal
  ) =>
    request<ApplicationDetail>(
      `/api/applications/${encodeURIComponent(applicationId)}/status`,
      {
        method: "PATCH",
        json: body,
        signal,
        timeoutMs: 60_000,
      }
    ),

  /** The evidence records of one tracked application. */
  listApplicationEvidence: (applicationId: string, signal?: AbortSignal) =>
    request<{ evidence: ApplicationEvidenceRecord[] }>(
      `/api/applications/${encodeURIComponent(applicationId)}/evidence`,
      { signal, timeoutMs: 30_000 }
    ),

  /**
   * The account's document library.
   *
   * The uploaded résumés and the tailored résumés the agent produced, so
   * the console can show what the account already has instead of asking
   * the operator to type a server-side path.
   */
  documents: (signal?: AbortSignal) =>
    request<{ documents: DocumentRecord[]; count: number }>("/api/documents", {
      signal,
      timeoutMs: 20_000,
    }),

  /** Run the decoupled corpus refresh (boards → normalize → persist → embed). */
  refreshJobs: (signal?: AbortSignal) =>
    request<JobRefreshResponse>("/api/jobs/refresh", {
      method: "POST",
      signal,
      timeoutMs: 900_000,
    }),
}
