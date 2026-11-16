import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip"
import { cn } from "cn"

/**
 * The current candidate profile.
 *
 * The id is twelve hex characters, which means nothing to a person: it is a
 * handle, not a name. The tooltip says what it *is* — the profile every
 * other screen works against — so the chip is readable rather than merely
 * present.
 *
 * WS-34 moves the chip into the shell's account area, which sits on two
 * surfaces: the paper chrome and (at desktop widths) the forest sidebar
 * footer. The `surface` prop restyles the hairline and text for the one
 * it is on; the terracotta dot stays, because the profile is the
 * human's own material.
 */
export function ProfileChip({
  profileId,
  surface = "default",
  className,
}: {
  profileId: string | null
  surface?: "default" | "sidebar"
  className?: string
}) {
  const onSidebar = surface === "sidebar"
  return (
    <TooltipProvider>
      <Tooltip>
        <TooltipTrigger
          render={
            <span
              className={cn(
                "inline-flex max-w-full items-center gap-1.5 rounded-lg border px-2.5 py-1.5 font-mono text-[11px]",
                onSidebar
                  ? "border-sidebar-border text-sidebar-muted"
                  : "border-border text-muted-foreground",
                className
              )}
            />
          }
        >
          <span
            aria-hidden="true"
            className="size-1.5 shrink-0 rounded-full bg-terracotta"
          />
          <span className="truncate">{profileId ?? "no profile"}</span>
        </TooltipTrigger>
        <TooltipContent
          side="bottom"
          align="end"
          className="max-w-[16rem] leading-relaxed"
        >
          {profileId
            ? "The candidate profile every screen works against. Upload a different résumé on the Documents screen to work with another one."
            : "No profile yet. Upload a résumé on the Documents screen and it becomes the profile every screen works against."}
        </TooltipContent>
      </Tooltip>
    </TooltipProvider>
  )
}
