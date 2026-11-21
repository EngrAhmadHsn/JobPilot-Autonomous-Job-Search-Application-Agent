import { screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { http, HttpResponse } from "msw"
import { describe, expect, it } from "vitest"

import { ModelCredentialsCard } from "@/components/profile/model-credentials-card"
import { renderScreen } from "@/test/render"
import { server } from "@/test/server"

/**
 * WS-22: the bring-your-own-key card.
 *
 * What these tests pin down, and why each one exists:
 *
 * - the card **never renders the key**: the read returns a mask, and the
 *   input starts empty even when a credential is stored — the server has no
 *   key to send, so the console must not pretend otherwise;
 * - a save sends exactly the documented body (provider, model, key, base
 *   URL), and clears the key field afterwards;
 * - the **test call is a separate action**: saving a key must not spend the
 *   user's quota, so the test endpoint is only called from its own button;
 * - the deployment modes are rendered honestly (`required`, `disabled`, and
 *   "no encryption key material" all say something different);
 * - the base-URL field appears where it is meaningful (required for a bare
 *   openai-compatible endpoint, optional for the vendor aliases).
 */

const BASE = "http://api.test"
const ROUTE = `${BASE}/api/llm/credentials`
const TEST_ROUTE = `${BASE}/api/llm/credentials/test`

interface CapturedPut {
  body: {
    provider?: string
    model?: string
    api_key?: string
    base_url?: string | null
  }
}

function state(overrides: Record<string, unknown> = {}) {
  return {
    mode: "optional",
    available: true,
    encryption: "local_file",
    platform_configured: true,
    using: "platform",
    credential: null,
    ...overrides,
  }
}

function capturePuts(): CapturedPut[] {
  const puts: CapturedPut[] = []
  server.use(
    http.put(ROUTE, async ({ request }) => {
      const body = (await request.json()) as CapturedPut["body"]
      puts.push({ body })
      return HttpResponse.json({
        provider: body.provider ?? "google",
        model: body.model ?? "",
        base_url: body.base_url ?? null,
        hint: (body.api_key ?? "").slice(-4),
        created_at: "2026-11-08T00:00:00Z",
        updated_at: "2026-11-08T00:00:00Z",
        last_used_at: null,
      })
    })
  )
  return puts
}

function serveState(payload: Record<string, unknown>) {
  server.use(http.get(ROUTE, () => HttpResponse.json(payload)))
}

describe("the Model credentials card", () => {
  it("says which key a call would spend, and never renders a stored key", async () => {
    serveState(
      state({
        using: "user",
        credential: {
          provider: "google",
          model: "gemini-3.8-flash",
          base_url: null,
          hint: "cret",
          created_at: "2026-11-08T00:00:00Z",
          updated_at: "2026-11-08T00:00:00Z",
          last_used_at: null,
        },
      })
    )

    renderScreen(<ModelCredentialsCard />, { route: "/app/profile" })

    expect(await screen.findByText("Your key is in use")).toBeInTheDocument()
    expect(screen.getByText(/key ending/)).toBeInTheDocument()

    const input = screen.getByLabelText(/API key/) as HTMLInputElement
    expect(input.value).toBe("")
    expect(input.type).toBe("password")
  })

  it("saves the documented body and clears the key field", async () => {
    serveState(state())
    const puts = capturePuts()
    const user = userEvent.setup()

    renderScreen(<ModelCredentialsCard />, { route: "/app/profile" })

    await screen.findByText("Using the deployment's key")
    await user.type(screen.getByLabelText("Model"), "gemini-3.8-flash")
    await user.type(screen.getByLabelText(/API key/), "sk-my-own-key-123456")
    await user.click(screen.getByRole("button", { name: "Save key" }))

    await waitFor(() => expect(puts).toHaveLength(1))
    expect(puts[0]?.body).toEqual({
      provider: "google",
      model: "gemini-3.8-flash",
      api_key: "sk-my-own-key-123456",
      base_url: null,
    })
    await waitFor(() =>
      expect((screen.getByLabelText(/API key/) as HTMLInputElement).value).toBe(
        ""
      )
    )
  })

  it("does not spend the user's quota when a key is saved", async () => {
    serveState(state())
    capturePuts()
    let tested = 0
    server.use(
      http.post(TEST_ROUTE, () => {
        tested += 1
        return HttpResponse.json({
          ok: true,
          provider: "google",
          model: "gemini-3.8-flash",
          latency_ms: 42,
        })
      })
    )
    const user = userEvent.setup()

    renderScreen(<ModelCredentialsCard />, { route: "/app/profile" })
    await screen.findByText("Using the deployment's key")
    await user.type(screen.getByLabelText("Model"), "gemini-3.8-flash")
    await user.type(screen.getByLabelText(/API key/), "sk-my-own-key-123456")
    await user.click(screen.getByRole("button", { name: "Save key" }))

    await waitFor(() => expect(tested).toBe(0))
  })

  it("tests a stored key only when asked", async () => {
    serveState(
      state({
        using: "user",
        credential: {
          provider: "google",
          model: "gemini-3.8-flash",
          base_url: null,
          hint: "23456",
          created_at: "2026-11-08T00:00:00Z",
          updated_at: "2026-11-08T00:00:00Z",
          last_used_at: null,
        },
      })
    )
    let tested = 0
    server.use(
      http.post(TEST_ROUTE, () => {
        tested += 1
        return HttpResponse.json({
          ok: true,
          provider: "google",
          model: "gemini-3.8-flash",
          latency_ms: 42,
        })
      })
    )
    const user = userEvent.setup()

    renderScreen(<ModelCredentialsCard />, { route: "/app/profile" })
    await screen.findByText("Your key is in use")
    await user.click(screen.getByRole("button", { name: "Test connection" }))

    await waitFor(() => expect(tested).toBe(1))
    expect(await screen.findByText("The key works")).toBeInTheDocument()
  })

  it("reports a rejected key as a problem with a next step", async () => {
    serveState(
      state({
        using: "user",
        credential: {
          provider: "google",
          model: "gemini-3.8-flash",
          base_url: null,
          hint: "23456",
          created_at: "2026-11-08T00:00:00Z",
          updated_at: "2026-11-08T00:00:00Z",
          last_used_at: null,
        },
      })
    )
    server.use(
      http.post(TEST_ROUTE, () =>
        HttpResponse.json({
          ok: false,
          provider: "google",
          model: "gemini-3.8-flash",
          latency_ms: null,
          error_type: "LLMCredentialError",
        })
      )
    )
    const user = userEvent.setup()

    renderScreen(<ModelCredentialsCard />, { route: "/app/profile" })
    await screen.findByText("Your key is in use")
    await user.click(screen.getByRole("button", { name: "Test connection" }))

    expect(await screen.findByText("The key did not work")).toBeInTheDocument()
    expect(
      screen.getByText(/rejected the key or the endpoint/)
    ).toBeInTheDocument()
  })

  it("asks for a base URL only where it is needed", async () => {
    serveState(state())
    const user = userEvent.setup()

    renderScreen(<ModelCredentialsCard />, { route: "/app/profile" })
    await screen.findByText("Using the deployment's key")

    // google: optional, with the default explained
    expect(screen.getByLabelText(/Base URL/)).toBeInTheDocument()
    expect(
      screen.getByText(/Leave empty to use this provider's default endpoint/)
    ).toBeInTheDocument()

    // a bare openai-compatible endpoint: required
    await user.selectOptions(
      screen.getByLabelText("Provider"),
      "openai-compatible"
    )
    expect(screen.getByLabelText(/Base URL/)).toBeInTheDocument()

    const save = screen.getByRole("button", { name: "Save key" })
    await user.type(screen.getByLabelText("Model"), "gpt-4o-mini")
    await user.type(screen.getByLabelText(/API key/), "sk-my-own-key-123456")
    expect(save).toBeDisabled()
    await user.type(
      screen.getByLabelText(/Base URL/),
      "https://api.example.com/v1"
    )
    expect(save).toBeEnabled()
  })

  it("offers the fallback providers with their own defaults (WS-30)", async () => {
    serveState(state())
    const user = userEvent.setup()

    renderScreen(<ModelCredentialsCard />, { route: "/app/profile" })
    await screen.findByText("Using the deployment's key")

    const provider = screen.getByLabelText("Provider")
    const values = Array.from(provider.querySelectorAll("option")).map(
      (option) => option.getAttribute("value")
    )
    // The three the platform's chain uses are registerable by a user too.
    expect(values).toEqual(
      expect.arrayContaining(["groq", "tokenharbor", "pollinations"])
    )

    // A vendor-default provider needs a key and a model, no URL.
    await user.selectOptions(provider, "groq")
    await user.type(screen.getByLabelText("Model"), "qwen/qwen3.8-27b")
    await user.type(screen.getByLabelText(/API key/), "gsk-my-own-key-123456")
    expect(screen.getByRole("button", { name: "Save key" })).toBeEnabled()
    expect(
      screen.getByText(/Leave empty to use this provider's default endpoint/)
    ).toBeInTheDocument()
  })

  it("renders the required mode as a demand, and the disabled mode as a fact", async () => {
    serveState(
      state({ mode: "required", platform_configured: false, using: "none" })
    )
    const first = renderScreen(<ModelCredentialsCard />, {
      route: "/app/profile",
    })
    expect(
      await screen.findByText("This deployment requires your own key")
    ).toBeInTheDocument()
    first.unmount()

    serveState(
      state({
        mode: "disabled",
        available: false,
        platform_configured: true,
        using: "platform",
      })
    )
    renderScreen(<ModelCredentialsCard />, { route: "/app/profile" })
    expect(
      await screen.findByText("Personal keys are disabled on this deployment.")
    ).toBeInTheDocument()
  })

  it("says so when the deployment has no encryption key material", async () => {
    serveState(
      state({ available: false, encryption: "none", using: "platform" })
    )

    renderScreen(<ModelCredentialsCard />, { route: "/app/profile" })

    expect(
      await screen.findByText(/cannot store credentials/)
    ).toBeInTheDocument()
  })
})

/*
  WS-46 restyled the card into the design's "Your model key" card
  (`15 · Account & security`): a state chip under the title, the masked-only
  promise in the description, and the economics of testing stated where the
  button is. The API surface did not change; these pin the new surface.
*/
describe("the Your model key card (WS-46)", () => {
  it("reads its state chip from the stored credential, never the key", async () => {
    serveState(state())

    renderScreen(<ModelCredentialsCard />, { route: "/app/profile" })

    expect(await screen.findByTestId("model-key-state")).toHaveTextContent(
      "No key configured"
    )
    // The test action needs a key to test; without one it is not offered,
    // because testing the deployment's own key would spend it unasked.
    expect(screen.queryByRole("button", { name: "Test connection" })).toBeNull()
    // The card's own economics line, in the design's words.
    expect(
      screen.getByText(
        "Testing makes a separate, billable provider call. It does not run automatically when saving."
      )
    ).toBeInTheDocument()
  })

  it("names the provider and the masked hint when a key is stored", async () => {
    serveState(
      state({
        using: "user",
        credential: {
          provider: "google",
          model: "gemini-3.8-flash",
          base_url: null,
          hint: "cret",
          created_at: "2026-11-08T00:00:00Z",
          updated_at: "2026-11-08T00:00:00Z",
          last_used_at: null,
        },
      })
    )

    renderScreen(<ModelCredentialsCard />, { route: "/app/profile" })

    const chip = await screen.findByTestId("model-key-state")
    expect(chip).toHaveTextContent("google")
    expect(chip).toHaveTextContent("••••••••cret")
    // The chip is a mask, not the key: the read only ever returns the hint,
    // and the chip renders exactly that.
    expect(chip.textContent).not.toContain("gemini-3.8-flash-key")
  })

  it("promises only a masked state after saving, in the description", async () => {
    serveState(state())

    renderScreen(<ModelCredentialsCard />, { route: "/app/profile" })

    expect(
      await screen.findByText(
        "Store, replace, or remove your key. Only a masked state is returned after saving."
      )
    ).toBeInTheDocument()
  })
})
