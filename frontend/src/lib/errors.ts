import {
  AbortedError,
  ApiError,
  NetworkError,
  ResponseTooLargeError,
  TimeoutError,
} from "@/lib/api/client"

/**
 * The console's error copy.
 *
 * **Who this is for.** Every failure the console can produce is read by a
 * person who is not an HTTP client: an operator whose password changed, a
 * candidate whose upload was rejected, someone whose session expired
 * overnight. `HTTP 400 · LOGIN_BAD_CREDENTIALS` is not an answer to "why
 * can't I sign in" — the code is fastapi-users' taxonomy, not the product's
 * language.
 *
 * **What it keeps.** A server detail that is already a sentence is kept
 * verbatim: the backend writes those for a human ("Host 'example.com' is not
 * on the domain allowlist", "The daily embedding budget is spent"). Only
 * machine answers are translated — bare error codes, framework phrases like
 * `Not Found`, and an empty body — and the translation is chosen by status
 * and by the known account codes.
 *
 * **What an administrator gets.** The raw status and the server's own words
 * travel in `technical`, and the administration screens render it (they pass
 * `verbose` to the notice). Debugging an admin panel is exactly where the
 * code matters; a sign-in form is where it does not.
 */

/** One decided message: a headline, a sentence, and the raw answer. */
export interface FriendlyError {
  title: string
  message: string
  /** The status and the server's own words, for an administrator or a log. */
  technical: string | null
  /** Field-level problems, with the transport noise removed. */
  details: string[]
}

/**
 * The identity stack's error codes, in the product's own voice.
 *
 * `fastapi-users` answers a login failure with `LOGIN_BAD_CREDENTIALS` and a
 * registration failure with `REGISTER_USER_ALREADY_EXISTS`; the console is
 * the only place those codes would otherwise reach a person.
 */
const ACCOUNT_ERRORS: Record<string, { title: string; message: string }> = {
  LOGIN_BAD_CREDENTIALS: {
    title: "We couldn't sign you in",
    message:
      "That email and password don't match an account here. Check them and try again.",
  },
  LOGIN_USER_NOT_VERIFIED: {
    title: "Verify your email first",
    message:
      "This account's email address hasn't been verified yet. Open the verification link we sent, then sign in.",
  },
  REGISTER_USER_ALREADY_EXISTS: {
    title: "That account already exists",
    message:
      "An account with that email already exists. Sign in instead, or reset the password.",
  },
  REGISTER_INVALID_PASSWORD: {
    title: "Choose a different password",
    message: "That password doesn't meet the account's requirements.",
  },
  RESET_PASSWORD_BAD_TOKEN: {
    title: "That link has expired",
    message:
      "The password-reset link is invalid or has expired. Request a new one.",
  },
  RESET_PASSWORD_INVALID_PASSWORD: {
    title: "Choose a different password",
    message: "That password doesn't meet the account's requirements.",
  },
  VERIFY_USER_BAD_TOKEN: {
    title: "That link has expired",
    message:
      "The verification link is invalid or has expired. Request a new one.",
  },
  VERIFY_USER_ALREADY_VERIFIED: {
    title: "This email is already verified",
    message: "This account's email address is already verified. Sign in.",
  },
  UPDATE_USER_EMAIL_ALREADY_EXISTS: {
    title: "That email is taken",
    message: "Another account already uses that email address.",
  },
  UPDATE_USER_INVALID_PASSWORD: {
    title: "That password wasn't accepted",
    message: "Check the password and try again.",
  },
}

/** Headlines and fallbacks by status, when the server said nothing useful. */
const STATUS_COPY: Record<
  number,
  { title: string; message: string }
> = {
  400: {
    title: "That didn't go through",
    message:
      "The server couldn't accept that request. Check the details and try again.",
  },
  401: {
    title: "Your session has ended",
    message: "Sign in again to continue.",
  },
  403: {
    title: "Not available for this account",
    message: "This account doesn't have access to that.",
  },
  404: {
    title: "Not found",
    message:
      "We couldn't find what you asked for. It may have been removed, or the link may be wrong.",
  },
  409: {
    title: "That conflicts with the current state",
    message: "Something changed while you were working. Reload and try again.",
  },
  413: {
    title: "That file is too large",
    message: "The file is larger than the server accepts. Try a smaller one.",
  },
  422: {
    title: "Some details weren't accepted",
    message: "Check the highlighted fields and try again.",
  },
  429: {
    title: "Too many requests",
    message: "The server asked us to slow down.",
  },
}

