import { describe, expect, it } from "vitest"

import { isSafeLinkUrl } from "@/lib/safe-url"

/**
 * WS-15: a listing's `application_url` is board-supplied, and it is the
 * one place the console turns untrusted text into something the browser
 * acts on. The backend enforces the same rule at the contract; these are
 * the console's own tests of its own half.
 */
describe("safe links", () => {
  it("allows the schemes a browser may follow", () => {
    expect(isSafeLinkUrl("https://boards.greenhouse.io/acme/jobs/1")).toBe(true)
    expect(isSafeLinkUrl("http://127.0.0.1:8901/jobs/1")).toBe(true)
    expect(isSafeLinkUrl("HTTPS://EXAMPLE.COM/x")).toBe(true)
  })

  it("refuses a javascript: URL", () => {
    expect(isSafeLinkUrl("javascript:alert(1)")).toBe(false)
    expect(isSafeLinkUrl("JavaScript:alert(1)")).toBe(false)
    expect(isSafeLinkUrl("  javascript:alert(1)  ")).toBe(false)
  })

  it("refuses the other schemes that do something other than open a page", () => {
    expect(isSafeLinkUrl("data:text/html,<script>alert(1)</script>")).toBe(
      false
    )
    expect(isSafeLinkUrl("file:///etc/passwd")).toBe(false)
    expect(isSafeLinkUrl("blob:https://example.com/abc")).toBe(false)
    expect(isSafeLinkUrl("vbscript:msgbox(1)")).toBe(false)
  })

  it("sees through the control characters a browser strips", () => {
    // A browser removes the tab before it reads the scheme, so this
    // navigates as javascript:alert(1). The characters are built at
    // runtime so this file stays plain ASCII.
    const tab = String.fromCharCode(9)
    const newline = String.fromCharCode(10)
    const nul = String.fromCharCode(0)
    expect(isSafeLinkUrl(`java${tab}script:alert(1)`)).toBe(false)
    expect(isSafeLinkUrl(`java${newline}script:alert(1)`)).toBe(false)
    expect(isSafeLinkUrl(`java${nul}script:alert(1)`)).toBe(false)
  })

  it("refuses a protocol-relative URL, which points at another host", () => {
    expect(isSafeLinkUrl("//evil.example/jobs/1")).toBe(false)
  })

  it("allows a relative reference, which opens a page on this origin", () => {
    expect(isSafeLinkUrl("/jobs/1")).toBe(true)
    expect(isSafeLinkUrl("jobs/1")).toBe(true)
  })

  it("refuses nothing at all", () => {
    expect(isSafeLinkUrl("")).toBe(false)
    expect(isSafeLinkUrl("   ")).toBe(false)
    expect(isSafeLinkUrl(null)).toBe(false)
    expect(isSafeLinkUrl(undefined)).toBe(false)
  })
})
