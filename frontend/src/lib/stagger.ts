import { cn } from "cn"
import type { CSSProperties } from "react"

/**
 * The props that make one item of a list arrive after the one above it.
 *
 * The delay is the item's **index** times a step, which is the same idea an
 * After Effects expression uses when it staggers by `index`: the list
 * arrives in order instead of all at once, and the operator's eye is
 * led down it.
 *
 * The step is small on purpose — 45 ms. A list of twenty rows must not
 * take a second to arrive; the stagger should be felt, not waited for.
 */
export function stagger(
  index: number,
  className?: string
): {
  className: string
  style: CSSProperties
} {
  return {
    className: cn("enter-up", className),
    style: { "--i": index } as CSSProperties,
  }
}
