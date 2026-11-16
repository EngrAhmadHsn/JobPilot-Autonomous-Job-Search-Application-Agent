/**
 * The backend's status vocabulary, and what each status means to a human.
 *
 * The console **never invents** a status: every label here is keyed by the
 * exact string the backend returns. A status the console does not know is
 * rendered as its raw value, with a neutral tone — hiding an unfamiliar
 * status would be a lie of omission, and colouring it "danger" would be a
 * lie of interpretation.
 *
 * Each entry carries the "what must a human do next" line, because a status
 * without a next step is just a word.
 */

/** How a status is presented. */
export type StatusTone =
  "neutral" | "info" | "progress" | "success" | "warning" | "danger"

/**
 * The Lucide icon that marks the status, by export name from
 * `lucide-react`. The name travels as data so this module stays free of
 * React imports; `components/ui/status-badge.tsx` owns the name → component
 * map and validates it by test.
 */
export type StatusIconName = string

export interface StatusPresentation {
  /** The label shown to the operator. */
  label: string
  /** The visual tone. */
  tone: StatusTone
  /** The Lucide icon name that marks the status (WS-34). */
  icon: StatusIconName
  /** What a human has to do next (or why nothing is needed). */
  nextStep: string
}

const APPLICATION_STATUSES: Record<string, StatusPresentation> = {
  discovered: {
    label: "Discovered",
    tone: "neutral",
    icon: "Search",
    nextStep: "The listing was found. Nothing has been prepared yet.",
  },
  matched: {
    label: "Matched",
    tone: "neutral",
    icon: "Target",
    nextStep:
      "The profile was scored against this listing. Nothing has been prepared yet.",
  },
  shortlisted: {
    label: "Shortlisted",
    tone: "info",
    icon: "Bookmark",
    nextStep: "The listing was shortlisted. Nothing has been prepared yet.",
  },
  prepared: {
    label: "Prepared",
    tone: "info",
    icon: "FileText",
    nextStep:
      "The application payload was built and is waiting for an approval decision.",
  },
  awaiting_approval: {
    label: "Awaiting approval",
    tone: "warning",
    icon: "Clock",
    nextStep:
      "A human must approve the prepared application before anything is submitted.",
  },
  submitted: {
    label: "Submitted, not yet verified",
    tone: "progress",
    icon: "Send",
    nextStep:
      "The form was submitted. The confirmation still has to be verified.",
  },
  verified: {
    label: "Verified",
    tone: "success",
    icon: "BadgeCheck",
    nextStep:
      "The evidence confirms the submission. Nothing further is needed.",
  },
  rejected: {
    label: "Rejected",
    tone: "danger",
    icon: "CircleX",
    nextStep: "The application was declined. This state is final.",
  },
  /*
    WS-34: the human outcomes are terracotta, not lime. Lime is the
    agent's mark, and an interview or an offer is something a **human**
    recorded — colouring it lime claimed the agent's credit for it.
  */
  interview: {
    label: "Interview",
    tone: "warning",
    icon: "MessagesSquare",
    nextStep:
      "A human outcome was recorded. The agent takes no further action.",
  },
  offer: {
    label: "Offer",
    tone: "warning",
    icon: "Trophy",
    nextStep:
      "A human outcome was recorded. The agent takes no further action.",
  },
  withdrawn: {
    label: "Withdrawn",
    tone: "neutral",
    icon: "Archive",
    nextStep:
      "A human outcome was recorded. The agent takes no further action.",
  },
}

const RESULT_STATUSES: Record<string, StatusPresentation> = {
  needs_human: {
    label: "Needs a human answer",
    tone: "warning",
    icon: "CircleHelp",
    nextStep:
      "The form asked something the candidate's evidence does not answer. Answer the questions by hand and re-run the flow.",
  },
  form_error: {
    label: "The form was rejected",
    tone: "danger",
    icon: "FileWarning",
    nextStep:
      "The server refused the form. Read the error list, fix the inputs and try again.",
  },
  blocked_human_review: {
    label: "Blocked by a challenge",
    tone: "warning",
    icon: "ShieldAlert",
    nextStep:
      "A CAPTCHA or a multi-factor prompt stopped the flow. Nothing was submitted and nothing was bypassed — finish it by hand.",
  },
  verification_failed: {
    label: "Could not be verified",
    tone: "danger",
    icon: "ShieldX",
    nextStep:
      "The submission is not confirmed. Inspect the evidence below and complete the application by hand if needed.",
  },
  unsafe_navigation: {
    label: "Blocked by the domain allowlist",
    tone: "danger",
    icon: "Ban",
    nextStep:
      "The page redirected to a host that is not on the allowlist. Nothing was submitted.",
  },
  // WS-32: an approved submission is accepted as durable work and the
  // answer carries the **run's** status, not the application's. `QUEUED` is
  // not a failure and not a success: the work is recorded, a worker will
  // perform it, and the run id is how the operator follows it.
  QUEUED: {
    label: "Accepted and queued",
    tone: "info",
    icon: "Hourglass",
    nextStep:
      "The submission is accepted as background work and runs as soon as a worker is available. Follow it by its run id.",
  },
}

