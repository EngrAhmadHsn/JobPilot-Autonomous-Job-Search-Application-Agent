import { ChevronRight, House } from "lucide-react"
import { Link, useLocation } from "react-router-dom"
import { cn } from "cn"

import {
  PRIMARY_DESTINATIONS,
  SYSTEM_DESTINATIONS,
  navMatches,
  type NavChild,
  type NavDestination,
} from "./nav-groups"

import { AccountMenu } from "./account-menu"

/*
  The desktop navigation rail (WS-42).

  The design file draws it as a **72 px** forest strip (node `47:2`) holding
  icon-only destinations in 44×44 boxes, and node `47:450` shows the same
  strip expanded to **240 px** with the labels spelled out. Those are two
  states of one component, not two components — so this rail owns both and
  the shell mounts exactly one.

  Why the rail replaces the 240 px sidebar the console had: the approved
  design keeps the canvas wide. At 1440 px the content column is
  **1304 px** (1440 − 72 − 32×2), where the old labelled sidebar left
  1120 px. The nav is six destinations plus two system surfaces; six glyphs
  do not need 168 px of permanent width, and the label is available on
  hover, on focus, and permanently once expanded.

  Accessibility, which an icon-only rail gets wrong by default:
  - Every link carries an accessible name from its **text**, not from a
    `title` or `aria-label` that a sighted keyboard user cannot read. The
    label is present in the DOM at all times and only *visually* hidden
    when collapsed, so a screen reader hears "Home" whether the rail is
    open or shut (`sr-only`, never `hidden`).
  - A destination's own pages (Approvals, Tailor, …) are in the tree at
    every width and out of the picture at every width — the design draws
    child rows in neither rail state.
  - The collapsed glyph also carries a native `title` for the hover case;
    the custom CSS tooltip it replaces hung outside the strip and computed
    a horizontal scrollbar inside the scroll container.
  - The expand control is a real `<button>` with `aria-expanded` and
    `aria-controls`, and it is the **first** control in the rail so the
    collapse/expand affordance is reachable before the destinations.
  - The current destination takes `aria-current="page"`; a destination
    whose child page is open merely brightens, so exactly one row is
    "current".
*/

export function AppRail({
  showAdmin,
  expanded,
  onExpandedChange,
}: {
  showAdmin: boolean
  /**
   * Whether the rail is expanded to 240 px, **owned by the shell**.
   *
   * The shell has to know: the design shifts the content column with the
   * rail (`47:450` puts the body at x=272 — 240 px of rail plus the 32 px
   * gutter), so the same state that widens the rail widens the shell's
   * gutter. Lifting the state also keeps the width transition and the
   * content's padding transition on the same clock.
   */
  expanded: boolean
  onExpandedChange: (next: boolean) => void
}) {
  const pathname = useLocation().pathname

  const primary = PRIMARY_DESTINATIONS
  const system = SYSTEM_DESTINATIONS.filter(
    (destination) => !destination.superuserOnly || showAdmin
  )

  return (
    <aside
      id="app-rail"
      aria-label="Workspace navigation"
      className={cn(
        "fixed inset-y-0 left-0 z-40 hidden flex-col bg-sidebar text-sidebar-foreground lg:flex",
        "transition-[width] duration-200 ease-[var(--ease-soft)] motion-reduce:transition-none",
        expanded ? "w-60" : "w-[72px]"
      )}
    >
      {/* The brand mark, and the collapse/expand control. */}
      <div
        className={cn(
          "flex h-[70px] shrink-0 items-center",
          expanded ? "justify-between px-6" : "justify-center px-2"
        )}
      >
        <Link
          to="/app"
          viewTransition
          className="flex items-center outline-none focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-sidebar-ring"
        >
          {/*
            The design's brand is **lime Geist 22/600** in both states —
            "JP" collapsed (47:2), "JobPilot" expanded (49:2229). One span
            swaps its text; the accessible name stays "JobPilot" either way.
          */}
          <span
            className="text-[22px] leading-[32px] font-semibold tracking-tight text-sidebar-primary"
          >
            {expanded ? "JobPilot" : "JP"}
          </span>
          {!expanded ? <span className="sr-only">JobPilot</span> : null}
        </Link>
        <button
          type="button"
          onClick={() => onExpandedChange(!expanded)}
          aria-expanded={expanded}
          aria-controls="app-rail-destinations"
          className={cn(
            "grid size-8 shrink-0 place-items-center rounded-lg bg-rail-control text-sidebar-foreground",
            "transition-colors outline-none hover:bg-sidebar-hover",
            "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-sidebar-ring",
            expanded ? "flex" : "absolute top-[86px] left-1/2 -translate-x-1/2"
          )}
        >
          <ChevronRight
            aria-hidden="true"
            strokeWidth={2}
            className={cn(
              "size-4 transition-transform duration-200 motion-reduce:transition-none",
              expanded && "rotate-180"
            )}
          />
          <span className="sr-only">
            {expanded ? "Collapse navigation" : "Expand navigation"}
          </span>
        </button>
      </div>

      {/*
        Two navigation landmarks, named exactly as the console has always
        named them — **Screens** (the candidate's own journey) and **System**
        (the surfaces that maintain the platform). WS-42's rail draws them as
        one visual column, but they are two different kinds of destination and
        a screen reader user navigates by landmark: merging them into one
        unnamed group would make "jump to the system surfaces" impossible.
      */}
      <nav
        id="app-rail-destinations"
        aria-label="Screens"
        className={cn(
          "flex flex-col gap-3.5 overflow-y-auto overscroll-contain",
          // Both design states start the rows at y=130 (47:2, 47:450):
          // the 70 px brand row plus 56 px of space.
          "pt-14",
          expanded ? "px-3.5" : "items-center"
        )}
      >
        {primary.map((destination) => (
          <div key={destination.to} className="contents">
            <RailLink
              destination={destination}
              expanded={expanded}
              pathname={pathname}
            />
            {/*
              A destination's own pages stay in the accessibility tree at
              **every** width, and out of the picture at every width.

              The design draws neither state with child rows: the 72 px rail
              (`47:2`) has no room for a label, and the expanded rail
              (`47:450`) draws exactly six destinations — no indented list.
              But *removing* the links would take six routes out of the
              navigation entirely. `sr-only` keeps the contract (every route
              is one hop from the nav, the tests pin their presence) while
              both visual states match the design's row count.
            */}
            {destination.children
              ? destination.children.map((child) => (
                  <RailChildLink key={child.to} child={child} />
                ))
              : null}
          </div>
        ))}
      </nav>

      {/*
        The system group sits at the bottom of the rail, as the design draws
        it (`Nav:Operations` at y=840, far below the journey destinations).
        `mt-auto` puts it there without a magic offset, so the gap between the
        groups is the rail's own height minus its content — which is what makes
        the separation read as a different kind of thing.
      */}
      <nav
        aria-label="System"
        className={cn(
          "mt-auto flex flex-col gap-3.5",
          expanded ? "px-3.5" : "items-center"
        )}
      >
        {system.map((destination) => (
          <RailLink
            key={destination.to}
            destination={destination}
            expanded={expanded}
            pathname={pathname}
          />
        ))}
      </nav>

      {/*
        The rail's account footer (nodes 47:27 collapsed, 49:2253+2368
        expanded): a 36 px avatar — alone in the 72 px strip, beside the
        account's two-line identity block once there is room. The design's
        expanded footer reads name over "Account & preferences"; the honest
        equivalent of the name is the account's own e-mail.
      */}
      <div
        className={cn(
          "flex shrink-0 pb-4",
          expanded ? "px-6 pt-3" : "justify-center pt-3"
        )}
      >
        <AccountMenu surface="sidebar" compact={!expanded} />
      </div>
    </aside>
  )
}

