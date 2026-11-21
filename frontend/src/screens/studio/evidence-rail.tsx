import { useState } from "react"

import { Check, CircleAlert, Sparkles } from "lucide-react"
import { cn } from "cn"

import { PlainText } from "@/components/common/plain-text"
import { LinkButton } from "@/components/ui/link-button"
import type {
  CandidateProfile,
  KeywordCoverage,
  TailorResponse,
} from "@/lib/api/types"

import {
  coverageIsMeasurable,
  keywordEvidence,
  keywordSupported,
  type KeywordEvidence,
} from "./diff-model"

/*
  The evidence rail of the Resume Studio (WS-42, design node `49:997` —
  "Make every claim count."; WS-47 tightens it to the design's right card).

  The design's rail: required and preferred keyword progress with the counts
  in the labels, the matched and not-evidenced terms as washes under dark
  headings, the sentence that missing keywords are gaps — not permission to
  invent — the factuality chip under its own divider, and the step to review
  as the card's last element. The console adds one group the design's
  example never needed: terms the candidate's own profile states but the
  tailoring did not emphasize. Erasing that distinction would read as
  permission to quietly absorb a gap, and the backend draws the same line
  itself (`_keyword_supported`, `src/resume/ats.py`).

  Where the design's example can say "0 unsupported claims" and stop, this
  rail derives the chip from the real factuality report: a stripped claim
  is named, never smoothed over. And the deliverable caption adapts to how
  the document was actually produced — an in-place edit has no regenerated
  layout to check, and a rewrite names the format the delivered file really
  is (`deliverableFormat`, WS-47), which is the design's own "Check
  regenerated DOCX layout before export." made true per case.
*/

type TermState = "hit" | "supported" | "gap"

const STATE_META: Record<
  TermState,
  { label: string; icon: typeof Check; chipClass: string }
> = {
  hit: {
    label: "In the tailored resume",
    icon: Check,
    chipClass: "bg-lime-soft text-lime-foreground",
  },
  supported: {
    label: "In your profile, not emphasized",
    icon: Sparkles,
    chipClass: "bg-terracotta-soft text-terracotta-foreground",
  },
  gap: {
    label: "Not in your source evidence",
    icon: CircleAlert,
    chipClass: "bg-terracotta-soft text-terracotta-foreground",
  },
}

const SOURCE_LABEL: Record<KeywordEvidence["source"], string> = {
  skills: "Skills",
  experience: "Experience",
  projects: "Projects",
  summary: "Summary",
}

/** One selectable keyword wash (design chip: r=6, pad 4/9, 11/600). */
function KeywordChip({
  term,
  state,
  selected,
  onToggle,
}: {
  term: string
  state: TermState
  selected: boolean
  onToggle: () => void
}) {
  const meta = STATE_META[state]
  const Icon = meta.icon
  return (
    <button
      type="button"
      aria-pressed={selected}
      onClick={onToggle}
      title={`${term} — ${meta.label}. Select for the evidence.`}
      aria-label={`${term} — ${meta.label}`}
      className={cn(
        "inline-flex items-center gap-1 rounded-[6px] px-2.5 py-1 text-[11px] font-semibold transition-colors",
        selected ? "bg-primary text-primary-foreground" : meta.chipClass,
        "outline-none focus-visible:ring-2 focus-visible:ring-ring/60"
      )}
    >
      <Icon className="size-3" aria-hidden />
      {term}
    </button>
  )
}

/** The three states, named in text — colour and icon are never the only cue. */
function StateLegend() {
  return (
    <div className="flex flex-wrap items-center gap-x-4 gap-y-1.5 text-[11px] text-muted-foreground">
      <span className="font-semibold text-foreground">Reading the terms:</span>
      {(["hit", "supported", "gap"] as TermState[]).map((state) => {
        const meta = STATE_META[state]
        const Icon = meta.icon
        return (
          <span key={state} className="inline-flex items-center gap-1.5">
            <Icon className="size-3" aria-hidden />
            {meta.label}
          </span>
        )
      })}
    </div>
  )
}

