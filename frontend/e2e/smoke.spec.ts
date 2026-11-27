import { expect, test } from "@playwright/test"
import { fileURLToPath } from "node:url"
import { dirname, join } from "node:path"

import { accountTrigger, signIn } from "./session"

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
 * the console reports that the model is unavailable. That branch checks
 * honest outage handling, not successful tailoring; the isolated Studio
 * browser spec covers the successful journey independently.
 *
 * WS-22: the "or unavailable" branch needs the time the API itself is
 * allowed to spend. A provider that stalls (rather than refusing) costs the
 * client its full timeout per attempt — three attempts of ``LLM_TIMEOUT``
 * plus backoff, ~190 s by default — so a 180 s wait failed a run whose
 * provider was merely slow, one step before the API answered. The wait is
 * now larger than that budget, and the test's own timeout leaves room for
 * the rest of the journey.
 */
test("the operator can go from a resume to a tracked application", async ({
  page,
}) => {
  // 0. Sign in -------------------------------------------------------------
  //
  // The API has an identity (WS-14), so the console asks the server who
  // it is and shows the sign-in screen when the answer is no. The
  // account is created on the first run and reused after that.
  await page.goto("/app/resume")
  await signIn(page)

  // 1. Sign in, then upload a resume ---------------------------------------
  await page.goto("/app/resume")
  await signIn(page)
  await page.getByLabel("Résumé file").setInputFiles(RESUME)
  await page.getByRole("button", { name: /Upload and analyze résumé/ }).click()

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

  /*
    WS-41: Discover became the reference's **split view** (WS-36). A result is
    no longer a link called "Open the job" that navigates away; it is a row
    **button** in the `Ranked matches` list, and choosing it opens the job's
    detail beside the list. The journey is the same — find a job, then tailor —
    so the spec follows the control the console actually renders. The
    assertion stays strict: the row must exist, and the detail pane must then
    offer the handoff into tailoring.
  */
  const firstMatch = page
    .getByRole("list", { name: "Ranked matches" })
    .getByRole("button")
    .first()
  await expect(firstMatch).toBeVisible({ timeout: 120_000 })

  // 3. Tailor for the job the search found --------------------------------
  await firstMatch.click()
  await page.getByRole("link", { name: "Tailor for this role →" }).click()
  await page.getByRole("button", { name: "Tailor this resume" }).click()

  const preview = page.getByRole("tab", { name: /^Preview / })
  const modelUnavailable = page.getByText(
    /^The language model(?: is unavailable| is rate-limiting requests| timed out while generating| did not return a usable tailored draft|'s daily quota)/
  )
  // A provider refusal is an observable outcome of the live smoke, not
  // evidence that it generated a draft. The Studio spec requires success.
  await expect(preview.or(modelUnavailable)).toBeVisible({ timeout: 260_000 })
  if (await preview.isVisible()) {
    await preview.click()
    await expect(
      page
        .getByRole("tabpanel", { name: /^Preview / })
        .getByText("The tailored resume is ready")
    ).toBeVisible()

    await page.getByRole("tab", { name: "Validation" }).click()
    await expect(
      page
        .getByRole("tabpanel", { name: "Validation" })
        .getByText("Factuality report", { exact: true })
    ).toBeVisible()
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
  //
  // WS-38 made the decision two steps, and renamed the control to match what
  // the route actually does: the page button says "Approve & continue" (not
  // "Approve and submit" — the route answers 202, it does not submit), and it
  // opens a confirmation that states the queued consequence before anything is
  // recorded. The spec walks both steps, so a regression that removed the
  // confirmation would fail here.
  await page.getByLabel("Reason").fill("Looks right")
  await page.getByRole("button", { name: "Approve & continue" }).click()

  const confirmDialog = page.getByRole("alertdialog")
  await expect(confirmDialog).toBeVisible()
  // The confirmation states the queued consequence before anything is recorded.
  await expect(
    confirmDialog.getByText(/nothing is submitted by/i)
  ).toBeVisible()
  await confirmDialog
    .getByRole("button", { name: "Approve & continue" })
    .click()

  // WS-32: the approve **accepts** the submission as durable work — the route
  // answers 202 with a run id and the run's own status. The console must say
  // accepted and queued (never "was not submitted", which reads as a refusal),
  // and never "submitted", which would claim the employer was reached.
  await expect(page.getByRole("heading", { name: "The decision" })).toBeVisible(
    { timeout: 120_000 }
  )
  await expect(page.getByText("Approved — queued")).toBeVisible()
  // The run id and the "nothing has been submitted" truth travel together in
  // the queued banner. They are matched as one sentence because the phrase
  // itself legitimately appears three times on this page (the payload panel,
  // the banner and the evidence panel) — scoping keeps the assertion about
  // *this* statement rather than about the page containing the words.
  await expect(
    page.getByText(
      /Run .+ is waiting for a worker\. Nothing has been submitted yet/i
    )
  ).toBeVisible()

  // 6. The tracker holds the application and its history --------------------
  await page.getByRole("link", { name: "Tracker" }).click()
  await expect(page.getByText("AI Engineer").first()).toBeVisible()

  await page.getByRole("link", { name: "AI Engineer" }).first().click()
  // WS-39 renamed the detail's chronology from "History (n)" to "Timeline (n)"
  // — the third view of the tracker (board/list/timeline) took the word — and
  // the outcome editor is the same control underneath.
  await expect(page.getByText(/Timeline \(\d+\)/)).toBeVisible()
  await expect(
    page.getByText(/Record a human outcome|The outcome is final/)
  ).toBeVisible()
})

/**
 * Sign in — creating the account the first time.
 *
 * The console is signed in through the cookie transport, so the browser
 * holds an `HttpOnly` session cookie and the console holds no token.
 */
/**
 * The keyboard path.
 *
 * Everything the operator can do with a mouse, they must be able to do with
 * a keyboard: the navigation, the upload, and the approval. This walks the
 * focus order in a real browser and checks that the focus is *visible* —
 * a focus ring that is not drawn is not a focus ring.
 */
test("the console is reachable by keyboard", async ({ page }) => {
  await page.goto("/app/resume")
  await signIn(page)
  await signIn(page)
  await page.goto("/app/resume")

  const visited: string[] = []
  let sawVisibleFocus = false

  /*
    WS-34/WS-41: the shell now carries the reference's **grouped** navigation —
    six journey destinations with their indented pages, plus the System group,
    plus the skip link, the mobile top bar and the account footer. That is more
    stops than the old flat header, so a 14-tab walk was exhausted inside the
    sidebar and never reached the screen at all. The budget is raised to cover
    the chrome, and the walk stops as soon as it has visited the upload
    control rather than depending on an exact count.
  */
  for (let step = 0; step < 60; step += 1) {
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
    if (focused.name.includes("Choose a file")) break
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
  await page.goto("/app/resume")
  await signIn(page)

  await accountTrigger(page).click()

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
  await page.goto("/app/matches")
  await signIn(page)

  // The horizontal bar is not in the DOM at this width: a screen reader
  // must never meet the same destination twice.
  await expect(page.getByRole("navigation", { name: "Screens" })).toHaveCount(0)

  // Below `lg` the drawer opens from the bottom bar's own slot.
  await page.getByRole("button", { name: "More" }).click()

  const drawer = page.getByRole("dialog")
  await expect(drawer).toBeVisible()
  await expect(drawer.getByRole("link", { name: "Discover" })).toBeVisible()
  await expect(drawer.getByRole("link", { name: "Operations" })).toBeVisible()

  await drawer.getByRole("link", { name: "Applications" }).click()

  await expect(page).toHaveURL(/\/app\/tracker$/)
  // The drawer closes on the choice, the way a drawer should.
  await expect(page.getByRole("dialog")).toHaveCount(0)
})
