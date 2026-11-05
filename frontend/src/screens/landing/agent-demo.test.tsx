import { screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { describe, expect, it } from "vitest"

import { renderScreen } from "@/test/render"

import { AgentDemo } from "./agent-demo"

/**
 * The interactive demonstration.
 *
 * It must be a working interface — a visitor drives it — and it must be
 * unmistakably a demo. Both are asserted here.
 */
describe("the agent demonstration", () => {
  it("starts on the first stage and shows what the agent does there", async () => {
    renderScreen(<AgentDemo />)

    expect(
      await screen.findByRole("tab", { name: /resume analysis/i })
    ).toHaveAttribute("aria-selected", "true")
    expect(await screen.findByText(/parsing the uploaded document/i)).toBeInTheDocument()
  })

  it("switches stages when a visitor clicks one", async () => {
    const user = userEvent.setup()
    renderScreen(<AgentDemo />)

    await user.click(screen.getByRole("tab", { name: /job discovery/i }))

    expect(
      screen.getByRole("tab", { name: /job discovery/i })
    ).toHaveAttribute("aria-selected", "true")
    expect(
      await screen.findByText(/searching greenhouse listings/i)
    ).toBeInTheDocument()
  })

  it("is driven by the keyboard", async () => {
    const user = userEvent.setup()
    renderScreen(<AgentDemo />)

    const first = screen.getByRole("tab", { name: /resume analysis/i })
    first.focus()
    await user.keyboard("{ArrowRight}")

    expect(
      screen.getByRole("tab", { name: /job discovery/i })
    ).toHaveAttribute("aria-selected", "true")
  })

  it("says, on the interface itself, that it is a demo", async () => {
    renderScreen(<AgentDemo />)

    expect(
      await screen.findByText(/this never contacts a real job board/i)
    ).toBeInTheDocument()
  })
})