/**
 * A destination's own page — present for assistive tech at every width,
 * visually hidden at every width (the design draws child rows in neither
 * rail state; see the call site).
 */
function RailChildLink({ child }: { child: NavChild }) {
  const pathname = useLocation().pathname
  const current = navMatches(child.match, pathname)
  return (
    <Link
      to={child.to}
      viewTransition
      aria-current={current ? "page" : undefined}
      className={cn(
        "flex h-8 items-center rounded-lg pr-3 pl-11 text-[13px] transition-colors",
        "outline-none focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-sidebar-ring",
        current
          ? "bg-sidebar-accent font-medium text-sidebar-accent-foreground"
          : "text-sidebar-muted hover:bg-sidebar-hover hover:text-sidebar-foreground",
        // Present for assistive tech, absent from the picture — both states.
        "sr-only"
      )}
    >
      <span className="truncate">{child.label}</span>
    </Link>
  )
}

/** One destination in the rail, collapsed or expanded. */
function RailLink({
  destination,
  expanded,
  pathname,
}: {
  destination: NavDestination
  expanded: boolean
  pathname: string
}) {
  const selfMatch = navMatches(destination.match, pathname)
  const childMatch = destination.children?.find((child) =>
    navMatches(child.match, pathname)
  )
  /*
    Exactly one row carries `aria-current`, and it is the **deepest** match.
    `/app/tracker` matches the Applications destination *and* its Tracker
    child, so the destination alone would claim a page its child is actually
    showing. Taking `selfMatch && !childMatch` reproduces the rule the
    expanded navigation has always used: the parent brightens (below), the
    child claims the page.
  */
  const current = selfMatch && !childMatch
  /*
    "Active" is broader than "current": a destination is active when it or
    any of its own pages is open. That is what lets the parent brighten while
    a child carries `aria-current` — the reader sees which part of the journey
    they are in *and* which exact page they are on, and no two elements claim
    to be the page.
  */
  const active = selfMatch || Boolean(childMatch)
  const Icon = destination.icon
  return (
    <Link
      to={destination.to}
      viewTransition
      aria-current={current ? "page" : undefined}
      data-active={active || undefined}
      /*
        The collapsed glyph's name: a native `title` (hover hint) plus the
        `sr-only` span the screen reader reads. The old custom CSS tooltip
        was an absolutely-positioned, nowrap span hanging outside the 72 px
        strip — inside a scroll container it computed a horizontal
        scrollbar for the whole rail. The design draws no tooltip in either
        state; its answer to "what does this glyph mean" is the expand
        affordance, and the native title covers the hover case.
      */
      title={expanded ? undefined : destination.label}
      className={cn(
        "relative flex items-center rounded-xl transition-colors duration-150 outline-none",
        "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-sidebar-ring",
        expanded ? "h-11 gap-3 px-3" : "size-11 justify-center",
        current
          ? "bg-sidebar-primary text-sidebar-primary-foreground"
          : active
            ? "bg-sidebar-hover font-medium text-sidebar-foreground"
            : "text-sidebar-foreground hover:bg-sidebar-hover"
      )}
    >
      <Icon
        aria-hidden="true"
        className="size-5 shrink-0"
        strokeWidth={current ? 2 : 1.6}
      />
      <span className={cn("truncate text-sm", !expanded && "sr-only")}>
        {destination.label}
      </span>
    </Link>
  )
}

/** The mark the phone chrome uses, kept alongside the rail's own. */
export const RAIL_HOME_ICON = House
