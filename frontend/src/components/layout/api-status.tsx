import { useQuery } from "@tanstack/react-query"
import { cn } from "cn"

import { api } from "@/lib/api/endpoints"

/**
 * Whether the API answers. Refreshed every 30 seconds.
 *
 * WS-34: extracted from `app-shell` so the sidebar footer and the
 * navigation drawer can both host it — it is a diagnostic, so it lives
 * with the account area rather than competing with the page content.
 *
 * The `surface` prop restyles it for the forest sidebar footer; the
 * default is the paper chrome.
 */
export function ApiStatus({
  surface = "default",
  className,
}: {
  surface?: "default" | "sidebar"
  className?: string
}) {
  const onSidebar = surface === "sidebar"
  const { data, isError, isPending } = useQuery({
    queryKey: ["health"],
    queryFn: ({ signal }) => api.health(signal),
    refetchInterval: 30_000,
    retry: false,
  })

  if (isPending) {
    return (
      <span
        className={cn(
          "inline-flex items-center gap-2 text-xs",
          onSidebar ? "text-sidebar-muted" : "text-muted-foreground",
          className
        )}
      >
        <span aria-hidden="true" className="size-1.5 rounded-full bg-border" />
        Checking the API
      </span>
    )
  }

  return (
    <span
      className={cn(
        "inline-flex items-center gap-2 text-xs",
        onSidebar ? "text-sidebar-muted" : "text-muted-foreground",
        className
      )}
    >
      <span
        aria-hidden="true"
        className={cn(
          "size-1.5 rounded-full",
          isError ? "bg-destructive" : onSidebar ? "bg-lime" : "bg-primary"
        )}
      />
      {isError ? "API unreachable" : `API online · ${data?.environment ?? "?"}`}
    </span>
  )
}
