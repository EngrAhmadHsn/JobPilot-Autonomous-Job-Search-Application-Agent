// The visual acceptance pass for WS-17: drive the built app in a real
// browser, capture the surfaces, and record any console/CSP errors.
import { chromium } from "playwright"
import { mkdirSync } from "node:fs"
import { fileURLToPath } from "node:url"
import { join } from "node:path"

const OUT = fileURLToPath(new URL("../refs-out/experience/", import.meta.url))
mkdirSync(OUT, { recursive: true })
const BASE = process.env.VERIFY_BASE ?? "http://localhost:4173"
const shot = (page, name) => page.screenshot({ path: join(OUT, name) })

const problems = []
const browser = await chromium.launch()
const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 } })
const page = await ctx.newPage()
page.on("console", (m) => {
  if (m.type() === "error") problems.push(`console.error: ${m.text()}`)
})
page.on("pageerror", (e) => problems.push(`pageerror: ${e.message}`))

// ---- the landing page ----------------------------------------------------
await page.goto(`${BASE}/`, { waitUntil: "networkidle" })
await page.waitForTimeout(900)
await shot(page, "01-landing-hero.png")

// Move the pointer across the hero to exercise the light field.
await page.mouse.move(400, 300)
await page.mouse.move(900, 420, { steps: 20 })
await page.waitForTimeout(500)
await shot(page, "02-landing-hero-pointer.png")

// Drive the demonstration.
await page.locator("#demo").scrollIntoViewIfNeeded()
await page.getByRole("tab", { name: /job discovery/i }).click()
await page.waitForTimeout(500)
await shot(page, "03-landing-demo-discovery.png")
await page.getByRole("tab", { name: /tailoring/i }).click()
await page.waitForTimeout(500)
await shot(page, "04-landing-demo-tailoring.png")
await page.getByRole("tab", { name: /approval/i }).click()
await page.waitForTimeout(400)
await shot(page, "05-landing-demo-approval.png")

await shot(page, "06-landing-full.png")

// ---- mobile --------------------------------------------------------------
const mobile = await browser.newContext({
  viewport: { width: 390, height: 844 },
  hasTouch: true,
  isMobile: true,
})
const mp = await mobile.newPage()
await mp.goto(`${BASE}/`, { waitUntil: "networkidle" })
await mp.waitForTimeout(800)
await mp.screenshot({ path: join(OUT, "07-landing-mobile.png") })
await mobile.close()

// ---- the console ---------------------------------------------------------
await page.goto(`${BASE}/sign-in`)
await page.waitForTimeout(400)
await shot(page, "08-sign-in.png")

await page.fill('input[type="email"]', "operator@example.com")
await page.fill('input[type="password"]', "operator-local-password")
await page.getByRole("button", { name: /sign in/i }).click()
await page.waitForTimeout(2500)
await shot(page, "09-console-overview.png")

for (const [name, path] of [
  ["10-activity", "/app/activity"],
  ["11-admin", "/app/admin"],
  ["12-resume", "/app/resume"],
  ["13-tracker", "/app/tracker"],
]) {
  await page.goto(`${BASE}${path}`, { waitUntil: "networkidle" })
  await page.waitForTimeout(1200)
  await shot(page, `${name}.png`)
}

// The signed-in console at a tablet width.
await page.setViewportSize({ width: 834, height: 1112 })
await page.goto(`${BASE}/app`, { waitUntil: "networkidle" })
await page.waitForTimeout(1000)
await shot(page, "14-console-tablet.png")

await browser.close()
console.log(JSON.stringify({ base: BASE, problems }, null, 2))
