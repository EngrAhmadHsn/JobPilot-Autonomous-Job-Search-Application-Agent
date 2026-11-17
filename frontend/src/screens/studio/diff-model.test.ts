import { describe, expect, it } from "vitest"

import { candidateProfile } from "@/test/factories"
import type { CandidateProfile } from "@/lib/api/types"

import {
  buildResumeDiff,
  contentTokens,
  coverageIsMeasurable,
  keywordEvidence,
  keywordSupported,
  normalizeText,
  tokenize,
} from "./diff-model"

/** A profile override helper: the factory with experience replaced. */
function profileWith(overrides: Partial<CandidateProfile>): CandidateProfile {
  return candidateProfile(overrides)
}

describe("the backend text identity, mirrored", () => {
  it("keeps +, # and internal dots, drops the rest", () => {
    expect(normalizeText("C++ Engineer")).toBe("c++ engineer")
    expect(normalizeText("Node.js/React")).toBe("node.js react")
    // Faithful to `src/core/text.normalize`: each punctuation run becomes one
    // space and only the ends are stripped — internal spacing survives, so
    // identity keys disagree exactly where the backend's would.
    expect(normalizeText("  Senior — AI  ")).toBe("senior   ai")
    expect(normalizeText("Senior AI")).toBe("senior ai")
  })

  it("strips sentence periods from tokens but keeps node.js", () => {
    expect(tokenize("Machine learning systems.")).toEqual([
      "machine",
      "learning",
      "systems",
    ])
    expect(tokenize("node.js and c++")).toEqual(["node.js", "and", "c++"])
    expect(contentTokens("building a machine learning system")).toEqual([
      "building",
      "machine",
      "learning",
      "system",
    ])
  })
})

describe("keyword support (the ATS `_keyword_supported` mirror)", () => {
  const skills = ["Python", "Machine Learning", "C++"]

  it("is true when one skill's tokens contain the keyword's", () => {
    expect(keywordSupported("machine learning", skills)).toBe(true)
    expect(keywordSupported("python", skills)).toBe(true)
  })

  it("is false when no skill carries the term", () => {
    expect(keywordSupported("kubernetes", skills)).toBe(false)
  })

  it("does not match inside a longer word", () => {
    expect(keywordSupported("go", ["google cloud", "django"])).toBe(false)
  })
})

describe("keyword evidence", () => {
  it("lists the profile passages that mention the term", () => {
    const profile = profileWith({
      skills: ["Python", "SQL"],
      experience: [
        {
          title: "Analyst",
          company: "Acme",
          dates: "",
          bullets: ["Wrote Python data pipelines."],
          years: 2,
        },
      ],
    })
    const evidence = keywordEvidence("Python", profile)
    expect(evidence.map((item) => item.source)).toEqual([
      "skills",
      "experience",
    ])
    expect(evidence[1]?.text).toContain("Wrote Python data pipelines.")
  })

  it("is empty for a term the profile never states — the honest gap", () => {
    const profile = profileWith({ skills: ["Python"] })
    expect(keywordEvidence("kubernetes", profile)).toEqual([])
  })
})

describe("coverageIsMeasurable", () => {
  it("is false when the listing declared no structured skills", () => {
    const empty = {
      required_hit: [],
      required_missing: [],
      preferred_hit: [],
      preferred_missing: [],
    }
    expect(coverageIsMeasurable(empty)).toBe(false)
  })

  it("is true once any requirement exists", () => {
    expect(
      coverageIsMeasurable({
        ...{
          required_hit: [],
          required_missing: [],
          preferred_hit: [],
          preferred_missing: [],
        },
        required_missing: ["kubernetes"],
      })
    ).toBe(true)
  })
})

