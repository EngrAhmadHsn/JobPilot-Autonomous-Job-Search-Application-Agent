import { expect, test } from "@playwright/test"
import { fileURLToPath } from "node:url"
import { dirname, join } from "node:path"

import { signIn } from "./session"

const HERE = dirname(fileURLToPath(import.meta.url))
const RESUME = join(HERE, "fixtures", "resume.txt")

/**
 * WS-21: the query suggestion panel is **not clipped** by the search card.
 *
 * The panel is absolutely positioned from under the query field; the shared
 * Card clips by default, which cut the panel off at the card's bottom edge.
 * jsdom cannot measure layout, so this is the real check: the panel's box
 * must extend below the card's box, and the keyboard must still work on the
 * rows it contains.
 *
 * Runs against the production build and the real backend (see
 * playwright.config.ts); the corpus supplies the suggestions. A profile is
 * uploaded first because the Matches search card only renders for a chosen
 * profile.
 */
test("the query suggestions extend past the search card", async ({ page }) => {
  await page.goto("/app/resume")
  await signIn(page)
  await page.goto("/app/resume")
  await signIn(page)
  await page.getByLabel("Résumé file").setInputFiles(RESUME)
  await page.getByRole("button", { name: /Upload and analyze résumé/ }).click()
  await expect(page.getByText("Your profile is ready").first()).toBeVisible({
    timeout: 60_000,
  })

  await page.goto("/app/matches")

  const input = page.getByLabel("Query")
  await input.click()
  await input.fill("eng")

  const panel = page.getByRole("listbox", {
    name: "Suggested roles from your listings",
  })
  await expect(panel).toBeVisible({ timeout: 30_000 })
  await expect(panel.getByRole("option").first()).toBeVisible()

  const card = page.locator('[data-slot="card"]').first()
  const panelBox = await panel.boundingBox()
  const cardBox = await card.boundingBox()
  expect(panelBox).not.toBeNull()
  expect(cardBox).not.toBeNull()
  // The panel's bottom edge lies below the card's: it is not clipped.
  expect(panelBox!.y + panelBox!.height).toBeGreaterThan(
    cardBox!.y + cardBox!.height
  )

  // Keyboard behaviour survives: ArrowDown highlights, Escape closes.
  await page.keyboard.press("ArrowDown")
  await expect(panel.getByRole("option").first()).toHaveAttribute(
    "aria-selected",
    "true"
  )
  await page.keyboard.press("Escape")
  await expect(panel).not.toBeVisible()
})
