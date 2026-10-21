/**
 * The one place the console talks to the API.
 *
 * Everything the backend can say — a status code, a `detail` string, a
 * validation array, a `Retry-After` header, a dead socket — is turned into
 * a **typed error** here, so that no screen has to guess what went wrong
 * and no screen can accidentally render an error object as text.
 *
 * The rules this module enforces:
 *
 * - the base URL comes from `VITE_API_BASE_URL` and nothing else; there is
 *   no secret, no token and no credential in the browser;
 * - every request has a timeout, because a console that waits forever is a
 *   console that lies about being busy;
 * - a non-2xx response never throws a bare `Error`: it throws an
 *   `ApiError` that carries the status, the server's `detail`, and the
 *   `Retry-After` the operator must be told about;
 * - a dead network throws a `NetworkError`, which is a different thing
 *   from a server that refused the request.
 */

/** The API base URL. Empty means "same origin" (the Vite dev proxy). */
export const API_BASE_URL = (import.meta.env.VITE_API_BASE_URL ?? "").replace(
  /\/+$/,
  ""
)

/** One validation problem, as FastAPI reports it. */
export interface ApiValidationIssue {
  loc: (string | number)[]
  msg: string
  type: string
}

/** A response the server refused. */
export class ApiError extends Error {
  readonly status: number
  /** The server's `detail`, as a single readable sentence. */
  readonly detail: string
  /** The validation problems, when the failure was a request-validation one. */
  readonly issues: ApiValidationIssue[]
  /** The seconds the server asked the caller to wait, if it said so. */
  readonly retryAfterSeconds: number | null
  /** The raw parsed body, for the rare case a screen needs more. */
  readonly body: unknown

  constructor(init: {
    status: number
    detail: string
    issues?: ApiValidationIssue[]
    retryAfterSeconds?: number | null
    body?: unknown
  }) {
    super(`${init.status}: ${init.detail}`)
    this.name = "ApiError"
    this.status = init.status
    this.detail = init.detail
    this.issues = init.issues ?? []
    this.retryAfterSeconds = init.retryAfterSeconds ?? null
    this.body = init.body
  }

  /** True when the request may be repeated unchanged. */
  get isRetryable(): boolean {
    if (this.status === 429) return false
    return this.status >= 500
  }
}

/** The request never reached the server. */
export class NetworkError extends Error {
  constructor(message = "The API is unreachable.") {
    super(message)
    this.name = "NetworkError"
  }
}

/** The request was abandoned by the client-side timeout. */
export class TimeoutError extends Error {
  readonly timeoutMs: number

  constructor(timeoutMs: number) {
    super(
      `The request took longer than ${Math.round(timeoutMs / 1000)}s and was abandoned.`
    )
    this.name = "TimeoutError"
    this.timeoutMs = timeoutMs
  }
}

/** The caller aborted the request (the operator pressed Cancel). */
export class AbortedError extends Error {
  constructor() {
    super("The request was cancelled.")
    this.name = "AbortedError"
  }
}

export interface RequestOptions {
  method?: "GET" | "POST" | "PATCH" | "PUT" | "DELETE"
  /** A JSON body. Mutually exclusive with `formData`. */
  json?: unknown
  /** A multipart body. */
  formData?: FormData
  /** The caller's abort signal, so a long call can be cancelled. */
  signal?: AbortSignal
  /** The client-side timeout in milliseconds. */
  timeoutMs?: number
  /** Query parameters, appended to the path. */
  query?: Record<
    string,
    string | number | boolean | undefined | null | string[]
  >
}

/** The default timeout: enough for a slow read, short enough to notice. */
export const DEFAULT_TIMEOUT_MS = 30_000

/**
 * The name of the double-submit CSRF cookie the API sets.
 *
 * It is deliberately **not** `HttpOnly`: the server's rule is that an
 * unsafe request must echo the cookie's value in the `X-CSRF-Token`
 * header, and only JavaScript can do that. The cookie is not a
 * credential — it grants nothing without the session cookie beside it.
 */
const CSRF_COOKIE_NAME = "aja_csrf"

/**
 * Read the CSRF token out of the document's cookies.
 *
 * Returns an empty string when there is no cookie yet (the first request
 * of a session, before the server has issued one), which simply means the
 * header is not sent — the server issues the cookie on that response.
 */
export function csrfToken(): string {
  if (typeof document === "undefined" || !document.cookie) return ""
  for (const part of document.cookie.split(";")) {
    const [name, ...rest] = part.trim().split("=")
    if (name === CSRF_COOKIE_NAME) return decodeURIComponent(rest.join("="))
  }
  return ""
}

/**
 * The absolute URL of an API path.
 *
 * Used for the links the browser follows directly (a DOCX download, an
 * evidence screenshot) rather than for a `fetch`.
 */
export function apiUrl(path: string): string {
  return `${API_BASE_URL}${path}`
}

