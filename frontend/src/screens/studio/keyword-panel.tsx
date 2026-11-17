import { useState } from "react"

import { Check, CircleAlert, Sparkles } from "lucide-react"
import { cn } from "cn"

import { SectionTitle } from "@/components/common/field-list"
import { PlainText } from "@/components/common/plain-text"
import type { CandidateProfile, KeywordCoverage } from "@/lib/api/types"

import {
  coverageIsMeasurable,
  keywordEvidence,
  keywordSupported,
  type KeywordEvidence,
} from "./diff-model"

/*
  The keyword coverage and evidence panel (WS-37, reference panel 3's
  "Keyword Matching" column).

  Required and preferred coverage are kept **separate** with the real
  matched and missing terms from `AtsReport.keyword_coverage`. Every missing
  term gets the only distinction the data model can honestly support:

  - **Present in the tailored resume** — the coverage report itself;
  - **Supported by your profile, not surfaced** — the term appears in the
    parsed profile's skills, so the tailoring could legitimately emphasize
    it; the panel may propose it, but nothing here adds it for you;
  - **Not in your source evidence** — neither the resume nor the profile
    states it. An honest gap, never proposed.

  The backend draws the same line itself (`_keyword_supported`,
  `src/resume/ats.py`) and writes it into the report notes; the ATS panel
  shows those notes verbatim. No percentage here claims ATS acceptance or an
  interview, and when the listing declares no structured skills the panel
  says coverage could not be measured — never a misleading 100% or 0%.
*/

type TermState = "hit" | "supported" | "gap"

function stateForTerm(term: string, hit: boolean, skills: string[]): TermState {
  if (hit) return "hit"
  return keywordSupported(term, skills) ? "supported" : "gap"
}

const STATE_META: Record<
  TermState,
  { label: string; chipClass: string; icon: typeof Check }
> = {
  hit: {
    label: "In the tailored resume",
    icon: Check,
    chipClass: "border-lime/70 bg-lime-soft text-lime-foreground",
  },
  supported: {
    label: "In your profile, not emphasized",
    icon: Sparkles,
    chipClass:
      "border-terracotta bg-terracotta-soft text-terracotta-foreground",
  },
  gap: {
    label: "Not in your source evidence",
    icon: CircleAlert,
    chipClass: "border-border bg-muted text-muted-foreground",
  },
}

const SOURCE_LABEL: Record<KeywordEvidence["source"], string> = {
  skills: "Skills",
  experience: "Experience",
  projects: "Projects",
  summary: "Summary",
}

/** One selectable keyword chip. */
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
        "inline-flex items-center gap-1 rounded-full border px-2.5 py-0.5 text-xs font-medium transition-colors",
        selected
          ? "border-primary bg-primary text-primary-foreground"
          : meta.chipClass
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
    <div className="flex flex-wrap items-center gap-x-4 gap-y-1.5 text-xs text-muted-foreground">
      <span className="font-medium text-foreground">Reading the terms:</span>
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

/** One coverage group: required or preferred. */
function CoverageGroup({
  title,
  hit,
  missing,
  skills,
  selectedTerm,
  onSelect,
}: {
  title: string
  hit: string[]
  missing: string[]
  skills: string[]
  selectedTerm: string | null
  onSelect: (term: string | null) => void
}) {
  return (
    <div className="space-y-2.5">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <SectionTitle>{title}</SectionTitle>
        <p className="text-xs text-muted-foreground tabular-nums">
          {hit.length} of {hit.length + missing.length} present
        </p>
      </div>
      {hit.length + missing.length === 0 ? (
        <p className="text-sm text-muted-foreground italic">
          The listing states none.
        </p>
      ) : (
        <div className="flex flex-wrap items-center gap-2">
          {hit.map((term) => (
            <KeywordChip
              key={`hit-${term}`}
              term={term}
              state="hit"
              selected={selectedTerm === term}
              onToggle={() => onSelect(selectedTerm === term ? null : term)}
            />
          ))}
          {missing.map((term) => {
            const state = stateForTerm(term, false, skills)
            return (
              <KeywordChip
                key={`missing-${term}`}
                term={term}
                state={state}
                selected={selectedTerm === term}
                onToggle={() => onSelect(selectedTerm === term ? null : term)}
              />
            )
          })}
        </div>
      )}
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
    <div className="rounded-xl border border-border bg-card/60 p-3">
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

/** The whole keyword coverage panel. */
export function KeywordPanel({
  coverage,
  profile,
}: {
  coverage: KeywordCoverage
  profile: CandidateProfile
}) {
  const [selected, setSelected] = useState<string | null>(null)
  const skills = profile.skills

  if (!coverageIsMeasurable(coverage)) {
    return (
      <div className="space-y-3">
        <div className="flex flex-wrap items-baseline justify-between gap-2">
          <h3 className="font-heading text-base font-semibold tracking-tight text-foreground">
            Keyword matching
          </h3>
        </div>
        <div className="rounded-xl border border-dashed border-border bg-card/60 p-4">
          <p className="text-sm font-medium text-foreground">
            Coverage could not be measured
          </p>
          <p className="mt-1.5 text-sm leading-relaxed text-muted-foreground">
            This listing declares no structured skill requirements, so there is
            nothing to measure the resume against. The ATS analyzer scored
            keywords neutrally rather than pretending a perfect or a zero score.
            Read the listing yourself and check the terms that matter — the
            resume text is on the Resume tab.
          </p>
        </div>
      </div>
    )
  }

  return (
    <div className="space-y-5">
      <div className="space-y-1">
        <h3 className="font-heading text-base font-semibold tracking-tight text-foreground">
          Keyword matching
        </h3>
        <p className="text-sm text-muted-foreground">
          Measured against the structured requirements the listing states.
          Select a term to see where your profile mentions it. Coverage is a
          measurement — never a promise of acceptance or an interview.
        </p>
      </div>

      <CoverageGroup
        title="Required"
        hit={coverage.required_hit}
        missing={coverage.required_missing}
        skills={skills}
        selectedTerm={selected}
        onSelect={setSelected}
      />

      <CoverageGroup
        title="Preferred"
        hit={coverage.preferred_hit}
        missing={coverage.preferred_missing}
        skills={skills}
        selectedTerm={selected}
        onSelect={setSelected}
      />

      <StateLegend />

      {selected ? (
        <EvidenceBlock term={selected} profile={profile} />
      ) : (
        <p className="text-xs text-muted-foreground">
          <Sparkles className="mr-1 inline size-3 align-[-1px]" aria-hidden />
          “In your profile, not emphasized” marks a term your own résumé
          supports — the tailoring could surface it, and whether to is your
          call. Nothing is added automatically.
        </p>
      )}
    </div>
  )
}
