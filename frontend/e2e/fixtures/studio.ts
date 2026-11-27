import { test as base, expect } from "@playwright/test"
import { basename } from "node:path"
import { fileURLToPath } from "node:url"

import type {
  DocumentRecord,
  StoredTailoring,
  TailoredEditRequest,
  TailorRequest,
} from "../../src/lib/api/types"
import {
  applicationProfileResponse,
  candidateProfile,
  healthResponse,
  identityResponse,
  jobListing,
  tailorResponse,
} from "../../src/test/factories"

const jobDescription =
  "Build Python APIs with FastAPI and PostgreSQL. Maintain automated testing, Kubernetes, and Terraform."
export const job = jobListing({
  id: "greenhouse:studio-backend",
  source_job_id: "studio-backend",
  title: "Backend Engineer",
  company: "Northstar Labs",
  description: jobDescription,
  required_skills: ["Python", "FastAPI", "PostgreSQL", "Kubernetes"],
  preferred_skills: ["FastAPI", "automated testing", "Terraform"],
})

export const originalSummary =
  "Backend developer building services with Python. Experience with APIs, PostgreSQL, and automated testing."
export const originalBullet =
  "Built API endpoints with FastAPI and wrote database queries in PostgreSQL."
export const proposedSummary =
  "Backend developer focused on Python APIs and PostgreSQL."
export const proposedBullet =
  "Developed API endpoints using FastAPI and PostgreSQL."
export const proposedLetter =
  "Dear hiring team, I develop Python APIs with FastAPI."
export const savedSummary =
  "Backend engineer building Python APIs with PostgreSQL and automated testing."
export const savedLetter =
  "Dear hiring team, I build Python APIs with FastAPI and PostgreSQL."

const originalProfileId = "studio-source"
const alternateProfileId = "studio-other-source"
const originalProfile = candidateProfile({
  personal_information: {
    name: "Alex Rivera",
    title: job.title,
    email: "alex.rivera@example.com",
    phone: "",
    location: "",
    website: "",
  },
  summary: originalSummary,
  experience: [
    {
      title: job.title,
      company: "Example Software",
      dates: "2022–2025",
      years: 3,
      bullets: [originalBullet],
    },
  ],
  skills: ["Python", "FastAPI", "PostgreSQL", "automated testing"],
  skill_categories: {},
  education: [],
  projects: [],
})
const alternateProfile = candidateProfile()
export const alternateSummary = alternateProfile.summary
export const alternateTitle = `Résumé — ${alternateProfile.personal_information.name}`
export const alternateFilename = "alternate-source.docx"

const draftId = "studio-draft-1"
export const draftFilename = `${draftId}.docx`
const createdAt = "2026-10-21T10:00:00Z"
const proposedCoverage = {
  required_coverage: 3 / 4,
  required_hit: ["Python", "FastAPI", "PostgreSQL"],
  required_missing: ["Kubernetes"],
  preferred_coverage: 1 / 3,
  preferred_hit: ["FastAPI"],
  preferred_missing: ["automated testing", "Terraform"],
}
const baseProposal = tailorResponse()
const proposal = tailorResponse({
  tailoring_id: draftId,
  job_id: job.id,
  profile_id: originalProfileId,
  docx_path: `./data/tailored/${draftFilename}`,
  tailored: {
    summary: proposedSummary,
    highlighted_skills: ["Python", "FastAPI", "PostgreSQL"],
    experience: [
      {
        title: job.title,
        company: "Example Software",
        bullets: [proposedBullet],
      },
    ],
    projects: [],
    cover_letter: proposedLetter,
  },
  ats_report: {
    ...baseProposal.ats_report,
    score: 81,
    keyword_coverage: proposedCoverage,
  },
  render: { ...baseProposal.render, edits: 2 },
  insights: {
    responsibilities: ["Build and maintain Python APIs"],
    tech_stack: job.required_skills,
    seniority_signals: [],
    culture_flags: [],
    summary: jobDescription,
  },
})

// Newer, same job and source. Opening by job or "latest" can't satisfy the
// exact-draft checks; the library id also has the API's real `tailored-` prefix.
const otherDraft: StoredTailoring = {
  ...proposal,
  tailoring_id: "studio-draft-2",
  docx_path: "./data/tailored/studio-draft-2.docx",
  created_at: "2026-10-21T11:00:00Z",
  edited_at: null,
  tailored: {
    ...proposal.tailored,
    summary: "Python services and database APIs.",
  },
}
export const otherDraftFilename = basename(otherDraft.docx_path)

export const jobRoute = `/app/tailor/${encodeURIComponent(job.id)}`
export const draftRoute = `${jobRoute}?draft=${encodeURIComponent(draftId)}`
export const draftApiPath = `/api/tailored/${encodeURIComponent(draftId)}`
export const downloadPath = `${draftApiPath}/download`

// The tracked synthetic DOCX stands in for a file attachment. This fixture
// does not run or validate the DOCX renderer.
const syntheticDocx = fileURLToPath(
  new URL(
    "../../../tests/evaluation/golden/resumes/alex_rivera_backend.docx",
    import.meta.url
  )
)

function tailoredDocument(draft: StoredTailoring): DocumentRecord {
  return {
    id: `tailored-${draft.tailoring_id}`,
    kind: "tailored",
    title: `Tailored résumé — ${draft.job_id}`,
    filename: basename(draft.docx_path),
    path: draft.docx_path,
    size_bytes: null,
    created_at: draft.created_at,
    profile_id: draft.profile_id,
    job_id: draft.job_id,
  }
}

