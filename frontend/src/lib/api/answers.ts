/**
 * The per-application answers API (WS-45).
 *
 * The human's answers to an employer's questions are **personal data tied
 * to one application**: they live on the application row the prepare flow
 * created, they are fenced to the signed-in account on the server (a
 * foreign application is a 404, indistinguishable from a missing one), and
 * they are the one kind of answer the console may store — EEO and
 * attestation questions are refused with a 422 and stay routed to the
 * employer's own site.
 *
 * `GET` and `PUT` answer the same shape — a save returns the **whole**
 * saved set, so the Review screen can render "5 of 6 answers confirmed"
 * straight off the response.
 *
 * The shapes here are written by hand, next to the generated ones in
 * `types.ts`, for the same reason `AuditEvent` is: `schema.ts` is generated
 * from a running backend and had not been regenerated when this file was
 * written (and `types.ts` belongs to another agent this sprint). When the
 * schema is next generated, the two interfaces can become aliases of
 * `components["schemas"]["ApplicationAnswersResponse"]` and friends.
 */
import { request } from "./client"
import type { BoardQuestion } from "./types"

/** One saved answer, as both `GET` and `PUT` return it (WS-45). */
export interface SavedAnswerRecord {
  /** The key the answer was saved under — the prepare response's `question_key`. */
  question_key: string
  /** The board's own wording, as displayed when the answer was saved. */
  label: string
  /** The taxonomy category, when it was known at save time. */
  category: string | null
  /** What the human answered. */
  answer: string
  /** When the answer was last saved (a re-answer refreshes it). */
  answered_at: string
}

/** The saved answers of one application — `GET` and `PUT`'s shared body. */
export interface ApplicationAnswers {
  application_id: string
  answers: SavedAnswerRecord[]
}

/** One answer in a `PUT` body. `label`/`category` are kept for display. */
export interface AnswerInput {
  question_key: string
  label?: string
  category?: string | null
  answer: string
}

/** The answers the human saved for one application. */
export function getApplicationAnswers(
  applicationId: string,
  signal?: AbortSignal
) {
  return request<ApplicationAnswers>(
    `/api/applications/${encodeURIComponent(applicationId)}/answers`,
    { signal, timeoutMs: 20_000 }
  )
}

/**
 * Save answers for one application — an upsert (a re-answer updates in
 * place; nothing is ever deleted here). The server refuses EEO/attestation
 * answers, blank answers, and answers over 500 characters with a `422`
 * whose `detail` is written for a human — the screen surfaces it verbatim.
 */
export function putApplicationAnswers(
  applicationId: string,
  answers: AnswerInput[],
  signal?: AbortSignal
) {
  return request<ApplicationAnswers>(
    `/api/applications/${encodeURIComponent(applicationId)}/answers`,
    { method: "PUT", json: { answers }, signal, timeoutMs: 20_000 }
  )
}

/**
 * A board question as the WS-45 backend sends it: `BoardQuestion` plus the
 * additive `question_key` (the answer's stable storage key). `schema.ts`
 * predates that field and `types.ts` is another agent's file this sprint,
 * so the one added field is named here; when the schema is regenerated the
 * intersection collapses onto the generated field.
 */
export type QuestionWithKey = BoardQuestion & { question_key?: string }

/**
 * The key a save is stored under for this question.
 *
 * The prepare response hands the console a canonical `question_key` (the
 * label's normalized form); the server's merge also accepts the raw label,
 * so an older payload without the field still saves under a key the merge
 * matches.
 */
export function questionKeyOf(question: QuestionWithKey): string {
  const raw = (question as { question_key?: unknown }).question_key
  if (typeof raw === "string" && raw.trim()) return raw.trim()
  return question.label
}
