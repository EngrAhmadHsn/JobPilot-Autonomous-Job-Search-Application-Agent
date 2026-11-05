// Why is nothing animating? Measure the actual runtime state.
import { chromium } from "playwright"

const BASE = process.env.VERIFY_BASE ?? "http://localhost:4173"

const browser = await chromium.launch()
const page = await browser.newPage({ viewport: { width: 1440, height: 900 } })
const errors = []
page.on("console", (m) => {
  if (m.type() === "error") errors.push(m.text())
})

await page.goto(`${BASE}/`, { waitUntil: "networkidle" })
await page.waitForTimeout(800)

const env = await page.evaluate(() => ({
  reducedMotion: window.matchMedia("(prefers-reduced-motion: reduce)").matches,
  pointerFine: window.matchMedia("(hover: hover) and (pointer: fine)").matches,
  canvases: document.querySelectorAll("canvas").length,
  canvasBox: (() => {
    const c = document.querySelector("canvas")
    if (!c) return null
    const r = c.getBoundingClientRect()
    return { w: Math.round(r.width), h: Math.round(r.height), bitmapW: c.width, bitmapH: c.height }
  })(),
}))

// Does the canvas actually repaint when the pointer moves?
const sample = async () => {
  const canvas = page.locator("canvas").first()
  return canvas.evaluate((c) => c.toDataURL().slice(-4000))
}
const before = await sample()
await page.mouse.move(200, 500)
await page.mouse.move(1200, 300, { steps: 30 })
await page.waitForTimeout(600)
const after = await sample()

// Are the CSS animations and transitions live, or zeroed by a media query?
const computed = await page.evaluate(() => {
  const probe = document.querySelector("h1")
  const h1 = probe ? getComputedStyle(probe) : null
  const btn = document.querySelector("a")
  const btnStyle = btn ? getComputedStyle(btn) : null
  // A reveal-marked card, wherever one is.
  const card = document.querySelector("[data-reveal]")
  const cardStyle = card ? getComputedStyle(card) : null
  return {
    h1FontFamily: h1?.fontFamily ?? null,
    h1AnimationName: h1?.animationName ?? null,
    h1AnimationDuration: h1?.animationDuration ?? null,
    bodyBg: getComputedStyle(document.body).backgroundColor,
    buttonTransitionDuration: btnStyle?.transitionDuration ?? null,
    cardTransitionDuration: cardStyle?.transitionDuration ?? null,
    cardOpacity: cardStyle?.opacity ?? null,
    cardRevealState: card?.getAttribute("data-reveal") ?? "(no attribute)",
    cardCount: document.querySelectorAll("[data-reveal]").length,
  }
})

// Does the demo advance on its own?
await page.locator("#demo").scrollIntoViewIfNeeded()
const selected = () =>
  page.evaluate(() => {
    const tab = document.querySelector('[role="tab"][aria-selected="true"]')
    return tab?.textContent?.trim() ?? null
  })
const tabBefore = await selected()
await page.waitForTimeout(6500)
const tabAfter = await selected()

await browser.close()
console.log(
  JSON.stringify(
    {
      BASE,
      env,
      canvasRepaintsOnPointerMove: before !== after,
      computed,
      demo: { tabBefore, tabAfter, advanced: tabBefore !== tabAfter },
      errors,
    },
    null,
    2
  )
)
