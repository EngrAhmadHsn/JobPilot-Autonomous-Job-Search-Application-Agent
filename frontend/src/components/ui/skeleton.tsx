import { cn } from "cn"
import type * as React from "react"

/**
 * A placeholder for content that is on its way.
 *
 * A skeleton is not decoration: it reserves the space the real content will
 * occupy, so the screen does not jump when the answer arrives, and it says
 * "this is loading" without asking the operator to read a sentence. It is
 * still announced — the caller owns the one live region (see
 * `MatchListSkeleton`), because a screenful of `aria-hidden` boxes is
 * silent to a screen reader and silence is indistinguishable from a hang.
 *
 * `animate-pulse` is Tailwind's own opacity loop (already available via
 * `tw-animate-css`, no dependency), and the console's reduced-motion block
 * zeroes it automatically — the bones then sit as flat muted blocks, which
 * is the right reduced-motion rendering because the pulse moves nothing.
 */
function Skeleton({ className, ...props }: React.ComponentProps<"div">) {
  return (
    <div
      data-slot="skeleton"
      aria-hidden="true"
      className={cn("animate-pulse rounded-md bg-muted", className)}
      {...props}
    />
  )
}

export { Skeleton }
