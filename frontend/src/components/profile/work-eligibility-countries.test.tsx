import { screen, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { http, HttpResponse } from "msw"
import { describe, expect, it } from "vitest"

import { ApplicationProfilePanel } from "@/components/profile/application-profile-panel"
import { setCurrentProfileId } from "@/lib/profile"
import { renderScreen } from "@/test/render"
import { server } from "@/test/server"

const BASE = "http://api.test"

/**
 * WS-25c · Work eligibility is stated **by country**.
 *
 * The boards ask "Are you authorized to work in the country for which you
 * apply?" — required on 12 live listings — and a single yes/no cannot answer
 * it: authorized in the UK is not authorized in the US. A blanket "yes"
 * filled into a US posting's authorization question is a fabricated statement
 * about the candidate's legal right to work.
 *
 * So the profile states the countries it may work in, and this file pins the
 * UI's half of that contract:
 *
 * 1. the picker lists the countries the **API** serves, not a copy kept in the
 *    component (a drifted copy offers a value the model then refuses);
 * 2. selecting several countries and saving sends canonical codes;
 * 3. the stored countries come back selected, so the screen is a round trip;
 * 4. an empty selection is a real state — "not stated" — and is offered as
 *    such rather than being forced.
 *
 * The panel renders the answers card, so the country control is found by its
 * label rather than by a component name — the test survives a re-wrap of the
 * surrounding card.
 */
function stubCountries() {
  server.use(
    http.get(`${BASE}/api/profiles/countries`, () =>
      HttpResponse.json({
        countries: [
          { code: "CA", name: "Canada" },
          { code: "DE", name: "Germany" },
          { code: "GB", name: "United Kingdom" },
          { code: "US", name: "United States" },
        ],
      })
    )
  )
}

describe("stating work eligibility by country", () => {
  it("offers the countries the API serves", async () => {
    setCurrentProfileId("profile-1")
    stubCountries()
    renderScreen(<ApplicationProfilePanel profileId="profile-1" />)

    const picker = await screen.findByTestId("authorized-countries")
    // The options arrive with the fetch, so this is an async query: awaiting
    // it is what proves the list came from the API rather than the component.
    const options = (await within(picker).findAllByRole("option")).map(
      (o) => o.textContent
    )

    // Served order, and every served country is offered.
    expect(options).toEqual([
      "Canada",
      "Germany",
      "United Kingdom",
      "United States",
    ])
  })

  it("shows the stored countries as selected", async () => {
    setCurrentProfileId("profile-1")
    stubCountries()
    server.use(
      http.get(`${BASE}/api/profiles/:profileId/application-profile`, () =>
        HttpResponse.json({
          profile_id: "profile-1",
          application_profile: {
            professional: {},
            preferences: { preferred_locations: [], employment_types: [] },
            answers: {
              work_authorization: {
                legally_authorized: null,
                requires_sponsorship: null,
                authorized_countries: ["GB", "DE"],
              },
              compensation: {},
              notice: {},
            },
          },
        })
      )
    )
    renderScreen(<ApplicationProfilePanel profileId="profile-1" />)

    const picker = (await screen.findByTestId(
      "authorized-countries"
    )) as HTMLSelectElement
    // Wait for the options, then read what is selected.
    await within(picker).findAllByRole("option")
    const selected = Array.from(picker.selectedOptions).map((o) => o.value)
    expect(selected).toEqual(["DE", "GB"])
  })

  it("sends the selected countries as canonical codes on save", async () => {
    setCurrentProfileId("profile-1")
    stubCountries()

    let saved: unknown = null
    server.use(
      http.put(
        `${BASE}/api/profiles/:profileId/application-profile`,
        async ({ request }) => {
          saved = await request.json()
          return HttpResponse.json({
            profile_id: "profile-1",
            application_profile: (saved as { application_profile?: unknown })
              .application_profile,
          })
        }
      )
    )

    const user = userEvent.setup({ delay: null })
    renderScreen(<ApplicationProfilePanel profileId="profile-1" />)

    const picker = (await screen.findByTestId(
      "authorized-countries"
    )) as HTMLSelectElement
    await within(picker).findAllByRole("option")
    await user.selectOptions(picker, ["GB", "DE"])
    // The panel holds two save buttons — one per card — so this names the
    // answers one rather than matching /save/i and matching either.
    await user.click(screen.getByRole("button", { name: "Save answers" }))

    const sent = saved as {
      answers: { work_authorization: { authorized_countries: string[] } }
    }
    // Canonical codes, and the country list travels with the answers the agent
    // reads — not as free text. The order is the picker's (DOM) order, which
    // is how the browser reports `selectedOptions`; asserting the set is the
    // stable contract, and the API re-canonicalizes on the way in anyway.
    expect(
      [...sent.answers.work_authorization.authorized_countries].sort()
    ).toEqual(["DE", "GB"])
    expect(sent.answers.work_authorization.authorized_countries).toHaveLength(2)
  })

  it("keeps an unanswered list unanswered rather than forcing a country", async () => {
    setCurrentProfileId("profile-1")
    stubCountries()
    renderScreen(<ApplicationProfilePanel profileId="profile-1" />)

    const picker = (await screen.findByTestId(
      "authorized-countries"
    )) as HTMLSelectElement
    expect(Array.from(picker.selectedOptions)).toHaveLength(0)
  })

  it("explains why the countries are asked for", async () => {
    setCurrentProfileId("profile-1")
    stubCountries()
    renderScreen(<ApplicationProfilePanel profileId="profile-1" />)

    const picker = await screen.findByTestId("authorized-countries")
    const field = picker.closest("label") as HTMLElement
    // The primary question's label, from the design (`11 · Application
    // profile`): eligibility is asked per country, not in the abstract.
    expect(
      within(field).getByText("Work eligibility country")
    ).toBeInTheDocument()
    // And the hint must name the cost of leaving it unanswered: a stop, not
    // a guess.
    expect(
      within(field).getByText(
        "Choose every country you may work in. A missing answer stops form filling instead of guessing."
      )
    ).toBeInTheDocument()
  })
})
