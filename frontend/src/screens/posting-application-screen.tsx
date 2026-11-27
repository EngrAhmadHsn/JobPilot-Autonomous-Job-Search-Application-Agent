import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { useRef, useState, type FormEvent } from "react"
import { Link, useParams, useSearchParams } from "react-router-dom"

import { CardSkeleton } from "@/components/common/card-skeleton"
import { ErrorNotice } from "@/components/common/error-notice"
import { useDocuments } from "@/components/documents/document-picker"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader } from "@/components/ui/card"
import { ErrorState } from "@/components/ui/error-state"
import { Input } from "@/components/ui/input"
import { LinkButton } from "@/components/ui/link-button"
import { useDocumentTitle } from "@/hooks/use-document-title"
import { api } from "@/lib/api/endpoints"
import {
  postingPath,
  preparePosting,
  useApplicationAccountId,
} from "@/lib/api/posting-application"
import type { DocumentRecord, JobListing } from "@/lib/api/types"
import { useCurrentProfileId } from "@/lib/profile"

import {
  PostingQuestions,
  usePostingQuestionEditor,
} from "./posting/posting-questions"
import {
  ManualPostingReview,
  postingReviewPath,
} from "./posting/posting-review"

type ContactField = "candidate_name" | "email" | "phone"
type Contact = Record<ContactField, string>

const contactFields = [
  {
    name: "candidate_name",
    label: "Full name",
    type: "text",
    autoComplete: "name",
    maxLength: 200,
  },
  {
    name: "email",
    label: "Email",
    type: "email",
    autoComplete: "email",
    maxLength: 254,
  },
  {
    name: "phone",
    label: "Phone",
    type: "tel",
    autoComplete: "tel",
    maxLength: 100,
  },
] as const

function usableDocument(document: DocumentRecord) {
  return document.size_bytes !== null && document.size_bytes > 0
}

export function PostingApplicationScreen() {
  const { jobId = "" } = useParams()
  const accountId = useApplicationAccountId()
  const [searchParams] = useSearchParams()
  const draftId = searchParams.get("draft")
  const job = useQuery({
    queryKey: ["job", jobId],
    queryFn: ({ signal }) => api.getJob(jobId, signal),
    enabled: Boolean(jobId),
  })
  const listing = job.data?.job
  const heading = useRef<HTMLHeadingElement>(null)
  useDocumentTitle("Prepare application")

  return (
    <div className="mx-auto max-w-3xl space-y-6">
      <header className="flex flex-wrap items-end justify-between gap-4">
        <div className="min-w-0">
          <h1 ref={heading} tabIndex={-1} className="type-display">
            Prepare application
          </h1>
          {listing ? (
            <p className="mt-2 text-sm wrap-anywhere text-muted-foreground">
              {listing.title} · {listing.company}
            </p>
          ) : null}
        </div>
        <LinkButton to={postingPath(jobId)} variant="outline">
          Back to posting
        </LinkButton>
      </header>
      {job.isError ? (
        <ErrorState error={job.error} onRetry={() => void job.refetch()} />
      ) : listing && accountId ? (
        <PostingEditor
          key={JSON.stringify([accountId, jobId, draftId])}
          accountId={accountId}
          job={listing}
          draftId={draftId}
          onReturnToEditor={() => {
            heading.current?.focus({ preventScroll: true })
            heading.current?.scrollIntoView({ block: "start" })
          }}
        />
      ) : (
        <CardSkeleton rows={4} />
      )}
    </div>
  )
}

