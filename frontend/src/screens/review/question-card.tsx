import { PlainText } from "@/components/common/plain-text"
import type { BoardQuestion } from "@/lib/api/types"

/**
 * The board's own application form, as measured (WS-25b).
 *
 * `prepared_summary.field_names` is **our** internal field map, sorted
 * alphabetically on the server. The board's own question order arrives in
 * `form_questions`, in the order the board publishes it, and it is the order
 * the agent will walk — so the operator approves by reading the form they
 * are about to have filled, not a re-sorted copy of our map.
 *
 * Every question also carries its **answer source**, because "the agent
 * knows this" and "nobody knows this" are different approvals: a question
 * answered from the profile names the fact it is answered from; a question
 * the evidence cannot answer is named as needing a human — the same
 * `blocking_questions` verdict the backend reported, in the board's own
 * wording. A board that publishes no schema, or one that timed out during
 * the prepare (both fail soft on the server), returns an empty list and
 * this renders nothing: the panel is unchanged where there is nothing
 * measured to show.
 *
 * Question labels are board-supplied text, so they render through
 * `PlainText` like every other untrusted string.
 */
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
  const blockedCount = questions.filter((question) =>
    blocked.has(question.label)
  ).length

  return (
    <div
      data-testid="board-questions"
      className="rounded-xl border border-border bg-card/60 p-3.5"
    >
      <h3 className="font-heading text-sm font-semibold tracking-tight text-foreground">
        Questions this board asks
      </h3>
      <p className="mt-0.5 mb-2.5 text-xs leading-relaxed text-muted-foreground">
        {blockedCount > 0
          ? `${blockedCount} of ${questions.length} the profile does not answer — they need a human. As the board publishes them, in order.`
          : "As the board publishes them, in order — this is what the agent will work through."}
      </p>
      <ul className="space-y-2">
        {questions.map((question) => (
          <li
            key={question.label}
            className="flex flex-wrap items-baseline gap-x-2 gap-y-1 text-sm"
          >
            <PlainText
              as="span"
              className={
                blocked.has(question.label)
                  ? "font-medium text-foreground"
                  : "text-foreground"
              }
            >
              {question.label}
            </PlainText>
            {question.required ? (
              <span className="rounded-full border border-border px-1.5 py-0.5 text-[10px] font-medium text-muted-foreground">
                required
              </span>
            ) : null}
            <AnswerSourceChip
              question={question}
              blocked={blocked.has(question.label)}
            />
          </li>
        ))}
      </ul>
    </div>
  )
}

/**
 * The one chip that says where an answer comes from.
 *
 * The verdicts are the backend's (`answerable | needs_human | autofillable |
 * skipped`). `needs_human` — or a name in `blocking_questions` — is the
 * terracotta "needs a human" mark. An `answerable` question names the
 * profile fact it is answered from, which is the "confirmed profile fact"
 * source; the candidate-provided answers are counted in the checklist, not
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
      <span className="rounded-full bg-terracotta-soft px-2 py-0.5 text-[11px] font-medium text-terracotta-foreground">
        needs a human
      </span>
    )
  }
  if (question.verdict === "answerable") {
    return (
      <span className="rounded-full border border-forest/25 px-1.5 py-0.5 text-[10px] font-medium text-forest">
        {question.answer_from
          ? `from your profile: ${question.answer_from}`
          : "the agent can answer"}
      </span>
    )
  }
  return (
    <span className="rounded-full border border-border px-1.5 py-0.5 text-[10px] font-medium text-muted-foreground">
      {question.verdict}
    </span>
  )
}
