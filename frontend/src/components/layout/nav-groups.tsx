import {
  Briefcase,
  Compass,
  FilePenLine,
  History,
  House,
  ServerCog,
  ShieldCheck,
  UserRound,
  type LucideIcon,
} from "lucide-react"
import { Link, matchPath, useLocation } from "react-router-dom"
import { cn } from "cn"

import { stagger } from "@/lib/stagger"

/*
  The navigation (WS-34), mapped onto the master prompt's §5 information
  architecture — the six destinations of the job-search journey, and the
  two technical surfaces in a secondary **System** group.

  The conceptual destinations are mapped onto the routes that already
  exist, so **no deep link changes**:

  - Home            → `/app`
  - Discover        → `/app/matches` and `/app/matches/:jobId`
  - Applications    → `/app/tracker*` and `/app/approvals`
  - Resume Studio   → `/app/tailor*`
  - Profile & Docs  → `/app/profile` and `/app/resume`
  - Activity        → `/app/activity`
  - System: Operations → `/app/operations`; Administration → `/app/admin`

  Where one destination owns more than one page, its pages render as
  indented children beneath it, so every route that existed yesterday is
  still exactly one click away. The active treatment follows the URL:
  exactly one row — the deepest match — carries `aria-current="page"` and
  the filled pill; the destination above it merely brightens, so there is
  always **one** clearly rendered selected item.
*/

/**
 * One `matchPath` pattern. A bare string matches by prefix (so
 * `"/app/tracker"` covers the detail route too); `{ end: true }` pins the
 * pattern to the exact path.
 */
type NavPattern = string | { path: string; end: true }

/** A page inside a destination (rendered indented under its parent). */
export interface NavChild {
  to: string
  label: string
  /** `matchPath` patterns; the child is current when one matches. */
  match: NavPattern[]
}

export interface NavDestination {
  to: string
  label: string
  icon: LucideIcon
  /** `matchPath` patterns; the destination is active when one matches. */
  match: NavPattern[]
  /** Pages of this destination, shown indented beneath it. */
  children?: NavChild[]
  /**
   * A courtesy, not a control: hiding the link stops a curious click,
   * and the route behind it refuses a non-superuser on the **server**
   * regardless of what this renders.
   */
  superuserOnly?: boolean
  /** Include in the mobile bottom navigation (≤5 destinations). */
  inBottomNav?: boolean
  /** The shortened label the bottom navigation's slots can hold. */
  bottomNavLabel?: string
}

export const PRIMARY_DESTINATIONS: NavDestination[] = [
  {
    to: "/app",
    label: "Home",
    icon: House,
    // The exact route only — every other /app path belongs elsewhere.
    match: [{ path: "/app", end: true }],
    inBottomNav: true,
    bottomNavLabel: "Home",
  },
  {
    to: "/app/matches",
    label: "Discover",
    icon: Compass,
    match: ["/app/matches", "/app/matches/:jobId"],
    children: [
      {
        to: "/app/matches",
        label: "Matches",
        match: [{ path: "/app/matches", end: true }],
      },
    ],
    inBottomNav: true,
    bottomNavLabel: "Discover",
  },
  {
    to: "/app/tracker",
    label: "Applications",
    icon: Briefcase,
    match: ["/app/tracker", "/app/approvals"],
    children: [
      { to: "/app/tracker", label: "Tracker", match: ["/app/tracker"] },
      { to: "/app/approvals", label: "Approvals", match: ["/app/approvals"] },
    ],
    inBottomNav: true,
    bottomNavLabel: "Apply",
  },
  {
    to: "/app/tailor",
    label: "Resume Studio",
    icon: FilePenLine,
    match: ["/app/tailor"],
    children: [
      {
        to: "/app/tailor",
        label: "Tailor",
        match: [{ path: "/app/tailor", end: true }],
      },
    ],
    inBottomNav: true,
    bottomNavLabel: "Studio",
  },
  {
    to: "/app/profile",
    label: "Profile & Documents",
    icon: UserRound,
    match: ["/app/profile", "/app/resume"],
    children: [
      {
        to: "/app/profile",
        label: "Profile",
        match: [{ path: "/app/profile", end: true }],
      },
      { to: "/app/resume", label: "Documents", match: ["/app/resume"] },
    ],
    inBottomNav: true,
    bottomNavLabel: "Profile",
  },
  {
    to: "/app/activity",
    label: "Activity",
    icon: History,
    match: ["/app/activity"],
  },
]

/*
  The technical surfaces (§5): they maintain the platform rather than
  being part of the operator's own workflow, so they read as a labelled
  secondary group, never as equal steps in the journey.
*/
export const SYSTEM_DESTINATIONS: NavDestination[] = [
  {
    to: "/app/operations",
    label: "Operations",
    icon: ServerCog,
    match: ["/app/operations"],
  },
  {
    to: "/app/admin",
    label: "Administration",
    icon: ShieldCheck,
    match: ["/app/admin"],
    superuserOnly: true,
  },
]

/** The destinations the mobile bottom navigation holds (≤5). */
export const BOTTOM_NAV_DESTINATIONS = PRIMARY_DESTINATIONS.filter(
  (destination) => destination.inBottomNav
)

/** Does the pathname match any of the patterns? */
export function navMatches(patterns: NavPattern[], pathname: string): boolean {
  return patterns.some((pattern) => matchPath(pattern, pathname) !== null)
}

/*
  The rows.

  Both shapes — the forest sidebar and the paper drawer — render the same
  destinations with the same wording and the same "you are here" marker;
  only the surface's colours change. On the forest sidebar the theme's
  `--ring` (forest) would be invisible, so focus moves to the sidebar's
  own lime ring token.
*/

