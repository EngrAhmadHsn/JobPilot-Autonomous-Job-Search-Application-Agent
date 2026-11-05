import { screen } from "@testing-library/react"
import { describe, expect, it } from "vitest"

import { renderApp } from "@/test/render"

/**
 * The public landing page.
 *
 * The page is the front door, and two properties matter most: it renders
 * for a visitor with no session (it must not touch the API), and its claims
 * are the product's real ones — no live auto-submission to real boards.
 */
describe("the landing page", () => {
  it("renders for a visitor with no session", async () => {
    renderApp({ route: "/" })

    expect(
      await screen.findByRole("heading", {
        name: /your job search, on autopilot/i,
      })
    ).toBeInTheDocument()
  })

  it("leads to the console", async () => {
    renderApp({ route: "/" })

    const links = await screen.findAllByRole("link", {
      name: /open the console|create your account/i,
    })
    expect(links.length).toBeGreaterThan(0)
    expect(links[0]).toHaveAttribute("href", "/sign-in")
  })

  it("labells the demonstration as a demo with sample data", async () => {
    renderApp({ route: "/" })

    expect(
      await screen.findByText(/this never contacts a real job board/i)
    ).toBeInTheDocument()
  })

  it("does not promise live automated submissions to real job boards", async () => {
    renderApp({ route: "/" })

    await screen.findByRole("heading", { name: /your job search/i })
    // The honest framing: approval-gated, controlled targets.
    expect(
      screen.getAllByText(/approval (required|before)/i).length
    ).toBeGreaterThan(0)
  })

  it("shows its content even where the scroll reveal cannot run", async () => {
    // jsdom has no IntersectionObserver, and the reveal is designed so the
    // content is present and visible without it — never hidden until
    // JavaScript runs.
    renderApp({ route: "/" })

    // Content that lives in a reveal-marked block: a capability card and a
    // trust card, both unique to their sections.
    expect(
      await screen.findByText(/matching that explains itself/i)
    ).toBeInTheDocument()
    expect(
      await screen.findByText(/tenant isolation by construction/i)
    ).toBeInTheDocument()
  })
})
