import { cn } from "cn"

import { PlainText } from "@/components/common/plain-text"

/**
 * Gap diagnosis: what the listing asks for and what the profile answers
 * (WS-22).
 *
 * The match explanation has always carried these two lists — but as
 * comma-joined prose, which is a list a person has to parse. Chips are the
 * same data in the shape the question is asked in: green for what the
 * profile covers, clay for what it does not. (The palette rule holds here
 * too: lime is the agent's finding, terracotta is what a person has to
 * deal with.)
 *
 * When both lists are empty the component renders **nothing**: a chip row
 * that says "nothing known" is noise, not information.
 */

const CHIP =
  "inline-flex max-w-full items-center rounded-full border px-2.5 py-0.5 text-xs"

function Chip({
  children,
  tone,
  title,
}: {
  children: React.ReactNode
  tone: "match" | "gap" | "sponsor" | "neutral"
  title?: string
}) {
  return (
    <li
      className={cn(
        CHIP,
        tone === "match" && "border-lime/70 bg-lime-soft text-lime-foreground",
        tone === "gap" &&
          "border-terracotta bg-terracotta-soft text-terracotta-foreground",
        tone === "sponsor" && "border-forest/30 bg-forest-soft text-forest",
        tone === "neutral" && "border-border bg-muted text-muted-foreground"
      )}
      title={title}
    >
      <PlainText as="span" className="truncate">
        {children}
      </PlainText>
    </li>
  )
}

function ChipRow({
  title,
  items,
  tone,
}: {
  title: string
  items: string[]
  tone: "match" | "gap"
}) {
  if (items.length === 0) return null
  return (
    <div>
      <p className="text-xs font-medium text-muted-foreground">{title}</p>
      <ul className="mt-1.5 flex flex-wrap gap-1.5">
        {items.map((item) => (
          <Chip key={item} tone={tone}>
            {item}
          </Chip>
        ))}
      </ul>
    </div>
  )
}

/** The verified-sponsorship finding from the imported registers (WS-22). */
export function SponsorBadge({
  status,
  note,
}: {
  status?: string | null
  note?: string | null
}) {
  if (!status || status === "no_data") return null
  if (status === "verified") {
    return (
      <ul className="flex flex-wrap gap-1.5">
        <Chip tone="sponsor" title={note ?? undefined}>
          {note ?? "Verified visa sponsor"}
        </Chip>
      </ul>
    )
  }
  return (
    <ul className="flex flex-wrap gap-1.5">
      <Chip tone="neutral" title={note ?? undefined}>
        No sponsorship record found
      </Chip>
    </ul>
  )
}

export function MatchGapChips({
  matched,
  missing,
  className,
}: {
  matched: string[]
  missing: string[]
  className?: string
}) {
  if (matched.length === 0 && missing.length === 0) return null
  return (
    <div className={cn("space-y-3", className)}>
      <ChipRow title="Matched requirements" items={matched} tone="match" />
      <ChipRow title="Missing requirements" items={missing} tone="gap" />
    </div>
  )
}