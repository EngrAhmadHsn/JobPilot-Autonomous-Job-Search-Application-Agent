import { screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { describe, expect, it } from "vitest"

import { AccountMenu } from "@/components/layout/account-menu"
import { renderScreen } from "@/test/render"

/**
 * The account menu opens.
 *
 * The menu's parts are rendered only when it opens, so a menu that throws
 * on open passes every test that never opens it. This one opens it.
 */
describe("the account menu", () => {
  it("opens and shows the account, the theme and the sign-out", async () => {
    const user = userEvent.setup()
    renderScreen(<AccountMenu />)

    await user.click(
      screen.getByRole("button", { name: "Account and display settings" })
    )

    expect(await screen.findByText("Operator console")).toBeInTheDocument()
    expect(screen.getByText("Sign out")).toBeInTheDocument()
    expect(screen.getByText("Ivory")).toBeInTheDocument()
    expect(screen.getByText("Charcoal")).toBeInTheDocument()
  })
})
