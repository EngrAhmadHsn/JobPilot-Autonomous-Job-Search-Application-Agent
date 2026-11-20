import type { ReactNode } from "react"

import { cn } from "cn"

import { useDocumentTitle } from "@/hooks/use-document-title"

/**
 * The heading of a screen (WS-34, type scale from WS-42).
 *
 * One rhythm for every screen, from the design file (node `47:35`): a
 * **display heading**, an optional line of prose that says what the screen is
 * for, and a **compact metadata row** — the small facts (a profile handle, a
 * status, a timestamp, a count) that used to be scattered beside the title.
 * The prose is capped at a readable width; the header is not a billboard.
 *
 * **It also names the tab.** Every console screen renders this component with
 * the screen's own title, so setting `document.title` here covers all of them
 * from one place (WCAG 2.4.2 Page Titled).
 *
 * The heading uses the `type-display` utility — the design file's measured
 * **36/47 Bricolage Grotesque 700 in forest ink** (node `47:36`). It is
 * declared once in `index.css` and expressed in `rem`, so a reader who raises
 * the browser font size still gets larger headings.
 *
 * **This module is the single implementation.** `components/common/page-header`
 * re-exports it. Two competing headers existed until WS-42 — one with a `meta`
 * row, one without — and half the screens imported each, so the same screen
 * title rendered at two different sizes depending on which module the author
 * happened to import.
 */
export function PageHeader({
  title,
  documentTitle,
  description,
  meta,
  actions,
  children,
  className,
}: {
  title: string
  /**
   * The tab title, when the visible `h1` is not the screen's name.
   *
   * The design leads several screens with a *statement* ("Your next career
   * move.") rather than a label — the statement is the `h1`, but the tab
   * still needs the stable screen name the accessibility contract pins
   * ("Overview · JobPilot"). When omitted the visible title is used, exactly
   * as before.
   */
  documentTitle?: string
  description?: ReactNode
  /** Compact metadata under the description: chips, counts, timestamps. */
  meta?: ReactNode
  actions?: ReactNode
  children?: ReactNode
  /** Extra classes for the header root (the default carries `mb-6`). */
  className?: string
}) {
  useDocumentTitle(documentTitle ?? title)

  return (
    <header
      className={cn(
        "mb-6 flex flex-wrap items-end justify-between gap-x-6 gap-y-4",
        className
      )}
    >
      <div className="min-w-0 flex-1">
        <h1 className="type-display text-balance">{title}</h1>
        {description ? (
          <div className="mt-2 max-w-[70ch] text-sm leading-relaxed text-muted-foreground">
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

/** A titled block inside a screen (node `49:770` — 20/29, forest ink). */
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
      <div className="mb-3 flex items-start justify-between gap-x-4 gap-y-2">
        <div className="min-w-0 flex-1">
          <h2 className="type-section">{title}</h2>
          {description ? (
            <p className="mt-1 max-w-[62ch] text-sm leading-relaxed text-muted-foreground">
              {description}
            </p>
          ) : null}
        </div>
        {/*
          The action never wraps *under* the heading the way a flex-wrap row
          would at phone widths — the design keeps it top-right (node
          49:10288, "View all applications →" beside a wrapped title), so
          the title shrinks and wraps internally instead.
        */}
        {action ? <div className="shrink-0">{action}</div> : null}
      </div>
      {children}
    </section>
  )
}
