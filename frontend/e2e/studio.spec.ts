import { expect, type Locator, type Page } from "@playwright/test"
import { mkdir, writeFile } from "node:fs/promises"
import { join } from "node:path"
import { fileURLToPath } from "node:url"

import {
  alternateFilename,
  alternateSummary,
  alternateTitle,
  downloadPath,
  draftApiPath,
  draftFilename,
  draftRoute,
  job,
  jobRoute,
  originalBullet,
  originalSummary,
  otherDraftFilename,
  proposedBullet,
  proposedLetter,
  proposedSummary,
  savedLetter,
  savedSummary,
  test,
} from "./fixtures/studio"

// The browser drives the real console UI. Responses and the downloaded file
// are synthetic; this is not a test of the model, database, or render pipeline.
test.use({
  serviceWorkers: "block",
  reducedMotion: "reduce",
  colorScheme: "light",
})
test.setTimeout(45_000)

const studioHeading = "Your experience. Better told."
const evidenceHeading = "Make every claim count."
const proposedStatus = "Diff review · proposed"
const editedStatus = "Diff review · edited by you"
const downloadLabel = /^Download (?:the )?DOCX$/

function inlineDiff(page: Page) {
  return page.getByRole("tabpanel", { name: "Inline diff" })
}

async function openView(page: Page, name: string) {
  await page.getByRole("tab", { name, exact: true }).click()
  const panel = page.getByRole("tabpanel", { name, exact: true })
  await expect(panel).toBeVisible()
  return panel
}

