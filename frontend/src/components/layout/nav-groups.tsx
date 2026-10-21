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

function NavItem({
  to,
  label,
  className,
}: {
  to: string
  label: string
  className?: string
}) {
  return (
    <NavLink
      to={to}
      className={({ isActive: exact }) =>
        cn(
          "relative inline-flex h-9 items-center rounded-lg px-3 text-sm transition-colors duration-150",
          exact
            ? "bg-accent font-medium text-primary"
            : "text-muted-foreground hover:bg-accent/60 hover:text-foreground",
          className
        )
      }
    >
      {({ isActive: exact }) => (
        <>
          {label}
          {exact ? (
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

/** The horizontal navigation, grouped. */
export function NavGroups({ className }: { className?: string }) {
  return (
    <nav
      aria-label="Screens"
      className={cn("flex items-center gap-1", className)}
    >
      {NAV_GROUPS.map((group, index) => (
        <div key={group.label} className="flex items-center gap-1">
          {index > 0 ? (
            <span aria-hidden="true" className="mx-2 h-4 w-px bg-border" />
          ) : null}
          <span className="hidden text-xs font-medium text-muted-foreground/80 sm:inline">
            {group.label}
          </span>
          {group.items.map((item) => (
            <NavItem key={item.to} to={item.to} label={item.label} />
          ))}
        </div>
      ))}
    </nav>
  )
}

/** The maintenance cluster, kept out of the operator's workflow. */
export function AdminNav({ className }: { className?: string }) {
  return (
    <nav
      aria-label="Administration"
      className={cn("flex items-center gap-1", className)}
    >
      {ADMIN_NAV.map((item) => (
        <NavItem
          key={item.to}
          to={item.to}
          label={item.label}
          className="text-muted-foreground/80"
        />
      ))}
    </nav>
  )
}
