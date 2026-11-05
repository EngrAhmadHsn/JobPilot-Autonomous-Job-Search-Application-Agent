import { useEffect, useRef } from "react"

/**
 * Reveal a block's marked descendants once, as they scroll into view.
 *
 * The wrapper is given to this hook; every descendant carrying a
 * `data-reveal` attribute is revealed individually, each with its own
 * index-based delay (the `--i` custom property the caller sets inline).
 *
 * The hidden state is applied **by this hook, after mount**, and only when
 * an `IntersectionObserver` exists. That ordering is the important part: in
 * a browser without the observer — or with scripting off, or in the jsdom
 * test environment — the attribute is never set and the content simply
 * shows. Content that is invisible until JavaScript runs is content that is
 * sometimes not there.
 *
 * Each target is unobserved once it has fired: the reveal is one-way, so it
 * never re-animates and never thrashes on scroll.
 */
export function useReveal<T extends HTMLElement = HTMLDivElement>() {
  const ref = useRef<T | null>(null)

  useEffect(() => {
    const root = ref.current
    if (!root) return
    if (typeof IntersectionObserver === "undefined") return

    const targets = [
      ...(root.hasAttribute("data-reveal") ? [root] : []),
      ...Array.from(root.querySelectorAll<HTMLElement>("[data-reveal]")),
    ]
    if (targets.length === 0) return

    for (const target of targets) target.setAttribute("data-reveal", "pending")

    const observer = new IntersectionObserver(
      (entries) => {
        for (const entry of entries) {
          if (!entry.isIntersecting) continue
          entry.target.setAttribute("data-reveal", "in")
          observer.unobserve(entry.target)
        }
      },
      { rootMargin: "0px 0px -8% 0px", threshold: 0.12 }
    )
    for (const target of targets) observer.observe(target)
    return () => observer.disconnect()
  }, [])

  return ref
}
