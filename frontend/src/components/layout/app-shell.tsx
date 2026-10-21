import { useQuery } from "@tanstack/react-query"
import { cn } from "cn"
import { Link, Outlet } from "react-router-dom"

import { api } from "@/lib/api/endpoints"
import { useCurrentProfileId } from "@/lib/profile"

import { AccountMenu } from "./account-menu"
import { BrandMark } from "./brand-mark"
import { AdminNav, NavGroups } from "./nav-groups"

/** Whether the API answers. Refreshed every 30 seconds. */
function ApiStatus() {
  const { data, isError, isPending } = useQuery({
    queryKey: ["health"],
    queryFn: ({ signal }) => api.health(signal),
    refetchInterval: 30_000,
    retry: false,
  })

  if (isPending) {
    return (
      <span className="hidden items-center gap-2 text-xs text-muted-foreground sm:inline-flex">
        <span className="size-1.5 rounded-full bg-border" />
        Checking the API
      </span>
    )
  }

  return (
    <span className="hidden items-center gap-2 text-xs text-muted-foreground sm:inline-flex">
      <span
        aria-hidden="true"
        className={cn(
          "size-1.5 rounded-full",
          isError ? "bg-destructive" : "bg-primary"
        )}
      />
      {isError ? "API unreachable" : `API online · ${data?.environment ?? "?"}`}
    </span>
  )
}

/**
 * The application shell.
 *
 * A refined horizontal header: the product mark, the workflow grouped by
 * what the operator is doing, the maintenance cluster set apart, and the
 * account menu. The current profile is always visible, because every
 * other screen works against it.
 */
export function AppShell() {
  const profileId = useCurrentProfileId()

  return (
    <div className="min-h-screen bg-background">
      <header className="sticky top-0 z-40 border-b border-border bg-card">
        <div className="console-container">
          <div className="flex h-16 items-center justify-between gap-4">
            <div className="flex items-center gap-3">
              <BrandMark />
              <div className="leading-tight">
                <Link
                  to="/resume"
                  className="font-heading text-[15px] font-semibold tracking-tight text-foreground"
                >
                  CareerPilot
                </Link>
                <p className="hidden text-[11px] text-muted-foreground sm:block">
                  The agentic job applier
                </p>
              </div>
            </div>

            <div className="flex items-center gap-2">
              <ApiStatus />
              <span className="hidden items-center gap-1.5 rounded-lg border border-border px-2.5 py-1.5 font-mono text-[11px] text-muted-foreground md:inline-flex">
                <span
                  aria-hidden="true"
                  className="size-1.5 rounded-full bg-terracotta"
                />
                {profileId ?? "no profile"}
              </span>
              <AccountMenu />
            </div>
          </div>

          {/*
            One navigation row. On a narrow screen it scrolls sideways rather
            than wrapping into a second band — a wrapped nav costs a whole
            line of the viewport, and a horizontal scroll costs none.
          */}
          <div className="flex items-center justify-between gap-4 border-t border-border py-1.5">
            <div className="min-w-0 flex-1 overflow-x-auto">
              <NavGroups />
            </div>
            <AdminNav />
          </div>
        </div>
      </header>

      <main className="console-container py-8">
        <Outlet />
      </main>
    </div>
  )
}