test("generates, edits, reloads, downloads, and reopens the exact Studio draft", async ({
  page,
}) => {
  await page.setViewportSize({ width: 1440, height: 1000 })
  await page.goto(jobRoute)
  await expect(page.getByRole("heading", { name: studioHeading })).toBeVisible()
  await expect(page.getByRole("heading", { name: job.title })).toBeVisible()
  await page.getByRole("button", { name: "Tailor this resume" }).click()
  await expect(page).toHaveURL(draftRoute)
  await expect(
    page.getByRole("tab", { name: "Inline diff", selected: true })
  ).toBeVisible()
  await expect(page.getByText(proposedStatus, { exact: true })).toBeVisible()

  const diff = inlineDiff(page)
  const paper = diff.getByRole("article")
  await expect(paper.getByText(originalSummary, { exact: true })).toBeVisible()
  await expect(paper.getByText(proposedSummary, { exact: true })).toBeVisible()
  await expect(paper.getByText(originalBullet, { exact: true })).toBeVisible()
  await expect(paper.getByText(proposedBullet, { exact: true })).toBeVisible()

  // Keep the designed comparison focused on wording without losing access
  // to the rest of the generated document.
  const details = paper.getByText("Skills and projects", { exact: true })
  await expect(
    paper.getByRole("heading", { name: "Skills", exact: true })
  ).toHaveCount(0)
  await details.click()
  await expect(
    paper.getByRole("heading", { name: "Skills", exact: true })
  ).toBeVisible()
  await details.click()

  const preview = await openView(page, "Preview DOCX")
  await expect(preview.getByText("The tailored resume is ready")).toBeVisible()
  await expect(preview.getByText(draftFilename, { exact: false })).toBeVisible()
  const validation = await openView(page, "Validation")
  await expect(
    validation.getByText("Factuality report", { exact: true })
  ).toBeVisible()
  await expect(
    validation.getByText("Every claim is supported by the résumé")
  ).toBeVisible()

  const letter = await openView(page, "Cover letter")
  await expect(
    letter.getByRole("textbox", { name: /^Cover letter for / })
  ).toHaveValue(proposedLetter)
  await openView(page, "Inline diff")
  await diff.getByRole("button", { name: "Edit draft" }).click()
  const summaryField = diff.getByRole("textbox", {
    name: "Professional summary",
  })
  await expect(summaryField).toHaveValue(proposedSummary)
  await summaryField.fill(savedSummary)
  // The server trims this field; assert on its returned value, not an
  // optimistic copy of what was typed into the section editor.
  await diff
    .getByRole("textbox", { name: "Cover letter", exact: true })
    .fill(`  ${savedLetter}  `)
  await diff.getByRole("button", { name: "Save changes" }).click()
  await expect(page).toHaveURL(draftRoute)
  await expect(page.getByText(editedStatus, { exact: true })).toBeVisible()
  await expect(diff.getByRole("button", { name: "Edit draft" })).toBeVisible()
  await expect(paper.getByText(savedSummary, { exact: true })).toBeVisible()
  await expect(
    diff.getByText("Preferred keywords · 2 of 3", { exact: true })
  ).toBeVisible()
  await openView(page, "Cover letter")
  await expect(
    letter.getByRole("textbox", { name: /^Cover letter for / })
  ).toHaveValue(savedLetter)
  await openView(page, "Validation")
  await expect(validation.getByText("85.0", { exact: true })).toBeVisible()

  const [restored] = await Promise.all([
    page.waitForResponse(
      (response) =>
        response.request().method() === "GET" &&
        new URL(response.url()).pathname === draftApiPath
    ),
    page.reload(),
  ])
  expect(restored.ok()).toBe(true)
  await expect(page).toHaveURL(draftRoute)
  await expect(page.getByText(editedStatus, { exact: true })).toBeVisible()
  await expect(paper.getByText(savedSummary, { exact: true })).toBeVisible()

  const downloadLink = page.getByRole("link", { name: downloadLabel })
  await expect(downloadLink).toHaveAttribute("href", downloadPath)
  const [download] = await Promise.all([
    page.waitForEvent("download"),
    downloadLink.click(),
  ])
  expect(new URL(download.url()).pathname).toBe(downloadPath)
  expect(download.suggestedFilename()).toBe(draftFilename)
  expect(await download.failure()).toBeNull()

  await page.goto("/app/resume")
  const alternateResume = page
    .getByRole("main")
    .getByRole("listitem")
    .filter({ hasText: alternateTitle })
  await alternateResume
    .getByRole("button", { name: `Use ${alternateTitle}`, exact: true })
    .click()
  await expect(
    alternateResume.getByText("In use", { exact: true })
  ).toBeVisible()

  await page.goto("/app/profile")
  const library = await openView(page, "Documents")
  const rowFor = (filename: string) =>
    library.getByRole("listitem").filter({
      has: page.getByText(filename, { exact: true }),
    })
  await expect(
    rowFor(alternateFilename).getByText("In use", { exact: true })
  ).toBeVisible()
  await expect(
    rowFor(otherDraftFilename).getByRole("link", { name: "Open in Studio" })
  ).toBeVisible()
  const reopen = rowFor(draftFilename).getByRole("link", {
    name: "Open in Studio",
  })
  await expect(reopen).toHaveAttribute("href", draftRoute)
  await reopen.click()
  await expect(page).toHaveURL(draftRoute)
  await expect(page.getByText(editedStatus, { exact: true })).toBeVisible()
  await expect(paper.getByText(savedSummary, { exact: true })).toBeVisible()
  await expect(paper.getByText(originalSummary, { exact: true })).toBeVisible()
  const original = await openView(page, "Original")
  await expect(
    original.getByText(originalSummary, { exact: true })
  ).toBeVisible()
  await expect(
    original.getByText(alternateSummary, { exact: true })
  ).toHaveCount(0)
})

const referenceSizes = [
  { width: 1440, height: 1000, sideBySide: true },
  { width: 1024, height: 1000, sideBySide: true },
  { width: 768, height: 1024, sideBySide: false },
  { width: 390, height: 844, sideBySide: false },
] as const
const captureDirectory = fileURLToPath(
  new URL("../.scratch/studio/", import.meta.url)
)

async function bounds(locator: Locator) {
  const box = await locator.boundingBox()
  if (!box) throw new Error(`No rendered box for ${locator}`)
  return box
}

type Box = Awaited<ReturnType<typeof bounds>>
const right = (box: Box) => box.x + box.width
const bottom = (box: Box) => box.y + box.height

