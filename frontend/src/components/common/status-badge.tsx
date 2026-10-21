import { cn } from "cn"

import { describeStatus, type StatusTone } from "@/lib/status"

/*
  A status badge says **who is holding this up**.

  Lime is the agent's mark: the agent prepared it, submitted it, verified
  it. Terracotta is a person's: it is waiting for a decision, or a person
  recorded the outcome. Anything the console does not understand is shown
  verbatim in a neutral tone — hiding an unfamiliar status would be a lie
  of omission.
*/
const TONE_CLASSES: Record<StatusTone, string> = {
  neutral: "border-border bg-muted text-muted-foreground",
  info: "border-border bg-card text-foreground",
  progress: "border-lime/70 bg-lime-soft text-lime-foreground",
  success: "border-lime/70 bg-lime text-lime-foreground",
  warning: "border-terracotta bg-terracotta-soft text-terracotta-foreground",
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
        "inline-flex items-center rounded-full border px-2.5 py-0.5 text-[11px] font-medium",
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
    <p className="text-sm leading-relaxed text-muted-foreground">
      <span className="font-medium text-foreground">{presentation.label}.</span>{" "}
      {presentation.nextStep}
    </p>
  )
}
