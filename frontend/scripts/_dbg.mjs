import { chromium } from "playwright"
const B = "http://localhost:5191"
const browser = await chromium.launch()
const ctx = await browser.newContext({
  viewport: { width: 1440, height: 1000 },
})
const p = await ctx.newPage()
await p.goto(`${B}/sign-in`, { waitUntil: "networkidle" })
await p.getByLabel(/e-?mail/i).fill("operator@example.com")
await p.getByLabel(/password/i).fill("operator-local-password")
await p.getByRole("button", { name: /sign in|log in/i }).click()
await p.waitForURL(/\/app/, { timeout: 60000 })
await p.goto(`${B}/app`, { waitUntil: "networkidle" })
await p.waitForTimeout(1200)
const info = await p.evaluate(() => {
  const aside = document.querySelector("aside#app-rail")
  const asides = [...document.querySelectorAll("aside")].map((a) => ({
    id: a.id,
    cls: a.className.slice(0, 90),
    disp: getComputedStyle(a).display,
    w: getComputedStyle(a).width,
  }))
  if (!aside) return { found: false, asides }
  const cs = getComputedStyle(aside)
  const r = aside.getBoundingClientRect()
  return {
    found: true,
    display: cs.display,
    position: cs.position,
    width: cs.width,
    bg: cs.backgroundColor,
    rect: { x: r.x, y: r.y, w: r.width, h: r.height },
    cls: aside.className.slice(0, 200),
    asides,
  }
})
console.log(JSON.stringify(info, null, 1))
await browser.close()
