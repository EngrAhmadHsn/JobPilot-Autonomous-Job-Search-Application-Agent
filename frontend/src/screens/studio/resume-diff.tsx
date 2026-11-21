import { useState } from "react"

import {
  CircleAlert,
  Columns2,
  Minus,
  PenLine,
  Plus,
  Rows3,
  Type,
} from "lucide-react"
import { cn } from "cn"

import { PlainText } from "@/components/common/plain-text"
import {
  buildResumeDiff,
  type DiffPair,
  type RenderReport,
  type ResumeDiff,
} from "./diff-model"
import type { CandidateProfile, TailoredResume } from "@/lib/api/types"

/*
  The document canvas of the Resume Studio (WS-42, design node `16:82`;
  WS-47 adds the edit entry point and the toolbar's format truth).

  The design draws the comparison as the tailored document itself: a paper
  sheet on a sage desk mat, where every changed passage is a full-width
  wash — the original wording on clay (the colour of "a human should look
  at this"), the tailored wording on the lime of the agent's mark — with a
  provenance line under each changed passage naming where the wording came
  from (node `49:996`: "Source: experience, bullet 2 · wording changed, no
  new claims added.").

  The provenance line is only claimed when the factuality validator passed:
  "no new claims added" is the validator's finding, not this screen's
  assertion. When the check stripped items, the line says only what the
  comparison itself proves, and the banner above the tabs carries the
  verdict.

  Two deliberate departures from the design's example, both because colour
  is never the only signal: every wash also carries a text caption (which
  side it is) and a status chip (what happened to it), and the five states
  the data model actually has — the design's example only exercises two —
  each render with their own words.

  The toolbar row keeps the design's composition but states **facts** where
  the design's mock drew editor controls: the B / I / U buttons would lie
  about a comparison the in-place editor cannot regenerate run formatting
  through, so the row's first control is the deliverable's real format from
  the render report ("Body · DOCX" — the WS-31 truth) beside the design's
  own two-chip legend, and the last is the one real edit this surface has:
  Edit draft, which opens the studio's section editor (WS-47).
*/

/**
 * The deliverable's format, named from the render report (WS-47).
 *
 * An in-place deliverable keeps the uploaded format (WS-31), so the label is
 * that format. A regenerated deliverable is a fresh document — the renderer's
 * DOCX, or the text fallback for an upload the text editor could not carry —
 * and the label says "regenerated", because promising an edit that did not
 * happen is the exact defect WS-31 fixed.
 */
export function sourceFormatLabel(render: RenderReport): string {
  const format = render.source_format.replace(".", "").toUpperCase()
  const known = format && format !== "NONE"
  if (render.mode === "in_place") {
    return known ? `Body · ${format}` : "Body · document"
  }
  return known ? `Body · regenerated ${format}` : "Body · regenerated document"
}

/** The toolbar row's format chip: what the deliverable really is. */
export function FormatChip({ render }: { render: RenderReport }) {
  const label = sourceFormatLabel(render)
  const detail =
    render.mode === "in_place"
      ? "The deliverable keeps your uploaded format; the original file itself is never modified."
      : "The original could not be edited in place, so a fresh document was rendered."
  return (
    <span
      title={detail}
      className="inline-flex h-8 items-center gap-1.5 rounded-lg border border-border-surface bg-card px-2.5 text-xs font-medium text-foreground"
    >
      <Type className="size-3.5 text-muted-foreground" aria-hidden />
      {label}
    </span>
  )
}

type DiffStatus = DiffPair["status"]

const STATUS_META: Record<
  DiffStatus,
  { label: string; icon: typeof Plus; chipClass: string }
> = {
  unchanged: {
    label: "Unchanged",
    icon: Minus,
    chipClass: "bg-muted text-muted-foreground",
  },
  reworded: {
    label: "Reworded",
    icon: PenLine,
    chipClass: "bg-terracotta-soft text-terracotta-foreground",
  },
  added: {
    label: "Added",
    icon: Plus,
    chipClass: "bg-lime-soft text-lime-foreground",
  },
  removed: {
    label: "Cleared",
    icon: Minus,
    chipClass: "bg-terracotta-soft text-terracotta-foreground",
  },
  notCompared: {
    label: "Not compared — manual review required",
    icon: CircleAlert,
    chipClass: "bg-terracotta-soft text-terracotta-foreground",
  },
}

