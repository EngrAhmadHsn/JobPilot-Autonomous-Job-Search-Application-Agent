import { PlainText } from "@/components/common/plain-text"
import type { BoardQuestion } from "@/lib/api/types"

import { CLAY_CHIP, FOREST_CHIP, OUTLINE_CHIP, SAGE_CHIP } from "./chips"

/*
  The read-only queue of the Review screen (WS-42, design node `49:1096` —
  "One answer needs you.").

  Since WS-45 the **answering** lives one card up, in `question-answer.tsx`:
  a human answer is stored on the tracked application and a re-prepare
  re-merges it, so a required question no longer blocks with no path
  through. What stays here is the thing a human approves — the board's own
  ordered list, every question carrying its verdict and its answer's
  source. The design's "Needs you / Confirmed" pills render as stat chips,
  deliberately **not** filters: a filter would hide the board's published
  order, which is the order the agent will walk and the thing the operator
  is approving.

  When questions still need a human, the answering card carries the
  heading and the chips and this card renders `listOnly` — the same list,
  without a second headline above it.

  `prepared_summary.field_names` is **our** internal field map, sorted
  alphabetically on the server. The board's own question order arrives in
  `form_questions`, in the order the board publishes it — so the operator
  approves by reading the form they are about to have filled, not a
  re-sorted copy of our map. A board that publishes no schema, or one that
  timed out during the prepare (both fail soft on the server), returns an
  empty list and this renders nothing.

  Question labels are board-supplied text, so they render through
  `PlainText` like every other untrusted string.
*/

/**
 * The board's question queue: every question, in the board's own order,
 * with the verdict and the answer's source. With `listOnly`, the heading
 * and the stat chips are omitted — the answering card above carries them —
 * and the list alone renders.
 */
export function QuestionCard({
  questions,
  blockers,
  listOnly = false,
}: {
  questions: BoardQuestion[]
  blockers: string[]
  /** Omit the heading and stat chips — the answering card carries them. */
  listOnly?: boolean
}) {
  if (questions.length === 0) {
    return null
  }
  const blocked = new Set(blockers)
  const isBlocked = (question: BoardQuestion) =>
    blocked.has(question.label) || question.verdict === "needs_human"
  const needsYou = questions.filter(isBlocked).length
  const confirmed = questions.length - needsYou

  return (
    <section
      id="board-questions"
      data-testid="board-questions"
      className="flex min-w-0 flex-col gap-3.5 rounded-surface border border-border-surface bg-card p-5"
    >
      {listOnly ? null : (
        <>
          <h2 className="text-[20px] leading-[29px] font-semibold text-primary">
            {needsYou === 0
              ? "Every answer is in hand."
              : needsYou === 1
                ? "One answer needs you."
                : `${needsYou} answers need you.`}
          </h2>

          {/*
            The design's count pills (nodes `49:1100` / `49:1102`), as stat
            chips — the counts the data supports, never a filter that would
            reorder or hide the board's own sequence.
          */}
          <div className="flex flex-wrap items-center gap-2.5">
            <span className={needsYou > 0 ? FOREST_CHIP : OUTLINE_CHIP}>
              Needs you {needsYou}
            </span>
            <span className={OUTLINE_CHIP}>Confirmed {confirmed}</span>
          </div>
        </>
      )}

      <p className="text-xs leading-relaxed text-muted-foreground">
        {needsYou > 0
          ? `${needsYou} of ${questions.length} the profile does not answer — they need a human. As the board publishes them, in order.`
          : "As the board publishes them, in order — this is what the agent will work through."}
      </p>

      <ol className="space-y-3">
        {questions.map((question, index) => (
          <li
            key={question.label}
            className="space-y-1.5 border-t border-border-surface pt-3 first:border-t-0 first:pt-0"
          >
            <div className="flex flex-wrap items-center gap-2">
              <span className={SAGE_CHIP}>
                QUESTION {index + 1} OF {questions.length}
              </span>
              {question.required ? (
                <span className={CLAY_CHIP}>Required</span>
              ) : null}
            </div>
            <PlainText className="text-sm font-semibold text-foreground">
              {question.label}
            </PlainText>
            <div>
              <AnswerSourceChip
                question={question}
                blocked={blocked.has(question.label)}
              />
            </div>
          </li>
        ))}
      </ol>
    </section>
  )
}

/**
 * The one chip that says where an answer comes from.
 *
 * The verdicts are the backend's (`answerable | never_autofill |
 * needs_human | optional_unanswered`; an older payload says `autofillable`
 * or `skipped` for the last two). `needs_human` — or a name in
 * `blocking_questions` — is the terracotta "needs a human" mark. An
 * `answerable` question names the source it is answered from: the profile
 * fact it reads, or `you` — the answer the human saved on the Review
 * screen (WS-45), which is the operator's own word and says so. Any other
 * verdict renders verbatim, like an unknown status: a second opinion about
 * what "autofillable" means is a lie the console cannot check.
 */
function AnswerSourceChip({
  question,
  blocked,
}: {
  question: BoardQuestion
  blocked: boolean
}) {
  if (blocked || question.verdict === "needs_human") {
    return <span className={CLAY_CHIP}>needs a human</span>
  }
  if (question.answer_from === "you") {
    return (
      <span className={SAGE_CHIP} title="Answered by you on the Review screen">
        answered by you
      </span>
    )
  }
  if (question.verdict === "answerable") {
    return (
      <span
        className={SAGE_CHIP}
        // The sage wash is the agent's mark; the text names the source.
        title={
          question.answer_from
            ? `Answered from the profile fact: ${question.answer_from}`
            : "The agent can answer this from your profile"
        }
      >
        {question.answer_from
          ? `from your profile: ${question.answer_from}`
          : "the agent can answer"}
      </span>
    )
  }
  if (question.verdict === "never_autofill") {
    return (
      <span
        className="inline-flex items-center rounded-[6px] border border-border-surface px-2.5 py-1 text-[11px] leading-4 font-semibold text-muted-foreground"
        title="Answered by you on the employer's own site — this console never autofills it"
      >
        answered on the employer site
      </span>
    )
  }
  return (
    <span className="inline-flex items-center rounded-[6px] border border-border-surface px-2.5 py-1 text-[11px] leading-4 font-semibold text-muted-foreground">
      {question.verdict}
    </span>
  )
}
