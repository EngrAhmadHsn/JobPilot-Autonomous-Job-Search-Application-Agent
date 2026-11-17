import { Link } from "react-router-dom"

import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { QueryCombobox } from "@/components/common/query-combobox"

/*
  The search area of the Discover split view (WS-36).

  The copy states the search's truth: it ranks the **stored** corpus — no
  board is fetched while the operator is looking at the screen — and the way
  to widen the corpus is Operations, which owns the refresh. The link is the
  product's own route, so the sentence never implies a live scrape.

  The filters rendered here are exactly the ones the `POST /api/jobs/search`
  contract supports: the query tokens, a location substring, and the size of
  the ranked slice. The reference panel's Remote/On-site/Hybrid chips, its
  sort control and its salary filter have no backend contract today, so they
  are not rendered (the WS-33 audit §7 list governs).

  Overflow: the query suggestions panel is absolutely positioned from under
  the field and must extend past this card's edge. The shared Card clips by
  default (`overflow-hidden`) and every other screen relies on that, so the
  exception lives here, at the one call site — not in card.tsx.
*/
export function SearchPanel({
  query,
  onQueryChange,
  location,
  onLocationChange,
  topN,
  onTopNChange,
  onSubmit,
  isPending,
}: {
  query: string
  onQueryChange: (value: string) => void
  location: string
  onLocationChange: (value: string) => void
  topN: number
  onTopNChange: (value: number) => void
  onSubmit: () => void
  isPending: boolean
}) {
  return (
    <Card className="overflow-visible">
      <CardHeader>
        <CardTitle>Search stored jobs</CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        <p className="text-sm text-muted-foreground">
          Rank the jobs already stored in this workspace against your profile —
          nothing is fetched from the boards while you search. Add more listings
          from{" "}
          <Link
            to="/app/operations"
            className="font-medium underline underline-offset-4"
          >
            Operations
          </Link>{" "}
          when you want a wider corpus.
        </p>

        <form
          className="grid gap-3 sm:grid-cols-[2fr_2fr_6rem_auto] sm:items-end"
          onSubmit={(event) => {
            event.preventDefault()
            onSubmit()
          }}
        >
          <div className="space-y-1">
            <label htmlFor="search-query" className="text-sm font-medium">
              Query
            </label>
            <QueryCombobox
              inputId="search-query"
              value={query}
              onChange={onQueryChange}
            />
          </div>
          <div className="space-y-1">
            <label htmlFor="search-location" className="text-sm font-medium">
              Location
            </label>
            <Input
              id="search-location"
              value={location}
              placeholder="Substring of the location"
              onChange={(event) => onLocationChange(event.target.value)}
            />
          </div>
          <div className="space-y-1">
            <label htmlFor="search-top-n" className="text-sm font-medium">
              Top N
            </label>
            <Input
              id="search-top-n"
              type="number"
              min={1}
              max={50}
              value={topN}
              onChange={(event) =>
                onTopNChange(Number(event.target.value) || 1)
              }
            />
          </div>
          <Button type="submit" disabled={isPending}>
            {isPending ? "Searching…" : "Search"}
          </Button>
        </form>
      </CardContent>
    </Card>
  )
}
