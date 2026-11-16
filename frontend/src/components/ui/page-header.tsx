import type { ReactNode } from "react"

import { useDocumentTitle } from "@/hooks/use-document-title"

/**
 * The heading of a screen (WS-34).
 *
 * One rhythm for every screen, from the reference: a **spacious display
 * heading**, an optional line of prose that says what the screen is for,
 * and a **compact metadata row** — the small facts (a profile handle, a
 * status, a timestamp, a count) that used to be scattered beside the
 * title. The prose is capped at a readable width; the header is not a
 * billboard.
 *
 * **It also names the tab.** Every console screen renders this component
 * with the screen's own title, so setting `document.title` here covers all
 * of them from one place (WCAG 2.4.2 Page Titled).
 *
 * The heading is set in `rem`-based scale steps (`text-3xl` is 30px), so a
 * reader who raises the browser font size actually gets larger headings.
 */
export function PageHeader({
  title,
  description,
  meta,
  actions,
  children,
}: {
  title: string
  description?: ReactNode
  /** Compact metadata under the description: chips, counts, timestamps. */
  meta?: ReactNode
  actions?: ReactNode
  children?: ReactNode
}) {
  useDocumentTitle(title)

  return (
    <header className="mb-10 flex flex-wrap items-end justify-between gap-x-6 gap-y-4">
      <div className="console-reading min-w-0 flex-1">
        <h1 className="font-heading text-3xl leading-[1.15] font-semibold tracking-tight text-balance text-foreground">
          {title}
        </h1>
        {description ? (
          <div className="mt-2 text-base leading-relaxed text-muted-foreground">
            {description}
          </div>
        ) : null}
        {meta ? (
          <div className="mt-3 flex flex-wrap items-center gap-x-3 gap-y-1.5 text-[13px] leading-relaxed text-muted-foreground">
            {meta}
          </div>
        ) : null}
        {children}
      </div>
      {actions ? (
        <div className="flex flex-wrap items-center gap-2">{actions}</div>
      ) : null}
    </header>
  )
}

/** A titled block inside a screen. */
export function Section({
  title,
  description,
  action,
  className,
  children,
}: {
  title: string
  description?: ReactNode
  action?: ReactNode
  className?: string
  children: ReactNode
}) {
  return (
    <section className={className}>
      <div className="mb-4 flex flex-wrap items-end justify-between gap-x-4 gap-y-2">
        <div className="min-w-0">
          <h2 className="font-heading text-lg font-semibold tracking-tight text-foreground">
            {title}
          </h2>
          {description ? (
            <p className="mt-1 max-w-[62ch] text-sm leading-relaxed text-muted-foreground">
              {description}
            </p>
          ) : null}
        </div>
        {action}
      </div>
      {children}
    </section>
  )
}
