import { Check, CircleAlert } from "lucide-react"

import { PlainText } from "@/components/common/plain-text"
import type { ApplicationPrepareResponse, BoardQuestion } from "@/lib/api/types"
import { formatList } from "@/lib/format"

type PreparedSummary = ApplicationPrepareResponse["prepared_summary"]

/**
 * One row of the Application Package checklist.
 *
 * The mark carries meaning, and it follows the product's colour law: a
 * check in forest ink is a fact of the payload (present, or counted), and a
 * terracotta mark is something a human has to deal with. There is no third
 * "decorative green" — an item is either accounted for or it needs you.
 */
function PackageItem({
  label,
  children,
  attention,
}: {
  label: string
  children: React.ReactNode
  attention?: boolean
}) {
  return (
    <li className="flex items-start gap-2.5 py-2 first:pt-0 last:pb-0">
      {attention ? (
        <CircleAlert className="mt-0.5 size-4 shrink-0 text-terracotta-foreground" />
      ) : (
        <Check className="mt-0.5 size-4 shrink-0 text-forest" />
      )}
      <div className="min-w-0 flex-1">
        <p className="text-sm font-medium text-foreground">{label}</p>
        <div className="mt-0.5 text-sm leading-relaxed text-muted-foreground">
          {children}
        </div>
      </div>
    </li>
  )
}

/**
 * The Application Package: what exactly is stored in the payload the
 * approval authorizes.
 *
 * Every row anchors to a real value the prepare response carried — the
 * résumé's stored path is the document's identity (a prepared or tailored
 * file on the server, not a re-derivation), the answers and facts are the
 * response's own names. Nothing here is decorated with a number the API did
 * not send: the reference's "ATS score 90/100" bound to a document revision
 * does not exist yet (WS-33 audit §7), so the checklist shows the
 * document's path instead — which is the identity the approval actually
 * binds.
 */
export function PackageChecklist({
  summary,
  questions,
  customFieldCount,
  coverLetterProvided,
}: {
  summary: PreparedSummary
  questions: BoardQuestion[]
  /** The candidate-provided answers the operator typed into the prepare form. */
  customFieldCount: number
  /** Whether the prepare request carried cover-letter text. */
  coverLetterProvided: boolean
}) {
  const needsHuman = questions.filter(
    (question) => question.verdict === "needs_human"
  ).length
  const answerable = questions.filter(
    (question) => question.verdict === "answerable"
  ).length

  return (
    <div className="rounded-xl border border-border bg-card/60 p-3.5">
      <h3 className="font-heading text-sm font-semibold tracking-tight text-foreground">
        Application package
      </h3>
      <p className="mt-0.5 mb-2 text-xs leading-relaxed text-muted-foreground">
        Stored with the payload — approving sends exactly this.
      </p>
      <ul className="divide-y divide-border/60">
        <PackageItem label="Résumé">
          {summary.resume_path ? (
            <PlainText
              as="span"
              className="font-mono text-[11px] wrap-anywhere"
            >
              {summary.resume_path}
            </PlainText>
          ) : (
            <span>None stored with the payload</span>
          )}
        </PackageItem>
        <PackageItem label="Cover letter" attention={false}>
          {coverLetterProvided ? (
            <span>Provided — the text is stored with the payload</span>
          ) : (
            <span>None</span>
          )}
        </PackageItem>
        {questions.length > 0 ? (
          <PackageItem
            label="Answers the agent will give"
            attention={needsHuman > 0}
          >
            <span>
              {answerable} answered from your profile
              {needsHuman > 0
                ? ` · ${needsHuman} need${needsHuman === 1 ? "s" : ""} you (below)`
                : ""}
            </span>
          </PackageItem>
        ) : null}
        {customFieldCount > 0 ? (
          <PackageItem label="Answers you provided">
            <span>
              {customFieldCount} custom field
              {customFieldCount === 1 ? "" : "s"} typed into the prepare form
            </span>
          </PackageItem>
        ) : null}
        <PackageItem label="Profile facts the agent may use">
          <PlainText as="span">
            {formatList(summary.profile_fact_names)}
          </PlainText>
        </PackageItem>
        {summary.requires_manual_review ? (
          <PackageItem label="Manual review" attention>
            <span>The form needs a human to complete it</span>
          </PackageItem>
        ) : null}
      </ul>
    </div>
  )
}
