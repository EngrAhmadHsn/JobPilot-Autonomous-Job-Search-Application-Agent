import { Skeleton } from "@/components/ui/skeleton"
import { cn } from "cn"

/*
  The results list, while it is being ranked (WS-36).

  The bones copy `ResultRow` deliberately — a title line, a meta line and the
  score pill on the right — so the list does not jump when the ranking lands.
  The lengths are uneven on purpose: evenly-sized bars read as a table of
  placeholders, uneven ones read as text.

  Accessibility: the wrapper is `aria-busy`, every bone is `aria-hidden` (that
  is inside `Skeleton`), and the caller owns the one live region — the
  section heading this skeleton sits under. Two live regions would announce
  the wait twice.
*/
export function ResultsSkeleton({
  rows = 5,
  className,
}: {
  rows?: number
  className?: string
}) {
  return (
    <div
      className={cn("space-y-2.5", className)}
      aria-busy="true"
      data-testid="results-skeleton"
    >
      {Array.from({ length: rows }, (_, index) => (
        <div
          key={index}
          className="flex items-start justify-between gap-3 rounded-xl border border-border bg-card px-4 py-3"
        >
          <div className="min-w-0 flex-1 space-y-2">
            {/* The title line. */}
            <Skeleton className="h-4 w-[min(16rem,72%)]" />
            {/* Company · location · posted/salary meta. */}
            <Skeleton className="h-3.5 w-[min(13rem,55%)]" />
            {/* The skill chips. */}
            <div className="flex gap-1.5 pt-0.5">
              <Skeleton className="h-5 w-16 rounded-full" />
              <Skeleton className="h-5 w-20 rounded-full" />
              <Skeleton className="h-5 w-14 rounded-full" />
            </div>
          </div>
          {/* The score chip: the same pill shape the real row draws. */}
          <Skeleton className="h-6 w-16 shrink-0 rounded-full" />
        </div>
      ))}
    </div>
  )
}
