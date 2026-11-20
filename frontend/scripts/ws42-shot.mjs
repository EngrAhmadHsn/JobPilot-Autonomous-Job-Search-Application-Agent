// A single-screen browser capture for the WS-42 visual loop.
//
// It signs in as the local operator, opens one route, waits for the network
// to settle, and writes a screenshot. Read-only: it clicks nothing that
// mutates state.
//
// Usage:
//   node scripts/ws42-shot.mjs --path /app --out ../docs/design/ws42/browser/x.png
//   node scripts/ws42-shot.mjs --path /app --size 390x844 --out shot.png
//
// Environment:
//   WS42_BASE      console origin   (default http://localhost:5191)
//   WS42_EMAIL     sign-in e-mail   (default operator@example.com)
//   WS42_PASSWORD  password         (default operator-local-password)

import { chromium } from "playwright"
import { mkdirSync } from "node:fs"
import { dirname, resolve } from "node:path"

const BASE = process.env.WS42_BASE ?? "http://localhost:5191"
const EMAIL = process.env.WS42_EMAIL ?? "operator@example.com"
const PASSWORD = process.env.WS42_PASSWORD ?? "operator-local-password"

function arg(name, fallback) {
  const index = process.argv.indexOf(`--${name}`)
  return index >= 0 && process.argv[index + 1] ? process.argv[index + 1] : fallback
}

const path = arg("path", "/app")
const size = arg("size", "1440x1000")
const full = process.argv.includes("--full")
/*
  `--no-login` photographs the unauthenticated surface (the sign-in screen).
  A fresh context has no session cookie, so the console cannot redirect away
  from it — the point of the flag is to skip the sign-in *submission*, not to
  fake a logged-out state.
*/
const noLogin = process.argv.includes("--no-login")
const out = resolve(arg("out", "../docs/design/ws42/browser/shot.png"))
/*
  The console keeps the chosen résumé profile in `localStorage`
  (`aja.currentProfileId`), not on the server, so a fresh browser context has
  no profile and every profile-dependent screen renders its empty state. That
  is correct behaviour and useless for a visual comparison — so this option
  seeds the choice before the first navigation. It is read-only: it selects an
  existing profile and writes nothing to the API.
*/
const profileId = arg("profile", "")
const storageProfile = arg("storage-profile", "aja.currentProfileId")

const [width, height] = size.split("x").map(Number)

const browser = await chromium.launch()
const context = await browser.newContext({
  viewport: { width, height },
  deviceScaleFactor: 1,
})

if (profileId) {
  /*
    `addInitScript` runs before any page script on every navigation, so the
    choice is in place before the console reads it — including after the
    sign-in navigation, which would otherwise leave a one-shot `evaluate`
    behind on a page that no longer exists.
  */
  await context.addInitScript(
    ([key, value]) => {
      try {
        window.localStorage.setItem(key, value)
      } catch {
        // A storage-denied context simply renders the empty state.
      }
    },
    [storageProfile, profileId]
  )
}

const page = await context.newPage()
const consoleErrors = []
page.on("console", (message) => {
  if (message.type() === "error") consoleErrors.push(message.text())
})

if (!noLogin) {
  await page.goto(`${BASE}/sign-in`, { waitUntil: "networkidle" })
  await page.getByLabel(/e-?mail/i).fill(EMAIL)
  await page.getByLabel(/password/i).fill(PASSWORD)
  await page.getByRole("button", { name: /sign in|log in/i }).click()
  await page.waitForURL(/\/app/, { timeout: 60_000 })
}

await page.goto(`${BASE}${path}`, { waitUntil: "networkidle" })
// Let skeletons resolve into content.
await page.waitForTimeout(1500)

const landed = new URL(page.url()).pathname
// Compare path **only**: `path` may carry a query string (`?view=board`),
// and the point of this check is to catch a redirect to the sign-in screen or
// the landing page — not to reject a URL that correctly kept its query.
const wantedPath = path.split("?")[0]
if (landed !== wantedPath) {
  console.warn(`landed on ${landed}, not ${wantedPath} — the screenshot is of ${landed}`)
}

mkdirSync(dirname(out), { recursive: true })
await page.screenshot({ path: out, fullPage: full })
console.log(`wrote ${out} (${size}${full ? ", full page" : ""}) from ${landed}`)
if (consoleErrors.length) {
  console.log(`console errors (${consoleErrors.length}):`)
  for (const message of consoleErrors.slice(0, 5)) console.log(`  • ${message}`)
}

await browser.close()