function StatusChip({ status }: { status: DiffStatus }) {
  const meta = STATUS_META[status]
  const Icon = meta.icon
  return (
    <span
      className={cn(
        "inline-flex shrink-0 items-center gap-1 rounded-[6px] px-2 py-0.5 text-[11px] font-semibold",
        meta.chipClass
      )}
    >
      <Icon className="size-3" aria-hidden />
      {meta.label}
    </span>
  )
}

/** The design's two-chip legend (node `49:981`): which wash is which side. */
function DiffLegend() {
  return (
    <div className="flex flex-wrap items-center gap-2.5">
      <span className="inline-flex items-center gap-1.5 rounded-[6px] bg-terracotta-soft px-2.5 py-1 text-[11px] font-semibold text-terracotta-foreground">
        <Minus className="size-3" aria-hidden />
        Original wording
      </span>
      <span className="inline-flex items-center gap-1.5 rounded-[6px] bg-lime-soft px-2.5 py-1 text-[11px] font-semibold text-lime-foreground">
        <Plus className="size-3" aria-hidden />
        Tailored wording
      </span>
    </div>
  )
}

/**
 * The provenance line under a changed passage (node `49:996`).
 *
 * Each clause is something the comparison or the validator actually
 * established — never a generic reassurance. Unchanged passages carry no
 * line: their provenance is themselves, and the status chip already says
 * so quietly.
 */
function provenanceLine(
  section: string,
  detail: string | null,
  status: DiffStatus,
  claimsVerified: boolean
): string | null {
  const where = detail ? `${section}, ${detail}` : section
  switch (status) {
    case "reworded":
      return `Source: ${where} · wording changed${claimsVerified ? ", no new claims added" : ""}.`
    case "added":
      return `Source: ${where} · not in the original wording${claimsVerified ? ", built from your own facts" : ""}.`
    case "removed":
      return `Source: ${where} · cleared from the tailored text.`
    default:
      return null
  }
}

/** One wash: a side of the comparison, captioned and status-chipped. */
function PassageBlock({
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
  const isOriginal = side === "Original résumé"
  /*
    The wash follows the pair's meaning, not just its status: a replacement
    (reworded) washes the replaced original in clay and the new wording in
    lime; an addition is lime; a cleared passage is clay; unchanged stays
    neutral paper. (`49:987` / `49:989` — `#f8e9e2` and `#eef9c4`.)
  */
  const wash =
    status === "unchanged"
      ? "border border-border-surface bg-card"
      : status === "added" || (status === "reworded" && !isOriginal)
        ? "bg-lime-soft"
        : status === "removed" || (status === "reworded" && isOriginal)
          ? "bg-terracotta-soft"
          : "border border-dashed border-terracotta bg-terracotta-soft/40"
  return (
    <figure className={cn("min-w-0 rounded-surface p-3", wash)}>
      <figcaption className="mb-1.5 flex flex-wrap items-center justify-between gap-2">
        <span className="text-[11px] font-semibold tracking-wide text-muted-foreground uppercase">
          {side}
        </span>
        <StatusChip status={status} />
      </figcaption>
      {text ? (
        <PlainText className="text-sm leading-relaxed">
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

/** One paired passage — stacked (the design's presentation) or side-by-side. */
function PassagePair({
  pair,
  layout,
}: {
  pair: DiffPair
  layout: "stacked" | "side-by-side"
}) {
  if (pair.status === "notCompared") {
    // Not compared: shown once, full width, never split into two pretending
    // columns.
    const text = pair.original ?? pair.tailored ?? ""
    return (
      <div className="min-w-0 rounded-surface border border-dashed border-terracotta bg-terracotta-soft/40 p-3">
        <div className="mb-1.5 flex flex-wrap items-center justify-between gap-2">
          <span className="text-[11px] font-semibold tracking-wide text-muted-foreground uppercase">
            {pair.original !== null ? "Original résumé" : "Tailored"}
          </span>
          <StatusChip status="notCompared" />
        </div>
        <PlainText className="text-sm leading-relaxed">{text}</PlainText>
      </div>
    )
  }
  const original = (
    <PassageBlock
      side="Original résumé"
      status={pair.status}
      text={pair.original}
      empty="Not in the original"
    />
  )
  const tailored = (
    <PassageBlock
      side="Tailored"
      status={pair.status}
      text={pair.tailored}
      empty="Removed from the tailored text"
    />
  )
  if (layout === "side-by-side") {
    return (
      <div className="grid min-w-0 items-start gap-3 md:grid-cols-2">
        {original}
        {tailored}
      </div>
    )
  }
  return (
    <div className="grid min-w-0 gap-2">
      {original}
      {tailored}
    </div>
  )
}

/** A section heading on the paper: `13/600`, forest, uppercase. */
function DocSectionLabel({ children }: { children: string }) {
  return (
    <h3 className="text-[13px] leading-[19px] font-semibold text-primary uppercase">
      {children}
    </h3>
  )
}

/** One provenance caption, in the design's 11/400 muted voice. */
function Provenance({ line }: { line: string }) {
  return <p className="text-[11px] leading-4 text-muted-foreground">{line}</p>
}

/** A skills row: kept, filtered out, and (regenerated only) added. */
function SkillsBlock({ diff }: { diff: ResumeDiff }) {
  const chip =
    "inline-flex items-center gap-1 rounded-[6px] px-2.5 py-1 text-[11px] font-semibold"
  return (
    <section className="min-w-0 space-y-2.5">
      <DocSectionLabel>Skills</DocSectionLabel>
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
                className={cn(chip, "bg-lime-soft text-lime-foreground")}
              >
                <Plus className="size-3" aria-hidden />
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
                className={cn(
                  chip,
                  "bg-terracotta-soft text-terracotta-foreground"
                )}
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
                className={cn(chip, "bg-lime-soft text-lime-foreground")}
              >
                <Plus className="size-3" aria-hidden />
                {skill}
              </span>
            ))}
          </div>
        ) : null}
      </div>
    </section>
  )
}

