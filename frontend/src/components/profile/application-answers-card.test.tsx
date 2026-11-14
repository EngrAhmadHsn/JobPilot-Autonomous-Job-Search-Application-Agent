import { screen, within } from "@testing-library/react"
import { http, HttpResponse } from "msw"
import { describe, expect, it } from "vitest"

import { ApplicationProfilePanel } from "@/components/profile/application-profile-panel"
import { setCurrentProfileId } from "@/lib/profile"
import { renderScreen } from "@/test/render"
import { server } from "@/test/server"

const BASE = "http://api.test"

/**
 * WS-25b · The questions the boards actually ask.
 *
 * The panel rendered ten hard-coded fields in an order nobody measured —
 * and on the live corpus five of them have never been asked, while "First
 * Name" (30 sightings across 3 boards) and "Latitude" (24 across 2) were
 * invisible.
 *
 * Three properties are pinned, and the endpoint already guarantees all
 * three — the console must not undo them:
 *
 * 1. the order is the server's, most-asked first;
 * 2. each entry says *why* it is asked, naming the board count;
 * 3. a question the profile cannot answer that no board asks is **not**
 *    shown, and no measurement renders as no card at all rather than an
 *    empty one.
 */
describe("the measured questions card", () => {
  it("lists the measured questions most-asked first", async () => {
    setCurrentProfileId("profile-1")
    renderScreen(<ApplicationProfilePanel profileId="profile-1" />)

    const card = await screen.findByTestId("measured-questions")
    const labels = within(card)
      .getAllByRole("listitem")
      .map((item) => item.textContent ?? "")

    // The server's order: First Name (30) before Latitude (24) before the
    // board-specific question (12). Asserted as relative position so a
    // future re-wrap of the markup does not break the test.
    const first = labels.findIndex((text) => text.includes("First Name"))
    const latitude = labels.findIndex((text) => text.includes("Latitude"))
    const custom = labels.findIndex((text) => text.includes("Why do you want"))

    expect(first).toBeGreaterThanOrEqual(0)
    expect(latitude).toBeGreaterThan(first)
    expect(custom).toBeGreaterThan(latitude)
  })

  it("says why each question is asked", async () => {
    setCurrentProfileId("profile-1")
    renderScreen(<ApplicationProfilePanel profileId="profile-1" />)

    const card = await screen.findByTestId("measured-questions")
    // "First Name" is asked by 3 boards, and the sentence names the count.
    expect(within(card).getByText(/asked by 3 boards/i)).toBeInTheDocument()
    // Singular for one board: "asked by 1 board", not "1 boards".
    expect(within(card).getByText(/asked by 1 board\b/i)).toBeInTheDocument()
  })

  it("marks a required question as required", async () => {
    setCurrentProfileId("profile-1")
    renderScreen(<ApplicationProfilePanel profileId="profile-1" />)

    const card = await screen.findByTestId("measured-questions")
    const items = within(card).getAllByRole("listitem")
    const firstName = items.find((item) => item.textContent?.includes("First Name"))
    expect(firstName).toBeDefined()
    expect(within(firstName as HTMLElement).getByText(/required/i)).toBeInTheDocument()
  })

  it("renders no card when no board has published a schema", async () => {
    setCurrentProfileId("profile-1")
    server.use(
      http.get(`${BASE}/api/profiles/:profileId/question-gaps`, () =>
        HttpResponse.json({
          profile_id: "profile-1",
          total_observed: 0,
          questions: [],
        })
      )
    )
    renderScreen(<ApplicationProfilePanel profileId="profile-1" />)

    // The answers card is still there — the panel did not fall over — and
    // the measured card is absent rather than empty. An empty card is a
    // layout scar on a screen about answers.
    expect(await screen.findByText("Application answers")).toBeInTheDocument()
    expect(screen.queryByTestId("measured-questions")).not.toBeInTheDocument()
  })
})
