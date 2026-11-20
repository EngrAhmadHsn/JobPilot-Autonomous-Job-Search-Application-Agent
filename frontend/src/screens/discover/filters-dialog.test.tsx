import { fireEvent, screen, waitFor, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { http, HttpResponse } from "msw"
import { describe, expect, it, vi } from "vitest"

import { MatchesScreen } from "@/screens/matches-screen"
import { jobListing, jobSearchResponse, matchPair } from "@/test/factories"
import { setCurrentProfileId } from "@/lib/profile"
import { server } from "@/test/server"
import { renderApp, renderScreen } from "@/test/render"

const BASE = "http://api.test"

/**
 * The locations the corpus holds (WS-44) — the shape `GET /api/jobs/locations`
 * answers with, the same shape as `/api/jobs/suggest`.
 */
const LOCATIONS = {
  query: "",
  suggestions: [
    { value: "United Kingdom", count: 12 },
    { value: "London, UK", count: 8 },
    { value: "Berlin, Germany", count: 3 },
  ],
}

function withProfile() {
  setCurrentProfileId("profile-1")
}

/** A ranked slice of `count` listings, shaped like the API sends. */
function sliceOf(count: number) {
  return Array.from({ length: count }, (_, index) =>
    matchPair({
      job: jobListing({ id: `job-${index}`, title: `Role ${index}` }),
    })
  )
}

/**
 * Capture what the screen actually posts, and serve it a ranked slice.
 * The locations handler feeds the dialog's Location select.
 */
function captureSearches() {
  const bodies: Record<string, unknown>[] = []
  server.use(
    http.post(`${BASE}/api/jobs/search`, async ({ request }) => {
      bodies.push((await request.json()) as Record<string, unknown>)
      return HttpResponse.json(jobSearchResponse({ results: sliceOf(2) }))
    }),
    http.get(`${BASE}/api/jobs/locations`, () => HttpResponse.json(LOCATIONS)),
    // A seeded query state (a URL's `skills`) has the combobox ask for
    // suggestions at mount; an empty list keeps the test on the dialog.
    http.get(`${BASE}/api/jobs/suggest`, () =>
      HttpResponse.json({ query: "", suggestions: [] })
    )
  )
  return bodies
}

async function openFiltersDialog(user: ReturnType<typeof userEvent.setup>) {
  // `findByRole`, because the route tree is lazy: the button may still be a
  // chunk away on the first query.
  await user.click(await screen.findByRole("button", { name: /^Filters/ }))
  await screen.findByRole("dialog", { name: "Job filters" })
}

describe("the job filters dialog (WS-44)", () => {
  it("opens with the design's fields, fed by the corpus's own locations", async () => {
    withProfile()
    captureSearches()
    const user = userEvent.setup()
    renderScreen(<MatchesScreen />)

    await openFiltersDialog(user)

    // The four fields the design draws (plus the honest fourth, Rank top N,
    // which moved here from the old disclosure).
    expect(
      screen.getByLabelText("Location", { selector: "select" })
    ).toBeInTheDocument()
    expect(screen.getByLabelText("Workplace")).toBeInTheDocument()
    expect(screen.getByLabelText("Skills")).toBeInTheDocument()
    expect(
      screen.getByLabelText("Rank top N", { selector: "input" })
    ).toBeInTheDocument()

    // The Location select offers what the corpus actually holds — the
    // endpoint's own values, not a geocoder's guesses.
    const location = screen.getByLabelText("Location", { selector: "select" })
    expect(
      within(location).getByRole("option", { name: "United Kingdom" })
    ).toBeInTheDocument()
    expect(
      within(location).getByRole("option", { name: "Berlin, Germany" })
    ).toBeInTheDocument()

    // The design's two actions.
    expect(
      screen.getByRole("button", { name: "Apply filters" })
    ).toBeInTheDocument()
    expect(screen.getByRole("button", { name: "Cancel" })).toBeInTheDocument()
  })

  it("states the honesty note verbatim", async () => {
    withProfile()
    captureSearches()
    const user = userEvent.setup()
    renderScreen(<MatchesScreen />)

    await openFiltersDialog(user)

    // The design's own sentence, word for word (`Overlay · Job filters`).
    expect(
      screen.getByText(
        "These filters apply to the stored corpus. They do not fetch job boards."
      )
    ).toBeInTheDocument()
  })

  it("applies the draft: the request, the chips and the URL all carry it", async () => {
    withProfile()
    const bodies = captureSearches()
    const user = userEvent.setup()
    const { router } = renderApp({ route: "/app/matches" })

    await openFiltersDialog(user)
    await user.selectOptions(
      screen.getByLabelText("Location", { selector: "select" }),
      "United Kingdom"
    )
    await user.selectOptions(screen.getByLabelText("Workplace"), "remote")
    await user.type(screen.getByLabelText("Skills"), "Python")
    fireEvent.change(screen.getByLabelText("Rank top N"), {
      target: { value: "25" },
    })
    await user.click(screen.getByRole("button", { name: "Apply filters" }))

    // The request the dialog produced — every filter on its contract field.
    await screen.findByRole("heading", { name: "Role 0" })
    expect(bodies).toHaveLength(1)
    expect(bodies[0]).toMatchObject({
      profile_id: "profile-1",
      location: "United Kingdom",
      workplace: "remote",
      query: "Python",
      top_n: 25,
    })

    // The applied filters render as the design's removable chips: the
    // workplace and location narrowing as one chip, the skills beside it —
    // and the Skills entrance is the same field the search box fills.
    expect(
      screen.getByRole("button", {
        name: /Remote · United Kingdom/,
      })
    ).toBeInTheDocument()
    expect(
      screen.getByRole("button", { name: /Remove the skills filter/ })
    ).toBeInTheDocument()
    expect(screen.getByLabelText("Query")).toHaveValue("Python")
    expect(
      screen.getByRole("button", { name: /Reset the ranked slice to 50/ })
    ).toBeInTheDocument()

    // The filters live in the URL alongside the selection, so the narrowed
    // search is an address, not a memory.
    const search = router.state.location.search
    expect(search).toContain("workplace=remote")
    // URLSearchParams encodes the space as `+` in query position.
    expect(search).toContain("location=United+Kingdom")
    expect(search).toContain("skills=Python")
    expect(search).toContain("top_n=25")
    // And WS-44's default selection is in the same address.
    expect(search).toContain("job=job-0")
  })

  it("cancel and Escape discard the draft without searching", async () => {
    withProfile()
    const bodies = captureSearches()
    const user = userEvent.setup()
    renderScreen(<MatchesScreen />)

    await openFiltersDialog(user)
    await user.selectOptions(screen.getByLabelText("Workplace"), "remote")
    await user.type(screen.getByLabelText("Skills"), "Python")

    // Escape is the primitive's own close; the edits never reach the screen.
    await user.keyboard("{Escape}")
    await waitFor(() => {
      expect(screen.queryByRole("dialog")).not.toBeInTheDocument()
    })
    expect(bodies).toHaveLength(0)
    expect(screen.getByLabelText("Query")).toHaveValue("")
    expect(
      screen.queryByRole("button", { name: /Remove the skills filter/ })
    ).not.toBeInTheDocument()

    // Cancel is the design's own discard.
    await openFiltersDialog(user)
    await user.type(screen.getByLabelText("Skills"), "Python")
    await user.click(screen.getByRole("button", { name: "Cancel" }))
    await waitFor(() => {
      expect(screen.queryByRole("dialog")).not.toBeInTheDocument()
    })
    expect(bodies).toHaveLength(0)
    expect(screen.getByLabelText("Query")).toHaveValue("")
    expect(
      screen.queryByRole("button", { name: /Remove the skills filter/ })
    ).not.toBeInTheDocument()
  })

  it("a chip's × clears exactly what it shows and searches again", async () => {
    withProfile()
    const bodies = captureSearches()
    const user = userEvent.setup()
    const { router } = renderApp({ route: "/app/matches" })

    await openFiltersDialog(user)
    await user.selectOptions(
      screen.getByLabelText("Location", { selector: "select" }),
      "United Kingdom"
    )
    await user.selectOptions(screen.getByLabelText("Workplace"), "remote")
    await user.click(screen.getByRole("button", { name: "Apply filters" }))
    await screen.findByRole("heading", { name: "Role 0" })
    expect(bodies).toHaveLength(1)

    // The narrowing chip's × clears the workplace and the location, and the
    // re-search runs without them — the request body carries no workplace
    // and no location at all.
    await user.click(screen.getByRole("button", { name: /Remove the Remote/ }))
    await waitFor(() => expect(bodies).toHaveLength(2))
    expect(bodies[1]).toEqual({
      profile_id: "profile-1",
      top_n: 50,
      only_embedded: false,
    })
    expect(
      screen.queryByRole("button", { name: /Remote · United Kingdom/ })
    ).not.toBeInTheDocument()
    expect(router.state.location.search).not.toContain("workplace=")
    expect(router.state.location.search).not.toContain("location=")

    // The skills chip's × clears the skills filter the same way.
    await openFiltersDialog(user)
    await user.type(screen.getByLabelText("Skills"), "Python")
    await user.click(screen.getByRole("button", { name: "Apply filters" }))
    await waitFor(() => expect(bodies).toHaveLength(3))
    expect(bodies[2]).toMatchObject({ query: "Python" })
    await user.click(
      screen.getByRole("button", { name: /Remove the skills filter/ })
    )
    await waitFor(() => expect(bodies).toHaveLength(4))
    expect(bodies[3]).toEqual({
      profile_id: "profile-1",
      top_n: 50,
      only_embedded: false,
    })
    expect(router.state.location.search).not.toContain("skills=")
  })

  it("a URL's filter params address the search: chips, dialog and request", async () => {
    withProfile()
    const bodies = captureSearches()
    const user = userEvent.setup()
    const { router } = renderApp({
      route:
        "/app/matches?workplace=remote&location=London&skills=Python&top_n=25",
    })

    // The chips render from the address alone, before anything is searched.
    expect(
      screen.getByRole("button", { name: /Remote · London/ })
    ).toBeInTheDocument()
    expect(
      screen.getByRole("button", { name: /Remove the skills filter/ })
    ).toBeInTheDocument()
    expect(
      screen.getByRole("button", { name: /Reset the ranked slice to 50/ })
    ).toBeInTheDocument()

    // The dialog opens pre-filled with what the address holds.
    await openFiltersDialog(user)
    expect(
      screen.getByLabelText("Location", { selector: "select" })
    ).toHaveValue("London")
    expect(screen.getByLabelText("Workplace")).toHaveValue("remote")
    expect(screen.getByLabelText("Skills")).toHaveValue("Python")
    expect(screen.getByLabelText("Rank top N")).toHaveValue(25)
    await user.keyboard("{Escape}")

    // And running the search posts the addressed filters, not defaults.
    await user.click(screen.getByRole("button", { name: "Search jobs" }))
    await screen.findByRole("heading", { name: "Role 0" })
    expect(bodies).toHaveLength(1)
    expect(bodies[0]).toMatchObject({
      workplace: "remote",
      location: "London",
      query: "Python",
      top_n: 25,
    })
    expect(router.state.location.search).toContain("workplace=remote")
  })
})

/*
  WS-44, the pane scroll: at `lg`+ the screen is a fixed-height flex under
  the 68 px top bar — the header block does not scroll, and the results and
  detail panes each scroll internally, so the page itself never scrolls.
  jsdom cannot measure layout, so this pins the classes that carry the
  behaviour (the real boxes are measured in the ws41-audit browser probe).
*/
describe("the Discover pane scroll (WS-44)", () => {
  it("fixes the screen to the viewport and scrolls the panes internally", async () => {
    withProfile()
    captureSearches()
    const user = userEvent.setup()
    const { container } = renderScreen(<MatchesScreen />)

    await user.click(screen.getByRole("button", { name: "Search jobs" }))
    await screen.findByRole("heading", { name: "Role 0" })

    const root = container.querySelector('[data-testid="discover-screen"]')
    expect(root).not.toBeNull()
    expect(root?.className).toContain("lg:h-[calc(100dvh-68px)]")
    expect(root?.className).toContain("lg:overflow-hidden")
    expect(root?.className).toContain("lg:flex-col")

    // The results pane scrolls inside itself; its heading stays put.
    const resultsScroll = container.querySelector(
      '[data-testid="results-scroll"]'
    )
    expect(resultsScroll?.className).toContain("lg:overflow-y-auto")
    expect(resultsScroll?.className).toContain("lg:flex-1")

    // The detail pane scrolls inside itself too.
    const detail = screen.getByRole("region", { name: "The selected job" })
    expect(detail.className).toContain("lg:overflow-y-auto")
    expect(detail.className).toContain("lg:min-h-0")
  })

  it("keeps the focused row visible while the keyboard walks the list", async () => {
    withProfile()
    captureSearches()
    const user = userEvent.setup()
    renderScreen(<MatchesScreen />)

    await user.click(screen.getByRole("button", { name: "Search jobs" }))
    const rows = await screen.findAllByRole("button", { name: /Role \d/ })

    const scrollIntoView = vi
      .spyOn(Element.prototype, "scrollIntoView")
      .mockClear()
    rows[0]?.focus()
    await user.keyboard("{ArrowDown}")
    expect(document.activeElement).toBe(rows[1])
    expect(scrollIntoView).toHaveBeenCalledWith({ block: "nearest" })
    scrollIntoView.mockRestore()
  })
})
