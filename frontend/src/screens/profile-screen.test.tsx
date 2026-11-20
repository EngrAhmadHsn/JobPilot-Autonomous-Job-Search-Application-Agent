import { screen, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { http, HttpResponse } from "msw"
import { describe, expect, it } from "vitest"

import { ProfileScreen } from "@/screens/profile-screen"
import { profileResponse } from "@/test/factories"
import { setCurrentProfileId } from "@/lib/profile"
import { server } from "@/test/server"
import { renderScreen } from "@/test/render"

const BASE = "http://api.test"

/**
 * WS-27 · Where the model-credentials card sits.
 *
 * The card was appended to the bottom of the Profile screen as a **bare
 * card**, after the résumé block: the only orphan card in the console, last
 * on a page about profile answers, and outside the heading outline. Its own
 * docstring calls it an account setting.
 *
 * Two properties are pinned here, and both have a real regression behind
 * them:
 *
 * 1. it belongs with the answer cards, **above** the résumé — a setting
 *    before reference material;
 * 2. it renders **without a stored profile**, which the old code claimed in
 *    a comment and then contradicted with an early return. A deployment in
 *    `required` mode could not take a key before the first résumé, so the
 *    one screen that fixes a rejected tailoring run was unreachable.
 */

function stubCredentials() {
  server.use(
    http.get(`${BASE}/api/llm/credentials`, () =>
      HttpResponse.json({
        using: "platform",
        provider: "google",
        model: "gemini-3.8-flash",
        hint: "",
      })
    )
  )
}

describe("the credential card on the profile screen", () => {
  it("sits below the tab set, reachable on every tab", async () => {
    setCurrentProfileId("profile-1")
    stubCredentials()

    const { container } = renderScreen(<ProfileScreen />)

    // Both are on the page.
    expect(
      await screen.findByRole("button", { name: "Save key" })
    ).toBeInTheDocument()

    /*
      WS-40 tabbed the profile. WS-27's rule survives: the card renders in
      **all three** states, so it sits outside the `storedProfile.data` guard
      that wraps the tabs — a `required`-mode deployment must be able to take
      a key before the first résumé exists. Asserted on the rendered document
      with `compareDocumentPosition`, so any future re-wrap of the JSX keeps
      the check meaningful.
    */
    const tabs = await screen.findByRole("tablist")
    const credentials = screen.getByRole("button", { name: "Save key" })
    expect(
      tabs.compareDocumentPosition(credentials) &
        Node.DOCUMENT_POSITION_FOLLOWING
    ).toBeTruthy()

    // And the section is a real section: it contributes an h2.
    expect(
      container.querySelectorAll("h2") &&
        screen.getByRole("heading", { name: "Your model" })
    ).toBeInTheDocument()
  })

  it("renders even when the account has no profile yet", async () => {
    /*
      No profile id, and no documents: `useProfileWithFallback` resolves to
      "missing", which used to hit the early return. The card must still be
      reachable — otherwise a `BYOK_MODE=required` deployment is unstartable.
      This is the regression the WS-40 tabbing could have reintroduced by
      putting the card inside the tabs.
    */
    setCurrentProfileId(null)
    stubCredentials()
    server.use(
      http.get(`${BASE}/api/documents`, () =>
        HttpResponse.json({ documents: [] })
      )
    )

    renderScreen(<ProfileScreen />)

    expect(
      await screen.findByRole("button", { name: "Save key" })
    ).toBeInTheDocument()
    expect(
      screen.getByRole("heading", { name: "Your model" })
    ).toBeInTheDocument()
    // And the page still explains the missing profile — once the document
    // list resolves and the hook stops being pending.
    expect(await screen.findByText("No profile yet")).toBeInTheDocument()
  })

  it("keeps the preferences editor reachable on its tab", async () => {
    /*
      The reorder must not have pushed the answer cards off the page. WS-42
      rebuilt the tabs to the design's three, so reachability — not mere
      presence in the tree — is what this pins now: click the tab, then see
      the editor.
    */
    setCurrentProfileId("profile-1")
    stubCredentials()
    server.use(
      http.get(`${BASE}/api/resumes/:profileId`, () =>
        HttpResponse.json(profileResponse())
      )
    )

    const user = userEvent.setup()
    renderScreen(<ProfileScreen />)

    await user.click(
      await screen.findByRole("tab", { name: "Work preferences" })
    )
    // The editor's own description proves the card is mounted — the tab
    // trigger carries the same words, so the count is at least two.
    expect(screen.getAllByText(/What you want from a job/).length).toBeGreaterThan(
      0
    )
    expect(screen.getByRole("button", { name: "Save key" })).toBeInTheDocument()
  })
})

describe("the design's tabbed profile (WS-42, from WS-40)", () => {
  /*
    The design file (node `16:202`) draws three content tabs — Documents ·
    Application answers · Work preferences — and the Documents card carries
    the upload action. Every tab must render real content — a tab that opens
    onto nothing is worse than no tab, because it promises a surface that
    does not exist.
  */
  it("offers the design's three tabs and every one opens onto real content", async () => {
    setCurrentProfileId("profile-1")
    stubCredentials()
    server.use(
      http.get(`${BASE}/api/resumes/:profileId`, () =>
        HttpResponse.json(profileResponse())
      )
    )

    const user = userEvent.setup()
    renderScreen(<ProfileScreen />)

    const tabs = await screen.findByRole("tablist")
    for (const name of ["Documents", "Application answers", "Work preferences"]) {
      expect(within(tabs).getByRole("tab", { name })).toBeInTheDocument()
    }

    // Documents: the library, with provenance chips on both kinds.
    expect(
      screen.getByText("Your original stays original.")
    ).toBeInTheDocument()
    expect(screen.getByText("ORIGINAL")).toBeInTheDocument()
    expect(screen.getByText("TAILORED")).toBeInTheDocument()
    expect(screen.getAllByText("In use").length).toBeGreaterThan(0)

    // The source-facts reveal opens onto the parsed résumé.
    await user.click(
      screen.getByRole("button", { name: "View source facts →" })
    )
    expect(
      await screen.findByText(/roles on record|role on record/)
    ).toBeInTheDocument()

    // Application answers: the confirmed-answers panel, gaps included.
    await user.click(screen.getByRole("tab", { name: "Application answers" }))
    expect(
      await screen.findByText("Questions the boards actually ask")
    ).toBeInTheDocument()
    expect(screen.getByText("Voluntary self-identification")).toBeInTheDocument()

    // Work preferences: the one editor, shared with the intake page.
    await user.click(screen.getByRole("tab", { name: "Work preferences" }))
    expect(
      await screen.findByText(/What you want from a job/)
    ).toBeInTheDocument()
  })

  it("never invents a completeness percentage", async () => {
    /*
      The reference draws a "Profile Complete" badge. There is no completeness
      endpoint, so the console must not print a percentage it cannot source.
    */
    setCurrentProfileId("profile-1")
    stubCredentials()
    server.use(
      http.get(`${BASE}/api/resumes/:profileId`, () =>
        HttpResponse.json(profileResponse())
      )
    )
    renderScreen(<ProfileScreen />)

    await screen.findByRole("tablist")
    expect(screen.queryByText(/profile complete/i)).not.toBeInTheDocument()
    expect(screen.queryByText(/\d{1,3}%\s*complete/i)).not.toBeInTheDocument()
  })
})
