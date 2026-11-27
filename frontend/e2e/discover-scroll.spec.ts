import { expect, test, type Page } from "@playwright/test"

import {
  healthResponse,
  identityResponse,
  jobListing,
  jobSearchResponse,
  matchPair,
} from "../src/test/factories"

const filters = "workplace=remote&location=London&skills=Python&top_n=15"
const descriptionEnd = "End of the stored description."
const description = [
  ...Array.from(
    { length: 24 },
    (_, i) =>
      `Responsibility ${i + 1}: Build reliable data pipelines and work with the platform team to improve how we monitor, document and operate them.`
  ),
  descriptionEnd,
].join("\n\n")

async function openRanking(page: Page, jobId?: string) {
  const ranking = jobSearchResponse({
    results: Array.from({ length: 15 }, (_, i) =>
      matchPair({
        job: jobListing({
          id: `role-${i + 1}`,
          title: `Platform Engineer ${i + 1}`,
          application_url: null,
          description,
        }),
      })
    ),
    stats: {
      found: 0,
      dropped: 0,
      deduped: 15,
      persisted: 0,
      stored: 15,
      semantic_covered: 15,
    },
  })
  await page.addInitScript((response) => {
    localStorage.setItem("aja.currentProfileId", "profile-1")
    localStorage.setItem(
      "ajp.lastSearch.profile-1",
      JSON.stringify({
        query: "Python",
        location: "London",
        workplace: "remote",
        topN: 15,
        response,
      })
    )
  }, ranking)
  const unexpected: string[] = []
  await page.context().route("**/api/**", async (route) => {
    const request = route.request()
    const url = new URL(request.url())
    switch (`${request.method()} ${url.pathname}`) {
      case "GET /api/auth/me":
        return route.fulfill({ json: identityResponse() })
      case "GET /api/health":
        return route.fulfill({ json: healthResponse() })
      case "GET /api/jobs/suggest":
        return route.fulfill({
          json: {
            query: url.searchParams.get("q"),
            suggestions: [{ value: "Platform Engineer", count: 15 }],
          },
        })
      default:
        unexpected.push(`${request.method()} ${url.pathname}`)
        return route.abort()
    }
  })
  await page.goto(`/app/matches?${filters}${jobId ? `&job=${jobId}` : ""}`)
  await expect(page).toHaveURL(/\/app\/matches\?/)
  return () => expect(unexpected, "unexpected API requests").toEqual([])
}

function resultsRail(page: Page) {
  return page.getByRole("region", { name: "Ranked matches" })
}

function selectedJob(page: Page) {
  return page.getByRole("region", { name: "The selected job" })
}

function result(page: Page, rank: number) {
  return resultsRail(page).getByRole("button", {
    name: new RegExp(`Platform Engineer ${rank}\\b`),
  })
}

test.use({ serviceWorkers: "block" })

test("the selected job uses the document to reach the end of its description", async ({
  page,
}) => {
  await page.setViewportSize({ width: 1440, height: 900 })
  const checkRequests = await openRanking(page)
  const detail = selectedJob(page)
  await expect(
    detail.getByRole("heading", { name: "Platform Engineer 1" })
  ).toBeVisible()
  await expect(detail).toHaveCSS("overflow-y", "visible")
  await expect(
    detail.getByRole("heading", { name: "Job description" })
  ).toBeVisible()
  const fullText = detail.getByText(descriptionEnd)
  await expect(fullText).toContainText("Responsibility 24")
  await page.evaluate(() => window.scrollTo(0, document.body.scrollHeight))
  await expect
    .poll(() => page.evaluate(() => window.scrollY))
    .toBeGreaterThan(500)
  await expect
    .poll(() =>
      fullText.evaluate((text) => {
        const bottom = text.getBoundingClientRect().bottom
        return bottom > 68 && bottom <= window.innerHeight
      })
    )
    .toBe(true)
  checkRequests()
})

