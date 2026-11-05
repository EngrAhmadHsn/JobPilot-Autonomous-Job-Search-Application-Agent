// One-off recon: visit the brief's reference sites in a real browser and
// record what is actually observable (or not). Output goes to refs-out/.
import { chromium } from "playwright"
import { mkdirSync } from "node:fs"
import { fileURLToPath } from "node:url"
import { join } from "node:path"

const OUT = fileURLToPath(new URL("../refs-out/", import.meta.url))
mkdirSync(OUT, { recursive: true })
const out = (n) => join(OUT, n)

const browser = await chromium.launch()
const ctx = await browser.newContext({
  viewport: { width: 1440, height: 900 },
  userAgent:
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36",
})

const results = []

async function visit(name, url, action) {
  const page = await ctx.newPage()
  const record = { name, url, ok: false, notes: [] }
  try {
    await page.goto(url, { waitUntil: "domcontentloaded", timeout: 30000 })
    await page.waitForTimeout(4000)
    if (action) await action(page, record)
    await page.screenshot({ path: out(`${name}.png`), fullPage: false })
    record.ok = true
    record.title = await page.title()
  } catch (err) {
    record.notes.push(`FAILED: ${err.message}`)
  } finally {
    await page.close()
  }
  results.push(record)
}

await visit("formless", "https://formless.xyz/", async (page, r) => {
  const info = await page.evaluate(() => {
    const canvases = [...document.querySelectorAll("canvas")].map((c) => ({
      w: c.width,
      h: c.height,
      cls: c.className,
    }))
    const body = getComputedStyle(document.body)
    return {
      canvasCount: canvases.length,
      canvases,
      bodyBackground: body.backgroundColor,
      bodyBackgroundImage: body.backgroundImage.slice(0, 200),
      fonts: [...new Set([...document.querySelectorAll("h1,h2,p")].map((e) => getComputedStyle(e).fontFamily))].slice(0, 6),
      h1: document.querySelector("h1")?.textContent?.trim() ?? null,
      textSample: document.body.innerText.slice(0, 400),
    }
  })
  Object.assign(r, info)
})

await visit("agencly", "https://agencly.app/", async (page, r) => {
  const info = await page.evaluate(() => ({
    h1: document.querySelector("h1")?.textContent?.trim() ?? null,
    sections: [...document.querySelectorAll("section")].slice(0, 12).map((s) =>
      (s.textContent || "").replace(/\s+/g, " ").trim().slice(0, 90)
    ),
  }))
  Object.assign(r, info)
  // Try to click a demo module if present.
  const btn = page.getByText(/click any module/i).first()
  if (await btn.count()) r.notes.push("found 'click any module' hint")
})

await visit("yt1", "https://www.youtube.com/watch?v=Fog8WpdTnYU", async (page, r) => {
  r.desc = await page
    .locator('meta[name="description"]')
    .getAttribute("content")
    .catch(() => null)
  const t = await page.title()
  r.notes.push(`title=${t}`)
})

await visit("yt2", "https://www.youtube.com/watch?v=pbhLsV-Dyho", async (page, r) => {
  r.desc = await page
    .locator('meta[name="description"]')
    .getAttribute("content")
    .catch(() => null)
  const t = await page.title()
  r.notes.push(`title=${t}`)
})

await visit("fb1", "https://www.facebook.com/share/r/1HhjPLqoRj/", async (page, r) => {
  r.text = (await page.locator("body").innerText().catch(() => "")).slice(0, 300)
})

await visit("fb2", "https://www.facebook.com/reel/1146520814389665", async (page, r) => {
  r.text = (await page.locator("body").innerText().catch(() => "")).slice(0, 300)
})

await browser.close()
console.log(JSON.stringify(results, null, 2))
