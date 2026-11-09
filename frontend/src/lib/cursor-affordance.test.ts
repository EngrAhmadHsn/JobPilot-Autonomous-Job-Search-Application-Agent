/// <reference types="node" />
import { readFileSync } from "node:fs"
import { resolve } from "node:path"
import { describe, expect, it } from "vitest"

/**
 * Interactive controls must show the pointer cursor.
 *
 * Tailwind v4's preflight dropped the `cursor: pointer` that v3 applied to
 * `<button>`, leaving the browser default — an arrow. Every button in the
 * console therefore stopped reading as clickable, across every screen at once
 * and with no error to notice. The fix is one rule in the base layer of
 * `src/index.css`; this test is what stops a future Tailwind upgrade (or a
 * careless edit of that file) from silently undoing it.
 *
 * It reads the stylesheet as **text** rather than computing a rendered style,
 * because jsdom does not resolve `@layer`/`@apply` — a computed style would
 * assert nothing. `?raw` imports return empty for CSS under this config, so
 * the file is read from disk, which is also the honest thing to check: the
 * rule has to exist in the source the build consumes.
 */

// Vitest runs with the package root as cwd, so `src/index.css` is stable
// regardless of which file imports this module.
const raw = readFileSync(resolve(process.cwd(), "src/index.css"), "utf-8")

// Comments are stripped first, and it matters: this file's own comment
// explains the rule *by naming it* ("the `cursor: pointer` that v3 applied"),
// so a matcher that reads the raw text would find that sentence and pass no
// matter what the declarations say. The check has to see code, not prose.
const stylesheet = raw.replace(/\/\*[\s\S]*?\*\//g, "")

/** The first `cursor: pointer` rule whose selector list contains *needle*. */
function ruleMentioning(needle: string): string {
  // A rule is `<selector list> { ... }`; scan them all and keep the one whose
  // selector list mentions the needle and whose body sets the pointer cursor.
  const rules = stylesheet.match(/[^{}]+\{[^}]*\}/gs) ?? []
  return (
    rules.find(
      (rule) => (rule.split("{")[0] ?? "").includes(needle) && /cursor:\s*pointer/.test(rule)
    ) ?? ""
  )
}

describe("the console's pointer affordance", () => {
  it("gives buttons the pointer cursor", () => {
    expect(ruleMentioning("button")).not.toBe("")
  })

  it("does not advertise a pointer on disabled controls", () => {
    // A disabled button that shows a pointer is a control offering a click
    // it will refuse.
    expect(ruleMentioning("button")).toContain(":not(:disabled)")
  })

  it("covers the other interactive and role-based controls", () => {
    // Base UI renders some controls as a non-<button> element with
    // `role="button"`; `<select>`, checkboxes and radios are interactive
    // without being buttons at all.
    for (const selector of ['[role="button"]', "select", 'input[type="checkbox"]']) {
      expect(ruleMentioning(selector), `${selector} should get the pointer cursor`).not.toBe(
        ""
      )
    }
  })
})