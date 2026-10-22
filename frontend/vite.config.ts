import { resolve } from "node:path"

import tailwindcss from "@tailwindcss/vite"
import react from "@vitejs/plugin-react"
import { loadEnv } from "vite"
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

/**
 * The Content-Security-Policy (WS-15).
 *
 * The API already sets `nosniff`, `X-Frame-Options` and `Referrer-Policy`
 * on its own responses, but the console's **own** document — the HTML, the
 * JavaScript, the stylesheet — was served with no policy at all. The
 * console is the surface that holds the "Approve and submit" button and
 * that renders attacker-influenced job-board text, so it is the surface
 * where a policy earns its keep.
 *
 * Two variants, and the difference is the dev server's fault:
 *
 * - **The build** gets the strict policy. Vite's production build emits
 *   no inline script (the modulepreload polyfill is not injected any
 *   more), so `script-src 'self'` holds with no exception.
 * - **The dev server** needs `'unsafe-inline'`, because the React
 *   Fast Refresh runtime is an inline module script. That is a
 *   development-only concession; the built bundle is what ships.
 *
 * `style-src` keeps `'unsafe-inline'` in both, because React writes
 * inline styles (the score panel's width). A style attribute cannot
 * execute script, so the concession is about layout, not execution.
 */
function contentSecurityPolicy(
  apiBaseUrl: string,
  { development }: { development: boolean }
): string {
  const connect = new Set(["'self'"])
  if (apiBaseUrl) {
    try {
      connect.add(new URL(apiBaseUrl).origin)
    } catch {
      // A malformed base URL is a configuration error, not a reason to
      // emit a policy that blocks every request. The API is then
      // unreachable, which the operator will see immediately.
    }
  }
  if (development) {
    // The HMR client opens a WebSocket, and the dev proxy may point at
    // the API on another port.
    connect.add("ws:")
    connect.add("wss:")
    connect.add(API_TARGET)
  }
  const scriptSrc = development
    ? "'self' 'unsafe-inline' 'unsafe-eval'"
    : "'self'"
  return [
    "default-src 'self'",
    `script-src ${scriptSrc}`,
    "style-src 'self' 'unsafe-inline'",
    "img-src 'self' data: blob:",
    "font-src 'self' data:",
    `connect-src ${[...connect].join(" ")}`,
    "object-src 'none'",
    "base-uri 'none'",
    "form-action 'self'",
    "frame-ancestors 'none'",
  ].join("; ")
}

/** The headers that go with the policy, whatever the transport. */
const SECURITY_HEADERS = {
  "X-Content-Type-Options": "nosniff",
  "X-Frame-Options": "DENY",
  "Referrer-Policy": "no-referrer",
  "Cross-Origin-Opener-Policy": "same-origin",
  "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
} as const

/**
 * Injects the policy into the built `index.html`.
 *
 * A static host that sets no headers still gets the policy, because the
 * policy is in the document. A host that *does* set the header gets the
 * same policy twice, which is harmless — the browser applies the
 * intersection.
 */
function contentSecurityPolicyPlugin(policy: string) {
  return {
    name: "aja-content-security-policy",
    apply: "build" as const,
    transformIndexHtml(html: string) {
      return {
        html,
        tags: [
          {
            tag: "meta",
            attrs: {
              "http-equiv": "Content-Security-Policy",
              content: policy,
            },
            injectTo: "head-prepend" as const,
          },
        ],
      }
    },
  }
}

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), "")
  const apiBaseUrl = env.VITE_API_BASE_URL ?? ""
  const productionPolicy = contentSecurityPolicy(apiBaseUrl, {
    development: false,
  })
  const developmentPolicy = contentSecurityPolicy(apiBaseUrl, {
    development: true,
  })

  return {
    plugins: [
      react(),
      tailwindcss(),
      contentSecurityPolicyPlugin(productionPolicy),
    ],
    resolve: {
      alias: {
        "@": resolve(import.meta.dirname, "./src"),
      },
    },
    server: {
      port: 5173,
      headers: {
        ...SECURITY_HEADERS,
        "Content-Security-Policy": developmentPolicy,
      },
      proxy: {
        "/api": {
          target: API_TARGET,
          changeOrigin: false,
        },
      },
    },
    // The preview server (the built app) proxies the API exactly like the dev
    // server does, so the end-to-end run can test the **production bundle**
    // rather than a dev server that reloads under you. It serves the built
    // app, so it gets the strict policy.
    preview: {
      port: 4173,
      headers: {
        ...SECURITY_HEADERS,
        "Content-Security-Policy": productionPolicy,
      },
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
  }
})
