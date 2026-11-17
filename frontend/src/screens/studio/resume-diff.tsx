import { useState } from "react"

import {
  CircleAlert,
  Columns2,
  Eye,
  Minus,
  PenLine,
  Plus,
  Rows3,
} from "lucide-react"
import { cn } from "cn"

import { PlainText } from "@/components/common/plain-text"
import { Banner } from "@/components/common/banner"
import { SectionTitle } from "@/components/common/field-list"

import {
  buildResumeDiff,
  type DiffPair,
  type RenderReport,
  type ResumeDiff,
} from "./diff-model"
import type { CandidateProfile, TailoredResume } from "@/lib/api/types"

/*
  The original-versus-tailored comparison (WS-37, reference panel 3).

  Side-by-side on wide screens, stacked or toggled on narrow ones — each
  block keeps its own "Original"/"Tailored" label either way, so the two
  columns can never be confused. The washes follow the design system's
  meaning and the workstream's letter (§6.4 task 3): additions carry the
  lime of the agent's new wording; a replacement washes the replaced
  original in terracotta — the colour of "this needs a human's eye" — and
  its tailored side in lime; a cleared passage is terracotta. Colour is
  never the only signal: every block also carries a labelled icon, and the
  legend names all five states.

  **The comparison is read-only.** There is no per-change accept/reject
  model behind it (the Task 1 audit found none in the backend), so there
  are no Accept/Reject controls here and the screen says so plainly rather
  than implying a persistence that does not exist.
*/

type DiffStatus = DiffPair["status"]

const STATUS_META: Record<
  DiffStatus,
  { label: string; icon: typeof Plus; chipClass: string }
> = {
  unchanged: {
    label: "Unchanged",
    icon: Minus,
    chipClass: "border-border bg-muted text-muted-foreground",
  },
  reworded: {
    label: "Reworded",
    icon: PenLine,
    chipClass:
      "border-terracotta bg-terracotta-soft text-terracotta-foreground",
  },
  added: {
    label: "Added",
    icon: Plus,
    chipClass: "border-lime/70 bg-lime-soft text-lime-foreground",
  },
  removed: {
    label: "Cleared",
    icon: Minus,
    chipClass:
      "border-terracotta bg-terracotta-soft text-terracotta-foreground",
  },
  notCompared: {
    label: "Not compared — manual review required",
    icon: CircleAlert,
    chipClass:
      "border-terracotta bg-terracotta-soft text-terracotta-foreground",
  },
}

function StatusChip({ status }: { status: DiffStatus }) {
  const meta = STATUS_META[status]
  const Icon = meta.icon
  return (
    <span
      className={cn(
        "inline-flex shrink-0 items-center gap-1 rounded-full border px-2 py-0.5 text-[11px] font-medium",
        meta.chipClass
      )}
    >
      <Icon className="size-3" aria-hidden />
      {meta.label}
    </span>
  )
}

/** The legend: every state named, with its icon and its colour sample. */
function DiffLegend() {
  return (
    <div className="flex flex-wrap items-center gap-x-4 gap-y-2 text-xs text-muted-foreground">
      <span className="font-medium text-foreground">Legend:</span>
      {(
        [
          "unchanged",
          "reworded",
          "added",
          "removed",
          "notCompared",
        ] as DiffStatus[]
      ).map((status) => (
        <span key={status} className="inline-flex items-center gap-1.5">
          <StatusChip status={status} />
        </span>
      ))}
    </div>
  )
}

/** One passage, rendered as one side of a comparison. */
function PassageCell({
  side,
  status,
  text,
  empty,
}: {
  side: "Original résumé" | "Tailored"
  status: DiffStatus
  text: string | null
  /** What to say when this side has no passage for the pair. */
  empty: string
}) {
  /*
    The wash follows the pair's meaning, not just its status: a replacement
    (reworded) washes the replaced original in terracotta and the new wording
    in lime; an addition is lime; a cleared passage is terracotta; unchanged
    stays neutral paper.
  */
  const wash =
    status === "unchanged"
      ? "border-border bg-card"
      : status === "added" || (status === "reworded" && side === "Tailored")
        ? "border-lime/70 bg-lime-soft/60"
        : status === "removed" ||
            (status === "reworded" && side === "Original résumé")
          ? "border-terracotta bg-terracotta-soft/60"
          : "border-dashed border-terracotta bg-terracotta-soft/30"
  return (
    <figure className={cn("min-w-0 rounded-xl border p-3", wash)}>
      <figcaption className="mb-1.5 flex flex-wrap items-center justify-between gap-2">
        <span className="text-[11px] font-semibold tracking-wide text-muted-foreground uppercase">
          {side}
        </span>
        <StatusChip status={status} />
      </figcaption>
      {text ? (
        <PlainText className="text-sm">
          {/* Unchanged passages read quieter than changed ones, so the eye
              lands on what the tailoring touched. */}
          <span
            className={
              status === "unchanged" ? "text-muted-foreground" : undefined
            }
          >
            {text}
          </span>
        </PlainText>
      ) : (
        <p className="text-sm text-muted-foreground italic">{empty}</p>
      )}
    </figure>
  )
}

