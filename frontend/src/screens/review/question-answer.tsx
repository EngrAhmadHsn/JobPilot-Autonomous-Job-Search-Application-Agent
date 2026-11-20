import { useState } from "react"

import { ErrorNotice } from "@/components/common/error-notice"
import { PlainText } from "@/components/common/plain-text"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import {
  questionKeyOf,
  type AnswerInput,
  type QuestionWithKey,
  type SavedAnswerRecord,
} from "@/lib/api/answers"

import { CLAY_CHIP, FOREST_CHIP, OUTLINE_CHIP, SAGE_CHIP } from "./chips"

/*
  The answering card of the Review screen (WS-45, design node `49:1096` —
  "One answer needs you." with `QUESTION 6 OF 6` and "Save answer →").

  The design's rule is one question at a time: each unanswered question
  surfaces here in the board's own order, the human answers it, saves, and
  the next one appears. Saving is real now: the answer is stored on the
  tracked application and the screen re-prepares, so the backend's plan
  re-merges the answer and `blocking_questions` shrinks. This card owns the
  walk and the drafts; the screen owns the save and the re-prepare.

  The control is derived from the taxonomy category, because the prepare
  payload carries no per-question answer type or option list: the boolean
  categories (work authorization, sponsorship, citizenship) get the design's
  Yes/No radio pair, the numeric ones a numeric input, the availability date
  a date input, and everything else — including the categories a form draws
  as a dropdown (employment type, work mode) — a plain text input, since the
  console cannot offer options the employer never published. A dropdown
  would have to invent them.

  Question labels are board-supplied text, so they render through
  `PlainText` like every other untrusted string.
*/

/** Categories whose answer is a strict Yes/No. */
const BOOLEAN_CATEGORIES = new Set([
  "work_authorization",
  "visa_sponsorship",
  "citizenship_status",
])

/** Categories whose answer is a number (coordinates, years, salary). */
const NUMBER_CATEGORIES = new Set([
  "location_latitude",
  "location_longitude",
  "total_experience",
  "skill_experience",
  "desired_salary",
  "current_salary",
])

/** Categories whose answer is a date. */
const DATE_CATEGORIES = new Set(["availability_date"])

/**
 * The categories the console never stores an answer for (WS-45's
 * `NEVER_AUTOFILL`): EEO and legal attestations are answered by the human
 * on the employer's own site, at submission time — policy, not a
 * limitation. The verdict names them too; the category is checked as well
 * so an older payload's vocabulary cannot route one into a save.
 */
const NEVER_AUTOFILL_CATEGORIES = new Set([
  "eeo_race",
  "eeo_gender",
  "eeo_disability",
  "eeo_veteran",
  "attestation",
])

const isNeverAutofill = (question: QuestionWithKey) =>
  question.verdict === "never_autofill" ||
  NEVER_AUTOFILL_CATEGORIES.has(question.category ?? "")

/** The server-side answer bound for a saved question key, when there is one. */
const answerFor = (
  answers: SavedAnswerRecord[],
  question: QuestionWithKey
): SavedAnswerRecord | null => {
  const key = questionKeyOf(question).toLowerCase()
  const label = question.label.toLowerCase()
  return (
    answers.find(
      (record) =>
        record.question_key.toLowerCase() === key ||
        (Boolean(record.label) && record.label.toLowerCase() === label)
    ) ?? null
  )
}

