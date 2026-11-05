import { useEffect, useState } from "react"

/**
 * Subscribe to a media query, SSR- and test-safely.
 *
 * `window.matchMedia` is absent in the Node test environment, and a
 * component must still render there: the query then answers `false`, which
 * is the conservative choice — false disables the intensive effect rather
 * than assuming the visitor wants it.
 */
export function useMediaQuery(query: string): boolean {
  const [matches, setMatches] = useState(() => {
    if (typeof window === "undefined" || !window.matchMedia) return false
    return window.matchMedia(query).matches
  })

  useEffect(() => {
    if (typeof window === "undefined" || !window.matchMedia) return
    const list = window.matchMedia(query)
    const onChange = () => setMatches(list.matches)
    onChange()
    list.addEventListener("change", onChange)
    return () => list.removeEventListener("change", onChange)
  }, [query])

  return matches
}

/** True when the visitor asked for less motion. */
export function useReducedMotion(): boolean {
  return useMediaQuery("(prefers-reduced-motion: reduce)")
}

/**
 * True when the device has a real pointer available.
 *
 * The light field follows a cursor, so on a device that only has a touch
 * screen it has nothing to follow and would either sit still or run a
 * needless render loop.
 *
 * **`any-pointer` and `any-hover`, not `pointer` and `hover`.** The
 * `pointer`/`hover` queries describe the device's **primary** input. On a
 * touchscreen laptop the primary input can be reported as `coarse` (touch)
 * even while the visitor is using the trackpad — and the effect would switch
 * itself off on exactly the machines that have a mouse. The `any-` variants
 * ask the right question: "is a fine, hovering pointer available at all?".
 * That is true on a touchscreen laptop (it has a trackpad) and false on a
 * phone or a tablet, which is precisely the split we want.
 */
export function usePointerCapable(): boolean {
  return useMediaQuery("(any-hover: hover) and (any-pointer: fine)")
}
