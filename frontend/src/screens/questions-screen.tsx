import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { ArrowLeft, Check, HelpCircle, Lock, ShieldCheck } from "lucide-react"
import { useState } from "react"
import { useParams } from "react-router-dom"

import { CardSkeleton } from "@/components/common/card-skeleton"
import { ErrorNotice } from "@/components/common/error-notice"
import { PageHeader } from "@/components/common/page-header"
import { PlainText } from "@/components/common/plain-text"
import { Button } from "@/components/ui/button"
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import { EmptyState } from "@/components/ui/empty-state"
import { Input } from "@/components/ui/input"
import { LinkButton } from "@/components/ui/link-button"
import { StatusBadge } from "@/components/ui/status-badge"
import {
  getApplicationQuestions,
  putApplicationAnswers,
  questionKeyOf,
  type AnswerInput,
  type QuestionWithKey,
  type SavedAnswerRecord,
} from "@/lib/api/answers"
import { describeStatus } from "@/lib/status"

import { CLAY_CHIP, FOREST_CHIP, OUTLINE_CHIP, SAGE_CHIP } from "./review/chips"
import {
  BOOLEAN_CATEGORIES,
  answerFor,
  answerInputMode,
  answerInputType,
  isNeverAutofill,
} from "./review/question-taxonomy"

/*
  The per-application questions page (WS-45), at
  `/app/tracker/:applicationId/questions`.

  The Review screen answers one question at a time and then asks the human
  to authorize. This page is the other half of that flow: **every** question
  the prepared packet carries for one application, in the board's own order,
  each one answerable in place — reached from Review's "View all questions →"
  and from the application's own detail screen.

  What it reads is the stored plan, not a live form: the backend keeps the
  question list with the approval it belongs to (`form_questions`), and folds
  the human's saved answers back into the verdicts on the read. So a question
  answered here reads "Confirmed · your answer" on the next render without a
  re-prepare, and the same answers unblock the packet's next prepare — the
  merge in `build_question_plan` reads them by posting, so Review's authorize
  step sees them.

  Two honest states are rendered rather than papered over:

  - **No plan** (`plan_available === false`): the application never went
    through prepare, so its questions are *unknown*. An empty list is not the
    same claim as "the employer asked nothing".
  - **Never autofilled** (EEO / attestation): those questions are listed with
    their verdict and no control at all, because the console refuses to store
    such an answer (the API answers 422) — policy, not a limitation.

  Question labels are board-supplied text, so they render through
  `PlainText` like every other untrusted string.
*/

/** How one question reads on this page: its chip and its explanation. */
function verdictOf(
  question: QuestionWithKey,
  saved: SavedAnswerRecord | null,
  blocked: boolean
) {
  if (saved) {
    return {
      label: "Confirmed",
      chip: SAGE_CHIP,
      // The human's own answer — the source line says whose it is.
      source: "From your answer.",
    }
  }
  if (isNeverAutofill(question)) {
    return {
      label: "On the employer's site",
      chip: CLAY_CHIP,
      source:
        "Answered by you on the employer's own form — this console never fills or stores it.",
    }
  }
  if (blocked || question.verdict === "needs_human") {
    return {
      label: "Needs answer",
      chip: CLAY_CHIP,
      source: "Not inferred from your résumé. The console never guesses.",
    }
  }
  if (question.verdict === "optional_unanswered") {
    return {
      label: "Optional",
      chip: OUTLINE_CHIP,
      source: "The employer does not require it. Answering is your choice.",
    }
  }
  return {
    label: "Confirmed",
    chip: SAGE_CHIP,
    // A profile-derived answer names its own source honestly.
    source: question.answer_from
      ? `From your application profile (${question.answer_from}).`
      : "From your application profile.",
  }
}

/**
 * One question, with its answer control.
 *
 * The draft is local to the row: typing never marks the screen dirty, and a
 * save hands the value to the page, which invalidates the read so the chip
 * moves from "Needs answer" to "Confirmed" off the server's own merge.
 */
