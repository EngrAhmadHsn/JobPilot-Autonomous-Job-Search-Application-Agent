import "@testing-library/jest-dom/vitest"

import { cleanup } from "@testing-library/react"
import { afterAll, afterEach, beforeAll, vi } from "vitest"

import { server } from "./server"

/**
 * The test environment.
 *
 * The API is mocked at the **network** boundary (MSW), not by stubbing the
 * client module: the components then exercise the same `fetch` code path
 * they use in production, including the error handling and the timeouts.
 */
beforeAll(() => {
  server.listen({ onUnhandledFrame: "error" })
})

afterEach(() => {
  cleanup()
  server.resetHandlers()
  window.localStorage.clear()
})

afterAll(() => {
  server.close()
})

// jsdom does not implement these, and the console uses them.
if (!window.matchMedia) {
  window.matchMedia = ((query: string) => ({
    matches: false,
    media: query,
    onchange: null,
    addListener: vi.fn(),
    removeListener: vi.fn(),
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
    dispatchEvent: vi.fn(),
  })) as unknown as typeof window.matchMedia
}

if (!Element.prototype.scrollIntoView) {
  Element.prototype.scrollIntoView = vi.fn()
}
