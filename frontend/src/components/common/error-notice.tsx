import { cn } from "cn"

import { ApiError, AbortedError, NetworkError, TimeoutError } from "@/lib/api/client"
import { describeError } from "@/lib/errors"

import { Banner } from "./banner"

/**
 * The one place a failure is shown.
 *
 * The copy comes from :mod:`@/lib/errors`, which turns a transport failure
 * into a sentence a person can act on: a refused **login** says the email and
 * password don't match, an expired **session** asks for a sign-in, a busy
 * **server** asks for a moment. A server detail that is already written for a
 * human is kept as it is, so the specific messages the backend takes care
 * over ("Host 'example.com' is not on the domain allowlist") survive.
 *
 * `verbose` is the administrator's view: the raw status and the server's own
 * words are shown alongside the sentence. The administration screens pass it;
 * every other screen — including this one on the sign-in form — stays in the
 * product's voice.
 */
export function ErrorNotice({
  error,
  onRetry,
  className,
  verbose = false,
}: {
  error: unknown
  onRetry?: () => void
  className?: string
  /** Show the HTTP status and the server's raw detail (administrators). */
  verbose?: boolean
}) {
  if (!error) return null

  const described = describeError(error)
  const status = error instanceof ApiError ? error.status : null
  const title =
    verbose && status !== null
      ? `${described.title} (HTTP ${status})`
      : described.title

  return (
    <Banner tone={toneFor(error)} title={title} className={className}>
      <p>{described.message}</p>
      {verbose && described.technical ? (
        <p className="mt-1 font-mono text-xs break-words opacity-80">
          {described.technical}
        </p>
      ) : null}
      {described.details.length > 0 ? (
        <ul className="mt-1 list-disc pl-5">
          {described.details.map((detail, index) => (
            <li key={`${detail}-${index}`}>{detail}</li>
          ))}
        </ul>
      ) : null}
      {onRetry ? (
        <button
          type="button"
          onClick={onRetry}
          className="mt-2 text-sm font-medium underline underline-offset-4"
        >
          Try again
        </button>
      ) : null}
    </Banner>
  )
}

function toneFor(error: unknown): "neutral" | "warning" | "danger" {
  if (error instanceof AbortedError) return "neutral"
  if (error instanceof TimeoutError) return "warning"
  if (error instanceof NetworkError) return "danger"
  if (error instanceof ApiError) return error.status >= 500 ? "danger" : "warning"
  return "danger"
}

/** The same copy, in a compact form for an inline panel. */
export function ErrorText({
  error,
  verbose = false,
}: {
  error: unknown
  verbose?: boolean
}) {
  const described = describeError(error)
  return (
    <span className={cn("text-sm")}>
      {verbose ? (described.technical ?? described.message) : described.message}
    </span>
  )
}