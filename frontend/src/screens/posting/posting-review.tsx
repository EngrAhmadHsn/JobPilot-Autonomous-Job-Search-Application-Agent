import { ArrowUpRightIcon, CopyIcon, DownloadIcon } from "lucide-react"
import { useEffect, useRef, useState, type ReactNode } from "react"

import { FieldList } from "@/components/common/field-list"
import {
  displayAnswer,
  hasAnswer,
} from "@/components/profile/employer-question-field"
import { Button, buttonVariants } from "@/components/ui/button"
import { Card, CardContent, CardHeader } from "@/components/ui/card"
import { apiUrl } from "@/lib/api/client"
import {
  editableQuestion,
  type PostingPacket,
} from "@/lib/api/posting-application"
import { isSafeLinkUrl } from "@/lib/safe-url"

import { AssistedFill } from "./assisted-fill"

export const postingReviewPath = (applicationId: string) =>
  `/app/tracker/${encodeURIComponent(applicationId)}/review`

function employerUrl(value: string) {
  if (!isSafeLinkUrl(value)) return null
  try {
    const url = new URL(value)
    return url.protocol === "https:" || url.protocol === "http:" ? url : null
  } catch {
    return null
  }
}

/** A read-only packet. The only handoff is the candidate opening the external link. */
export function ManualPostingReview({
  packet,
  contact,
  jobUrl,
  actions,
  checking = false,
  documentCurrent = true,
  reviewCurrent = true,
}: {
  packet: PostingPacket
  contact: NonNullable<PostingPacket["contact"]>
  jobUrl: string
  actions?: ReactNode
  checking?: boolean
  documentCurrent?: boolean
  reviewCurrent?: boolean
}) {
  const headingRef = useRef<HTMLHeadingElement>(null)
  useEffect(() => {
    headingRef.current?.focus({ preventScroll: true })
    headingRef.current?.scrollIntoView({ block: "start" })
  }, [])

  const blockers = packet.blocking_questions
  const savedAnswers =
    packet.posting_form?.questions.filter(
      (question) => editableQuestion(question) && hasAnswer(question.answer)
    ) ?? []
  const manual = packet.on_employer_site ?? []
  const site = employerUrl(jobUrl)
  const stale = !documentCurrent || !reviewCurrent
  const ready = !checking && !stale && blockers.length === 0
  const { document_id: documentId, document_filename: filename } =
    packet.prepared_summary

  return (
    <div className="space-y-5" aria-busy={checking || undefined}>
      <section aria-labelledby="posting-review-heading">
        <Card className="border border-border-surface bg-forest-soft">
          <CardHeader>
            <h2
              ref={headingRef}
              id="posting-review-heading"
              tabIndex={-1}
              className="type-section"
            >
              {checking
                ? "Checking your saved review…"
                : stale
                  ? "Prepare an updated review"
                  : ready
                    ? "Ready for your review"
                    : "Required answers still missing"}
            </h2>
            <p className="text-sm leading-relaxed text-muted-foreground">
              Nothing has been filled in or submitted. You enter the details and
              submit the application yourself on the employer’s site.
            </p>
          </CardHeader>
          <CardContent className="space-y-4">
            {stale && !checking ? (
              <div role="status" className="space-y-1 text-sm">
                {!documentCurrent ? (
                  <p>Your résumé has changed or is no longer available.</p>
                ) : null}
                {!reviewCurrent ? (
                  <p>
                    Your saved answers have changed since this review was
                    prepared.
                  </p>
                ) : null}
                <p>
                  Return to preparation and create a new review before using
                  this packet.
                </p>
              </div>
            ) : null}
            {blockers.length > 0 ? (
              <ul className="list-disc space-y-1 ps-5 text-sm">
                {blockers.map((label, index) => (
                  <li key={`${label}-${index}`} className="wrap-anywhere">
                    {label}
                  </li>
                ))}
              </ul>
            ) : null}
            {packet.posting_form?.state !== "available" ? (
              <p className="text-sm text-muted-foreground">
                The employer’s questions could not be verified for this review.
                Check the live form before applying.
              </p>
            ) : null}
            {ready && site && packet.assist_available ? (
              <AssistedFill
                applicationId={packet.application_id}
                host={site.host}
              />
            ) : null}
            <div className="flex flex-wrap items-center gap-2">
              {ready && site ? (
                <a
                  href={site.href}
                  target="_blank"
                  rel="noreferrer noopener"
                  className={buttonVariants()}
                >
                  Open employer site <ArrowUpRightIcon aria-hidden="true" />
                </a>
              ) : null}
              {actions}
            </div>
            {ready ? (
              <p className="text-sm wrap-anywhere text-muted-foreground">
                {site ? (
                  <>Employer destination: {site.host} · Opens in a new tab</>
                ) : (
                  "There is no verified link to the employer site for this posting."
                )}
              </p>
            ) : null}
          </CardContent>
        </Card>
      </section>

      <Card>
        <CardHeader>
          <h2 className="type-section">Contact and résumé</h2>
        </CardHeader>
        <CardContent className="space-y-3">
          <FieldList
            items={[
              {
                label: "Full name",
                value: (
                  <span className="wrap-anywhere">
                    {contact.candidate_name}
                  </span>
                ),
              },
              {
                label: "Email",
                value: <span className="wrap-anywhere">{contact.email}</span>,
              },
              {
                label: "Phone",
                value: (
                  <span className="wrap-anywhere">
                    {contact.phone || "Not provided"}
                  </span>
                ),
              },
              {
                label: "Résumé",
                value: <span className="wrap-anywhere">{filename}</span>,
              },
            ]}
          />
          {documentCurrent && !checking ? (
            <a
              href={apiUrl(
                `/api/documents/${encodeURIComponent(documentId)}/download`
              )}
              className="inline-flex max-w-full items-start gap-2 rounded-sm text-sm font-medium wrap-anywhere text-primary underline underline-offset-4"
            >
              <DownloadIcon
                className="mt-0.5 size-4 shrink-0"
                aria-hidden="true"
              />
              <span>Download {filename}</span>
            </a>
          ) : null}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <h2 className="type-section">Saved employer answers</h2>
        </CardHeader>
        <CardContent className="space-y-4">
          {savedAnswers.length > 0 ? (
            <dl className="divide-y divide-border-surface">
              {savedAnswers.map((question) => (
                <SavedAnswer
                  key={question.question_key}
                  label={question.label}
                  value={displayAnswer(question)}
                  copyable={reviewCurrent && !checking}
                />
              ))}
            </dl>
          ) : (
            <p className="text-sm text-muted-foreground">
              No saved employer answers were included in this review.
            </p>
          )}
          {manual.length > 0 ? (
            <div className="space-y-2 rounded-lg border border-border-surface bg-muted/40 p-3">
              <h3 className="font-semibold">Answer on the employer site</h3>
              <p className="text-muted-foreground">
                The employer requires these answers. They are not saved in this
                review.
              </p>
              <ul className="list-disc space-y-1 ps-5">
                {manual.map((label, index) => (
                  <li key={`${label}-${index}`} className="wrap-anywhere">
                    {label}
                  </li>
                ))}
              </ul>
            </div>
          ) : null}
        </CardContent>
      </Card>
    </div>
  )
}

function SavedAnswer({
  label,
  value,
  copyable,
}: {
  label: string
  value: string
  copyable: boolean
}) {
  const [notice, setNotice] = useState("")

  async function copy() {
    try {
      await navigator.clipboard.writeText(value)
      setNotice("Copied to clipboard.")
    } catch {
      setNotice("Clipboard unavailable. Select and copy this answer instead.")
    }
  }

  return (
    <div className="space-y-2 py-3 first:pt-0 last:pb-0">
      <dt className="font-medium wrap-anywhere">{label}</dt>
      <dd className="space-y-2">
        <p className="wrap-anywhere whitespace-pre-wrap">{value}</p>
        {copyable ? (
          <div className="flex flex-wrap items-center gap-2">
            <Button
              type="button"
              variant="outline"
              size="sm"
              aria-label={`Copy answer for ${label}`}
              onClick={() => void copy()}
            >
              <CopyIcon aria-hidden="true" /> Copy answer
            </Button>
            <p role="status" className="text-sm text-muted-foreground">
              {notice}
            </p>
          </div>
        ) : null}
      </dd>
    </div>
  )
}
