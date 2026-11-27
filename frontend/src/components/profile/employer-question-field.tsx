import { useId } from "react"

import { Input } from "@/components/ui/input"
import type {
  AnswerValue,
  PostingQuestion,
} from "@/lib/api/posting-application"

const control =
  "w-full min-w-0 rounded-md border border-input bg-background px-3 py-2 text-sm outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:opacity-60"

export function hasAnswer(value: AnswerValue | null | undefined) {
  return Array.isArray(value) ? value.length > 0 : Boolean(value?.trim())
}

export function displayAnswer(q: PostingQuestion) {
  if (!q.answer) return ""
  const label = (value: string) =>
    q.options?.find((choice) => choice.value === value)?.label ?? value
  return Array.isArray(q.answer)
    ? q.answer.map(label).join(", ")
    : label(q.answer)
}

export function EmployerQuestionField({
  question,
  value,
  onChange,
}: {
  question: PostingQuestion
  value: AnswerValue
  onChange: (value: AnswerValue) => void
}) {
  const id = useId()
  const hintId = `${id}-hint`
  const description = question.description ?? undefined
  const describedBy = description ? hintId : undefined
  const text = typeof value === "string" ? value : ""
  const values = Array.isArray(value) ? value : []
  const label = (
    <span className="flex flex-wrap items-baseline gap-x-2">
      <span className="font-medium wrap-anywhere">{question.label}</span>{" "}
      <span className="text-xs font-normal text-muted-foreground">
        {question.required ? "Required by employer" : "Optional"}
      </span>
    </span>
  )
  const hint = description ? (
    <p
      id={hintId}
      className="text-sm wrap-anywhere whitespace-pre-line text-muted-foreground"
    >
      {description}
    </p>
  ) : null

  if (question.kind === "multiselect") {
    return (
      <fieldset className="min-w-0 space-y-2" aria-describedby={describedBy}>
        <legend>{label}</legend>
        {hint}
        {question.options?.map((option) => (
          <label
            key={option.value}
            className="flex w-fit items-start gap-2 py-1 text-sm wrap-anywhere"
          >
            <input
              type="checkbox"
              className="mt-0.5 size-4 shrink-0 accent-primary"
              checked={values.includes(option.value)}
              onChange={(event) =>
                onChange(
                  event.target.checked
                    ? [...values, option.value]
                    : values.filter((item) => item !== option.value)
                )
              }
            />
            {option.label}
          </label>
        ))}
      </fieldset>
    )
  }

  return (
    <div className="min-w-0 space-y-2">
      <label htmlFor={id}>{label}</label>
      {hint}
      {question.kind === "select" ? (
        <select
          id={id}
          aria-label={question.label}
          aria-describedby={describedBy}
          className={control}
          value={text}
          onChange={(event) => onChange(event.target.value)}
        >
          <option value="">Choose an answer</option>
          {question.options?.map((option) => (
            <option key={option.value} value={option.value}>
              {option.label}
            </option>
          ))}
        </select>
      ) : question.kind === "textarea" ? (
        <textarea
          id={id}
          aria-label={question.label}
          aria-describedby={describedBy}
          rows={4}
          className={`${control} min-h-24 resize-y`}
          maxLength={4000}
          value={text}
          onChange={(event) => onChange(event.target.value)}
        />
      ) : (
        <Input
          id={id}
          aria-label={question.label}
          aria-describedby={describedBy}
          autoComplete="off"
          maxLength={4000}
          value={text}
          onChange={(event) => onChange(event.target.value)}
        />
      )}
    </div>
  )
}
