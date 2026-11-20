import { screen, waitFor } from "@testing-library/react"
import { http, HttpResponse } from "msw"
import { describe, expect, it } from "vitest"

import { server } from "@/test/server"
import { renderApp } from "@/test/render"

const BASE = "http://api.test"

/**
 * The document-level accessibility plumbing.
 *
 * These three properties used to be absent on every route, and each was a
 * finding in `docs/evaluations/interface-review-2026-11-12.md`. They are cheap
 * to lose again in a refactor, so each one is pinned here:
 *
 * - every screen names its browser tab (WCAG 2.4.2 Page Titled);
 * - a keyboard user can skip the chrome (2.4.1 Bypass Blocks);
 * - the public page exposes a `<main>` landmark (1.3.1).
 */
describe("document-level accessibility", () => {
  it("names the tab on the landing page", async () => {
    renderApp({ route: "/" })

    await waitFor(() => {
      expect(document.title).toContain("JobPilot")
    })
    expect(document.title).toMatch(/job search/i)
  })

  it("names the tab per console screen, not once for the app", async () => {
    server.use(
      http.get(`${BASE}/api/auth/me`, () =>
        HttpResponse.json({
          id: "user-1",
          email: "operator@example.com",
          is_superuser: true,
          created_at: "2026-01-01T00:00:00Z",
        })
      )
    )
    renderApp({ route: "/app" })

    // The screen is lazily loaded, so the title lands with it. The visible
    // h1 is the design's statement (node 47:36); the tab keeps the stable
    // screen name through `PageHeader`'s `documentTitle`.
    await screen.findByRole("heading", { name: "Your next career move." })
    await waitFor(() => {
      expect(document.title).toBe("Overview · JobPilot")
    })
  })

  it("offers a skip link, first in the tab order", async () => {
    renderApp({ route: "/" })

    const skip = await screen.findByRole("link", { name: /skip to content/i })
    expect(skip).toHaveAttribute("href", "#main-content")

    // It must be the first focusable element, or it cannot skip anything.
    const focusable = [
      ...document.querySelectorAll(
        'a[href], button, input, select, textarea, [tabindex]:not([tabindex="-1"])'
      ),
    ].filter((el) => (el as HTMLElement).offsetParent !== null || true)
    expect(focusable[0]).toBe(skip)
  })

  it("gives the landing page a main landmark the skip link targets", async () => {
    renderApp({ route: "/" })

    await screen.findByRole("heading", { level: 1 })
    const main = document.querySelector("main#main-content")
    expect(main).not.toBeNull()
    // The header must sit outside it, or the landmark includes the chrome the
    // skip link exists to bypass.
    expect(main?.querySelector("header")).toBeNull()
    expect(document.querySelector("header")).not.toBeNull()
  })
})