async function populatedDiff(page: Page) {
  await page.goto(draftRoute)
  const heading = page.getByRole("heading", { name: studioHeading })
  const diff = inlineDiff(page)
  const paper = diff.getByRole("article")
  const evidence = diff.getByRole("complementary").filter({
    has: page.getByRole("heading", { name: evidenceHeading }),
  })
  await expect(heading).toBeVisible()
  await expect(paper.getByRole("heading", { name: job.title })).toBeVisible()
  await expect(paper.getByText(proposedSummary, { exact: true })).toBeVisible()
  await expect(paper.getByText(proposedBullet, { exact: true })).toBeVisible()
  await expect(
    evidence.getByText("Required keywords · 3 of 4", { exact: true })
  ).toBeVisible()
  await expect(
    evidence.getByText("Preferred keywords · 1 of 3", { exact: true })
  ).toBeVisible()
  await expect(
    evidence.getByRole("button", { name: /^Python — / })
  ).toBeVisible()
  await expect(
    evidence.getByRole("button", { name: /^Kubernetes — / })
  ).toBeVisible()
  await expect(
    evidence.getByText("0 unsupported claims", { exact: true })
  ).toBeVisible()
  await page.evaluate(async () => {
    await document.fonts.ready
  })
  return { heading, paper, evidence }
}

async function readGeometry(page: Page) {
  const main = page.getByRole("main")
  return main.evaluate((element) => ({
    viewportWidth: document.documentElement.clientWidth,
    pageScrollWidth: Math.max(
      document.documentElement.scrollWidth,
      document.body.scrollWidth
    ),
    mainWidth: element.clientWidth,
    mainScrollWidth: element.scrollWidth,
  }))
}

function expectNoOverflow(geometry: Awaited<ReturnType<typeof readGeometry>>) {
  expect(
    geometry.pageScrollWidth,
    "page has no horizontal scrollbar"
  ).toBeLessThanOrEqual(geometry.viewportWidth + 1)
  expect(
    geometry.mainScrollWidth,
    "Studio content does not overflow its container"
  ).toBeLessThanOrEqual(geometry.mainWidth + 1)
}

async function pillBoxes(page: Page) {
  const tabs = page.getByRole("main").getByRole("tablist").getByRole("tab")
  const download = page.getByRole("link", { name: downloadLabel })
  await expect(tabs.getByText("Inline diff", { exact: true })).toBeVisible()
  await expect(download).toBeVisible()
  return [
    ...(await Promise.all((await tabs.all()).map(bounds))),
    await bounds(download),
  ]
}

function expectPillsFit(pills: Box[], width: number, wraps: boolean) {
  for (const pill of pills) {
    expect(pill.x, "pill starts inside the viewport").toBeGreaterThanOrEqual(-1)
    expect(right(pill), "pill ends inside the viewport").toBeLessThanOrEqual(
      width + 1
    )
  }
  if (wraps) {
    const tops = pills.map((pill) => pill.y)
    expect(
      Math.max(...tops) - Math.min(...tops),
      "pills wrap instead of clipping or scrolling"
    ).toBeGreaterThan(16)
  }
}

async function tabTo(page: Page, control: Locator) {
  // Walk the real tab order without assuming the number of shell controls.
  for (let i = 0; i < 30; i += 1) {
    if (await control.evaluate((el) => el === document.activeElement)) break
    await page.keyboard.press("Tab")
  }
  await expect(control).toBeFocused()
}

async function expectVisibleFocus(control: Locator) {
  await expect(control).toBeFocused()
  await expect(control).toBeInViewport()
  await expect
    .poll(
      () =>
        control.evaluate((el) => {
          const style = getComputedStyle(el)
          const outline =
            style.outlineStyle !== "none" && parseFloat(style.outlineWidth) > 0
          const box = el.getBoundingClientRect()
          const topElement = document.elementFromPoint(
            box.x + box.width / 2,
            box.y + box.height / 2
          )
          return (
            el.matches(":focus-visible") &&
            (outline || style.boxShadow !== "none") &&
            el.contains(topElement)
          )
        }),
      { message: "keyboard focus is painted on an unobscured control" }
    )
    .toBe(true)
}

