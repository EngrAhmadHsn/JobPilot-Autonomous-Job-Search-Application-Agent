import { useRef } from "react"
import { cn } from "cn"

import { PlainText } from "@/components/common/plain-text"
import { RelativeTime } from "@/components/common/relative-time"
import { Button } from "@/components/ui/button"

import { formatScore } from "@/lib/format"
import type { JobMatchPair } from "@/lib/api/types"

/*
  The ranked results list of the Discover split view (WS-36).

  Dense rows at the reference's density: title, company, location, the
  date/source where the listing carries one, the real score chip, and up to
  three real skill chips (the listing's own required skills — what the board
  asks for, not a match claim). Every string the board supplied renders
  through `PlainText` or a chip that contains one: job-board content is
  untrusted text, never markup.

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
*/

/** The compact score pill for a dense row — the same lime chip, smaller. */
function RowScore({ value }: { value: number }) {
  return (
    <span
      className="inline-flex shrink-0 items-baseline gap-1 rounded-full bg-lime px-2 py-0.5 text-xs font-semibold text-lime-foreground tabular-nums"
      aria-label={`Match score ${formatScore(value)} out of 100`}
    >
      {formatScore(value)}
    </span>
  )
}

/** One real skill the listing asks for, as a quiet chip. */
function SkillChip({ children }: { children: string }) {
  return (
    <li className="inline-flex max-w-full items-center rounded-full border border-border bg-muted px-2 py-0.5 text-xs text-muted-foreground">
      <PlainText as="span" className="text-xs">
        {children}
      </PlainText>
    </li>
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
  onSelect: (jobId: string) => void
  refCallback: (element: HTMLButtonElement | null) => void
}) {
  const { job, match } = pair
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
        onClick={() => onSelect(job.id)}
        className={cn(
          "w-full rounded-xl border px-4 py-3 text-start transition-colors duration-150",
          selected
            ? "border-primary bg-accent"
            : "border-border bg-card hover:bg-accent/60"
        )}
      >
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0 flex-1">
            <PlainText
              as="span"
              className="block font-heading text-sm font-semibold wrap-anywhere text-foreground"
            >
              {job.title}
            </PlainText>
            <PlainText
              as="span"
              className="mt-0.5 block text-xs wrap-anywhere text-muted-foreground"
            >
              {job.company}
              {job.location ? ` · ${job.location}` : ""}
              {job.remote_policy ? ` · ${job.remote_policy}` : ""}
            </PlainText>
            <PlainText
              as="span"
              className="mt-0.5 block text-xs text-muted-foreground"
            >
              <span className="inline-flex min-w-0 flex-wrap items-center gap-x-1">
                {salary ? (
                  <span className="tabular-nums">{salary} · </span>
                ) : null}
                {freshness}
              </span>
            </PlainText>
          </div>
          <RowScore value={match.overall_score} />
        </div>
        {skills.length > 0 ? (
          <ul className="mt-2 flex flex-wrap gap-1.5">
            {skills.map((skill) => (
              <SkillChip key={skill}>{skill}</SkillChip>
            ))}
          </ul>
        ) : null}
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
  onSelect: (jobId: string) => void
  /** The window step, named in the control's label. */
  pageSize: number
}) {
  const rowRefs = useRef<Array<HTMLButtonElement | null>>([])
  const visible = pairs.slice(0, visibleCount)
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
    buttons[next]?.focus()
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
              pair.job.id === selectedId || (selectedId === null && index === 0)
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
