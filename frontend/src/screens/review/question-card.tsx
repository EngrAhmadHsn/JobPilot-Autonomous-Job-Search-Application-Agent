import { PlainText } from "@/components/common/plain-text"
import type { BoardQuestion } from "@/lib/api/types"

/*
  The question queue of the Review screen (WS-42, design node `49:1096` —
  "One answer needs you.").

  The design draws one question at a time with radio options and a save. The
  backend has no per-answer persistence to save into — an answer exists only
  as a custom field inside a freshly **prepared** payload — so the console
  renders what it can prove: the board's own ordered list, every question
  carrying its verdict. The design's "Needs you / Confirmed" pills render as
  stat chips, deliberately **not** filters: a filter would hide the board's
  published order, which is the order the agent will walk and the thing the
  operator is approving.

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

/** The wash-chip look shared by the queue's position and count chips. */
const SAGE_CHIP =
  "inline-flex items-center rounded-[6px] bg-forest-soft px-2.5 py-1 text-[11px] font-semibold leading-4 text-primary"
const CLAY_CHIP =
  "inline-flex items-center rounded-[6px] bg-terracotta-soft px-2.5 py-1 text-[11px] font-semibold leading-4 text-terracotta-foreground"
const FOREST_CHIP =
  "inline-flex items-center rounded-[6px] bg-primary px-2.5 py-1 text-[11px] font-semibold leading-4 text-primary-foreground"
const OUTLINE_CHIP =
  "inline-flex items-center rounded-[6px] border border-border-surface bg-card px-2.5 py-1 text-[11px] font-semibold leading-4 text-primary"

export function QuestionCard({
  questions,
  blockers,
}: {
  questions: BoardQuestion[]
  blockers: string[]
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
      data-testid="board-questions"
      className="flex min-w-0 flex-col gap-3.5 rounded-surface border border-border-surface bg-card p-5"
    >
      <h2 className="text-[20px] font-semibold leading-[29px] text-primary">
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
 * The verdicts are the backend's (`answerable | needs_human | autofillable |
 * skipped`). `needs_human` — or a name in `blocking_questions` — is the
 * terracotta "needs a human" mark. An `answerable` question names the
 * profile fact it is answered from, which is the "confirmed profile fact"
 * source; the candidate-provided answers are counted in the packet, not
 * re-attributed here, because the response does not tie custom fields to
 * questions. Any other verdict renders verbatim, like an unknown status:
 * a second opinion about what "autofillable" means is a lie the console
 * cannot check.
 */
function AnswerSourceChip({
  question,
  blocked,
}: {
  question: BoardQuestion
  blocked: boolean
}) {
  if (blocked || question.verdict === "needs_human") {
    return (
      <span className={CLAY_CHIP}>needs a human</span>
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
  return (
    <span className="inline-flex items-center rounded-[6px] border border-border-surface px-2.5 py-1 text-[11px] font-semibold leading-4 text-muted-foreground">
      {question.verdict}
    </span>
  )
}
