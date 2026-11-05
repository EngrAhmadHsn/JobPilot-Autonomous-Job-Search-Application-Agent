import { describe, expect, it } from "vitest"

/**
 * Every link inside the console must stay inside the console.
 *
 * The console lives under `/app`, and the public landing page is at `/`.
 * Moving the console under `/app` once broke every screen-to-screen link —
 * they still pointed at `/matches/...`, which fell through the catch-all to
 * the landing page. Nothing in the unit suite caught it, because each test
 * asserted what a screen *rendered*, not where its links *went*.
 *
 * This test closes that gap mechanically: it reads the screen and component
 * sources (Vite inlines them as raw text) and fails on any internal link
 * that is not `/`, `/sign-in`, or under `/app`. It is the frontend echo of
 * the backend's route/README check — a rule a careless edit cannot quietly
 * break.
 */

const SOURCES = import.meta.glob("../**/*.tsx", {
  query: "?raw",
  import: "default",
  eager: true,
}) as Record<string, string>

/** The only destinations that may sit outside `/app`. */
const PUBLIC_PATHS = ["/", "/sign-in"]

/** A `to="..."`, `to={`...`}` or `navigate("...")` target. */
const LINK_PATTERNS = [
  /to="([^"]*)"/g,
  /to=\{`([^`]*)`\}/g,
  /navigate\("([^"]*)"\)/g,
  /navigate\(`([^`]*)`\)/g,
]

function isAllowed(target: string): boolean {
  if (!target.startsWith("/")) return true // an external URL or a hash
  if (PUBLIC_PATHS.includes(target)) return true
  return target === "/app" || target.startsWith("/app/")
}

describe("console navigation", () => {
  it("keeps every internal link under /app (or a public path)", () => {
    const offenders: string[] = []
    for (const [file, text] of Object.entries(SOURCES)) {
      if (file.endsWith(".test.tsx")) continue
      for (const pattern of LINK_PATTERNS) {
        for (const match of text.matchAll(pattern)) {
          const target = match[1] ?? ""
          if (!isAllowed(target)) {
            offenders.push(`${file.replace("../", "")} → ${target}`)
          }
        }
      }
    }
    expect(offenders, offenders.join("\n")).toEqual([])
  })
})
