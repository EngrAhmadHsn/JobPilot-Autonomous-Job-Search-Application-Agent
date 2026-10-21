import { QueryClientProvider } from "@tanstack/react-query"
import { render, type RenderOptions } from "@testing-library/react"
import type { ReactElement } from "react"
import {
  MemoryRouter,
  RouterProvider,
  createMemoryRouter,
} from "react-router-dom"

import { createQueryClient } from "@/lib/query-client"
import { routes } from "@/routes"

type QueryClient = ReturnType<typeof createQueryClient>

/**
 * Render the console's real route tree.
 *
 * The routing is the console's own, in a memory router, and the query
 * client is the console's own policy — so a test exercises the same wiring
 * the browser gets.
 */
export function renderApp(
  options: { route?: string; queryClient?: QueryClient } & RenderOptions = {}
) {
  const { route = "/", queryClient = createQueryClient(), ...rest } = options
  const router = createMemoryRouter(routes, { initialEntries: [route] })
  const result = render(
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={router} />
    </QueryClientProvider>,
    rest
  )
  return { ...result, router, queryClient }
}

/**
 * Render one screen on its own, inside the console's providers.
 *
 * The screen is mounted in a memory router so that `useParams`, `Link` and
 * `useNavigate` work exactly as they do in the application.
 */
export function renderScreen(
  ui: ReactElement,
  options: { route?: string; queryClient?: QueryClient } & RenderOptions = {}
) {
  const { route = "/", queryClient = createQueryClient(), ...rest } = options
  const result = render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={[route]}>{ui}</MemoryRouter>
    </QueryClientProvider>,
    rest
  )
  return { ...result, queryClient }
}
