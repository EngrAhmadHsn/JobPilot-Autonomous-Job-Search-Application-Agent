import { screen, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { http, HttpResponse } from "msw"
import { describe, expect, it } from "vitest"

import { AccountScreen } from "@/screens/account-screen"
import { renderScreen } from "@/test/render"
import { server } from "@/test/server"

const BASE = "http://api.test"

/**
 * WS-46 · The Account & Security screen.
 *
 * What these tests pin, and why:
 *
 * - the design draws four tabs, but the backend has **no sessions surface**
 *   the console can render honestly, so the screen ships three — Profile ·
 *   Model credentials · Privacy — and the word "sessions" appears nowhere;
 * - the identity card is **editable** because `PATCH /api/auth/me` exists
 *   (verified in `src/auth/routes.py` at implementation time): the test
 *   captures the PATCH body, so a fake Save button could not slip through;
 * - the password change states its real side effect — the backend signs the
 *   caller's **other** sessions out — and refuses to submit a mismatched
 *   pair;
 * - the privacy panel links to the profile's answers tab, where the
 *   voluntary EEO answers actually live, rather than duplicating them;
 * - the Model credentials tab hosts the same key card, same endpoints, same
 *   behavior it had on Profile.
 */

function stubIdentityPatch() {
  const patches: unknown[] = []
  server.use(
    http.patch(`${BASE}/api/auth/me`, async ({ request }) => {
      const body = await request.json()
      patches.push(body)
      return HttpResponse.json({
        ...{
          id: "user-1",
          email: "operator@example.com",
          full_name: "Operator",
          is_active: true,
          is_superuser: false,
          is_verified: true,
        },
        ...(body as object),
      })
    })
  )
  return patches
}

/** The credentials read, so the key card's state chip can resolve. */
function stubCredentials(payload: Record<string, unknown> = {}) {
  server.use(
    http.get(`${BASE}/api/llm/credentials`, () =>
      HttpResponse.json({
        mode: "optional",
        available: true,
        encryption: "local_file",
        platform_configured: true,
        using: "platform",
        credential: null,
        ...payload,
      })
    )
  )
}

describe("the account and security screen", () => {
  it("offers the three tabs the backend supports, and no Sessions tab", async () => {
    renderScreen(<AccountScreen />, { route: "/app/account" })

    const tabs = await screen.findByRole("tablist", {
      name: "Account sections",
    })
    for (const name of ["Profile", "Model credentials", "Privacy"]) {
      expect(within(tabs).getByRole("tab", { name })).toBeInTheDocument()
    }
    expect(within(tabs).queryByRole("tab", { name: /sessions/i })).toBeNull()

    // The header describes what the screen really holds — it does not
    // advertise a sessions list that does not exist.
    expect(screen.queryByText(/sessions/i)).toBeNull()
  })

  it("fills the identity card from /api/auth/me", async () => {
    renderScreen(<AccountScreen />, { route: "/app/account" })

    expect(await screen.findByText("Your account")).toBeInTheDocument()
    expect((screen.getByLabelText("Name") as HTMLInputElement).value).toBe(
      "Operator"
    )
    expect((screen.getByLabelText("Email") as HTMLInputElement).value).toBe(
      "operator@example.com"
    )

    // Nothing to save when nothing moved: the button is honest about it.
    expect(screen.getByRole("button", { name: "Save changes" })).toBeDisabled()
  })

  it("saves name and email through PATCH /api/auth/me", async () => {
    const patches = stubIdentityPatch()
    const user = userEvent.setup()

    renderScreen(<AccountScreen />, { route: "/app/account" })

    const name = await screen.findByLabelText("Name")
    await user.clear(name)
    await user.type(name, "Ada Lovelace")
    await user.click(screen.getByRole("button", { name: "Save changes" }))

    await screen.findByText("Saved.")
    expect(patches).toEqual([
      { full_name: "Ada Lovelace", email: "operator@example.com" },
    ])
  })

  it("reveals the password form, refuses a mismatched pair, and PATCHes the password", async () => {
    const patches = stubIdentityPatch()
    const user = userEvent.setup()

    renderScreen(<AccountScreen />, { route: "/app/account" })

    await screen.findByText("Your account")
    await user.click(screen.getByRole("button", { name: "Change password" }))

    // The real side effect, stated before it happens: the backend ends the
    // caller's other sessions on a password change.
    expect(
      screen.getByText(/signs your other sessions out/)
    ).toBeInTheDocument()

    const newPassword = screen.getByLabelText("New password")
    await user.type(newPassword, "s3cure-passphrase")
    await user.type(screen.getByLabelText("Confirm new password"), "different")

    const change = screen.getByRole("button", { name: "Change password" })
    expect(
      screen.getByText("The passwords do not match yet.")
    ).toBeInTheDocument()
    expect(change).toBeDisabled()

    await user.clear(screen.getByLabelText("Confirm new password"))
    await user.type(
      screen.getByLabelText("Confirm new password"),
      "s3cure-passphrase"
    )
    expect(change).toBeEnabled()
    await user.click(change)

    await screen.findByText("Password changed.")
    expect(
      screen.getByText("Your other sessions were signed out.")
    ).toBeInTheDocument()
    expect(patches).toEqual([{ password: "s3cure-passphrase" }])
  })

  it("hosts the model key card on its tab", async () => {
    stubCredentials()
    const user = userEvent.setup()
    renderScreen(<AccountScreen />, { route: "/app/account" })

    await user.click(
      await screen.findByRole("tab", { name: "Model credentials" })
    )
    // The card's title (a `CardTitle`, which is a styled div, not a heading
    // element — the chip and the description sit beside it).
    expect(await screen.findByText("Your model key")).toBeInTheDocument()
    expect(screen.getByTestId("model-key-state")).toHaveTextContent(
      "No key configured"
    )
    expect(screen.getByRole("button", { name: "Save key" })).toBeInTheDocument()
  })

  it("links the privacy panel to the profile's answers tab", async () => {
    const user = userEvent.setup()
    renderScreen(<AccountScreen />, { route: "/app/account" })

    await user.click(await screen.findByRole("tab", { name: "Privacy" }))

    expect(await screen.findByText("Privacy & deletion")).toBeInTheDocument()
    expect(
      screen.getByText(/stored separately from your application profile/)
    ).toBeInTheDocument()
    const link = screen.getByRole("link", { name: "Review EEO answers →" })
    expect(link).toHaveAttribute("href", "/app/profile?tab=answers")
  })
})