export function QuestionAnswer({
  questions,
  blockers,
  savedAnswers,
  companyName,
  saving,
  error,
  onSave,
}: {
  /** The board's whole form, in the order the board publishes it. */
  questions: QuestionWithKey[]
  /** `blocking_questions`, from the prepare response. */
  blockers: string[]
  /** The answers already saved for this application (inherited ones included). */
  savedAnswers: SavedAnswerRecord[]
  /** The employer's name, for the "Required by …" line. */
  companyName: string
  /** True while the save is in flight. */
  saving: boolean
  /** The save's failure, if any — surfaced beside the controls. */
  error: unknown
  /** Save one answer; resolves after the server accepted it. */
  onSave: (input: AnswerInput) => Promise<void>
}) {
  const isBlocked = (question: QuestionWithKey) =>
    blockers.includes(question.label) || question.verdict === "needs_human"

  /*
    The walk. The position is the question's place in the board's own order
    (the design's "QUESTION 6 OF 6" / "6 / 6"), and it opens on the first
    question that needs a human. Previous pages back through the questions
    that came before — including confirmed ones, which can be re-answered
    (a save is an upsert).
  */
  const [index, setIndex] = useState(() => {
    const first = questions.findIndex(isBlocked)
    return first >= 0 ? first : 0
  })
  const [drafts, setDrafts] = useState<Record<string, string>>({})

  /*
    When the plan re-merges after a save, the answered question leaves the
    blocked set — the walk advances to the next question that still needs a
    human, after this one, then from the top. Manual navigation between
    re-prepares is never overridden: the adjustment reads the position only
    when the questions themselves change (React's adjust-state-on-prop-change
    pattern, which runs during render instead of in an effect, so a stale
    position never paints).
  */
  const [renderedQuestions, setRenderedQuestions] = useState(questions)
  if (renderedQuestions !== questions) {
    setRenderedQuestions(questions)
    setIndex((current) => {
      const clamped = Math.min(
        Math.max(current, 0),
        Math.max(questions.length - 1, 0)
      )
      const here = questions[clamped]
      if (here && isBlocked(here)) return clamped
      const after = questions.findIndex(
        (question, at) => at > clamped && isBlocked(question)
      )
      if (after >= 0) return after
      const any = questions.findIndex(isBlocked)
      return any >= 0 ? any : clamped
    })
  }

  const needsYou = questions.filter(isBlocked).length
  const confirmed = questions.length - needsYou

  const current: QuestionWithKey | undefined = questions[index]
  const key = current ? questionKeyOf(current) : ""
  const saved = current ? answerFor(savedAnswers, current) : null
  const draft = drafts[key] ?? saved?.answer ?? ""
  const neverAutofill = current ? isNeverAutofill(current) : false
  const booleanSelection = /^yes$/i.test(draft)
    ? "Yes"
    : /^no$/i.test(draft)
      ? "No"
      : null
  const hasAnswer = current
    ? neverAutofill
      ? false
      : BOOLEAN_CATEGORIES.has(current.category ?? "")
        ? booleanSelection !== null
        : draft.trim().length > 0
    : false

  if (!current || questions.length === 0) return null

  const setDraft = (value: string) =>
    setDrafts((prev) => ({ ...prev, [key]: value }))

  const save = async () => {
    if (!current || neverAutofill || !hasAnswer) return
    try {
      await onSave({
        question_key: key,
        label: current.label,
        category: current.category ?? null,
        answer: BOOLEAN_CATEGORIES.has(current.category ?? "")
          ? (booleanSelection as string)
          : draft.trim(),
      })
      // Saved: the server holds it now (and the screen re-prepares, which
      // advances the walk). The local draft yields to the stored answer.
      setDrafts((prev) => {
        const next = { ...prev }
        delete next[key]
        return next
      })
    } catch {
      // The parent holds the refusal; it renders beside the controls and
      // the draft is untouched, so "Save answer" retries it.
    }
  }

  return (
    <section
      data-testid="question-answer"
      className="flex min-w-0 flex-col gap-3.5 rounded-surface border border-border-surface bg-card p-5"
    >
      <h2 className="text-[20px] leading-[29px] font-semibold text-primary">
        {needsYou === 1
          ? "One answer needs you."
          : `${needsYou} answers need you.`}
      </h2>

      <div className="flex flex-wrap items-center gap-2.5">
        <span className={needsYou > 0 ? FOREST_CHIP : OUTLINE_CHIP}>
          Needs you {needsYou}
        </span>
        <span className={OUTLINE_CHIP}>Confirmed {confirmed}</span>
      </div>

      <div className="flex flex-wrap items-center gap-2">
        <span className={SAGE_CHIP}>
          QUESTION {index + 1} OF {questions.length}
        </span>
        {current.required ? <span className={CLAY_CHIP}>Required</span> : null}
      </div>

      <PlainText className="text-[17px] leading-snug font-semibold text-foreground">
        {current.label}
      </PlainText>
      <p className="text-xs leading-relaxed text-muted-foreground">
        {current.required
          ? `Required by ${companyName} · not inferred from your résumé.`
          : `Asked by ${companyName} · not inferred from your résumé.`}
      </p>

      {neverAutofill ? (
        <p className="text-sm leading-relaxed text-terracotta-foreground">
          Answer on the employer site — this console never autofills it.
        </p>
      ) : BOOLEAN_CATEGORIES.has(current.category ?? "") ? (
        <div
          role="radiogroup"
          aria-label={current.label}
          className="flex flex-wrap items-center gap-2.5"
        >
          {(["Yes", "No"] as const).map((option) => {
            const selected = booleanSelection === option
            return (
              <label
                key={option}
                className={`inline-flex h-9 cursor-pointer items-center gap-2 rounded-lg border px-3.5 text-[13px] font-semibold transition-colors outline-none has-[:focus-visible]:outline-2 has-[:focus-visible]:outline-offset-2 has-[:focus-visible]:outline-ring ${
                  selected
                    ? "border-primary bg-forest-soft text-primary"
                    : "border-border-surface bg-card text-foreground hover:bg-muted"
                }`}
              >
                <input
                  type="radio"
                  name={`answer-${key}`}
                  value={option}
                  checked={selected}
                  onChange={() => setDraft(option)}
                  className="sr-only"
                />
                <span
                  aria-hidden
                  className="flex size-[15px] shrink-0 items-center justify-center rounded-full border border-muted-foreground/60"
                >
                  {selected ? (
                    <span className="size-[7px] rounded-full bg-primary" />
                  ) : null}
                </span>
                {option}
              </label>
            )
          })}
        </div>
      ) : (
        <Input
          aria-label={current.label}
          type={
            DATE_CATEGORIES.has(current.category ?? "")
              ? "date"
              : NUMBER_CATEGORIES.has(current.category ?? "")
                ? "number"
                : "text"
          }
          inputMode={
            NUMBER_CATEGORIES.has(current.category ?? "")
              ? "decimal"
              : undefined
          }
          maxLength={500}
          value={draft}
          onChange={(event) => setDraft(event.target.value)}
        />
      )}

      <p className="text-xs leading-relaxed text-muted-foreground">
        Choose the answer that is true for you.
      </p>

      {error ? <ErrorNotice error={error} /> : null}

      <div className="flex flex-wrap items-center gap-3 border-t border-border-surface pt-4">
        <Button
          type="button"
          variant="outline"
          disabled={index === 0}
          onClick={() => setIndex((value) => Math.max(value - 1, 0))}
        >
          ← Previous
        </Button>
        <span className="text-[13px] leading-[19px] text-muted-foreground">
          {index + 1} / {questions.length}
        </span>
        {neverAutofill ? null : (
          <Button
            type="button"
            className="ml-auto"
            disabled={saving || !hasAnswer}
            onClick={() => void save()}
          >
            {saving ? "Saving…" : "Save answer →"}
          </Button>
        )}
      </div>

      <p className="text-xs leading-relaxed text-muted-foreground">
        Each unanswered question appears here, one at a time. Review all before
        approval.
      </p>
    </section>
  )
}
