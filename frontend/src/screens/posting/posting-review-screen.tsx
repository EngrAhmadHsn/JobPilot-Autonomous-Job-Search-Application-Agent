import { useQuery } from "@tanstack/react-query"
import { useParams } from "react-router-dom"

import { CardSkeleton } from "@/components/common/card-skeleton"
import { ErrorState } from "@/components/ui/error-state"
import { LinkButton } from "@/components/ui/link-button"
import { PageHeader } from "@/components/ui/page-header"
import {
  postingPath,
  preparePath,
  readPostingPacket,
  useApplicationAccountId,
} from "@/lib/api/posting-application"

import { ManualPostingReview } from "./posting-review"

export function PostingReviewScreen() {
  const { applicationId = "" } = useParams()
  const accountId = useApplicationAccountId()
  const review = useQuery({
    queryKey: ["posting-review", applicationId, accountId],
    queryFn: ({ signal }) => readPostingPacket(applicationId, signal),
    enabled: Boolean(applicationId && accountId),
    staleTime: 0,
    refetchOnWindowFocus: true,
  })
  const packet = accountId && !review.isError ? review.data : undefined
  const documentId = packet?.prepared_summary.document_id
  const draftId = documentId?.startsWith("tailored-")
    ? documentId.slice("tailored-".length)
    : null
  const editorPath = packet
    ? `${preparePath(packet.job_id)}${draftId ? `?draft=${encodeURIComponent(draftId)}` : ""}`
    : null

  return (
    <div className="mx-auto max-w-3xl space-y-6">
      <PageHeader
        title="Application review"
        description={
          packet ? (
            <p className="wrap-anywhere">
              {packet.job_title} · {packet.company_name}
            </p>
          ) : undefined
        }
        actions={
          packet ? (
            <LinkButton variant="outline" to={postingPath(packet.job_id)}>
              Back to posting
            </LinkButton>
          ) : (
            <LinkButton variant="outline" to="/app/tracker">
              Back to Tracker
            </LinkButton>
          )
        }
      />
      {packet ? (
        <ManualPostingReview
          key={`${accountId}:${applicationId}`}
          packet={packet}
          contact={packet.contact}
          jobUrl={packet.job_url}
          checking={review.isFetching}
          documentCurrent={packet.document_current}
          reviewCurrent={packet.review_current}
          actions={
            editorPath ? (
              <LinkButton variant="outline" to={editorPath}>
                Edit preparation
              </LinkButton>
            ) : undefined
          }
        />
      ) : review.isError ? (
        <ErrorState
          error={review.error}
          onRetry={() => void review.refetch()}
        />
      ) : (
        <CardSkeleton rows={4} />
      )}
    </div>
  )
}
