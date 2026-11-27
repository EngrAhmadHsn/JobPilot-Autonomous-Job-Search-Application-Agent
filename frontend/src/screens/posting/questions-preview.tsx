import { useId } from "react"
import { Link } from "react-router-dom"

import { hasAnswer } from "@/components/profile/employer-question-field"
import {
  editableQuestion,
  preparePath,
  usePostingForm,
} from "@/lib/api/posting-application"

export const employerQuestionsAnchor = "#employer-questions"

const PREVIEW_LIMIT = 3

/** Mounted only on a full listing or the currently selected Discover detail. */
export function PostingQuestionsPreview({
  jobId,
  heading: Heading = "h2",
}: {
  jobId: string
  heading?: "h2" | "h3"
}) {
  const headingId = useId()
  const form = usePostingForm(jobId)
  const data = !form.isError ? form.data : undefined
  const questions =
    data?.state === "available"
      ? data.questions.filter(
          (question) =>
            question.kind !== "contact" && question.kind !== "resume"
        )
      : []
  const missing = questions.filter(
    (question) =>
      question.required &&
      editableQuestion(question) &&
      !hasAnswer(question.answer)
  )
  const missingKeys = new Set(missing.map((question) => question.question_key))
  const preview = [
    ...missing,
    ...questions.filter((question) => !missingKeys.has(question.question_key)),
  ].slice(0, PREVIEW_LIMIT)
  const message = form.isPending
    ? "Reading the employer’s published questions…"
    : form.isError || form.data?.state === "unavailable"
      ? "We couldn’t read the employer’s questions. You can retry in preparation."
      : data?.state !== "available"
        ? "This source doesn’t provide questions we can show here."
        : questions.length === 0
          ? "No additional questions were listed beyond contact and résumé fields."
          : `${questions.length} ${questions.length === 1 ? "question" : "questions"} · ${missing.length} required ${missing.length === 1 ? "answer" : "answers"} not saved`

  return (
    <section
      aria-labelledby={headingId}
      className="min-w-0 space-y-2 rounded-xl border border-border-surface bg-muted/40 px-4 py-3"
    >
      <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
        <Heading
          id={headingId}
          className="text-sm font-semibold text-foreground"
        >
          Employer questions
        </Heading>
        <Link
          to={`${preparePath(jobId)}${employerQuestionsAnchor}`}
          className="rounded-sm text-sm font-medium text-primary underline underline-offset-4"
        >
          Open employer questions
        </Link>
      </div>
      <p
        className="text-sm text-muted-foreground"
        role={form.isPending ? "status" : undefined}
      >
        {message}
      </p>
      {preview.length > 0 ? (
        <ul className="space-y-1 text-sm">
          {preview.map((question) => (
            <li
              key={question.question_key}
              className="flex items-baseline gap-2 wrap-anywhere"
            >
              <span aria-hidden="true" className="text-muted-foreground">
                ·
              </span>
              <span>
                {question.label}
                {question.kind === "employer" ? (
                  <span className="text-xs text-muted-foreground">
                    {" "}
                    · On employer site
                  </span>
                ) : missingKeys.has(question.question_key) ? (
                  <span className="text-xs text-muted-foreground">
                    {" "}
                    · Required
                  </span>
                ) : null}
              </span>
            </li>
          ))}
        </ul>
      ) : null}
    </section>
  )
}
