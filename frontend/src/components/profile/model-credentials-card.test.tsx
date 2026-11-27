import { screen, waitFor, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { http, HttpResponse } from "msw"
import { describe, expect, it } from "vitest"

import { ModelCredentialsCard } from "@/components/profile/model-credentials-card"
import type { LlmCredentialState, LlmCredentialStatus } from "@/lib/api/types"
import { renderScreen } from "@/test/render"
import { server } from "@/test/server"

const ROUTE = "http://api.test/api/llm/credentials"
// This synthetic input is only sent to MSW. Stored fixtures contain hints only.
const DUMMY_KEY = "test-only-value-2020"

const primary: LlmCredentialStatus = {
  id: "connection-1",
  provider: "google",
  model: "gemini-standard",
  base_url: null,
  hint: "1010",
  created_at: "2026-11-08T00:00:00Z",
  updated_at: "2026-11-08T00:00:00Z",
  last_used_at: null,
}

const spare: LlmCredentialStatus = {
  ...primary,
  id: "connection-2",
  model: "gemini-mini",
  hint: "2020",
}

function serveState(overrides: Partial<LlmCredentialState> = {}) {
  const state: LlmCredentialState = {
    mode: "optional",
    available: true,
    encryption: "local_file",
    platform_configured: true,
    using: "platform",
    credential: null,
    credentials: [],
    ...overrides,
  }
  server.use(http.get(ROUTE, () => HttpResponse.json(state)))
  return state
}

function serveTwoConnections() {
  return serveState({
    using: "user",
    credential: primary,
    credentials: [primary, spare],
  })
}

function renderCard() {
  return renderScreen(<ModelCredentialsCard />, {
    route: "/app/account?tab=credentials",
  })
}

function connection(model: string) {
  return within(screen.getByRole("listitem", { name: new RegExp(model) }))
}

async function openAdd(user: ReturnType<typeof userEvent.setup>) {
  await user.click(await screen.findByRole("button", { name: "Add connection" }))
  return within(screen.getByRole("dialog", { name: "Add connection" }))
}

async function openEdit(user: ReturnType<typeof userEvent.setup>, model: string) {
  await screen.findByRole("listitem", { name: new RegExp(model) })
  await user.click(connection(model).getByRole("button", { name: /^Edit/ }))
  return within(screen.getByRole("dialog", { name: "Edit connection" }))
}

async function openRemove(user: ReturnType<typeof userEvent.setup>, model: string) {
  await screen.findByRole("listitem", { name: new RegExp(model) })
  await user.click(connection(model).getByRole("button", { name: /^Remove/ }))
  return within(screen.getByRole("alertdialog", { name: "Remove connection?" }))
}

describe("the Model credentials card", () => {
  it("adds a second connection of the same provider without replacing or testing the first", async () => {
    const state = serveState({
      using: "user",
      credential: primary,
      credentials: [primary],
    })
    const posts: unknown[] = []
    const rowActions: string[] = []
    server.use(
      http.post(ROUTE, async ({ request }) => {
        posts.push(await request.json())
        state.credentials = [primary, spare]
        return HttpResponse.json(spare, { status: 201 })
      }),
      http.post(`${ROUTE}/:id/test`, () => {
        rowActions.push("test")
        return HttpResponse.json({ ok: false }, { status: 409 })
      }),
      http.post(`${ROUTE}/:id/activate`, () => {
        rowActions.push("activate")
        return HttpResponse.json({ detail: "Unexpected activation" }, { status: 409 })
      })
    )
    const user = userEvent.setup()
    const { queryClient } = renderCard()

    const editor = await openAdd(user)
    await user.type(editor.getByLabelText("Model"), spare.model)
    const key = editor.getByLabelText("Provider API key")
    expect(key).toHaveAttribute("type", "password")
    expect(key).toHaveValue("")
    await user.type(key, DUMMY_KEY)
    await user.click(editor.getByRole("button", { name: "Save connection" }))

    await screen.findByRole("listitem", { name: /gemini-mini/ })
    expect(posts).toEqual([
      { provider: "google", model: "gemini-mini", base_url: null, api_key: DUMMY_KEY },
    ])
    expect(rowActions).toEqual([])
    expect(connection(primary.model).getByText("Active")).toBeInTheDocument()
    expect(connection(spare.model).queryByText("Active")).not.toBeInTheDocument()
    expect(connection(spare.model).getByText(/••••••••2020/)).toBeInTheDocument()
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument())
    expect(screen.queryByDisplayValue(DUMMY_KEY)).not.toBeInTheDocument()
    expect(JSON.stringify(queryClient.getQueryCache().getAll().map((entry) => entry.state))).not.toContain(DUMMY_KEY)
    expect(JSON.stringify(queryClient.getMutationCache().getAll().map((entry) => entry.state))).not.toContain(DUMMY_KEY)
  })

  it("PATCHes only the changed model and leaves the saved key alone", async () => {
    const endpoint = "https://models.example.test/v1"
    const saved = { ...spare, provider: "openai-compatible", base_url: endpoint }
    const state = serveState({
      using: "user",
      credential: primary,
      credentials: [primary, saved],
    })
    const patches: unknown[] = []
    server.use(
      http.patch(`${ROUTE}/connection-2`, async ({ request }) => {
        patches.push(await request.json())
        const updated = { ...saved, model: "model-revised" }
        state.credentials = [primary, updated]
        return HttpResponse.json(updated)
      })
    )
    const user = userEvent.setup()
    renderCard()

    const editor = await openEdit(user, spare.model)
    expect(editor.getByLabelText("Provider")).toHaveValue("openai-compatible")
    expect(editor.getByLabelText("Model")).toHaveValue(spare.model)
    expect(editor.getByLabelText(/Base URL/)).toHaveValue(endpoint)
    expect(editor.getByLabelText("Provider API key")).toHaveValue("")
    expect(editor.getByText(/leave blank to keep/i)).toBeInTheDocument()
    expect(editor.getByRole("button", { name: "Save changes" })).toBeDisabled()
    await user.clear(editor.getByLabelText("Model"))
    await user.type(editor.getByLabelText("Model"), "model-revised")
    await user.click(editor.getByRole("button", { name: "Save changes" }))

    await screen.findByRole("listitem", { name: /model-revised/ })
    expect(patches).toEqual([{ model: "model-revised" }])
    expect(connection("model-revised").getByText(/••••••••2020/)).toBeInTheDocument()
  })

  it("requires a fresh key when changing the provider", async () => {
    serveTwoConnections()
    const user = userEvent.setup()
    renderCard()

    const editor = await openEdit(user, spare.model)
    const key = editor.getByLabelText("Provider API key")
    await user.type(key, DUMMY_KEY)
    await user.selectOptions(editor.getByLabelText("Provider"), "groq")

    expect(key).toHaveValue("")
    expect(editor.getByText(/enter a new key.*provider/i)).toBeInTheDocument()
    expect(editor.getByRole("button", { name: "Save changes" })).toBeDisabled()
    await user.type(key, DUMMY_KEY)
    expect(editor.getByRole("button", { name: "Save changes" })).toBeEnabled()
  })

  it("lets the server decide whether an endpoint change needs a new key", async () => {
    const state = serveTwoConnections()
    const endpoint = "https://models.example.test/gemini"
    const patches: unknown[] = []
    server.use(
      http.patch(`${ROUTE}/connection-2`, async ({ request }) => {
        const body = await request.json()
        patches.push(body)
        if (patches.length === 1) {
          return HttpResponse.json({ detail: "A new key is required for the endpoint." }, { status: 422 })
        }
        const updated = { ...spare, base_url: endpoint }
        state.credentials = [primary, updated]
        return HttpResponse.json(updated)
      })
    )
    const user = userEvent.setup()
    renderCard()

    const editor = await openEdit(user, spare.model)
    await user.type(editor.getByLabelText(/Base URL/), endpoint)
    await user.click(editor.getByRole("button", { name: "Save changes" }))
    expect(await editor.findByRole("alert")).toHaveTextContent(/new API key/i)
    expect(editor.getByLabelText(/Base URL/)).toHaveValue(endpoint)

    await user.type(editor.getByLabelText("Provider API key"), DUMMY_KEY)
    await user.click(editor.getByRole("button", { name: "Save changes" }))
    expect(await screen.findByText(endpoint)).toBeInTheDocument()
    expect(patches).toEqual([
      { base_url: endpoint },
      { base_url: endpoint, api_key: DUMMY_KEY },
    ])
  })

  it("clears a rejected key and never displays validation details that could echo it", async () => {
    serveState()
    server.use(
      http.post(ROUTE, () =>
        HttpResponse.json({ detail: `The server rejected ${DUMMY_KEY}.` }, { status: 422 })
      )
    )
    const user = userEvent.setup()
    const { queryClient } = renderCard()

    const editor = await openAdd(user)
    await user.type(editor.getByLabelText("Model"), spare.model)
    await user.type(editor.getByLabelText("Provider API key"), DUMMY_KEY)
    await user.click(editor.getByRole("button", { name: "Save connection" }))

    expect(await editor.findByRole("alert")).not.toHaveTextContent(DUMMY_KEY)
    expect(editor.getByLabelText("Provider API key")).toHaveValue("")
    expect(editor.getByLabelText("Model")).toHaveValue(spare.model)
    expect(JSON.stringify(queryClient.getMutationCache().getAll().map((entry) => entry.state))).not.toContain(DUMMY_KEY)
  })

  it("requires a base URL for a custom compatible provider but not a vendor default", async () => {
    serveState()
    const user = userEvent.setup()
    renderCard()

    const editor = await openAdd(user)
    const provider = editor.getByLabelText("Provider")
    expect(within(provider).getAllByRole("option").map((option) => option.getAttribute("value"))).toEqual(
      expect.arrayContaining(["groq", "tokenharbor", "pollinations"])
    )
    const save = editor.getByRole("button", { name: "Save connection" })
    await user.selectOptions(provider, "groq")
    await user.type(editor.getByLabelText("Model"), "sample-groq-model")
    await user.type(editor.getByLabelText("Provider API key"), DUMMY_KEY)
    expect(save).toBeEnabled()

    await user.selectOptions(provider, "openai-compatible")
    await user.type(editor.getByLabelText("Provider API key"), DUMMY_KEY)
    expect(save).toBeDisabled()
    await user.type(editor.getByLabelText(/Base URL/), "https://models.example.test/v1")
    expect(save).toBeEnabled()
  })

  it("makes the selected row active and displays the refreshed server order", async () => {
    const state = serveTwoConnections()
    const activations: string[] = []
    server.use(
      http.post(`${ROUTE}/:id/activate`, ({ params }) => {
        activations.push(String(params.id))
        state.credential = spare
        state.credentials = [spare, primary]
        return HttpResponse.json(spare)
      })
    )
    const user = userEvent.setup()
    renderCard()

    await screen.findByRole("listitem", { name: /gemini-standard/ })
    expect(connection(primary.model).queryByRole("button", { name: /^Make active/ })).not.toBeInTheDocument()
    await user.click(connection(spare.model).getByRole("button", { name: /^Make active/ }))

    expect(await connection(spare.model).findByText("Active")).toBeInTheDocument()
    expect(connection(primary.model).queryByText("Active")).not.toBeInTheDocument()
    expect(screen.getAllByRole("listitem")[0]).toHaveAccessibleName(/gemini-mini/)
    expect(activations).toEqual(["connection-2"])
  })

  it("tests a non-active row only when asked and never makes it active", async () => {
    serveTwoConnections()
    const calls: string[] = []
    let finishTest!: () => void
    const pendingTest = new Promise<void>((resolve) => { finishTest = resolve })
    server.use(
      http.post(`${ROUTE}/:id/test`, async ({ params }) => {
        calls.push(`test:${params.id}`)
        await pendingTest
        return HttpResponse.json({ ok: true, provider: "google", model: spare.model, latency_ms: 42, error_type: null })
      }),
      http.post(`${ROUTE}/:id/activate`, ({ params }) => {
        calls.push(`activate:${params.id}`)
        return HttpResponse.json(spare)
      })
    )
    const user = userEvent.setup()
    renderCard()

    await screen.findByRole("listitem", { name: /gemini-mini/ })
    expect(screen.getByText(/billable provider call/i)).toBeInTheDocument()
    expect(calls).toEqual([])
    await user.click(connection(spare.model).getByRole("button", { name: /^Test connection/ }))
    expect(connection(spare.model).getByRole("button", { name: /^Testing/ })).toBeDisabled()
    expect(connection(spare.model).getByRole("button", { name: /^Make active/ })).toBeDisabled()
    finishTest()

    expect(await connection(spare.model).findByText(/answered in 42 ms/i)).toBeInTheDocument()
    expect(connection(primary.model).getByText("Active")).toBeInTheDocument()
    expect(connection(spare.model).queryByText("Active")).not.toBeInTheDocument()
    expect(calls).toEqual(["test:connection-2"])
  })

  it("shows a failed provider test on the tested row without changing the active one", async () => {
    serveTwoConnections()
    server.use(
      http.post(`${ROUTE}/connection-2/test`, () =>
        HttpResponse.json({ ok: false, provider: "google", model: spare.model, latency_ms: null, error_type: "LLMCredentialError" })
      )
    )
    const user = userEvent.setup()
    renderCard()

    await screen.findByRole("listitem", { name: /gemini-mini/ })
    await user.click(connection(spare.model).getByRole("button", { name: /^Test connection/ }))

    expect(await connection(spare.model).findByRole("alert")).toHaveTextContent(/rejected the key or the endpoint/i)
    expect(connection(primary.model).getByText("Active")).toBeInTheDocument()
  })

  it("confirms active removal with the next saved connection in server order", async () => {
    const state = serveTwoConnections()
    const oldest = { ...spare, id: "connection-3", model: "gemini-oldest", hint: "3030", created_at: "2026-11-01T00:00:00Z" }
    state.credentials = [primary, spare, oldest]
    const deleted: string[] = []
    server.use(
      http.delete(`${ROUTE}/:id`, ({ params }) => {
        deleted.push(String(params.id))
        state.credential = spare
        state.credentials = [spare, oldest]
        return HttpResponse.json({ removed: true })
      })
    )
    const user = userEvent.setup()
    renderCard()

    const confirmation = await openRemove(user, primary.model)
    expect(confirmation.getByText(/gemini-mini.*become the default/i)).toBeInTheDocument()
    expect(deleted).toEqual([])
    await user.click(confirmation.getByRole("button", { name: "Cancel" }))
    await waitFor(() => expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument())
    expect(deleted).toEqual([])

    const reopened = await openRemove(user, primary.model)
    await user.click(reopened.getByRole("button", { name: "Remove connection" }))
    expect(await connection(spare.model).findByText("Active")).toBeInTheDocument()
    expect(screen.queryByRole("listitem", { name: /gemini-standard/ })).not.toBeInTheDocument()
    expect(connection(oldest.model).queryByText("Active")).not.toBeInTheDocument()
    expect(deleted).toEqual(["connection-1"])
  })

  it.each([
    { mode: "optional", consequence: /deployment's key/i, title: "Using the deployment's key", using: "platform" },
    { mode: "required", consequence: /model calls cannot run/i, title: "This deployment requires your own key", using: "none" },
  ])("explains the $mode policy before removing the last connection", async ({ mode, consequence, title, using }) => {
    const state = serveState({ mode, using: "user", credential: primary, credentials: [primary] })
    server.use(
      http.delete(`${ROUTE}/connection-1`, () => {
        state.credential = null
        state.credentials = []
        state.using = using
        return HttpResponse.json({ removed: true })
      })
    )
    const user = userEvent.setup()
    renderCard()

    const confirmation = await openRemove(user, primary.model)
    expect(confirmation.getByText(consequence)).toBeInTheDocument()
    await user.click(confirmation.getByRole("button", { name: "Remove connection" }))

    expect(await screen.findByText("No saved connections yet.")).toBeInTheDocument()
    expect(screen.getByText(title)).toBeInTheDocument()
    expect(screen.queryByRole("button", { name: /^Test connection/ })).not.toBeInTheDocument()
  })

  it.each([
    { mode: "disabled", encryption: "local_file", policy: /personal keys are disabled/i },
    { mode: "optional", encryption: "none", policy: /no encryption key material/i },
  ])("allows removal but not new use when personal connections are $mode with encryption $encryption", async ({ mode, encryption, policy }) => {
    const state = serveState({ mode, encryption, available: false, using: "platform", credential: primary, credentials: [primary, spare] })
    server.use(
      http.delete(`${ROUTE}/connection-2`, () => {
        state.credentials = [primary]
        return HttpResponse.json({ removed: true })
      })
    )
    const user = userEvent.setup()
    renderCard()

    expect(await screen.findByText(policy)).toBeInTheDocument()
    expect(connection(primary.model).getByText("Default (not in use)")).toBeInTheDocument()
    expect(screen.queryByText("Active")).not.toBeInTheDocument()
    for (const name of [/^Add connection/, /^Edit/, /^Make active/, /^Test connection/]) {
      expect(screen.queryAllByRole("button", { name }).every((button) => (button as HTMLButtonElement).disabled)).toBe(true)
    }

    const confirmation = await openRemove(user, spare.model)
    expect(confirmation.getByText(/default connection will not change/i)).toBeInTheDocument()
    await user.click(confirmation.getByRole("button", { name: "Remove connection" }))
    await waitFor(() => expect(screen.queryByRole("listitem", { name: /gemini-mini/ })).not.toBeInTheDocument())
    expect(connection(primary.model).getByText("Default (not in use)")).toBeInTheDocument()
  })

  it("does not claim a deployment key is in use when none is configured", async () => {
    serveState({ platform_configured: false, using: "none" })
    renderCard()

    expect(await screen.findByText("No model key is in use")).toBeInTheDocument()
    expect(screen.getByText("No saved connections yet.")).toBeInTheDocument()
    expect(screen.getByRole("button", { name: "Add connection" })).toBeEnabled()
    expect(screen.queryByText("Using the deployment's key")).not.toBeInTheDocument()
  })

  it("does not mistake a legacy response for an empty list", async () => {
    server.use(
      http.get(ROUTE, () => HttpResponse.json({
        mode: "optional", available: true, encryption: "local_file", using: "platform", platform_configured: true, credential: null,
      }))
    )
    renderCard()

    expect(await screen.findByRole("alert")).toHaveTextContent(/API does not support multiple model connections/i)
    expect(screen.queryByRole("button", { name: "Add connection" })).not.toBeInTheDocument()
  })
})