describe("buildResumeDiff — the renderer's identity rules", () => {
  it("pairs multiple roles by company and title, bullets by ordinal", () => {
    const profile = profileWith({
      experience: [
        {
          title: "Analyst",
          company: "Analytical Engine Project",
          dates: "1842-1843",
          bullets: [
            "Designed the first published algorithm.",
            "Wrote the notes.",
          ],
          years: 1,
        },
        {
          title: "Mathematician",
          company: "Windermere House",
          dates: "1840-1841",
          bullets: ["Tutored in mathematics."],
          years: 1,
        },
      ],
    })
    const tailored = {
      summary: "Engineer.",
      highlighted_skills: ["Python"],
      experience: [
        {
          title: "Mathematician",
          company: "Windermere House",
          bullets: ["Tutored mathematics, with care."],
        },
        {
          title: "Analyst",
          company: "Analytical Engine Project",
          bullets: [
            "Designed the first published algorithm, for computing.",
            "Prepared the publisher's notes.",
          ],
        },
      ],
      projects: [],
      cover_letter: "Dear hiring team.",
    }
    const diff = buildResumeDiff(profile, tailored, {
      mode: "in_place",
      source_format: ".docx",
      edits: 3,
      appended: 0,
      removed: 0,
      skipped: [],
      notes: [],
    })

    // Two roles, each paired with its own identity — never by proximity.
    expect(diff.experience).toHaveLength(2)
    const analyst = diff.experience.find((entry) =>
      entry.label.startsWith("Analyst")
    )
    const mathematician = diff.experience.find((entry) =>
      entry.label.startsWith("Mathematician")
    )
    expect(analyst?.status).toBe("reworded")
    expect(mathematician?.status).toBe("reworded")
    // The Analyst's first bullet pairs with the original first bullet, even
    // though the tailored list arrived in the opposite order.
    expect(analyst?.bullets[0]?.original).toBe(
      "Designed the first published algorithm."
    )
    expect(analyst?.bullets[0]?.tailored).toContain("for computing")
    expect(diff.hasUnpaired).toBe(false)
  })

  it("pairs repeated (identical) bullets by position, not by content", () => {
    const profile = profileWith({
      experience: [
        {
          title: "Analyst",
          company: "Acme",
          dates: "",
          bullets: ["Owned reporting.", "Owned reporting."],
          years: 2,
        },
      ],
    })
    const tailored = {
      summary: "",
      highlighted_skills: [],
      experience: [
        {
          title: "Analyst",
          company: "Acme",
          bullets: ["Owned weekly reporting.", "Owned reporting."],
        },
      ],
      projects: [],
      cover_letter: "",
    }
    const diff = buildResumeDiff(profile, tailored, {
      mode: "in_place",
      source_format: ".docx",
      edits: 1,
      appended: 0,
      removed: 0,
      skipped: [],
      notes: [],
    })
    const entry = diff.experience[0]
    // The first bullet changed, the second did not — ordinal pairing sees
    // the difference; content matching would have confused the two.
    expect(entry?.bullets[0]?.status).toBe("reworded")
    expect(entry?.bullets[0]?.original).toBe("Owned reporting.")
    expect(entry?.bullets[0]?.tailored).toBe("Owned weekly reporting.")
    expect(entry?.bullets[1]?.status).toBe("unchanged")
  })

  it("labels surplus original bullets as removed and surplus tailored bullets as added", () => {
    const profile = profileWith({
      experience: [
        {
          title: "Analyst",
          company: "Acme",
          dates: "",
          bullets: ["First.", "Second.", "Third."],
          years: 1,
        },
      ],
    })
    const tailored = {
      summary: "",
      highlighted_skills: [],
      experience: [
        { title: "Analyst", company: "Acme", bullets: ["First rewritten."] },
      ],
      projects: [],
      cover_letter: "",
    }
    const diff = buildResumeDiff(profile, tailored, {
      mode: "in_place",
      source_format: ".docx",
      edits: 1,
      appended: 0,
      removed: 2,
      skipped: [],
      notes: [],
    })
    const bullets = diff.experience[0]?.bullets
    expect(bullets?.[0]?.status).toBe("reworded")
    expect(bullets?.[1]).toMatchObject({
      status: "removed",
      original: "Second.",
    })
    expect(bullets?.[2]).toMatchObject({
      status: "removed",
      original: "Third.",
    })
  })

  it("refuses to pair two original entries that share one identity", () => {
    const profile = profileWith({
      experience: [
        {
          title: "Contractor",
          company: "Acme",
          dates: "1840",
          bullets: ["First tour."],
          years: 1,
        },
        {
          title: "Contractor",
          company: "Acme",
          dates: "1843",
          bullets: ["Second tour."],
          years: 1,
        },
      ],
    })
    const tailored = {
      summary: "",
      highlighted_skills: [],
      experience: [
        { title: "Contractor", company: "Acme", bullets: ["Rewritten tour."] },
      ],
      projects: [],
      cover_letter: "",
    }
    const diff = buildResumeDiff(profile, tailored, {
      mode: "in_place",
      source_format: ".docx",
      edits: 1,
      appended: 0,
      removed: 0,
      skipped: [],
      notes: [],
    })
    expect(diff.hasUnpaired).toBe(true)
    // The tailored entry is labelled, not fuzzy-matched onto either tour.
    const tailoredEntry = diff.experience[0]
    expect(tailoredEntry?.status).toBe("notCompared")
    expect(tailoredEntry?.note).toContain("2 entries")
    // Both original occurrences are shown, numbered, for the human.
    const originals = diff.experience.filter(
      (entry) => entry.bullets[0]?.original !== null
    )
    expect(originals).toHaveLength(2)
    expect(originals[0]?.label).toContain("entry 1 of 2")
    expect(originals[1]?.label).toContain("entry 2 of 2")
  })

  it("labels an original entry with no tailored counterpart as not compared — and untouched", () => {
    const profile = profileWith({
      experience: [
        {
          title: "Analyst",
          company: "Acme",
          dates: "",
          bullets: ["Original work."],
          years: 1,
        },
        {
          title: "Tutor",
          company: "Windermere",
          dates: "",
          bullets: ["Tutoring."],
          years: 1,
        },
      ],
    })
    const tailored = {
      summary: "",
      highlighted_skills: [],
      experience: [
        { title: "Analyst", company: "Acme", bullets: ["Tailored work."] },
      ],
      projects: [],
      cover_letter: "",
    }
    const diff = buildResumeDiff(profile, tailored, {
      mode: "in_place",
      source_format: ".docx",
      edits: 1,
      appended: 0,
      removed: 0,
      skipped: [],
      notes: [],
    })
    const tutor = diff.experience.find((entry) =>
      entry.label.startsWith("Tutor")
    )
    expect(tutor?.status).toBe("notCompared")
    expect(tutor?.note).toContain("left untouched")
    expect(tutor?.bullets[0]?.original).toBe("Tutoring.")
  })

  it("compares skills item-level and never claims an addition for an in-place edit", () => {
    const profile = profileWith({
      skills: ["Python", "SQL", "Machine Learning"],
    })
    const tailored = {
      summary: "",
      highlighted_skills: ["Python", "SQL"],
      experience: [],
      projects: [],
      cover_letter: "",
    }
    const diff = buildResumeDiff(profile, tailored, {
      mode: "in_place",
      source_format: ".docx",
      edits: 1,
      appended: 0,
      removed: 0,
      skipped: [],
      notes: [],
    })
    expect(diff.skills.kept).toEqual(["Python", "SQL"])
    expect(diff.skills.removed).toEqual(["Machine Learning"])
    expect(diff.skills.added).toEqual([])
  })

  it("does not diff projects for an in-place deliverable — the editor leaves them alone", () => {
    const profile = profileWith({
      projects: [
        {
          name: "Bernoulli Numbers",
          subtitle: "Notes",
          tech: "",
          bullets: ["Computed them."],
        },
      ],
    })
    const tailored = {
      summary: "",
      highlighted_skills: [],
      experience: [],
      projects: [
        { name: "Bernoulli Numbers", bullets: ["Computed them, faster."] },
      ],
      cover_letter: "",
    }
    const diff = buildResumeDiff(profile, tailored, {
      mode: "in_place",
      source_format: ".docx",
      edits: 1,
      appended: 0,
      removed: 0,
      skipped: [],
      notes: [],
    })
    expect(diff.projects.state).toBe("notEditedInPlace")
    expect(diff.projects.entries).toEqual([])
    expect(diff.projects.selected).toEqual(["Bernoulli Numbers"])
  })

  it("pairs projects by name when the deliverable was regenerated", () => {
    const profile = profileWith({
      projects: [
        {
          name: "Bernoulli Numbers",
          subtitle: "Notes",
          tech: "",
          bullets: ["Computed them."],
        },
        {
          name: "Analytical Engine",
          subtitle: "",
          tech: "",
          bullets: ["Designed it."],
        },
      ],
    })
    const tailored = {
      summary: "",
      highlighted_skills: [],
      experience: [],
      projects: [
        { name: "Bernoulli Numbers", bullets: ["Computed them, faster."] },
      ],
      cover_letter: "",
    }
    const diff = buildResumeDiff(profile, tailored, {
      mode: "regenerated",
      source_format: "none",
      edits: 0,
      appended: 0,
      removed: 0,
      skipped: [],
      notes: [],
    })
    expect(diff.projects.state).toBe("compared")
    expect(diff.projects.entries).toHaveLength(2)
    const paired = diff.projects.entries.find((entry) =>
      entry.label.startsWith("Bernoulli")
    )
    expect(paired?.status).toBe("reworded")
    expect(paired?.bullets[0]?.original).toBe("Computed them.")
    const dropped = diff.projects.entries.find((entry) =>
      entry.label.startsWith("Analytical")
    )
    expect(dropped?.status).toBe("notCompared")
    expect(dropped?.note).toContain("not part of the regenerated deliverable")
  })

  it("pairs the summary and reports it reworded, verbatim on both sides", () => {
    const profile = profileWith({
      summary:
        "Engineer working on analytical engines and applied machine learning.",
    })
    const tailored = {
      summary: "AI Engineer with analytical and machine learning experience.",
      highlighted_skills: [],
      experience: [],
      projects: [],
      cover_letter: "",
    }
    const diff = buildResumeDiff(profile, tailored, {
      mode: "in_place",
      source_format: ".txt",
      edits: 2,
      appended: 0,
      removed: 0,
      skipped: [],
      notes: [],
    })
    expect(diff.summary?.status).toBe("reworded")
    expect(diff.summary?.original).toBe(
      "Engineer working on analytical engines and applied machine learning."
    )
    expect(diff.summary?.tailored).toBe(
      "AI Engineer with analytical and machine learning experience."
    )
  })

  it("reports an added summary when the original document had none", () => {
    const profile = profileWith({ summary: "" })
    const tailored = {
      summary: "A fresh summary.",
      highlighted_skills: [],
      experience: [],
      projects: [],
      cover_letter: "",
    }
    const diff = buildResumeDiff(profile, tailored, {
      mode: "in_place",
      source_format: ".docx",
      edits: 1,
      appended: 2,
      removed: 0,
      skipped: [],
      notes: [
        "The résumé had no summary section, so a summary was added under its own heading",
      ],
    })
    expect(diff.summary?.status).toBe("added")
    expect(diff.summary?.original).toBeNull()
    expect(diff.summary?.tailored).toBe("A fresh summary.")
  })

  it("never mutates either side: the original strings come back verbatim", () => {
    const originalBullet = "  Designed the first published algorithm.  "
    const profile = profileWith({
      experience: [
        {
          title: "Analyst",
          company: "Acme",
          dates: "",
          bullets: [originalBullet],
          years: 1,
        },
      ],
    })
    const tailoredBullet = "Designed the first published algorithm, improved."
    const tailored = {
      summary: "",
      highlighted_skills: [],
      experience: [
        { title: "Analyst", company: "Acme", bullets: [tailoredBullet] },
      ],
      projects: [],
      cover_letter: "",
    }
    const diff = buildResumeDiff(profile, tailored, {
      mode: "in_place",
      source_format: ".docx",
      edits: 1,
      appended: 0,
      removed: 0,
      skipped: [],
      notes: [],
    })
    // The pair carries the strings as the server sent them — trimmed for
    // comparison only where the parser itself trims, never rewritten.
    expect(diff.experience[0]?.bullets[0]?.original).toBe(originalBullet)
    expect(diff.experience[0]?.bullets[0]?.tailored).toBe(tailoredBullet)
  })
})
