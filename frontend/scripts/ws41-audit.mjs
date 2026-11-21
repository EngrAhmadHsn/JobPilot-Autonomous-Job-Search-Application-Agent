// WS-41 (WS-UX-09) — the responsive / accessibility / state audit harness.
//
// It drives the **running** console against the **real** backend, signs in as
// the local operator, and then, for every required surface and viewport,
// records: whether the page scrolls sideways, whether any element overflows its
// container, every interactive control that has no accessible name, every
// heading outline, and a screenshot.
//
// It is read-only: it clicks no destructive control, never approves, never
// submits, and never types into a form that would save. Everything it records is
// an observation of server state it did not change.
//
// Usage:
//   node scripts/ws41-audit.mjs                 # all surfaces, all viewports
//   node scripts/ws41-audit.mjs --only home,discover
//   node scripts/ws41-audit.mjs --viewports 1440x1000,390x844
//
// Environment:
//   WS41_BASE       console origin            (default http://localhost:5191)
//   WS41_EMAIL      sign-in e-mail            (default operator@example.com)
//   WS41_PASSWORD   sign-in password          (default operator-local-password)
//   WS41_OUT        screenshot directory      (default ../.scratch/ws41)

import { chromium } from "playwright"
import { mkdirSync, writeFileSync } from "node:fs"
import { fileURLToPath } from "node:url"
import { join, resolve } from "node:path"

const BASE = process.env.WS41_BASE ?? "http://localhost:5191"
const EMAIL = process.env.WS41_EMAIL ?? "operator@example.com"
const PASSWORD = process.env.WS41_PASSWORD ?? "operator-local-password"
const OUT = resolve(
  fileURLToPath(
    new URL(process.env.WS41_OUT ?? "../.scratch/ws41", import.meta.url)
  )
)

/**
 * Every required surface.
 *
 * The paths are the **real** routes from `src/routes.tsx` — the nav's
 * conceptual labels ("Discover") map onto existing URLs (`/app/matches`), and
 * no deep link may change.
 *
 * The render assertion is the **landed path**, not a text match: an unknown
 * path falls to the catch-all, which redirects to the public landing page, and
 * an unauthenticated caller is sent to `/sign-in`. Both would otherwise be
 * photographed as if they were the surface we asked for. Comparing `pathname`
 * catches exactly those two cases and nothing else — a text probe would also
 * trip over the console's own copy ("Résumé" is accented; a heading may be
 * absent on an intentionally empty screen).
 */
const SURFACES = [
  { key: "home", path: "/app" },
  { key: "discover", path: "/app/matches" },
  { key: "resume", path: "/app/resume" },
  { key: "tailor", path: "/app/tailor" },
  { key: "review", path: "/app/approvals" },
  { key: "tracker", path: "/app/tracker" },
  { key: "profile", path: "/app/profile" },
  { key: "account", path: "/app/account" },
  { key: "activity", path: "/app/activity" },
  { key: "operations", path: "/app/operations" },
  { key: "admin", path: "/app/admin" },
]

/**
 * Tab steps that reveal a region the master prompt requires us to check.
 *
 * The labels are the **real** ones the screen renders (WS-46 moved Profile's
 * tabs to Documents / Application answers / Work preferences). A stale label
 * here is worse than no step: the sweep asks for a tab that does not exist,
 * photographs the first tab instead, and reports a clean surface it never
 * visited.
 */
const TAB_STEPS = {
  profile: [
    { tab: "Application answers", key: "profile-answers" },
    { tab: "Work preferences", key: "profile-preferences" },
  ],
  account: [
    { tab: "Model credentials", key: "account-credentials" },
    { tab: "Privacy", key: "account-privacy" },
  ],
}

const VIEWPORTS = [
  // The four frames the design is drawn at, then the three the sweep has
  // always carried (a laptop, a tablet-landscape and two phones).
  { w: 1440, h: 1000, key: "1440x1000" },
  { w: 1024, h: 1000, key: "1024x1000" },
  { w: 1280, h: 800, key: "1280x800" },
  { w: 900, h: 1000, key: "900x1000" },
  { w: 768, h: 1024, key: "768x1024" },
  { w: 390, h: 844, key: "390x844" },
  { w: 360, h: 800, key: "360x800" },
]

function arg(name, fallback) {
  const i = process.argv.indexOf(`--${name}`)
  return i === -1 ? fallback : process.argv[i + 1]
}

