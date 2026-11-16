import { render, screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { describe, expect, it } from "vitest"

import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"

/**
 * WS-34: the tabs' active treatment is an underline over the list's
 * hairline, not a pill (the reference's "Overview / Match Details" rows).
 *
 * Fix round 2: the first revision carried the paint class
 * `after:bg-primary` unconditionally, so every trigger — active or not —
 * rendered the underline and the `data-active` variant was dead code.
 * These tests pin the class contract: no bare paint class on any trigger,
 * the transparent default everywhere, the paint riding `data-active` only
 * (Base UI sets that attribute on exactly the selected tab).
 */
function renderTwoTabs() {
  return render(
    <Tabs defaultValue="one">
      <TabsList>
        <TabsTrigger value="one">Overview</TabsTrigger>
        <TabsTrigger value="two">Match details</TabsTrigger>
      </TabsList>
      <TabsContent value="one">Overview panel</TabsContent>
      <TabsContent value="two">Match details panel</TabsContent>
    </Tabs>
  )
}

describe("the tabs trigger", () => {
  it("carries the underline classes only on the active tab", () => {
    renderTwoTabs()

    const active = screen.getByRole("tab", { name: "Overview" })
    const inactive = screen.getByRole("tab", { name: "Match details" })

    // Base UI marks exactly the selected trigger; the underline applies
    // through the data-active variant, never unconditionally.
    expect(active).toHaveAttribute("data-active")
    expect(inactive).not.toHaveAttribute("data-active")
    expect(active).toHaveClass("data-active:after:bg-primary")

    // The bare paint class must not sit on any trigger — on the inactive
    // trigger it was the defect (an underline on every tab).
    expect(active).not.toHaveClass("after:bg-primary")
    expect(inactive).not.toHaveClass("after:bg-primary")

    // The transparent default is on both, so the ::after element stays
    // colourless until data-active turns it into the underline.
    expect(active).toHaveClass("after:bg-transparent")
    expect(inactive).toHaveClass("after:bg-transparent")
  })

  it("moves the underline when the selection changes", async () => {
    const user = userEvent.setup()
    renderTwoTabs()

    const first = screen.getByRole("tab", { name: "Overview" })
    const second = screen.getByRole("tab", { name: "Match details" })
    expect(first).toHaveAttribute("data-active")

    await user.click(second)

    expect(second).toHaveAttribute("data-active")
    expect(first).not.toHaveAttribute("data-active")
    expect(second).toHaveClass("data-active:after:bg-primary")
    expect(first).not.toHaveClass("after:bg-primary")
    expect(second).not.toHaveClass("after:bg-primary")
  })
})
