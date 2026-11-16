import { createHash } from "node:crypto"
import { readFileSync } from "node:fs"
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
 * - **The build** gets the strict policy. Vite's production build emits no
 *   module script inline, so `script-src 'self'` holds — plus one hash, for
 *   the single inline script the document carries (see below).
 * - **The dev server** needs `'unsafe-inline'`, because the React Fast Refresh
 *   runtime is an inline module script. That is a development-only concession;
 *   the built bundle is what ships.
 *
 * **The one inline script: the pre-paint theme.**
 *
 * `index.html` runs a few lines before the first paint to set the theme class,
 * so a visitor who chose dark never sees the light canvas flash. In a strict
 * policy that is blocked unless the policy allows it. `'unsafe-inline'` would
 * be the wrong answer, because it would allow *every* inline script. Instead
 * the policy carries a SHA-256 hash of that exact script, computed from the
 * HTML the build actually emitted, so:
 *
 * - the script runs;
 * - any other inline script the page might ever gain does not;
 * - and editing the script cannot silently break it, because the hash is
 *   derived from the emitted markup rather than hard-coded.
 *
 * `'unsafe-hashes'` is not needed: the hash covers the whole `<script>`
 * element, not an event-handler attribute.
 *
 * `style-src` keeps `'unsafe-inline'` in both, because React writes inline
 * styles (the score panel's width). A style attribute cannot execute script, so
 * the concession is about layout, not execution.
 */
function contentSecurityPolicy(
  apiBaseUrl: string,
  {
    development,
    meta = false,
    scriptHashes = [],
  }: {
    development: boolean
    meta?: boolean
    /** SHA-256 hashes of the inline scripts the document is allowed to run. */
    scriptHashes?: string[]
  }
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
    : ["'self'", ...scriptHashes].join(" ")
  const directives = [
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
  ]
  /*
    A `<meta>`-delivered policy cannot carry every directive. `frame-ancestors`
    — with `report-uri` and `sandbox` — is defined only for a policy delivered
    in a **header**; in a `<meta>` tag the browser ignores that one directive
    and logs an error on every load (which is what this console was doing).
    So the meta policy omits it instead of asking for something it cannot
    have, and the framing defence rides on the header — the dev and preview
    servers set one, and `X-Frame-Options: DENY` above covers a host that
    sets headers at all. A host that sets none gets the rest of the policy
    from the document, but framing protection is a header's job and cannot be
    faked in the markup.
  */
  const META_IGNORED = ["frame-ancestors"]
  const emitted = meta
    ? directives.filter(
        (directive) => !META_IGNORED.some((name) => directive.startsWith(name))
      )
    : directives
  return emitted.join("; ")
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
 * policy is in the document — minus the directives a `<meta>` policy cannot
 * carry (see `contentSecurityPolicy`). A host that *does* set the header gets
 * the full policy as well, which is harmless — the browser applies the
 * intersection.
 *
 * The hash is computed here, from the HTML Vite actually emitted, rather than
 * from the source `index.html`. That is deliberate: a build-time transform
 * could rewrite the script body, and a hard-coded hash would then block it.
 * Hashing the output means the policy always matches what ships.
 */
function contentSecurityPolicyPlugin(
  buildPolicy: (scriptHashes: string[]) => string
) {
  return {
    name: "aja-content-security-policy",
    apply: "build" as const,
    transformIndexHtml(html: string) {
      /*
        Every inline `<script>` in the emitted document, hashed. The build
        emits exactly one (the theme bootstrap); the regex is written to find
        all of them so a second one added later is allowed only if the policy
        is regenerated, rather than silently breaking the page.
      */
      const inlineScripts = [
        ...html.matchAll(/<script(?![^>]*\bsrc=)[^>]*>([\s\S]*?)<\/script>/gi),
      ].map((match) => match[1] ?? "")
      const scriptHashes = inlineScripts
        .filter((body) => body.trim().length > 0)
        .map(
          (body) =>
            `'sha256-${createHash("sha256").update(body, "utf8").digest("base64")}'`
        )

      return {
        html,
        tags: [
          {
            tag: "meta",
            attrs: {
              "http-equiv": "Content-Security-Policy",
              content: buildPolicy(scriptHashes),
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
  // The **header** policies carry the full directive set, including
  // `frame-ancestors`, which a `<meta>` policy cannot express. The meta policy
  // is built per document by `contentSecurityPolicyPlugin`, because its
  // `script-src` needs the hash of the inline theme script.
  const developmentPolicy = contentSecurityPolicy(apiBaseUrl, {
    development: true,
  })

  /*
    The theme script is inline in `index.html`, so the preview server's
    **header** policy has to allow that one script too — otherwise the header
    and the meta tag disagree, the browser applies the intersection, and the
    script is blocked. Reading the source document here is correct for the
    header case: Vite copies `index.html` verbatim except for injected tags, so
    the script body a preview serves is the one on disk. The meta policy is
    still hashed from the emitted output, which is the one that must track any
    build-time rewrite.
  */
  const sourceHtml = readFileSync(
    resolve(import.meta.dirname, "index.html"),
    "utf8"
  )
  const themeScriptHashes = [
    ...sourceHtml.matchAll(
      /<script(?![^>]*\bsrc=)[^>]*>([\s\S]*?)<\/script>/gi
    ),
  ]
    .map((match) => match[1] ?? "")
    .filter((body) => body.trim().length > 0)
    .map(
      (body) =>
        `'sha256-${createHash("sha256").update(body, "utf8").digest("base64")}'`
    )
  const productionHeaderPolicy = contentSecurityPolicy(apiBaseUrl, {
    development: false,
    scriptHashes: themeScriptHashes,
  })

  return {
    plugins: [
      react(),
      tailwindcss(),
      // The meta policy is rebuilt per document, because its `script-src`
      // carries a hash computed from the emitted inline scripts.
      contentSecurityPolicyPlugin((scriptHashes) =>
        contentSecurityPolicy(apiBaseUrl, {
          development: false,
          meta: true,
          scriptHashes,
        })
      ),
    ],
    build: {
      /*
        The vendors are their own chunk.

        Every route is lazy now, so the framework and the router are the only
        code every page needs. Splitting them means they are fetched once, cached
        across a deploy, and never re-downloaded when a screen changes — and it
        keeps the router's own code out of the chunk that changes most often.
      */
      rolldownOptions: {
        output: {
          advancedChunks: {
            groups: [
              {
                name: "vendor",
                test: /node_modules[\\/](react|react-dom|react-router|react-router-dom|@tanstack|scheduler)[\\/]/,
              },
            ],
          },
        },
      },
    },
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
        "Content-Security-Policy": productionHeaderPolicy,
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
