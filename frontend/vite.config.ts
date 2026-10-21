import { resolve } from "node:path"

import tailwindcss from "@tailwindcss/vite"
import react from "@vitejs/plugin-react"
import { defineConfig } from "vitest/config"

/**
 * The dev proxy is the default transport in development.
 *
 * The console talks to the API through the same origin (`/api/...`), and
 * Vite forwards those calls to the local FastAPI server. Two reasons:
 *
 * 1. The browser then makes no cross-origin request at all, so the CORS
 *    configuration is not load-bearing in development (it still matters for
 *    a deployment that serves the console from another origin).
 * 2. The rate limiter keys on the transport peer. Through the proxy every
 *    request arrives from the proxy, which is one bucket for the whole
 *    machine — the operator sees the 429 and its `Retry-After` instead of a
 *    stream of confusing per-browser refusals.
 *
 * `VITE_API_BASE_URL` overrides the whole thing: set it to an absolute URL
 * to talk to a remote API, leave it empty for the proxy.
 */
const API_TARGET = process.env.VITE_API_PROXY_TARGET ?? "http://127.0.0.1:8000"

export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: {
      "@": resolve(import.meta.dirname, "./src"),
    },
  },
  server: {
    port: 5173,
    proxy: {
      "/api": {
        target: API_TARGET,
        changeOrigin: false,
      },
    },
  },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./src/test/setup.ts"],
    css: false,
    include: ["src/**/*.test.{ts,tsx}"],
    // The console's base URL is absolute in the tests, so that MSW sees a
    // real absolute URL (a relative one cannot be fetched by Node's fetch).
    env: {
      VITE_API_BASE_URL: "http://api.test",
    },
    coverage: {
      provider: "v8",
      reporter: ["text", "html"],
      include: ["src/**/*.{ts,tsx}"],
      exclude: [
        "src/**/*.test.{ts,tsx}",
        "src/test/**",
        "src/lib/api/schema.ts",
      ],
    },
  },
})
