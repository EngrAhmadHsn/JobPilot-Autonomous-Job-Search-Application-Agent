import { PlainText } from "@/components/common/plain-text"
import { Banner } from "@/components/common/banner"
import { StatusBadge, StatusExplainer } from "@/components/common/status-badge"
import { LinkButton } from "@/components/ui/link-button"
import type { ApprovalStatus } from "@/lib/api/types"
import { formatDateTime } from "@/lib/format"

/**
 * The persisted approval state, read back from the server.
 *
 * This is the reload contract: the decision the human made is **stored** on
 * the approval row, and `GET /api/applications/approvals/{id}` reports it —
 * so a reload mid-run shows the truth the server holds, not whatever the
 * console happened to have in memory. The banner is built from that GET
 * response alone; the run id travels beside it (recorded from the 202 at
 * approval time) and is labelled as exactly that, because the GET does not
 * carry it.
 *
 * Every state the approval lifecycle actually has is rendered as itself:
 * `pending` (nobody decided), `approved` (decided, run queued),
 * `rejected` (decided, nothing queued), `expired` (the window closed —
 * WS-25), `executed` and `failed` (the run's recorded outcomes). An
 * unfamiliar status renders verbatim with its own explainer rather than
 * being folded into a convenient one.
 *
 * What the GET deliberately does **not** return is the payload itself, so
 * this banner never offers the approve action: approving without the exact
 * packet on screen would approve a payload the human is not looking at.
 * The way back to a full review is the prepare form.
 */
export function ApprovalStateBanner({
  state,
  runId,
}: {
  state: ApprovalStatus
  /** The run id recorded from the 202 when the approval was granted. */
  runId: string | null
}) {
  const decision = state.decided_at ? (
    <p className="text-xs text-muted-foreground">
      Decided {formatDateTime(state.decided_at)}
      {state.decision_reason ? (
        <>
          {" "}
          — reason: <PlainText as="span">{state.decision_reason}</PlainText>
        </>
      ) : null}
    </p>
  ) : null

  switch (state.status) {
    case "pending":
      return (
        <Banner
          tone="info"
          title="A prepared application is waiting for your decision"
        >
          <p>
            <PlainText as="span">
              {state.job_title} at {state.company_name}
            </PlainText>{" "}
            — approval{" "}
            <code className="font-mono text-[11px] wrap-anywhere">
              {state.approval_id}
            </code>
            , prepared {formatDateTime(state.created_at)}. Nothing has been
            submitted; nothing will be without your approval.
          </p>
          <p>
            The packet's full contents are not re-shown after a reload, and you
            approve only what you can see. Review it by preparing the
            application again — that stores a fresh payload and shows the
            complete form.
          </p>
          {decision}
        </Banner>
      )
    case "approved":
      return (
        <Banner tone="info" title="Approved — queued">
          <p>
            Your approval of{" "}
            <PlainText as="span">
              {state.job_title} at {state.company_name}
            </PlainText>{" "}
            (approval{" "}
            <code className="font-mono text-[11px] wrap-anywhere">
              {state.approval_id}
            </code>
            ) was recorded. The submission was accepted as durable work; a
            background worker performs it.
          </p>
          {runId ? (
            <p>
              Run{" "}
              <code className="font-mono text-[11px] wrap-anywhere">
                {runId}
              </code>{" "}
              was queued when you approved — follow it in Operations.
            </p>
          ) : null}
          <p>
            Nothing on this page claims the application reached the employer:
            the run's own outcome — submitted, verified, or stopped — is what
            Operations reports.
          </p>
          <div className="mt-2">
            <LinkButton to="/app/operations" variant="outline" size="sm">
              Open Operations
            </LinkButton>
          </div>
          {decision}
        </Banner>
      )
    case "rejected":
      return (
        <Banner tone="neutral" title="Rejected — nothing was submitted">
          <p>
            You rejected the application for{" "}
            <PlainText as="span">
              {state.job_title} at {state.company_name}
            </PlainText>{" "}
            (approval{" "}
            <code className="font-mono text-[11px] wrap-anywhere">
              {state.approval_id}
            </code>
            ). Nothing was submitted and nothing was queued.
          </p>
          {decision}
        </Banner>
      )
    case "expired":
      return (
        <Banner tone="warning" title="The approval expired">
          <p>
            The approval window for{" "}
            <PlainText as="span">
              {state.job_title} at {state.company_name}
            </PlainText>{" "}
            closed before a run was performed, so the decision is no longer
            executable. Nothing was submitted.
          </p>
          <p>
            To apply, prepare the application again: that stores a fresh payload
            with a new review and a new window.
          </p>
          {decision}
        </Banner>
      )
    case "executed":
      return (
        <Banner tone="success" title="Executed — the approved payload ran">
          <p>
            The payload you approved (approval{" "}
            <code className="font-mono text-[11px] wrap-anywhere">
              {state.approval_id}
            </code>
            ) was executed by a worker.
            {state.message ? " What it reported: " : ""}
            {state.message ? (
              <PlainText as="span">{state.message}</PlainText>
            ) : null}
          </p>
          <div className="mt-2 flex flex-wrap gap-2">
            <LinkButton to="/app/tracker" variant="outline" size="sm">
              Open the Tracker
            </LinkButton>
            <LinkButton to="/app/operations" variant="ghost" size="sm">
              Open Operations
            </LinkButton>
          </div>
          {decision}
        </Banner>
      )
    case "failed":
      return (
        <Banner tone="warning" title="The approved run did not succeed">
          <p>
            The run for approval{" "}
            <code className="font-mono text-[11px] wrap-anywhere">
              {state.approval_id}
            </code>{" "}
            did not complete.
            {state.message ? " What it reported: " : ""}
            {state.message ? (
              <PlainText as="span">{state.message}</PlainText>
            ) : null}{" "}
            Nothing is claimed as submitted — the run's evidence and the
            application's history say what actually happened.
          </p>
          <div className="mt-2 flex flex-wrap gap-2">
            <LinkButton to="/app/tracker" variant="outline" size="sm">
              Open the Tracker
            </LinkButton>
            <LinkButton to="/app/operations" variant="ghost" size="sm">
              Open Operations
            </LinkButton>
          </div>
          {decision}
        </Banner>
      )
    default:
      // An unfamiliar lifecycle state is shown verbatim — never hidden,
      // never recoloured into a state the console prefers.
      return (
        <Banner tone="neutral" title="The stored approval state">
          <div className="flex flex-wrap items-center gap-2">
            <StatusBadge status={state.status} />
          </div>
          <StatusExplainer status={state.status} />
          {decision}
        </Banner>
      )
  }
}
