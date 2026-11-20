import { FileText, TriangleAlert } from "lucide-react"
import type { LucideIcon } from "lucide-react"
import type { ReactNode } from "react"
import { Link } from "react-router-dom"
import { cn } from "cn"

import { PlainText } from "@/components/common/plain-text"
import { Button } from "@/components/ui/button"

/*
  The Home screen's presentation pieces, from the design file's node `16:2`.

  Each one takes **already-resolved, already-honest** data. None of them
  invents a number, a trend or a colour: the caller decides what is true and
  these components decide how it reads. That split is the reason the screen
  can say "server total" and mean it.
*/

/**
 * The next-step hero (node `49:757`).
 *
 * The design puts this first: a clay wash, an eyebrow saying what kind of
 * thing this is, a statement of what is nearly ready, the job it concerns,
 * and one sentence of consequence. The primary action and an attention chip
 * sit on one row beneath.
 *
 * It renders **only when there is a real next step**. An "all clear" hero
 * would be a decorative block pretending to be information, so the caller
 * renders nothing in that case and the page leads with the work.
 */
export function NextStepPanel({
  eyebrow = "Your next step",
  statement,
  subject,
  consequence,
  action,
  chip,
}: {
  eyebrow?: string
  statement: string
  subject: ReactNode
  consequence: ReactNode
  action: ReactNode
  /** A short count or status chip beside the action. */
  chip?: ReactNode
}) {
  return (
    <div className="flex flex-col gap-3.5 rounded-[var(--radius-surface)] bg-terracotta-soft p-6">
      <p className="type-eyebrow text-forest">{eyebrow}</p>
      <p className="type-statement">{statement}</p>
      <p className="type-card-title">{subject}</p>
      <p className="text-sm leading-5 text-muted-foreground">{consequence}</p>
      <div className="flex flex-wrap items-center gap-3">
        {action}
        {/*
          The design's chip sits on the panel's own clay wash — it is an
          eyebrow with padding, not a filled pill (node 49:767).
        */}
        {chip ? (
          <span className="type-eyebrow rounded-md px-2 py-1 text-forest">
            {chip}
          </span>
        ) : undefined}
      </div>
    </div>
  )
}

/**
 * A metric tile (node `49:774`).
 *
 * Deliberately small: a value, a label, and nothing else. The design draws
 * four of these in a row, and the value is the only emphasis — no icons, no
 * deltas, no sparklines. A tile whose number the caller cannot source must
 * not render at all (which is why `value` accepts `undefined` and renders an
 * em dash rather than a zero).
 *
 * `data-stat-card` is the hook the Home tests use to scope a label to its own
 * tile — the labels repeat in the pipeline legend, so a bare text query would
 * match twice.
 */
export function MetricTile({
  value,
  label,
  loading,
  footer,
  className,
}: {
  value: ReactNode
  label: ReactNode
  loading?: boolean
  /** An optional provenance line under the label. */
  footer?: ReactNode
  className?: string
}) {
  return (
    <div data-stat-card="" className={cn("surface p-4", className)}>
      {loading ? (
        <div className="skeleton h-[41px] w-12 rounded" />
      ) : (
        <p className="type-metric">{value}</p>
      )}
      <p className="type-caption mt-1">{label}</p>
      {footer ? <p className="type-caption mt-0.5">{footer}</p> : null}
    </div>
  )
}

/**
 * One row of the action queue (node `49:789`).
 *
 * An icon, a title with one line of why, and a trailing action. The whole
 * row is **not** a link: the action is the affordance, and making a large
 * clickable region that contains a smaller one is how a reader ends up
 * somewhere they did not choose. The title and body stay readable text.
 */
export function ActionRow({
  icon: Icon,
  title,
  body,
  action,
}: {
  icon: LucideIcon
  title: ReactNode
  body: ReactNode
  action: ReactNode
}) {
  return (
    <div className="flex items-center gap-3 py-2.5">
      <Icon
        aria-hidden="true"
        className="size-[18px] shrink-0 text-muted-foreground"
        strokeWidth={1.6}
      />
      <div className="min-w-0 flex-1">
        <p className="text-sm font-semibold text-foreground">{title}</p>
        <p className="text-xs leading-relaxed text-muted-foreground">{body}</p>
      </div>
      <div className="shrink-0">{action}</div>
    </div>
  )
}

/**
 * The pipeline distribution bar (node `49:1027`).
 *
 * Four segments whose widths are the real proportions of the tracked
 * applications by stage. **A stage with zero applications renders no
 * segment** — a zero-width sliver or a full-width empty track would read as
 * a stage that exists, and the design's own example is a corpus of five
 * applications across four stages.
 *
 * The design draws the segments **only**: 12 px tall, radius 4, 5 px gaps,
 * widths proportional to the counts. The names and counts are not lost with
 * a colour-only encoding — the four metric tiles directly above carry every
 * stage's name and count as text (the design's own pairing), the bar is a
 * labelled `role="img"`, and each segment carries its meaning in a tooltip.
 */
export interface PipelineSegment {
  key: string
  label: string
  count: number
  /** The token that fills the segment, e.g. `bg-stage-review`. */
  tone: string
}

const SEGMENT_FILLS: Record<string, string> = {
  review: "bg-[var(--color-stage-review)]",
  handoff: "bg-[var(--color-stage-handoff)]",
  progress: "bg-[var(--color-stage-progress)]",
  outcome: "bg-[var(--color-stage-outcome)]",
}

