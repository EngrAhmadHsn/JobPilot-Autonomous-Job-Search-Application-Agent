import { describe, expect, it } from "vitest"

import {
  AbortedError,
  ApiError,
  NetworkError,
  TimeoutError,
} from "@/lib/api/client"
import { describeError } from "@/lib/errors"

/**
 * The console's error copy.
 *
 * The property under test: a person is never shown a machine's taxonomy —
 * `LOGIN_BAD_CREDENTIALS` is a fastapi-users code, not an answer — while a
 * message the backend wrote for a human survives untouched, and the raw
 * status plus the server's own words stay available for an administrator.
 */
function apiError(
  status: number,
  detail: string,
  extra: Partial<{ issues: ApiError["issues"]; retryAfterSeconds: number }> = {}
) {
  return new ApiError({ status, detail, ...extra })
}

describe("the friendly error copy", () => {
  it("turns a refused login into something a person can act on", () => {
    const described = describeError(apiError(400, "LOGIN_BAD_CREDENTIALS"))

    expect(described.title).toBe("We couldn't sign you in")
    expect(described.message).toMatch(/don't match an account here/i)
    expect(described.message).not.toContain("LOGIN_BAD_CREDENTIALS")
    // The raw answer is preserved for the administrator.
    expect(described.technical).toBe("HTTP 400 · LOGIN_BAD_CREDENTIALS")
  })

  it("recognises the code when the server wrapped it", () => {
    // The console's own mock once produced "400: LOGIN_BAD_CREDENTIALS"; a
    // proxy or a future SDK may wrap it too, so the code is matched inside
    // the detail rather than by exact equality.
    const described = describeError(apiError(400, "400: LOGIN_BAD_CREDENTIALS"))

    expect(described.title).toBe("We couldn't sign you in")
    expect(described.message).not.toContain("LOGIN_BAD_CREDENTIALS")
  })

  it("explains the other account codes", () => {
    expect(
      describeError(apiError(400, "REGISTER_USER_ALREADY_EXISTS")).title
    ).toBe("That account already exists")
    expect(
      describeError(apiError(400, "RESET_PASSWORD_BAD_TOKEN")).title
    ).toBe("That link has expired")
    expect(
      describeError(apiError(400, "LOGIN_USER_NOT_VERIFIED")).title
    ).toBe("Verify your email first")
  })

  it("keeps a detail the backend wrote for a human", () => {
    const detail = "Host 'example.com' is not on the domain allowlist"
    const described = describeError(apiError(400, detail))

    expect(described.message).toBe(detail)
    expect(described.title).toBe("That didn't go through")
  })

  it("keeps the specific long-running-operation messages", () => {
    const detail =
      "The background queue is at its run limit (25). Wait for the current work to finish, then retry."
    expect(describeError(apiError(503, detail)).message).toBe(detail)
    expect(describeError(apiError(503, "Server busy. Please retry shortly.")).message).toBe(
      "Server busy. Please retry shortly."
    )
  })

  it("replaces the framework's own phrases", () => {
    const described = describeError(apiError(404, "Not Found"))

    expect(described.message).toMatch(/couldn't find what you asked for/i)
    expect(described.message).not.toBe("Not Found")
    expect(describeError(apiError(401, "Unauthorized")).message).toMatch(
      /sign in again/i
    )
  })

  it("falls back by status when there is no detail at all", () => {
    expect(describeError(apiError(500, "")).title).toBe(
      "The server had a problem"
    )
    expect(describeError(apiError(404, "")).title).toBe("Not found")
    expect(describeError(apiError(409, "")).message).toMatch(/reload/i)
  })

  it("says how long a rate-limited caller should wait", () => {
    const described = describeError(
      apiError(429, "Too many requests.", { retryAfterSeconds: 30 })
    )

    expect(described.message).toMatch(/30 seconds/)
    expect(
      describeError(apiError(429, "Too many requests.", { retryAfterSeconds: 1 }))
        .message
    ).toMatch(/1 second\./)
    expect(describeError(apiError(429, "")).message).toMatch(/a few seconds/)
  })

  it("cleans the transport noise out of validation issues", () => {
    const described = describeError(
      apiError(422, "The request did not pass validation.", {
        issues: [
          {
            loc: ["body", "email"],
            msg: "value is not a valid email address",
            type: "value_error",
          },
        ],
      })
    )

    expect(described.details).toEqual([
      "email: value is not a valid email address",
    ])
    expect(described.message).toMatch(/highlighted fields/i)
  })

  it("speaks plainly for the transport failures too", () => {
    expect(describeError(new NetworkError()).title).toBe("Can't reach the server")
    expect(describeError(new TimeoutError(30_000)).message).toMatch(
      /stopped waiting after 30 seconds/
    )
    expect(describeError(new AbortedError()).title).toBe("Cancelled")
  })

  it("never returns an empty message", () => {
    for (const error of [
      apiError(400, ""),
      apiError(500, "Internal Server Error"),
      new NetworkError(),
      new TimeoutError(1000),
      new AbortedError(),
      new Error("boom"),
      "not an error at all",
      null,
    ]) {
      const described = describeError(error)
      expect(described.title.length).toBeGreaterThan(0)
      expect(described.message.length).toBeGreaterThan(0)
    }
  })
})