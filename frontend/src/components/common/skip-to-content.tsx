/**
 * The first focusable element on a page: a way past the chrome.
 *
 * Both surfaces put a lot in front of their content. The landing page has a
 * sticky header with three section links, a motion control and a sign-in
 * button; the console has a header, a nav row and an account menu. A keyboard
 * user had to tab through all of it on every route change to reach the page
 * they came for, which is what WCAG 2.4.1 (Bypass Blocks) is about.
 *
 * It is visually hidden until focused, then becomes an ordinary button in the
 * top-left corner. `sr-only` plus `focus:not-sr-only` is the standard pattern:
 * the element stays in the tab order and announces its name, but takes no
 * space until a keyboard user summons it. A pointer user never sees it.
 *
 * It targets `#main-content`, which both surfaces put on their content
 * container (the landing page's `<main>` and the console's `<main>`). The
 * `scroll-mt` on that target is what keeps the heading clear of the sticky
 * header, so the jump lands on visible content rather than under the chrome.
 */
export function SkipToContent() {
  return (
    <a
      href="#main-content"
      className="sr-only rounded-lg bg-lime px-4 py-2.5 text-sm font-semibold text-lime-foreground focus:not-sr-only focus:absolute focus:top-3 focus:left-3 focus:z-50"
    >
      Skip to content
    </a>
  )
}
