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

import { ApiStatus } from "./api-status"
import { NavGroups, SystemNav } from "./nav-groups"
import { BrandMark } from "./brand-mark"
import { ProfileChip } from "./profile-chip"
import { useCurrentProfileId } from "@/lib/profile"

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
export function NavDrawer({ showAdmin = false }: { showAdmin?: boolean }) {
  const [open, setOpen] = useState(false)
  const profileId = useCurrentProfileId()

  return (
    <Sheet open={open} onOpenChange={setOpen}>
      {/*
        `size-11` is 44px. Below `lg` this button is the console's only
        path to the drawer's destinations, so a thumb that misses it has
        no way to reach them. It was `size-9`.
      */}
      <SheetTrigger
        aria-label="Open the navigation menu"
        className="inline-flex size-11 shrink-0 items-center justify-center rounded-lg border border-border bg-card text-foreground transition-colors duration-150 hover:bg-accent/60 lg:hidden"
      >
        <Menu className="size-4" strokeWidth={1.8} aria-hidden="true" />
      </SheetTrigger>

      <SheetContent side="left" className="w-72 gap-0 p-0 sm:max-w-72">
        <SheetHeader className="border-b border-border p-4">
          <div className="flex items-center gap-3">
            <BrandMark />
            <div className="leading-tight">
              <SheetTitle className="font-heading text-[15px] font-semibold tracking-tight">
                JobPilot
              </SheetTitle>
              <SheetDescription className="text-[11px] text-muted-foreground">
                The agentic job applier
              </SheetDescription>
            </div>
          </div>
        </SheetHeader>

        <div className="flex flex-1 flex-col overflow-y-auto overscroll-contain p-4">
          <NavGroups
            surface="paper"
            staggerItems
            onNavigate={() => setOpen(false)}
          />

          <div className="mt-2 border-t border-border pt-2">
            <SystemNav
              surface="paper"
              showAdmin={showAdmin}
              onNavigate={() => setOpen(false)}
            />
          </div>
        </div>

        {/*
          The account area, mirrored from the sidebar footer: the
          diagnostics that a phone hides from the top bar.
        */}
        <div className="flex flex-col gap-2 border-t border-border p-4">
          <ProfileChip profileId={profileId} className="max-w-full" />
          <ApiStatus />
        </div>
      </SheetContent>
    </Sheet>
  )
}
