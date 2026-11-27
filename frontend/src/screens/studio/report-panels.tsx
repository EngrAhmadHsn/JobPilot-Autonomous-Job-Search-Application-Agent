import { Banner } from "@/components/common/banner"
import { FieldList, SectionTitle } from "@/components/common/field-list"
import { PlainText } from "@/components/common/plain-text"
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import { formatList } from "@/lib/format"
import type { TailorResponse } from "@/lib/api/types"

/*
  One panel per real report (WS-37 task 5), in plain language, each honest
  about its limits:

  - the factuality report is **content**, never an error — a failed report is
    rendered as findings with visual weight, and the global banner above the
    tabs repeats it so it cannot hide behind a green ATS score;
  - the ATS panel prints the deterministic weights (keywords 45%, sections
    20%, title alignment 20%, format safety 15% — confirmed against
    `src/resume/ats.py:36-39`, `ATS_WEIGHTS`, and verified in the WS-33
    audit's stale-doc table row 8) and never claims acceptance or interviews;
  - the style panel reports the wording verdict; it never rewrites;
  - the render panel states in-place versus regeneration with the skipped
    content and the reasons the backend gave;
  - the insights panel separates what the listing text says from anything
    inferred — which here is easy, because nothing is inferred.
*/

/**
 * The factuality report.
 *
 * A factuality failure is **not** an error: the stripped content plus the
 * violations is the product. The report is rendered as a warning with the
 * removed items listed, never as a failure.
 */
export function FactualityReport({
  factuality,
}: {
  factuality: TailorResponse["factuality"]
}) {
  const removed =
    factuality.removed_skills.length +
    factuality.removed_experience.length +
    factuality.removed_projects.length

  return (
    <Card>
      <CardHeader>
        <CardTitle>Factuality report</CardTitle>
      </CardHeader>
      <CardContent className="space-y-3">
        {factuality.passed ? (
          <Banner tone="success" title="Every claim is supported by the résumé">
            <p>
              The validator found nothing to strip: every skill, role and
              project in the tailored resume is stated by the document.
            </p>
          </Banner>
        ) : (
          <Banner
            tone="warning"
            title={
              removed > 0
                ? `${removed} unsupported item(s) were removed`
                : "The factuality check revised the wording"
            }
          >
            <p>Review the changes below before using the tailored draft.</p>
          </Banner>
        )}

        <FieldList
          items={[
            {
              label: "Removed skills",
              value: formatList(factuality.removed_skills),
            },
            {
              label: "Removed experience",
              value: formatList(factuality.removed_experience),
            },
            {
              label: "Removed projects",
              value: formatList(factuality.removed_projects),
            },
          ]}
        />

        {factuality.violations.length > 0 ? (
          <div className="space-y-1">
            <SectionTitle>Violations</SectionTitle>
            <ul className="list-disc space-y-1 pl-5 text-sm">
              {factuality.violations.map((violation) => (
                <li key={violation}>
                  <PlainText as="span">{violation}</PlainText>
                </li>
              ))}
            </ul>
          </div>
        ) : null}
      </CardContent>
    </Card>
  )
}

/** How the delivered document was produced (WS-31). */
export function RenderPanel({ render }: { render: TailorResponse["render"] }) {
  const sourceLabel =
    render.source_format === "none" ? "no original" : render.source_format
  return (
    <Card>
      <CardHeader>
        <CardTitle>Your document</CardTitle>
        <CardDescription>
          {render.mode === "in_place"
            ? "Your own file was edited: the wording changed, your formatting did not."
            : "Your own file could not be edited, so a freshly formatted document was written instead."}
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-3">
        <Banner
          tone={render.mode === "in_place" ? "success" : "warning"}
          title={
            render.mode === "in_place"
              ? `Edited in place from your ${sourceLabel} résumé`
              : "A new document was generated"
          }
        >
          {/* The counts are only meaningful for an in-place edit, so they are
              shown only then — a rewrite has nothing to count. */}
          {render.mode === "in_place" ? (
            <p>
              {render.edits} passage{render.edits === 1 ? "" : "s"} rewritten
              {render.appended > 0 ? `, ${render.appended} added` : ""}
              {render.removed > 0 ? `, ${render.removed} cleared` : ""}. Your
              fonts, section order and page setup are unchanged.
            </p>
          ) : (
            <p>
              The original could not be edited, so the content was written into
              a standard layout instead.
            </p>
          )}
        </Banner>

        {render.notes.length > 0 ? (
          <ul className="list-disc space-y-1 pl-5 text-xs text-muted-foreground">
            {render.notes.map((note) => (
              <li key={note}>{note}</li>
            ))}
          </ul>
        ) : null}

        {render.skipped.length > 0 ? (
          <div>
            <SectionTitle>Left untouched</SectionTitle>
            <ul className="list-disc space-y-1 pl-5 text-xs text-muted-foreground">
              {render.skipped.map((item) => (
                <li key={item}>{item}</li>
              ))}
            </ul>
          </div>
        ) : null}
      </CardContent>
    </Card>
  )
}

