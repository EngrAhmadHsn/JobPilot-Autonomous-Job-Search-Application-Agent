import { useQuery } from "@tanstack/react-query"
import { useRef } from "react"
import { Link, Outlet } from "react-router-dom"

import { useHeaderHeight } from "@/hooks/use-header-height"
import { ApiError } from "@/lib/api/client"
import { api } from "@/lib/api/endpoints"
import { useCurrentProfileId } from "@/lib/profile"

import { SkipToContent } from "@/components/common/skip-to-content"
import { ErrorState } from "@/components/ui/error-state"
import { SignInScreen } from "@/screens/sign-in-screen"

import { AccountMenu } from "./account-menu"
import { ProfileChip } from "./profile-chip"
import { ApiStatus } from "./api-status"
import { BrandMark } from "./brand-mark"
import { NavGroups, SystemNav } from "./nav-groups"
import { BottomNav } from "./bottom-nav"
import { NavDrawer } from "./nav-drawer"

/*
  The application shell (WS-34).

  The frame is the reference image's: at desktop widths a **deep forest
  sidebar** holds the brand, the grouped destinations and the account
  footer over the ivory canvas; below `lg` it swaps for a compact top
  bar, a five-slot bottom navigation and the drawer for everything else.
  The two shapes are never both in the accessibility tree at once — the
  sidebar is `hidden lg:flex` and the phone chrome is `lg:hidden` — so a
  screen reader never meets the same destination twice.

  What the redesign did not touch: the identity gate below (a caller with
  no session sees the sign-in screen, never the console chrome), the lazy
  routes that render inside `<Outlet />`, the `viewTransition` on every
  nav link, the skip link as the first tab stop, or the published
  `--header-height` the sticky offsets read.
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
  //
  // WS-41: "no" has to mean **no**. Only a 401/403 is a refusal; anything
  // else — a 429 from the per-identity request budget, a timeout, a dropped
  // connection — is the console failing to ask, not the session ending.
  // Rendering the sign-in screen for those told a signed-in operator they
  // were logged out and invited them to re-enter a password that was never
  // the problem, so a transient failure now says so and offers a retry. It
  // is still fail-closed: no console chrome renders until the server has
  // actually confirmed the identity.
  if (identity.isError) {
    const status =
      identity.error instanceof ApiError ? identity.error.status : 0
    const refused = status === 401 || status === 403
    if (refused) return <SignInScreen />
    return (
      <div className="grid min-h-screen place-items-center bg-background p-6">
        <div className="w-full max-w-md">
          {/*
            Deliberately not the sign-in screen. The copy makes the
            distinction the user cannot otherwise see: the request failed,
            the session did not end.
          */}
          <p className="mb-3 text-center text-sm leading-relaxed text-muted-foreground">
            Your session has not ended — the console could not reach the server
            to confirm it.
          </p>
          <ErrorState
            error={identity.error}
            onRetry={() => identity.refetch()}
          />
        </div>
      </div>
    )
  }

  const isSuperuser = Boolean(identity.data?.is_superuser)

  return (
    <div className="min-h-screen bg-background">
      {/*
        First in the tab order, before the sidebar nav, the bottom bar
        and the account menus. `#main-content` is on the `<main>` below,
        and its `scroll-mt` clears the phone's sticky top bar so the
        jump lands on visible content.
      */}
      <SkipToContent />

      {/*
        The desktop sidebar: forest, full height, its own scroll. Fixed
        rather than sticky so the canvas scrolls under it without the
        sidebar repainting.
      */}
      <aside className="fixed inset-y-0 left-0 z-40 hidden w-60 flex-col bg-sidebar text-sidebar-foreground lg:flex">
        <div className="flex items-center gap-3 px-4 pt-5 pb-2">
          <BrandMark variant="sidebar" />
          <div className="min-w-0 leading-tight">
            <Link
              to="/app"
              viewTransition
              className="block font-heading text-[17px] font-semibold tracking-tight text-sidebar-foreground outline-none focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-sidebar-ring"
            >
              JobPilot
            </Link>
            <p className="truncate text-[11px] text-sidebar-muted">
              The agentic job applier
            </p>
          </div>
        </div>

        <div className="flex-1 overflow-y-auto overscroll-contain pt-2 pb-4">
          <NavGroups surface="forest" />
          <SystemNav surface="forest" showAdmin={isSuperuser} />
        </div>

        {/*
          The account footer, as in the reference: the API's pulse, the
          profile the console works against, and the account menu. The
          menu opens upward from here.
        */}
        <div className="flex flex-col gap-2 border-t border-sidebar-border px-4 py-3">
          <ApiStatus surface="sidebar" />
          <ProfileChip
            profileId={profileId}
            surface="sidebar"
            className="w-full"
          />
          <AccountMenu surface="sidebar" className="w-full justify-start" />
        </div>
      </aside>

      {/*
        The phone chrome. The top bar carries the drawer trigger, the
        brand and the account menu; the bottom bar carries the five
        journey destinations; the drawer holds everything else.
      */}
      <header
        ref={headerRef}
        className="sticky top-0 z-40 border-b border-border bg-card lg:hidden"
      >
        <div className="flex h-14 items-center justify-between gap-2 px-2 sm:px-3">
          <div className="flex min-w-0 items-center gap-1">
            <NavDrawer showAdmin={isSuperuser} />
            <Link
              to="/app"
              viewTransition
              className="flex min-w-0 items-center gap-2 rounded-lg px-1.5 py-1 outline-none focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring"
            >
              <BrandMark />
              <span className="font-heading text-[15px] font-semibold tracking-tight text-foreground">
                JobPilot
              </span>
            </Link>
          </div>
          <AccountMenu />
        </div>
      </header>

      <BottomNav className="lg:hidden" />

      <main
        id="main-content"
        className="min-w-0 scroll-mt-[calc(var(--header-height,3.5rem)+1rem)] lg:pl-60"
      >
        {/*
          The container centres inside the remaining width, and the
          phone keeps a generous bottom padding so no content or focus
          hides behind the fixed bottom bar.
        */}
        <div className="console-container py-8 pb-28 lg:py-10 lg:pb-12">
          <Outlet />
        </div>
      </main>
    </div>
  )
}