const APPROVAL_STATUSES: Record<string, StatusPresentation> = {
  pending: {
    label: "Pending",
    tone: "warning",
    icon: "Clock",
    nextStep: "A human must approve or reject this prepared application.",
  },
  approved: {
    label: "Approved",
    tone: "info",
    icon: "Check",
    nextStep: "The approval was recorded; the execution result is below.",
  },
  /*
    This label matches the application status of the same name on
    purpose: the two vocabularies never render in one list (an approval
    decision is a Review-surface fact; an application status is a
    Tracker fact), and the status-table test enforces distinctness
    within the application vocabulary, not across the namespaces. If a
    screen ever renders both in one view, this is the label to revisit.
  */
  rejected: {
    label: "Rejected",
    tone: "neutral",
    icon: "CircleMinus",
    nextStep: "The operator rejected this application. Nothing was submitted.",
  },
  executed: {
    label: "Executed",
    tone: "success",
    icon: "CircleCheck",
    nextStep: "The approved payload was executed. The evidence is below.",
  },
  failed: {
    label: "Failed",
    tone: "danger",
    icon: "TriangleAlert",
    nextStep: "The execution did not succeed. The evidence says why.",
  },
}

/*
  WS-34: the one run status that crosses into `describeStatus` consumers.
  A `202` answer's `QUEUED` was already here; `RUNNING` is the state the
  same run moves to while a worker executes it, and a screen that renders
  a run's status as a badge needs the same single presentation. The rest
  of the run vocabulary (`RETRY_WAIT`, `PAUSED`, `RECOVERABLE`,
  `COMPLETED`, `PARTIAL`, `CANCELLED`, run-level `FAILED`) is presented by
  `components/observability/run-progress.tsx`, which owns that surface;
  duplicating it here would create two competing presentations for one
  state. (The backend has no `uncertain` status: `submission.uncertain`
  is an internal audit event that never reaches the console as a status
  value — the honest console states for that path are "Blocked by a
  challenge" and "Could not be verified".)
*/
const RUN_STATUSES: Record<string, StatusPresentation> = {
  RUNNING: {
    label: "Running",
    tone: "progress",
    icon: "LoaderCircle",
    nextStep:
      "A worker is executing this run now. Its progress is shown with the run.",
  },
}

/**
 * Every known status, in one map.
 *
 * WS-15: the map is built with a **null prototype**. A plain object
 * inherits from `Object.prototype`, so a server-supplied status of
 * `"constructor"` or `"toString"` would be found on the prototype chain
 * and returned as if it were a status — the badge would then render an
 * empty label, and the unknown status would be swallowed instead of shown
 * verbatim, which is the one thing this file promises to do.
 */
const ALL: Record<string, StatusPresentation> = Object.assign(
  Object.create(null) as Record<string, StatusPresentation>,
  APPLICATION_STATUSES,
  RESULT_STATUSES,
  APPROVAL_STATUSES,
  RUN_STATUSES
)

/** Every application status the backend knows, for the filter control. */
export const APPLICATION_STATUS_NAMES = Object.keys(APPLICATION_STATUSES)

/**
 * Every status this console can present, for the status-table test and for
 * any surface that needs to enumerate the vocabulary. The backend's states
 * that never reach a `describeStatus` consumer (the rest of the run
 * vocabulary) are deliberately absent — see the RUN_STATUSES note.
 */
export const KNOWN_STATUS_NAMES = Object.keys(ALL)

/**
 * The statuses only a human may set. The backend's actor rule enforces this
 * on the server; the console offers exactly these four and nothing else.
 */
export const HUMAN_OUTCOME_STATUS_NAMES = [
  "interview",
  "offer",
  "rejected",
  "withdrawn",
] as const

/** How a status is presented. Unknown statuses are shown verbatim. */
export function describeStatus(
  status: string | null | undefined
): StatusPresentation {
  if (!status) {
    return {
      label: "Unknown",
      tone: "neutral",
      icon: "CircleDashed",
      nextStep: "The server did not report a status for this record.",
    }
  }
  // WS-15: the lookup is an **own** property lookup, so a status named
  // "constructor" or "toString" is not found on the prototype chain and
  // falls through to the verbatim branch below.
  const known = Object.hasOwn(ALL, status) ? ALL[status] : undefined
  if (known) return known
  return {
    label: status,
    tone: "neutral",
    icon: "CircleDashed",
    nextStep:
      "The server reported a status this console does not know. The raw value is shown unchanged.",
  }
}

/** True when the status is one a human may set. */
export function isHumanOutcomeStatus(status: string): boolean {
  return (HUMAN_OUTCOME_STATUS_NAMES as readonly string[]).includes(status)
}
