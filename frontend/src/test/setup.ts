import "@testing-library/jest-dom/vitest"

import { configure, cleanup } from "@testing-library/react"
import { afterAll, afterEach, beforeAll, vi } from "vitest"

import { setCurrentProfileId } from "@/lib/profile"

import { server, resetStore } from "./server"

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

/*
  Every console route is a lazy chunk, so the first query in a screen has to
  wait for the chunk to load *and* for the mocked call to answer. The default
  one-second `asyncUtilTimeout` measures the chunk fetch, which is fine on an
  idle machine and is not fine under the whole suite's parallel load — the
  approvals tests failed intermittently at ~2.5 s for exactly this reason,
  and they failed identically on a pristine tree, so the flake was in the
  wait, not in the screen.

  Raised here, once, rather than at each call site: the timing belongs to the
  test environment, and a per-call `timeout:` is the same number copied into
  every lazy-route test that will ever be written. A test that *should* fail
  fast still fails — three seconds is a bound, not a wait.
*/
configure({ asyncUtilTimeout: 3_000 })

afterEach(() => {
  cleanup()
  server.resetHandlers()
  // The mock's stateful stores (the application profile persists PUTs) must
  // not leak between tests.
  resetStore()
  window.localStorage.clear()
  // The current profile lives in a module-level store; it has to be reset
  // explicitly, or a test would inherit the previous test's profile.
  setCurrentProfileId(null)
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

/*
  WS-48's @animate-ui primitives animate with the Web Animations API and
  branch on `SVGGeometryElement` — neither of which jsdom implements, so
  every menu the account drawer opens (any popup whose rows stagger) threw
  `row.animate is not a function` / `SVGGeometryElement is not defined`
  from inside the primitives on a pristine tree. The animation is the
  primitives' own polish — rows sliding in, indicators popping — and is
  never what a test asserts, so the stubs answer "already finished" and let
  the components run their real logic. Same family as the shims above: the
  environment catches up to what the console (now) uses.
*/
if (!Element.prototype.animate) {
  Element.prototype.animate = (() => ({
    finished: Promise.resolve(),
    currentTime: 0,
    startTime: null,
    playState: "finished",
    id: null,
    effect: null,
    cancel: () => {},
    finish: () => {},
    pause: () => {},
    play: () => {},
  })) as unknown as typeof Element.prototype.animate
}
if (!Element.prototype.getAnimations) {
  Element.prototype.getAnimations = () => []
}
if (typeof window.SVGGeometryElement === "undefined") {
  // Only used for an `instanceof` branch (stroke-draw vs fade): a bare
  // class answers "no" for every jsdom element, so indicators fade —
  // which is all a jsdom test can observe anyway.
  window.SVGGeometryElement =
    class SVGGeometryElement {} as unknown as typeof SVGGeometryElement
}
if (typeof window.ResizeObserver === "undefined") {
  // The primitives' sliding indicator observes its tab list to re-measure
  // the underline; jsdom has no observer and no layout to observe, so the
  // no-op one is exactly as informative as the real thing would be here.
  window.ResizeObserver = class ResizeObserver {
    observe() {}
    unobserve() {}
    disconnect() {}
  } as unknown as typeof ResizeObserver
}
