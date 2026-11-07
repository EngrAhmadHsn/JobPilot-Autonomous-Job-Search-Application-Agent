import { expect, test } from "@playwright/test"
import { fileURLToPath } from "node:url"
import { dirname, join } from "node:path"

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

/**
 * The sign-in flow, mirroring smoke.spec.ts: a fresh account per run — a
 * real account from a previous run would carry a password this run does not
 * know, so the run would fail on a credential rather than on a defect.
 */
async function signIn(page: import("@playwright/test").Page) {
  const stamp = Date.now().toString(36)
  const email = `suggestions-${stamp}@example.com`
  const password = "a-long-enough-password"

  const accountText = await page.evaluate(() => {
    const element = document.querySelector(
      'button[aria-label="Account and display settings"]'
    )
    return element?.textContent ?? ""
  })
  if (accountText.includes("@")) return

  const needsCredentials = await page
    .getByRole("heading", { name: "Sign in" })
    .waitFor({ timeout: 20_000 })
    .then(() => true)
    .catch(() => false)
  if (!needsCredentials) return

  await page.getByLabel("Email").waitFor({ state: "visible", timeout: 15_000 })
  await page.getByLabel("Email").fill(email)
  await page.getByLabel("Password").fill(password)
  await page.getByRole("button", { name: "Sign in" }).click()

  const signedIn = await page
    .getByRole("button", { name: "Account and display settings" })
    .waitFor({ timeout: 30_000 })
    .then(() => true)
    .catch(() => false)
  if (signedIn) return

  await page.getByRole("button", { name: /No account yet/ }).click()
  await page.getByLabel("Email").fill(email)
  await page.getByLabel("Password").fill(password)
  await page.getByRole("button", { name: "Create the account" }).click()
  await page
    .getByRole("button", { name: "Account and display settings" })
    .waitFor({ timeout: 60_000 })
}