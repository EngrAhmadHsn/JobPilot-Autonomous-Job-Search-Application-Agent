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

import { AdminNav, NavGroups } from "./nav-groups"
import { BrandMark } from "./brand-mark"

/**
 * The navigation drawer.
 *
 * On a narrow screen the horizontal navigation cannot fit, and a
 * second band of links under the header is neither a good use of the
 * viewport nor a good pattern. The Material 3 answer for a phone is a
 * **modal navigation drawer** opened from a navigation icon in the top
 * bar, and that is what this is: the same groups, the same wording, the
 * same "you are here" marker, in a panel that slides in from the left and
 * closes when the operator picks a destination.
 */
export function NavDrawer() {
  const [open, setOpen] = useState(false)

  return (
    <Sheet open={open} onOpenChange={setOpen}>
      <SheetTrigger
        aria-label="Open the navigation menu"
        className="inline-flex size-9 items-center justify-center rounded-lg border border-border bg-card text-foreground transition-colors duration-150 hover:bg-accent/60 lg:hidden"
      >
        <Menu className="size-4" strokeWidth={1.8} aria-hidden="true" />
      </SheetTrigger>

      <SheetContent side="left" className="w-72 gap-0 p-0 sm:max-w-72">
        <SheetHeader className="border-b border-border p-4">
          <div className="flex items-center gap-3">
            <BrandMark />
            <div className="leading-tight">
              <SheetTitle className="font-heading text-[15px] font-semibold tracking-tight">
                CareerPilot
              </SheetTitle>
              <SheetDescription className="text-[11px] text-muted-foreground">
                The agentic job applier
              </SheetDescription>
            </div>
          </div>
        </SheetHeader>

        <div className="flex-1 overflow-y-auto p-4">
          <NavGroups variant="vertical" onNavigate={() => setOpen(false)} />

          <div className="mt-6 border-t border-border pt-4">
            <p className="px-3 pb-1 text-xs font-medium text-muted-foreground/80">
              Administration
            </p>
            <AdminNav variant="vertical" onNavigate={() => setOpen(false)} />
          </div>
        </div>
      </SheetContent>
    </Sheet>
  )
}
