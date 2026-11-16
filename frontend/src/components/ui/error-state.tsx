import { TriangleAlertIcon } from "lucide-react"
import { cn } from "cn"

import { ApiError, AbortedError } from "@/lib/api/client"
import { describeError } from "@/lib/errors"

/**
 * An error state (WS-34).
 *
 * The actionable sibling of `common/error-notice.tsx`'s banner: a full
 * panel a screen can render **in place of its content** when the data it
 * exists to show could not be loaded. The copy comes from
 * `lib/errors`, which turns a transport failure into a sentence a person
 * can act on, and the recovery path is a real button — "try again" is an
 * action, not an apology.
 *
 * `verbose` is the administrator's view (the raw status and the server's
 * own words); the administration screens pass it, everything else stays in
 * the product's voice.
 */
export function ErrorState({
  error,
  onRetry,
  verbose = false,
  className,
}: {
  error: unknown
  onRetry?: () => void
  /** Show the HTTP status and the server's raw detail (administrators). */
  verbose?: boolean
  className?: string
}) {
  const described = describeError(error)
  const status = error instanceof ApiError ? error.status : null
  const title =
    verbose && status !== null
      ? `${described.title} (HTTP ${status})`
      : described.title
  const urgent = !(error instanceof AbortedError)

  return (
    <div
      role={urgent ? "alert" : "status"}
      data-slot="error-state"
      className={cn(
        "flex flex-col items-center justify-center gap-3 rounded-xl border border-destructive/40 bg-destructive/5 px-6 py-12 text-center",
        className
      )}
    >
      <span
        aria-hidden="true"
        className="flex size-10 items-center justify-center rounded-full bg-destructive/10 text-destructive"
      >
        <TriangleAlertIcon className="size-5" strokeWidth={1.6} />
      </span>
      <div className="max-w-[52ch]">
        <h3 className="font-heading text-base font-semibold text-foreground">
          {title}
        </h3>
        <p className="mt-1.5 text-sm leading-relaxed text-muted-foreground">
          {described.message}
        </p>
        {verbose && described.technical ? (
          <p className="mt-2 font-mono text-xs break-words text-muted-foreground">
            {described.technical}
          </p>
        ) : null}
        {described.details.length > 0 ? (
          <ul className="mt-2 list-disc space-y-1 ps-5 text-start text-sm text-muted-foreground">
            {described.details.map((detail, index) => (
              <li key={`${detail}-${index}`}>{detail}</li>
            ))}
          </ul>
        ) : null}
      </div>
      {onRetry ? (
        <button
          type="button"
          onClick={onRetry}
          className="mt-1 inline-flex h-9 items-center rounded-lg border border-border bg-card px-3 text-sm font-medium text-foreground transition-colors duration-150 hover:bg-muted hover:text-foreground"
        >
          Try again
        </button>
      ) : null}
    </div>
  )
}
