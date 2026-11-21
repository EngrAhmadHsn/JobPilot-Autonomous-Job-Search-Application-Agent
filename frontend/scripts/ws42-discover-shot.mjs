// Drive a real Discover search so the split view can be photographed.
//
// Read-only in the sense that matters: it posts one `POST /api/jobs/search`
// — the same call the operator makes — and clicks nothing that mutates state.

import { chromium } from "playwright"
import { mkdirSync } from "node:fs"
import { dirname, resolve } from "node:path"

const BASE = process.env.WS42_BASE ?? "http://localhost:5191"
const EMAIL = process.env.WS42_EMAIL ?? "operator@example.com"
const PASSWORD = process.env.WS42_PASSWORD ?? "operator-local-password"

function arg(name, fallback) {
  const index = process.argv.indexOf(`--${name}`)
  return index >= 0 && process.argv[index + 1]
    ? process.argv[index + 1]
    : fallback
}

const profileId = arg("profile", "")
const query = arg("query", "backend engineer")
const out = resolve(
  arg("out", "../docs/design/ws42/browser/discover-search.png")
)
const size = arg("size", "1440x1000")
const [width, height] = size.split("x").map(Number)

const browser = await chromium.launch()
const context = await browser.newContext({
  viewport: { width, height },
  deviceScaleFactor: 1,
})
if (profileId) {
  await context.addInitScript(
    ([key, value]) => {
      try {
        window.localStorage.setItem(key, value)
      } catch {
        /* storage denied: the screen shows its empty state */
      }
    },
    ["aja.currentProfileId", profileId]
  )
}
const page = await context.newPage()
const errors = []
page.on("console", (m) => {
  if (m.type() === "error") errors.push(m.text())
})

await page.goto(`${BASE}/sign-in`, { waitUntil: "networkidle" })
await page.getByLabel(/e-?mail/i).fill(EMAIL)
await page.getByLabel(/password/i).fill(PASSWORD)
await page.getByRole("button", { name: /sign in|log in/i }).click()
await page.waitForURL(/\/app/, { timeout: 60_000 })

await page.goto(`${BASE}/app/matches`, { waitUntil: "networkidle" })
await page.getByLabel(/query/i).fill(query)
/*
  Click the **form's** submit button, scoped to the search form. A bare
  `getByRole("button", { name: /search/i })` also matches the top bar's
  "Search jobs" link, which sits earlier in the DOM — the first version of
  this line clicked that instead, navigated, and photographed an empty screen
  while believing it had run a search.
*/
await page.getByRole("button", { name: "Search jobs", exact: true }).click()

// The ranking can take a while on a cold corpus; wait for a result row.
try {
  await page.waitForSelector(
    '[aria-label="Ranked matches"] li, [aria-label="Ranked matches"] a',
    {
      timeout: 180_000,
    }
  )
} catch {
  console.warn("no ranked rows appeared within 180s")
}
await page.waitForTimeout(2500)

mkdirSync(dirname(out), { recursive: true })
await page.screenshot({ path: out })
console.log(`wrote ${out} (${size})`)
if (errors.length) {
  console.log(`console errors (${errors.length}):`)
  for (const e of errors.slice(0, 5)) console.log(`  • ${e}`)
}
await browser.close()
