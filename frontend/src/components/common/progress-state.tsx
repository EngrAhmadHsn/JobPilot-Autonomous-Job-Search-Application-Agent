import { cn } from "cn"
import type { ReactNode } from "react"

import { useElapsed } from "@/hooks/use-elapsed"

/**
 * The state of a call that is still running.
 *
 * The console makes long calls (a search, a tailoring run, a refresh), and
 * a long call with no feedback is indistinguishable from a hung console. The
 * elapsed seconds and the Cancel button are what make the wait honest: the
 * operator can see it is moving, and can stop waiting without pretending
 * the server stopped.
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
        "rounded-lg border border-border bg-muted/40 px-3 py-2",
        className
      )}
    >
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <p className="text-sm font-medium">{title}</p>
          {description ? (
            <p className="text-sm text-muted-foreground">{description}</p>
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
              className="text-xs font-medium underline underline-offset-4"
            >
              Cancel
            </button>
          ) : null}
        </div>
      </div>
      {children ? <div className="mt-2">{children}</div> : null}
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
        "rounded-lg border border-dashed border-border px-4 py-8 text-center",
        className
      )}
    >
      <p className="text-sm font-medium">{title}</p>
      {description ? (
        <div className="mx-auto mt-1 max-w-prose text-sm text-muted-foreground">
          {description}
        </div>
      ) : null}
      {action ? <div className="mt-3 flex justify-center">{action}</div> : null}
    </div>
  )
}
