import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip"

/**
 * The current candidate profile.
 *
 * The id is twelve hex characters, which means nothing to a person: it is a
 * handle, not a name. The tooltip says what it *is* — the profile every
 * other screen works against — so the chip is readable rather than merely
 * present.
 */
export function ProfileChip({ profileId }: { profileId: string | null }) {
  return (
    <TooltipProvider>
      <Tooltip>
        <TooltipTrigger
          render={
            <span className="hidden items-center gap-1.5 rounded-lg border border-border px-2.5 py-1.5 font-mono text-[11px] text-muted-foreground md:inline-flex" />
          }
        >
          <span
            aria-hidden="true"
            className="size-1.5 rounded-full bg-terracotta"
          />
          {profileId ?? "no profile"}
        </TooltipTrigger>
        <TooltipContent
          side="bottom"
          align="end"
          className="max-w-[16rem] leading-relaxed"
        >
          {profileId
            ? "The candidate profile every screen works against. Upload a different résumé on the Resume screen to work with another one."
            : "No profile yet. Upload a résumé on the Resume screen and it becomes the profile every screen works against."}
        </TooltipContent>
      </Tooltip>
    </TooltipProvider>
  )
}
