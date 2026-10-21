import type { ReactNode } from "react"

/**
 * The heading of a screen.
 *
 * One rhythm for every screen: a display-set title, a line of prose that
 * says what the screen is for, and room for the screen's own actions.
 * The prose is capped at a readable width — the header is not a billboard.
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
  return (
    <div className="mb-8 flex flex-wrap items-end justify-between gap-4">
      <div className="console-reading">
        <h1 className="font-heading text-[28px] leading-tight font-semibold tracking-tight text-balance text-foreground sm:text-[32px]">
          {title}
        </h1>
        {description ? (
          <div className="mt-2 text-[15px] leading-relaxed text-muted-foreground">
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