function PostingEditor({
  accountId,
  job,
  draftId,
  onReturnToEditor,
}: {
  accountId: string
  job: JobListing
  draftId: string | null
  onReturnToEditor: () => void
}) {
  const queryClient = useQueryClient()
  const activeProfileId = useCurrentProfileId()
  const documents = useDocuments()
  const [chosenId, setChosenId] = useState<string | null>(null)
  const [contactEdits, setContactEdits] = useState<Partial<Contact>>({})
  const editor = usePostingQuestionEditor(job.id, accountId)

  const files = (documents.data?.documents ?? []).filter(usableDocument)
  const originals = files.filter((file) => file.kind === "resume")
  const tailored = files.filter(
    (file) => file.kind === "tailored" && file.job_id === job.id
  )
  const defaultOriginal =
    (activeProfileId
      ? originals.find((file) => file.profile_id === activeProfileId)
      : undefined) ?? originals[0]
  const linkedDraft = draftId
    ? tailored.find((file) => file.id === `tailored-${draftId}`)
    : undefined
  const choices = [...originals, ...tailored]
  const selected =
    chosenId !== null
      ? choices.find((file) => file.id === chosenId)
      : draftId
        ? linkedDraft
        : defaultOriginal
  const contactProfileId = selected?.profile_id ?? null
  const profile = useQuery({
    queryKey: ["profile", contactProfileId],
    queryFn: ({ signal }) => api.getResume(contactProfileId!, signal),
    enabled: Boolean(contactProfileId),
    retry: false,
  })
  const information = profile.data?.profile.personal_information
  const contact: Contact = {
    candidate_name: contactEdits.candidate_name ?? information?.name ?? "",
    email: contactEdits.email ?? information?.email ?? "",
    phone: contactEdits.phone ?? information?.phone ?? "",
  }
  const phoneRequired = editor.questions.some(
    (question) =>
      question.kind === "contact" &&
      question.field_name === "phone" &&
      question.required
  )
  const prepare = useMutation({
    mutationFn: preparePosting,
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["applications"] })
    },
  })
  const canPrepare =
    Boolean(selected) &&
    !documents.isError &&
    !prepare.isPending &&
    !editor.save.isPending &&
    !editor.hasChanges

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!selected || !canPrepare) return
    prepare.mutate({
      job_id: job.id,
      job_title: job.title,
      company_name: job.company,
      job_url: job.application_url ?? "",
      document_id: selected.id,
      candidate_name: contact.candidate_name.trim(),
      email: contact.email.trim(),
      phone: contact.phone.trim(),
    })
  }

  if (prepare.data) {
    return (
      <ManualPostingReview
        packet={prepare.data}
        contact={prepare.data.contact ?? prepare.variables}
        jobUrl={
          prepare.data.prepared_summary.job_url ?? prepare.variables.job_url
        }
        actions={
          <>
            <Button
              type="button"
              variant="outline"
              onClick={() => {
                prepare.reset()
                onReturnToEditor()
              }}
            >
              Edit preparation
            </Button>
            <LinkButton
              variant="outline"
              to={postingReviewPath(prepare.data.application_id)}
            >
              Open saved review in Tracker
            </LinkButton>
          </>
        }
      />
    )
  }

  return (
    <>
      <form
        id="posting-preparation"
        aria-labelledby="posting-contact"
        onSubmit={submit}
      >
        <Card>
          <CardHeader>
            <h2 id="posting-contact" className="type-section">
              Contact and résumé
            </h2>
            <p className="text-muted-foreground">
              Verify your contact details and choose the file you plan to
              upload. Tailoring is optional.
            </p>
          </CardHeader>
          <CardContent>
            <fieldset
              className="min-w-0 space-y-4"
              disabled={prepare.isPending}
            >
              <div className="grid gap-4 sm:grid-cols-2">
                {contactFields.map((field) => {
                  const required = field.name !== "phone" || phoneRequired
                  return (
                    <div
                      key={field.name}
                      className={
                        field.name === "candidate_name"
                          ? "space-y-1.5 sm:col-span-2"
                          : "space-y-1.5"
                      }
                    >
                      <label
                        className="block font-medium"
                        htmlFor={`posting-${field.name}`}
                      >
                        {field.label}
                        {field.name === "phone" && (
                          <span
                            className="ml-2 text-xs font-normal text-muted-foreground"
                            aria-hidden="true"
                          >
                            {required ? "Required by employer" : "Optional"}
                          </span>
                        )}
                      </label>
                      <Input
                        id={`posting-${field.name}`}
                        name={field.name}
                        value={contact[field.name]}
                        onChange={(event) =>
                          setContactEdits((edits) => ({
                            ...edits,
                            [field.name]: event.target.value,
                          }))
                        }
                        type={field.type}
                        autoComplete={field.autoComplete}
                        maxLength={field.maxLength}
                        required={required}
                        pattern={
                          field.name === "candidate_name" ||
                          (required && field.name === "phone")
                            ? ".*\\S.*"
                            : undefined
                        }
                        className="min-h-10"
                      />
                    </div>
                  )
                })}
              </div>
              {profile.isError ? (
                <p role="status" className="text-muted-foreground">
                  We could not read contact details from the selected résumé.
                  Enter them above.
                </p>
              ) : null}
              <div className="space-y-2 border-t border-border-surface pt-4">
                <label className="block font-medium" htmlFor="posting-document">
                  Résumé
                </label>
                <select
                  id="posting-document"
                  name="document_id"
                  value={selected?.id ?? ""}
                  onChange={(event) => {
                    const next = choices.find(
                      (file) => file.id === event.target.value
                    )
                    if (!next) return
                    if (
                      contactProfileId !== null &&
                      next.profile_id !== contactProfileId
                    )
                      setContactEdits({})
                    setChosenId(next.id)
                  }}
                  aria-describedby="posting-document-hint"
                  disabled={!choices.length || documents.isError}
                  required
                  className="min-h-10 w-full rounded-lg border border-input bg-background px-3 py-2 outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:opacity-60"
                >
                  <option value="" disabled>
                    {documents.isPending
                      ? "Loading your documents…"
                      : "Choose a résumé"}
                  </option>
                  {choices.map((file) => (
                    <option key={file.id} value={file.id}>
                      {file.kind === "resume"
                        ? "Original upload"
                        : "Tailored for this posting"}{" "}
                      — {file.filename}
                    </option>
                  ))}
                </select>
                <p id="posting-document-hint" className="text-muted-foreground">
                  {draftId &&
                  !linkedDraft &&
                  documents.isSuccess &&
                  chosenId === null
                    ? "The linked draft is not available for this posting. Choose a résumé to continue."
                    : "Use your original upload or choose a tailored résumé saved for this posting."}
                </p>
                {documents.isError ? (
                  <ErrorNotice
                    error={documents.error}
                    onRetry={() => void documents.refetch()}
                  />
                ) : documents.isSuccess && choices.length === 0 ? (
                  <p>
                    There’s no available résumé for this posting.{" "}
                    <Link
                      to="/app/resume"
                      className="text-primary underline underline-offset-4"
                    >
                      Upload a résumé
                    </Link>{" "}
                    to continue.
                  </p>
                ) : null}
              </div>
            </fieldset>
          </CardContent>
        </Card>
      </form>

      <PostingQuestions editor={editor} busy={prepare.isPending} />

      <div className="space-y-3">
        <ErrorNotice error={prepare.error} />
        {editor.hasChanges ? (
          <p className="text-sm text-muted-foreground">
            Save or discard your answer edits before preparing the review.
          </p>
        ) : null}
        <Button
          type="submit"
          form="posting-preparation"
          className="min-h-11"
          disabled={!canPrepare}
        >
          {prepare.isPending ? "Preparing your review…" : "Prepare for review"}
        </Button>
      </div>
    </>
  )
}