/** A project note for the in-place deliverable. */
function ProjectsBlock({
  diff,
  claimsVerified,
  layout,
}: {
  diff: ResumeDiff
  claimsVerified: boolean
  layout: "stacked" | "side-by-side"
}) {
  if (diff.projects.state === "notEditedInPlace") {
    return (
      <section className="min-w-0 space-y-2.5">
        <DocSectionLabel>Projects</DocSectionLabel>
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
      </section>
    )
  }
  return (
    <section className="min-w-0 space-y-2.5">
      <DocSectionLabel>Projects</DocSectionLabel>
      <div className="space-y-4">
        {diff.projects.entries.map((entry, index) => (
          <EntryBlock
            key={`project-${entry.label}-${index}`}
            section="projects"
            entry={entry}
            claimsVerified={claimsVerified}
            layout={layout}
          />
        ))}
      </div>
    </section>
  )
}

/** One experience or project entry: header plus its paired bullets. */
function EntryBlock({
  section,
  entry,
  claimsVerified,
  layout,
}: {
  section: "experience" | "projects"
  entry: ResumeDiff["experience"][number]
  claimsVerified: boolean
  layout: "stacked" | "side-by-side"
}) {
  return (
    <div className="min-w-0 space-y-2.5">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="min-w-0">
          <p className="text-[13px] font-semibold text-primary">
            {entry.label}
          </p>
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
      <div className="space-y-2.5">
        {entry.bullets.map((pair, index) => {
          const line = provenanceLine(
            section,
            entry.bullets.length > 1 ? `bullet ${index + 1}` : entry.label,
            pair.status,
            claimsVerified
          )
          return (
            <div key={`bullet-${entry.label}-${index}`} className="space-y-1.5">
              <PassagePair pair={pair} layout={layout} />
              {line ? <Provenance line={line} /> : null}
            </div>
          )
        })}
      </div>
    </div>
  )
}

