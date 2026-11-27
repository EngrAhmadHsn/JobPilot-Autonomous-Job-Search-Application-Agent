import { useQuery } from "@tanstack/react-query"

import { request } from "./client"
import { api } from "./endpoints"

export function useApplicationAccountId() {
  const identity = useQuery({
    queryKey: ["identity"],
    queryFn: ({ signal }) => api.identity(signal),
    retry: false,
  })
  return identity.isSuccess ? identity.data?.id : undefined
}

export type AnswerValue = string | string[]
export type FormState = "available" | "unavailable" | "unsupported"
export type QuestionKind =
  | "text"
  | "textarea"
  | "select"
  | "multiselect"
  | "contact"
  | "resume"
  | "employer"

export interface PostingQuestion {
  question_key: string
  label: string
  kind: QuestionKind
  required: boolean
  description?: string | null
  options?: { value: string; label: string }[]
  answer: AnswerValue | null
  field_name?: string | null
}

export interface PostingForm {
  state: FormState
  questions: PostingQuestion[]
}

export interface EmployerAnswer extends PostingQuestion {
  id: string
  job_id: string
  company_name: string
  job_title: string
  updated_at: string
  answer: AnswerValue
}

export interface PostingPacket {
  application_id: string
  approval_id: string
  blocking_questions: string[]
  prepared_summary: {
    document_id: string
    document_filename: string
    job_url?: string
  }
  posting_form?: PostingForm
  on_employer_site?: string[]
  assist_available?: boolean
  contact?: { candidate_name: string; email: string; phone: string }
}

export interface StoredPostingPacket extends PostingPacket {
  job_id: string
  job_title: string
  company_name: string
  job_url: string
  posting_form: PostingForm
  on_employer_site: string[]
  contact: { candidate_name: string; email: string; phone: string }
  document_current: boolean
  review_current: boolean
}

export interface PostingPreparation {
  job_id: string
  job_title: string
  company_name: string
  job_url: string
  document_id: string
  candidate_name: string
  email: string
  phone: string
}

export const postingPath = (jobId: string) =>
  `/app/matches/${encodeURIComponent(jobId)}`
export const preparePath = (jobId: string) => `${postingPath(jobId)}/prepare`
const formPath = (jobId: string) =>
  `/api/jobs/${encodeURIComponent(jobId)}/application-form`
const libraryPath = "/api/profiles/employer-answers"

export const postingFormKey = (jobId: string, accountId?: string) =>
  accountId
    ? (["posting-form", jobId, accountId] as const)
    : (["posting-form", jobId] as const)
export const employerLibraryKey = ["employer-answers"] as const
export const editableQuestion = (q: PostingQuestion) =>
  q.kind !== "contact" && q.kind !== "resume" && q.kind !== "employer"

export function usePostingForm(jobId: string) {
  const accountId = useApplicationAccountId()
  return useQuery({
    queryKey: postingFormKey(jobId, accountId),
    queryFn: ({ signal }) => request<PostingForm>(formPath(jobId), { signal }),
    enabled: Boolean(jobId && accountId),
    staleTime: 60_000,
    retry: false,
  })
}

export const savePostingAnswers = (
  jobId: string,
  answers: { question_key: string; answer: AnswerValue }[]
) =>
  request<PostingForm>(`${formPath(jobId)}/answers`, {
    method: "PUT",
    json: { answers },
  })

export const preparePosting = (json: PostingPreparation) =>
  request<PostingPacket>("/api/applications/prepare", { method: "POST", json })

export const readPostingPacket = (id: string, signal?: AbortSignal) =>
  request<StoredPostingPacket>(
    `/api/applications/${encodeURIComponent(id)}/posting-review`,
    { signal }
  )

export const employerAnswers = (offset: number, signal?: AbortSignal) =>
  request<{ items: EmployerAnswer[]; next_offset: number | null }>(
    libraryPath,
    {
      query: { offset },
      signal,
    }
  )

export const editEmployerAnswer = (id: string, answer: AnswerValue) =>
  request<EmployerAnswer>(`${libraryPath}/${encodeURIComponent(id)}`, {
    method: "PUT",
    json: { answer },
  })

export const removeEmployerAnswer = (id: string) =>
  request<void>(`${libraryPath}/${encodeURIComponent(id)}`, {
    method: "DELETE",
  })
