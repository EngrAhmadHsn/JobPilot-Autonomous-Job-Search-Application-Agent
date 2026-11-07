import { cn } from "cn"
import { NavLink } from "react-router-dom"

import { stagger } from "@/lib/stagger"

/**
 * The navigation, grouped by what the operator is doing.
 *
 * The groups are the workflow: **overview** (where you are), **discover**
 * (find work), **prepare** (build an application), **track** (follow what
 * happened, and watch the agent). Operations and Administration are a
 * separate, quieter cluster — they maintain the platform rather than being
 * part of the operator's own workflow, so they should not read as equal
 * steps in it.
 *
 * Every destination is under `/app`, because the console now lives behind
 * a public landing page. It has two shapes: a horizontal bar on a wide
 * screen, and the items of a drawer on a narrow one. The grouping and the
 * wording are the same in both; only the arrangement changes.
 */
export const NAV_GROUPS = [
  {
    /*
      The first group has no heading: its one item is "Overview", and a
      heading that repeats the item beneath it is noise. An empty label
      renders no heading at all, in either shape.
    */
    label: "",
    items: [{ to: "/app", label: "Overview", end: true }],
  },
  {
    label: "Discover",
    items: [
      { to: "/app/resume", label: "Resume" },
      { to: "/app/profile", label: "Profile" },
      { to: "/app/matches", label: "Matches" },
      { to: "/app/tailor", label: "Tailor" },
    ],
  },
  {
    label: "Prepare",
    items: [{ to: "/app/approvals", label: "Approvals" }],
  },
  {
    label: "Track",
    items: [
      { to: "/app/tracker", label: "Tracker" },
      { to: "/app/activity", label: "Activity" },
    ],
  },
] as const

export const ADMIN_NAV = [
  { to: "/app/operations", label: "Operations" },
  { to: "/app/admin", label: "Administration", superuserOnly: true },
] as const

/**
 * The groups with each destination's index in the whole list.
 *
 * The index is the item's place in the sequence, and the sequence is what
 * the drawer's arrival is built on — the destinations rise one after
 * another, in the order they are read. It is computed once, at module
 * level, because the groups never change.
 */
const INDEXED_GROUPS = NAV_GROUPS.map((group, groupIndex) => {
  const first = NAV_GROUPS.slice(0, groupIndex).reduce(
    (total, earlier) => total + earlier.items.length,
    0
  )
  return {
    label: group.label,
    items: group.items.map((item, index) => ({
      ...item,
      index: first + index,
    })),
  }
})

type NavVariant = "horizontal" | "vertical"

function NavItem({
  to,
  label,
  variant,
  onNavigate,
  className,
  index,
  end,
}: {
  to: string
  label: string
  variant: NavVariant
  onNavigate?: () => void
  className?: string
  index?: number
  end?: boolean
}) {
  const vertical = variant === "vertical"

  return (
    <NavLink
      to={to}
      end={end}
      /*
        The View Transitions API animates between the two screens: the
        browser captures the old one and the new one and crossfades them,
        so the exit runs even though the router has already swapped the
        tree. React Router turns it on per link and falls back to an
        instant swap where the browser has no such API.
      */
      viewTransition
      onClick={onNavigate}
      className={({ isActive }) =>
        cn(
          "relative inline-flex items-center rounded-lg transition-colors duration-150",
          vertical ? "h-11 w-full px-3 text-[15px]" : "h-9 px-3 text-sm",
          vertical ? stagger(index ?? 0).className : undefined,
          isActive
            ? "bg-accent font-medium text-primary"
            : "text-muted-foreground hover:bg-accent/60 hover:text-foreground",
          className
        )
      }
    >
      {({ isActive }) => (
        <>
          {label}
          {!vertical && isActive ? (
            <span
              aria-hidden="true"
              className="absolute inset-x-3 -bottom-px h-0.5 rounded-full bg-primary"
            />
          ) : null}
        </>
      )}
    </NavLink>
  )
}

/** The navigation, in one of its two shapes. */
export function NavGroups({
  variant = "horizontal",
  onNavigate,
  className,
}: {
  variant?: NavVariant
  onNavigate?: () => void
  className?: string
}) {
  const vertical = variant === "vertical"

  if (vertical) {
    /*
      The drawer arrives as a sequence: the destinations rise one after
      another, so the operator's eye follows the panel in rather than
      meeting a list that is simply there.
    */
    return (
      <nav aria-label="Screens" className={cn("space-y-5", className)}>
        {INDEXED_GROUPS.map((group) => (
          <div key={group.label || "primary"} className="space-y-1">
            {group.label ? (
              <p className="px-3 pb-1 text-xs font-medium text-muted-foreground/80">
                {group.label}
              </p>
            ) : null}
            {group.items.map((item) => (
              <NavItem
                key={item.to}
                to={item.to}
                label={item.label}
                variant={variant}
                onNavigate={onNavigate}
                index={item.index}
                end={"end" in item ? item.end : undefined}
              />
            ))}
          </div>
        ))}
      </nav>
    )
  }

  return (
    <nav
      aria-label="Screens"
      className={cn("flex flex-wrap items-center gap-x-1 gap-y-1", className)}
    >
      {NAV_GROUPS.map((group, index) => (
        <div key={group.label || "primary"} className="flex flex-wrap items-center gap-1">
          {index > 0 ? (
            <span aria-hidden="true" className="mx-2 h-4 w-px bg-border" />
          ) : null}
          {group.label ? (
            <span className="text-xs font-medium text-muted-foreground/80">
              {group.label}
            </span>
          ) : null}
          {group.items.map((item) => (
            <NavItem
              key={item.to}
              to={item.to}
              label={item.label}
              variant={variant}
              onNavigate={onNavigate}
              end={"end" in item ? item.end : undefined}
            />
          ))}
        </div>
      ))}
    </nav>
  )
}

/**
 * The maintenance cluster, kept out of the operator's workflow.
 *
 * The **Administration** destination is shown only to a superuser. That is
 * a courtesy, not a control: hiding a link stops a curious click, and the
 * route behind it refuses a non-superuser on the **server** regardless of
 * what this renders. A frontend flag that *was* the control would be a
 * frontend flag that could be edited in a console.
 */
export function AdminNav({
  variant = "horizontal",
  onNavigate,
  className,
  showAdmin = false,
}: {
  variant?: NavVariant
  onNavigate?: () => void
  className?: string
  showAdmin?: boolean
}) {
  const vertical = variant === "vertical"
  const items = ADMIN_NAV.filter((item) => !("superuserOnly" in item) || showAdmin)

  return (
    <nav
      aria-label="Administration"
      className={cn(
        vertical ? "space-y-1" : "flex items-center gap-1",
        className
      )}
    >
      {items.map((item) => (
        <NavItem
          key={item.to}
          to={item.to}
          label={item.label}
          variant={variant}
          onNavigate={onNavigate}
          className={vertical ? undefined : "text-muted-foreground/80"}
        />
      ))}
    </nav>
  )
}
