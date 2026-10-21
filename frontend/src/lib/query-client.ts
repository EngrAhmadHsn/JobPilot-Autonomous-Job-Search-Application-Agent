import { QueryClient } from "@tanstack/react-query"

import { ApiError, NetworkError } from "@/lib/api/client"

/**
 * The console's server-state policy.
 *
 * The rules are deliberately conservative, because the backend is not a
 * forgiving API:
 *
 * - a **query** (a read) may be retried **once**, and only when the failure
 *   is plausibly transient (a 5xx or a dead socket). A 4xx is the server
 *   refusing the request, and repeating it would only produce the same
 *   answer;
 * - a **429 is never retried automatically.** The server said when to come
 *   back, and the console tells the operator instead of hiding the refusal;
 * - a **mutation is never retried.** `approve` drives a browser against a
 *   third-party site: repeating it could submit twice. The operator decides
 *   to run it again.
 */
export function isRetryableQueryError(error: unknown): boolean {
  if (error instanceof ApiError) {
    if (error.status === 429) return false
    return error.status >= 500
  }
  if (error instanceof NetworkError) return true
  return false
}

export function createQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: {
        retry: (failureCount, error) =>
          failureCount < 1 && isRetryableQueryError(error),
        refetchOnWindowFocus: false,
        staleTime: 30_000,
      },
      mutations: {
        retry: false,
      },
    },
  })
}
