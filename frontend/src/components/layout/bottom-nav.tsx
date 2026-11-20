import { Link, matchPath, useLocation } from "react-router-dom"
import { cn } from "cn"

import { BOTTOM_NAV_DESTINATIONS } from "./nav-groups"
import { NavDrawer } from "./nav-drawer"

/*
  The phone's navigation, from the design's mobile frames (nodes 49:10379
  and 49:7677): a 64 px paper bar with **three** destinations and a fourth
  "More" slot that opens the drawer holding everything else.

  The active state is the design's own: the same forest ink on every slot,
  with the current destination's label at weight 600 — the glyph carries no
  pill. `aria-current` still marks exactly one destination for the screen
  reader, and the bar keeps its own height clear of the platform's
  safe-area inset, with `index.css` publishing the matching
  `scroll-padding-block-end` so focus never lands underneath it.

  The bar is the `lg:hidden` complement of the desktop rail — at any real
  width exactly one of them is rendered, so a screen reader never meets the
  same destination twice.
*/

/** The three destinations the design's bar carries (the rest live in the drawer). */
const BAR_ROUTES = new Set(["/app", "/app/matches", "/app/tracker"])

export function BottomNav({
  className,
  showAdmin = false,
}: {
  className?: string
  showAdmin?: boolean
}) {
  const { pathname } = useLocation()
  const destinations = BOTTOM_NAV_DESTINATIONS.filter((destination) =>
    BAR_ROUTES.has(destination.to)
  )

  return (
    <nav
      aria-label="Primary"
      className={cn(
        "fixed inset-x-0 bottom-0 z-40 border-t border-border bg-card pb-[env(safe-area-inset-bottom,0px)]",
        className
      )}
    >
      <ul className="grid grid-cols-4">
        {destinations.map((destination) => {
          const exact = matchPath(
            { path: destination.to, end: destination.to === "/app" },
            pathname
          )
          const family =
            exact !== null || navMatchesFamily(destination, pathname)
          const Icon = destination.icon

          return (
            <li key={destination.to} className="flex">
              <Link
                to={destination.to}
                viewTransition
                aria-current={family ? (exact ? "page" : "true") : undefined}
                data-active={family || undefined}
                className={cn(
                  "flex min-w-0 flex-1 flex-col items-center justify-center gap-0.5 px-1 py-2.5 text-forest transition-colors duration-150 outline-none",
                  "focus-visible:outline-2 focus-visible:-outline-offset-8 focus-visible:outline-ring"
                )}
              >
                <Icon
                  aria-hidden="true"
                  className="size-5"
                  strokeWidth={1.7}
                />
                <span
                  className={cn(
                    "max-w-full truncate text-[10px] leading-[14px]",
                    family ? "font-semibold" : "font-normal"
                  )}
                >
                  {destination.bottomNavLabel ?? destination.label}
                </span>
              </Link>
            </li>
          )
        })}
        {/*
          The fourth slot opens the drawer — the design's `Nav:Expand`
          (node 49:10386). It is a button, not a link: it reveals the
          destinations rather than travelling to one.
        */}
        <li className="flex">
          <NavDrawer showAdmin={showAdmin} variant="nav-item" />
        </li>
      </ul>
    </nav>
  )
}

/**
 * Is any of the destination's family (itself or a child page) in view?
 * The bottom bar represents the destination, not one of its pages, so
 * the whole family lights the marker.
 */
function navMatchesFamily(
  destination: (typeof BOTTOM_NAV_DESTINATIONS)[number],
  pathname: string
): boolean {
  return (
    destination.match.some(
      (pattern) => matchPath(pattern, pathname) !== null
    ) ||
    (destination.children ?? []).some((child) =>
      child.match.some((pattern) => matchPath(pattern, pathname) !== null)
    )
  )
}
