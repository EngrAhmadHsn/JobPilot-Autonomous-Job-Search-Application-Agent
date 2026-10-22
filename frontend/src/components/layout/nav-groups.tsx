import { cn } from "cn"
import { NavLink } from "react-router-dom"

/**
 * The navigation, grouped by what the operator is doing.
 *
 * The groups are the workflow: **discover** (find work), **prepare** (build
 * an application), **track** (follow what happened). Operations is a
 * separate, quieter cluster — it maintains the corpus rather than being
 * part of an application, and it should not read as an equal step in the
 * operator's own workflow.
 *
 * It has two shapes: a horizontal bar on a wide screen, and the items of a
 * drawer on a narrow one. The grouping and the wording are the same in
 * both; only the arrangement changes.
 */
export const NAV_GROUPS = [
  {
    label: "Discover",
    items: [
      { to: "/resume", label: "Resume" },
      { to: "/matches", label: "Matches" },
      { to: "/tailor", label: "Tailor" },
    ],
  },
  {
    label: "Prepare",
    items: [{ to: "/approvals", label: "Approvals" }],
  },
  {
    label: "Track",
    items: [{ to: "/tracker", label: "Tracker" }],
  },
] as const

export const ADMIN_NAV = [{ to: "/operations", label: "Operations" }] as const

type NavVariant = "horizontal" | "vertical"

function NavItem({
  to,
  label,
  variant,
  onNavigate,
  className,
}: {
  to: string
  label: string
  variant: NavVariant
  onNavigate?: () => void
  className?: string
}) {
  const vertical = variant === "vertical"

  return (
    <NavLink
      to={to}
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
    return (
      <nav aria-label="Screens" className={cn("space-y-5", className)}>
        {NAV_GROUPS.map((group) => (
          <div key={group.label} className="space-y-1">
            <p className="px-3 pb-1 text-xs font-medium text-muted-foreground/80">
              {group.label}
            </p>
            {group.items.map((item) => (
              <NavItem
                key={item.to}
                to={item.to}
                label={item.label}
                variant={variant}
                onNavigate={onNavigate}
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
        <div key={group.label} className="flex flex-wrap items-center gap-1">
          {index > 0 ? (
            <span aria-hidden="true" className="mx-2 h-4 w-px bg-border" />
          ) : null}
          <span className="text-xs font-medium text-muted-foreground/80">
            {group.label}
          </span>
          {group.items.map((item) => (
            <NavItem
              key={item.to}
              to={item.to}
              label={item.label}
              variant={variant}
              onNavigate={onNavigate}
            />
          ))}
        </div>
      ))}
    </nav>
  )
}

/** The maintenance cluster, kept out of the operator's workflow. */
export function AdminNav({
  variant = "horizontal",
  onNavigate,
  className,
}: {
  variant?: NavVariant
  onNavigate?: () => void
  className?: string
}) {
  const vertical = variant === "vertical"

  return (
    <nav
      aria-label="Administration"
      className={cn(
        vertical ? "space-y-1" : "flex items-center gap-1",
        className
      )}
    >
      {ADMIN_NAV.map((item) => (
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
