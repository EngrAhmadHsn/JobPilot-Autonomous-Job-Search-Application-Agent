import { Search } from "lucide-react"
import { Link, useLocation } from "react-router-dom"
import { cn } from "cn"

import { useCurrentProfileId } from "@/lib/profile"

import { ApiStatus } from "./api-status"
import { AccountMenu } from "./account-menu"
import { ProfileChip } from "./profile-chip"

/*
  The desktop top bar (WS-42), from the design file's node `47:28`.

  It is 68 px tall, paper-coloured, and carries four things left to right:

  - the **breadcrumb** (`WORKSPACE / HOME`), which is the one piece of
    chrome that tells a reader where they are without looking at the rail.
    It is *not* a `<nav>` landmark: there is one destination per screen, the
    rail already owns navigation, and a second navigation landmark for a
    two-word label would be noise in a screen reader's landmark list.
  - the environment marker, where the design file draws its
    `Concept · example data` annotation. The console shows the **real**
    environment instead — this is a live product surface, and a label
    claiming the data is an example would be a lie in the other direction.
  - the workspace search affordance with its real shortcut hint.
  - the account control, which is the existing `AccountMenu` so sign-out,
    theme and motion stay in one place.

  The bar is `sticky` so the breadcrumb survives a long board, and it is
  hidden below `lg` — the phone chrome has its own header.
*/

/** The screen names the breadcrumb can say, keyed by route prefix. */
const SECTION_LABELS: { prefix: string; label: string }[] = [
  { prefix: "/app/matches", label: "Discover" },
  { prefix: "/app/tailor", label: "Resume Studio" },
  { prefix: "/app/approvals", label: "Review" },
  { prefix: "/app/tracker", label: "Applications" },
  { prefix: "/app/profile", label: "Profile & Documents" },
  { prefix: "/app/resume", label: "Profile & Documents" },
  { prefix: "/app/activity", label: "Activity" },
  { prefix: "/app/operations", label: "Operations" },
  { prefix: "/app/admin", label: "Administration" },
]

/** The breadcrumb's second segment for a pathname. */
export function sectionLabelFor(pathname: string): string {
  const match = SECTION_LABELS.find(
    (entry) =>
      pathname === entry.prefix || pathname.startsWith(`${entry.prefix}/`)
  )
  return match?.label ?? "Home"
}

export function TopBar({ className }: { className?: string }) {
  const pathname = useLocation().pathname
  const section = sectionLabelFor(pathname)
  const profileId = useCurrentProfileId()

  return (
    <header
      className={cn(
        "sticky top-0 z-30 hidden h-[68px] shrink-0 items-center gap-4",
        "border-b border-border-surface bg-card px-8 lg:flex",
        className
      )}
    >
      {/*
        The breadcrumb. `aria-label` on a plain span would be ignored, so the
        text is read in order and the separator is `aria-hidden` — a screen
        reader says "Workspace Home", never "Workspace slash Home".
      */}
      <p className="type-breadcrumb text-muted-foreground">
        <span>Workspace</span>
        <span aria-hidden="true" className="mx-2">
          /
        </span>
        <span className="text-foreground">{section}</span>
      </p>

      <div className="ml-auto flex items-center gap-5">
        {/*
          The environment marker, in the design's own position. It reports
          what the API says about itself; when the API is unreachable the
          marker says that instead of claiming a healthy environment.
        */}
        <ApiStatus className="hidden xl:inline-flex" />

        {/*
          The candidate profile every screen works against. It is chrome, not
          a screen's content: a reader needs to know *whose* matches and
          documents they are looking at before they read a single number.
        */}
        <ProfileChip profileId={profileId} className="hidden md:inline-flex" />

        {/*
          The way into the workspace's search.

          The design file draws `Search anywhere ⌘ K` (node `47:30`). The
          honest version of that affordance is a **link to the search that
          exists** — Discover's field, which suggests from the real corpus and
          ranks the stored jobs. What it must not be is a button that fakes a
          palette: an earlier draft of this control called
          `window.location.assign` on click, which was a full document reload
          wearing a search button's clothes — it dropped the query cache,
          re-fetched the identity and flashed the whole console, and its label
          promised a ⌘K shortcut that did not exist.

          So: a real link, client-side, no reload; and no shortcut hint,
          because showing `⌘ K` for a binding that is not wired would be a
          lie about the product. When a command palette is built, the hint
          comes back with it.
        */}
        <Link
          to="/app/matches"
          viewTransition
          className={cn(
            "hidden items-center gap-2 rounded-lg px-2 py-1.5 text-xs text-muted-foreground",
            "transition-colors outline-none hover:bg-accent hover:text-foreground sm:inline-flex",
            "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring"
          )}
        >
          <Search aria-hidden="true" className="size-3.5" strokeWidth={1.8} />
          <span>Search jobs</span>
        </Link>

        <AccountMenu surface="bar" />
      </div>
    </header>
  )
}