/** One coverage meter (design `49:999`–`49:1004`): label + 6 px track. */
function CoverageMeter({
  label,
  hit,
  total,
  fill,
}: {
  label: string
  hit: number
  total: number
  fill: string
}) {
  return (
    <div className="space-y-1.5">
      <p className="text-[13px] leading-[19px] font-semibold text-primary">
        {label} · {hit} of {total}
      </p>
      {/*
        A plain div, not a `role="progressbar"`: the fraction is already in
        the label's own text, and a second reading of "78%" would only
        double what the label says.
      */}
      <div className="h-1.5 w-full overflow-hidden rounded-full bg-forest-soft">
        <div
          className={cn("h-full rounded-full", fill)}
          style={{
            width: `${total > 0 ? Math.round((hit / total) * 100) : 0}%`,
          }}
        />
      </div>
    </div>
  )
}

/** The evidence a selected term carries — or the honest absence of any. */
function EvidenceBlock({
  term,
  profile,
}: {
  term: string
  profile: CandidateProfile
}) {
  const evidence = keywordEvidence(term, profile)
  return (
    <div className="rounded-surface border border-border-surface bg-card/60 p-3">
      <p className="text-xs font-semibold text-foreground">
        Evidence for “{term}”
      </p>
      {evidence.length === 0 ? (
        <p className="mt-1.5 text-sm text-muted-foreground">
          Your résumé and profile never state this term. The panel leaves the
          gap honest rather than proposing wording you have no evidence for.
        </p>
      ) : (
        <ul className="mt-2 space-y-1.5">
          {evidence.map((item, index) => (
            <li
              key={`evidence-${term}-${index}`}
              className="text-xs text-muted-foreground"
            >
              <PlainText as="span" className="text-xs">
                {`${SOURCE_LABEL[item.source]} · ${item.text}`}
              </PlainText>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

/** A heading + wash group in the rail. */
function ChipGroup({
  heading,
  headingClass,
  terms,
  state,
  selected,
  onSelect,
}: {
  heading: string
  headingClass: string
  terms: string[]
  /** Every term in a group holds one state — the group heading is the state. */
  state: TermState
  selected: string | null
  onSelect: (term: string | null) => void
}) {
  if (terms.length === 0) return null
  return (
    <div className="space-y-2">
      <p
        className={cn("text-[13px] leading-[19px] font-semibold", headingClass)}
      >
        {heading}
      </p>
      <div className="flex flex-wrap items-center gap-2">
        {terms.map((term) => (
          <KeywordChip
            key={`${heading}-${term}`}
            term={term}
            state={state}
            selected={selected === term}
            onToggle={() => onSelect(selected === term ? null : term)}
          />
        ))}
      </div>
    </div>
  )
}

/**
 * The format of the **deliverable**, named for the caption (WS-47).
 *
 * An in-place deliverable keeps the uploaded format (WS-31), so the label is
 * that format. A regenerated deliverable is the renderer's output — a DOCX,
 * except for a text upload the fallback renderer carried through — so the
 * label names what the file really is, never the unknown source. "Check the
 * regenerated document layout" told the candidate nothing; the design's own
 * sentence names the format, and the honest version does too.
 */
function deliverableFormat(render: TailorResponse["render"]): string {
  const format = render.source_format.toLowerCase()
  if (render.mode === "in_place") {
    return format === "none" || format === ""
      ? "document"
      : format.replace(".", "").toUpperCase()
  }
  if (format === ".txt" || format === ".md") {
    return format.slice(1).toUpperCase()
  }
  return "DOCX"
}

/** The whole rail: keywords, the factuality verdict, and the step to review. */
export function EvidenceRail({
  coverage,
  profile,
  factuality,
  render,
}: {
  coverage: KeywordCoverage
  profile: CandidateProfile
  factuality: TailorResponse["factuality"]
  render: TailorResponse["render"]
}) {
  const [selected, setSelected] = useState<string | null>(null)
  const skills = profile.skills
  const measurable = coverageIsMeasurable(coverage)

  const requiredTotal =
    coverage.required_hit.length + coverage.required_missing.length
  const preferredTotal =
    coverage.preferred_hit.length + coverage.preferred_missing.length
  const supported = (term: string) => keywordSupported(term, skills)
  /*
    A term can be listed in both the required and the preferred set; the
    groups dedupe, or one wash would render twice (and collide as a React
    key) — the defect the WS-42 pass already caught once in another queue.
  */
  const matched = [
    ...new Set([...coverage.required_hit, ...coverage.preferred_hit]),
  ]
  const missing = [
    ...new Set([...coverage.required_missing, ...coverage.preferred_missing]),
  ]
  const profileBacked = missing.filter(supported)
  const gaps = missing.filter((term) => !supported(term))

  const removed =
    factuality.removed_skills.length +
    factuality.removed_experience.length +
    factuality.removed_projects.length

  return (
    <aside className="flex min-w-0 flex-col gap-4 rounded-surface border border-border-surface bg-card p-6">
      <h2 className="text-[22px] leading-[30px] font-semibold text-primary">
        Make every claim count.
      </h2>

      {measurable ? (
        <div className="space-y-3.5">
          <CoverageMeter
            label="Required keywords"
            hit={coverage.required_hit.length}
            total={requiredTotal}
            fill="bg-progress-required"
          />
          <CoverageMeter
            label="Preferred keywords"
            hit={coverage.preferred_hit.length}
            total={preferredTotal}
            fill="bg-progress-preferred"
          />
        </div>
      ) : (
        <div className="rounded-surface border border-dashed border-border-surface p-4">
          <p className="text-sm font-medium text-foreground">
            Coverage could not be measured
          </p>
          <p className="mt-1.5 text-sm leading-relaxed text-muted-foreground">
            This listing declares no structured skill requirements, so there is
            nothing to measure the resume against. The ATS analyzer scored
            keywords neutrally rather than pretending a perfect or a zero score.
            Read the listing yourself and check the terms that matter — the
            resume text is on the Inline diff tab.
          </p>
        </div>
      )}

      {measurable ? (
        <>
          <ChipGroup
            heading="Matched in your source"
            headingClass="text-primary"
            terms={matched}
            state="hit"
            selected={selected}
            onSelect={setSelected}
          />
          <ChipGroup
            heading="In your profile, not emphasized"
            headingClass="text-terracotta-foreground"
            terms={profileBacked}
            state="supported"
            selected={selected}
            onSelect={setSelected}
          />
          <ChipGroup
            heading="Not evidenced"
            headingClass="text-primary"
            terms={gaps}
            state="gap"
            selected={selected}
            onSelect={setSelected}
          />
          <p className="text-[13px] leading-[19px] text-muted-foreground">
            Missing keywords are gaps, not permission to invent experience.
          </p>
          <StateLegend />
        </>
      ) : null}

      {selected ? (
        <EvidenceBlock term={selected} profile={profile} />
      ) : (
        <p className="text-[11px] leading-4 text-muted-foreground">
          <Sparkles className="mr-1 inline size-3 align-[-1px]" aria-hidden />
          “In your profile, not emphasized” marks a term your own résumé
          supports — the tailoring could surface it, and whether to is your
          call. Nothing is added automatically.
        </p>
      )}

      <div className="h-px w-full shrink-0 bg-border-surface" aria-hidden />

      <div className="space-y-1.5">
        {factuality.passed ? (
          <span className="inline-flex items-center rounded-[6px] bg-lime-soft px-2.5 py-1 text-[11px] font-semibold text-lime-foreground">
            0 unsupported claims
          </span>
        ) : (
          <span className="inline-flex items-center rounded-[6px] bg-terracotta-soft px-2.5 py-1 text-[11px] font-semibold text-terracotta-foreground">
            {removed} unsupported claim{removed === 1 ? "" : "s"} stripped
          </span>
        )}
        <p className="text-xs leading-[17px] text-muted-foreground">
          {render.mode === "in_place"
            ? "Original preserved. Your own file was edited in place — check the delivered layout before export."
            : `Original preserved. Check the regenerated ${deliverableFormat(render)} layout before export.`}
        </p>
      </div>

      <div>
        <LinkButton to="/app/approvals">Continue to review →</LinkButton>
      </div>
    </aside>
  )
}
