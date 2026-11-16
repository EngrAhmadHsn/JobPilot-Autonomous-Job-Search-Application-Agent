import { ArrowUpRightIcon } from "lucide-react"
import type { ReactNode } from "react"
import { Link } from "react-router-dom"
import { cn } from "cn"

import { Skeleton } from "@/components/ui/skeleton"

/*
  One metric of the Home stat strip (WS-35).

  The shared `StatTile` renders a value with provenance but is not a link;
  every tile of the reference's stat strip leads somewhere real (Approvals,
  Matches, Tracker), so this is the tile as a link — with the same plain
  anatomy: label, value, hint that says where the number came from.

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
  /** True while the first read is on the way: bones, not zeros. */
  loading?: boolean
}

export function StatCard({
  label,
  value,
  hint,
  to,
  variant = "default",
  loading = false,
}: StatCardProps) {
  const attention = variant === "attention"
  const linked = Boolean(to) && !loading

  const frame = cn(
    "block rounded-xl border px-4 py-3.5 transition-[box-shadow] duration-150",
    attention
      ? "border-terracotta bg-terracotta-soft"
      : "border-border bg-card hover:shadow-[var(--shadow-lift)]"
  )

  const body = (
    <>
      <div className="flex items-center justify-between gap-2">
        <p
          className={cn(
            "text-xs font-medium tracking-wide uppercase",
            attention ? "text-terracotta-foreground" : "text-muted-foreground"
          )}
        >
          {label}
        </p>
        {linked ? (
          <ArrowUpRightIcon
            aria-hidden="true"
            className={cn(
              "size-4 shrink-0",
              attention ? "text-terracotta-foreground" : "text-muted-foreground"
            )}
            strokeWidth={1.8}
          />
        ) : null}
      </div>
      {loading ? (
        <div className="mt-2 space-y-1.5" aria-hidden="true">
          <Skeleton className="h-7 w-12" />
          <Skeleton className="h-3 w-28" />
        </div>
      ) : (
        <>
          <p
            className={cn(
              "mt-1.5 font-heading text-2xl leading-none font-semibold tabular-nums",
              attention ? "text-terracotta-foreground" : "text-foreground"
            )}
          >
            {value}
          </p>
          {hint ? (
            <p
              className={cn(
                "mt-1.5 text-xs leading-relaxed",
                attention
                  ? "text-terracotta-foreground"
                  : "text-muted-foreground"
              )}
            >
              {hint}
            </p>
          ) : null}
        </>
      )}
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
