import { ArrowUpRightIcon } from "lucide-react"
import type { LucideIcon } from "lucide-react"
import type { ReactNode } from "react"
import { Link } from "react-router-dom"
import { cn } from "cn"

import { Skeleton } from "@/components/ui/skeleton"

/*
  One metric of the Home stat strip (WS-35).

  The shared `StatTile` renders a value with provenance but is not a link;
  every tile of the reference's stat strip leads somewhere real (Approvals,
  Matches, Tracker), so this is the tile as a link. The anatomy is the same
  as the tile's — a leading glyph, the value with its plain-case label
  beneath, then the provenance line — and the reference's one extra signal:
  the attention tile carries a trailing chevron, which here is the link
  affordance on every tile that leads somewhere.

  The attention variant is the reference's terracotta card, and the tone law
  behind it: terracotta is the human's colour, and "need your attention" is
  the one strip metric a *person* has to resolve. Every text on the wash is
  `terracotta-foreground` (8.07:1 on `terracotta-soft`, the design system's
  measured pair) — an alpha-modified muted would blend below AA there, so
  the wash carries no `/80` text.

  A failed read renders "—", never a stand-in zero, and the first read
  renders bones rather than a number that would only be a guess.
*/

export interface StatCardProps {
  label: string
  value: ReactNode
  /** Where the number came from, in a sentence. */
  hint?: ReactNode
  /** The screen that resolves the metric, when the tile leads somewhere. */
  to?: string
  variant?: "default" | "attention"
  /** A leading Lucide glyph, drawn bare in the tone's ink. */
  icon?: LucideIcon
  /** True while the first read is on the way: bones, not zeros. */
  loading?: boolean
}

export function StatCard({
  label,
  value,
  hint,
  to,
  variant = "default",
  icon: Icon,
  loading = false,
}: StatCardProps) {
  const attention = variant === "attention"
  const linked = Boolean(to) && !loading

  const frame = cn(
    "block rounded-xl border px-5 py-4 transition-[box-shadow] duration-150",
    attention
      ? "border-terracotta bg-terracotta-soft"
      : "border-border bg-card hover:shadow-[var(--shadow-lift)]"
  )

  const ink = attention ? "text-terracotta-foreground" : "text-foreground"
  const mutedInk = attention
    ? "text-terracotta-foreground"
    : "text-muted-foreground"

  const body = (
    <>
      <div className="flex items-center gap-3.5">
        {Icon ? (
          <Icon
            aria-hidden="true"
            className={cn(
              "size-7 shrink-0",
              attention ? "text-terracotta-foreground" : "text-primary"
            )}
            strokeWidth={1.6}
          />
        ) : null}
        <div className="min-w-0 flex-1">
          {loading ? (
            <div className="space-y-2" aria-hidden="true">
              <Skeleton className="h-8 w-14" />
              <Skeleton className="h-3.5 w-28" />
            </div>
          ) : (
            <>
              <p
                className={cn(
                  "font-heading text-3xl leading-none font-bold tabular-nums",
                  ink
                )}
              >
                {value}
              </p>
              <p className={cn("mt-1.5 text-sm", ink)}>{label}</p>
            </>
          )}
          {hint && !loading ? (
            <p className={cn("mt-2 text-xs leading-relaxed", mutedInk)}>
              {hint}
            </p>
          ) : null}
        </div>
        {linked ? (
          <ArrowUpRightIcon
            aria-hidden="true"
            className={cn("size-4 shrink-0 self-center", mutedInk)}
            strokeWidth={1.8}
          />
        ) : null}
      </div>
    </>
  )

  if (linked) {
    return (
      <Link
        to={to as string}
        viewTransition
        className={frame}
        data-stat-card={label}
      >
        {body}
      </Link>
    )
  }

  return (
    <div
      className={frame}
      aria-busy={loading || undefined}
      data-stat-card={label}
    >
      {body}
    </div>
  )
}
