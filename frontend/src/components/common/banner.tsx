import { cn } from "cn"
import type { ReactNode } from "react"

/** The visual tones a banner can carry. */
export type BannerTone = "neutral" | "info" | "warning" | "danger" | "success"

/*
  The tones follow one rule: **lime is the agent, terracotta is a person.**
  A success banner is something the agent did on its own, so it is lime. A
  warning is something a person has to deal with, so it is the warm clay.
  A danger is a failure and says so in the destructive red.
*/
const TONE_CLASSES: Record<BannerTone, string> = {
  neutral: "border-border bg-card text-foreground",
  info: "border-forest/20 bg-forest-soft text-forest",
  warning: "border-terracotta bg-terracotta-soft text-terracotta-foreground",
  danger: "border-destructive/40 bg-destructive/10 text-foreground",
  success: "border-lime/70 bg-lime-soft text-lime-foreground",
}

const TONE_LABELS: Record<BannerTone, string> = {
  neutral: "Note",
  info: "Information",
  warning: "Needs you",
  danger: "Problem",
  success: "Done",
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
        "rounded-xl border px-4 py-3",
        TONE_CLASSES[tone],
        className
      )}
    >
      <p className="text-sm font-semibold">
        <span className="sr-only">{TONE_LABELS[tone]}: </span>
        {title}
      </p>
      {children ? (
        <div className="mt-1.5 text-sm leading-relaxed">{children}</div>
      ) : null}
    </div>
  )
}
