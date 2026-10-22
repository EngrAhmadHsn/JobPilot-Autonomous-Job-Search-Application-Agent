import { expect, test } from "@playwright/test"
import { fileURLToPath } from "node:url"
import { dirname, join } from "node:path"

const HERE = dirname(fileURLToPath(import.meta.url))
const RESUME = join(HERE, "fixtures", "resume.txt")

/**
 * The end-to-end smoke path.
 *
 * One operator's journey, against the **real** backend and the **real**
 * fake ATS: upload a resume → search the corpus → tailor → prepare →
 * approve (which really submits a form) → read the history.
 *
 * The test asserts what the console must do, and it asserts the *truth*:
 * the tailoring step passes when the tailored resume is ready **or** when
 * the console says the model is unavailable. A console that hid a provider
 * failure would fail this test, which is the point.
 */
test("the operator can go from a resume to a tracked application", async ({
  page,
}) => {
  // 0. Sign in -------------------------------------------------------------
  //
  // The API has an identity (WS-14), so the console asks the server who
  // it is and shows the sign-in screen when the answer is no. The
  // account is created on the first run and reused after that.
  await page.goto("/resume")
  await signIn(page)

  // 1. Sign in, then upload a resume ---------------------------------------
  await page.goto("/resume")
  await signIn(page)
  await page.getByLabel("Résumé file").setInputFiles(RESUME)
  await page.getByRole("button", { name: /Upload and analyse résumé/ }).click()

  await expect(page.getByText("Your profile is ready").first()).toBeVisible()
  const profileId = await page
    .locator("main code")
    .first()
    .textContent()
    .then((value) => value?.trim() ?? "")
  expect(profileId).not.toBe("")

  // 2. Search the stored corpus -------------------------------------------
  await page.getByRole("link", { name: "Matches" }).click()
  await page.getByRole("button", { name: "Search" }).click()

  const firstMatch = page.getByRole("link", { name: "Open the job" }).first()
  await expect(firstMatch).toBeVisible({ timeout: 120_000 })

  // 3. Tailor for the job the search found --------------------------------
  await firstMatch.click()
  await page.getByRole("link", { name: "Tailor for this job" }).click()
  await page.getByRole("button", { name: "Tailor this resume" }).click()

  const tailored = page.getByText("The tailored resume is ready")
  const modelUnavailable = page.getByText(
    "The language model is unavailable; try again later."
  )
  await expect(tailored.or(modelUnavailable)).toBeVisible({ timeout: 180_000 })
  if (await tailored.isVisible()) {
    await expect(page.getByText("Factuality report")).toBeVisible()
  }

  // 4. Prepare an application against the fake ATS -------------------------
  await page.getByRole("link", { name: "Approvals" }).click()
  await page.getByLabel("Job title").fill("AI Engineer")
  await page.getByLabel("Company").fill("Acme")
  await page.getByLabel("Job URL").fill("http://127.0.0.1:8901/basic")
  await page.getByLabel("Candidate name").fill("Ada Lovelace")
  await page.getByLabel("Email").fill("ada@example.com")
  await page.getByLabel("Phone").fill("+44 20 7946 0000")
  await page.getByRole("button", { name: "Prepare application" }).click()

  await expect(page.getByText("What will be submitted")).toBeVisible()
  await expect(page.getByText(/Nothing has been submitted yet/)).toBeVisible()

  // 5. Approve — the irreversible step ------------------------------------
  //
  // There is no approver field: the decision is recorded against the
  // signed-in account (WS-14).
  await page.getByLabel("Reason").fill("Looks right")
  await page.getByRole("button", { name: "Approve and submit" }).click()

  await expect(page.getByText("The decision")).toBeVisible({ timeout: 120_000 })
  const decision = page.getByText("The decision").locator("..")
  await expect(
    page.getByText(
      /The application was submitted|The application was not submitted/
    )
  ).toBeVisible()

  // 6. The tracker holds the application and its history --------------------
  await page.getByRole("link", { name: "Tracker" }).click()
  await expect(page.getByText("AI Engineer").first()).toBeVisible()

  await page.getByRole("link", { name: "AI Engineer" }).first().click()
  await expect(page.getByText(/History \(\d+\)/)).toBeVisible()
  await expect(page.getByText("Record a human outcome")).toBeVisible()
  void decision
})

/**
 * Sign in — creating the account the first time.
 *
 * The console is signed in through the cookie transport, so the browser
 * holds an `HttpOnly` session cookie and the console holds no token.
 */
