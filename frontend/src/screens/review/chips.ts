/**
 * The wash-chip look shared across the Review screen's cards (WS-42/45).
 *
 * The four tints are the screen's whole vocabulary: the sage wash marks
 * position and the agent's confirmed sources, the clay wash marks a human's
 * attention ("Required", "needs a human"), the solid forest chip is the
 * queue's live count, and the outlined chip is a quiet count. Living in one
 * module is what keeps the answering card and the read-only queue reading
 * as one surface.
 */

/** Sage wash — position chips and the agent's confirmed answer sources. */
export const SAGE_CHIP =
  "inline-flex items-center rounded-[6px] bg-forest-soft px-2.5 py-1 text-[11px] font-semibold leading-4 text-primary"

/** Clay wash — a human's attention: "Required", "needs a human". */
export const CLAY_CHIP =
  "inline-flex items-center rounded-[6px] bg-terracotta-soft px-2.5 py-1 text-[11px] font-semibold leading-4 text-terracotta-foreground"

/** Solid forest — the live count ("Needs you n") that wants the operator's eye. */
export const FOREST_CHIP =
  "inline-flex items-center rounded-[6px] bg-primary px-2.5 py-1 text-[11px] font-semibold leading-4 text-primary-foreground"

/** Outlined — the quiet count ("Confirmed n") and every other stat. */
export const OUTLINE_CHIP =
  "inline-flex items-center rounded-[6px] border border-border-surface bg-card px-2.5 py-1 text-[11px] font-semibold leading-4 text-primary"
