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
export function NavDrawer({ showAdmin = false }: { showAdmin?: boolean }) {
  const [open, setOpen] = useState(false)

  return (
    <Sheet open={open} onOpenChange={setOpen}>
      {/*
        The trigger is the bottom bar's fourth slot (the design's
        `Nav:Expand`, node 49:10386): a glyph-over-label control matching the
        bar's three links, opening the same drawer. WS-49 removed the
        standalone hamburger this component used to offer as a second
        variant — nothing had mounted it since WS-43 moved the mobile
        trigger into the bar, so it was a branch only its own unit test
        rendered.
      */}
      <SheetTrigger className="flex min-w-0 flex-1 flex-col items-center justify-center gap-0.5 px-1 py-2.5 text-forest transition-colors duration-150 outline-none focus-visible:outline-2 focus-visible:-outline-offset-8 focus-visible:outline-ring">
        <Menu aria-hidden="true" className="size-5" strokeWidth={1.7} />
        <span className="text-[10px] leading-[14px]">More</span>
      </SheetTrigger>

      {/*
        The design's mobile drawer (`13 · Expanded navigation · 768/390`,
        node 49:11961) is the expanded rail as a forest panel: the same
        `#1b3831` ground, the lime active pill, the account block at the
        foot. Nothing about "a menu opened from a phone" makes it a paper
        surface.

        WS-43: the panel is wide — `min(26rem, 88vw)` gives roughly half
        the frame at ≥768 and near-full on a phone — and the width rides a
        `data-[side=left]` variant because the Sheet primitive's own
        `w-3/4`/`max-w-sm` carry that variant, and tailwind-merge only
        drops a base class for an override on the same variant. The scrim
        (the Sheet's warm `bg-ink/20`) and the popup's own
        `overflow-y-auto overscroll-contain` are kept as they were.
      */}
      <SheetContent
        side="left"
        className="w-[min(26rem,88vw)] gap-0 border-none bg-sidebar p-0 text-sidebar-foreground data-[side=left]:w-[min(26rem,88vw)] data-[side=left]:sm:max-w-[min(26rem,88vw)]"
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

        {/*
          The nav container takes the rail's `px-3.5`, so the rows' own
          `px-3` land the glyphs and labels on the same x-positions as the
          expanded rail (26 px / 58 px).
        */}
        <div className="flex flex-1 flex-col overflow-y-auto overscroll-contain px-3.5 py-4">
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
          — the same account control the chrome carries elsewhere, laid out
          on the rail footer's structure (`px-3.5` container, `px-3` row) so
          the avatar lines up under the drawer rows' icons, as the render's
          footer does (avatar at 26 px, identity at 74 px).
        */}
        <div className="flex items-center border-t border-sidebar-hover px-3.5 py-3">
          <AccountMenu surface="sidebar" className="gap-3 px-3" />
        </div>
      </SheetContent>
    </Sheet>
  )
}
