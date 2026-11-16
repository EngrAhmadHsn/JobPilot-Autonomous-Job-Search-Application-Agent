import { screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { http, HttpResponse } from "msw"
import { describe, expect, it } from "vitest"

import { MatchesScreen } from "@/screens/matches-screen"
import { jobListing, jobSearchResponse, matchPair } from "@/test/factories"
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

  it("lets the suggestion panel out of the search card (WS-21)", async () => {
    /*
      The defect: the panel is absolutely positioned from under the query
      field, and the shared Card's default `overflow-hidden` cut it off at
      the card's edge. jsdom cannot measure layout, so the *contract* (this
      one card is overflow-visible) is pinned here; the real boxes are
      measured in a browser by e2e/suggestions.spec.ts.
    */
    withProfile()
    server.use(
      http.get(`${BASE}/api/jobs/suggest`, () =>
        HttpResponse.json({
          query: "eng",
          suggestions: [{ value: "AI Engineer", count: 3 }],
        })
      )
    )
    const user = userEvent.setup()
    const { container } = renderScreen(<MatchesScreen />)

    await user.type(screen.getByLabelText("Query"), "eng")
    expect(await screen.findByRole("listbox")).toBeInTheDocument()

    const card = container.querySelector('[data-slot="card"]')
    expect(card?.className).toContain("overflow-visible")
  })

  it("keeps the last search when the screen is left and returned to", async () => {
    withProfile()
    let calls = 0
    server.use(
      http.get(`${BASE}/api/jobs/suggest`, () =>
        HttpResponse.json({ query: "eng", suggestions: [] })
      ),
      http.post(`${BASE}/api/jobs/search`, () => {
        calls += 1
        return HttpResponse.json(jobSearchResponse())
      })
    )
    const user = userEvent.setup()
    const first = renderScreen(<MatchesScreen />)

    await user.type(screen.getByLabelText("Query"), "eng")
    await user.click(screen.getByRole("button", { name: "Search" }))
    expect(await screen.findByText("AI Engineer")).toBeInTheDocument()
    expect(calls).toBe(1)

    // Leave the screen and come back: the ranking — and the fields that
    // produced it — are still there, without paying for the search again.
    first.unmount()
    renderScreen(<MatchesScreen />)

    expect(await screen.findByText("AI Engineer")).toBeInTheDocument()
    expect(screen.getByText("82.5")).toBeInTheDocument()
    expect(screen.getByLabelText("Query")).toHaveValue("eng")
    expect(calls).toBe(1)
  })

  it("a new search replaces the kept one", async () => {
    withProfile()
    let calls = 0
    server.use(
      http.post(`${BASE}/api/jobs/search`, () => {
        calls += 1
        const title = `Role ${calls}`
        return HttpResponse.json(
          jobSearchResponse({
            results: [
              matchPair({
                job: jobListing({ id: `job-${calls}`, title }),
              }),
            ],
          })
        )
      })
    )
    const user = userEvent.setup()
    const first = renderScreen(<MatchesScreen />)

    await user.click(screen.getByRole("button", { name: "Search" }))
    expect(await screen.findByText("Role 1")).toBeInTheDocument()
    await user.click(screen.getByRole("button", { name: "Search" }))
    expect(await screen.findByText("Role 2")).toBeInTheDocument()

    first.unmount()
    renderScreen(<MatchesScreen />)
    expect(await screen.findByText("Role 2")).toBeInTheDocument()
    expect(screen.queryByText("Role 1")).not.toBeInTheDocument()
    expect(calls).toBe(2)
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
    renderApp({ route: `/app/matches/${encodeURIComponent("greenhouse:1")}` })

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
      route: `/app/matches/${encodeURIComponent("greenhouse:1")}`,
    })

    await waitFor(() => {
      expect(container.textContent).toContain("<script>")
    })
    expect(container.querySelector("img")).toBeNull()
    expect(container.querySelector("script")).toBeNull()
    expect((window as unknown as { __pwned?: boolean }).__pwned).toBeUndefined()
  })
})

