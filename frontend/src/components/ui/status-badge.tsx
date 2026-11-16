import {
  ArchiveIcon,
  BadgeCheckIcon,
  BanIcon,
  BookmarkIcon,
  CheckIcon,
  CircleCheckIcon,
  CircleDashedIcon,
  CircleHelpIcon,
  CircleMinusIcon,
  CircleXIcon,
  ClockIcon,
  FileTextIcon,
  FileWarningIcon,
  HourglassIcon,
  LoaderCircleIcon,
  MessagesSquareIcon,
  SearchIcon,
  SendIcon,
  ShieldAlertIcon,
  ShieldXIcon,
  TargetIcon,
  TriangleAlertIcon,
  TrophyIcon,
  type LucideIcon,
} from "lucide-react"
import { createElement, type ComponentProps } from "react"
import { cn } from "cn"

import { describeStatus, type StatusTone } from "@/lib/status"

/*
  The one presentation of a backend status (WS-34).

  One backend state has exactly one label, one tone, one icon and one
  explanation — enforced by the status-table test in `lib/status.test.ts`.
  This component is the only place that turns `lib/status`'s presentation
  objects into pixels, so Home, Review, Tracker and Activity cannot drift
  apart.

  The tones follow the semantic law: **lime is the agent, terracotta is a
  human.** `success` and `progress` render in the agent's lime; `warning`
  renders in the human's terracotta; `danger` is a failure saying so; the
  rest are quiet paper. Colour never carries the meaning alone: the icon
  and the label are redundant cues, and the explanation rides in `title`
  plus the explainer below.
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
 * The icon for a status, by the name `lib/status` records on each
 * presentation. The names are validated by test against this map, so a
 * typo in the vocabulary fails the suite rather than a screen.
 *
 * The lookup goes through `statusIcon` rather than a raw index so an
 * unknown name falls back to the dashed circle instead of assuming a
 * shape the vocabulary never promised.
 */
export const STATUS_ICONS = {
  Archive: ArchiveIcon,
  BadgeCheck: BadgeCheckIcon,
  Ban: BanIcon,
  Bookmark: BookmarkIcon,
  Check: CheckIcon,
  CircleCheck: CircleCheckIcon,
  CircleDashed: CircleDashedIcon,
  CircleHelp: CircleHelpIcon,
  CircleMinus: CircleMinusIcon,
  CircleX: CircleXIcon,
  Clock: ClockIcon,
  FileText: FileTextIcon,
  FileWarning: FileWarningIcon,
  Hourglass: HourglassIcon,
  LoaderCircle: LoaderCircleIcon,
  MessagesSquare: MessagesSquareIcon,
  Search: SearchIcon,
  Send: SendIcon,
  ShieldAlert: ShieldAlertIcon,
  ShieldX: ShieldXIcon,
  Target: TargetIcon,
  TriangleAlert: TriangleAlertIcon,
  Trophy: TrophyIcon,
} as const satisfies Record<string, LucideIcon>

function statusIcon(name: string, props: ComponentProps<LucideIcon>) {
  const Icon =
    (STATUS_ICONS as Record<string, LucideIcon>)[name] ?? CircleDashedIcon
  return createElement(Icon, { "aria-hidden": true, ...props })
}

/**
 * A status, as a badge with its icon.
 *
 * An unfamiliar status is shown verbatim in a neutral tone with the
 * dashed-circle mark — the console does not hide what it does not
 * understand, and does not invent a meaning for it either.
 */
export function StatusBadge({
  status,
  className,
  withIcon = true,
}: {
  status: string | null | undefined
  className?: string
  /** Show the status's icon before the label (on by default). */
  withIcon?: boolean
}) {
  const presentation = describeStatus(status)
  return (
    <span
      data-status={status ?? "unknown"}
      title={presentation.nextStep}
      className={cn(
        "inline-flex max-w-full items-center gap-1 rounded-full border px-2.5 py-0.5 text-[11px] font-medium",
        TONE_CLASSES[presentation.tone],
        className
      )}
    >
      {withIcon
        ? statusIcon(presentation.icon, {
            className: "size-3 shrink-0",
            strokeWidth: 2,
          })
        : null}
      <span className="truncate">{presentation.label}</span>
    </span>
  )
}

/**
 * A status, with the line that says what a human must do next.
 *
 * The status table's `nextStep` is the plain-language explanation; this
 * renders it under (or beside) the badge wherever a screen needs the
 * sentence rather than the word.
 */
export function StatusExplainer({
  status,
  className,
}: {
  status: string | null | undefined
  className?: string
}) {
  const presentation = describeStatus(status)
  return (
    <p
      className={cn(
        "flex items-start gap-2 text-sm leading-relaxed text-muted-foreground",
        className
      )}
    >
      {statusIcon(presentation.icon, {
        className: "mt-0.5 size-4 shrink-0 text-foreground",
        strokeWidth: 1.8,
      })}
      <span>
        <span className="font-medium text-foreground">
          {presentation.label}.
        </span>{" "}
        {presentation.nextStep}
      </span>
    </p>
  )
}
