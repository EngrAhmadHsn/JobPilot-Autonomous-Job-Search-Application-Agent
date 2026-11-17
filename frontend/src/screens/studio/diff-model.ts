import type {
  CandidateProfile,
  TailoredResume,
  TailorResponse,
} from "@/lib/api/types"

/** The render report, exactly as the tailoring response carries it. */
export type RenderReport = TailorResponse["render"]

/*
  The original-versus-tailored diff model (WS-37).

  **The pairing rules are the renderer's, not a similarity heuristic.** The
  backend editor (`src/resume/edit.py`) pairs a tailored experience entry to
  the original entry with the same normalized company and title, and a bullet
  to the original bullet at the same ordinal position — no fuzzy matching,
  because a wrong match would compare the wrong sentence of a real résumé.
  This module mirrors those rules in the same order, so the diff shows exactly
  what the editor would have touched:

  - summary: the document's single summary passage;
  - skills: item-level — the tailored selection filters the original list, it
    never adds a skill the document does not state;
  - experience: entries by `(normalize(title), normalize(company))`, bullets
    by ordinal;
  - projects: the in-place editor never touches the projects section, so they
    are only comparable when the deliverable was regenerated.

  Everything that cannot be paired **confidently** under those rules is
  labelled "not compared / manual review required" — including the ambiguous
  case of two original entries sharing one identity key (the backend dict
  keeps the last; a console cannot say which was edited, so the console does
  not claim to). The diff compares content, never pixel positions.

  The original side comes from the **parsed candidate profile** — the
  parser's structured read of the uploaded document — because the API returns
  the tailored content and the reports, never the raw original file. The
  comparison therefore covers the passages the tailoring works on (summary,
  skills, experience, projects); document parts the parser does not model
  (education, certifications, tables) are covered by the render report's
  "left untouched" list instead of a pretended diff.
*/

/** How one passage changed between the original and the tailored text. */
export type DiffStatus =
  "unchanged" | "reworded" | "added" | "removed" | "notCompared"

/** One paired passage, with both sides verbatim. */
export interface DiffPair {
  status: DiffStatus
  /** The original passage, or null when the tailored one has no original. */
  original: string | null
  /** The tailored passage, or null when the original had none. */
  tailored: string | null
}

/** One experience or project entry in the diff. */
export interface DiffEntry {
  /** The entry header as it reads in the original ("Title — Company"). */
  label: string
  /** The original entry's dates line, when the parser captured one. */
  dates: string | null
  status: DiffStatus
  bullets: DiffPair[]
  /** Present when the entry could not be paired confidently. */
  note?: string
}

/** The skills section: an item-level filter, never an addition. */
export interface SkillsDiff {
  /** Skills the original states and the tailored selection keeps. */
  kept: string[]
  /** Skills the original states that the tailored selection filtered out. */
  removed: string[]
  /**
   * Skills the tailored selection names that the original does not. The
   * in-place editor never adds a skill, so this is empty for an in-place
   * deliverable; a regenerated document renders the tailored list as written.
   */
  added: string[]
}

/** The whole resume comparison. */
export interface ResumeDiff {
  summary: DiffPair | null
  skills: SkillsDiff
  experience: DiffEntry[]
  projects: {
    /**
     * `notEditedInPlace` — the in-place editor leaves the projects section
     * alone, so no diff is claimed. `compared` — the deliverable was
     * regenerated, so the tailored projects are what shipped.
     */
    state: "notEditedInPlace" | "compared"
    entries: DiffEntry[]
    /** The tailored project names, for the informational list. */
    selected: string[]
  }
  /** True when at least one block is "not compared". */
  hasUnpaired: boolean
}

/**
 * The backend's text identity (`src/core/text.normalize`): lowercase, every
 * character outside `[a-z0-9+#. ]` becomes a space, trimmed. `+`, `#` and `.`
 * survive so `c++`, `c#` and `node.js` keep their names.
 */
