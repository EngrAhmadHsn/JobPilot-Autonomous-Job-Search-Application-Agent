import { screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { http, HttpResponse } from "msw"
import { describe, expect, it } from "vitest"

import { MatchesScreen } from "@/screens/matches-screen"
import { jobSearchResponse } from "@/test/factories"
import { setCurrentProfileId } from "@/lib/profile"
import { server } from "@/test/server"
import { renderApp, renderScreen } from "@/test/render"

const BASE = "http://api.test"

function withProfile() {
  setCurrentProfileId("profile-1")
}

describe("the matches screen", () => {
  it("asks for a profile before it can search", () => {
    renderScreen(<MatchesScreen />)

    expect(screen.getByText("No profile selected")).toBeInTheDocument()
  })

  it("ranks the matches and explains the ranking", async () => {
    withProfile()
    const user = userEvent.setup()
    renderScreen(<MatchesScreen />)

    await user.click(screen.getByRole("button", { name: "Search" }))

    expect(await screen.findByText("AI Engineer")).toBeInTheDocument()
    expect(screen.getByText("82.5")).toBeInTheDocument()

    await user.click(screen.getByText("Why this score"))
    expect(
      screen.getByText(
        "The profile states Python and SQL, which the listing asks for."
      )
    ).toBeInTheDocument()
  })

  it("says so when the scoring was degraded", async () => {
    withProfile()
    server.use(
      http.post(`${BASE}/api/jobs/search`, () =>
        HttpResponse.json(jobSearchResponse({ degraded: true }))
      )
    )
    const user = userEvent.setup()
    renderScreen(<MatchesScreen />)

    await user.click(screen.getByRole("button", { name: "Search" }))

    expect(
      await screen.findByText("The scoring was degraded")
    ).toBeInTheDocument()
  })

  it("names the job sources that failed", async () => {
    withProfile()
    server.use(
      http.post(`${BASE}/api/jobs/search`, () =>
        HttpResponse.json(
          jobSearchResponse({
            source_errors: { remotive: "getaddrinfo failed" },
          })
        )
      )
    )
    const user = userEvent.setup()
    renderScreen(<MatchesScreen />)

    await user.click(screen.getByRole("button", { name: "Search" }))

    expect(
      await screen.findByText("1 job source(s) failed")
    ).toBeInTheDocument()
    expect(screen.getByText("remotive")).toBeInTheDocument()
    expect(screen.getByText("getaddrinfo failed")).toBeInTheDocument()
  })

  it("shows the server's refusal of a search", async () => {
    withProfile()
    server.use(
      http.post(`${BASE}/api/jobs/search`, () =>
        HttpResponse.json(
          { detail: "Profile 'nope' not found" },
          { status: 404 }
        )
      )
    )
    const user = userEvent.setup()
    renderScreen(<MatchesScreen />)

    await user.click(screen.getByRole("button", { name: "Search" }))

    expect(
      await screen.findByText("Profile 'nope' not found")
    ).toBeInTheDocument()
  })
})

describe("the job detail screen", () => {
  it("shows the listing and the match the profile scored", async () => {
    withProfile()
    renderApp({ route: `/matches/${encodeURIComponent("greenhouse:1")}` })

    await waitFor(() => {
      expect(screen.getByText("The listing")).toBeInTheDocument()
    })
    expect(
      screen.getByText(
        "Build machine learning systems for a payments platform."
      )
    ).toBeInTheDocument()
    expect(screen.getByText("Why this job ranked")).toBeInTheDocument()
  })

  it("renders a hostile description as text, never as markup", async () => {
    withProfile()
    server.use(
      http.get(`${BASE}/api/jobs/:jobId`, () =>
        HttpResponse.json({
          job: {
            id: "greenhouse:1",
            source: "greenhouse",
            source_job_id: "1",
            title: "<script>window.__pwned = true</script>",
            company: "Acme",
            description: '<img src=x onerror="window.__pwned = true">',
            location: null,
            remote_policy: null,
            employment_type: null,
            salary: null,
            currency: null,
            seniority: null,
            required_skills: [],
            preferred_skills: [],
            experience_requirements: null,
            education_requirements: null,
            application_url: null,
            company_url: null,
            posted_at: null,
            metadata: {},
          },
        })
      )
    )

    const { container } = renderApp({
      route: `/matches/${encodeURIComponent("greenhouse:1")}`,
    })

    await waitFor(() => {
      expect(container.textContent).toContain("<script>")
    })
    expect(container.querySelector("img")).toBeNull()
    expect(container.querySelector("script")).toBeNull()
    expect((window as unknown as { __pwned?: boolean }).__pwned).toBeUndefined()
  })
})