/*
  WS-24c: a running search shows the shape of the answer, not a stopwatch.

  The screen used to render a ProgressState with a ticking "{n}s elapsed"
  counter. It was honest, but it was the only thing on screen moving, and it
  told the operator something they already knew. The skeleton reserves the
  space the ranking will fill, and there are two properties that matter:
  the placeholder is visible **while** the request is in flight (so it is not
  a decoration that only appears after the wait), and it is gone afterwards
  (so it is not a permanent fixture that happens to look like loading).
*/
describe("the matches screen while a search is running", () => {
  /** A search that stays pending until the test releases it. */
  function deferredSearch() {
    let release: (() => void) | undefined
    const gate = new Promise<void>((resolve) => {
      release = resolve
    })
    server.use(
      http.post(`${BASE}/api/jobs/search`, async () => {
        await gate
        return HttpResponse.json(jobSearchResponse())
      })
    )
    return () => release?.()
  }

  it("shows the ranked-list skeleton while the search is in flight", async () => {
    withProfile()
    const release = deferredSearch()
    const user = userEvent.setup()
    const { container } = renderScreen(<MatchesScreen />)

    await user.click(screen.getByRole("button", { name: "Search" }))

    // The placeholder is on screen, and the region says it is busy.
    await waitFor(() => {
      expect(container.querySelector('[aria-busy="true"]')).toBeInTheDocument()
    })
    expect(
      container.querySelectorAll('[data-slot="skeleton"]').length
    ).toBeGreaterThan(0)

    release()
    expect(await screen.findByText("AI Engineer")).toBeInTheDocument()

    // ...and it is gone once the ranking lands.
    await waitFor(() => {
      expect(
        container.querySelector('[aria-busy="true"]')
      ).not.toBeInTheDocument()
    })
  })

  it("does not show an elapsed-seconds counter", async () => {
    /*
      The counter is what this change removed. Asserting its absence is the
      only way to keep it from creeping back: nothing else on the screen
      mentions time, so a re-added ProgressState would otherwise pass.
    */
    withProfile()
    const release = deferredSearch()
    const user = userEvent.setup()
    const { container } = renderScreen(<MatchesScreen />)

    await user.click(screen.getByRole("button", { name: "Search" }))
    await waitFor(() => {
      expect(container.querySelector('[aria-busy="true"]')).toBeInTheDocument()
    })
    expect(container.textContent).not.toMatch(/\d+s elapsed/)
    expect(
      screen.queryByText("This takes a few seconds.")
    ).not.toBeInTheDocument()

    release()
    await screen.findByText("AI Engineer")
  })

  it("says what it is doing instead of waiting silently", async () => {
    /*
      A screenful of aria-hidden boxes is silent to a screen reader, and
      silence is indistinguishable from a hang. The heading is the
      announcement, so it has to be a real heading with the words in it.
    */
    withProfile()
    const release = deferredSearch()
    const user = userEvent.setup()
    renderScreen(<MatchesScreen />)

    await user.click(screen.getByRole("button", { name: "Search" }))

    expect(
      await screen.findByRole("heading", { name: "Ranking your saved jobs" })
    ).toBeInTheDocument()

    release()
    await screen.findByText("AI Engineer")
  })

  it("replaces the previous ranking rather than stacking on it", async () => {
    /*
      Old results stay in the query cache between searches. If the skeleton
      were additive, a second search would show placeholders above last
      time's numbers — which reads as "these are still updating" instead of
      "these are the old ones, the new ones are coming".
    */
    withProfile()
    const user = userEvent.setup()
    const { container } = renderScreen(<MatchesScreen />)

    await user.click(screen.getByRole("button", { name: "Search" }))
    expect(await screen.findByText("AI Engineer")).toBeInTheDocument()

    const release = deferredSearch()
    await user.click(screen.getByRole("button", { name: "Search" }))

    await waitFor(() => {
      expect(container.querySelector('[aria-busy="true"]')).toBeInTheDocument()
    })
    expect(screen.queryByText("AI Engineer")).not.toBeInTheDocument()
    expect(screen.queryByText("82.5")).not.toBeInTheDocument()

    release()
    expect(await screen.findByText("AI Engineer")).toBeInTheDocument()
  })
})
