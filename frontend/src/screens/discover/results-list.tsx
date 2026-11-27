import { useRef } from "react"
import { cn } from "cn"
import { motion } from "motion/react"
import {
  motionTokens,
  useTempoTransition,
} from "@animate-ui/react/utils/motion"

import { PlainText } from "@/components/common/plain-text"
import { RelativeTime } from "@/components/common/relative-time"
import { Button } from "@/components/ui/button"

import type { JobMatchPair } from "@/lib/api/types"

/*
  The ranked results list of the Discover split view, at the design's row
  anatomy (WS-42, node `49:887`): a 16/600/23 title with the score chip on
  its trailing edge, a 12/400/17 company · location line, the required
  skills as **plain dot-joined text** (what the board asks for, not a match
  claim — the design draws "Python · FastAPI", not chips), a "View →"
  affordance, and a thin score bar along the bottom (track sage, value
  #8ea758 — the ruler green, not the agent's lime). The selected row wears
  the sage wash (#e6ece8, node `49:875`); its chip pops lime while the
  unselected rows' chips stay sage.

  The chip carries the **whole** score ("86", node `49:878`) — a rounded
  display form, never a decimal. The full precision stays with the
  breakdown in the detail panel.

  Every string the board supplied renders through `PlainText`: job-board
  content is untrusted text, never markup.

  The `wrap-anywhere` utility on the wrapping lines is deliberate and
  measured: `break-words` maps to `overflow-wrap: break-word`, which breaks
  text only *after* the box has already sized itself to the longest token —
  a 69-character title measured 425 px inside a 311 px card and clipped.
  `wrap-anywhere` (`overflow-wrap: anywhere`) also affects min-content
  sizing, so the box shrinks and the token breaks inside it. Do not regress
  these lines to `break-words`.

  Keyboard model: each row is a real `<button>`; the list is one tab stop
  (roving tabindex — the selected row, or the first row when nothing is
  selected), and ArrowUp/ArrowDown/Home/End move the focus between rows
  without moving the selection. Enter or Space activates the focused row,
  which is the button's own behaviour.

  Pagination: the server has already returned the whole ranked slice (up to
  Top N), so the "Show more" control extends the client-side window — it
  never implies another server page. The count line above the list states
  the honest total; the slice-at-cap wording lives with it.

  Selection (WS-48): the sage wash is an **absolutely positioned layer under
  the row's content**, not a background class that changes — so it fades in
  and out on `transition.fade` instead of snapping. It is a layer rather
  than a `layoutId` highlight because the row is a hot path: a `layoutId`
  move is projected on the main thread over rows whose heights the board
  supplies, and a scroll-full of those is exactly where main-thread work
  must not go. Opacity is compositor-only and the row's geometry never
  changes, so keyboard focus and the roving tabindex stay instant.
*/

/**
 * The row's score chip, as the design draws it (nodes `49:878` / `49:890`):
 * a 24px r6 chip carrying the whole score, 11/600/16. The selected row's
 * chip wears the agent's lime (`#eef9c4`); unselected rows keep the quiet
 * sage (`#e6ece8`) — the same number, quieter clothes.
 */
function RowScore({ value, selected }: { value: number; selected: boolean }) {
  const whole = String(Math.round(value))
  return (
    <span
      className={cn(
        "inline-flex h-6 shrink-0 items-center rounded-[6px] px-[9px] text-[11px] leading-4 font-semibold text-lime-foreground tabular-nums transition-colors duration-150",
        selected ? "bg-lime-soft" : "bg-forest-soft"
      )}
      aria-label={`Match score ${whole} out of 100`}
    >
      {whole}
    </span>
  )
}

