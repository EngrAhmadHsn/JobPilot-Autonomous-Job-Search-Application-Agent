import { screen, waitFor } from "@testing-library/react"
import { http, HttpResponse } from "msw"
import { describe, expect, it } from "vitest"

import { jobListing, matchesHistory } from "@/test/factories"
import { setCurrentProfileId } from "@/lib/profile"
import { server } from "@/test/server"
import { renderApp } from "@/test/render"

const BASE = "http://api.test"

const ROUTE = `/app/matches/${encodeURIComponent("greenhouse:1")}`

function withProfile() {
  setCurrentProfileId("profile-1")
}

/**
 * A history row with every component measured, so a test that cares about
 * one state overrides just that state. The scores dictionary is the
 * backend's free-form shape — exactly what `matchFromHistoryEntry` reads
 * through the safe accessors.
 */
function measuredHistory(overrides: Record<string, unknown> = {}) {
  return {
    profile_id: "profile-1",
    matches: [
      {
        profile_id: "profile-1",
        job_id: "greenhouse:1",
        scores: {
          overall_score: 82.5,
          semantic_score: 80,
          lexical_score: 70,
          skill_score: 90,
          experience_score: 75,
          seniority_score: 80,
          location_score: 100,
          preference_score: 70,
          role_score: 90,
          role_family: "data_science_ml",
          role_family_confidence: 0.9,
          role_targets: ["AI Engineer"],
          role_target_source: "user",
          role_capped: false,
          evidence_coverage: 90,
          component_states: {
            semantic: "MATCHED",
            lexical: "MATCHED",
            skill: "MATCHED",
            experience: "MATCHED",
            seniority: "MATCHED",
            location: "MATCHED",
            preference: "MATCHED",
            role: "MATCHED",
          },
          missing_requirements: ["Kubernetes"],
          matched_requirements: ["Python", "SQL"],
          ...overrides,
        },
        explanation:
          "The profile states Python and SQL, which the listing asks for.",
        created_at: "2026-10-21T10:00:00Z",
      },
    ],
  }
}

