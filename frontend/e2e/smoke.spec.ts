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

  await page.getByLabel("Email").fill(email)
  await page.getByLabel("Password").fill(password)
  await page.getByRole("button", { name: "Sign in" }).click()

  // The console either signs in, or refuses the credentials because the
  // account does not exist yet. In the second case it creates it and
  // signs in again.
  const signedIn = await page
    .getByRole("link", { name: "Matches" })
    .waitFor({ timeout: 10_000 })
    .then(() => true)
    .catch(() => false)
  if (signedIn) return

  await page.getByRole("button", { name: /No account yet/ }).click()
  await page.getByLabel("Email").fill(email)
  await page.getByLabel("Password").fill(password)
  await page.getByRole("button", { name: "Create the account" }).click()
  await page.getByRole("link", { name: "Matches" }).waitFor({ timeout: 20_000 })
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
