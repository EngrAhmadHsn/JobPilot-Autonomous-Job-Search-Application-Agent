import { Link, matchPath, useLocation } from "react-router-dom"
import { cn } from "cn"

import { BOTTOM_NAV_DESTINATIONS } from "./nav-groups"

/*
  The phone's navigation (WS-34).

  A bottom bar holding the **five** journey destinations the directive
  allows (Home, Discover, Applications, Resume Studio, Profile &
  Documents); Activity and the System surfaces live in the drawer, which
  holds every destination. The bar is the `lg:hidden` complement of the
  desktop sidebar — at any real width exactly one of them is rendered,
  so a screen reader never meets the same destination twice.

  The active state is a forest pill on the paper surface — the same
  "one clearly rendered selected destination" as the sidebar, inverted
  for the light background. The bar keeps its own height clear of the
  platform's safe-area inset, and `index.css` publishes the matching
  `scroll-padding-block-end` so focus never lands underneath it.
*/
export function BottomNav({ className }: { className?: string }) {
  const { pathname } = useLocation()

  return (
    <nav
      aria-label="Primary"
      className={cn(
        "fixed inset-x-0 bottom-0 z-40 border-t border-border bg-card pb-[env(safe-area-inset-bottom,0px)]",
        className
      )}
    >
      <ul className="grid grid-cols-5">
        {BOTTOM_NAV_DESTINATIONS.map((destination) => {
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
                  "flex min-w-0 flex-1 flex-col items-center justify-center gap-0.5 px-1 py-2.5 transition-colors duration-150 outline-none",
                  "focus-visible:outline-2 focus-visible:-outline-offset-8 focus-visible:outline-ring",
                  family
                    ? "text-forest"
                    : "text-muted-foreground hover:text-foreground"
                )}
              >
                <span
                  aria-hidden="true"
                  className={cn(
                    "flex h-7 w-11 items-center justify-center rounded-full transition-colors duration-150",
                    family && "bg-forest-soft"
                  )}
                >
                  <Icon
                    className="size-[20px]"
                    strokeWidth={family ? 2 : 1.8}
                  />
                </span>
                <span className="max-w-full truncate text-[11px] leading-tight">
                  {destination.bottomNavLabel ?? destination.label}
                </span>
              </Link>
            </li>
          )
        })}
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
