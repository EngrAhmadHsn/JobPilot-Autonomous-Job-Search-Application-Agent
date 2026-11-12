import { Card, CardContent, CardHeader } from "@/components/ui/card"
import { Skeleton } from "@/components/ui/skeleton"
import { cn } from "cn"

/**
 * A card-shaped screen section, while its content is on the way.
 *
 * The console knows the shape of most answers before it has them: a title
 * line, a line of metadata, a few rows. Rendering that shape as bones means
 * the page does not jump when the data lands, and the wait reads as "here it
 * comes" rather than as a blank page with the word "Loading" on it.
 *
 * `rows` is the number of body lines to draw. The lengths are uneven on
 * purpose: evenly-sized bars read as a table of placeholders, uneven ones read
 * as text. The first line is always the longest, which is how a real paragraph
 * or a real label column looks.
 *
 * Accessibility: the wrapper is `aria-busy`, every bone is `aria-hidden` (set
 * inside `Skeleton`), and the caller owns the one live region. Two live regions
 * on the same screen would announce the wait twice.
 */
export function CardSkeleton({
  rows = 3,
  withHeader = true,
  className,
}: {
  rows?: number
  withHeader?: boolean
  className?: string
}) {
  const widths = [
    "w-[min(22rem,72%)]",
    "w-[min(16rem,46%)]",
    "w-[min(18rem,56%)]",
    "w-[min(12rem,38%)]",
  ]

  return (
    <Card className={cn("rounded-2xl", className)} aria-busy="true">
      {withHeader ? (
        <CardHeader>
          <Skeleton className="h-5 w-[min(14rem,44%)]" />
          <Skeleton className="h-4 w-[min(22rem,66%)]" />
        </CardHeader>
      ) : null}
      <CardContent className="space-y-2.5">
        {Array.from({ length: rows }, (_, index) => (
          <Skeleton
            key={index}
            className={cn("h-4", widths[index % widths.length])}
          />
        ))}
      </CardContent>
    </Card>
  )
}

/**
 * A short block of prose while it loads.
 *
 * For a panel that is a paragraph rather than a card, a single bone of the
 * right height reserves the space without pretending the text is a card.
 */
export function InlineSkeleton({ className }: { className?: string }) {
  return (
    <div className="space-y-2" aria-busy="true">
      <Skeleton className={cn("h-4 w-full", className)} />
      <Skeleton className="h-4 w-[72%]" />
    </div>
  )
}
