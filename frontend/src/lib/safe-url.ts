/**
 * Safe links.
 *
 * A job listing's `application_url` is board-supplied text: it comes from
 * a job board, it is not written by the operator, and it is rendered as a
 * **link** — the one place the console turns untrusted text into
 * something the browser acts on.
 *
 * A `javascript:` URL is the case that matters. React 19 blocks
 * `javascript:` in `href` as a defence of last resort, but relying on the
 * framework's own guard is relying on somebody else's decision; the
 * console checks the scheme itself, and the backend checks it again at the
 * contract (so a listing that arrives from a board never carries one).
 *
 * The other case — an ordinary `https://` link to a hostile board's
 * phishing page — is not a scheme problem and is not solved here. It is
 * solved by the operator seeing the full URL in the link text before
 * clicking it.
 */

/** The schemes a link may use. */
const SAFE_SCHEMES = new Set(["http:", "https:"])

/**
 * Drop the control characters a browser strips before it reads a scheme.
 *
 * A browser removes them from the URL, so "java<TAB>script:alert(1)"
 * navigates as `javascript:alert(1)`. The check has to see the same
 * string the browser would.
 */
function stripControlCharacters(value: string): string {
  let out = ""
  for (const character of value) {
    const code = character.codePointAt(0) ?? 0
    if (code <= 0x1f || code === 0x7f) continue
    out += character
  }
  return out
}

/**
 * True when *url* is safe to put in an `href`.
 *
 * A URL with no scheme is a relative reference: it opens a page on the
 * current origin and does nothing else, so it is allowed. Anything with
 * another scheme — `javascript:`, `data:`, `file:`, `blob:` — is refused.
 */
export function isSafeLinkUrl(url: string | null | undefined): boolean {
  if (!url) return false
  const candidate = url.trim()
  if (!candidate) return false
  const cleaned = stripControlCharacters(candidate)
  const match = /^([a-zA-Z][a-zA-Z0-9+.-]*):/.exec(cleaned)
  if (!match) {
    // No scheme at all: a relative reference, or a protocol-relative one.
    // A protocol-relative URL points at another host while looking like
    // a path, so it is refused.
    if (cleaned.startsWith("//")) return false
    return true
  }
  return SAFE_SCHEMES.has(`${(match[1] ?? "").toLowerCase()}:`)
}
