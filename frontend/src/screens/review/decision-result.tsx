import { PlainText } from "@/components/common/plain-text"
import { Banner, type BannerTone } from "@/components/common/banner"
import { FieldList } from "@/components/common/field-list"
import { StatusBadge, StatusExplainer } from "@/components/common/status-badge"
import { LinkButton } from "@/components/ui/link-button"
import { Card, CardContent } from "@/components/ui/card"
import { apiUrl } from "@/lib/api/client"
import type { ApprovalDecisionResponse } from "@/lib/api/types"
import { asString, asStringArray } from "@/lib/safe"

/**
 * What the decision actually says (WS-32).
 *
 * Approving no longer performs the submission inside the request: it records
 * the decision, **accepts** the submission as durable work and answers `202`
 * with the run a worker will execute. `success: false` is that contract, not
 * a failure — nothing has been submitted yet — so reading `success` alone
 * would present an accepted, queued submission as "not submitted", and an
 * operator who reads that will prepare the same job again.
 *
 * Three cases, from the response alone:
 *
 * - **submitted** — a completed execution's own verdict (`success`);
 * - **queued** — a run id came back and no execution has happened yet;
 * - **refused** — everything else: a refusal, a rejected form, a challenge,
 *   a failure. The questions, errors and evidence below carry the detail.
 */
type DecisionOutcome = "submitted" | "queued" | "refused"

export function decisionOutcome(
  result: ApprovalDecisionResponse
): DecisionOutcome {
  if (result.success) return "submitted"
  if (result.run_id) return "queued"
  return "refused"
}

const DECISION_BANNERS: Record<
  DecisionOutcome,
  { tone: BannerTone; title: string }
> = {
  submitted: { tone: "success", title: "The application was submitted" },
  queued: {
    tone: "info",
    /*
      The headline is the audit fix (WS-33 §2.3-4): the button used to say
      "Approve and submit" while the route answers 202 + a run id. The
      banner says what actually happened — the decision was recorded, the
      work was queued — and never "submitted": the employer has not been
      reached. The run id and the next step follow in the body.
    */
    title: "Approved — queued",
  },
  refused: { tone: "warning", title: "The application was not submitted" },
}

/** The result of a decision, with the evidence that came with it. */
export function DecisionResult({
  result,
  applicationId,
}: {
  result: ApprovalDecisionResponse
  applicationId: string | null
}) {
  const outcome = decisionOutcome(result)
  const banner = DECISION_BANNERS[outcome]
  const metadata = result.metadata ?? {}
  const questions = asStringArray(metadata.questions)
  const errors = asStringArray(metadata.errors)
  const challenge = asString(metadata.challenge)
  const evidence = result.evidence
  // The evidence object is a free-form dictionary on the wire, so every value
  // is read through the safe accessors.
  const screenshotPath = asString(evidence?.screenshot_path)
  const separator = Math.max(
    screenshotPath.lastIndexOf("/"),
    screenshotPath.lastIndexOf(String.fromCharCode(92))
  )
  const screenshotName =
    separator >= 0 ? screenshotPath.slice(separator + 1) : screenshotPath

  return (
    <Card className="rounded-2xl">
      <CardContent className="space-y-4 pt-6">
        <div className="flex flex-wrap items-center gap-3">
          <h2 className="font-heading text-lg font-semibold tracking-tight text-foreground">
            The decision
          </h2>
          <StatusBadge status={result.status} />
        </div>

        <StatusExplainer status={result.status} />

        <Banner tone={banner.tone} title={banner.title}>
          <PlainText as="span">{result.message}</PlainText>
          {outcome === "queued" && result.run_id ? (
            // The run id is what the operator follows; without it the
            // acceptance is a dead end. Nothing is claimed as done.
            <div className="mt-1.5 space-y-2">
              <p>
                Run{" "}
                <code className="font-mono text-[11px] wrap-anywhere">
                  {result.run_id}
                </code>{" "}
                is waiting for a worker. Nothing has been submitted yet — the
                run's outcome lands here and in Operations when the worker
                finishes.
              </p>
              <LinkButton to="/app/operations" variant="outline" size="sm">
                Follow the run in Operations
              </LinkButton>
            </div>
          ) : null}
        </Banner>

        {questions.length > 0 ? (
          <div className="space-y-1">
            <h3 className="text-sm font-medium text-foreground">
              The form asked questions the evidence does not answer
            </h3>
            <ul className="list-disc space-y-1 pl-5 text-sm text-muted-foreground">
              {questions.map((question) => (
                <li key={question}>
                  <PlainText as="span">{question}</PlainText>
                </li>
              ))}
            </ul>
          </div>
        ) : null}

        {errors.length > 0 ? (
          <div className="space-y-1">
            <h3 className="text-sm font-medium text-foreground">
              The server refused the form
            </h3>
            <ul className="list-disc space-y-1 pl-5 text-sm text-muted-foreground">
              {errors.map((error) => (
                <li key={error}>
                  <PlainText as="span">{error}</PlainText>
                </li>
              ))}
            </ul>
          </div>
        ) : null}

        {challenge ? (
          <Banner tone="warning" title="The flow stopped at a challenge">
            <p>
              The page presented{" "}
              <code className="font-mono text-[11px] wrap-anywhere">
                {challenge}
              </code>
              . Nothing was submitted and nothing was bypassed — complete it by
              hand.
            </p>
          </Banner>
        ) : null}

        {evidence ? (
          <div className="space-y-2">
            <h3 className="text-sm font-medium text-foreground">Evidence</h3>
            <FieldList
              items={[
                { label: "URL", value: asString(evidence.url) || "—" },
                {
                  label: "Confirmation",
                  value: asString(evidence.confirmation_text) ? (
                    <PlainText as="span">
                      {asString(evidence.confirmation_text)}
                    </PlainText>
                  ) : (
                    "—"
                  ),
                },
                {
                  label: "Evidence status",
                  value: asString(evidence.status) || "—",
                },
                { label: "Screenshot", value: screenshotPath || "—" },
                { label: "Trace", value: asString(evidence.trace_path) || "—" },
              ]}
            />

            {screenshotPath && applicationId && screenshotName ? (
              <figure className="space-y-1">
                <img
                  src={apiUrl(
                    `/api/applications/${encodeURIComponent(applicationId)}/evidence/${encodeURIComponent(screenshotName)}`
                  )}
                  alt="The screenshot captured as evidence of the submission"
                  className="max-w-full rounded-xl border border-border"
                />
                <figcaption className="text-xs text-muted-foreground">
                  The screenshot the browser captured at the moment of the
                  outcome.
                </figcaption>
              </figure>
            ) : null}
          </div>
        ) : outcome === "queued" ? (
          // An accepted submission has no evidence yet by definition: the
          // worker has not reached the employer. Saying "no evidence" here
          // would read as a defect rather than as the contract.
          <p className="text-sm text-muted-foreground">
            Nothing has been submitted yet, so there is no evidence to show. The
            run carries the outcome when the worker finishes.
          </p>
        ) : (
          <p className="text-sm text-muted-foreground">
            The result carried no evidence. Nothing is claimed on the strength
            of this decision.
          </p>
        )}
      </CardContent>
    </Card>
  )
}