/** The full canvas: the design's paper sheet, with every real section. */
export function ResumeDiffView({
  profile,
  tailored,
  render,
  jobTitle,
  company,
  claimsVerified,
  onStartEdit,
}: {
  profile: CandidateProfile
  tailored: TailoredResume
  render: RenderReport
  jobTitle: string
  company: string
  /** The factuality validator passed: provenance may claim verified wording. */
  claimsVerified: boolean
  /** WS-47: opens the studio's section editor. Absent while already editing. */
  onStartEdit?: () => void
}) {
  const diff = buildResumeDiff(profile, tailored, render)
  /*
    The design's presentation is the default: full-width stacked washes,
    original first. Side-by-side stays one click away for a wide screen.
  */
  const [layout, setLayout] = useState<"stacked" | "side-by-side">("stacked")
  const summaryLine = diff.summary
    ? provenanceLine("summary", null, diff.summary.status, claimsVerified)
    : null

  return (
    <div className="flex min-w-0 flex-col gap-3.5 rounded-surface bg-forest-soft p-4">
      {/* The toolbar row: the deliverable's real format, then the real controls. */}
      <div className="flex flex-wrap items-center justify-between gap-3">
        <FormatChip render={render} />
        <div className="flex items-center gap-2">
          <div className="hidden items-center gap-1 md:flex">
            <button
              type="button"
              aria-pressed={layout === "stacked"}
              onClick={() => setLayout("stacked")}
              className={cn(
                "inline-flex h-8 items-center gap-1.5 rounded-lg border px-2.5 text-xs font-medium transition-colors",
                layout === "stacked"
                  ? "border-primary bg-primary text-primary-foreground"
                  : "border-border-surface bg-card text-muted-foreground hover:text-foreground"
              )}
            >
              <Rows3 className="size-3.5" aria-hidden />
              Stacked
            </button>
            <button
              type="button"
              aria-pressed={layout === "side-by-side"}
              onClick={() => setLayout("side-by-side")}
              className={cn(
                "inline-flex h-8 items-center gap-1.5 rounded-lg border px-2.5 text-xs font-medium transition-colors",
                layout === "side-by-side"
                  ? "border-primary bg-primary text-primary-foreground"
                  : "border-border-surface bg-card text-muted-foreground hover:text-foreground"
              )}
            >
              <Columns2 className="size-3.5" aria-hidden />
              Side-by-side
            </button>
          </div>
          {onStartEdit ? (
            <button
              type="button"
              onClick={onStartEdit}
              className="inline-flex h-8 items-center gap-1.5 rounded-lg border border-primary bg-primary px-2.5 text-xs font-medium text-primary-foreground transition-colors outline-none hover:opacity-90 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring"
            >
              <PenLine className="size-3.5" aria-hidden />
              Edit draft
            </button>
          ) : null}
        </div>
      </div>

      {/* The paper (node `49:977`): `#fffdfa` on the sage mat, pad 30. */}
      <article className="flex min-w-0 flex-col gap-3.5 rounded-surface border border-border-surface bg-card p-[30px]">
        <h2 className="text-[22px] leading-8 font-semibold text-primary uppercase">
          {jobTitle}
        </h2>
        <p className="text-xs leading-[17px] text-muted-foreground">
          {company} · tailored draft · source preserved
        </p>
        <div className="h-px w-full shrink-0 bg-border-surface" aria-hidden />
        {/* The design's legend sits on the paper, under the meta line. */}
        <DiffLegend />

        {diff.summary ? (
          <section className="min-w-0 space-y-2.5">
            <DocSectionLabel>Professional summary</DocSectionLabel>
            <PassagePair pair={diff.summary} layout={layout} />
            {summaryLine ? <Provenance line={summaryLine} /> : null}
          </section>
        ) : null}

        <SkillsBlock diff={diff} />

        <section className="min-w-0 space-y-2.5">
          <DocSectionLabel>Experience</DocSectionLabel>
          {diff.experience.length === 0 ? (
            <p className="text-sm text-muted-foreground">
              No experience entries to compare.
            </p>
          ) : (
            <div className="space-y-5">
              {diff.experience.map((entry, index) => (
                <EntryBlock
                  key={`experience-${entry.label}-${index}`}
                  section="experience"
                  entry={entry}
                  claimsVerified={claimsVerified}
                  layout={layout}
                />
              ))}
            </div>
          )}
        </section>

        <ProjectsBlock
          diff={diff}
          claimsVerified={claimsVerified}
          layout={layout}
        />

        <p className="text-[11px] leading-4 text-muted-foreground">
          Read-only comparison — wording changes go through Edit draft above: a
          save revalidates the sections against your résumé and regenerates the
          deliverable. The Preview tab names the deliverable of record.
        </p>
      </article>
    </div>
  )
}
