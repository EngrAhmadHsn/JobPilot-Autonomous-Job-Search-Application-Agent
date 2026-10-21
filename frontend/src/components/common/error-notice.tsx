import { cn } from "cn"

import {
  ApiError,
  AbortedError,
  NetworkError,
  TimeoutError,
} from "@/lib/api/client"

import { Banner } from "./banner"

/**
 * The one place a failure is shown.
 *
 * Every failure the console can produce lands here, and each kind says
 * something different and true:
 *
 * - a **4xx** is the server refusing this request, and its `detail` is the
 *   reason;
 * - a **429** carries the `Retry-After` the server asked for, and the
 *   console says how long to wait;
 * - a **503** says the server is busy (or, for the tailoring route, that
 *   the model is unavailable);
 * - a **network failure** says the request never arrived;
 * - a **timeout** says the console gave up waiting, and that the server may
 *   still be working — which matters for the long calls.
 */
export function ErrorNotice({
  error,
  onRetry,
  className,
}: {
  error: unknown
  onRetry?: () => void
  className?: string
}) {
  if (!error) return null

  if (error instanceof AbortedError) {
    return (
      <Banner tone="neutral" title="Cancelled" className={className}>
        The request was cancelled before the server answered.
      </Banner>
    )
  }

  if (error instanceof TimeoutError) {
    return (
      <Banner
        tone="warning"
        title="The request timed out"
        className={className}
      >
        <p>
          The console stopped waiting after {Math.round(error.timeoutMs / 1000)}{" "}
          seconds. The server may still be working — check the server log before
          trying again.
        </p>
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

  if (error instanceof NetworkError) {
    return (
      <Banner
        tone="danger"
        title="The API is unreachable"
        className={className}
      >
        <p>
          The request never reached the server. Is the API running, and is the
          console pointed at the right base URL?
        </p>
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

  if (error instanceof ApiError) {
    const title = `The server refused the request (HTTP ${error.status})`
    return (
      <Banner
        tone={error.status >= 500 ? "danger" : "warning"}
        title={title}
        className={className}
      >
        <p>{error.detail}</p>
        {error.status === 429 ? (
          <p className="mt-1">
            {error.retryAfterSeconds !== null
              ? `The server asked the caller to wait ${error.retryAfterSeconds} second(s) before retrying.`
              : "The server did not say how long to wait; retry in a few seconds."}
          </p>
        ) : null}
        {error.issues.length > 0 ? (
          <ul className="mt-1 list-disc pl-5">
            {error.issues.map((issue) => (
              <li key={`${issue.loc.join(".")}-${issue.msg}`}>
                {issue.loc.length > 0 ? `${issue.loc.join(" → ")}: ` : ""}
                {issue.msg}
              </li>
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

  return (
    <Banner tone="danger" title="Something went wrong" className={className}>
      <p>
        {error instanceof Error
          ? error.message
          : "The console hit an unexpected error."}
      </p>
    </Banner>
  )
}

/** The same notice, in a compact form for an inline panel. */
export function ErrorText({ error }: { error: unknown }) {
  if (error instanceof ApiError)
    return <span className={cn("text-sm")}>{error.detail}</span>
  if (error instanceof Error)
    return <span className="text-sm">{error.message}</span>
  return <span className="text-sm">Something went wrong.</span>
}
