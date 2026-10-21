import { cn } from "cn"

import { describeStatus, type StatusTone } from "@/lib/status"

const TONE_CLASSES: Record<StatusTone, string> = {
  neutral: "border-border bg-muted text-muted-foreground",
  info: "border-primary/30 bg-primary/10 text-primary",
  progress: "border-sky-500/40 bg-sky-500/10 text-sky-700 dark:text-sky-300",
  success:
    "border-emerald-500/40 bg-emerald-500/10 text-emerald-700 dark:text-emerald-300",
  warning:
    "border-amber-500/40 bg-amber-500/10 text-amber-700 dark:text-amber-300",
  danger: "border-destructive/40 bg-destructive/10 text-destructive",
}

/**
 * A status, as a badge.
 *
 * The badge shows the backend's own vocabulary, mapped to a label. An
 * unfamiliar status is shown verbatim in a neutral tone — the console does
 * not hide what it does not understand.
 */
export function StatusBadge({
  status,
  className,
}: {
  status: string | null | undefined
  className?: string
}) {
  const presentation = describeStatus(status)
  return (
    <span
      data-status={status ?? "unknown"}
      title={presentation.nextStep}
      className={cn(
        "inline-flex items-center rounded-full border px-2 py-0.5 text-xs font-medium",
        TONE_CLASSES[presentation.tone],
        className
      )}
    >
      {presentation.label}
    </span>
  )
}

/** A status, with the line that says what a human must do next. */
export function StatusExplainer({
  status,
}: {
  status: string | null | undefined
}) {
  const presentation = describeStatus(status)
  return (
    <p className="text-sm text-muted-foreground">
      <span className="font-medium text-foreground">{presentation.label}.</span>{" "}
      {presentation.nextStep}
    </p>
  )
}
