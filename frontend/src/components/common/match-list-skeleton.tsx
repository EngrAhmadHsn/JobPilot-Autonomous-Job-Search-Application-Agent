import { Card, CardContent, CardHeader } from "@/components/ui/card"
import { Skeleton } from "@/components/ui/skeleton"
import { cn } from "cn"

/**
 * The ranked list, while it is being ranked.
 *
 * It replaces the "N seconds elapsed" readout on the Matches screen. The
 * elapsed clock was honest but it was also the only thing moving — it told
 * the operator how long they had been waiting, which is exactly the thing a
 * waiting person already knows. A skeleton says something better: here is
 * the shape of the answer, and here is where it will appear.
 *
 * The bones copy `MatchCard` deliberately — a Card with a title line, a
 * meta line and the score chip in the header, then the disclosure row and
 * the action button. The lengths are uneven on purpose: evenly-sized bars
 * read as a table of placeholders, uneven ones read as text.
 *
 * Accessibility: the list is `aria-busy` and every bone is `aria-hidden`
 * (that is inside `Skeleton`), so a screen reader meets one announced
 * heading — the `Section` this sits in — and not a pile of empty boxes. The
 * caller owns the heading, which is why there is no live region here: two
 * would say "Ranking your saved jobs" twice.
 */
export function MatchListSkeleton({
  rows = 4,
  className,
}: {
  rows?: number
  className?: string
}) {
  return (
    <div className={cn("space-y-4", className)} aria-busy="true">
      {Array.from({ length: rows }, (_, index) => (
        <Card key={index} className="rounded-2xl">
          <CardHeader>
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div className="min-w-0 flex-1 space-y-2">
                {/* The title line. */}
                <Skeleton className="h-5 w-[min(22rem,70%)]" />
                {/* Company · location · work mode. */}
                <Skeleton className="h-4 w-[min(16rem,50%)]" />
              </div>
              {/* The score chip: the same pill shape the real card draws. */}
              <Skeleton className="h-7 w-20 rounded-full" />
            </div>
          </CardHeader>
          <CardContent className="space-y-3">
            {/* "Why this score", collapsed. */}
            <Skeleton className="h-9 w-40 rounded-lg" />
            {/* The "Open the job" action. */}
            <Skeleton className="h-8 w-28 rounded-lg" />
          </CardContent>
        </Card>
      ))}
    </div>
  )
}