async function checkNarrowKeyboard(page: Page) {
  const diffTab = page.getByRole("tab", { name: "Inline diff" })
  const originalTab = page.getByRole("tab", { name: "Original", exact: true })
  await tabTo(page, diffTab)
  await expectVisibleFocus(diffTab)
  await page.keyboard.press("ArrowRight")
  await expectVisibleFocus(originalTab)
  await page.keyboard.press("Enter")
  await expect(
    page
      .getByRole("tabpanel", { name: "Original", exact: true })
      .getByText(originalSummary, { exact: true })
  ).toBeVisible()
  await page.keyboard.press("ArrowLeft")
  await expect(diffTab).toBeFocused()
  await page.keyboard.press("Enter")
  await expect(inlineDiff(page)).toBeVisible()
  await tabTo(page, page.getByRole("link", { name: downloadLabel }))
  await expectVisibleFocus(page.getByRole("link", { name: downloadLabel }))
  const edit = inlineDiff(page).getByRole("button", { name: "Edit draft" })
  await tabTo(page, edit)
  await expectVisibleFocus(edit)
  await page.keyboard.press("Enter")
  await expect(
    inlineDiff(page).getByRole("textbox", { name: "Professional summary" })
  ).toBeVisible()
}

test.describe("responsive Studio", () => {
  test.use({ seedDraft: true })

  for (const { width, height, sideBySide } of referenceSizes) {
    test(`populated Inline diff at ${width}×${height}`, async ({ page }) => {
      await page.setViewportSize({ width, height })
      const { heading, paper, evidence } = await populatedDiff(page)
      await expect(
        page.getByText(proposedStatus, { exact: true })
      ).toBeVisible()
      const review = evidence.getByRole("link", { name: /^Continue to review/ })
      await expect(review).toBeVisible()
      const geometry = await readGeometry(page)
      const pills = await pillBoxes(page)
      const paperBox = await bounds(paper)
      const evidenceBox = await bounds(evidence)
      const reviewBox = await bounds(review)

      // Match the reference frame (not the extra scrollable content below it).
      if (process.env.E2E_STUDIO_SCREENSHOTS === "1") {
        await mkdir(captureDirectory, { recursive: true })
        const target = join(
          captureDirectory,
          `studio-inline-diff-${width}x${height}`
        )
        await page.screenshot({
          path: `${target}.png`,
          animations: "disabled",
          scale: "css",
        })
        await writeFile(
          `${target}.json`,
          JSON.stringify(
            {
              width,
              height,
              heading: await bounds(heading),
              pills,
              paper: paperBox,
              evidence: evidenceBox,
              review: reviewBox,
              geometry,
            },
            null,
            2
          ) + "\n"
        )
      }

      expectNoOverflow(geometry)
      expectPillsFit(pills, geometry.viewportWidth, width === 390)
      if (sideBySide) {
        expect(
          evidenceBox.x,
          "evidence is to the right of the document"
        ).toBeGreaterThan(right(paperBox))
        expect(
          evidenceBox.y,
          "evidence starts alongside the document, not below it"
        ).toBeLessThanOrEqual(paperBox.y + 1)
        // Its card ends shortly below its last control, not at the taller
        // document's bottom edge. Allow space for padding and focus rings.
        expect(
          bottom(evidenceBox) - bottom(reviewBox),
          "evidence uses its own content height"
        ).toBeLessThanOrEqual(48)
      } else {
        expect(
          evidenceBox.y,
          "evidence stacks below the document"
        ).toBeGreaterThan(bottom(paperBox))
        expect(evidenceBox.x).toBeLessThanOrEqual(paperBox.x + 1)
        expect(right(evidenceBox)).toBeGreaterThanOrEqual(right(paperBox) - 1)
      }
      if (width === 390) await checkNarrowKeyboard(page)
    })
  }

  test("360px Studio wraps without overflow and remains keyboard operable", async ({
    page,
  }) => {
    await page.setViewportSize({ width: 360, height: 800 })
    await populatedDiff(page)
    const geometry = await readGeometry(page)
    expectNoOverflow(geometry)
    expectPillsFit(await pillBoxes(page), geometry.viewportWidth, true)
    await checkNarrowKeyboard(page)
    expectNoOverflow(await readGeometry(page))
  })
})
