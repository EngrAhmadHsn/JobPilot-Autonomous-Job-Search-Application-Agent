import { cn } from "cn"
import type { LucideIcon } from "lucide-react"
import type { ReactNode } from "react"

/*
  One metric, as a tile.

  The anatomy is the reference's ("01 Dashboard", node 1:44): a leading
  glyph, then the value with its label beneath it, then the provenance
  line. The reference draws the glyph bare — no chip behind it — at 1.6px
  stroke in the brand green, so the icon renders at `size-7` with the
  forest ink and no wash. The value leads because the number is the hero;
  the label below it is plain case, and the hint still says where the
  number came from — a number with no provenance is a number a reader has
  to trust blindly, and this console does not ask to be trusted.
*/

const TONE_CLASSES = {
  neutral: { value: "text-foreground", icon: "text-primary" },
  agent: { value: "text-lime-foreground", icon: "text-lime-foreground" },
  human: {
    value: "text-terracotta-foreground",
    icon: "text-terracotta-foreground",
  },
  attention: { value: "text-destructive", icon: "text-destructive" },
} as const

export function StatTile({
  label,
  value,
  hint,
  tone = "neutral",
  icon: Icon,
  className,
}: {
  label: string
  value: ReactNode
  hint?: ReactNode
  /** `agent` is lime, `human` is terracotta — the console's colour rule. */
  tone?: keyof typeof TONE_CLASSES
  /** A leading Lucide glyph, drawn bare in the tone's ink. */
  icon?: LucideIcon
  className?: string
}) {
  const toneClasses = TONE_CLASSES[tone]

  return (
    <div
      className={cn(
        "rounded-xl border border-border bg-card px-5 py-4",
        className
      )}
    >
      <div className="flex items-center gap-3.5">
        {Icon ? (
          <Icon
            aria-hidden="true"
            className={cn("size-7 shrink-0", toneClasses.icon)}
            strokeWidth={1.6}
          />
        ) : null}
        <div className="min-w-0">
          <p
            className={cn(
              "font-heading text-3xl leading-none font-bold tabular-nums",
              toneClasses.value
            )}
          >
            {value}
          </p>
          <p className="mt-1.5 text-sm text-foreground">{label}</p>
        </div>
      </div>
      {hint ? (
        <p className="mt-2 text-xs text-muted-foreground">{hint}</p>
      ) : null}
    </div>
  )
}