test("the desktop list stays pinned and scrolls without moving the description", async ({
  page,
}) => {
  await page.setViewportSize({ width: 1024, height: 768 })
  const checkRequests = await openRanking(page)
  const rail = resultsRail(page)
  const rows = page.getByTestId("results-scroll")
  const header = page.getByRole("banner")
  const title = selectedJob(page).getByRole("heading", {
    name: "Platform Engineer 1",
  })
  await expect(rail.getByRole("heading", { name: "15 matches" })).toBeVisible()
  await title.hover()
  await page.mouse.wheel(0, 640)
  await expect
    .poll(() => page.evaluate(() => window.scrollY))
    .toBeGreaterThan(450)
  const pageOffset = await page.evaluate(() => window.scrollY)
  const bar = (await header.boundingBox())!
  const pinned = (await rail.boundingBox())!
  expect(Math.abs(bar.y)).toBeLessThan(2)
  expect(pinned.y).toBeGreaterThanOrEqual(bar.y + bar.height)
  expect(pinned.y).toBeLessThan(bar.y + bar.height + 32)
  expect(pinned.y + pinned.height).toBeLessThanOrEqual(768)
  await expect(rows).toHaveCSS("scrollbar-width", "thin")
  await expect(rows).toHaveCSS("scrollbar-color", /rgba\(0, 0, 0, 0\)$/)

  const scrollport = (await rows.boundingBox())!
  await page.mouse.move(
    scrollport.x + scrollport.width / 2,
    scrollport.y + scrollport.height / 2
  )
  await page.mouse.wheel(0, 300)
  await expect
    .poll(() => rows.evaluate((node) => node.scrollTop))
    .toBeGreaterThan(100)
  expect(await page.evaluate(() => window.scrollY)).toBe(pageOffset)

  await result(page, 2).focus()
  await page.keyboard.press("End")
  const lastVisible = result(page, 10)
  await expect(lastVisible).toBeFocused()
  await expect(lastVisible).toHaveCSS("outline-style", "solid")
  const rowBox = (await lastVisible.boundingBox())!
  const rowsBox = (await rows.boundingBox())!
  expect(rowBox.y).toBeGreaterThanOrEqual(rowsBox.y - 1)
  expect(rowBox.y + rowBox.height).toBeLessThanOrEqual(
    rowsBox.y + rowsBox.height + 1
  )
  await expect(title).toBeAttached() // Arrow navigation has not selected a job.

  const listOffset = await rows.evaluate((node) => node.scrollTop)
  await page.keyboard.press("Enter")
  await expect(lastVisible).toHaveAttribute("aria-current", "true")
  await expect(lastVisible).toBeFocused()
  await expect(
    selectedJob(page).getByRole("heading", { name: "Platform Engineer 10" })
  ).toBeInViewport()
  expect(await rows.evaluate((node) => node.scrollTop)).toBe(listOffset)
  await expect(page).toHaveURL(new RegExp(`${filters}&job=role-10$`))
  checkRequests()
})

test("short desktop windows keep keyboard focus visible when opening a result", async ({
  page,
}) => {
  await page.setViewportSize({ width: 1024, height: 520 })
  const checkRequests = await openRanking(page)
  await expect(page.getByTestId("results-scroll")).toHaveCSS(
    "overflow-y",
    "visible"
  )
  await result(page, 1).focus()
  await page.keyboard.press("End")
  await expect(result(page, 10)).toBeFocused()
  await page.keyboard.press("Enter")

  const heading = selectedJob(page).getByRole("heading", {
    name: "Platform Engineer 10",
  })
  await expect(heading).toBeInViewport()
  await expect(heading).toBeFocused()
  checkRequests()
})

test("dark mode keeps a quiet thumb and forced colors restores the system scrollbar", async ({
  page,
}) => {
  await page.setViewportSize({ width: 1440, height: 900 })
  await page.addInitScript(() => localStorage.setItem("theme", "dark"))
  await page.emulateMedia({ reducedMotion: "reduce" })
  const checkRequests = await openRanking(page)
  await expect(page.locator("html")).toHaveClass(/\bdark\b/)
  const rows = page.getByTestId("results-scroll")
  await expect(rows).toHaveCSS("scrollbar-width", "thin")
  await expect(rows).toHaveCSS("scrollbar-color", /rgba\(0, 0, 0, 0\)$/)
  await page.emulateMedia({ forcedColors: "active" })
  await expect(rows).toHaveCSS("scrollbar-width", "auto")
  await expect(rows).toHaveCSS("scrollbar-color", "auto")
  checkRequests()
})

test.describe("touch selection", () => {
  test.use({
    hasTouch: true,
    isMobile: true,
    viewport: { width: 390, height: 844 },
    reducedMotion: "reduce",
  })

  test("results lead and Back restores the chosen row without clearing filters", async ({
    page,
  }) => {
    const checkRequests = await openRanking(page)
    const row = result(page, 6)
    await expect(row).toBeVisible()
    await expect(page).toHaveURL(new RegExp(`${filters}$`))
    await expect(selectedJob(page)).toBeHidden()

    await row.tap()
    const title = selectedJob(page).getByRole("heading", {
      name: "Platform Engineer 6",
    })
    await expect(title).toBeFocused()
    await expect(title).toBeInViewport()
    const back = page.getByRole("button", { name: "Back to results" })
    await expect(back).toBeInViewport()
    await expect(resultsRail(page)).toBeHidden()

    await back.tap()
    await expect(row).toBeFocused()
    await expect(row).toBeInViewport()
    await expect(page).toHaveURL(new RegExp(`${filters}$`))
    await expect(selectedJob(page)).toBeHidden()
    checkRequests()
  })

  test("an explicit job link opens directly and fits a 320px viewport", async ({
    page,
  }) => {
    await page.setViewportSize({ width: 320, height: 700 })
    const checkRequests = await openRanking(page, "role-2")
    const detail = selectedJob(page)
    await expect(
      detail.getByRole("heading", { name: "Platform Engineer 2" })
    ).toBeVisible()
    await expect(detail.getByText(descriptionEnd)).toBeAttached()
    await expect(resultsRail(page)).toBeHidden()
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth - window.innerWidth
      )
    ).toBeLessThanOrEqual(1)
    checkRequests()
  })
})
