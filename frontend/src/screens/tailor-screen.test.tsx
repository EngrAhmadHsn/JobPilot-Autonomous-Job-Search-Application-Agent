import { screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { http, HttpResponse } from "msw"
import { describe, expect, it } from "vitest"

import { setCurrentProfileId } from "@/lib/profile"
import { server } from "@/test/server"
import { renderApp } from "@/test/render"
import { jobListing, tailorResponse } from "@/test/factories"

const BASE = "http://api.test"
const ROUTE = `/app/tailor/${encodeURIComponent("greenhouse:1")}`

describe("the tailor index", () => {
  it("has a heading even when there is no profile to tailor", async () => {
    renderApp({ route: "/app/tailor" })

    // A screen that shows only an empty state, with no heading, reads as a
    // broken screen. The heading says what the screen is for; the empty
    // state says what to do next.
    expect(
      await screen.findByRole("heading", {
        name: /Tailor the résumé for a job/i,
        level: 1,
      })
    ).toBeInTheDocument()
    expect(
      screen.getByText("Tailoring needs a résumé first")
    ).toBeInTheDocument()
  })

  it("lists one row per job, best match first (WS-21)", async () => {
    setCurrentProfileId("profile-1")
    let requested = ""
    server.use(
      http.get(`${BASE}/api/profiles/:profileId/matches`, ({ request }) => {
        requested = new URL(request.url).search
        return HttpResponse.json({
          profile_id: "profile-1",
          matches: [
            {
              profile_id: "profile-1",
              job_id: "job-b",
              scores: { overall_score: 91 },
              explanation: "",
              created_at: "2026-11-08T12:00:00Z",
            },
            {
              profile_id: "profile-1",
              job_id: "job-d",
              scores: { overall_score: 84 },
              explanation: "",
              created_at: "2026-11-08T11:00:00Z",
            },
            {
              profile_id: "profile-1",
              job_id: "job-c",
              scores: { overall_score: 72 },
              explanation: "",
              created_at: "2026-11-08T10:00:00Z",
            },
            {
              profile_id: "profile-1",
              job_id: "job-a",
              scores: { overall_score: 45 },
              explanation: "",
              created_at: "2026-11-08T09:00:00Z",
            },
          ],
        })
      }),
      http.get(`${BASE}/api/jobs/:jobId`, ({ params }) =>
        HttpResponse.json({
          job: jobListing({
            id: String(params.jobId),
            title: `Role ${String(params.jobId)}`,
          }),
        })
      )
    )
    renderApp({ route: "/app/tailor" })

    const titles = await screen.findAllByText(/^Role job-/)
    // One row per job, in the order the server ranked them (best first) —
    // the screen never re-sorts or slices what it was given.
    expect(titles.map((element) => element.textContent)).toEqual([
      "Role job-b",
      "Role job-d",
      "Role job-c",
      "Role job-a",
    ])
    // The server was asked for the ranked view — not the raw history.
    expect(requested).toContain("ranked=true")
    expect(requested).toContain("limit=25")
  })
})

describe("the tailor screen", () => {
  it("tails the resume and shows the reports", async () => {
    setCurrentProfileId("profile-1")
    const user = userEvent.setup()
    renderApp({ route: ROUTE })

    await user.click(
      await screen.findByRole("button", { name: "Tailor this resume" })
    )

    expect(
      await screen.findByText("The tailored resume is ready")
    ).toBeInTheDocument()
    expect(screen.getByText("Factuality report")).toBeInTheDocument()
    expect(screen.getByText("ATS report")).toBeInTheDocument()
    expect(screen.getByText("Grounded job insights")).toBeInTheDocument()
    expect(
      screen.getByText(
        "AI Engineer with analytical and machine learning experience."
      )
    ).toBeInTheDocument()
  })

  it("offers the rendered DOCX for download", async () => {
    setCurrentProfileId("profile-1")
    const user = userEvent.setup()
    renderApp({ route: ROUTE })

    await user.click(
      await screen.findByRole("button", { name: "Tailor this resume" })
    )

    const link = await screen.findByRole("link", { name: "Download the DOCX" })
    expect(link).toHaveAttribute(
      "href",
      "http://api.test/api/tailored/tailoring-1/download"
    )
  })

  it("renders a factuality failure as content, not as an error", async () => {
    server.use(
      http.post(`${BASE}/api/tailor`, () =>
        HttpResponse.json(
          tailorResponse({
            factuality: {
              passed: false,
              removed_skills: ["Kubernetes"],
              removed_experience: ["Chief Scientist"],
              removed_projects: [],
              violations: ["'Kubernetes' is not stated by the resume"],
            },
          })
        )
      )
    )
    setCurrentProfileId("profile-1")
    const user = userEvent.setup()
    renderApp({ route: ROUTE })

    await user.click(
      await screen.findByRole("button", { name: "Tailor this resume" })
    )

    expect(
      await screen.findByText(/unsupported item\(s\) were removed/)
    ).toBeInTheDocument()
    expect(screen.getByText("Kubernetes")).toBeInTheDocument()
    expect(screen.getByText("Chief Scientist")).toBeInTheDocument()
    expect(
      screen.getByText("'Kubernetes' is not stated by the resume")
    ).toBeInTheDocument()
    // A failed factuality report is not an error: no error banner.
    expect(
      screen.queryByText(/The server refused the request/)
    ).not.toBeInTheDocument()
  })

  it("says so when the language model is unavailable", async () => {
    server.use(
      http.post(`${BASE}/api/tailor`, () =>
        HttpResponse.json(
          { detail: "The language model is unavailable; try again later." },
          { status: 503 }
        )
      )
    )
    setCurrentProfileId("profile-1")
    const user = userEvent.setup()
    renderApp({ route: ROUTE })

    await user.click(
      await screen.findByRole("button", { name: "Tailor this resume" })
    )

    expect(
      await screen.findByText(
        "The language model is unavailable; try again later."
      )
    ).toBeInTheDocument()
  })

  it("asks for a profile before it can tailor", async () => {
    renderApp({ route: ROUTE })

    await waitFor(() => {
      expect(
        screen.getByText("Tailoring needs a résumé first")
      ).toBeInTheDocument()
    })
  })
})
