import { useQuery } from "@tanstack/react-query"
import { useRef, useState } from "react"
import { Link, Outlet, useLocation } from "react-router-dom"

import { useHeaderHeight } from "@/hooks/use-header-height"
import { ApiError } from "@/lib/api/client"
import { api } from "@/lib/api/endpoints"

import { SkipToContent } from "@/components/common/skip-to-content"
import { ErrorState } from "@/components/ui/error-state"
import { SignInScreen } from "@/screens/sign-in-screen"

import { AccountMenu } from "./account-menu"
import { ApiStatus } from "./api-status"
import { AppRail } from "./app-rail"
import { BottomNav } from "./bottom-nav"
import { TopBar } from "./top-bar"

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
  const headerRef = useRef<HTMLElement>(null)
  useHeaderHeight(headerRef)
  /*
    The rail's expanded state lives here, not in the rail: the shell is what
    knows a navigation happened (WS-43's auto-collapse) and what the rail
    floats **over** — the content column's gutter is constant (below), so
    the expansion is an overlay, not a reflow.
  */
  const [railExpanded, setRailExpanded] = useState(false)
  /*
    WS-43: the expanded rail overlays the content, so a route change that
    left it open would park 168 px of forest over the screen the operator
    just asked for. Collapse on every pathname change — the toggle stays
    usable — with React's adjust-state-on-prop-change pattern: compare
    against the location the last render saw, and reset *during* that
    render, so the rail is already collapsed when the new screen commits
    (an effect would paint one frame of rail-over-content). The initial
    state is collapsed and the tracker starts on the current pathname, so
    nothing collapses on first load.
  */
  const { pathname } = useLocation()
  const [lastPathname, setLastPathname] = useState(pathname)
  if (lastPathname !== pathname) {
    setLastPathname(pathname)
    setRailExpanded(false)
  }
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
        The desktop chrome (WS-42): a 72 px icon rail and a 68 px top bar,
        exactly the frame every screen in the design file draws (nodes
        `47:2` and `47:28`). The rail replaces the 240 px labelled sidebar
        the console used to carry — the labels are always one hover, one
        focus or one expand click away, and the width it frees is what lets
        the content column reach the design's 1304 px.

        Both are `hidden lg:flex`, and the phone chrome below is
        `lg:hidden`, so a screen reader never meets the same destination
        twice.
      */}
      <AppRail
        showAdmin={isSuperuser}
        expanded={railExpanded}
        onExpandedChange={setRailExpanded}
      />

      {/*
        The phone chrome (the design's mobile frames, nodes 49:7561 and
        49:10263): a **forest** 64 px bar carrying the wordmark, the
        environment marker and the account control — no drawer trigger up
        here, because the bottom bar's fourth slot ("More") opens the
        drawer, exactly where a thumb rests.
      */}
      <header
        ref={headerRef}
        className="sticky top-0 z-40 bg-sidebar text-sidebar-foreground lg:hidden"
      >
        <div className="relative flex h-16 items-center justify-between gap-2 px-5">
          <Link
            to="/app"
            viewTransition
            className="flex min-w-0 items-center rounded-lg px-1 py-1 outline-none focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring"
          >
            <span className="text-[21px] leading-[29px] font-semibold text-white">
              JobPilot
            </span>
          </Link>
          <ApiStatus
            surface="sidebar"
            className="absolute left-1/2 -translate-x-1/2 text-[10px] leading-[14px]"
          />
          <AccountMenu surface="bar" />
        </div>
      </header>

      <BottomNav className="lg:hidden" showAdmin={isSuperuser} />

      {/*
        The content column. `lg:pl-[72px]` clears the collapsed rail — the
        rail is `fixed`, so it takes no space in the flow, and the design
        file's own inset (node 47:33 at x=104 with a 72 px rail) is exactly
        a 32 px gutter on top of the rail's width.

        WS-43: the gutter is **constant**. Expanding the rail used to pad
        this column out to 240 px and reflow every element on screen — the
        violent layout shift the user pass caught. The design pushes the
        content with the rail (node `47:450` puts the body at x=272), but
        the push reflows the whole column on every toggle, so the recorded
        deviation (spec, WS-43) is the overlay: the expanded rail floats
        **over** this column with an elevated shadow, the gutter never
        moves, and navigation auto-collapses the rail so the screen is
        never left under the strip. The top bar is `sticky` and lives
        *inside* this column, so a long board scrolls under it without the
        rail moving.
      */}
      <div className="lg:pl-[72px]">
        <div className="hidden lg:block">
          <TopBar />
        </div>
        <main
          id="main-content"
          className="min-w-0 scroll-mt-[calc(var(--header-height,3.5rem)+1rem)]"
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
    </div>
  )
}
