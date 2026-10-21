import { cn } from "cn"
import type { ReactNode } from "react"

/** The visual tones a banner can carry. */
export type BannerTone = "neutral" | "info" | "warning" | "danger" | "success"

const TONE_CLASSES: Record<BannerTone, string> = {
  neutral: "border-border bg-muted/40 text-foreground",
  info: "border-primary/30 bg-primary/5 text-foreground",
  warning: "border-amber-500/40 bg-amber-500/10 text-foreground",
  danger: "border-destructive/40 bg-destructive/10 text-foreground",
  success: "border-emerald-500/40 bg-emerald-500/10 text-foreground",
}

const TONE_LABELS: Record<BannerTone, string> = {
  neutral: "Note",
  info: "Information",
  warning: "Warning",
  danger: "Problem",
  success: "Confirmed",
}

/**
 * A message the operator must read.
 *
 * A banner is used for the things the operator would otherwise miss: a
 * degraded search, a source that failed, a stripped factuality violation.
 */
export function Banner({
  tone = "neutral",
  title,
  children,
  className,
}: {
  tone?: BannerTone
  title: string
  children?: ReactNode
  className?: string
}) {
  return (
    <div
      role={tone === "danger" || tone === "warning" ? "alert" : "status"}
      className={cn(
        "rounded-lg border px-3 py-2",
        TONE_CLASSES[tone],
        className
      )}
    >
      <p className="text-sm font-medium">
        <span className="sr-only">{TONE_LABELS[tone]}: </span>
        {title}
      </p>
      {children ? <div className="mt-1 text-sm">{children}</div> : null}
    </div>
  )
}
