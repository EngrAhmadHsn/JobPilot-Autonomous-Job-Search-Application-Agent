/*
  The four stage groups of the Applications board (WS-42).

  The design file's screen 05 draws **four** columns — Awaiting review,
  Needs you, In progress, Outcome recorded — and the backend vocabulary has
  eleven statuses (`src/applications/tracking.py:50-63`). So a column is a
  **group** of statuses, and each mapping below is a claim about what those
  statuses mean. None of them is invented: every member is a real status, and
  the comment says why it belongs.

  This module exists separately from the board so that the board, Home's
  stage tiles and the tests all read **one** declaration — three screens
  disagreeing about which stage an application is in would be worse than any
  of them being wrong alone.
*/

/** One board column: a stage name over the statuses that belong to it. */
export interface StageGroup {
  /** Stable key for query keys and DOM ids. */
  key: string
  /** The column's title, in the design's own words. */
  label: string
  /** Every status this stage covers — the multi-status filter's value. */
  statuses: string[]
  /** One line saying what the stage means, shown under the title. */
  meaning: string
  /** The stage's bar colour token (`bg-stage-*`). */
  tone: string
}

/*
  Why these groupings, in the journey's own terms:

  - **Awaiting review** — `awaiting_approval` and `prepared`. Both mean the
    package exists and a human has not decided. `prepared` is included
    because the vocabulary itself says it is "waiting for an approval
    decision", and because the tracked row is created `prepared` and only
    then moved in a second write that can fail and roll back — so a
    `prepared` row is a decision that has not landed, not a different stage.

  - **Needs you** — `verified`. This is the honest awkward one. `verified`
    means **the submission was confirmed by evidence**; the machine saw it
    land. It is *not* "waiting to be submitted" and must never be presented
    that way. It sits in "Needs you" because the machine's work is done and
    nothing further will happen until a person records what came of it —
    and the column's own copy says exactly that.

  - **In progress** — `submitted`. Sent to the board; the confirmation is
    still pending, so the agent is still the actor.

  - **Outcome recorded** — `interview`, `offer`, `rejected`, `withdrawn`.
    Every one of these requires a human: the platform never infers an
    interview or an offer from a page it read.

  The pre-application states (`discovered`, `matched`, `shortlisted`) are
  deliberately in **no** column: they are not tracked applications, they have
  no tracked row, and a column for them would always read zero and imply a
  stage that does not exist. The board says so above the columns.
*/
export const STAGE_GROUPS: StageGroup[] = [
  {
    key: "review",
    label: "Awaiting review",
    statuses: ["awaiting_approval", "prepared"],
    meaning: "A human decision is what moves these.",
    tone: "bg-stage-review",
  },
  {
    key: "needs-you",
    label: "Needs you",
    statuses: ["verified"],
    meaning:
      "Confirmed by evidence. Nothing further happens until you record the outcome.",
    tone: "bg-stage-handoff",
  },
  {
    key: "in-progress",
    label: "In progress",
    statuses: ["submitted"],
    meaning: "Sent to the board; the confirmation is still pending.",
    tone: "bg-stage-progress",
  },
  {
    key: "outcome",
    label: "Outcome recorded",
    statuses: ["interview", "offer", "rejected", "withdrawn"],
    meaning: "A person recorded this. The agent takes no further action.",
    tone: "bg-stage-outcome",
  },
]

/** The statuses that are **not** on the board, and why (for the legend). */
export const OFF_BOARD_STATUSES = ["discovered", "matched", "shortlisted"]