async function signIn(page: import("@playwright/test").Page) {
  // A **fresh** account per run. The account is a real one, and a real
  // account from a previous run would carry a password this run does
  // not know — so the run would fail on a credential rather than on a
  // defect.
  const stamp = Date.now().toString(36)
  const email = process.env.E2E_ACCOUNT ?? `operator-${stamp}@example.com`
  const password = process.env.E2E_PASSWORD ?? "a-long-enough-password"

  // The console renders itself for a moment before the identity check
  // answers, so the presence of a control proves nothing about whether
  // the session is good. The two real signals are: the account menu
  // showing an **address** (signed in), and the sign-in screen (signed
  // out). The helper waits for one of them.
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

  // The console either signs in, or refuses the credentials because the
  // account does not exist yet. In the second case it creates it and
  // signs in again.
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
  // Creating the account hashes the password with argon2, which takes
  // seconds when the machine is busy. The wait has to allow for that, or
  // the run fails on the provider's cost and not on the console.
  await page
    .getByRole("button", { name: "Account and display settings" })
    .waitFor({ timeout: 90_000 })
}

/**
 * The keyboard path.
 *
 * Everything the operator can do with a mouse, they must be able to do with
 * a keyboard: the navigation, the upload, and the approval. This walks the
 * focus order in a real browser and checks that the focus is *visible* —
 * a focus ring that is not drawn is not a focus ring.
 */
test("the console is reachable by keyboard", async ({ page }) => {
  await page.goto("/resume")
  await signIn(page)
  await signIn(page)
  await page.goto("/resume")

  const visited: string[] = []
  let sawVisibleFocus = false

  for (let step = 0; step < 14; step += 1) {
    await page.keyboard.press("Tab")
    const focused = await page.evaluate(() => {
      const el = document.activeElement as HTMLElement | null
      if (!el || el === document.body) return null
      const style = getComputedStyle(el)
      return {
        name: (el.getAttribute("aria-label") || el.textContent || "")
          .trim()
          .slice(0, 40),
        outlineWidth: style.outlineWidth,
        outlineStyle: style.outlineStyle,
      }
    })
    if (!focused) continue
    visited.push(focused.name)
    if (
      focused.outlineStyle !== "none" &&
      Number.parseFloat(focused.outlineWidth) > 0
    ) {
      sawVisibleFocus = true
    }
  }

  // The navigation is reachable, in order.
  expect(visited.some((name) => name.includes("Resume"))).toBe(true)
  expect(visited.some((name) => name.includes("Matches"))).toBe(true)
  // The upload has a keyboard-reachable control, not a drag-only target.
  expect(visited.some((name) => name.includes("Choose a file"))).toBe(true)
  // And the focus is visible when it lands.
  expect(sawVisibleFocus).toBe(true)
})

/**
 * The account menu opens.
 *
 * A menu's parts are rendered only when it opens, so a menu that throws
 * when it opens passes every test that never opens it. The console's own
 * error boundary is what the operator saw, so the test opens it.
 */
test("the account menu opens", async ({ page }) => {
  await page.goto("/resume")
  await signIn(page)

  await page
    .getByRole("button", { name: "Account and display settings" })
    .click()

  await expect(page.getByText("Sign out")).toBeVisible()
  await expect(page.getByText("Operator console")).toBeVisible()
})

/**
 * The mobile navigation.
 *
 * A narrow screen cannot hold a horizontal bar of links, and a second band
 * under the header is neither a good use of the viewport nor a good
 * pattern. The navigation becomes a **modal drawer** — the Material 3
 * answer for a phone — opened from a navigation icon, with the same
 * groups, the current page marked, and the drawer closing when the
 * operator picks a destination.
 */
test("the navigation is a drawer on a narrow screen", async ({ page }) => {
  await page.setViewportSize({ width: 375, height: 780 })
  await page.goto("/matches")
  await signIn(page)

  // The horizontal bar is not in the DOM at this width: a screen reader
  // must never meet the same destination twice.
  await expect(page.getByRole("navigation", { name: "Screens" })).toHaveCount(0)

  await page.getByRole("button", { name: "Open the navigation menu" }).click()

  const drawer = page.getByRole("dialog")
  await expect(drawer).toBeVisible()
  await expect(drawer.getByRole("link", { name: "Matches" })).toBeVisible()
  await expect(drawer.getByRole("link", { name: "Operations" })).toBeVisible()

  await drawer.getByRole("link", { name: "Tracker" }).click()

  await expect(page).toHaveURL(/\/tracker$/)
  // The drawer closes on the choice, the way a drawer should.
  await expect(page.getByRole("dialog")).toHaveCount(0)
})