function DestinationRow({
  label,
  to,
  icon: Icon,
  onNavigate,
  surface,
  child,
  active,
  current,
  index,
}: {
  label: string
  to: string
  icon?: LucideIcon
  onNavigate?: () => void
  surface: "forest" | "paper"
  /** Rendered as an indented child row. */
  child?: boolean
  active: boolean
  current: boolean
  index?: number
}) {
  const forest = surface === "forest"

  return (
    <Link
      to={to}
      viewTransition
      onClick={onNavigate}
      aria-current={current ? "page" : undefined}
      data-active={active || undefined}
      className={cn(
        "relative flex items-center rounded-lg transition-colors duration-150 outline-none",
        forest
          ? cn(
              "mx-2 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-sidebar-ring",
              child
                ? "h-8 gap-2 pr-3 pl-9 text-[13px]"
                : "h-10 gap-2.5 px-3 text-sm",
              current
                ? "bg-sidebar-accent font-medium text-sidebar-accent-foreground"
                : active
                  ? "font-medium text-sidebar-foreground"
                  : "text-sidebar-muted hover:bg-sidebar-hover hover:text-sidebar-foreground"
            )
          : cn(
              child ? "h-8 pr-3 pl-9 text-[13px]" : "h-11 px-3 text-[15px]",
              current
                ? "bg-accent font-medium text-primary"
                : "text-muted-foreground hover:bg-accent/60 hover:text-foreground"
            ),
        index !== undefined && !child ? stagger(index).className : undefined
      )}
    >
      {Icon && !child ? (
        <Icon
          aria-hidden="true"
          className="size-[18px] shrink-0"
          strokeWidth={current || active ? 2 : 1.8}
        />
      ) : null}
      <span className="truncate">{label}</span>
    </Link>
  )
}

function Destination({
  destination,
  onNavigate,
  surface,
  pathname,
  index,
}: {
  destination: NavDestination
  onNavigate?: () => void
  surface: "forest" | "paper"
  pathname: string
  index?: number
}) {
  const children = destination.children ?? []
  const currentChild = children.find((child) =>
    navMatches(child.match, pathname)
  )
  const selfMatch = navMatches(destination.match, pathname)
  // The parent defers to its child when a child is the page in view, so
  // exactly one row in the group carries the pill and aria-current.
  const current = selfMatch && !currentChild
  const active = selfMatch || currentChild !== undefined

  return (
    <li className="space-y-0.5">
      <DestinationRow
        label={destination.label}
        to={destination.to}
        icon={destination.icon}
        onNavigate={onNavigate}
        surface={surface}
        active={active}
        current={current}
        index={index}
      />
      {children.length > 0 ? (
        <ul className="space-y-0.5">
          {children.map((child) => (
            <li key={`${child.to} ${child.label}`}>
              <DestinationRow
                label={child.label}
                to={child.to}
                onNavigate={onNavigate}
                surface={surface}
                child
                active={navMatches(child.match, pathname)}
                current={currentChild === child}
              />
            </li>
          ))}
        </ul>
      ) : null}
    </li>
  )
}

function VerticalNav({
  destinations,
  onNavigate,
  surface,
  label,
  groupLabel,
  staggerItems = false,
  className,
}: {
  destinations: NavDestination[]
  onNavigate?: () => void
  surface: "forest" | "paper"
  label: string
  /** An optional visible group heading (the System group's label). */
  groupLabel?: string
  staggerItems?: boolean
  className?: string
}) {
  const { pathname } = useLocation()

  return (
    <nav aria-label={label} className={cn("space-y-1", className)}>
      {groupLabel ? (
        <p
          className={cn(
            "px-3 pt-4 pb-1 text-xs font-medium",
            surface === "forest"
              ? "text-sidebar-muted"
              : "text-muted-foreground/80"
          )}
        >
          {groupLabel}
        </p>
      ) : null}
      <ul className="space-y-0.5">
        {destinations.map((destination, index) => (
          <Destination
            key={`${destination.to} ${destination.label}`}
            destination={destination}
            onNavigate={onNavigate}
            surface={surface}
            pathname={pathname}
            index={staggerItems ? index : undefined}
          />
        ))}
      </ul>
    </nav>
  )
}

/**
 * The primary group, in the sidebar (forest) or the drawer (paper).
 *
 * The destinations rise one after another in the **drawer** — the panel
 * arrives as a sequence and the operator's eye follows it in. The
 * persistent sidebar does not animate: navigation chrome is seen every
 * minute, and a re-entrance on every mount is motion that performs
 * rather than answers.
 */
export function NavGroups({
  onNavigate,
  surface = "paper",
  staggerItems = false,
  className,
}: {
  onNavigate?: () => void
  surface?: "forest" | "paper"
  staggerItems?: boolean
  className?: string
}) {
  return (
    <VerticalNav
      destinations={PRIMARY_DESTINATIONS}
      onNavigate={onNavigate}
      surface={surface}
      label="Screens"
      staggerItems={staggerItems}
      className={className}
    />
  )
}

/**
 * The System group (WS-34): Operations and Administration, set apart from
 * the journey. `showAdmin` filters the Administration link for a
 * non-superuser; the server's authorization stays the real control.
 */
export function SystemNav({
  onNavigate,
  surface = "paper",
  showAdmin = false,
  className,
}: {
  onNavigate?: () => void
  surface?: "forest" | "paper"
  showAdmin?: boolean
  className?: string
}) {
  const destinations = SYSTEM_DESTINATIONS.filter(
    (destination) => !destination.superuserOnly || showAdmin
  )
  if (destinations.length === 0) return null

  return (
    <VerticalNav
      destinations={destinations}
      onNavigate={onNavigate}
      surface={surface}
      label="System"
      groupLabel="System"
      className={className}
    />
  )
}