/** One paired passage — two cells, aligned side-by-side or stacked. */
function PassageRow({
  pair,
  layout,
}: {
  pair: DiffPair
  layout: "side-by-side" | "stacked"
}) {
  if (pair.status === "notCompared") {
    // Not compared: shown once, full width, never split into two pretending
    // columns.
    const text = pair.original ?? pair.tailored ?? ""
    return (
      <div className="min-w-0 rounded-xl border border-dashed border-terracotta bg-terracotta-soft/30 p-3">
        <div className="mb-1.5 flex flex-wrap items-center justify-between gap-2">
          <span className="text-[11px] font-semibold tracking-wide text-muted-foreground uppercase">
            {pair.original !== null ? "Original résumé" : "Tailored"}
          </span>
          <StatusChip status="notCompared" />
        </div>
        <PlainText className="text-sm">{text}</PlainText>
      </div>
    )
  }
  if (layout === "side-by-side") {
    return (
      <div className="grid min-w-0 items-start gap-3 md:grid-cols-2">
        <PassageCell
          side="Original résumé"
          status={pair.status}
          text={pair.original}
          empty="Not in the original"
        />
        <PassageCell
          side="Tailored"
          status={pair.status}
          text={pair.tailored}
          empty="Removed from the tailored text"
        />
      </div>
    )
  }
  return (
    <div className="grid min-w-0 gap-2">
      <PassageCell
        side="Original résumé"
        status={pair.status}
        text={pair.original}
        empty="Not in the original"
      />
      <PassageCell
        side="Tailored"
        status={pair.status}
        text={pair.tailored}
        empty="Removed from the tailored text"
      />
    </div>
  )
}

/** A skills row: kept, filtered out, and (regenerated only) added. */
function SkillsBlock({ diff }: { diff: ResumeDiff }) {
  return (
    <div className="space-y-3">
      <SectionTitle>Skills</SectionTitle>
      <p className="text-sm text-muted-foreground">
        The tailored document keeps your own skills list, filtered to the
        selection the job rewards. Nothing was added to it.
      </p>
      <div className="space-y-2">
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-xs font-medium text-muted-foreground">
            Kept:
          </span>
          {diff.skills.kept.length === 0 ? (
            <span className="text-sm text-muted-foreground italic">
              none of the original skills survived the selection
            </span>
          ) : (
            diff.skills.kept.map((skill) => (
              <span
                key={`kept-${skill}`}
                className="inline-flex items-center gap-1 rounded-full border border-border bg-card px-2.5 py-0.5 text-xs text-foreground"
              >
                <Plus className="size-3 text-lime-foreground" aria-hidden />
                {skill}
              </span>
            ))
          )}
        </div>
        {diff.skills.removed.length > 0 ? (
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-xs font-medium text-muted-foreground">
              Filtered out:
            </span>
            {diff.skills.removed.map((skill) => (
              <span
                key={`removed-${skill}`}
                className="inline-flex items-center gap-1 rounded-full border border-terracotta bg-terracotta-soft px-2.5 py-0.5 text-xs text-terracotta-foreground"
              >
                <Minus className="size-3" aria-hidden />
                {skill}
              </span>
            ))}
          </div>
        ) : null}
        {diff.skills.added.length > 0 ? (
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-xs font-medium text-muted-foreground">
              Added by the rewrite:
            </span>
            {diff.skills.added.map((skill) => (
              <span
                key={`added-${skill}`}
                className="inline-flex items-center gap-1 rounded-full border border-lime/70 bg-lime-soft px-2.5 py-0.5 text-xs text-lime-foreground"
              >
                <Plus className="size-3" aria-hidden />
                {skill}
              </span>
            ))}
          </div>
        ) : null}
      </div>
    </div>
  )
}

