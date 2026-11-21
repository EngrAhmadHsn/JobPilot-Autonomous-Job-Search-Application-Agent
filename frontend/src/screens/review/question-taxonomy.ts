/**
 * The question taxonomy the console renders controls from (WS-45).
 *
 * The prepare payload carries each question's **category** (from
 * `src/applications/questions.py`) but no per-question answer type or option
 * list, and the console must not invent options the employer never
 * published. So the control is derived from the category: the boolean
 * categories get a Yes/No radio pair, the numeric ones a numeric input, the
 * availability date a date input, and everything else — including the
 * categories a form draws as a dropdown — a plain text input.
 *
 * This module is the single home of that mapping, shared by the Review
 * card (one question at a time) and the per-application questions page
 * (all of them). Two copies would drift, and a drifted copy is how an EEO
 * question becomes saveable.
 */
import {
  questionKeyOf,
  type QuestionWithKey,
  type SavedAnswerRecord,
} from "@/lib/api/answers"

/** Categories whose answer is a strict Yes/No. */
export const BOOLEAN_CATEGORIES = new Set([
  "work_authorization",
  "visa_sponsorship",
  "citizenship_status",
])

/** Categories whose answer is a number (coordinates, years, salary). */
export const NUMBER_CATEGORIES = new Set([
  "location_latitude",
  "location_longitude",
  "total_experience",
  "skill_experience",
  "desired_salary",
  "current_salary",
])

/** Categories whose answer is a date. */
export const DATE_CATEGORIES = new Set(["availability_date"])

/**
 * The categories the console never stores an answer for (WS-45's
 * `NEVER_AUTOFILL`): EEO and legal attestations are answered by the human
 * on the employer's own site, at submission time — policy, not a
 * limitation. The verdict names them too; the category is checked as well
 * so an older payload's vocabulary cannot route one into a save.
 */
export const NEVER_AUTOFILL_CATEGORIES = new Set([
  "eeo_race",
  "eeo_gender",
  "eeo_disability",
  "eeo_veteran",
  "attestation",
])

/** Whether the console refuses to store an answer for this question. */
export const isNeverAutofill = (question: QuestionWithKey) =>
  question.verdict === "never_autofill" ||
  NEVER_AUTOFILL_CATEGORIES.has(question.category ?? "")

/** The saved answer bound to a question, when the human has given one. */
export const answerFor = (
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

/** The `type` an `<input>` should carry for a question's answer. */
export const answerInputType = (category: string | null | undefined) =>
  DATE_CATEGORIES.has(category ?? "")
    ? "date"
    : NUMBER_CATEGORIES.has(category ?? "")
      ? "number"
      : "text"

/** The `inputMode` an `<input>` should carry for a question's answer. */
export const answerInputMode = (category: string | null | undefined) =>
  NUMBER_CATEGORIES.has(category ?? "") ? "decimal" : undefined