describe("the job detail screen (WS-36)", () => {
  it("shows the complete listing with the full reasoning in place", async () => {
    withProfile()
    server.use(
      http.get(`${BASE}/api/profiles/:profileId/matches`, () =>
        HttpResponse.json(measuredHistory())
      )
    )
    renderApp({ route: ROUTE })

    // The complete record: the listing's fields, the description, the
    // verdict slot, and the full component breakdown rendered in place (the
    // route's purpose — not buried in a disclosure the way the Discover
    // panel keeps it).
    expect(
      await screen.findByRole("heading", { name: "AI Engineer" })
    ).toBeInTheDocument()
    expect(screen.getByText("The listing")).toBeInTheDocument()
    expect(
      screen.getByText(
        "Build machine learning systems for a payments platform."
      )
    ).toBeInTheDocument()
    // The fit card leads with the verdict slot (WS-42, node 49:1920),
    // derived from the engine's component verdicts and the recorded gaps.
    expect(screen.getByText("A good fit, with one gap.")).toBeInTheDocument()
    expect(screen.getByText("Semantic")).toBeInTheDocument()
    expect(
      screen.getByText("Based on 90.0% of the available signals.")
    ).toBeInTheDocument()

    // Source and freshness, as the data carries them. WS-42 (node 47:524):
    // the header's meta row names the *source* — the raw source_job_id
    // stays in the listing's own field table, and only there.
    expect(screen.getAllByText(/greenhouse · 1/).length).toBe(1)

    // The real actions, at their real destinations, and no save. The back
    // pill carries the history's own count (WS-42, design node 47:488) —
    // the count arrives with the history read, so wait for it.
    expect(
      await screen.findByRole("link", { name: /Back to \d+ match(es)?/ })
    ).toHaveAttribute("href", "/app/matches")
    expect(
      screen.getByRole("link", { name: /Tailor for this role/ })
    ).toHaveAttribute("href", "/app/tailor/greenhouse%3A1")
    expect(
      screen.queryByRole("button", { name: /save/i })
    ).not.toBeInTheDocument()
  })

  it("renders an unavailable component as unknown with its reason, never as its zero", async () => {
    withProfile()
    const history = measuredHistory()
    const row = history.matches[0]
    if (!row) throw new Error("the factory row is missing")
    const scores = row.scores as Record<string, unknown>
    scores.location_score = 0
    scores.component_states = {
      ...(scores.component_states as Record<string, string>),
      // The candidate never said where they want to work: the component
      // rests on nothing, and must not read as a 0.
      location: "CANDIDATE_DATA_MISSING",
    }
    server.use(
      http.get(`${BASE}/api/profiles/:profileId/matches`, () =>
        HttpResponse.json(history)
      )
    )
    renderApp({ route: ROUTE })

    expect(
      await screen.findByText("unknown — you haven't said")
    ).toBeInTheDocument()
    // The zero the raw score carries for it never renders as a value.
    expect(screen.queryByText("0.0")).not.toBeInTheDocument()
    // The measured components render their real numbers (skill and role
    // both carry 90 here, so the number is on screen twice).
    expect(screen.getAllByText("90.0").length).toBeGreaterThanOrEqual(1)
    expect(screen.getByText("75.0")).toBeInTheDocument()
  })

  it("renders a missing requirement as an evidence gap, not a disqualification", async () => {
    withProfile()
    server.use(
      http.get(`${BASE}/api/profiles/:profileId/matches`, () =>
        HttpResponse.json(measuredHistory())
      )
    )
    renderApp({ route: ROUTE })

    // The clay wash names the gap in the design's own words (WS-42, nodes
    // 49:1929–49:1931) and frames what a gap is — never a disqualification.
    expect(
      await screen.findByText("Kubernetes is not in your source résumé.")
    ).toBeInTheDocument()
    expect(
      screen.getByText("An evidence gap, not a reason to invent experience.")
    ).toBeInTheDocument()
  })

  it("renders sponsorship as unknown when no register covers the listing", async () => {
    withProfile()
    server.use(
      http.get(`${BASE}/api/profiles/:profileId/matches`, () =>
        HttpResponse.json(measuredHistory())
      )
    )
    renderApp({ route: ROUTE })

    // No sponsor_status rides on the row: the honest answer is unknown,
    // not a silent absence and not a guessed negative — and the rail keeps
    // the guardrail sentence visible under the finding (WS-42, node
    // 49:1958).
    expect(await screen.findByText("Sponsorship: unknown")).toBeInTheDocument()
    expect(screen.getByText(/No register data is available/)).toBeInTheDocument()
    expect(
      screen.getByText(
        /never boosts a match score or promises future eligibility/
      )
    ).toBeInTheDocument()
  })

  it("renders sponsorship from the register when the row carries it", async () => {
    withProfile()
    const history = measuredHistory()
    const row = history.matches[0] as Record<string, unknown>
    row.sponsor_status = "verified"
    row.sponsor_note = "Registered UK sponsor"
    server.use(
      http.get(`${BASE}/api/profiles/:profileId/matches`, () =>
        HttpResponse.json(history)
      )
    )
    renderApp({ route: ROUTE })

    expect(await screen.findByText("Registered UK sponsor")).toBeInTheDocument()
    expect(screen.queryByText(/Sponsorship unknown/)).not.toBeInTheDocument()
  })

  it("shows an honest empty state when the profile has not matched the job", async () => {
    withProfile()
    server.use(
      http.get(`${BASE}/api/profiles/:profileId/matches`, () =>
        HttpResponse.json({ profile_id: "profile-1", matches: [] })
      )
    )
    renderApp({ route: ROUTE })

    expect(
      await screen.findByText("No match history for this job")
    ).toBeInTheDocument()
    expect(screen.getByRole("link", { name: /Open Discover/ })).toHaveAttribute(
      "href",
      "/app/matches"
    )
  })

  it("renders the server's refusal as an error state with a way back", async () => {
    withProfile()
    server.use(
      http.get(`${BASE}/api/jobs/:jobId`, () =>
        HttpResponse.json(
          { detail: "Job 'greenhouse:1' not found" },
          { status: 404 }
        )
      )
    )
    renderApp({ route: ROUTE })

    expect(await screen.findByRole("alert")).toBeInTheDocument()
    expect(screen.getByText("Job 'greenhouse:1' not found")).toBeInTheDocument()
    expect(
      screen.getByRole("button", { name: /Try again/ })
    ).toBeInTheDocument()
  })

  it("names the tab after the listing", async () => {
    withProfile()
    renderApp({ route: ROUTE })

    await waitFor(() => {
      expect(document.title).toBe("AI Engineer · JobPilot")
    })
  })

  it("pins the wrap-anywhere contract on the listing title", async () => {
    /*
      jsdom cannot measure layout, so the *contract* is pinned here: a
      69-character unbreakable token measured 425 px inside a 311 px card
      with `break-words`, because it only breaks after the box has sized
      itself. `wrap-anywhere` also affects min-content sizing, so the box
      shrinks and the token breaks inside it. The real boxes are measured
      in the browser sweep at 360 px.
    */
    withProfile()
    const longToken = "S".repeat(69)
    server.use(
      http.get(`${BASE}/api/jobs/:jobId`, () =>
        HttpResponse.json({
          job: jobListing({ title: longToken }),
        })
      )
    )
    renderApp({ route: ROUTE })

    const heading = await screen.findByRole("heading", { level: 1 })
    expect(heading.className).toContain("wrap-anywhere")
  })

  it("rebuilds a match from a pre-role history row without fabricating values", async () => {
    withProfile()
    // The default factory row predates the role fields (WS-21): the safe
    // accessors default them, and the screen must still render.
    server.use(
      http.get(`${BASE}/api/profiles/:profileId/matches`, () =>
        HttpResponse.json(matchesHistory())
      )
    )
    renderApp({ route: ROUTE })

    expect(
      await screen.findByText("A good fit, with one gap.")
    ).toBeInTheDocument()
    expect(
      await screen.findByText(
        "The profile states Python and SQL, which the listing asks for."
      )
    ).toBeInTheDocument()
  })
})

