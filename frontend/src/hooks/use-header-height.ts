import { useEffect, type RefObject } from "react"

/**
 * Publish the header's height as a CSS variable.
 *
 * The header is sticky, so anything else that sticks has to clear it — and
 * the header's height is not a constant: the navigation wraps on a narrow
 * screen, and the account menu grows a line when it shows an address. A
 * hard-coded offset therefore cuts the top off a sticky panel on some
 * screens and not on others.
 *
 * The measurement is written to `--header-height` on the document element,
 * and the sticky panels read it. It is a measurement, not a state: nothing
 * re-renders because of it.
 */
export function useHeaderHeight(ref: RefObject<HTMLElement | null>) {
  useEffect(() => {
    const element = ref.current
    if (!element) return

    const apply = () => {
      const height = Math.round(element.getBoundingClientRect().height)
      document.documentElement.style.setProperty(
        "--header-height",
        `${height}px`
      )
    }

    apply()

    if (typeof ResizeObserver === "undefined") {
      window.addEventListener("resize", apply)
      return () => window.removeEventListener("resize", apply)
    }

    const observer = new ResizeObserver(apply)
    observer.observe(element)
    return () => observer.disconnect()
  }, [ref])
}
