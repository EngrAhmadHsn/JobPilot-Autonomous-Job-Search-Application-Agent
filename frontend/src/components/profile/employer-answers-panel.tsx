import {
  useInfiniteQuery,
  useMutation,
  useQueryClient,
} from "@tanstack/react-query"
import { useId, useRef, useState, type FormEvent, type RefObject } from "react"

import { ErrorNotice } from "@/components/common/error-notice"
import {
  displayAnswer,
  EmployerQuestionField,
  hasAnswer,
} from "@/components/profile/employer-question-field"
import {
  AlertDialog,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog"
import { Button } from "@/components/ui/button"
import {
  Dialog,
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { LinkButton } from "@/components/ui/link-button"
import {
  editableQuestion,
  editEmployerAnswer,
  employerAnswers,
  employerLibraryKey,
  postingFormKey,
  preparePath,
  removeEmployerAnswer,
  useApplicationAccountId,
  type AnswerValue,
  type EmployerAnswer,
} from "@/lib/api/posting-application"

type AnswerAction =
  | { type: "edit"; item: EmployerAnswer; draft: AnswerValue }
  | { type: "delete"; item: EmployerAnswer }

function groupAnswers(rows: EmployerAnswer[]) {
  const companies = new Map<
    string,
    Map<string, { title: string; items: EmployerAnswer[] }>
  >()
  // Offset pages can overlap if another tab saves an answer while paging.
  const seen = new Set<string>()
  for (const row of rows) {
    if (seen.has(row.id)) continue
    seen.add(row.id)
    const postings =
      companies.get(row.company_name) ??
      new Map<string, { title: string; items: EmployerAnswer[] }>()
    const posting = postings.get(row.job_id) ?? {
      title: row.job_title,
      items: [],
    }
    posting.items.push(row)
    postings.set(row.job_id, posting)
    companies.set(row.company_name, postings)
  }
  return companies
}

function validationMessage(item: EmployerAnswer, draft: AnswerValue) {
  if (item.kind === "multiselect") {
    if (!Array.isArray(draft) || !hasAnswer(draft))
      return "Select at least one answer."
    if (draft.length > 100) return "Select no more than 100 answers."
    if (
      draft.some(
        (value) => !item.options?.some((option) => option.value === value)
      )
    ) {
      return "Select only the employer’s listed options."
    }
  } else if (item.kind === "select") {
    if (
      !hasAnswer(draft) ||
      !item.options?.some((option) => option.value === draft)
    ) {
      return "Select one of the employer’s listed options."
    }
  } else if (
    typeof draft !== "string" ||
    !hasAnswer(draft) ||
    draft.trim().length > 4000
  ) {
    return "Enter an answer of 1 to 4,000 characters, or delete the saved answer."
  }
  return null
}

export function EmployerAnswersPanel() {
  const accountId = useApplicationAccountId()
  const headingId = useId()
  const heading = useRef<HTMLHeadingElement>(null)

  return (
    <section
      aria-labelledby={headingId}
      className="min-w-0 space-y-4 rounded-surface border border-border-surface bg-card p-5"
    >
      <header className="space-y-1">
        <h2
          id={headingId}
          ref={heading}
          tabIndex={-1}
          className="text-xl font-semibold text-primary"
        >
          Company-specific answers
        </h2>
        <p className="text-sm text-muted-foreground">
          Answers saved while preparing an application are only used for that
          posting and question. They aren’t reused for other jobs, even at the
          same company.
        </p>
      </header>
      {accountId ? (
        <EmployerAnswersLibrary
          key={accountId}
          accountId={accountId}
          heading={heading}
        />
      ) : (
        <p role="status" className="text-sm text-muted-foreground">
          Checking your account…
        </p>
      )}
    </section>
  )
}

function EmployerAnswersLibrary({
  accountId,
  heading,
}: {
  accountId: string
  heading: RefObject<HTMLHeadingElement | null>
}) {
  const trigger = useRef<HTMLButtonElement>(null)
  const [action, setAction] = useState<AnswerAction | null>(null)
  const [validation, setValidation] = useState<string | null>(null)
  const [status, setStatus] = useState("")
  const queryClient = useQueryClient()
  const libraryKey = [...employerLibraryKey, accountId] as const
  const library = useInfiniteQuery({
    queryKey: libraryKey,
    queryFn: ({ pageParam, signal }) => employerAnswers(pageParam, signal),
    initialPageParam: 0,
    getNextPageParam: (page) => page.next_offset ?? undefined,
    retry: false,
  })
  const saved = useMutation({
    mutationFn: async (submitted: AnswerAction) => {
      if (submitted.type === "delete") {
        await removeEmployerAnswer(submitted.item.id)
      } else {
        await editEmployerAnswer(submitted.item.id, submitted.draft)
      }
    },
    retry: false,
    onSuccess: async (_response, submitted) => {
      // Never change or invalidate answers for a different posting, even at the same company.
      void queryClient.invalidateQueries({
        queryKey: postingFormKey(submitted.item.job_id),
      })
      void queryClient.invalidateQueries({ queryKey: ["posting-review"] })
      // Saving can reorder the account’s list; let the API repaginate all loaded pages.
      await queryClient.invalidateQueries({ queryKey: libraryKey, exact: true })
      if (submitted.type === "delete") trigger.current = null
      setAction(null)
      setStatus(
        submitted.type === "delete" ? "Answer deleted." : "Answer saved."
      )
    },
  })
  const companies = groupAnswers(
    library.data?.pages.flatMap((page) => page.items) ?? []
  )
  const edit = action?.type === "edit" ? action : null
  const deletion = action?.type === "delete" ? action : null
  const finalFocus = () =>
    trigger.current?.isConnected ? trigger.current : heading.current

  function open(next: AnswerAction, button: HTMLButtonElement) {
    trigger.current = button
    saved.reset()
    setValidation(null)
    setStatus("")
    setAction(next)
  }

  function onOpenChange(isOpen: boolean) {
    if (!isOpen && !saved.isPending) setAction(null)
  }

  function submitEdit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!edit || saved.isPending) return
    const error = validationMessage(edit.item, edit.draft)
    setValidation(error)
    if (error) return
    const { item, draft } = edit
    saved.mutate({
      ...edit,
      draft:
        (item.kind === "text" || item.kind === "textarea") &&
        typeof draft === "string"
          ? draft.trim()
          : draft,
    })
  }

  return (
    <>
      <p role="status" className="sr-only">
        {status}
      </p>
      {library.isPending ? (
        <p role="status" className="text-sm text-muted-foreground">
          Loading company-specific answers…
        </p>
      ) : null}
      {library.isError ? (
        <ErrorNotice
          error={library.error}
          onRetry={() => {
            void (library.isFetchNextPageError
              ? library.fetchNextPage()
              : library.refetch())
          }}
        />
      ) : null}
      {library.isSuccess && companies.size === 0 && !library.hasNextPage ? (
        <p className="text-sm text-muted-foreground">
          No company-specific answers yet.
        </p>
      ) : null}

      {[...companies].map(([company, postings]) => (
        <div
          key={company}
          className="space-y-3 border-t border-border-surface pt-4"
        >
          <h3 className="font-semibold wrap-anywhere text-foreground">
            {company}
          </h3>
          {[...postings].map(([jobId, posting]) => (
            <div
              key={jobId}
              className="min-w-0 space-y-2 rounded-lg border border-border-surface px-3 py-2"
            >
              <div className="flex flex-wrap items-start justify-between gap-x-3 gap-y-1">
                <div className="min-w-0">
                  <h4 className="text-sm font-semibold wrap-anywhere text-foreground">
                    {posting.title}
                  </h4>
                  <p className="text-xs wrap-anywhere text-muted-foreground">
                    Posting {jobId}
                  </p>
                </div>
                <LinkButton to={preparePath(jobId)} variant="ghost" size="sm">
                  Open application
                  <span className="sr-only">
                    {" "}
                    for {posting.title} at {company}, posting {jobId}
                  </span>
                </LinkButton>
              </div>
              <ul className="divide-y divide-border-surface border-t border-border-surface">
                {posting.items.map((item) => (
                  <li
                    key={item.id}
                    className="flex min-w-0 flex-wrap items-start justify-between gap-x-4 gap-y-2 py-2"
                  >
                    <div className="min-w-0 flex-1 basis-48 space-y-1 text-sm wrap-anywhere">
                      <p className="font-medium">{item.label}</p>
                      <p className="whitespace-pre-wrap text-muted-foreground">
                        {displayAnswer(item)}
                      </p>
                    </div>
                    <div className="flex gap-1">
                      {editableQuestion(item) ? (
                        <Button
                          type="button"
                          variant="outline"
                          size="sm"
                          aria-label={`Edit answer: ${item.label} (${posting.title}, posting ${jobId})`}
                          onClick={(event) =>
                            open(
                              { type: "edit", item, draft: item.answer },
                              event.currentTarget
                            )
                          }
                        >
                          Edit
                        </Button>
                      ) : null}
                      <Button
                        type="button"
                        variant="ghost"
                        size="sm"
                        aria-label={`Delete answer: ${item.label} (${posting.title}, posting ${jobId})`}
                        onClick={(event) =>
                          open({ type: "delete", item }, event.currentTarget)
                        }
                      >
                        Delete
                      </Button>
                    </div>
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </div>
      ))}
      {library.hasNextPage && !library.isFetchNextPageError ? (
        <Button
          type="button"
          variant="outline"
          size="sm"
          disabled={library.isFetching}
          onClick={() => void library.fetchNextPage()}
        >
          {library.isFetchingNextPage ? "Loading more…" : "Load more answers"}
        </Button>
      ) : null}

      <Dialog open={edit !== null} onOpenChange={onOpenChange}>
        <DialogContent
          showCloseButton={false}
          finalFocus={finalFocus}
          className="max-h-[calc(100dvh-2rem)] overflow-y-auto sm:max-w-lg"
        >
          {edit ? (
            <>
              <DialogHeader>
                <DialogTitle>Edit saved answer</DialogTitle>
                <DialogDescription className="wrap-anywhere">
                  {edit.item.job_title} at {edit.item.company_name} · Posting{" "}
                  {edit.item.job_id}
                </DialogDescription>
              </DialogHeader>
              <form onSubmit={submitEdit} className="space-y-4">
                <fieldset disabled={saved.isPending} className="min-w-0">
                  <EmployerQuestionField
                    question={edit.item}
                    value={edit.draft}
                    onChange={(draft) => {
                      setAction({ ...edit, draft })
                      setValidation(null)
                      if (saved.isError) saved.reset()
                    }}
                  />
                </fieldset>
                {validation ? (
                  <p role="alert" className="text-sm text-destructive">
                    {validation}
                  </p>
                ) : null}
                <ErrorNotice error={saved.error} />
                <div className="flex flex-wrap justify-end gap-2">
                  <DialogClose
                    render={<Button type="button" variant="outline" />}
                    disabled={saved.isPending}
                  >
                    Cancel
                  </DialogClose>
                  <Button type="submit" disabled={saved.isPending}>
                    {saved.isPending ? "Saving…" : "Save answer"}
                  </Button>
                </div>
              </form>
            </>
          ) : null}
        </DialogContent>
      </Dialog>

      <AlertDialog open={deletion !== null} onOpenChange={onOpenChange}>
        <AlertDialogContent
          finalFocus={finalFocus}
          className="max-h-[calc(100dvh-2rem)] overflow-y-auto"
        >
          {deletion ? (
            <>
              <AlertDialogHeader>
                <AlertDialogTitle>Delete this saved answer?</AlertDialogTitle>
                <AlertDialogDescription className="wrap-anywhere">
                  This removes the saved answer to “{deletion.item.label}” for{" "}
                  {deletion.item.job_title} at {deletion.item.company_name}{" "}
                  (posting {deletion.item.job_id}). It does not affect other
                  postings.
                </AlertDialogDescription>
              </AlertDialogHeader>
              <ErrorNotice error={saved.error} />
              <AlertDialogFooter>
                <AlertDialogCancel disabled={saved.isPending}>
                  Cancel
                </AlertDialogCancel>
                <Button
                  type="button"
                  variant="destructive"
                  disabled={saved.isPending}
                  onClick={() => saved.mutate(deletion)}
                >
                  {saved.isPending ? "Deleting…" : "Delete answer"}
                </Button>
              </AlertDialogFooter>
            </>
          ) : null}
        </AlertDialogContent>
      </AlertDialog>
    </>
  )
}
