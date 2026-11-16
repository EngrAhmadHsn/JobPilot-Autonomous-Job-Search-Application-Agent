import { Link } from "react-router-dom"

import { InlineSkeleton } from "@/components/common/card-skeleton"
import { PlainText } from "@/components/common/plain-text"
import { StatusBadge } from "@/components/ui/status-badge"
import { EmptyState } from "@/components/ui/empty-state"
import { LinkButton } from "@/components/ui/link-button"

/*
  "Your attention" (WS-35) — the screen's answer to "what is my next useful
  action", before anything else on the page competes for it.

  Every row is a real, resolvable thing: an approval waiting for a decision,
  a trail entry a human should read, a question the boards ask that the
  profile does not answer, a missing résumé. Each row links to the screen
  that resolves it — no row is a dead end. When a source could not be read,
  the failure is named with the way back — an unreadable source is not a
  clean bill of health — and the section's all-clear renders only once
  every source has actually answered: a quiet "nothing needs you" while a
  source is still unknown would be a lie by omission.
*/

/** A summary row: a count of things, and the screen that resolves them. */
export interface AttentionItem {
  key: string
  title: string
  body: string
  to: string
  /** The action's words, on the button at the row's end. */
  label: string
}

/** A source that could not be read, with the way back. */
export interface AttentionFailure {
  key: string
  title: string
  body: string
  onRetry: () => void
}

/**
 * One awaiting-decision application, shown as its own row.
 *
 * Both resting states a decision resolves — `prepared` and
 * `awaiting_approval` — render this way. The status renders through the one
 * presentation (`describeStatus`, via `StatusBadge`) — never a screen-local
 * label — and the row links to the application's own tracker page, where
 * its history and evidence live.
 */
export interface AttentionApplication {
  id: string
  jobTitle: string
  company: string
  status: string
}

function ApplicationRow({
  application,
}: {
  application: AttentionApplication
}) {
  return (
    <li>
      <Link
        to={`/app/tracker/${encodeURIComponent(application.id)}`}
        viewTransition
        className="group grid grid-cols-[minmax(0,1fr)_auto] items-center gap-x-3 gap-y-1.5 rounded-xl border border-border bg-card px-4 py-3 transition-colors duration-150 hover:bg-muted/60"
      >
        <span className="flex min-w-0 flex-wrap items-center gap-x-3 gap-y-1.5">
          <StatusBadge status={application.status} />
          <PlainText as="span" className="text-sm font-medium wrap-anywhere">
            {application.jobTitle}
          </PlainText>
          <PlainText
            as="span"
            className="text-sm wrap-anywhere text-muted-foreground"
          >
            {application.company}
          </PlainText>
        </span>
        <span
          aria-hidden="true"
          className="text-muted-foreground transition-colors duration-150 group-hover:text-foreground"
        >
          →
        </span>
      </Link>
    </li>
  )
}

function SummaryRow({ item }: { item: AttentionItem }) {
  return (
    <li className="enter-up flex flex-wrap items-center justify-between gap-3 rounded-xl border border-terracotta/50 bg-terracotta-soft/60 px-4 py-3">
      <div className="max-w-[52ch] min-w-0">
        <p className="text-sm font-medium text-foreground">{item.title}</p>
        <p className="mt-0.5 text-sm text-muted-foreground">{item.body}</p>
      </div>
      <LinkButton to={item.to} variant="outline" size="sm">
        {item.label}
      </LinkButton>
    </li>
  )
}

/*
  The failure row carries the destructive tones — the design system's rule
  is that terracotta means "a human must act", while a failed read is an
  error, which is `--destructive`'s job. The copy and the "Try again"
  control follow `ErrorState`'s pattern (a real action, not an apology).
*/
function FailureRow({ failure }: { failure: AttentionFailure }) {
  return (
    <li className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-destructive/40 bg-destructive/5 px-4 py-3">
      <div className="max-w-[52ch] min-w-0">
        <p className="text-sm font-medium text-foreground">{failure.title}</p>
        <p className="mt-0.5 text-sm text-muted-foreground">{failure.body}</p>
      </div>
      <button
        type="button"
        onClick={failure.onRetry}
        className="inline-flex h-9 items-center rounded-lg border border-border bg-card px-3 text-sm font-medium text-foreground transition-colors duration-150 hover:bg-muted hover:text-foreground"
      >
        Try again
      </button>
    </li>
  )
}

export function AttentionSection({
  items,
  applications,
  failures = [],
  sourcesReady,
}: {
  items: AttentionItem[]
  /** The newest awaiting-decision applications, already cut to a few. */
  applications: AttentionApplication[]
  /** Sources that could not be read — named, never swallowed. */
  failures?: AttentionFailure[]
  /**
   * True only when every attention source answered successfully. The
   * all-clear depends on it; while sources are pending (or failed without a
   * row of their own — the applications banner covers those), the section
   * shows bones instead of claiming "nothing".
   */
  sourcesReady: boolean
}) {
  const hasRows =
    items.length > 0 || applications.length > 0 || failures.length > 0

  if (!hasRows) {
    if (!sourcesReady) {
      // Sources still answering (or a failure the banner above the strip
      // already names): no all-clear until they have.
      return (
        <div aria-busy="true">
          <InlineSkeleton />
        </div>
      )
    }
    return (
      <EmptyState
        title="Nothing needs you right now"
        message="No approvals are waiting and the recent trail is clean. The agent holds anything that would need a decision."
      />
    )
  }

  return (
    <div className="space-y-3">
      {items.length > 0 ? (
        <ul className="space-y-3">
          {items.map((item) => (
            <SummaryRow key={item.key} item={item} />
          ))}
        </ul>
      ) : null}
      {failures.length > 0 ? (
        <ul className="space-y-3">
          {failures.map((failure) => (
            <FailureRow key={failure.key} failure={failure} />
          ))}
        </ul>
      ) : null}
      {applications.length > 0 ? (
        <ul className="space-y-2">
          {applications.map((application) => (
            <ApplicationRow key={application.id} application={application} />
          ))}
        </ul>
      ) : null}
    </div>
  )
}
