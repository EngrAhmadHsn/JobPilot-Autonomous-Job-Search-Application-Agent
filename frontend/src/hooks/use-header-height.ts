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
export function useHeaderHeight(
  ref: RefObject<HTMLElement | null>,
  desktopRef: RefObject<HTMLElement | null>
) {
  useEffect(() => {
    const headers = [ref.current, desktopRef.current].filter(
      (element) => element !== null
    )
    const style = document.documentElement.style

    const apply = () => {
      // The inactive header is display:none, so only the visible one contributes.
      const height = Math.max(
        0,
        ...headers.map((header) => header.getBoundingClientRect().height)
      )
      if (height > 0) style.setProperty("--header-height", `${height}px`)
      else style.removeProperty("--header-height")
    }

    apply()

    if (typeof ResizeObserver === "undefined") {
      window.addEventListener("resize", apply)
      return () => {
        window.removeEventListener("resize", apply)
        style.removeProperty("--header-height")
      }
    }

    const observer = new ResizeObserver(apply)
    headers.forEach((header) => observer.observe(header))
    return () => {
      observer.disconnect()
      style.removeProperty("--header-height")
    }
  }, [ref, desktopRef])
}
