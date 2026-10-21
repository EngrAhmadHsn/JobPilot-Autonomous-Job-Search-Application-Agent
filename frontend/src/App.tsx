import { QueryClientProvider } from "@tanstack/react-query"
import { RouterProvider, createBrowserRouter } from "react-router-dom"

import { createQueryClient } from "@/lib/query-client"
import { routes } from "@/routes"

/**
 * The console's root.
 *
 * The `QueryClient` is created here (and not at module scope) so that a
 * test can mount the same tree with its own client and its own mocked
 * network.
 */
const router = createBrowserRouter(routes)
const queryClient = createQueryClient()

export function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={router} />
    </QueryClientProvider>
  )
}

export default App