/** The deterministic style report on the delivered wording (WS-22). */
export function StylePanel({ style }: { style: TailorResponse["style"] }) {
  const ratio = Math.round(style.quantified_ratio * 100)
  return (
    <Card>
      <CardHeader>
        <CardTitle>Style report</CardTitle>
        <CardDescription>
          Plain-language check on the wording: AI jargon, filler phrases and how
          many bullets carry a number. It reports — it never rewrites.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-3">
        {style.findings.length === 0 ? (
          <Banner tone="success" title="No jargon or filler found">
            <p>
              None of the checked phrases — the AI jargon and the weak filler
              verbs in the style policy — appear in the summary, the cover
              letter or the bullets.
            </p>
          </Banner>
        ) : (
          <Banner
            tone="warning"
            title={`${style.findings.length} phrase(s) to reconsider`}
          >
            <p>
              The wording is delivered as written; these are the parts a
              recruiter reads as filler.
            </p>
          </Banner>
        )}

        <FieldList
          items={[
            {
              label: "Quantified bullets",
              value: `${style.quantified_count} of ${style.bullet_count}${
                style.bullet_count > 0 ? ` (${ratio}%)` : ""
              }`,
            },
          ]}
        />

        {style.findings.length > 0 ? (
          <div className="space-y-1">
            <SectionTitle>Findings</SectionTitle>
            <ul className="space-y-1.5 text-sm">
              {style.findings.map((finding, index) => (
                <li key={`${finding.phrase}-${index}`}>
                  <span className="font-medium">
                    <PlainText as="span">{finding.phrase}</PlainText>
                  </span>
                  <span className="text-muted-foreground">
                    {" "}
                    → {finding.suggestion}
                  </span>
                  {finding.snippet ? (
                    <PlainText className="mt-0.5 text-xs text-muted-foreground">
                      {finding.snippet}
                    </PlainText>
                  ) : null}
                </li>
              ))}
            </ul>
          </div>
        ) : null}
      </CardContent>
    </Card>
  )
}

/**
 * The ATS analysis of the tailored resume.
 *
 * The weights are printed because a person reading a score deserves to see
 * how it was built. They are the analyzer's own constants (`ATS_WEIGHTS`,
 * `src/resume/ats.py:36-39`); if the backend ever changes them, this line
 * must change with it — the test suite pins the numbers against that file's
 * documented values.
 */
export function AtsPanel({ ats }: { ats: TailorResponse["ats_report"] }) {
  const coverage = ats.keyword_coverage
  return (
    <Card>
      <CardHeader>
        <CardTitle>ATS report</CardTitle>
        <CardDescription>
          A measurement, not a promise: the score never predicts an acceptance
          or an interview. Weights — keywords 45%, sections 20%, title alignment
          20%, format safety 15%.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-3">
        <div className="flex items-baseline gap-3">
          <span className="text-2xl font-semibold tabular-nums">
            {ats.score.toFixed(1)}
          </span>
          <span className="text-xs text-muted-foreground">/ 100 ATS score</span>
          <span className="text-xs text-muted-foreground">
            title alignment {ats.title_alignment.toFixed(1)}
          </span>
        </div>

        <FieldList
          items={[
            {
              label: "Required keywords hit",
              value: `${coverage.required_hit.length} of ${coverage.required_hit.length + coverage.required_missing.length} (${(coverage.required_coverage * 100).toFixed(0)}%)`,
            },
            {
              label: "Required missing",
              value: formatList(coverage.required_missing),
            },
            {
              label: "Preferred hit",
              value: formatList(coverage.preferred_hit),
            },
            {
              label: "Preferred missing",
              value: formatList(coverage.preferred_missing),
            },
            {
              label: "Sections present",
              value:
                Object.entries(ats.section_completeness)
                  .map(
                    ([section, present]) =>
                      `${section}: ${present ? "yes" : "no"}`
                  )
                  .join(", ") || "none reported",
            },
            { label: "Format risks", value: formatList(ats.format_risks) },
          ]}
        />

        {ats.notes.length > 0 ? (
          <div className="space-y-1">
            <SectionTitle>Notes from the analyzer</SectionTitle>
            <ul className="list-disc space-y-1 pl-5 text-xs text-muted-foreground">
              {ats.notes.map((note) => (
                <li key={note}>
                  <PlainText as="span" className="text-xs">
                    {note}
                  </PlainText>
                </li>
              ))}
            </ul>
          </div>
        ) : null}
      </CardContent>
    </Card>
  )
}

/** The grounded insights about the job. */
export function InsightsPanel({
  insights,
}: {
  insights: TailorResponse["insights"]
}) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>Grounded job insights</CardTitle>
        <CardDescription>
          Extracted from the listing text — sourced facts, nothing fetched from
          the web, nothing inferred. Fields the listing never states are
          reported as empty rather than guessed.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-3">
        {insights.summary ? <PlainText>{insights.summary}</PlainText> : null}
        <FieldList
          items={[
            {
              label: "Responsibilities",
              value: formatList(insights.responsibilities),
            },
            { label: "Tech stack", value: formatList(insights.tech_stack) },
            {
              label: "Seniority signals",
              value: formatList(insights.seniority_signals),
            },
            {
              label: "Culture flags",
              value: formatList(insights.culture_flags),
            },
          ]}
        />
      </CardContent>
    </Card>
  )
}