const originals: DocumentRecord[] = [
  {
    id: `profile-${alternateProfileId}`,
    kind: "resume",
    title: alternateTitle,
    filename: alternateFilename,
    path: `./data/resumes/${alternateFilename}`,
    size_bytes: null,
    created_at: "2026-10-20T10:00:00Z",
    profile_id: alternateProfileId,
    job_id: null,
  },
  {
    id: `profile-${originalProfileId}`,
    kind: "resume",
    title: `Résumé — ${originalProfile.personal_information.name}`,
    filename: "original-source.docx",
    path: "./data/resumes/original-source.docx",
    size_bytes: null,
    created_at: "2026-10-19T10:00:00Z",
    profile_id: originalProfileId,
    job_id: null,
  },
]

const apiProfiles = {
  [originalProfileId]: originalProfile,
  [alternateProfileId]: alternateProfile,
}

/** Isolated UI/browser integration: every API response is local to one test. */
export const test = base.extend<{ seedDraft: boolean; studioApi: void }>({
  seedDraft: [false, { option: true }],
  studioApi: [
    async ({ baseURL, context, seedDraft }, use) => {
      if (!baseURL) throw new Error("Studio requires the console baseURL")
      const origin = new URL(baseURL).origin
      let draft: StoredTailoring | undefined = seedDraft
        ? { ...proposal, created_at: createdAt, edited_at: null }
        : undefined
      const unexpected: string[] = []

      // Seed an existing synthetic profile without a cookie, a login, or a
      // real upload. The operator can still switch profiles in the browser.
      await context.addInitScript(
        ({ origin, profileId }) => {
          if (
            location.origin === origin &&
            !localStorage.getItem("aja.currentProfileId")
          ) {
            localStorage.setItem("aja.currentProfileId", profileId)
          }
        },
        { origin, profileId: originalProfileId }
      )

      await context.route(
        (url) =>
          url.origin !== origin ||
          url.pathname === "/api" ||
          url.pathname.startsWith("/api/"),
        async (route) => {
          const request = route.request()
          const url = new URL(request.url())
          const key = `${request.method()} ${url.pathname}`
          const reject = async (reason: string) => {
            unexpected.push(`${key}: ${reason}`)
            await route.abort("blockedbyclient")
          }

          if (url.origin !== origin) {
            return reject(
              "cross-origin request; use a same-origin console build"
            )
          }

          switch (key) {
            case "GET /api/auth/me":
              return route.fulfill({ json: identityResponse() })
            case "GET /api/health":
              return route.fulfill({ json: healthResponse() })
            case "GET /api/documents": {
              const documents = [
                tailoredDocument(otherDraft),
                ...(draft ? [tailoredDocument(draft)] : []),
                ...originals,
              ]
              return route.fulfill({
                json: { documents, count: documents.length },
              })
            }
            case `GET /api/jobs/${encodeURIComponent(job.id)}`:
              return route.fulfill({ json: { job } })
            case "POST /api/tailor": {
              const body = request.postDataJSON() as TailorRequest | null
              if (
                draft ||
                body?.profile_id !== originalProfileId ||
                body.job_id !== job.id
              ) {
                return reject("unexpected generation or the wrong job/profile")
              }
              draft = { ...proposal, created_at: createdAt, edited_at: null }
              return route.fulfill({ json: proposal })
            }
            case `GET ${draftApiPath}`:
              if (draft) return route.fulfill({ json: draft })
              return reject("asked for the draft before it was generated")
            case `GET /api/tailored/${encodeURIComponent(otherDraft.tailoring_id)}`:
              return route.fulfill({ json: otherDraft })
            case `PUT ${draftApiPath}`: {
              const body = request.postDataJSON() as TailoredEditRequest | null
              if (
                !draft ||
                body?.summary !== savedSummary ||
                body.cover_letter?.trim() !== savedLetter
              ) {
                return reject(
                  "save did not address the intended draft and edits"
                )
              }
              draft = {
                ...draft,
                edited_at: "2026-10-21T10:10:00Z",
                tailored: {
                  ...draft.tailored,
                  summary: body.summary,
                  cover_letter: body.cover_letter.trim(),
                },
                ats_report: {
                  ...draft.ats_report,
                  score: 85,
                  keyword_coverage: {
                    ...proposedCoverage,
                    preferred_coverage: 2 / 3,
                    preferred_hit: ["FastAPI", "automated testing"],
                    preferred_missing: ["Terraform"],
                  },
                },
              }
              return route.fulfill({ json: draft })
            }
            case `GET ${downloadPath}`:
              if (!draft?.edited_at)
                return reject("asked for a draft that wasn't saved")
              return route.fulfill({
                path: syntheticDocx,
                contentType:
                  "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                headers: {
                  "Content-Disposition": `attachment; filename="${draftFilename}"`,
                },
              })
          }

          if (request.method() === "GET") {
            for (const [profileId, profile] of Object.entries(apiProfiles)) {
              switch (url.pathname) {
                case `/api/resumes/${profileId}`:
                  return route.fulfill({
                    json: { profile_id: profileId, profile },
                  })
                case `/api/profiles/${profileId}/application-profile`:
                  return route.fulfill({
                    json: {
                      ...applicationProfileResponse(
                        profile.application_profile
                      ),
                      profile_id: profileId,
                    },
                  })
                case `/api/profiles/${profileId}/question-gaps`:
                  return route.fulfill({
                    json: {
                      profile_id: profileId,
                      total_observed: 0,
                      questions: [],
                    },
                  })
              }
            }
          }

          return reject("not in the Studio fixture")
        }
      )

      await use()
      expect(unexpected, "No API calls may escape the Studio fixture").toEqual(
        []
      )
    },
    { auto: true },
  ],
})
