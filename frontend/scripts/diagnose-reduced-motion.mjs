// Reproduce the visitor's environment: prefers-reduced-motion: reduce
// (Playwright otherwise forces no-preference, which hid this).
import { chromium } from "playwright"

const BASE = process.env.VERIFY_BASE ?? "http://localhost:5173"

const SAMPLER = () => {
  const samples = []
  const start = performance.now()
  const tick = () => {
    const h1 = document.querySelector("h1")
    if (h1) {
      const cs = getComputedStyle(h1)
      samples.push([
        Math.round(performance.now() - start),
        cs.opacity,
        cs.transform === "none" ? "none" : cs.transform,
      ])
    }
    if (performance.now() - start < 1600) requestAnimationFrame(tick)
  }
  requestAnimationFrame(tick)
  // @ts-ignore
  window.__samples = samples
}

const browser = await chromium.launch()

async function run(label, reducedMotion) {
  const ctx = await browser.newContext({
    viewport: { width: 1440, height: 900 },
    reducedMotion,
  })
  const page = await ctx.newPage()
  await page.addInitScript(SAMPLER)
  await page.goto(`${BASE}/`, { waitUntil: "networkidle" })
  await page.waitForTimeout(1800)

  const report = await page.evaluate(() => {
    // @ts-ignore
    const samples = window.__samples ?? []
    const h1 = document.querySelector("h1")
    const card = document.querySelector("[data-reveal]")
    return {
      samples,
      h1Animation: h1
        ? `${getComputedStyle(h1).animationName} ${getComputedStyle(h1).animationDuration}`
        : null,
      cardTransitionDuration: card
        ? getComputedStyle(card).transitionDuration
        : null,
      prefersReduced: window.matchMedia("(prefers-reduced-motion: reduce)")
        .matches,
      canvases: document.querySelectorAll("canvas").length,
    }
  })
  await ctx.close()

  // Did the headline actually fade, or blink?
  const opacities = report.samples.map((s) => Number(s[1]))
  const distinct = [...new Set(opacities)]
  const travelled = report.samples.some((s) => s[2] !== "none")

  return {
    label,
    prefersReduced: report.prefersReduced,
    h1Animation: report.h1Animation,
    cardTransitionDuration: report.cardTransitionDuration,
    canvases: report.canvases,
    opacitySeriesFirst10: report.samples.slice(0, 10),
    fadedThroughIntermediateValues: distinct.length > 2,
    travelledWithTransform: travelled,
  }
}

const reduce = await run("reduced-motion ON (the visitor's machine)", "reduce")
const normal = await run("reduced-motion OFF", "no-preference")

await browser.close()
console.log(JSON.stringify({ reduce, normal }, null, 2))
