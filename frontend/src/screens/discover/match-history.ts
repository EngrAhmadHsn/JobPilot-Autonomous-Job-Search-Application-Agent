import { asNumber, asRecord, asStringArray } from "@/lib/safe"
import type { JobMatchResult } from "@/lib/api/types"

/*
  The match of one persisted history row, rebuilt (WS-36).

  The matches-history endpoint stores the component scores in a free-form
  dictionary — the table has no schema for them — so the console reads them
  through the safe accessors and rebuilds the same shape the search response
  uses.

  This is a **screen-local mirror**, kept byte-equivalent to the two copies
  that already exist (`job-detail-screen.tsx`'s `matchFromHistory` and
  `screens/overview/match-history.ts`'s `matchFromHistoryEntry`, the latter
  landed by WS-35). WS-36 needs the rebuild in a third place — the Discover
  detail panel resolves a deep-linked job's match from the history when the
  job is not in the loaded search slice. The shared extraction is the LEAD's
  Wave-4 work (all three consumers, one module); until it lands, this copy
  must not drift, and any change here is a change to make in all three.
*/

export interface MatchHistoryEntry {
  job_id?: unknown
  scores?: unknown
  explanation?: unknown
  sponsor_status?: unknown
  sponsor_note?: unknown
}

export function matchFromHistoryEntry(
  entry: MatchHistoryEntry | undefined
): JobMatchResult | null {
  if (!entry) return null
  const scores = asRecord(entry.scores)
  return {
    overall_score: asNumber(scores.overall_score),
    semantic_score: asNumber(scores.semantic_score),
    lexical_score: asNumber(scores.lexical_score),
    skill_score: asNumber(scores.skill_score),
    experience_score: asNumber(scores.experience_score),
    seniority_score: asNumber(scores.seniority_score),
    location_score: asNumber(scores.location_score),
    preference_score: asNumber(scores.preference_score),
    // WS-21: older persisted rows predate the role fields; the accessors
    // default them safely (no role evidence — never a fabricated match).
    role_score: asNumber(scores.role_score),
    role_family:
      typeof scores.role_family === "string" ? scores.role_family : null,
    role_family_confidence: asNumber(scores.role_family_confidence),
    role_targets: asStringArray(scores.role_targets),
    role_target_source:
      typeof scores.role_target_source === "string"
        ? scores.role_target_source
        : "none",
    role_capped: scores.role_capped === true,
    evidence_coverage: asNumber(scores.evidence_coverage),
    component_states: asRecord(scores.component_states) as Record<
      string,
      string
    >,
    notes: asStringArray(scores.notes),
    missing_requirements: asStringArray(scores.missing_requirements),
    matched_requirements: asStringArray(scores.matched_requirements),
    missing_keywords: asStringArray(scores.missing_keywords),
    matched_keywords: asStringArray(scores.matched_keywords),
    // WS-22: the sponsorship finding rides on the serialized match row.
    sponsor_status:
      typeof entry.sponsor_status === "string" ? entry.sponsor_status : null,
    sponsor_note:
      typeof entry.sponsor_note === "string" ? entry.sponsor_note : null,
    explanation: typeof entry.explanation === "string" ? entry.explanation : "",
  }
}
