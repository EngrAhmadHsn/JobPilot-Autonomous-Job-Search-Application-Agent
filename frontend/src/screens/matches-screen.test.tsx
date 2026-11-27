import { screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { http, HttpResponse } from "msw"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"

import { MatchesScreen } from "@/screens/matches-screen"
import { jobListing, jobSearchResponse, matchPair } from "@/test/factories"
import { setCurrentProfileId } from "@/lib/profile"
import { server } from "@/test/server"
import { renderApp, renderScreen } from "@/test/render"

const BASE = "http://api.test"

function withProfile() {
  setCurrentProfileId("profile-1")
}

/**
 * A search response whose ranked slice holds `count` listings, each a real
 * pair shaped like the API sends.
 */
function sliceOf(count: number) {
  return Array.from({ length: count }, (_, index) =>
    matchPair({
      job: jobListing({ id: `job-${index}`, title: `Role ${index}` }),
    })
  )
}

describe("the matches screen", () => {
  it("asks for a profile before it can search", () => {
    renderScreen(<MatchesScreen />)

    expect(screen.getByText("No profile selected")).toBeInTheDocument()
  })

  it("does not clip the suggestion panel (WS-21, re-pinned for WS-42)", async () => {
    /*
      The original defect: the suggestion panel is absolutely positioned from
      under the query field, and the shared `Card`'s default `overflow-hidden`
      cut it off at the card's edge. The first fix pinned *that card's*
      `overflow-visible` class.

      WS-42 removed the card — the design file draws the search as a bare
      field with its action attached (node `49:845`), not a card — so the
      original assertion no longer has a subject. The **contract** it was
      protecting is unchanged and is now asserted directly: nothing between
      the query field and the screen root may clip. That survives any future
      restyle, where pinning one class name did not.

      jsdom cannot measure layout, so this checks the computed overflow of the
      field's ancestors; the real boxes are measured in a browser by
      `e2e/suggestions.spec.ts`.
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
    renderScreen(<MatchesScreen />)

    const field = screen.getByLabelText("Query")
    await user.type(field, "eng")
    expect(await screen.findByRole("listbox")).toBeInTheDocument()

    // Walk up from the field: nothing may clip along the way.
    for (let node = field.parentElement; node; node = node.parentElement) {
      const overflow = getComputedStyle(node).overflow
      expect(["", "visible"]).toContain(overflow)
    }
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
    await user.click(screen.getByRole("button", { name: "Search jobs" }))
    expect(await screen.findByText("AI Engineer")).toBeInTheDocument()
    expect(calls).toBe(1)

    // Leave the screen and come back: the ranking — and the fields that
    // produced it — are still there, without paying for the search again.
    first.unmount()
    renderScreen(<MatchesScreen />)

    // WS-44: the restored ranking also selects its top match by default, so
    // the title is on screen twice — the list's row and the detail's heading.
    expect(
      (await screen.findAllByText("AI Engineer")).length
    ).toBeGreaterThanOrEqual(1)
    // The row's score chip carries the whole score (WS-42, node 49:878) —
    // a rounded display form; the full precision stays with the breakdown.
    expect(screen.getByText("83")).toBeInTheDocument()
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

    await user.click(screen.getByRole("button", { name: "Search jobs" }))
    expect(await screen.findByText("Role 1")).toBeInTheDocument()
    await user.click(screen.getByRole("button", { name: "Search jobs" }))
    // WS-44: the top match of each search is selected by default, so the
    // title renders as the list's row and the detail's heading alike.
    expect(
      (await screen.findAllByText("Role 2")).length
    ).toBeGreaterThanOrEqual(1)

    first.unmount()
    renderScreen(<MatchesScreen />)
    expect(
      (await screen.findAllByText("Role 2")).length
    ).toBeGreaterThanOrEqual(1)
    expect(screen.queryByText("Role 1")).not.toBeInTheDocument()
    expect(calls).toBe(2)
  })

  it("ranks the matches and explains the ranking beside the list", async () => {
    withProfile()
    const user = userEvent.setup()
    renderScreen(<MatchesScreen />)

    await user.click(screen.getByRole("button", { name: "Search jobs" }))

    // WS-44: the ranked slice arrives with its top match selected by
    // default — the title renders as the list's row and the detail's
    // heading alike, so the landing is asserted on either.
    expect(
      (await screen.findAllByText("AI Engineer")).length
    ).toBeGreaterThanOrEqual(1)
    // The chip shows the whole score, not a decimal (WS-42, node 49:878).
    expect(screen.getByText("83")).toBeInTheDocument()

    // Selecting a row opens the reasoning beside the list — the split
    // view's "why this job matches" block, with the engine's explanation
    // visible without expanding anything.
    await user.click(screen.getByRole("button", { name: /AI Engineer/ }))
    expect(
      await screen.findByText(
        "The profile states Python and SQL, which the listing asks for."
      )
    ).toBeInTheDocument()
  })

  it("shows the server's total, not the loaded window", async () => {
    withProfile()
    server.use(
      http.post(`${BASE}/api/jobs/search`, () =>
        HttpResponse.json(jobSearchResponse({ results: sliceOf(12) }))
      )
    )
    const user = userEvent.setup()
    renderScreen(<MatchesScreen />)

    await user.click(screen.getByRole("button", { name: "Search jobs" }))

    // The count line is the whole ranked slice — the server returned it in
    // one response — while the list shows its window of ten.
    expect(
      await screen.findByText(/Showing 10 of 12 ranked matches/)
    ).toBeInTheDocument()
    const rows = screen.getAllByRole("button", { name: /Role \d/ })
    expect(rows).toHaveLength(10)

    // "Show more" extends the window; it never implies a second server page.
    await user.click(screen.getByRole("button", { name: /Show 2 more/ }))
    expect(
      await screen.findByText(/Showing 12 of 12 ranked matches/)
    ).toBeInTheDocument()
    expect(screen.getAllByRole("button", { name: /Role \d/ })).toHaveLength(12)
    expect(screen.queryByText(/Show \d+ more/)).not.toBeInTheDocument()
  })

  it("says the ranked slice is a slice when it came back full", async () => {
    withProfile()
    server.use(
      http.post(`${BASE}/api/jobs/search`, () =>
        HttpResponse.json(
          jobSearchResponse({
            results: sliceOf(50),
            // A store-only search contacts no board: `found` is zero and
            // `stored` is the corpus it ranked against — the shape the
            // endpoint really returns (the factory default carries a full
            // pipeline's counters instead). The corpus is larger than the
            // slice, because a server cannot return 50 ranked results out of
            // 11 stored listings (WS-36 review fix).
            stats: {
              found: 0,
              dropped: 0,
              deduped: 120,
              persisted: 120,
              stored: 120,
              semantic_covered: 120,
            },
          })
        )
      )
    )
    const user = userEvent.setup()
    renderScreen(<MatchesScreen />)

    // The default Top N fills the whole ranked slice, so the scope line
    // says what was ranked and what was not, and the count line stays
    // honest about the window on screen.
    await user.click(screen.getByRole("button", { name: "Search jobs" }))

    expect(
      await screen.findByText(
        /Ranked against 120 stored jobs — the first 50 shown/
      )
    ).toBeInTheDocument()
    expect(
      screen.getByText(/Showing 10 of 50 ranked matches/)
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

    await user.click(screen.getByRole("button", { name: "Search jobs" }))

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

    await user.click(screen.getByRole("button", { name: "Search jobs" }))

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

    await user.click(screen.getByRole("button", { name: "Search jobs" }))

    expect(
      await screen.findByText("Profile 'nope' not found")
    ).toBeInTheDocument()
  })

  it("renders an honest empty state when nothing in the corpus matches", async () => {
    withProfile()
    server.use(
      http.post(`${BASE}/api/jobs/search`, () =>
        HttpResponse.json(jobSearchResponse({ results: [] }))
      )
    )
    const user = userEvent.setup()
    renderScreen(<MatchesScreen />)

    await user.click(screen.getByRole("button", { name: "Search jobs" }))

    expect(await screen.findByText("No stored jobs match")).toBeInTheDocument()
    // The way to widen the corpus is the real screen that owns it.
    expect(
      screen.getByRole("link", { name: /Open Operations/ })
    ).toHaveAttribute("href", "/app/operations")
  })
})

describe("the Discover split view", () => {
  it("renders an unavailable component as unknown with its reason, never as its zero", async () => {
    withProfile()
    const base = matchPair().match
    server.use(
      http.post(`${BASE}/api/jobs/search`, () =>
        HttpResponse.json(
          jobSearchResponse({
            results: [
              matchPair({
                match: {
                  ...base,
                  location_score: 0,
                  component_states: {
                    ...base.component_states,
                    // The candidate never said where they want to work: the
                    // component rests on nothing, and must not read as a 0.
                    location: "CANDIDATE_DATA_MISSING",
                  },
                },
              }),
            ],
          })
        )
      )
    )
    const user = userEvent.setup()
    renderScreen(<MatchesScreen />)

    await user.click(screen.getByRole("button", { name: "Search jobs" }))
    await user.click(screen.getByRole("button", { name: /AI Engineer/ }))
    // WS-42 keeps the reasoning one disclosure deep in the panel (node
    // 49:944); opening it reveals the component rows.
    await user.click(
      screen.getByText("See all 8 score components and evidence")
    )

    // The unknown states its reason…
    expect(
      await screen.findByText("unknown — you haven't said")
    ).toBeInTheDocument()
    // …and the zero the raw score carries for it never renders as a value.
    expect(screen.queryByText("0.0")).not.toBeInTheDocument()
    // The measured components render their real numbers (skill and role
    // both carry 90 here, so the number is on screen twice).
    expect(screen.getAllByText("90.0").length).toBeGreaterThanOrEqual(1)
    expect(screen.getByText("75.0")).toBeInTheDocument()
  })

  it("renders a missing requirement as an evidence gap, not a disqualification", async () => {
    withProfile()
    const user = userEvent.setup()
    renderScreen(<MatchesScreen />)

    await user.click(screen.getByRole("button", { name: "Search jobs" }))
    await user.click(screen.getByRole("button", { name: /AI Engineer/ }))

    // The listing asks for Kubernetes and the profile does not state it:
    // the clay wash names the gap in the design's own words (WS-42, nodes
    // 49:939–49:942), framed as an evidence gap — never a disqualification.
    expect(
      await screen.findByText("Kubernetes not found in your source résumé")
    ).toBeInTheDocument()
    expect(screen.getByText("Evidence gap")).toBeInTheDocument()
  })

  it("wires the real actions and renders no save that has no endpoint", async () => {
    withProfile()
    const user = userEvent.setup()
    renderScreen(<MatchesScreen />)

    await user.click(screen.getByRole("button", { name: "Search jobs" }))
    await user.click(screen.getByRole("button", { name: /AI Engineer/ }))

    expect(
      await screen.findByRole("link", { name: /Tailor for this role/ })
    ).toHaveAttribute("href", "/app/tailor/greenhouse%3A1")
    // The board's own listing opens through the safe-link guard; the
    // factory URL is an ordinary http one, so the design's second action
    // goes to it.
    expect(
      screen.getByRole("link", { name: /Open original listing/ })
    ).toHaveAttribute("href", "http://127.0.0.1:8901/basic")
    // There is no save/shortlist endpoint, so there is no save action —
    // the reference panel's heart is dropped, not faked.
    expect(
      screen.queryByRole("button", { name: /save/i })
    ).not.toBeInTheDocument()
    expect(
      screen.queryByRole("link", { name: /save/i })
    ).not.toBeInTheDocument()
  })

  it("falls back to the complete record when there is no safe board URL", async () => {
    withProfile()
    server.use(
      http.post(`${BASE}/api/jobs/search`, () =>
        HttpResponse.json(
          jobSearchResponse({
            results: [
              matchPair({
                job: jobListing({ application_url: null }),
              }),
            ],
          })
        )
      )
    )
    const user = userEvent.setup()
    renderScreen(<MatchesScreen />)

    await user.click(screen.getByRole("button", { name: "Search jobs" }))
    await user.click(screen.getByRole("button", { name: /AI Engineer/ }))

    // With no safe URL the same slot hands off to the console's own
    // complete record — it never invents a destination.
    expect(
      await screen.findByRole("link", { name: /Open the full listing/ })
    ).toHaveAttribute("href", "/app/matches/greenhouse%3A1")
  })

  it("selects a deep-linked job after load, without a search", async () => {
    withProfile()
    // No stored search: the deep link alone must resolve the job — the
    // listing from its own read, the match from the persisted history.
    renderApp({ route: "/app/matches?job=greenhouse%3A1" })

    expect(
      await screen.findByRole("heading", { name: "AI Engineer" })
    ).toBeInTheDocument()
    expect(
      screen.getByText(
        "The profile states Python and SQL, which the listing asks for."
      )
    ).toBeInTheDocument()
    expect(screen.queryByText("No search yet")).not.toBeInTheDocument()
  })

  it("shows board-supplied descriptions literally without creating markup", async () => {
    const description = '<img src=x onerror="window.__pwned = true">'
    withProfile()
    server.use(
      http.post(`${BASE}/api/jobs/search`, () =>
        HttpResponse.json(
          jobSearchResponse({
            results: [
              matchPair({
                job: jobListing({ description }),
              }),
            ],
          })
        )
      )
    )
    const user = userEvent.setup()
    const { container } = renderScreen(<MatchesScreen />)

    await user.click(screen.getByRole("button", { name: "Search jobs" }))
    await user.click(screen.getByRole("button", { name: /AI Engineer/ }))
    await waitFor(() => {
      expect(
        screen.getByRole("heading", { name: /AI Engineer/ })
      ).toBeInTheDocument()
    })
    expect(container.querySelector("img")).toBeNull()
    expect(screen.getByText(description)).toBeInTheDocument()
    expect((window as unknown as { __pwned?: boolean }).__pwned).toBeUndefined()
  })

  it("moves focus through the rows with the arrow keys and selects with Enter", async () => {
    withProfile()
    server.use(
      http.post(`${BASE}/api/jobs/search`, () =>
        HttpResponse.json(jobSearchResponse({ results: sliceOf(4) }))
      )
    )
    const user = userEvent.setup()
    renderScreen(<MatchesScreen />)

    await user.click(screen.getByRole("button", { name: "Search jobs" }))
    const rows = await screen.findAllByRole("button", { name: /Role \d/ })

    // One tab stop for the list; the arrows walk the rows.
    rows[0]?.focus()
    expect(document.activeElement).toBe(rows[0])
    await user.keyboard("{ArrowDown}")
    expect(document.activeElement).toBe(rows[1])
    await user.keyboard("{ArrowUp}")
    expect(document.activeElement).toBe(rows[0])

    // Enter activates the focused row: it becomes the selection, in the
    // URL, and the reasoning opens beside the list.
    await user.keyboard("{Enter}")
    expect(
      await screen.findByRole("heading", { name: "Role 0" })
    ).toBeInTheDocument()
    expect(rows[0]).toHaveAttribute("aria-current", "true")
    expect(
      screen.getByText(
        "The profile states Python and SQL, which the listing asks for."
      )
    ).toBeInTheDocument()
  })
})

/*
  WS-44: when ranked results are on screen and no `?job=` is addressed, the
  top-ranked match is the selection — written to the URL, replaced not
  pushed, so landing here is not a navigation the operator made. A URL that
  already carries `?job=` is never overridden: deep-linked and invalid
  selections resolve by their own reads exactly as they always have.
*/
describe("the desktop default selection (WS-44)", () => {
  beforeEach(() => {
    const matchMedia = window.matchMedia.bind(window)
    vi.spyOn(window, "matchMedia").mockImplementation((query) => ({
      ...matchMedia(query),
      matches: query === "(min-width: 64rem)",
    }))
  })

  afterEach(() => {
    vi.restoreAllMocks()
  })

  /** A stored search whose ranked slice holds `count` listings. */
  function storedSearch(count: number) {
    return {
      query: "eng",
      location: "",
      workplace: "",
      topN: 50,
      response: jobSearchResponse({ results: sliceOf(count) }),
    }
  }

  function seedStoredSearch(record: unknown) {
    window.localStorage.setItem(
      "ajp.lastSearch.profile-1",
      JSON.stringify(record)
    )
  }

  it("selects the top match when the last search is restored", async () => {
    withProfile()
    seedStoredSearch(storedSearch(2))
    const { router } = renderApp({ route: "/app/matches" })

    // The first ranked match is the selection, in the URL, with the detail
    // rendered beside the list — the screen's first paint already answers
    // "why".
    await screen.findByRole("heading", { name: "Role 0" })
    expect(router.state.location.search).toContain("job=job-0")
    // The write replaced history rather than pushing an entry: landing on
    // the screen is not a navigation the operator made.
    expect(router.state.historyAction).toBe("REPLACE")
    expect(screen.getByRole("button", { name: /Role 1/ })).toBeInTheDocument()
  })

  it("selects the top match after a fresh search", async () => {
    withProfile()
    server.use(
      http.post(`${BASE}/api/jobs/search`, () =>
        HttpResponse.json(jobSearchResponse({ results: sliceOf(3) }))
      )
    )
    const user = userEvent.setup()
    const { router } = renderApp({ route: "/app/matches" })

    await user.click(screen.getByRole("button", { name: "Search jobs" }))

    await screen.findByRole("heading", { name: "Role 0" })
    expect(router.state.location.search).toContain("job=job-0")
    expect(router.state.historyAction).toBe("REPLACE")
    expect(screen.getByRole("button", { name: /Role 2/ })).toBeInTheDocument()
  })

  it("leaves an addressed ?job= alone, even when results are restored", async () => {
    withProfile()
    seedStoredSearch(storedSearch(2))
    // An id outside the restored slice: the deep link resolves by its own
    // reads (the lookup job renders), and the URL is never overridden with
    // the slice's top match.
    const { router } = renderApp({ route: "/app/matches?job=job-9" })

    await screen.findByRole("heading", { name: "AI Engineer" })
    expect(router.state.location.search).toBe("?job=job-9")
    // The restored list is still beside it.
    expect(screen.getByRole("button", { name: /Role 0/ })).toBeInTheDocument()
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
    // The fit card leads with the verdict slot (WS-42, node 49:1920),
    // derived from the engine's own component verdicts and the recorded
    // gaps — the factory row asks for one skill the profile does not state.
    expect(screen.getByText("A good fit, with one gap.")).toBeInTheDocument()
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

    await user.click(screen.getByRole("button", { name: "Search jobs" }))

    // The placeholder is on screen, and the region says it is busy.
    await waitFor(() => {
      expect(container.querySelector('[aria-busy="true"]')).toBeInTheDocument()
    })
    expect(
      container.querySelectorAll('[data-slot="skeleton"]').length
    ).toBeGreaterThan(0)

    release()
    // The ranking lands with its top match selected by default (WS-44), so
    // the title is the list's row and the detail's heading alike.
    expect(
      (await screen.findAllByText("AI Engineer")).length
    ).toBeGreaterThanOrEqual(1)

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

    await user.click(screen.getByRole("button", { name: "Search jobs" }))
    await waitFor(() => {
      expect(container.querySelector('[aria-busy="true"]')).toBeInTheDocument()
    })
    expect(container.textContent).not.toMatch(/\d+s elapsed/)
    expect(
      screen.queryByText("This takes a few seconds.")
    ).not.toBeInTheDocument()

    release()
    // The ranking lands with its top match selected by default (WS-44).
    await screen.findAllByText("AI Engineer")
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

    await user.click(screen.getByRole("button", { name: "Search jobs" }))

    expect(
      await screen.findByRole("heading", { name: "Ranking your saved jobs" })
    ).toBeInTheDocument()

    release()
    // The ranking lands with its top match selected by default (WS-44).
    await screen.findAllByText("AI Engineer")
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

    await user.click(screen.getByRole("button", { name: "Search jobs" }))
    expect(await screen.findByText("AI Engineer")).toBeInTheDocument()

    const release = deferredSearch()
    await user.click(screen.getByRole("button", { name: "Search jobs" }))

    await waitFor(() => {
      expect(container.querySelector('[aria-busy="true"]')).toBeInTheDocument()
    })
    expect(screen.queryByText("AI Engineer")).not.toBeInTheDocument()
    expect(screen.queryByText("83")).not.toBeInTheDocument()

    release()
    // WS-44: the ranking lands with its top match selected by default — the
    // title is on screen as the list's row and the detail's heading alike.
    expect(
      (await screen.findAllByText("AI Engineer")).length
    ).toBeGreaterThanOrEqual(1)
  })
})

describe("a failed match-history read (WS-36 review fix)", () => {
  /*
    The unknown must stay unknown. When the persisted history cannot be read,
    the panel previously rendered "Not matched yet" — a definitive claim about
    a state nobody observed, which is the exact class of fabrication this
    product forbids. A failed read and a genuinely-unscored listing are two
    different facts and must render differently.
  */
  it("renders an honest read failure, never the Not-matched-yet claim", async () => {
    withProfile()
    server.use(
      http.get(`${BASE}/api/profiles/:profileId/matches`, () =>
        HttpResponse.json({ detail: "boom" }, { status: 500 })
      )
    )
    renderApp({ route: "/app/matches?job=greenhouse%3A1" })

    expect(
      await screen.findByText("The match for this listing could not be read.")
    ).toBeInTheDocument()
    expect(screen.queryByText("Not matched yet")).not.toBeInTheDocument()
    // The retry affordance exists so the transient case is recoverable.
    expect(
      screen.getByRole("button", { name: "Try reading it again" })
    ).toBeInTheDocument()
    // The listing itself still renders — the failure is scoped to the match.
    expect(
      screen.getByRole("heading", { name: "AI Engineer" })
    ).toBeInTheDocument()
  })

  it("still says Not matched yet when the history read succeeds and is empty", async () => {
    withProfile()
    server.use(
      http.get(`${BASE}/api/profiles/:profileId/matches`, () =>
        HttpResponse.json({ matches: [] })
      )
    )
    renderApp({ route: "/app/matches?job=greenhouse%3A1" })

    expect(await screen.findByText("Not matched yet")).toBeInTheDocument()
    expect(
      screen.queryByText("The match for this listing could not be read.")
    ).not.toBeInTheDocument()
  })
})
