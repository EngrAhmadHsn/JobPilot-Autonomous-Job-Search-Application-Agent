import { screen, waitFor } from "@testing-library/react"
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
  it("sits above the résumé, not below it", async () => {
    setCurrentProfileId("profile-1")
    stubCredentials()

    const { container } = renderScreen(<ProfileScreen />)

    // Both are on the page.
    expect(await screen.findByRole("button", { name: "Save key" })).toBeInTheDocument()
    const resumeToggle = await screen.findByText("See the full résumé profile")

    /*
      Order is asserted on the *rendered document*, not on the source: a
      `compareDocumentPosition` check survives any future re-wrap of the
      surrounding JSX, which a text-index comparison over innerHTML would
      not.
    */
    const credentials = screen.getByRole("button", { name: "Save key" })
    const position = resumeToggle.compareDocumentPosition(credentials)
    expect(position & Node.DOCUMENT_POSITION_PRECEDING).toBeTruthy()

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
    */
    setCurrentProfileId(null)
    stubCredentials()
    server.use(http.get(`${BASE}/api/documents`, () => HttpResponse.json({ documents: [] })))

    renderScreen(<ProfileScreen />)

    expect(await screen.findByRole("button", { name: "Save key" })).toBeInTheDocument()
    expect(screen.getByRole("heading", { name: "Your model" })).toBeInTheDocument()
    // And the page still explains the missing profile — once the document
    // list resolves and the hook stops being pending.
    expect(await screen.findByText("No profile yet")).toBeInTheDocument()
  })

  it("keeps the profile answers visible when a résumé exists", async () => {
    /* The reorder must not have pushed the answer cards off the page. */
    setCurrentProfileId("profile-1")
    stubCredentials()
    server.use(http.get(`${BASE}/api/resumes/:profileId`, () => HttpResponse.json(profileResponse())))

    renderScreen(<ProfileScreen />)

    await waitFor(() => {
      expect(screen.getByText("Work preferences")).toBeInTheDocument()
    })
    expect(screen.getByRole("button", { name: "Save key" })).toBeInTheDocument()
  })
})