export function normalizeText(value: string): string {
  return value
    .toLowerCase()
    .replace(/[^a-z0-9+#. ]/g, " ")
    .trim()
}

/** Words the keyword matcher carries no evidence on (`src/core/text.py`). */
const STOPWORDS = new Set([
  "a",
  "an",
  "the",
  "of",
  "and",
  "or",
  "to",
  "in",
  "on",
  "for",
  "with",
  "at",
  "by",
  "from",
  "as",
  "is",
  "are",
  "be",
  "been",
  "will",
  "would",
  "we",
  "you",
  "our",
  "us",
  "they",
  "their",
  "that",
  "this",
  "these",
  "it",
  "its",
  "your",
  "who",
  "have",
  "has",
  "had",
  "do",
  "does",
  "not",
  "but",
  "than",
  "then",
  "also",
  "into",
  "such",
  "must",
  "should",
  "can",
  "may",
])

/**
 * The backend's tokenizer (`src/core/text.tokenize`): normalize, split on
 * whitespace, strip each token's leading/trailing periods (a sentence period
 * is punctuation; `node.js`'s internal one is not).
 */
export function tokenize(value: string): string[] {
  const tokens: string[] = []
  for (const raw of normalizeText(value).split(/\s+/)) {
    if (!raw) continue
    const token = raw.replace(/^\.+/, "").replace(/\.+$/, "")
    if (token) tokens.push(token)
  }
  return tokens
}

/** Tokens that carry evidentiary weight (`src/core/text.content_tokens`). */
export function contentTokens(value: string): string[] {
  return tokenize(value).filter((token) => !STOPWORDS.has(token))
}

/**
 * Mirror of the ATS analyzer's `_keyword_supported` (`src/resume/ats.py`):
 * a keyword is supported when **one profile skill's** tokens contain every
 * content token of the keyword. This is the "supported by the profile but
 * not surfaced" distinction the backend itself writes into its notes.
 */
export function keywordSupported(keyword: string, skills: string[]): boolean {
  const wanted = new Set(contentTokens(keyword))
  if (wanted.size === 0) return false
  return skills.some((skill) => {
    const available = new Set(tokenize(skill))
    for (const token of wanted) {
      if (!available.has(token)) return false
    }
    return true
  })
}

/** The identity of an experience entry, normalized on both sides. */
function identityKey(title: string, company: string): string {
  return `${normalizeText(title || "")}\u0000${normalizeText(company || "")}`
}

/** "Title — Company", the way the editor names an entry. */
function entryLabel(title: string, company: string, suffix = ""): string {
  return [title, company].filter((part) => part.trim()).join(" — ") + suffix
}

/** Pair one ordered list of passages against another, by ordinal position. */
function pairBullets(original: string[], tailored: string[]): DiffPair[] {
  const pairs: DiffPair[] = []
  const shared = Math.min(original.length, tailored.length)
  for (let index = 0; index < shared; index += 1) {
    // The loop bounds place both indexes inside their arrays; the assertions
    // only restate that for `noUncheckedIndexedAccess`.
    const before = original[index] as string
    const after = tailored[index] as string
    pairs.push({
      status: before === after ? "unchanged" : "reworded",
      original: before,
      tailored: after,
    })
  }
  for (let index = shared; index < original.length; index += 1) {
    pairs.push({
      status: "removed",
      original: original[index] as string,
      tailored: null,
    })
  }
  for (let index = shared; index < tailored.length; index += 1) {
    pairs.push({
      status: "added",
      original: null,
      tailored: tailored[index] as string,
    })
  }
  return pairs
}

/** Pair the two single-paragraph summaries. */
function pairSummary(
  originalSummary: string,
  tailoredSummary: string
): DiffPair | null {
  const before = originalSummary.trim()
  const after = tailoredSummary.trim()
  if (!before && !after) return null
  if (!before) return { status: "added", original: null, tailored: after }
  if (!after) return { status: "removed", original: before, tailored: null }
  return {
    status: before === after ? "unchanged" : "reworded",
    original: before,
    tailored: after,
  }
}

/** The document's skills filtered down to the tailored selection. */
function pairSkills(
  originalSkills: string[],
  highlightedSkills: string[]
): SkillsDiff {
  const selected = new Set(
    highlightedSkills.map((skill) => normalizeText(skill))
  )
  const stated = new Set(originalSkills.map((skill) => normalizeText(skill)))
  const kept: string[] = []
  const removed: string[] = []
  for (const skill of originalSkills) {
    ;(selected.has(normalizeText(skill)) ? kept : removed).push(skill)
  }
  const added = highlightedSkills.filter(
    (skill) => !stated.has(normalizeText(skill))
  )
  return { kept, removed, added }
}

/**
 * The experience comparison.
 *
 * Entries are paired by identity. A tailored entry whose identity appears
 * exactly once in the profile is paired; one that appears twice is ambiguous
 * (the backend keeps the last occurrence — a console cannot know which was
 * edited) and both sides are labelled not compared; a profile entry no
 * tailored entry names is not compared either — and, because the editor only
 * rewrites entries the tailoring produced, that original survives the
 * deliverable untouched, which the note says.
 */
function pairExperience(
  profileEntries: CandidateProfile["experience"],
  tailoredEntries: TailoredResume["experience"]
): DiffEntry[] {
  // How many original entries carry each identity key.
  const counts = new Map<string, number>()
  for (const entry of profileEntries) {
    const key = identityKey(entry.title, entry.company)
    counts.set(key, (counts.get(key) ?? 0) + 1)
  }

  const entries: DiffEntry[] = []
  const pairedKeys = new Set<string>()

  for (const tailoredEntry of tailoredEntries) {
    const key = identityKey(tailoredEntry.title, tailoredEntry.company)
    const occurrences = counts.get(key) ?? 0
    if (occurrences === 1) {
      const original = profileEntries.find(
        (candidate) => identityKey(candidate.title, candidate.company) === key
      )
      if (original) {
        pairedKeys.add(key)
        const bullets = pairBullets(original.bullets, tailoredEntry.bullets)
        entries.push({
          label: entryLabel(tailoredEntry.title, tailoredEntry.company),
          dates: original.dates.trim() || null,
          status: bullets.every((pair) => pair.status === "unchanged")
            ? "unchanged"
            : "reworded",
          bullets,
        })
        continue
      }
    }
    entries.push({
      label: entryLabel(tailoredEntry.title, tailoredEntry.company),
      dates: null,
      status: "notCompared",
      bullets: tailoredEntry.bullets.map((bullet) => ({
        status: "notCompared" as DiffStatus,
        original: null,
        tailored: bullet,
      })),
      note:
        occurrences > 1
          ? `${occurrences} entries in your original share this company and title, so the one that was edited cannot be identified. Compare by hand.`
          : "The tailored resume names an entry the parsed original does not, so it could not be paired. Compare by hand.",
    })
  }

  // Original entries that were never confidently paired. Each one survives
  // the delivered file untouched (the editor only rewrites entries the
  // tailoring produced), and each is shown so a human can compare by hand.
  const emitted = new Map<string, number>()
  for (const original of profileEntries) {
    const key = identityKey(original.title, original.company)
    if (pairedKeys.has(key)) continue
    const total = counts.get(key) ?? 0
    const nth = (emitted.get(key) ?? 0) + 1
    emitted.set(key, nth)
    entries.push({
      label: entryLabel(
        original.title,
        original.company,
        total > 1 ? ` (entry ${nth} of ${total} with this title)` : ""
      ),
      dates: original.dates.trim() || null,
      status: "notCompared",
      bullets: original.bullets.map((bullet) => ({
        status: "notCompared" as DiffStatus,
        original: bullet,
        tailored: null,
      })),
      note:
        total > 1
          ? undefined
          : "The tailoring produced no entry with this company and title, so your original text was left untouched in the delivered file. Compare by hand.",
    })
  }
  return entries
}

/**
 * The projects comparison — only when the deliverable was regenerated.
 * Identity is the normalized project name; bullets pair by ordinal.
 */
function pairProjects(
  profileProjects: CandidateProfile["projects"],
  tailoredProjects: TailoredResume["projects"],
  mode: RenderReport["mode"]
): ResumeDiff["projects"] {
  const selected = tailoredProjects.map((project) => project.name)
  if (mode !== "regenerated") {
    return { state: "notEditedInPlace", entries: [], selected }
  }
  const counts = new Map<string, number>()
  for (const project of profileProjects) {
    const key = normalizeText(project.name)
    counts.set(key, (counts.get(key) ?? 0) + 1)
  }

  const entries: DiffEntry[] = []
  const pairedKeys = new Set<string>()
  for (const tailoredProject of tailoredProjects) {
    const key = normalizeText(tailoredProject.name)
    if ((counts.get(key) ?? 0) === 1) {
      const original = profileProjects.find(
        (candidate) => normalizeText(candidate.name) === key
      )
      if (original) {
        pairedKeys.add(key)
        const bullets = pairBullets(original.bullets, tailoredProject.bullets)
        entries.push({
          label: tailoredProject.name,
          dates: original.subtitle.trim() || null,
          status: bullets.every((pair) => pair.status === "unchanged")
            ? "unchanged"
            : "reworded",
          bullets,
        })
        continue
      }
    }
    const occurrences = counts.get(key) ?? 0
    entries.push({
      label: tailoredProject.name,
      dates: null,
      status: "notCompared",
      bullets: tailoredProject.bullets.map((bullet) => ({
        status: "notCompared" as DiffStatus,
        original: null,
        tailored: bullet,
      })),
      note:
        occurrences > 1
          ? `${occurrences} original projects share this name, so the one that was rewritten cannot be identified. Compare by hand.`
          : "This project could not be paired with one original project by name. Compare by hand.",
    })
  }

  const emitted = new Map<string, number>()
  for (const original of profileProjects) {
    const key = normalizeText(original.name)
    if (pairedKeys.has(key)) continue
    const total = counts.get(key) ?? 0
    const nth = (emitted.get(key) ?? 0) + 1
    emitted.set(key, nth)
    entries.push({
      label: entryLabel(
        original.name,
        original.subtitle,
        total > 1 ? ` (entry ${nth} of ${total} with this name)` : ""
      ),
      dates: null,
      status: "notCompared",
      bullets: original.bullets.map((bullet) => ({
        status: "notCompared" as DiffStatus,
        original: bullet,
        tailored: null,
      })),
      note:
        total > 1
          ? undefined
          : "The tailored resume does not name this project, so it is not part of the regenerated deliverable. Compare by hand.",
    })
  }
  return { state: "compared", entries, selected }
}

/**
 * The whole diff, built once from the parsed profile, the tailored content
 * and the render report. Pure: no fetches, no state, no mutation.
 */
export function buildResumeDiff(
  profile: CandidateProfile,
  tailored: TailoredResume,
  render: RenderReport
): ResumeDiff {
  const summary = pairSummary(profile.summary, tailored.summary)
  const skills = pairSkills(profile.skills, tailored.highlighted_skills)
  const experience = pairExperience(profile.experience, tailored.experience)
  const projects = pairProjects(
    profile.projects,
    tailored.projects,
    render.mode
  )
  const hasUnpaired =
    experience.some((entry) => entry.status === "notCompared") ||
    (projects.state === "compared" &&
      projects.entries.some((entry) => entry.status === "notCompared"))
  return { summary, skills, experience, projects, hasUnpaired }
}

/** Where the profile mentions a keyword, as evidence for the keyword panel. */
export interface KeywordEvidence {
  source: "skills" | "experience" | "projects" | "summary"
  /** The passage that mentions it, verbatim. */
  text: string
}

/**
 * The profile passages that mention a keyword — token containment, the same
 * "mentions the same thing" rule the ATS analyzer uses, so the evidence list
 * cannot overclaim. Empty when the profile never states the term: that is the
 * honest gap the panel shows instead.
 */
export function keywordEvidence(
  keyword: string,
  profile: CandidateProfile
): KeywordEvidence[] {
  const wanted = new Set(contentTokens(keyword))
  if (wanted.size === 0) return []
  const mentions = (text: string): boolean => {
    const available = new Set(tokenize(text))
    for (const token of wanted) {
      if (!available.has(token)) return false
    }
    return true
  }
  const evidence: KeywordEvidence[] = []
  for (const skill of profile.skills) {
    if (mentions(skill)) {
      evidence.push({ source: "skills", text: skill })
    }
  }
  for (const entry of profile.experience) {
    for (const bullet of entry.bullets) {
      if (mentions(bullet)) {
        evidence.push({
          source: "experience",
          text: `${entry.title} — ${entry.company}: ${bullet}`,
        })
      }
    }
  }
  for (const project of profile.projects) {
    for (const bullet of project.bullets) {
      if (mentions(bullet)) {
        evidence.push({
          source: "projects",
          text: `${project.name}: ${bullet}`,
        })
      }
    }
  }
  if (profile.summary.trim() && mentions(profile.summary)) {
    evidence.push({ source: "summary", text: profile.summary })
  }
  return evidence
}

/**
 * Whether the listing carried enough structured requirements to measure
 * coverage at all. With none, the honest answer is "could not be measured" —
 * never a 100% or a 0%.
 */
export function coverageIsMeasurable(coverage: {
  required_hit: string[]
  required_missing: string[]
  preferred_hit: string[]
  preferred_missing: string[]
}): boolean {
  return (
    coverage.required_hit.length +
      coverage.required_missing.length +
      coverage.preferred_hit.length +
      coverage.preferred_missing.length >
    0
  )
}
