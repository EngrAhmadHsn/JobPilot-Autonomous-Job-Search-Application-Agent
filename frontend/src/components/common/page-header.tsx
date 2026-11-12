import type { ReactNode } from "react"

import { useDocumentTitle } from "@/hooks/use-document-title"

/**
 * The heading of a screen.
 *
 * One rhythm for every screen: a display-set title, a line of prose that
 * says what the screen is for, and room for the screen's own actions.
 * The prose is capped at a readable width — the header is not a billboard.
 *
 * **It also names the tab.** Every console screen renders this component with
 * the screen's own title, so setting `document.title` here covers all of them
 * from one place rather than at eleven call sites. A client-rendered app has a
 * single document, so without this every route kept the title `index.html`
 * shipped with and a screen reader heard the same name after every navigation
 * (WCAG 2.4.2 Page Titled).
 *
 * Sizes come from the scale (`text-3xl` is 30px) rather than `text-[28px]`, so
 * a reader who raises the browser font size actually gets larger headings.
 */
export function PageHeader({
  title,
  description,
  actions,
  children,
}: {
  title: string
  description?: ReactNode
  actions?: ReactNode
  children?: ReactNode
}) {
  useDocumentTitle(title)

  return (
    <div className="mb-8 flex flex-wrap items-end justify-between gap-4">
      <div className="console-reading">
        <h1 className="font-heading text-3xl leading-[1.15] font-semibold tracking-tight text-balance text-foreground">
          {title}
        </h1>
        {description ? (
          <div className="mt-2 text-base leading-relaxed text-muted-foreground">
            {description}
          </div>
        ) : null}
        {children}
      </div>
      {actions ? (
        <div className="flex items-center gap-2">{actions}</div>
      ) : null}
    </div>
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
      <div className="mb-4 flex flex-wrap items-end justify-between gap-3">
        <div>
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