const onlyKeys = arg("only")
  ?.split(",")
  .map((s) => s.trim())
const viewportKeys = arg("viewports")
  ?.split(",")
  .map((s) => s.trim())
  .map((k) => VIEWPORTS.find((v) => v.key === k))
  .filter(Boolean)

const surfaces = onlyKeys
  ? SURFACES.filter((s) => onlyKeys.includes(s.key))
  : SURFACES
const viewports = viewportKeys?.length ? viewportKeys : VIEWPORTS

/**
 * A surface whose path cannot be a constant.
 *
 * One application's questions page lives at
 * `/app/tracker/<application id>/questions`, so the sweep discovers the id
 * from the signed-in session and appends the surface. Nothing is invented:
 * with no tracked application in the database the surface is skipped and
 * the run says so.
 */
function addDiscoveredSurface(surface) {
  SURFACES.push(surface)
  if (!onlyKeys || onlyKeys.includes(surface.key)) surfaces.push(surface)
}

/** The in-page probe. Returns observations, never mutates anything. */
async function probe(page) {
  return page.evaluate(() => {
    const de = document.documentElement
    const name = (el) => {
      const aria = el.getAttribute("aria-label")?.trim()
      if (aria) return aria
      const labelled = el.getAttribute("aria-labelledby")
      if (labelled) {
        const t = labelled
          .split(/\s+/)
          .map((id) => document.getElementById(id)?.textContent ?? "")
          .join(" ")
          .trim()
        if (t) return t
      }
      if (el.id) {
        const l = document.querySelector(`label[for="${CSS.escape(el.id)}"]`)
        if (l?.textContent?.trim()) return l.textContent.trim()
      }
      const wrapped = el.closest("label")
      if (wrapped?.textContent?.trim()) return wrapped.textContent.trim()
      const text = el.textContent?.trim()
      if (text) return text
      const title = el.getAttribute("title")?.trim()
      if (title) return title
      const img = el.getAttribute("alt")?.trim()
      if (img) return img
      const ph = el.getAttribute("placeholder")?.trim()
      if (ph) return `(placeholder only) ${ph}`
      return null
    }

    // Controls a screen reader must be able to name.
    const controlSel =
      "a[href],button,input:not([type=hidden]),select,textarea,[role=button],[role=link],[role=tab],[role=checkbox],[role=switch],[role=radio]"
    const unnamed = []
    for (const el of document.querySelectorAll(controlSel)) {
      if (el.closest("[aria-hidden=true]")) continue
      const style = getComputedStyle(el)
      if (style.display === "none" || style.visibility === "hidden") continue
      if (el.closest("[inert]")) continue
      if (!name(el)) {
        unnamed.push({
          tag: el.tagName.toLowerCase(),
          type: el.getAttribute("type"),
          cls: (el.className || "").toString().slice(0, 80),
        })
      }
    }

    // Elements that stick out sideways past the viewport.
    //
    // A child of a horizontally scrollable container is NOT a defect: a chip
    // row that scrolls on a phone is the correct treatment, and reporting it
    // would drown the real findings. So an offender is only recorded when no
    // ancestor along the way clips or scrolls horizontally.
    const vw = window.innerWidth
    const scrollableAncestor = (el) => {
      for (
        let a = el.parentElement;
        a && a !== document.body;
        a = a.parentElement
      ) {
        const s = getComputedStyle(a)
        const scrollsX =
          a.scrollWidth > a.clientWidth + 1 &&
          /(auto|scroll|hidden|clip)/.test(s.overflowX)
        if (scrollsX) return a
        if (s.overflowX === "hidden" || s.overflowX === "clip") return a
      }
      return null
    }
    const overflow = []
    for (const el of document.querySelectorAll("body *")) {
      if (el.closest("[data-ws41-ignore]")) continue
      const r = el.getBoundingClientRect()
      if (r.width === 0 || r.height === 0) continue
      if (r.right > vw + 1 || r.left < -1) {
        const container = scrollableAncestor(el)
        if (container) continue
        overflow.push({
          tag: el.tagName.toLowerCase(),
          cls: (el.className || "").toString().slice(0, 70),
          left: Math.round(r.left),
          right: Math.round(r.right),
          text: (el.textContent ?? "").trim().slice(0, 50),
        })
      }
    }

    const h1s = [...document.querySelectorAll("h1")].map((h) =>
      (h.textContent ?? "").trim()
    )
    const headings = [...document.querySelectorAll("h1,h2,h3,h4")].map((h) => ({
      level: Number(h.tagName[1]),
      text: (h.textContent ?? "").trim().slice(0, 70),
    }))

    // Focus visibility: the treatment must paint a ring, not just outline:none.
    const focusables = [
      ...document.querySelectorAll("a[href],button,input,select,textarea"),
    ].filter((el) => {
      const s = getComputedStyle(el)
      return s.display !== "none" && s.visibility !== "hidden" && !el.disabled
    }).length

    return {
      title: document.title,
      scrollWidth: de.scrollWidth,
      clientWidth: de.clientWidth,
      sideways: de.scrollWidth > de.clientWidth + 1,
      docHeight: de.scrollHeight,
      unnamed: unnamed.slice(0, 40),
      unnamedCount: unnamed.length,
      overflow: overflow.slice(0, 25),
      overflowCount: overflow.length,
      h1s,
      headings: headings.slice(0, 60),
      focusables,
      hasMain: !!document.querySelector("main"),
      hasSkip: !!document.querySelector(
        'a[href^="#"][class*="sr-only"], a[data-skip-link]'
      ),
      loadingMentions: (
        document.body.innerText.match(/loading|please wait/gi) ?? []
      ).length,
      errorTexts: [
        ...document.querySelectorAll(
          "[role=alert], .error-state, [data-error-state]"
        ),
      ].map((e) => (e.textContent ?? "").trim().slice(0, 120)),
    }
  })
}