export function PipelineBar({
  segments,
  total,
  title,
  className,
}: {
  segments: PipelineSegment[]
  total: number
  title: ReactNode
  className?: string
}) {
  const shown = segments.filter((segment) => segment.count > 0)
  return (
    <div className={cn("surface px-5 py-3.5", className)}>
      <p className="text-[13px] font-semibold text-forest">{title}</p>
      {total > 0 ? (
        <div
          className="mt-3 flex h-3 gap-[5px]"
          role="img"
          aria-label={shown
            .map((segment) => `${segment.label}: ${segment.count}`)
            .join(", ")}
        >
          {shown.map((segment) => (
            <div
              key={segment.key}
              title={`${segment.label}: ${segment.count}`}
              className={cn(
                "rounded-[4px]",
                SEGMENT_FILLS[segment.key] ?? "bg-muted"
              )}
              style={{ flexGrow: segment.count, flexBasis: 0 }}
            />
          ))}
        </div>
      ) : (
        <p className="type-caption mt-2">Nothing tracked yet.</p>
      )}
    </div>
  )
}

/**
 * One entry of "while you were away" (node `49:810`).
 *
 * The actor chip is the console's colour law made visible: `Agent` is lime
 * because the agent did it, `You` is clay because a person did. There is a
 * **third** actor, `System`, and it is not a nicety: a step the platform
 * refused or blocked is not the agent's work — attributing a CAPTCHA stop to
 * the agent would blame it for obeying a safety rule. The same distinction
 * the full Activity trail makes is made here.
 *
 * The time is relative and comes from a real timestamp, never from a
 * sentence.
 */
export function DigestEntry({
  actor,
  at,
  title,
  detail,
  action,
}: {
  actor: "agent" | "human" | "system"
  at: ReactNode
  title: ReactNode
  detail: ReactNode
  action?: ReactNode
}) {
  const label =
    actor === "agent" ? "Agent" : actor === "human" ? "You" : "System"
  return (
    <div className="py-3.5">
      <div className="flex items-center gap-2.5">
        {/*
          The design's chips are the **soft washes** (node 49:811: lime-soft
          `#eef9c4`, terracotta-soft `#faeee6`), not the solid fills — the
          solid lime is reserved for the agent's *actions* (buttons, active
          nav). The third actor keeps the sage wash.
        */}
        <span
          className={cn(
            "type-eyebrow rounded-md px-2 py-1 uppercase",
            actor === "agent"
              ? "bg-lime-soft text-forest"
              : actor === "human"
                ? "bg-terracotta-soft text-terracotta-foreground"
                : "bg-forest-soft text-forest"
          )}
        >
          {label}
        </span>
        <span className="type-caption">{at}</span>
      </div>
      <p className="mt-1.5 text-[15px] font-semibold leading-[22px] text-forest">
        {title}
      </p>
      <p className="type-caption mt-1.5">{detail}</p>
      {action ? <div className="mt-1.5">{action}</div> : null}
    </div>
  )
}

/** A link styled as a quiet action, for the panels above. */
export function QuietLink({
  to,
  children,
}: {
  to: string
  children: ReactNode
}) {
  return (
    <Link
      to={to}
      viewTransition
      className="inline-flex items-center gap-1 rounded text-[13px] font-semibold text-forest outline-none hover:underline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring"
    >
      {children}
    </Link>
  )
}

/**
 * One waiting application, as a row of the action queue (design node
 * `49:789`): an icon, a **task-phrased** title with one line of consequence,
 * and the trailing action. The design's queue carries no status badge — the
 * row's membership in "the things awaiting you" is the status — so the
 * caller phrases the task ("Review your Acme application") and this renders
 * it with the consequence line.
 *
 * **The whole row is one link**, and the trailing "Review draft →" is a
 * styled `span` inside it rather than a second anchor. Two nested
 * interactive elements would be invalid HTML and a screen reader would
 * announce the same destination twice; a single link also gives the row a
 * full-width touch target instead of a 90 px button.
 */
export function ApplicationActionRow({
  applicationId,
  title,
  body,
  actionLabel,
}: {
  applicationId: string
  title: string
  body: string
  actionLabel: string
}) {
  return (
    <Link
      to={`/app/tracker/${encodeURIComponent(applicationId)}`}
      viewTransition
      className={cn(
        "-mx-2 flex items-center gap-3 rounded-lg px-2 py-2.5 transition-colors",
        "outline-none hover:bg-accent/60 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring"
      )}
    >
      <FileText
        aria-hidden="true"
        className="size-[18px] shrink-0 text-muted-foreground"
        strokeWidth={1.6}
      />
      <div className="min-w-0 flex-1">
        <p className="text-sm font-semibold text-foreground">
          <PlainText as="span" className="text-sm font-semibold">
            {title}
          </PlainText>
        </p>
        <p className="text-xs leading-relaxed text-muted-foreground">
          <PlainText as="span" className="text-xs">
            {body}
          </PlainText>
        </p>
      </div>
      <span
        aria-hidden="true"
        className="shrink-0 text-[13px] font-semibold text-forest"
      >
        {actionLabel} →
      </span>
    </Link>
  )
}

/**
 * A source that could not be read, as a queue row with its way back.
 *
 * It is a row rather than a banner because a failed source is something a
 * person has to resolve — and because the section must never look all-clear
 * while one of its sources is unknown.
 */
export function FailureActionRow({
  title,
  body,
  onRetry,
}: {
  title: string
  body: string
  onRetry: () => void
}) {
  return (
    <div className="flex items-center gap-3 py-2.5">
      <TriangleAlert
        aria-hidden="true"
        className="size-[18px] shrink-0 text-destructive"
        strokeWidth={1.6}
      />
      <div className="min-w-0 flex-1">
        <p className="text-sm font-semibold text-foreground">{title}</p>
        <p className="text-xs leading-relaxed text-muted-foreground">{body}</p>
      </div>
      <div className="shrink-0">
        <Button type="button" variant="outline" size="sm" onClick={onRetry}>
          Try again
        </Button>
      </div>
    </div>
  )
}
