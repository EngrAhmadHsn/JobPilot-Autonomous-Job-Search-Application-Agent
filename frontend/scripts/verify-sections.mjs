// Capture the landing page's lower sections as their own frames.
import { chromium } from "playwright"
import { fileURLToPath } from "node:url"
import { join } from "node:path"
import { mkdirSync } from "node:fs"

const OUT = fileURLToPath(new URL("../refs-out/experience/", import.meta.url))
mkdirSync(OUT, { recursive: true })
const BASE = process.env.VERIFY_BASE ?? "http://localhost:4173"

const browser = await chromium.launch()
const page = await browser.newPage({ viewport: { width: 1440, height: 1100 } })
const problems = []
page.on("console", (m) => {
  if (m.type() === "error") problems.push(m.text())
})
page.on("pageerror", (e) => problems.push(`pageerror: ${e.message}`))
await page.goto(`${BASE}/`, { waitUntil: "networkidle" })
await page.waitForTimeout(900)

for (const id of ["how", "product", "trust"]) {
  const el = page.locator(`#${id}`)
  await el.scrollIntoViewIfNeeded()
  await page.waitForTimeout(700)
  await el.screenshot({ path: join(OUT, `section-${id}.png`) })
}

await page.evaluate(() => window.scrollTo(0, document.body.scrollHeight))
await page.waitForTimeout(700)
await page.screenshot({ path: join(OUT, "section-footer.png") })

await browser.close()
console.log(JSON.stringify({ sections: "captured", problems }, null, 2))
