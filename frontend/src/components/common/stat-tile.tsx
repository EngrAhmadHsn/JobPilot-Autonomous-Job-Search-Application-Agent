import { cn } from "cn"
import type { ReactNode } from "react"

/**
 * One metric, as a tile.
 *
 * A tile is deliberately plain: a label, a value, and an optional hint
 * that says where the number came from. The hint matters — a number with
 * no provenance is a number a reader has to trust blindly, and this
 * console does not ask to be trusted.
 */
export function StatTile({
  label,
  value,
  hint,
  tone = "neutral",
  className,
}: {
  label: string
  value: ReactNode
  hint?: ReactNode
  /** `agent` is lime, `human` is terracotta — the console's colour rule. */
  tone?: "neutral" | "agent" | "human" | "attention"
  className?: string
}) {
  const valueTone =
    tone === "agent"
      ? "text-lime-foreground"
      : tone === "human"
        ? "text-terracotta-foreground"
        : tone === "attention"
          ? "text-destructive"
          : "text-foreground"

  return (
    <div
      className={cn(
        "rounded-xl border border-border bg-card px-4 py-3.5",
        className
      )}
    >
      <p className="text-xs font-medium tracking-wide text-muted-foreground uppercase">
        {label}
      </p>
      <p className={cn("mt-1 font-heading text-2xl font-semibold", valueTone)}>
        {value}
      </p>
      {hint ? (
        <p className="mt-0.5 text-xs text-muted-foreground">{hint}</p>
      ) : null}
    </div>
  )
}
