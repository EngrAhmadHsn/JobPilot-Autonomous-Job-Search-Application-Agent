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

export interface StatusPresentation {
  /** The label shown to the operator. */
  label: string
  /** The visual tone. */
  tone: StatusTone
  /** What a human has to do next (or why nothing is needed). */
  nextStep: string
}

const APPLICATION_STATUSES: Record<string, StatusPresentation> = {
  discovered: {
    label: "Discovered",
    tone: "neutral",
    nextStep: "The listing was found. Nothing has been prepared yet.",
  },
  matched: {
    label: "Matched",
    tone: "neutral",
    nextStep:
      "The profile was scored against this listing. Nothing has been prepared yet.",
  },
  shortlisted: {
    label: "Shortlisted",
    tone: "info",
    nextStep: "The listing was shortlisted. Nothing has been prepared yet.",
  },
  prepared: {
    label: "Prepared",
    tone: "info",
    nextStep:
      "The application payload was built and is waiting for an approval decision.",
  },
  awaiting_approval: {
    label: "Awaiting approval",
    tone: "warning",
    nextStep:
      "A human must approve the prepared application before anything is submitted.",
  },
  submitted: {
    label: "Submitted, not yet verified",
    tone: "progress",
    nextStep:
      "The form was submitted. The confirmation still has to be verified.",
  },
  verified: {
    label: "Verified",
    tone: "success",
    nextStep:
      "The evidence confirms the submission. Nothing further is needed.",
  },
  rejected: {
    label: "Rejected",
    tone: "danger",
    nextStep: "The application was declined. This state is final.",
  },
  interview: {
    label: "Interview",
    tone: "success",
    nextStep:
      "A human outcome was recorded. The agent takes no further action.",
  },
  offer: {
    label: "Offer",
    tone: "success",
    nextStep:
      "A human outcome was recorded. The agent takes no further action.",
  },
  withdrawn: {
    label: "Withdrawn",
    tone: "neutral",
    nextStep:
      "A human outcome was recorded. The agent takes no further action.",
  },
}

const RESULT_STATUSES: Record<string, StatusPresentation> = {
  needs_human: {
    label: "Needs a human answer",
    tone: "warning",
    nextStep:
      "The form asked something the candidate's evidence does not answer. Answer the questions by hand and re-run the flow.",
  },
  form_error: {
    label: "The form was rejected",
    tone: "danger",
    nextStep:
      "The server refused the form. Read the error list, fix the inputs and try again.",
  },
  blocked_human_review: {
    label: "Blocked by a challenge",
    tone: "warning",
    nextStep:
      "A CAPTCHA or a multi-factor prompt stopped the flow. Nothing was submitted and nothing was bypassed — finish it by hand.",
  },
  verification_failed: {
    label: "Could not be verified",
    tone: "danger",
    nextStep:
      "The submission is not confirmed. Inspect the evidence below and complete the application by hand if needed.",
  },
  unsafe_navigation: {
    label: "Blocked by the domain allowlist",
    tone: "danger",
    nextStep:
      "The page redirected to a host that is not on the allowlist. Nothing was submitted.",
  },
}

const APPROVAL_STATUSES: Record<string, StatusPresentation> = {
  pending: {
    label: "Pending",
    tone: "warning",
    nextStep: "A human must approve or reject this prepared application.",
  },
  approved: {
    label: "Approved",
    tone: "info",
    nextStep: "The approval was recorded; the execution result is below.",
  },
  rejected: {
    label: "Rejected",
    tone: "neutral",
    nextStep: "The operator rejected this application. Nothing was submitted.",
  },
  executed: {
    label: "Executed",
    tone: "success",
    nextStep: "The approved payload was executed. The evidence is below.",
  },
  failed: {
    label: "Failed",
    tone: "danger",
    nextStep: "The execution did not succeed. The evidence says why.",
  },
}

const ALL: Record<string, StatusPresentation> = {
  ...APPLICATION_STATUSES,
  ...RESULT_STATUSES,
  ...APPROVAL_STATUSES,
}

/** Every application status the backend knows, for the filter control. */
export const APPLICATION_STATUS_NAMES = Object.keys(APPLICATION_STATUSES)

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
      nextStep: "The server did not report a status for this record.",
    }
  }
  const known = ALL[status]
  if (known) return known
  return {
    label: status,
    tone: "neutral",
    nextStep:
      "The server reported a status this console does not know. The raw value is shown unchanged.",
  }
}

/** True when the status is one a human may set. */
export function isHumanOutcomeStatus(status: string): boolean {
  return (HUMAN_OUTCOME_STATUS_NAMES as readonly string[]).includes(status)
}