function QuestionRow({
  question,
  index,
  total,
  saved,
  blocked,
  saving,
  onSave,
}: {
  question: QuestionWithKey
  index: number
  total: number
  saved: SavedAnswerRecord | null
  blocked: boolean
  saving: boolean
  onSave: (input: AnswerInput) => Promise<void>
}) {
  const key = questionKeyOf(question)
  const [draft, setDraft] = useState(saved?.answer ?? "")
  const state = verdictOf(question, saved, blocked)
  const neverAutofill = isNeverAutofill(question)
  const isBoolean = BOOLEAN_CATEGORIES.has(question.category ?? "")
  const booleanSelection = /^yes$/i.test(draft)
    ? "Yes"
    : /^no$/i.test(draft)
      ? "No"
      : null
  const hasAnswer = isBoolean
    ? booleanSelection !== null
    : draft.trim().length > 0
  // A saved answer that has not been touched needs no second save.
  const dirty = draft !== (saved?.answer ?? "")

  return (
    <li
      data-testid="question-row"
      className="flex flex-col gap-3 border-t border-border-surface py-5 first:border-t-0 first:pt-0"
    >
      <div className="flex flex-wrap items-center gap-2">
        <span className={SAGE_CHIP}>
          QUESTION {index + 1} OF {total}
        </span>
        {question.required ? <span className={CLAY_CHIP}>Required</span> : null}
        <span className={`${state.chip} ml-auto`}>{state.label}</span>
      </div>

      <PlainText className="text-[15px] leading-snug font-semibold text-foreground">
        {question.label}
      </PlainText>

      <p className="text-xs leading-relaxed text-muted-foreground">
        {state.source}
      </p>

      {saved && !dirty ? (
        <p className="text-sm leading-relaxed text-foreground">
          <span className="font-medium">Your answer:</span>{" "}
          <PlainText as="span">{saved.answer}</PlainText>
        </p>
      ) : null}

      {neverAutofill ? null : (
        <div className="flex flex-col gap-3 sm:flex-row sm:items-center">
          {isBoolean ? (
            <div
              role="radiogroup"
              aria-label={question.label}
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
              aria-label={question.label}
              className="sm:max-w-md"
              type={answerInputType(question.category)}
              inputMode={answerInputMode(question.category)}
              maxLength={500}
              value={draft}
              onChange={(event) => setDraft(event.target.value)}
            />
          )}
          <Button
            type="button"
            variant={dirty ? "default" : "outline"}
            disabled={saving || !hasAnswer || !dirty}
            onClick={() =>
              void onSave({
                question_key: key,
                label: question.label,
                category: question.category ?? null,
                answer: isBoolean ? (booleanSelection as string) : draft.trim(),
              })
            }
          >
            {saving ? "Saving..." : saved ? "Update answer" : "Save answer"}
          </Button>
        </div>
      )}
    </li>
  )
}