function buildUrl(path: string, query?: RequestOptions["query"]): string {
  const url = `${API_BASE_URL}${path}`
  if (!query) return url
  const params = new URLSearchParams()
  for (const [key, value] of Object.entries(query)) {
    if (value === undefined || value === null || value === "") continue
    if (Array.isArray(value)) {
      for (const item of value) params.append(key, item)
    } else {
      params.append(key, String(value))
    }
  }
  const queryString = params.toString()
  return queryString ? `${url}?${queryString}` : url
}

function parseRetryAfter(response: Response): number | null {
  const raw = response.headers.get("Retry-After")
  if (!raw) return null
  const seconds = Number.parseInt(raw, 10)
  if (Number.isFinite(seconds) && seconds >= 0) return seconds
  return null
}

function isValidationIssue(value: unknown): value is ApiValidationIssue {
  return (
    typeof value === "object" &&
    value !== null &&
    "msg" in value &&
    typeof (value as { msg: unknown }).msg === "string"
  )
}

/** Turn a FastAPI error body into one readable sentence. */
function readDetail(
  status: number,
  body: unknown
): {
  detail: string
  issues: ApiValidationIssue[]
} {
  if (typeof body === "object" && body !== null && "detail" in body) {
    const detail = (body as { detail: unknown }).detail
    if (typeof detail === "string" && detail.trim()) {
      return { detail: detail.trim(), issues: [] }
    }
    if (
      Array.isArray(detail) &&
      detail.length > 0 &&
      detail.every(isValidationIssue)
    ) {
      const issues = detail as ApiValidationIssue[]
      const sentences = issues.map((issue) => {
        const where = issue.loc.join(" → ")
        return where ? `${where}: ${issue.msg}` : issue.msg
      })
      return { detail: sentences.join("; "), issues }
    }
  }
  if (typeof body === "string" && body.trim()) {
    return { detail: body.trim(), issues: [] }
  }
  return { detail: defaultDetailForStatus(status), issues: [] }
}

/** The honest fallback when the server sent no usable detail. */
export function defaultDetailForStatus(status: number): string {
  switch (status) {
    case 400:
      return "The server refused the request."
    case 403:
      return "The server refused the request: the policy does not allow it."
    case 404:
      return "Not found."
    case 409:
      return "The record has already moved on, so this change conflicts with its state."
    case 413:
      return "The request is larger than the server's body limit."
    case 422:
      return "The request did not pass validation."
    case 429:
      return "Too many requests. The server asked the caller to slow down."
    case 500:
      return "The server failed to handle the request."
    case 503:
      return "The server is busy and refused the request."
    default:
      return `The server answered with HTTP ${status}.`
  }
}

/**
 * Perform one API request.
 *
 * @throws {ApiError} when the server answered with a non-2xx status.
 * @throws {NetworkError} when the request never reached the server.
 * @throws {TimeoutError} when the client-side timeout elapsed.
 * @throws {AbortedError} when the caller aborted the request.
 */
export async function request<T>(
  path: string,
  options: RequestOptions = {}
): Promise<T> {
  const {
    method = "GET",
    json,
    formData,
    signal,
    timeoutMs = DEFAULT_TIMEOUT_MS,
    query,
  } = options

  const controller = new AbortController()
  let timedOut = false
  const timer = setTimeout(() => {
    timedOut = true
    controller.abort()
  }, timeoutMs)

  const onExternalAbort = () => controller.abort()
  if (signal) {
    if (signal.aborted) {
      clearTimeout(timer)
      throw new AbortedError()
    }
    signal.addEventListener("abort", onExternalAbort, { once: true })
  }

  const headers: Record<string, string> = { Accept: "application/json" }
  let body: BodyInit | undefined
  if (formData) {
    // The browser must set the multipart boundary itself.
    body = formData
  } else if (json !== undefined) {
    headers["Content-Type"] = "application/json"
    body = JSON.stringify(json)
  }
  const csrf = csrfToken()
  if (csrf && method !== "GET" && method !== "HEAD") {
    headers["X-CSRF-Token"] = csrf
  }

  let response: Response
  try {
    response = await fetch(buildUrl(path, query), {
      method,
      headers,
      body,
      signal: controller.signal,
      // The session lives in an HttpOnly cookie that the browser attaches
      // on its own. The console never holds a token: a token in
      // JavaScript is readable by any script that gets injected, and an
      // HttpOnly cookie is not.
      credentials: "include",
    })
  } catch (error) {
    if (timedOut) throw new TimeoutError(timeoutMs)
    if (signal?.aborted) throw new AbortedError()
    throw new NetworkError(
      error instanceof Error && error.message
        ? `The API is unreachable: ${error.message}`
        : "The API is unreachable."
    )
  } finally {
    clearTimeout(timer)
    signal?.removeEventListener("abort", onExternalAbort)
  }

  const rawText = await response.text()
  let parsed: unknown = undefined
  if (rawText) {
    try {
      parsed = JSON.parse(rawText)
    } catch {
      parsed = rawText
    }
  }

  if (!response.ok) {
    const { detail, issues } = readDetail(response.status, parsed)
    throw new ApiError({
      status: response.status,
      detail,
      issues,
      retryAfterSeconds: parseRetryAfter(response),
      body: parsed,
    })
  }

  return parsed as T
}
