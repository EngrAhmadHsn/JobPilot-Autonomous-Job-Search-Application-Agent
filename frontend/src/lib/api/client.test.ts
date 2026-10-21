import { http, HttpResponse } from "msw"
import { describe, expect, it } from "vitest"

import { server } from "@/test/server"

import {
  AbortedError,
  ApiError,
  NetworkError,
  TimeoutError,
  request,
} from "@/lib/api/client"

const BASE = "http://api.test"

describe("the API client", () => {
  it("returns the parsed body of a successful response", async () => {
    server.use(
      http.get(`${BASE}/api/thing`, () =>
        HttpResponse.json({ ok: true, value: 42 })
      )
    )

    const result = await request<{ ok: boolean; value: number }>("/api/thing")

    expect(result).toEqual({ ok: true, value: 42 })
  })

  it("turns a 400 into an ApiError carrying the server's detail", async () => {
    server.use(
      http.get(`${BASE}/api/thing`, () =>
        HttpResponse.json(
          { detail: "The file extension is not allowed." },
          { status: 400 }
        )
      )
    )

    await expect(request("/api/thing")).rejects.toBeInstanceOf(ApiError)
    await expect(request("/api/thing")).rejects.toMatchObject({
      status: 400,
      detail: "The file extension is not allowed.",
    })
  })

  it("turns a 422 into an ApiError with the validation issues", async () => {
    server.use(
      http.post(`${BASE}/api/thing`, () =>
        HttpResponse.json(
          {
            detail: [
              {
                loc: ["body", "top_n"],
                msg: "Input should be greater than or equal to 1",
                type: "greater_than_equal",
              },
            ],
          },
          { status: 422 }
        )
      )
    )

    try {
      await request("/api/thing", { method: "POST", json: { top_n: 0 } })
      expect.unreachable("the request should have failed")
    } catch (error) {
      expect(error).toBeInstanceOf(ApiError)
      const apiError = error as ApiError
      expect(apiError.status).toBe(422)
      expect(apiError.issues).toHaveLength(1)
      expect(apiError.issues[0]?.msg).toContain("greater than or equal to 1")
      expect(apiError.detail).toContain("body → top_n")
    }
  })

  it("reads Retry-After from a 429 and never treats it as retryable", async () => {
    server.use(
      http.get(`${BASE}/api/thing`, () =>
        HttpResponse.json(
          { detail: "Too many requests." },
          { status: 429, headers: { "Retry-After": "7" } }
        )
      )
    )

    try {
      await request("/api/thing")
      expect.unreachable("the request should have failed")
    } catch (error) {
      const apiError = error as ApiError
      expect(apiError.status).toBe(429)
      expect(apiError.retryAfterSeconds).toBe(7)
      expect(apiError.isRetryable).toBe(false)
    }
  })

  it("reports a 503 with the server's own message", async () => {
    server.use(
      http.get(`${BASE}/api/thing`, () =>
        HttpResponse.json(
          { detail: "Server busy. Please retry shortly." },
          { status: 503 }
        )
      )
    )

    await expect(request("/api/thing")).rejects.toMatchObject({
      status: 503,
      detail: "Server busy. Please retry shortly.",
    })
  })

  it("reports a dead network as a NetworkError, not an ApiError", async () => {
    server.use(http.get(`${BASE}/api/thing`, () => HttpResponse.error()))

    const error = await request("/api/thing").catch((caught: unknown) => caught)

    expect(error).toBeInstanceOf(NetworkError)
    expect(error).not.toBeInstanceOf(ApiError)
  })

  it("gives up on a slow response and says so", async () => {
    server.use(
      http.get(`${BASE}/api/thing`, async () => {
        await new Promise((resolve) => setTimeout(resolve, 200))
        return HttpResponse.json({ ok: true })
      })
    )

    const error = await request("/api/thing", { timeoutMs: 20 }).catch(
      (caught: unknown) => caught
    )

    expect(error).toBeInstanceOf(TimeoutError)
  })

  it("reports the caller's cancellation as an AbortedError", async () => {
    server.use(
      http.get(`${BASE}/api/thing`, async () => {
        await new Promise((resolve) => setTimeout(resolve, 200))
        return HttpResponse.json({ ok: true })
      })
    )

    const controller = new AbortController()
    const pending = request("/api/thing", { signal: controller.signal }).catch(
      (caught: unknown) => caught
    )
    controller.abort()

    expect(await pending).toBeInstanceOf(AbortedError)
  })

  it("sends no cookie and asks for JSON", async () => {
    let seenCookie: string | null = null
    let seenAccept: string | null = null
    server.use(
      http.get(`${BASE}/api/thing`, ({ request }) => {
        seenCookie = request.headers.get("cookie")
        seenAccept = request.headers.get("Accept")
        return HttpResponse.json({ ok: true })
      })
    )

    await request("/api/thing")

    // The API has no authentication and must never receive a cookie: the
    // console holds no credential of any kind.
    expect(seenCookie).toBeNull()
    expect(seenAccept).toContain("application/json")
  })
})
