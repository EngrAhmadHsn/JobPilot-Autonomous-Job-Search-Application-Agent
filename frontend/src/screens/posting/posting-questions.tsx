import { useMutation, useQueryClient } from "@tanstack/react-query"
import { useEffect, useRef, useState } from "react"
import { Link, useLocation } from "react-router-dom"

import { ErrorNotice } from "@/components/common/error-notice"
import {
  EmployerQuestionField,
  hasAnswer,
} from "@/components/profile/employer-question-field"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader } from "@/components/ui/card"
import {
  editableQuestion,
  employerLibraryKey,
  postingFormKey,
  savePostingAnswers,
  usePostingForm,
  type AnswerValue,
  type PostingQuestion,
} from "@/lib/api/posting-application"
import type { Identity } from "@/lib/api/types"

import { employerQuestionsAnchor } from "./questions-preview"

function equalAnswer(left: AnswerValue, right: AnswerValue | null) {
  if (!Array.isArray(left)) return left === (right ?? "")
  if (!Array.isArray(right)) return !left.length && right === null
  return (
    left.length === right.length && left.every((value) => right.includes(value))
  )
}

export function usePostingQuestionEditor(jobId: string, accountId: string) {
  const queryClient = useQueryClient()
  const form = usePostingForm(jobId)
  const [draft, setDraft] = useState<Record<string, AnswerValue>>({})
  const questions = form.data?.state === "available" ? form.data.questions : []
  const editable = questions.filter(editableQuestion)
  const changes = editable.flatMap((question) => {
    const value = draft[question.question_key]
    const answer = typeof value === "string" ? value.trim() : value
    return answer === undefined || equalAnswer(answer, question.answer)
      ? []
      : [{ question_key: question.question_key, answer }]
  })
  const hasEmptyEdits = changes.some(({ answer }) => !hasAnswer(answer))
  const accountFormKey = postingFormKey(jobId, accountId)
  const save = useMutation({
    mutationFn: () => savePostingAnswers(jobId, changes),
    onSuccess: async (savedForm) => {
      await queryClient.cancelQueries({ queryKey: accountFormKey, exact: true })
      if (queryClient.getQueryData<Identity>(["identity"])?.id !== accountId)
        return
      queryClient.setQueryData(accountFormKey, savedForm)
      setDraft({})
      void queryClient.invalidateQueries({ queryKey: employerLibraryKey })
      void queryClient.invalidateQueries({ queryKey: ["posting-review"] })
    },
  })

  return {
    form,
    questions,
    editable,
    draft,
    hasChanges: changes.length > 0,
    hasEmptyEdits,
    tooManyEdits: changes.length > 100,
    save,
    change: (question: PostingQuestion, value: AnswerValue) => {
      save.reset()
      setDraft((current) => ({ ...current, [question.question_key]: value }))
    },
    discard: () => {
      save.reset()
      setDraft({})
    },
  }
}