const browser = await chromium.launch()
const results = []
mkdirSync(OUT, { recursive: true })

// ---- one signed-in session, reused ---------------------------------------
const ctx = await browser.newContext({
  viewport: { width: 1440, height: 1000 },
})
const page = await ctx.newPage()
const consoleErrors = []
page.on("console", (m) => {
  if (m.type() === "error") consoleErrors.push(m.text().slice(0, 300))
})
page.on("pageerror", (e) => consoleErrors.push(`pageerror: ${e.message}`))

await page.goto(`${BASE}/sign-in`, { waitUntil: "networkidle" })
await page.getByLabel("Email").fill(EMAIL)
await page.getByLabel("Password").fill(PASSWORD)
await page.getByRole("button", { name: /^Sign in$/ }).click()
await page.waitForURL(/\/app(\/|$)/, { timeout: 30_000 })
const signedIn = page.url()
console.log(`signed in → ${signedIn}`)

// ---- the discovered surface ----------------------------------------------
// The per-application questions page (WS-45) is the one console surface
// whose path carries a record id. Ask the signed-in session for the first
// tracked application; with none, skip the surface and say so rather than
// photograph a 404 as if it were the page.
const firstApplicationId = await page.evaluate(async () => {
  try {
    const response = await fetch("/api/applications?limit=1", {
      credentials: "include",
    })
    if (!response.ok) return null
    const body = await response.json()
    return body?.items?.[0]?.id ?? null
  } catch {
    return null
  }
})
if (firstApplicationId) {
  addDiscoveredSurface({
    key: "questions",
    path: `/app/tracker/${firstApplicationId}/questions`,
  })
  console.log(`questions surface → /app/tracker/${firstApplicationId}/questions`)
} else {
  console.log("no tracked application — the questions surface is skipped")
}

const storage = await ctx.storageState()

