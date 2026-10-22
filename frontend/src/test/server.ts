import { http, HttpResponse } from "msw"
import { setupServer } from "msw/node"

import {
  applicationDetail,
  applicationEvidence,
  applicationList,
  approvalDecision,
  healthResponse,
  identityResponse,
  jobDetail,
  jobSearchResponse,
  matchesHistory,
  profileResponse,
  refreshResponse,
  resumeUploadResponse,
  tailorResponse,
  tailoredResponse,
} from "./factories"

/**
 * The mocked API.
 *
 * The handlers answer the routes the console uses with payloads that are
 * shaped exactly like the backend's (they are built from the same OpenAPI
 * schema), so a test that passes against the mock is testing the console's
 * handling of the **real** shapes.
 *
 * A test overrides a route with `server.use(...)` when it needs a different
 * answer — a 429, a 503, a factuality failure.
 */
const BASE = "http://api.test"

export const server = setupServer(
  http.get(`${BASE}/api/health`, () => HttpResponse.json(healthResponse())),

  // The identity (WS-14). The mocked console is signed in by default,
  // so the screens render; a test that needs the signed-out state
  // overrides this route with a 401.
  http.get(`${BASE}/api/auth/me`, () => HttpResponse.json(identityResponse())),
  http.post(
    `${BASE}/api/auth/cookie/login`,
    () => new HttpResponse(null, { status: 204 })
  ),
  http.post(
    `${BASE}/api/auth/cookie/logout`,
    () => new HttpResponse(null, { status: 204 })
  ),
  http.post(`${BASE}/api/auth/register`, () =>
    HttpResponse.json(identityResponse(), { status: 201 })
  ),

  http.post(`${BASE}/api/resumes`, () =>
    HttpResponse.json(resumeUploadResponse())
  ),
  http.get(`${BASE}/api/resumes/:profileId`, () =>
    HttpResponse.json(profileResponse())
  ),

  http.post(`${BASE}/api/jobs/search`, () =>
    HttpResponse.json(jobSearchResponse())
  ),
  http.get(`${BASE}/api/jobs/:jobId`, () => HttpResponse.json(jobDetail())),
  http.get(`${BASE}/api/profiles/:profileId/matches`, () =>
    HttpResponse.json(matchesHistory())
  ),

  http.post(`${BASE}/api/tailor`, () => HttpResponse.json(tailorResponse())),
  http.get(`${BASE}/api/tailored/:tailoringId`, () =>
    HttpResponse.json(tailoredResponse())
  ),

  http.post(`${BASE}/api/applications/prepare`, () =>
    HttpResponse.json({
      approval_id: "approval-1",
      workflow_id: "workflow-1",
      adapter_name: "fake-ats",
      status: "awaiting_approval",
      prepared_summary: {
        job_title: "AI Engineer",
        company_name: "Acme",
        job_url: "http://127.0.0.1:8901/basic",
        adapter_name: "fake-ats",
        field_names: ["email", "name", "phone"],
        profile_fact_names: ["email", "name", "phone"],
        resume_path: null,
        requires_manual_review: false,
      },
      application_id: "application-1",
    })
  ),
  http.post(`${BASE}/api/applications/:approvalId/approve`, () =>
    HttpResponse.json(approvalDecision())
  ),
  http.post(`${BASE}/api/applications/:approvalId/reject`, () =>
    HttpResponse.json(approvalDecision())
  ),
  http.get(`${BASE}/api/applications/approvals/:approvalId`, () =>
    HttpResponse.json({
      approval_id: "approval-1",
      workflow_id: "workflow-1",
      adapter_name: "fake-ats",
      job_url: "http://127.0.0.1:8901/basic",
      job_title: "AI Engineer",
      company_name: "Acme",
      status: "pending",
      approver: null,
      decision_reason: null,
      created_at: "2026-10-21T10:00:00Z",
      decided_at: null,
      success: null,
      message: null,
    })
  ),

  http.get(`${BASE}/api/applications`, () =>
    HttpResponse.json(applicationList())
  ),
  http.get(`${BASE}/api/applications/:applicationId/evidence`, () =>
    HttpResponse.json(applicationEvidence())
  ),
  http.get(`${BASE}/api/applications/:applicationId`, () =>
    HttpResponse.json(applicationDetail())
  ),
  http.patch(`${BASE}/api/applications/:applicationId/status`, () =>
    HttpResponse.json(applicationDetail())
  ),

  http.get(`${BASE}/api/documents`, () =>
    HttpResponse.json({
      documents: [
        {
          id: "profile-profile-1",
          kind: "resume",
          title: "Résumé — Ada Lovelace",
          filename: "profile-1.docx",
          path: "data/resumes/profile-1.docx",
          size_bytes: 24576,
          created_at: "2026-10-21T10:00:00Z",
          profile_id: "profile-1",
          job_id: null,
        },
        {
          id: "tailored-tailoring-1",
          kind: "tailored",
          title: "Tailored résumé — greenhouse:1",
          filename: "tailoring-1.docx",
          path: "data/tailored/tailoring-1.docx",
          size_bytes: 18944,
          created_at: "2026-10-21T11:00:00Z",
          profile_id: "profile-1",
          job_id: "greenhouse:1",
        },
      ],
      count: 2,
    })
  ),

  http.post(`${BASE}/api/jobs/refresh`, () =>
    HttpResponse.json(refreshResponse())
  )
)
