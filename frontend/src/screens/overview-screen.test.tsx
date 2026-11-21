import { screen, waitFor, within } from "@testing-library/react"
import { http, HttpResponse } from "msw"
import { describe, expect, it, vi } from "vitest"

import { OverviewScreen } from "@/screens/overview-screen"
import { eventLink } from "@/screens/overview/activity-feed"
import {
  applicationSummary,
  auditEvent,
  auditResponse,
  jobListing,
  matchesHistory,
} from "@/test/factories"
import { renderScreen } from "@/test/render"
import { server } from "@/test/server"
import { setCurrentProfileId } from "@/lib/profile"

import type { ApplicationList, AuditPage } from "@/lib/api/types"

// Production cadences compressed to milliseconds — see `test/polling-cadence.ts`.
vi.mock("@/lib/polling", async () => await import("@/test/polling-cadence"))

const BASE = "http://api.test"

const hold = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms))

/** A page shape exactly like `GET /api/applications` sends. */
function listPage(
  items: ApplicationList["items"],
  total: number,
  limit = 50
): ApplicationList {
  return { items, total, limit, offset: 0 }
}

/** One tracked application, shaped like the API sends, with overrides. */
function applicationWith(
  overrides: Partial<ApplicationList["items"][number]>
): ApplicationList["items"][number] {
  return { ...applicationSummary(), ...overrides }
}

/**
 * A tile of the stat strip, found by its label. The tile is a link once its
 * first read lands; before that it is a plain panel — both carry the
 * `data-stat-card` mark, so the helper finds either.
 */
function tileFor(label: string): HTMLElement {
  const tile = screen.getByText(label).closest("[data-stat-card]")
  if (!tile) throw new Error(`No stat tile found for "${label}"`)
  return tile as HTMLElement
}

/**
 * The applications list, answering each of the reads the screen polls: the
 * unfiltered totals read, the awaiting-approval page, the prepared page and
 * the submitted page — each with its own server `total`, deliberately
 * **larger than the page it returns**, so a screen that counted loaded rows
 * instead of the server's total fails here visibly. A resting `prepared`
 * application is a real backend state (the row is created PREPARED and only
 * then moved to AWAITING_APPROVAL), so it counts toward "need your
 * attention" exactly like an awaiting one.
 */
function useSplitApplicationTotals() {
  server.use(
    http.get(`${BASE}/api/applications`, ({ request }) => {
      const url = new URL(request.url)
      // **Every** requested status is honoured, including the multi-status
      // form the screen uses for its stage groups. That mirrors the API
      // since 2026-11-19: before the fix a two-status request silently
      // returned the unfiltered list, so a mock answering only exact single
      // statuses would have hidden the very bug this screen now relies on
      // being fixed.
      const requested = url.searchParams
        .getAll("status")
        .flatMap((value) => value.split(","))
        .filter(Boolean)
      const wants = (status: string) => requested.includes(status)

      if (wants("awaiting_approval")) {
        return HttpResponse.json(
          listPage(
            [
              applicationWith({
                id: "application-a1",
                job_title: "Backend Engineer",
                company_name: "TechFlow",
                status: "awaiting_approval",
                verified_at: null,
                submitted_at: null,
              }),
            ],
            1,
            10
          )
        )
      }
      if (wants("prepared")) {
        return HttpResponse.json(
          listPage(
            [
              applicationWith({
                id: "application-p1",
                job_title: "Platform Engineer",
                company_name: "Helios",
                status: "prepared",
                verified_at: null,
                submitted_at: null,
              }),
              applicationWith({
                id: "application-p2",
                job_title: "Data Engineer",
                company_name: "DataForge",
                status: "prepared",
                verified_at: null,
                submitted_at: null,
              }),
            ],
            2,
            10
          )
        )
      }
      if (wants("submitted")) {
        return HttpResponse.json(listPage([applicationSummary()], 3, 1))
      }
      if (
        wants("interview") ||
        wants("offer") ||
        wants("rejected") ||
        wants("withdrawn")
      ) {
        return HttpResponse.json(listPage([], 2, 1))
      }
      if (wants("verified")) {
        return HttpResponse.json(listPage([], 1, 1))
      }
      // The unfiltered totals read: a one-row page carrying the server's
      // total of seven.
      return HttpResponse.json(listPage([applicationSummary()], 7, 1))
    })
  )
}

