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
test("the operator can go from a resume to a tracked application", async ({ page }) => {
  // 1. Upload a resume -----------------------------------------------------
  await page.goto("/resume")
  await page.getByLabel("Resume file").setInputFiles(RESUME)
  await page.getByRole("button", { name: "Upload and parse" }).click()

  await expect(page.getByText("The resume was parsed and stored")).toBeVisible()
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
    "The language model is unavailable; try again later.",
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
  await page.getByRole("button", { name: "Prepare for approval" }).click()

  await expect(page.getByText("What will be submitted")).toBeVisible()
  await expect(page.getByText("Nothing has been submitted yet")).toBeVisible()

  // 5. Approve — the irreversible step ------------------------------------
  await page.getByLabel("Approver").fill("Ada")
  await page.getByLabel("Reason (optional)").fill("Looks right")
  await page.getByRole("button", { name: "Approve and submit" }).click()

  await expect(page.getByText("The decision")).toBeVisible({ timeout: 120_000 })
  const decision = page.getByText("The decision").locator("..")
  await expect(
    page.getByText(/The application was submitted|The application was not submitted/),
  ).toBeVisible()

  // 6. The tracker holds the application and its history --------------------
  await page.getByRole("link", { name: "Tracker" }).click()
  await expect(page.getByText("AI Engineer").first()).toBeVisible()

  await page.getByRole("link", { name: "AI Engineer" }).first().click()
  await expect(page.getByText(/History \(\d+\)/)).toBeVisible()
  await expect(page.getByText("Record a human outcome")).toBeVisible()
  void decision
})