describe("a failed match-history read on the job route (WS-36 review fix)", () => {
  /*
    Same distinction as Discover, and the same prohibition: "No match history
    for this job" is a claim about the candidate's profile that a failed read
    never established. Unknown must render as unknown, with the retry that
    makes a transient failure recoverable.
  */
  it("names the read failure instead of claiming there is no history", async () => {
    withProfile()
    server.use(
      http.get(`${BASE}/api/profiles/:profileId/matches`, () =>
        HttpResponse.json({ detail: "boom" }, { status: 500 })
      )
    )
    renderApp({ route: ROUTE })

    expect(
      await screen.findByText("The match for this listing could not be read.")
    ).toBeInTheDocument()
    expect(
      screen.queryByText("No match history for this job")
    ).not.toBeInTheDocument()
    expect(
      screen.getByRole("button", { name: "Try reading it again" })
    ).toBeInTheDocument()
    // The listing still renders; only the match section is unknown.
    expect(
      screen.getByRole("heading", { name: "AI Engineer" })
    ).toBeInTheDocument()
  })

  it("still says no history when the read succeeds and returns none", async () => {
    withProfile()
    server.use(
      http.get(`${BASE}/api/profiles/:profileId/matches`, () =>
        HttpResponse.json({ matches: [] })
      )
    )
    renderApp({ route: ROUTE })

    expect(
      await screen.findByText("No match history for this job")
    ).toBeInTheDocument()
    expect(
      screen.queryByText("The match for this listing could not be read.")
    ).not.toBeInTheDocument()
  })
})
