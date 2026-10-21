import { ChevronRight } from "lucide-react"
import type { ReactNode } from "react"

/**
 * A disclosure the operator opens to see the agent's reasoning.
 *
 * The content sits in its own quiet panel with a comfortable measure, so a
 * long explanation reads as a paragraph and not as a squeezed column. The
 * chevron turns when it opens, which is the only motion the panel needs.
 */
export function Disclosure({
  summary,
  hint,
  children,
}: {
  summary: string
  hint?: string
  children: ReactNode
}) {
  return (
    <details className="group">
      <summary className="flex cursor-pointer list-none items-center gap-2 rounded-lg py-1 text-sm font-medium text-foreground transition-colors hover:text-primary">
        <ChevronRight
          aria-hidden="true"
          className="size-4 shrink-0 text-muted-foreground transition-transform duration-200 group-open:rotate-90"
        />
        {summary}
        {hint ? (
          <span className="text-xs font-normal text-muted-foreground">
            — {hint}
          </span>
        ) : null}
      </summary>
      <div className="mt-3 space-y-4 rounded-xl border border-border bg-muted/30 p-4 sm:p-5">
        {children}
      </div>
    </details>
  )
}