/** A project note for the in-place deliverable. */
function ProjectsBlock({ diff }: { diff: ResumeDiff }) {
  if (diff.projects.state === "notEditedInPlace") {
    return (
      <div className="space-y-2">
        <SectionTitle>Projects</SectionTitle>
        <p className="text-sm text-muted-foreground">
          The in-place editor does not rewrite the projects section, so your
          projects survived the deliverable exactly as you wrote them. The
          tailoring did select these as relevant to the job — guidance, not a
          change to your file:
        </p>
        <ul className="list-disc space-y-1 pl-5 text-sm">
          {diff.projects.selected.length === 0 ? (
            <li className="text-muted-foreground">No projects selected.</li>
          ) : (
            diff.projects.selected.map((name) => <li key={name}>{name}</li>)
          )}
        </ul>
      </div>
    )
  }
  return (
    <div className="space-y-3">
      <SectionTitle>Projects</SectionTitle>
      <div className="space-y-4">
        {diff.projects.entries.map((entry, index) => (
          <EntryBlock
            key={`project-${entry.label}-${index}`}
            entry={entry}
            layout="side-by-side"
          />
        ))}
      </div>
    </div>
  )
}

/** One experience or project entry: header plus its paired bullets. */
function EntryBlock({
  entry,
  layout,
}: {
  entry: ResumeDiff["experience"][number]
  layout: "side-by-side" | "stacked"
}) {
  return (
    <div className="min-w-0 space-y-2">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="min-w-0">
          <p className="text-sm font-medium text-foreground">{entry.label}</p>
          {entry.dates ? (
            <p className="text-xs text-muted-foreground tabular-nums">
              {entry.dates}
            </p>
          ) : null}
        </div>
        <StatusChip status={entry.status} />
      </div>
      {entry.note ? (
        <p className="text-xs text-terracotta-foreground">{entry.note}</p>
      ) : null}
      <div className="space-y-2">
        {entry.bullets.map((pair, index) => (
          <PassageRow
            key={`bullet-${entry.label}-${index}`}
            pair={pair}
            layout={layout}
          />
        ))}
      </div>
    </div>
  )
}

/** The full comparison: legend, view toggle, and every section. */
export function ResumeDiffView({
  profile,
  tailored,
  render,
}: {
  profile: CandidateProfile
  tailored: TailoredResume
  render: RenderReport
}) {
  const diff = buildResumeDiff(profile, tailored, render)
  const [layout, setLayout] = useState<"side-by-side" | "stacked">(
    "side-by-side"
  )
  const effectiveLayout = layout

  return (
    <div className="space-y-5">
      <Banner tone="info" title="Read-only comparison">
        <p>
          This compares the résumé you uploaded (as the parser read it) with the
          tailored text the agent delivered. Nothing here can be edited or
          accepted line by line — the delivered file is fixed, and per-change
          review is not built yet. The rendered file on the Overview tab is the
          deliverable of record.
        </p>
      </Banner>

      <div className="flex flex-wrap items-center justify-between gap-3">
        <DiffLegend />
        <div className="hidden items-center gap-1 md:flex">
          <button
            type="button"
            aria-pressed={effectiveLayout === "side-by-side"}
            onClick={() => setLayout("side-by-side")}
            className={cn(
              "inline-flex h-8 items-center gap-1.5 rounded-lg border px-2.5 text-xs font-medium transition-colors",
              effectiveLayout === "side-by-side"
                ? "border-primary bg-primary text-primary-foreground"
                : "border-border bg-card text-muted-foreground hover:text-foreground"
            )}
          >
            <Columns2 className="size-3.5" aria-hidden />
            Side-by-side
          </button>
          <button
            type="button"
            aria-pressed={effectiveLayout === "stacked"}
            onClick={() => setLayout("stacked")}
            className={cn(
              "inline-flex h-8 items-center gap-1.5 rounded-lg border px-2.5 text-xs font-medium transition-colors",
              effectiveLayout === "stacked"
                ? "border-primary bg-primary text-primary-foreground"
                : "border-border bg-card text-muted-foreground hover:text-foreground"
            )}
          >
            <Rows3 className="size-3.5" aria-hidden />
            Stacked
          </button>
        </div>
      </div>

      <p className="flex items-center gap-1.5 text-xs text-muted-foreground">
        <Eye className="size-3.5" aria-hidden />
        On a narrow screen the two columns stack with their labels; every
        passage keeps its own "Original" and "Tailored" marking.
      </p>

      <div className="space-y-8">
        {diff.summary ? (
          <div className="space-y-3">
            <SectionTitle>Summary</SectionTitle>
            <PassageRow pair={diff.summary} layout={effectiveLayout} />
          </div>
        ) : null}

        <SkillsBlock diff={diff} />

        <div className="space-y-3">
          <SectionTitle>Experience</SectionTitle>
          {diff.experience.length === 0 ? (
            <p className="text-sm text-muted-foreground">
              No experience entries to compare.
            </p>
          ) : (
            <div className="space-y-6">
              {diff.experience.map((entry, index) => (
                <EntryBlock
                  key={`experience-${entry.label}-${index}`}
                  entry={entry}
                  layout={effectiveLayout}
                />
              ))}
            </div>
          )}
        </div>

        <ProjectsBlock diff={diff} />
      </div>
    </div>
  )
}