export function QuestionsScreen() {
  const { applicationId = "" } = useParams()
  const queryClient = useQueryClient()

  const questions = useQuery({
    queryKey: ["application-questions", applicationId],
    queryFn: ({ signal }) => getApplicationQuestions(applicationId, signal),
    enabled: Boolean(applicationId),
  })

  const save = useMutation({
    mutationFn: (input: AnswerInput) =>
      putApplicationAnswers(applicationId, [input]),
    // The server folds the saved answer into the stored plan on the read, so
    // re-reading the questions is what moves the chip — there is nothing to
    // patch locally, and a local patch could disagree with the server.
    onSuccess: () =>
      queryClient.invalidateQueries({
        queryKey: ["application-questions", applicationId],
      }),
  })

  const data = questions.data
  const blockers = new Set(data?.blocking_questions ?? [])
  const rows = data?.questions ?? []
  const needsYou = rows.filter(
    (question) =>
      !answerFor(data?.answers ?? [], question) &&
      !isNeverAutofill(question) &&
      (blockers.has(question.label) || question.verdict === "needs_human")
  ).length
  const confirmed = rows.length - needsYou
  const status = data?.status ?? ""

  return (
    <div className="space-y-6">
      <PageHeader
        title="Every question, in one place."
        documentTitle="Application questions"
        description={
          data
            ? `${data.company_name} · ${data.job_title}`
            : "The employer's questions for one application."
        }
        meta={
          data ? (
            <>
              <StatusBadge status={status} />
              <span>{describeStatus(status).label}</span>
            </>
          ) : null
        }
        actions={
          <LinkButton variant="outline" to={`/app/tracker/${applicationId}`}>
            <ArrowLeft className="size-4" aria-hidden />
            Application details
          </LinkButton>
        }
      />

      {questions.isPending ? <CardSkeleton rows={5} /> : null}

      {questions.isError ? (
        <ErrorNotice
          error={questions.error}
          onRetry={() => void questions.refetch()}
        />
      ) : null}

      {data && !data.plan_available ? (
        <EmptyState
          icon={HelpCircle}
          title="No prepared questions for this application."
          message={
            <>
              The console keeps the employer's questions with the packet it
              prepared. This application has none — it was not prepared through
              the Review flow, so its questions are unknown rather than empty.
            </>
          }
          action={
            <LinkButton to="/app/approvals">
              Prepare an application →
            </LinkButton>
          }
        />
      ) : null}

      {data?.plan_available ? (
        <div className="grid gap-6 xl:grid-cols-[minmax(0,2fr)_minmax(0,1fr)] xl:items-start">
          <Card className="min-w-0">
            <CardHeader>
              <CardTitle className="text-xl leading-[29px]">
                The employer&apos;s form.
              </CardTitle>
              <CardDescription>
                Every question the prepared packet carries, in the board&apos;s
                own order. An answer you save here is yours — the console never
                guesses one.
              </CardDescription>
              <div className="mt-3 flex flex-wrap items-center gap-2.5">
                <span className={needsYou > 0 ? FOREST_CHIP : OUTLINE_CHIP}>
                  Needs you {needsYou}
                </span>
                <span className={OUTLINE_CHIP}>Confirmed {confirmed}</span>
              </div>
            </CardHeader>
            <CardContent>
              {save.isError ? (
                <div className="mb-4">
                  <ErrorNotice error={save.error} />
                </div>
              ) : null}
              <ul className="flex flex-col">
                {rows.map((question, index) => (
                  <QuestionRow
                    key={questionKeyOf(question)}
                    question={question}
                    index={index}
                    total={rows.length}
                    saved={answerFor(data.answers ?? [], question)}
                    blocked={blockers.has(question.label)}
                    saving={save.isPending}
                    onSave={(input) =>
                      save.mutateAsync(input).then(() => undefined)
                    }
                  />
                ))}
              </ul>
            </CardContent>
          </Card>

          <aside className="min-w-0 space-y-3 xl:sticky xl:top-[calc(var(--header-height,7rem)+1rem)]">
            {needsYou > 0 ? (
              <section className="flex flex-col gap-2.5 rounded-surface bg-terracotta-soft p-[18px]">
                <div className="flex items-center gap-2">
                  <Lock
                    className="size-4 shrink-0 text-terracotta-foreground"
                    aria-hidden
                  />
                  <h2 className="text-[15px] leading-snug font-semibold text-terracotta-foreground">
                    Not ready to authorize
                  </h2>
                </div>
                <p className="text-sm leading-relaxed text-terracotta-foreground">
                  {needsYou} answer{needsYou === 1 ? "" : "s"} still need
                  {needsYou === 1 ? "s" : ""} a human — the console never
                  guesses.
                </p>
                <p className="text-sm leading-relaxed font-semibold text-terracotta-foreground">
                  Confirm the required answer to unlock approval.
                </p>
              </section>
            ) : (
              <section className="flex flex-col gap-2.5 rounded-surface bg-forest-soft p-[18px]">
                <div className="flex items-center gap-2">
                  <Check className="size-4 shrink-0 text-primary" aria-hidden />
                  <h2 className="text-[15px] leading-snug font-semibold text-primary">
                    Every answer is in hand.
                  </h2>
                </div>
                <p className="text-sm leading-relaxed text-primary">
                  Nothing is left for you to answer. Review the exact packet
                  before you authorize form filling.
                </p>
              </section>
            )}

            <LinkButton to="/app/approvals" className="w-full">
              Review &amp; authorize →
            </LinkButton>

            <section className="flex flex-col gap-2 rounded-surface border border-border-surface bg-card p-5">
              <div className="flex items-center gap-2">
                <ShieldCheck
                  className="size-4 shrink-0 text-primary"
                  aria-hidden
                />
                <h2 className="text-sm font-semibold text-foreground">
                  Your answers have a clear source.
                </h2>
              </div>
              <p className="text-xs leading-relaxed text-muted-foreground">
                A profile-derived answer names the field it came from; a
                never-autofilled question (equal opportunity, attestation) has
                no control here at all. Saving an answer records it on this
                application and refreshes its history.
              </p>
            </section>
          </aside>
        </div>
      ) : null}
    </div>
  )
}
