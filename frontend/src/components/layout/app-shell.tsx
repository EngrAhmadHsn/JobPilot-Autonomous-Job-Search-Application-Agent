import { useQuery } from "@tanstack/react-query"
import { cn } from "cn"
import { useRef } from "react"
import { Link, Outlet } from "react-router-dom"

import { useHeaderHeight } from "@/hooks/use-header-height"
import { api } from "@/lib/api/endpoints"
import { useCurrentProfileId } from "@/lib/profile"

import { SignInScreen } from "@/screens/sign-in-screen"

import { AccountMenu } from "./account-menu"
import { ProfileChip } from "./profile-chip"
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
  const headerRef = useRef<HTMLElement>(null)
  useHeaderHeight(headerRef)
  const identity = useQuery({
    queryKey: ["identity"],
    queryFn: ({ signal }) => api.identity(signal),
    retry: false,
  })

  // WS-14: the API has an identity, so the console needs one. A caller
  // with no session is refused by every protected route, so the console
  // asks the server who it is and shows the sign-in screen when the
  // answer is no.
  if (identity.isError) {
    return <SignInScreen />
  }

  return (
    <div className="min-h-screen bg-background">
      <header
        ref={headerRef}
        className="sticky top-0 z-40 border-b border-border bg-card"
      >
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
              <ProfileChip profileId={profileId} />
              <AccountMenu />
            </div>
          </div>

          {/*
            One navigation row. On a narrow screen the items wrap onto a
            second line: a scrollable nav would need a scrollbar, and a
            scrollbar in a header is a control the operator did not ask
            for.
          */}
          <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-1 border-t border-border py-1.5">
            <div className="min-w-0 flex-1">
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
