import { defineConfig, devices } from "@playwright/test"

/**
 * The end-to-end configuration.
 *
 * The smoke test drives the console against the **real** backend and the
 * local fake ATS — the same path an operator takes. The API has to be
 * running (`uvicorn src.main:app`) and the fake ATS has to be running
 * (`python scripts/serve_fake_ats.py`), because the approval step really
 * does fill a form and submit it.
 *
 * The console is served by the Vite dev server, which proxies `/api` to the
 * backend — the same transport the developer uses.
 */
/*
  The end-to-end run drives the **built** console, served by `vite preview`.

  A dev server reloads whenever a file changes — including when another
  session is editing the same repository — and a reload mid-test empties
  the form the test had just filled in. The production bundle has no such
  behaviour, and testing it is the more honest thing to test anyway.
*/
const CONSOLE_URL = process.env.E2E_BASE_URL ?? "http://localhost:4173"

export default defineConfig({
  testDir: "./e2e",
  // The tailoring call alone can take a minute, and the approval step drives
  // a real browser against the fake ATS.
  timeout: 240_000,
  expect: { timeout: 20_000 },
  fullyParallel: false,
  workers: 1,
  retries: 0,
  reporter: [["list"]],
  use: {
    baseURL: CONSOLE_URL,
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  projects: [
    {
      name: "chromium",
      use: { ...devices["Desktop Chrome"] },
    },
  ],
  webServer: {
    command: "npm run build && npm run preview",
    url: CONSOLE_URL,
    reuseExistingServer: !process.env.CI,
    timeout: 180_000,
  },
})