export function PostingQuestions({
  editor,
  busy,
}: {
  editor: ReturnType<typeof usePostingQuestionEditor>
  busy: boolean
}) {
  const {
    form,
    questions,
    editable,
    draft,
    hasChanges,
    hasEmptyEdits,
    tooManyEdits,
    save,
  } = editor
  const { hash, key } = useLocation()
  const heading = useRef<HTMLHeadingElement>(null)
  useEffect(() => {
    if (hash !== employerQuestionsAnchor) return
    heading.current?.focus({ preventScroll: true })
    heading.current?.scrollIntoView({ block: "start" })
  }, [hash, key])

  const employerOnly = questions.filter(
    (question) => question.kind === "employer"
  )
  const mapped = questions.filter(
    (question) => question.kind === "contact" || question.kind === "resume"
  )
  const missing = editable.filter(
    (question) => question.required && !hasAnswer(question.answer)
  ).length
  const canSave =
    !busy && !form.isFetching && hasChanges && !hasEmptyEdits && !tooManyEdits

  return (
    <section aria-labelledby="employer-questions">
      <Card className="min-w-0">
        <CardHeader>
          <h2
            ref={heading}
            id="employer-questions"
            tabIndex={-1}
            className="type-section"
          >
            Employer questions
          </h2>
        </CardHeader>
        <CardContent className="space-y-5">
          {form.isPending ? (
            <p role="status" className="text-muted-foreground">
              Reading the employer’s questions…
            </p>
          ) : form.isError || form.data?.state === "unavailable" ? (
            <div className="space-y-2">
              <p role="status" className="text-muted-foreground">
                We could not read the employer’s questions. You can still
                prepare a local review and check the current requirements on the
                employer site.
              </p>
              <Button
                type="button"
                variant="outline"
                onClick={() => void form.refetch()}
                disabled={form.isFetching || busy}
              >
                {form.isFetching
                  ? "Checking employer questions…"
                  : "Retry employer questions"}
              </Button>
            </div>
          ) : form.data?.state === "unsupported" ? (
            <p className="text-muted-foreground">
              This source doesn’t provide questions we can show here. Check what
              the employer asks on its site.
            </p>
          ) : (
            <>
              {editable.length === 0 ? (
                <p className="text-muted-foreground">
                  No employer questions can be saved here for this posting.
                </p>
              ) : (
                <form
                  aria-labelledby="employer-questions"
                  className="space-y-4"
                  onSubmit={(event) => {
                    event.preventDefault()
                    if (canSave) save.mutate()
                  }}
                >
                  <p className="text-muted-foreground">
                    Use the employer’s wording and directions below. Saving
                    stores your answers in Profile, not with the employer.
                  </p>
                  {missing > 0 ? (
                    <p className="font-medium text-foreground">
                      {missing} required {missing === 1 ? "answer" : "answers"}{" "}
                      not saved
                    </p>
                  ) : null}
                  <fieldset
                    disabled={busy || save.isPending}
                    className="min-w-0 space-y-5"
                  >
                    {editable.map((question) => (
                      <EmployerQuestionField
                        key={question.question_key}
                        question={question}
                        value={
                          draft[question.question_key] ??
                          question.answer ??
                          (question.kind === "multiselect" ? [] : "")
                        }
                        onChange={(value) => editor.change(question, value)}
                      />
                    ))}
                  </fieldset>
                  {hasEmptyEdits ? (
                    <p className="text-muted-foreground">
                      To remove a saved answer, discard this edit and remove it
                      in{" "}
                      <Link
                        to="/app/profile?tab=answers"
                        className="text-primary underline underline-offset-4"
                      >
                        Profile
                      </Link>
                      .
                    </p>
                  ) : null}
                  {tooManyEdits ? (
                    <p>Edit no more than 100 answers before saving.</p>
                  ) : null}
                  <ErrorNotice error={save.error} />
                  <div className="flex flex-wrap items-center gap-2">
                    <Button
                      type="submit"
                      variant="outline"
                      disabled={!canSave || save.isPending}
                    >
                      {save.isPending ? "Saving answers…" : "Save answers"}
                    </Button>
                    {hasChanges ? (
                      <Button
                        type="button"
                        variant="ghost"
                        onClick={editor.discard}
                        disabled={busy || save.isPending}
                      >
                        Discard answer edits
                      </Button>
                    ) : null}
                    {save.isSuccess ? (
                      <p role="status" className="text-primary">
                        Answers saved to your Profile.
                      </p>
                    ) : null}
                  </div>
                </form>
              )}
              {mapped.length > 0 ? (
                <QuestionDirections
                  questions={mapped}
                  title="Use your contact details and résumé"
                />
              ) : null}
              {employerOnly.length > 0 ? (
                <QuestionDirections
                  questions={employerOnly}
                  title="Answer on the employer site"
                  description="These questions aren’t collected or saved here."
                />
              ) : null}
            </>
          )}
        </CardContent>
      </Card>
    </section>
  )
}

function QuestionDirections({
  questions,
  title,
  description,
}: {
  questions: PostingQuestion[]
  title: string
  description?: string
}) {
  return (
    <div className="space-y-2 rounded-lg border border-border-surface bg-muted/40 p-3">
      <h3 className="font-semibold">{title}</h3>
      {description ? (
        <p className="text-muted-foreground">{description}</p>
      ) : null}
      <ul className="space-y-2">
        {questions.map((question) => (
          <li key={question.question_key} className="wrap-anywhere">
            <span>{question.label}</span>
            {question.required ? (
              <span className="text-xs text-muted-foreground">
                {" "}
                · Required by employer
              </span>
            ) : null}
            {question.description ? (
              <p className="whitespace-pre-line text-muted-foreground">
                {question.description}
              </p>
            ) : null}
          </li>
        ))}
      </ul>
    </div>
  )
}
