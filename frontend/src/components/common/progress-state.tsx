import { cn } from "cn"
import type { ReactNode } from "react"

import { useElapsed } from "@/hooks/use-elapsed"

/**
 * The state of a call that is still running.
 *
 * The console makes long calls (a search, a tailoring run, a refresh), and
 * a long call with no feedback is indistinguishable from a hung console.
 * The elapsed seconds and the Cancel button are what make the wait honest:
 * the operator can see it is moving, and can stop waiting without
 * pretending the server stopped.
 */
export function ProgressState({
  title,
  description,
  active = true,
  onCancel,
  className,
  children,
}: {
  title: string
  description?: ReactNode
  active?: boolean
  onCancel?: () => void
  className?: string
  children?: ReactNode
}) {
  const seconds = useElapsed(active)

  return (
    <div
      role="status"
      aria-live="polite"
      className={cn(
        "rounded-xl border border-border bg-card px-4 py-3.5",
        className
      )}
    >
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="min-w-0">
          <p className="text-sm font-medium text-foreground">{title}</p>
          {description ? (
            <p className="text-sm leading-relaxed text-muted-foreground">
              {description}
            </p>
          ) : null}
        </div>
        <div className="flex items-center gap-3">
          {active ? (
            <span className="text-xs text-muted-foreground tabular-nums">
              {seconds}s elapsed
            </span>
          ) : null}
          {onCancel ? (
            <button
              type="button"
              onClick={onCancel}
              className="text-xs font-medium text-muted-foreground underline underline-offset-4 transition-colors hover:text-foreground"
            >
              Cancel
            </button>
          ) : null}
        </div>
      </div>
      <div className="agent-progress mt-3 h-1 w-full rounded-full" />
      {children ? <div className="mt-3">{children}</div> : null}
    </div>
  )
}

/** The state of a screen that has nothing to show yet. */
export function EmptyState({
  title,
  description,
  action,
  className,
}: {
  title: string
  description?: ReactNode
  action?: ReactNode
  className?: string
}) {
  return (
    <div
      className={cn(
        "rounded-2xl border border-dashed border-border bg-card/60 px-6 py-12 text-center",
        className
      )}
    >
      <p className="font-heading text-base font-semibold tracking-tight text-foreground">
        {title}
      </p>
      {description ? (
        <div className="mx-auto mt-2 max-w-prose text-sm leading-relaxed text-muted-foreground">
          {description}
        </div>
      ) : null}
      {action ? <div className="mt-5 flex justify-center">{action}</div> : null}
    </div>
  )
}