describe("the Home dashboard", () => {
  it("counts from the server's totals, not from the loaded page", async () => {
    setCurrentProfileId("profile-1")
    useSplitApplicationTotals()
    renderScreen(<OverviewScreen />)

    // The design leads with the statement as the h1 (node 47:36); the tab
    // keeps the stable screen name ("Overview · JobPilot") through
    // `documentTitle`, which a separate document test pins.
    expect(
      await screen.findByRole("heading", { name: "Your next career move." })
    ).toBeInTheDocument()

    // The unfiltered read returns one row; the server says seven. WS-42
    // renamed the tile to the design's stage vocabulary ("Outcome recorded"
    // and "In progress" are the other two), so the total lives in the
    // pipeline panel's title, which is the one place that says how many
    // applications exist in all.
    await waitFor(() => {
      expect(
        screen.getByText(/Your pipeline · 7 applications/)
      ).toBeInTheDocument()
    })
    // The awaiting page returns one row and the prepared page two; the
    // server says 1 + 2 = 3 applications await a decision. The tile speaks
    // the **server totals**, not the two loaded rows.
    expect(
      within(tileFor("Awaiting review")).getByText("3")
    ).toBeInTheDocument()
    // The design's second stage groups the applications a human must
    // resolve but the machine cannot: verified submissions with no recorded
    // outcome yet. The server says one.
    expect(within(tileFor("Needs you")).getByText("1")).toBeInTheDocument()
    // The attention summary row also speaks the server total, not the rows
    // that happen to be loaded.
    expect(
      await screen.findByText("3 applications awaiting your approval")
    ).toBeInTheDocument()
    // The submitted page returns one row; the server says three.
    expect(within(tileFor("In progress")).getByText("3")).toBeInTheDocument()
    // The outcome group is the multi-status read over the four human
    // outcomes; the server says two.
    expect(
      within(tileFor("Outcome recorded")).getByText("2")
    ).toBeInTheDocument()
  })

  it("aggregates need-your-attention from real statuses and links each row to its resolver", async () => {
    setCurrentProfileId("profile-1")
    useSplitApplicationTotals()
    renderScreen(<OverviewScreen />)

    // The queue names the **task**, as the design's rows do ("Review your
    // Acorn application" / "The packet is ready for your decision."), and
    // the whole row is one link to the application's tracker page. The
    // design carries no status badge here — the row's membership in the
    // awaiting queue is the status — and the one shared status presentation
    // (`data-status`) remains pinned where statuses render, on the board.
    const rowA1 = (
      await screen.findByText("Review your TechFlow application")
    ).closest("a")
    expect(rowA1).toHaveAttribute("href", "/app/tracker/application-a1")
    const rowP2 = screen
      .getByText("Review your DataForge application")
      .closest("a")
    expect(rowP2).toHaveAttribute("href", "/app/tracker/application-p2")
    const rowP1 = screen
      .getByText("Review your Helios application")
      .closest("a")
    expect(rowP1).toHaveAttribute("href", "/app/tracker/application-p1")

    // The summary rows lead to the screens that resolve them.
    const approvalsLink = screen.getByRole("link", {
      name: /Review approvals/,
    })
    expect(approvalsLink).toHaveAttribute("href", "/app/approvals")
    const activityLink = screen.getByRole("link", { name: /Open activity/ })
    expect(activityLink).toHaveAttribute("href", "/app/activity")
    // The mocked trail holds one blocked challenge; the row says so, scoped
    // to the window the audit endpoint actually returns.
    expect(
      screen.getByText("1 trail event needs attention")
    ).toBeInTheDocument()
    // And the measured question gaps the profile does not answer.
    expect(
      await screen.findByText(
        /3 employer questions the profile does not answer/
      )
    ).toBeInTheDocument()
    expect(screen.getByRole("link", { name: /Open Profile/ })).toHaveAttribute(
      "href",
      "/app/profile"
    )
  })

  it("never claims all-clear while an attention source is unreadable", async () => {
    // Every clean source answers zero; the measured question gaps fail.
    setCurrentProfileId("profile-1")
    server.use(
      http.get(`${BASE}/api/applications`, () =>
        HttpResponse.json(listPage([], 0))
      ),
      http.get(`${BASE}/api/audit`, () =>
        HttpResponse.json({ events: [], count: 0 })
      ),
      http.get(`${BASE}/api/profiles/:profileId/question-gaps`, () =>
        HttpResponse.json(
          { detail: "The server failed to handle the request." },
          { status: 500 }
        )
      ),
      http.get(`${BASE}/api/profiles/:profileId/matches`, () =>
        HttpResponse.json({ profile_id: "profile-1", matches: [] })
      )
    )
    renderScreen(<OverviewScreen />)

    // The failure is named, with the way back…
    expect(
      await screen.findByText("Employer questions couldn't be read")
    ).toBeInTheDocument()
    expect(
      screen.getByRole("button", { name: /Try again/ })
    ).toBeInTheDocument()
    // …and the empty state never claims a clean bill of health while a
    // source is unknown.
    expect(
      screen.queryByText("Nothing needs you right now")
    ).not.toBeInTheDocument()
  })

  it("renders every section honestly when the account is empty", async () => {
    // No profile chosen, no applications, no matches, no trail rows.
    server.use(
      http.get(`${BASE}/api/applications`, () =>
        HttpResponse.json(listPage([], 0))
      ),
      http.get(`${BASE}/api/audit`, () =>
        HttpResponse.json({ events: [], count: 0 })
      ),
      http.get(`${BASE}/api/profiles/:profileId/matches`, () =>
        HttpResponse.json({ profile_id: "profile-1", matches: [] })
      ),
      http.get(`${BASE}/api/profiles/:profileId/question-gaps`, () =>
        HttpResponse.json({
          profile_id: "profile-1",
          total_observed: 0,
          questions: [],
        })
      ),
      http.get(`${BASE}/api/documents`, () =>
        HttpResponse.json({ documents: [], count: 0 })
      )
    )
    renderScreen(<OverviewScreen />)

    // The attention section is the honest empty state, with the one real
    // ask (a résumé) as a row, because a profile is genuinely missing.
    expect(await screen.findByText("Upload a résumé")).toBeInTheDocument()
    expect(screen.getByRole("link", { name: /Go to Resume/ })).toHaveAttribute(
      "href",
      "/app/resume"
    )

    // Real server zeros on the stage strip — never a stand-in number. WS-42
    // replaced the old four metric tiles with the design's four pipeline
    // stages, and each of them must read the server's own zero.
    await waitFor(() => {
      expect(
        within(tileFor("Awaiting review")).getByText("0")
      ).toBeInTheDocument()
    })
    expect(within(tileFor("Needs you")).getByText("0")).toBeInTheDocument()
    expect(within(tileFor("In progress")).getByText("0")).toBeInTheDocument()
    expect(
      within(tileFor("Outcome recorded")).getByText("0")
    ).toBeInTheDocument()

    // The featured slot and the feed are honest empties, not placeholder cards.
    expect(await screen.findByText("No matches yet")).toBeInTheDocument()
    expect(screen.getByText("No recorded activity yet")).toBeInTheDocument()

    // Nothing from the reference's illustrative set may appear.
    expect(screen.queryByText(/Live/)).not.toBeInTheDocument()
    expect(screen.queryByText(/\+2/)).not.toBeInTheDocument()
    expect(screen.queryByText(/Pro Plan/)).not.toBeInTheDocument()
    expect(screen.queryByText(/Company Fit/)).not.toBeInTheDocument()
    expect(screen.queryByText(/96%/)).not.toBeInTheDocument()
  })

  it("attributes the trail's actors and links the rows that have a real destination", async () => {
    setCurrentProfileId("profile-1")
    server.use(
      http.get(`${BASE}/api/audit`, () => {
        const page: AuditPage = {
          // The digest shows the design's three-row window (nodes
          // 49:812–49:835), so the mock puts one row of **each actor** in
          // it: the agent's unknown action, the person's approval, and the
          // system's blocked step.
          events: [
            // An action the console has no label for: shown verbatim, and
            // linked nowhere rather than to a guessed destination.
            auditEvent({
              id: 60,
              action: "something.unheard",
              actor: "agent",
              actor_kind: "agent",
              outcome: "success",
            }),
            auditEvent({
              id: 59,
              action: "application.approve",
              actor: "human:operator",
              actor_kind: "user",
              outcome: "success",
            }),
            auditEvent({
              id: 58,
              action: "application.blocked_challenge",
              actor: "system",
              actor_kind: "system",
              outcome: "blocked",
            }),
          ],
          count: 3,
        }
        return HttpResponse.json(page)
      })
    )
    renderScreen(<OverviewScreen />)

    // Attribution: the chip names the actor — the design's digest chips
    // read AGENT / YOU / SYSTEM (node 49:811) — and a blocked step reads as
    // the SYSTEM's call-out, not the agent's: a blocked step is a platform
    // stop, which is how the shared trail presents it too. (The chip's
    // uppercase is CSS; the DOM text is "Agent", so the match is
    // case-insensitive and exact.)
    // One row of each actor, in the design's three-row window.
    await waitFor(() => {
      expect(screen.getAllByText(/^agent$/i)).toHaveLength(1)
    })
    expect(screen.getAllByText(/^you$/i)).toHaveLength(1)
    expect(screen.getAllByText(/^system$/i)).toHaveLength(1)
    expect(
      screen.getAllByText(/stopped at a captcha or multi-factor prompt/i).length
    ).toBeGreaterThanOrEqual(1)
    expect(
      screen.getAllByText(/approved an application/i).length
    ).toBeGreaterThanOrEqual(1)
    // The unknown action is not hidden and not invented into a label, and
    // it carries no link at all.
    expect(screen.getByText(/something\.unheard/)).toBeInTheDocument()

    // The rows that have a real destination carry it: the approval leads to
    // the Review surface, the blocked challenge to the full trail.
    const reviewLinks = screen.getAllByRole("link", { name: /Review/ })
    expect(reviewLinks[0]).toHaveAttribute("href", "/app/approvals")
    const trailLinks = screen.getAllByRole("link", { name: /Trail/ })
    expect(trailLinks[0]).toHaveAttribute("href", "/app/activity")
    // The unknown action row carries no link at all.
    expect(
      screen
        .getAllByRole("link")
        .filter((link) => link.textContent?.includes("something.unheard"))
    ).toHaveLength(0)

    // The rest of the link table is the feed's own mapping, pinned directly:
    // submission work → Tracker, uploads → Resume, and an action the map
    // does not know → nowhere rather than a guessed destination.
    expect(eventLink(auditEvent({ action: "application.submit" }))?.to).toBe(
      "/app/tracker"
    )
    expect(eventLink(auditEvent({ action: "resume.upload" }))?.to).toBe(
      "/app/resume"
    )
    expect(eventLink(auditEvent({ action: "something.else" }))).toBeNull()
  })

  it("renders unknown match components as unknown, never as their zero score", async () => {
    setCurrentProfileId("profile-1")
    server.use(
      http.get(`${BASE}/api/profiles/:profileId/matches`, () =>
        HttpResponse.json({
          profile_id: "profile-1",
          matches: [
            {
              profile_id: "profile-1",
              job_id: "greenhouse:1",
              scores: {
                overall_score: 82.5,
                semantic_score: 80,
                skill_score: 90,
                experience_score: 75,
                location_score: 0,
                evidence_coverage: 100,
                component_states: {
                  semantic: "MATCHED",
                  skill: "MATCHED",
                  experience: "MATCHED",
                  // The candidate never said where they want to work: the
                  // component rests on nothing, and must not read as a 0.
                  location: "CANDIDATE_DATA_MISSING",
                },
                matched_requirements: ["Python", "SQL"],
                missing_requirements: ["Kubernetes"],
              },
              explanation:
                "The profile states Python and SQL, which the listing asks for.",
              created_at: "2026-10-21T10:00:00Z",
            },
          ],
        })
      )
    )
    renderScreen(<OverviewScreen />)

    // The featured card is the design's "Recommended role" card (node
    // 49:836): the score chip, the title, the meta line, the rationale.
    // The component-score breakdown lives on the match's own screen — where
    // the WS-20 rule (an unknown component renders its reason, never the
    // raw 0.0) stays pinned by the matches and job-detail tests.
    expect(
      await screen.findByRole("heading", { name: "AI Engineer" })
    ).toBeInTheDocument()
    expect(screen.getByText(/83 \/ 100 match/i)).toBeInTheDocument()
    // The zero the raw score carries for the unknown component never
    // renders as a value here either.
    expect(screen.queryByText("0.0")).not.toBeInTheDocument()

    // The one action, at the match's own screen.
    expect(
      screen.getByRole("link", { name: /Explore matches/ })
    ).toHaveAttribute("href", "/app/matches/greenhouse%3A1")
  })

  it("polls only the applications and audit reads, on the shared interval, and pauses when hidden", async () => {
    const applicationPaths: string[] = []
    const auditPaths: string[] = []
    server.use(
      http.get(`${BASE}/api/applications`, ({ request }) => {
        applicationPaths.push(new URL(request.url).pathname)
        return HttpResponse.json(listPage([applicationSummary()], 1, 50))
      }),
      http.get(`${BASE}/api/audit`, ({ request }) => {
        auditPaths.push(new URL(request.url).pathname)
        return HttpResponse.json(auditResponse())
      })
    )
    renderScreen(<OverviewScreen />)

    // The mount reads fire, then the interval refetches only the same two
    // endpoints — the ranked matches, the listings, the profile and the
    // question gaps are per-mount reads, not part of any cycle.
    await waitFor(() => expect(auditPaths.length).toBeGreaterThanOrEqual(3), {
      timeout: 2_000,
    })
    expect(applicationPaths.length).toBeGreaterThanOrEqual(3)
    for (const path of applicationPaths) expect(path).toBe("/api/applications")
    for (const path of auditPaths) expect(path).toBe("/api/audit")
  })

  it("does not poll while the tab is hidden, and resumes when it returns", async () => {
    let hidden = true
    Object.defineProperty(document, "visibilityState", {
      configurable: true,
      get: () => (hidden ? "hidden" : "visible"),
    })
    let auditCalls = 0
    server.use(
      http.get(`${BASE}/api/audit`, () => {
        auditCalls += 1
        return HttpResponse.json(auditResponse())
      })
    )
    renderScreen(<OverviewScreen />)

    // The mount fetch happens; the interval behind it must not.
    await waitFor(() => expect(auditCalls).toBe(1))
    await hold(300)
    expect(auditCalls).toBe(1)

    hidden = false
    window.dispatchEvent(new Event("visibilitychange"))
    await waitFor(() => expect(auditCalls).toBeGreaterThanOrEqual(2), {
      timeout: 1_000,
    })
  })

  it("keeps the matched listing's honest fallback when the listing cannot be read", async () => {
    setCurrentProfileId("profile-1")
    server.use(
      http.get(`${BASE}/api/jobs/greenhouse%3A1`, () =>
        HttpResponse.json(
          { detail: "Job 'greenhouse:1' not found" },
          { status: 404 }
        )
      )
    )
    renderScreen(<OverviewScreen />)

    // The ranked match exists but its listing did not answer: the card says
    // so and points at the screen that re-runs the search — no fabricated
    // card, no broken frame.
    expect(
      await screen.findByText(/The top match's listing can't be shown/)
    ).toBeInTheDocument()
    expect(screen.getByRole("link", { name: /Open Matches/ })).toHaveAttribute(
      "href",
      "/app/matches"
    )
  })

  it("names the poll, not a stream: the feed says its window and interval", async () => {
    setCurrentProfileId("profile-1")
    renderScreen(<OverviewScreen />)

    // The feed's provenance line, at the digest's foot, states the interval
    // and the window. (The interval's number comes from `OVERVIEW_POLL_MS`,
    // which this file compresses to milliseconds — the real 30-second
    // cadence is pinned in `lib/polling.test.ts`.)
    expect(await screen.findByText(/updated every/i)).toBeInTheDocument()
    expect(screen.getByText(/newest 100 events/i)).toBeInTheDocument()
    // The trail's window is stated once — the feed is the first audit page,
    // never presented as the whole history.
    expect(
      screen.getByText(/the first page, not the whole history/i)
    ).toBeInTheDocument()
    // And no "Live" badge, anywhere.
    expect(screen.queryByText("Live")).not.toBeInTheDocument()
  })

  it("shows the profile's matches' honest shortlist only when more matches exist", async () => {
    setCurrentProfileId("profile-1")
    server.use(
      http.get(`${BASE}/api/profiles/:profileId/matches`, () => {
        const history = matchesHistory()
        return HttpResponse.json({
          profile_id: "profile-1",
          matches: [
            history.matches[0],
            {
              profile_id: "profile-1",
              job_id: "lever:2",
              scores: {
                overall_score: 74.5,
                semantic_score: 70,
                skill_score: 80,
                experience_score: 70,
                location_score: 100,
                evidence_coverage: 90,
                component_states: { semantic: "MATCHED", skill: "MATCHED" },
                matched_requirements: ["Python"],
              },
              explanation: "A reasonable second match.",
              created_at: "2026-10-21T09:00:00Z",
            },
          ],
        })
      }),
      // The listing read echoes the requested id, so each shortlist card's
      // link carries its own job's destination.
      http.get(`${BASE}/api/jobs/:jobId`, ({ params }) =>
        HttpResponse.json({ job: jobListing({ id: String(params.jobId) }) })
      )
    )
    renderScreen(<OverviewScreen />)

    // The shortlist row renders the additional real match…
    const section = await screen.findByText("Also strong")
    expect(section).toBeInTheDocument()
    expect(screen.getByText(/74\.5/)).toBeInTheDocument()
    // …linked to the job's own screen.
    const card = screen
      .getAllByRole("link", { name: /View details/ })
      .find((link) => link.getAttribute("href") === "/app/matches/lever%3A2")
    expect(card).toBeInTheDocument()
  })
})
