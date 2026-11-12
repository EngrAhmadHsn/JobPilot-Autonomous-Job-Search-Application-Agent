import { useEffect } from "react"

/**
 * Set the browser tab's title for the screen that is showing.
 *
 * A client-rendered app has one document, so without this every route keeps the
 * `<title>` that `index.html` shipped with. Three things break when that
 * happens: a screen reader announces the same name after every navigation, a
 * person with several console tabs open cannot tell them apart, and the public
 * page is indexed under the wrong name.
 *
 * The title is restored to the document's original on unmount so a screen
 * without a call of its own never inherits a stale name.
 *
 * The suffix is the product, not the route: "JobPilot" is what the tab should
 * say, and the screen name is what distinguishes one tab from another.
 */
export function useDocumentTitle(title: string) {
  useEffect(() => {
    const previous = document.title
    document.title = `${title} · JobPilot`
    return () => {
      document.title = previous
    }
  }, [title])
}
