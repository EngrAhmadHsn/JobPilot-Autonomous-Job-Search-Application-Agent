import type { Page } from "@playwright/test"

/**
 * The session helpers the e2e specs share.
 *
 * Both specs used to carry their own copy of `signIn`, and both copies
 * drifted from the console at the same two points — which is why they live
 * here now, once.
 */

/**
 * The account trigger, whichever chrome is holding it.
 *
 * The console ships **two** controls with this label by design: the top
 * bar's, and the rail's own footer (WS-43's expanded-navigation work gave
 * the rail its identity block back). Both are always in the DOM — the rail
 * one is hidden below 1024 — so a bare `getByRole` is a strict-mode
 * violation, and `.first()` would pick the rail's and then wait for a
 * hidden element on a phone viewport. Visible-first is the honest selector:
 * it is the trigger the visitor can actually reach.
 */
export function accountTrigger(page: Page) {
  return page
    .locator('button[aria-label="Account and display settings"]:visible')
    .first()
}

/**
 * Sign in, creating the account when it does not exist yet.
 *
 * A **fresh** account per run: a real account from a previous run would
 * carry a password this run does not know, so the run would fail on a
 * credential rather than on a defect.
 *
 * The signed-out signal is the sign-in **screen**, and the screen's heading
 * is its own copy: "Welcome back." for a returning candidate, "Create an
 * account" once the visitor asks for one (WS-33's copy rewrite). Asking for
 * a heading literally named "Sign in" matched nothing, so this helper used
 * to return believing a session existed — and the test then hung on the
 * first control of a screen it had never signed into.
 */
export async function signIn(
  page: Page,
  options: { prefix?: string; password?: string } = {}
) {
  const stamp = Date.now().toString(36)
  const email =
    process.env.E2E_ACCOUNT ??
    `${options.prefix ?? "operator"}-${stamp}@example.com`
  const password =
    process.env.E2E_PASSWORD ?? options.password ?? "a-long-enough-password"

  // The console renders itself for a moment before the identity check
  // answers, so the presence of a control proves nothing about whether the
  // session is good. The two real signals are an address in the account
  // trigger (signed in) and the sign-in screen (signed out). The helper
  // waits for one of them.
  const signedInAlready = await accountTrigger(page)
    .textContent()
    .then((text) => (text ?? "").includes("@"))
    .catch(() => false)
  if (signedInAlready) return

  const needsCredentials = await page
    .getByRole("heading", { name: /Welcome back\.|Create an account/ })
    .waitFor({ timeout: 20_000 })
    .then(() => true)
    .catch(() => false)
  if (!needsCredentials) return

  await page.getByLabel("Email").waitFor({ state: "visible", timeout: 15_000 })
  await page.getByLabel("Email").fill(email)
  await page.getByLabel("Password").fill(password)
  await page.getByRole("button", { name: "Sign in" }).click()

  // The console either signs in, or refuses the credentials because the
  // account does not exist yet. In the second case it creates it and signs
  // in again.
  const signedIn = await accountTrigger(page)
    .waitFor({ timeout: 30_000 })
    .then(() => true)
    .catch(() => false)
  if (signedIn) return

  await page.getByRole("button", { name: /No account yet/ }).click()
  await page.getByLabel("Email").fill(email)
  await page.getByLabel("Password").fill(password)
  await page.getByRole("button", { name: "Create the account" }).click()
  // Creating the account hashes the password with argon2, which takes
  // seconds when the machine is busy. The wait has to allow for that, or
  // the run fails on the provider's cost and not on the console.
  await accountTrigger(page).waitFor({ timeout: 90_000 })
}
