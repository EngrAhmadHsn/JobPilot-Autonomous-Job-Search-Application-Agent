import { QueryClientProvider } from "@tanstack/react-query"
import { render, type RenderOptions } from "@testing-library/react"
import type { ReactElement } from "react"
import {
  MemoryRouter,
  RouterProvider,
  createMemoryRouter,
} from "react-router-dom"

import { ThemeProvider } from "@/components/theme-provider"
import { createQueryClient } from "@/lib/query-client"
import { routes } from "@/routes"

type QueryClient = ReturnType<typeof createQueryClient>

/**
 * Render the console's real route tree.
 *
 * The routing is the console's own, in a memory router, and the query
 * client is the console's own policy, so a test exercises the same wiring
 * the browser gets.
 *
 * `state` carries a location's `history.state`, which is how a caller asks
 * a screen to open in a particular mode. The landing page uses it to request
 * the create form from `/sign-in`, so a test needs to be able to set it the
 * same way a `<Link state={...}>` does.
 */
export function renderApp(
  options: {
    route?: string
    state?: Record<string, unknown>
    queryClient?: QueryClient
  } & RenderOptions = {}
) {
  const {
    route = "/",
    state,
    queryClient = createQueryClient(),
    ...rest
  } = options
  const router = createMemoryRouter(routes, {
    initialEntries: [state ? { pathname: route, state } : route],
  })
  const result = render(
    <ThemeProvider>
      <QueryClientProvider client={queryClient}>
        <RouterProvider router={router} />
      </QueryClientProvider>
    </ThemeProvider>,
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
    <ThemeProvider>
      <QueryClientProvider client={queryClient}>
        <MemoryRouter initialEntries={[route]}>{ui}</MemoryRouter>
      </QueryClientProvider>
    </ThemeProvider>,
    rest
  )
  return { ...result, queryClient }
}
