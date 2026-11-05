// The visitor's machine says "reduce". Does the in-app "Full" choice
// restore the light field, the stagger and the walkthrough?
import { chromium } from "playwright"

const BASE = process.env.VERIFY_BASE ?? "http://localhost:5173"

const browser = await chromium.launch()
const ctx = await browser.newContext({
  viewport: { width: 1440, height: 900 },
  reducedMotion: "reduce",
})
const page = await ctx.newPage()
await page.goto(`${BASE}/`, { waitUntil: "networkidle" })
await page.waitForTimeout(700)

const snapshot = async (label) => {
  const state = await page.evaluate(() => {
    const h1 = document.querySelector("h1")
    const sub = Array.from(document.querySelectorAll("h1 ~ p"))[0]
    return {
      dataMotion: document.documentElement.getAttribute("data-motion"),
      h1Animation: h1 ? `${getComputedStyle(h1).animationName} ${getComputedStyle(h1).animationDuration} delay ${getComputedStyle(h1).animationDelay}` : null,
      subAnimationDelay: sub ? getComputedStyle(sub).animationDelay : null,
    }
  })
  return { label, ...state }
}

const canvasHash = () =>
  page.locator("canvas").first().evaluate((c) => c.toDataURL().slice(-3000))

const before = await snapshot("on load (OS = reduce)")

const hashA = await canvasHash()
await page.mouse.move(200, 500)
await page.mouse.move(1200, 250, { steps: 25 })
await page.waitForTimeout(600)
const reducedRepaints = hashA !== (await canvasHash())

// Choose "Full" from the header control.
await page
  .getByRole("group", { name: "Motion" })
  .first()
  .getByRole("button", { name: "Full" })
  .click()
await page.waitForTimeout(600)

const after = await snapshot("after choosing Full")

const hashB = await canvasHash()
await page.mouse.move(300, 600)
await page.mouse.move(1250, 200, { steps: 25 })
await page.waitForTimeout(600)
const fullRepaints = hashB !== (await canvasHash())

// Does the walkthrough advance now?
await page.locator("#demo").scrollIntoViewIfNeeded()
const selected = () =>
  page.evaluate(
    () =>
      document.querySelector('[role="tab"][aria-selected="true"]')
        ?.textContent?.trim() ?? null
  )
const tabBefore = await selected()
await page.waitForTimeout(6500)
const tabAfter = await selected()

await browser.close()
console.log(
  JSON.stringify(
    {
      before,
      after,
      reducedRepaints,
      fullRepaints,
      demo: { tabBefore, tabAfter, advanced: tabBefore !== tabAfter },
    },
    null,
    2
  )
)