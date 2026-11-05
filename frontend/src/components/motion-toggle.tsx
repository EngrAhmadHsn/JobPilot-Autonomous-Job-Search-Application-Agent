import { cn } from "cn"

import {
  setMotionPreference,
  useMotionPreference,
  type MotionPreference,
} from "@/lib/motion"

const OPTIONS: { value: MotionPreference; label: string; title: string }[] = [
  {
    value: "system",
    label: "System",
    title: "Follow this device's motion setting",
  },
  { value: "full", label: "Full", title: "Always play the animations" },
  { value: "reduced", label: "Reduced", title: "Never move anything" },
]

/**
 * The motion control.
 *
 * A three-way choice, not a switch: "System" is the honest default (it
 * respects the OS), "Full" lets a visitor see the product's motion on a
 * machine that reports reduce for unrelated reasons, and "Reduced" turns
 * movement off regardless. The choice is per browser.
 *
 * It is a segmented control of real buttons with `aria-pressed`, so it is
 * operable by keyboard and announced correctly.
 */
export function MotionToggle({
  tone = "light",
  className,
}: {
  tone?: "light" | "night"
  className?: string
}) {
  const preference = useMotionPreference()
  const night = tone === "night"

  return (
    <div
      role="group"
      aria-label="Motion"
      className={cn(
        "inline-flex items-center gap-0.5 rounded-lg border p-0.5",
        night
          ? "border-night-line bg-night-soft/70"
          : "border-border bg-card",
        className
      )}
    >
      {OPTIONS.map((option) => {
        const active = preference === option.value
        return (
          <button
            key={option.value}
            type="button"
            title={option.title}
            aria-pressed={active}
            onClick={() => setMotionPreference(option.value)}
            className={cn(
              "rounded-md px-2 py-1 text-[11px] font-medium transition-colors duration-150",
              active
                ? night
                  ? "bg-lime text-lime-foreground"
                  : "bg-primary text-primary-foreground"
                : night
                  ? "text-night-muted hover:text-ivory"
                  : "text-muted-foreground hover:text-foreground"
            )}
          >
            {option.label}
          </button>
        )
      })}
    </div>
  )
}