function ResultRow({
  pair,
  selected,
  tabbable,
  onSelect,
  refCallback,
}: {
  pair: JobMatchPair
  selected: boolean
  tabbable: boolean
  onSelect: (jobId: string, trigger: HTMLButtonElement) => void
  refCallback: (element: HTMLButtonElement | null) => void
}) {
  const { job, match } = pair
  // The wash eases rather than snaps, on the library's own fade timing and
  // through the tempo, so a slower motion setting slows it too.
  const wash = useTempoTransition(motionTokens.transition.fade)
  // The date the listing carries, or the board it came from — one of the
  // two is always known; neither is invented.
  const freshness = job.posted_at ? (
    <RelativeTime value={job.posted_at} />
  ) : (
    job.source
  )
  const salary = job.salary
    ? `${job.salary}${job.currency ? ` ${job.currency}` : ""}`
    : null
  const skills = job.required_skills.slice(0, 3)

  return (
    <li className="min-w-0">
      <button
        type="button"
        ref={refCallback}
        tabIndex={tabbable ? 0 : -1}
        aria-current={selected || undefined}
        onClick={(event) => onSelect(job.id, event.currentTarget)}
        className={cn(
          "relative isolate w-full space-y-2 rounded-[var(--radius-surface)] border bg-card p-4 text-start transition-colors duration-150",
          selected
            ? "border-transparent"
            : "border-border-surface hover:bg-accent/50"
        )}
      >
        {/*
          The selected row's sage wash (design node `49:875`, #e6ece8).
          Painted under the row's own background and above its border —
          negative z-index children draw over the element's background and
          border in the CSS painting order, which is why `isolate` is here:
          it keeps the layer inside this row's stacking context instead of
          falling behind the pane. `aria-hidden` because selection is
          already announced by `aria-current`.
        */}
        <motion.span
          aria-hidden="true"
          className="pointer-events-none absolute inset-0 -z-10 rounded-[var(--radius-surface)] bg-forest-soft"
          initial={false}
          animate={{ opacity: selected ? 1 : 0, transition: wash }}
        />
        {/*
          The design's row anatomy (node 49:875/49:887): the title with the
          score chip on its trailing edge, then company · location, then the
          skills as plain dot-joined text beside the "View →" affordance,
          then a thin score bar along the bottom. The bar is a *second
          rendering* of the same number the chip carries, never a different
          one.
        */}
        <div className="flex items-start justify-between gap-3">
          <PlainText
            as="span"
            className="min-w-0 flex-1 text-[16px] leading-[23px] font-semibold wrap-anywhere text-forest"
          >
            {job.title}
          </PlainText>
          <RowScore value={match.overall_score} selected={selected} />
        </div>
        <PlainText
          as="span"
          className="block text-xs leading-[17px] wrap-anywhere text-muted-foreground"
        >
          {job.company}
          {job.location ? ` · ${job.location}` : ""}
          {job.remote_policy ? ` · ${job.remote_policy}` : ""}
        </PlainText>
        <div className="flex items-end justify-between gap-3">
          <div className="min-w-0 flex-1">
            {skills.length > 0 ? (
              <PlainText
                as="span"
                className="block text-xs leading-[17px] wrap-anywhere text-muted-foreground"
              >
                {skills.join(" · ")}
              </PlainText>
            ) : (
              <PlainText
                as="span"
                className="block text-xs leading-[17px] text-muted-foreground"
              >
                {salary ? `${salary} · ` : ""}
                {freshness}
              </PlainText>
            )}
          </div>
          <span className="shrink-0 text-[13px] leading-[19px] font-semibold text-forest">
            View →
          </span>
        </div>
        {/*
          The score bar, as the design draws it (nodes `49:897`/`49:898`): a
          6px sage track with the ruler-green value (`#8ea758`, the
          `--color-progress-required` token — the agent's lime stays reserved
          for the agent's own marks). `aria-hidden` because the chip above
          already names the number; a screen reader would otherwise hear the
          same fact twice.
        */}
        <div
          aria-hidden="true"
          className="h-1.5 w-full overflow-hidden rounded-[3px] bg-forest-soft"
        >
          <div
            className="h-full rounded-[3px] bg-progress-required"
            style={{
              width: `${Math.max(0, Math.min(100, match.overall_score))}%`,
            }}
          />
        </div>
      </button>
    </li>
  )
}

export function ResultsList({
  pairs,
  visibleCount,
  onShowMore,
  selectedId,
  onSelect,
  pageSize,
}: {
  pairs: JobMatchPair[]
  /** How many rows of the already-loaded slice are on screen. */
  visibleCount: number
  /** Extend the window by the caller's page size. */
  onShowMore: () => void
  selectedId: string | null
  onSelect: (jobId: string, trigger: HTMLButtonElement) => void
  /** The window step, named in the control's label. */
  pageSize: number
}) {
  const rowRefs = useRef<Array<HTMLButtonElement | null>>([])
  const visible = pairs.slice(0, visibleCount)
  const hasVisibleSelection = visible.some(({ job }) => job.id === selectedId)
  const remaining = pairs.length - visible.length

  function handleKeyDown(event: React.KeyboardEvent<HTMLUListElement>) {
    if (
      event.key !== "ArrowDown" &&
      event.key !== "ArrowUp" &&
      event.key !== "Home" &&
      event.key !== "End"
    ) {
      return
    }
    const buttons = rowRefs.current.filter(
      (element): element is HTMLButtonElement => element !== null
    )
    if (buttons.length === 0) return
    event.preventDefault()
    const current = buttons.indexOf(document.activeElement as HTMLButtonElement)
    let next: number
    if (event.key === "ArrowDown") {
      next = current < 0 ? 0 : Math.min(current + 1, buttons.length - 1)
    } else if (event.key === "ArrowUp") {
      next = current < 0 ? 0 : Math.max(current - 1, 0)
    } else if (event.key === "Home") {
      next = 0
    } else {
      next = buttons.length - 1
    }
    // Keep the ring in view with the smallest possible scroll in either layout.
    buttons[next]?.focus({ preventScroll: true })
    buttons[next]?.scrollIntoView({ block: "nearest" })
  }

  return (
    <div className="space-y-3">
      <ul
        aria-label="Ranked matches"
        onKeyDown={handleKeyDown}
        className="space-y-2.5"
      >
        {visible.map((pair, index) => (
          <ResultRow
            key={pair.job.id}
            pair={pair}
            selected={pair.job.id === selectedId}
            tabbable={
              pair.job.id === selectedId ||
              (!hasVisibleSelection && index === 0)
            }
            onSelect={onSelect}
            refCallback={(element) => {
              rowRefs.current[index] = element
            }}
          />
        ))}
      </ul>
      {remaining > 0 ? (
        <Button type="button" variant="outline" size="sm" onClick={onShowMore}>
          Show {Math.min(remaining, pageSize)} more
        </Button>
      ) : null}
    </div>
  )
}
