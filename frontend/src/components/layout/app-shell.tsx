import { useQuery } from "@tanstack/react-query"
import { cn } from "cn"
import { NavLink, Outlet } from "react-router-dom"

import { api } from "@/lib/api/endpoints"
import { useCurrentProfileId } from "@/lib/profile"

const NAV_ITEMS = [
  { to: "/resume", label: "Resume" },
  { to: "/matches", label: "Matches" },
  { to: "/tailor", label: "Tailor" },
  { to: "/approvals", label: "Approvals" },
  { to: "/tracker", label: "Tracker" },
  { to: "/operations", label: "Operations" },
]

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
      <span className="text-xs text-muted-foreground">Checking the API…</span>
    )
  }
  if (isError) {
    return (
      <span className="text-xs font-medium text-destructive">
        The API is unreachable — the console cannot do anything until it is
        back.
      </span>
    )
  }
  return (
    <span className="text-xs text-muted-foreground">
      API {data?.status ?? "unknown"} · {data?.environment ?? "?"}
    </span>
  )
}

/**
 * The application shell: the navigation, the API's reachability, and which
 * candidate profile the console is working with.
 *
 * The profile is shown in the header of every screen because the API has no
 * profile listing (BA-4): the console keeps the current profile id
 * client-side, and the operator must always be able to see which one it is.
 */
export function AppShell() {
  const profileId = useCurrentProfileId()

  return (
    <div className="min-h-screen bg-background text-foreground">
      <header className="border-b border-border bg-card">
        <div className="mx-auto flex max-w-6xl flex-col gap-3 px-4 py-3">
          <div className="flex flex-wrap items-baseline justify-between gap-2">
            <div>
              <h1 className="font-heading text-lg font-semibold">
                Agentic Job Applier
              </h1>
              <p className="text-xs text-muted-foreground">
                Operator console — a human approves every submission.
              </p>
            </div>
            <ApiStatus />
          </div>

          <nav aria-label="Screens">
            <ul className="flex flex-wrap gap-1">
              {NAV_ITEMS.map((item) => (
                <li key={item.to}>
                  <NavLink
                    to={item.to}
                    className={({ isActive }) =>
                      cn(
                        "inline-flex h-8 items-center rounded-lg px-3 text-sm font-medium transition-colors",
                        isActive
                          ? "bg-primary text-primary-foreground"
                          : "text-muted-foreground hover:bg-muted hover:text-foreground"
                      )
                    }
                  >
                    {item.label}
                  </NavLink>
                </li>
              ))}
            </ul>
          </nav>

          <p className="text-xs text-muted-foreground">
            {profileId ? (
              <>
                Current profile:{" "}
                <code className="rounded bg-muted px-1 py-0.5 font-mono text-[11px]">
                  {profileId}
                </code>
              </>
            ) : (
              <>
                No profile selected — upload a resume on the Resume screen to
                begin.
              </>
            )}
          </p>
        </div>
      </header>

      <main className="mx-auto max-w-6xl px-4 py-6">
        <Outlet />
      </main>
    </div>
  )
}
