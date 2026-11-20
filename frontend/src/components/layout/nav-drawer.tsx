import { Menu } from "lucide-react"
import { useState } from "react"

import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
  SheetTrigger,
} from "@/components/ui/sheet"

import { AccountMenu } from "./account-menu"
import { NavGroups, SystemNav } from "./nav-groups"
import { BrandMark } from "./brand-mark"

/**
 * The navigation drawer (WS-34).
 *
 * On a phone the six journey destinations cannot all sit in a bottom
 * bar, and the System surfaces never belonged there. The drawer is the
 * "more" surface: it holds **every** destination the sidebar holds —
 * the journey group including Activity, and the labelled System group —
 * in a panel that slides in from the left, scrolls inside its own box
 * (`overflow-y-auto` with `overscroll-behavior: contain`, so scrolling
 * past its end never scrolls the page behind), closes when the operator
 * picks a destination, and returns focus to the trigger on close (the
 * Base UI dialog's own focus management).
 */
export function NavDrawer({
  showAdmin = false,
  variant = "top",
}: {
  showAdmin?: boolean
  /**
   * `top` — the standalone hamburger button the old phone top bar used.
   * `nav-item` — the bottom bar's fourth slot (the design's `Nav:Expand`,
   * node 49:10386): a glyph-over-label control matching the bar's three
   * links, opening the same drawer.
   */
  variant?: "top" | "nav-item"
}) {
  const [open, setOpen] = useState(false)

  return (
    <Sheet open={open} onOpenChange={setOpen}>
      {variant === "nav-item" ? (
        <SheetTrigger className="flex min-w-0 flex-1 flex-col items-center justify-center gap-0.5 px-1 py-2.5 text-forest transition-colors duration-150 outline-none focus-visible:outline-2 focus-visible:-outline-offset-8 focus-visible:outline-ring">
          <Menu aria-hidden="true" className="size-5" strokeWidth={1.7} />
          <span className="text-[10px] leading-[14px]">More</span>
        </SheetTrigger>
      ) : (
        /*
          `size-11` is 44px. Below `lg` this button is the console's only
          path to the drawer's destinations, so a thumb that misses it has
          no way to reach them. It was `size-9`.
        */
        <SheetTrigger
          aria-label="Open the navigation menu"
          className="inline-flex size-11 shrink-0 items-center justify-center rounded-lg border border-border bg-card text-foreground transition-colors duration-150 hover:bg-accent/60 lg:hidden"
        >
          <Menu className="size-4" strokeWidth={1.8} aria-hidden="true" />
        </SheetTrigger>
      )}

      {/*
        The design's mobile drawer (node 49:11961) is the expanded rail as a
        forest panel: the same `#1b3831` ground, the lime active pill, the
        account block at the foot. Nothing about "a menu opened from a
        phone" makes it a paper surface.
      */}
      <SheetContent
        side="left"
        className="w-[290px] gap-0 border-none bg-sidebar text-sidebar-foreground p-0 sm:max-w-[290px]"
      >
        <SheetHeader className="border-b border-sidebar-hover p-4">
          <div className="flex items-center gap-3">
            <BrandMark />
            <div className="leading-tight">
              <SheetTitle className="font-heading text-[15px] font-semibold tracking-tight text-sidebar-foreground">
                JobPilot
              </SheetTitle>
              <SheetDescription className="text-[11px] text-sidebar-muted">
                The agentic job applier
              </SheetDescription>
            </div>
          </div>
        </SheetHeader>

        <div className="flex flex-1 flex-col overflow-y-auto overscroll-contain p-4">
          <NavGroups
            surface="forest"
            staggerItems
            onNavigate={() => setOpen(false)}
          />

          <div className="mt-2 border-t border-sidebar-hover pt-2">
            <SystemNav
              surface="forest"
              showAdmin={showAdmin}
              onNavigate={() => setOpen(false)}
            />
          </div>
        </div>

        {/*
          The account block, as the design draws it (avatar, name, caption)
          — the same account control the chrome carries elsewhere.
        */}
        <div className="flex items-center gap-3 border-t border-sidebar-hover p-4">
          <AccountMenu surface="sidebar" />
        </div>
      </SheetContent>
    </Sheet>
  )
}