// ---- the sweep ------------------------------------------------------------
for (const vp of viewports) {
  for (const surface of surfaces) {
    const vctx = await browser.newContext({
      viewport: { width: vp.w, height: vp.h },
      storageState: storage,
      hasTouch: vp.w <= 900,
      isMobile: false,
    })
    const p = await vctx.newPage()
    const errs = []
    p.on("console", (m) => {
      if (m.type() === "error") errs.push(m.text().slice(0, 300))
    })
    p.on("pageerror", (e) => errs.push(`pageerror: ${e.message}`))

    const record = {
      surface: surface.key,
      path: surface.path,
      viewport: vp.key,
    }
    try {
      await p.goto(`${BASE}${surface.path}`, {
        waitUntil: "networkidle",
        timeout: 45_000,
      })
      // A polling screen keeps a request in flight; networkidle is enough.
      await p.waitForTimeout(700)

      // ---- the render assertion -----------------------------------------
      // The console redirects an unauthenticated caller to the sign-in
      // screen, and an unknown path falls to the catch-all that redirects
      // home. Both would otherwise be photographed as if they were the
      // surface we asked for.
      const landed = p.url()
      const landedPath = new URL(landed).pathname
      const isSignIn =
        landedPath === "/sign-in" ||
        (await p.getByLabel("Password").count()) > 0
      if (isSignIn) {
        record.failure = `not authenticated — landed on the sign-in screen (${landed})`
        results.push(record)
        console.log(
          `${vp.key.padEnd(9)} ${surface.key.padEnd(11)} FAILED (not signed in)`
        )
        await vctx.close()
        continue
      }
      if (landedPath !== surface.path) {
        record.failure = `surface did not render — asked for ${surface.path}, the console landed on ${landedPath}`
        results.push(record)
        console.log(
          `${vp.key.padEnd(9)} ${surface.key.padEnd(11)} FAILED (landed on ${landedPath})`
        )
        await vctx.close()
        continue
      }
      record.landed = landed

      record.main = await probe(p)
      await p.screenshot({
        path: join(OUT, `${surface.key}-${vp.key}.png`),
        fullPage: true,
      })

      for (const step of TAB_STEPS[surface.key] ?? []) {
        const tab = p.getByRole("tab", { name: step.tab })
        if (await tab.count()) {
          await tab.first().click()
          await p.waitForTimeout(600)
          record[step.key] = await probe(p)
          await p.screenshot({
            path: join(OUT, `${step.key}-${vp.key}.png`),
            fullPage: true,
          })
        } else {
          record[step.key] = { missingTab: step.tab }
        }
      }
    } catch (error) {
      record.failure = String(error).slice(0, 400)
    }
    record.consoleErrors = errs.slice(0, 10)
    results.push(record)
    console.log(
      `${vp.key.padEnd(9)} ${surface.key.padEnd(11)} ${
        record.failure
          ? "FAILED"
          : `sideways=${record.main?.sideways} unnamed=${record.main?.unnamedCount} overflow=${record.main?.overflowCount} h1=${record.main?.h1s?.length}`
      }`
    )
    await vctx.close()
    // The API allows 60 requests a minute per identity, and a single console
    // screen costs several. Pacing here is what makes the sweep finish instead
    // of tripping the limit and recording a 429 as a screen defect.
    await new Promise((r) =>
      setTimeout(r, Number(process.env.WS41_PACE ?? 1500))
    )
  }
}

await browser.close()
writeFileSync(join(OUT, "audit.json"), JSON.stringify(results, null, 2))

// ---- the summary an operator reads ---------------------------------------
const problems = []
for (const r of results) {
  const where = `${r.surface} @ ${r.viewport}`
  if (r.failure)
    problems.push(`${where}: navigation/assertion failed — ${r.failure}`)
  for (const [label, m] of Object.entries(r)) {
    if (!m || typeof m !== "object" || !("scrollWidth" in m)) continue
    if (m.sideways)
      problems.push(
        `${where}${label === "main" ? "" : ` (${label})`}: sideways scroll ${m.scrollWidth} > ${m.clientWidth}`
      )
    if (m.overflowCount > 0)
      problems.push(
        `${where}${label === "main" ? "" : ` (${label})`}: ${m.overflowCount} element(s) outside the viewport, first=${m.overflow[0]?.tag}.${m.overflow[0]?.cls}`
      )
    if (m.unnamedCount > 0)
      problems.push(
        `${where}${label === "main" ? "" : ` (${label})`}: ${m.unnamedCount} unnamed control(s), first=${JSON.stringify(m.unnamed[0])}`
      )
    if (m.h1s.length !== 1)
      problems.push(
        `${where}${label === "main" ? "" : ` (${label})`}: ${m.h1s.length} h1 element(s) ${JSON.stringify(m.h1s)}`
      )
    if (!m.hasMain)
      problems.push(
        `${where}${label === "main" ? "" : ` (${label})`}: no <main> landmark`
      )
  }
  if (r.consoleErrors?.length)
    problems.push(
      `${where}: ${r.consoleErrors.length} console error(s): ${r.consoleErrors[0]}`
    )
}

console.log(`\n${"=".repeat(70)}`)
console.log(`${results.length} surface/viewport combinations recorded → ${OUT}`)
console.log(`${problems.length} problem(s):\n`)
for (const line of problems) console.log(`  • ${line}`)
if (consoleErrors.length) {
  console.log(`\nSession console errors: ${consoleErrors.length}`)
  for (const e of consoleErrors.slice(0, 10)) console.log(`  • ${e}`)
}
process.exitCode = problems.length ? 1 : 0
