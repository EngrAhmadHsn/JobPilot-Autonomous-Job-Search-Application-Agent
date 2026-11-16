import { FolderOpenIcon, type LucideIcon } from "lucide-react"
import { cn } from "cn"
import type { ReactNode } from "react"

/**
 * An empty state (WS-34).
 *
 * The screen's answer to "there is nothing here yet": a short explanation
 * of **why** it is empty and, where one exists, the action that fills it.
 * It renders exactly what the caller gives it — never sample rows, never
 * placeholder counts, because a fabricated row is a lie about the
 * candidate's real data.
 *
 * The panel is a bordered region, not a card-in-a-card; the icon is
 * decorative and the heading carries the meaning.
 */
export function EmptyState({
  icon: Icon = FolderOpenIcon,
  title,
  message,
  action,
  children,
  className,
}: {
  /** Lucide icon component — pick one that names the absent thing. */
  icon?: LucideIcon
  title: string
  /** Why it is empty, in a sentence or two. */
  message?: ReactNode
  /** The real action that fills the list, if the product has one. */
  action?: ReactNode
  children?: ReactNode
  className?: string
}) {
  return (
    <div
      data-slot="empty-state"
      className={cn(
        "flex flex-col items-center justify-center gap-3 rounded-xl border border-dashed border-border bg-card/60 px-6 py-12 text-center",
        className
      )}
    >
      <span
        aria-hidden="true"
        className="flex size-10 items-center justify-center rounded-full bg-muted text-muted-foreground"
      >
        <Icon className="size-5" strokeWidth={1.6} />
      </span>
      <div className="max-w-[48ch]">
        <h3 className="font-heading text-base font-semibold text-foreground">
          {title}
        </h3>
        {message ? (
          <div className="mt-1.5 text-sm leading-relaxed text-muted-foreground">
            {message}
          </div>
        ) : null}
      </div>
      {action ? (
        <div className="mt-1 flex items-center gap-2">{action}</div>
      ) : null}
      {children}
    </div>
  )
}