/** The framework's own phrases: English, but not written for a person. */
const FRAMEWORK_PHRASES = new Set([
  "Not Found",
  "Unauthorized",
  "Forbidden",
  "Bad Request",
  "Internal Server Error",
  "Method Not Allowed",
  "Unprocessable Entity",
  "Service Unavailable",
  "Gateway Timeout",
])

/** A bare machine code: `LOGIN_BAD_CREDENTIALS`, `NOT_A_SENTENCE`. */
const CODE_LIKE = /^[A-Z][A-Z0-9_]*$/

function copyForStatus(status: number): { title: string; message: string } {
  const known = STATUS_COPY[status]
  if (known) return known
  if (status >= 500) {
    return {
      title: "The server had a problem",
      message: "That request failed on the server. Try again in a moment.",
    }
  }
  return {
    title: "The server refused that request",
    message: "It did not explain why. Try again, and tell an administrator if it keeps happening.",
  }
}

/** Field-level issues, without the transport's own path segments. */
function friendlyIssues(issues: ApiError["issues"]): string[] {
  return issues.map((issue) => {
    const where = issue.loc
      .filter((part) => !["body", "query", "path"].includes(String(part)))
      .join(" → ")
    return where ? `${where}: ${issue.msg}` : issue.msg
  })
}

/** The account code in a detail, when there is one. */
function accountErrorFor(detail: string) {
  const code = Object.keys(ACCOUNT_ERRORS).find((key) => detail.includes(key))
  return code ? ACCOUNT_ERRORS[code] : null
}

/**
 * The one decision: what a person is told, and what the administrator can
 * still see.
 */
export function describeError(error: unknown): FriendlyError {
  if (error instanceof AbortedError) {
    return {
      title: "Cancelled",
      message: "The request was cancelled before the server answered.",
      technical: null,
      details: [],
    }
  }

  if (error instanceof TimeoutError) {
    return {
      title: "The request timed out",
      message: `The console stopped waiting after ${Math.round(
        error.timeoutMs / 1000
      )} seconds. The work may still be finishing on the server — check the server log before trying again.`,
      technical: `timeout after ${error.timeoutMs} ms`,
      details: [],
    }
  }

  if (error instanceof NetworkError) {
    return {
      title: "Can't reach the server",
      message:
        "The request never arrived. Check your connection — and if you run the console locally, that the API is running.",
      technical: error.message,
      details: [],
    }
  }

  if (error instanceof ResponseTooLargeError) {
    return {
      title: "The answer was too large to read",
      message:
        "The server sent more data than the console will load in one response. Try the request again, or narrow it down.",
      technical: error.message,
      details: [],
    }
  }

  if (error instanceof ApiError) {
    const technical = `HTTP ${error.status} · ${error.detail}`
    const details = friendlyIssues(error.issues)
    const account = accountErrorFor(error.detail)

    // A known account code is the most specific answer available.
    if (account) {
      return { ...account, technical, details }
    }

    const detail = error.detail.trim()
    const isSentence =
      detail.length > 0 &&
      !CODE_LIKE.test(detail) &&
      !FRAMEWORK_PHRASES.has(detail)

    // Rate limiting: the server's own sentence (if it wrote one) plus the
    // wait it asked for. "Too many requests." alone leaves the caller
    // without the one number that makes it actionable.
    if (error.status === 429) {
      const base = isSentence ? detail : copyForStatus(429).message
      return {
        title: copyForStatus(429).title,
        message:
          error.retryAfterSeconds !== null
            ? `${base} Try again in ${error.retryAfterSeconds} second${
                error.retryAfterSeconds === 1 ? "" : "s"
              }.`
            : `${base} Try again in a few seconds.`,
        technical,
        details,
      }
    }

    // A structured validation answer: the field list under the sentence is
    // the useful part, not the framework's "did not pass validation".
    if (error.status === 422 && details.length > 0) {
      return { ...copyForStatus(422), technical, details }
    }

    // A detail the backend wrote for a human is kept as it is.
    if (isSentence) {
      return {
        title: copyForStatus(error.status).title,
        message: detail,
        technical,
        details,
      }
    }

    return { ...copyForStatus(error.status), technical, details }
  }

  return {
    title: "Something went wrong",
    message:
      error instanceof Error
        ? error.message
        : "The console hit an unexpected error.",
    technical: error instanceof Error ? (error.stack ?? error.message) : null,
    details: [],
  }
}