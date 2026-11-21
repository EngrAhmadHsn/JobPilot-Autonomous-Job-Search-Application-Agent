import { screen, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { http, HttpResponse } from "msw"
import { beforeAll, describe, expect, it, vi } from "vitest"

import { ApplicationProfilePanel } from "@/components/profile/application-profile-panel"
import { setCurrentProfileId } from "@/lib/profile"
import { renderScreen } from "@/test/render"
import { server } from "@/test/server"

const BASE = "http://api.test"

/**
 * WS-25b · The questions the boards actually ask — and, since WS-45, the
 * gap rows that turn them into actions.
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
    const firstName = items.find((item) =>
      item.textContent?.includes("First Name")
    )
    expect(firstName).toBeDefined()
    expect(
      within(firstName as HTMLElement).getByText(/required/i)
    ).toBeInTheDocument()
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

/*
  WS-45 · The gaps UI (`20 · Questions & privacy`).

  A gap row is an action, not a statistic: the chip says whether the answer
  exists (Needs answer / Confirmed / Never autofilled, in the backend's own
  coverage words), and — when the category maps onto a field on this screen —
  an "Add answer →"/"Edit answer →" link focuses that field. A category with
  no field here (a candidate's first name, a latitude, a board-specific
  question) gets **no** link: those questions are answered on the employer's
  own form at review time, and a link that goes nowhere is a lie.
*/
describe("the question gaps rows (WS-45)", () => {
  function stubGaps(questions: Array<Record<string, unknown>>) {
    server.use(
      http.get(`${BASE}/api/profiles/:profileId/question-gaps`, () =>
        HttpResponse.json({
          profile_id: "profile-1",
          total_observed: questions.length * 10,
          questions,
        })
      )
    )
  }

  beforeAll(() => {
    // jsdom does not implement scrolling; the row link scrolls the field
    // into view before focusing it.
    Element.prototype.scrollIntoView = vi.fn()
  })

  it("reads each gap's coverage as the design's chips", async () => {
    setCurrentProfileId("profile-1")
    stubGaps([
      {
        label: "Visa sponsorship",
        times_seen: 12,
        boards: 3,
        required: true,
        category: "visa_sponsorship",
        block: "questions",
        coverage: "not_in_profile",
      },
      {
        label: "Notice period",
        times_seen: 8,
        boards: 2,
        required: false,
        category: "notice_period",
        block: "questions",
        coverage: "answered",
      },
      {
        label: "Signature",
        times_seen: 4,
        boards: 1,
        required: false,
        category: "attestation",
        block: "questions",
        coverage: "never_autofill",
      },
    ])
    renderScreen(<ApplicationProfilePanel profileId="profile-1" />)

    const card = await screen.findByTestId("measured-questions")
    const rows = within(card).getAllByRole("listitem")

    expect(
      within(rows[0] as HTMLElement).getByText("Needs answer")
    ).toBeInTheDocument()
    expect(
      within(rows[1] as HTMLElement).getByText("Confirmed")
    ).toBeInTheDocument()
    expect(
      within(rows[2] as HTMLElement).getByText("Never autofilled")
    ).toBeInTheDocument()
  })

  it("links a mappable gap to its field and focuses it", async () => {
    setCurrentProfileId("profile-1")
    stubGaps([
      {
        label: "Visa sponsorship",
        times_seen: 12,
        boards: 3,
        required: true,
        category: "visa_sponsorship",
        block: "questions",
        coverage: "not_in_profile",
      },
      {
        label: "Notice period",
        times_seen: 8,
        boards: 2,
        required: false,
        category: "notice_period",
        block: "questions",
        coverage: "answered",
      },
    ])
    renderScreen(<ApplicationProfilePanel profileId="profile-1" />)

    const card = await screen.findByTestId("measured-questions")
    const rows = within(card).getAllByRole("listitem")

    // Unanswered → "Add answer →"; answered → "Edit answer →".
    const add = within(rows[0] as HTMLElement).getByRole("button", {
      name: "Add answer →",
    })
    const user = userEvent.setup()
    await user.click(add)
    expect(document.activeElement).toBe(
      document.getElementById("field-sponsorship")
    )

    expect(
      within(rows[1] as HTMLElement).getByRole("button", {
        name: "Edit answer →",
      })
    ).toBeInTheDocument()
  })

  it("offers no link for a category this screen cannot answer", async () => {
    setCurrentProfileId("profile-1")
    stubGaps([
      {
        label: "First Name",
        times_seen: 30,
        boards: 3,
        required: true,
        category: "candidate_first_name",
        block: "questions",
        coverage: "not_in_profile",
      },
      {
        label: "Latitude",
        times_seen: 24,
        boards: 2,
        required: true,
        category: "location_latitude",
        block: "questions",
        coverage: "not_in_profile",
      },
    ])
    renderScreen(<ApplicationProfilePanel profileId="profile-1" />)

    const card = await screen.findByTestId("measured-questions")
    // The names and coordinates are on the résumé, not in this form —
    // pretending otherwise would offer a link that ends nowhere.
    expect(within(card).queryByRole("button")).toBeNull()
  })
})

/*
  WS-45 · Voluntary self-identification, restyled to `20 · Questions &
  privacy`: the card leads with what the data is ("Voluntary · Separate"),
  states the stored state as a chip, and discloses the fields behind
  "Manage voluntary answers" instead of always showing an empty form.
*/
describe("the voluntary answers card (WS-45)", () => {
  it("leads with what the data is and states the stored state", async () => {
    setCurrentProfileId("profile-1")
    renderScreen(<ApplicationProfilePanel profileId="profile-1" />)

    expect(await screen.findByText("Voluntary · Separate")).toBeInTheDocument()
    expect(
      screen.getByText("Your choice. Never a ranking signal.")
    ).toBeInTheDocument()
    expect(screen.getByTestId("eeo-state")).toHaveTextContent(
      "Off · no answers saved"
    )
    // The honesty line the design puts under the actions.
    expect(
      screen.getByText(
        "Only supported work-eligibility countries are selectable. Missing employer answers stop execution for your review."
      )
    ).toBeInTheDocument()
  })

  it("discloses the fields behind Manage voluntary answers, and keeps delete available", async () => {
    setCurrentProfileId("profile-1")
    renderScreen(<ApplicationProfilePanel profileId="profile-1" />)

    const card = await screen.findByTestId("voluntary-answers")
    // Off state: no empty form on show.
    expect(within(card).queryByLabelText(/Race \/ ethnicity/)).toBeNull()

    const user = userEvent.setup()
    await user.click(
      within(card).getByRole("button", { name: "Manage voluntary answers" })
    )

    const optIn = within(card).getByLabelText(/I want to provide these details/)
    expect(optIn).not.toBeChecked()
    expect(within(card).getByLabelText(/Race \/ ethnicity/)).toBeDisabled()

    // Delete is reachable from either state.
    expect(
      within(card).getByRole("button", { name: "Delete answers" })
    ).toBeInTheDocument()
  })

  it("reads On and the stored answers once the account opted in", async () => {
    setCurrentProfileId("profile-1")
    server.use(
      http.get(`${BASE}/api/profiles/:profileId/eeo`, () =>
        HttpResponse.json({
          profile_id: "profile-1",
          eeo: { opt_in: true, gender: "Woman" },
        })
      )
    )
    renderScreen(<ApplicationProfilePanel profileId="profile-1" />)

    const card = await screen.findByTestId("voluntary-answers")
    expect(await screen.findByTestId("eeo-state")).toHaveTextContent(
      "On · answers stored"
    )
    // Already opted in: the editor is open without a second click.
    const gender = await within(card).findByLabelText(/Gender/)
    expect(gender).toHaveValue("Woman")
    expect(gender).toBeEnabled()
  })
})

/*
  WS-45 · Work authorization is asked per country (`11 · Application
  profile`), with the anywhere-fallback tri-state kept as the secondary
  question and the never-inferred sponsorship note in the design's terracotta.
*/
describe("the context-dependent authorization questions (WS-45)", () => {
  it("asks the work eligibility country as the primary authorization question", async () => {
    setCurrentProfileId("profile-1")
    renderScreen(<ApplicationProfilePanel profileId="profile-1" />)

    const picker = await screen.findByTestId("authorized-countries")
    const field = picker.closest("label") as HTMLElement
    expect(
      within(field).getByText("Work eligibility country")
    ).toBeInTheDocument()
    // The design's honest help: a missing answer is a stop, not a guess.
    expect(
      within(field).getByText(
        "Choose every country you may work in. A missing answer stops form filling instead of guessing."
      )
    ).toBeInTheDocument()
  })

  it("keeps the anywhere-fallback tri-state as a secondary question", async () => {
    setCurrentProfileId("profile-1")
    renderScreen(<ApplicationProfilePanel profileId="profile-1" />)

    /*
      The fields are queried by role and name rather than by `labelText`:
      the repo's field pattern keeps the help text inside the wrapping
      `<label>`, so the accessible name carries the hint along with the
      question — a name matcher matches it, an exact text match would not.
    */
    const tri = await screen.findByRole("combobox", {
      name: /Legally authorized to work\?/,
    })
    expect(
      within(tri).getByRole("option", { name: "Not answered" })
    ).toBeInTheDocument()
    // The context-free framing is gone — it pretended a single yes/no could
    // answer a per-country question.
    expect(screen.queryByText("Authorized to work here?")).toBeNull()
    // And the copy names what the fallback actually is (WS-25c).
    expect(
      screen.getByText(
        /with no countries listed above, this answers for any country/i
      )
    ).toBeInTheDocument()
  })

  it("wears the required styling while visa sponsorship is unanswered", async () => {
    setCurrentProfileId("profile-1")
    renderScreen(<ApplicationProfilePanel profileId="profile-1" />)

    const sponsorship = await screen.findByRole("combobox", {
      name: /Need visa sponsorship/,
    })
    expect(sponsorship).toHaveClass("border-terracotta")
    expect(
      screen.getByText(
        "This answer is required. It is never inferred from your résumé."
      )
    ).toBeInTheDocument()
  })
})
