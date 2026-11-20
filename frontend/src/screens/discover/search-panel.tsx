import { Search, SlidersHorizontal } from "lucide-react"
import { useEffect, useId, useState } from "react"
import { Link } from "react-router-dom"
import { cn } from "cn"

import { QueryCombobox } from "@/components/common/query-combobox"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"

/*
  The search area of the Discover screen (WS-36, re-shaped for WS-42).

  The design file (node `16:42`) draws **one wide search field** with the
  search action attached to its right edge, and the filters as a separate
  row of removable chips under it. A three-field form in a card (what the
  earlier version rendered) put the two rarely-used controls — location and
  slice size — at the same visual weight as the query, which is the one thing
  every search needs.

  So the query leads and `Location`/`Top N` live behind a **Filters**
  disclosure. Nothing is removed: a search that needs a location still has
  one, and the disclosure states how many secondary filters are active so a
  narrowed search can never look like a plain one.

  The copy still states the search's truth — it ranks the **stored** corpus,
  no board is fetched while the operator looks at the screen, and the way to
  widen the corpus is Operations, which owns the refresh. The filters are
  exactly the ones `POST /api/jobs/search` supports; the design's
  Remote/On-site/Hybrid chips have no backend contract, so they are not
  invented (the WS-33 audit §7 rule).

  Overflow: the query suggestion panel is absolutely positioned from under the
  field and must extend past its container. `overflow-visible` lives here, at
  the one call site, not in the shared card.
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
  recentSearches,
  onPickRecent,
  onRemoveRecent,
  onSuggestingChange,
}: {
  query: string
  onQueryChange: (value: string) => void
  location: string
  onLocationChange: (value: string) => void
  topN: number
  onTopNChange: (value: number) => void
  onSubmit: () => void
  isPending: boolean
  /** The queries this browser has actually run, newest first (WS-42). */
  recentSearches?: string[]
  /** Run a recent query again — the chip's own action. */
  onPickRecent?: (query: string) => void
  /** Remove a query from the recent list. */
  onRemoveRecent?: (query: string) => void
  /** Whether the suggestions are on screen (the design's swap state). */
  onSuggestingChange?: (suggesting: boolean) => void
}) {
  const [filtersOpen, setFiltersOpen] = useState(false)
  const filtersId = useId()

  /*
    The keyboard guide's first row promises "/" focuses the job search (node
    `49:1568`) — so the promise is implemented here, at the field the guide
    sits beside. "/" works only when the operator is not already typing in a
    field; everything else passes through untouched.
  */
  useEffect(() => {
    function onSlash(event: KeyboardEvent) {
      if (event.key !== "/" || event.defaultPrevented) return
      const target = event.target as HTMLElement | null
      if (
        target &&
        (target.tagName === "INPUT" ||
          target.tagName === "TEXTAREA" ||
          target.isContentEditable)
      ) {
        return
      }
      event.preventDefault()
      document.getElementById("search-query")?.focus()
    }
    window.addEventListener("keydown", onSlash)
    return () => window.removeEventListener("keydown", onSlash)
  }, [])

  // How many secondary filters are narrowing this search. A search with a
  // location filter and a search without one must never look identical.
  const activeFilterCount = (location.trim() ? 1 : 0) + (topN !== 50 ? 1 : 0)

  return (
    <div className="space-y-3">
      <form
        className="flex flex-wrap items-center gap-2"
        onSubmit={(event) => {
          event.preventDefault()
          onSubmit()
        }}
      >
        {/*
          The field and the button read as one control, as the design draws
          them: a tall input with the action on its right edge. The label is
          visually hidden because the placeholder and the button both say what
          this is — but it stays in the accessibility tree, so the field is
          never unnamed.
        */}
        <div className="relative min-w-0 flex-1">
          {/*
            The label is visually hidden because the placeholder and the button
            both say what this field is — but it stays first in the
            accessibility tree, so the field is never unnamed and its name is
            stable ("Query") regardless of the placeholder's wording.
          */}
          <label htmlFor="search-query" className="sr-only">
            Query
          </label>
          <QueryCombobox
            inputId="search-query"
            value={query}
            onChange={onQueryChange}
            className="h-[50px] pl-10 text-base"
            placeholder="Search title, skills, or company"
            recentSearches={recentSearches}
            onPickRecent={onPickRecent}
            onRemoveRecent={onRemoveRecent}
            onSuggestingChange={onSuggestingChange}
          />
          <Search
            aria-hidden="true"
            className="pointer-events-none absolute top-1/2 left-3.5 size-4 -translate-y-1/2 text-muted-foreground"
            strokeWidth={1.8}
          />
        </div>
        {/*
          The action rides the field's right edge at the design's size
          (node `49:1524` — 118x37, forest fill). The design's trailing "↵"
          glyph is a keyboard-hint chip, the one ruling class the console
          drops everywhere, so it stays off.
        */}
        <Button
          type="submit"
          size="lg"
          disabled={isPending}
          className="h-[37px] px-3.5 text-[13px] leading-[19px] font-semibold"
        >
          <Search aria-hidden="true" className="size-4" strokeWidth={2} />
          {isPending ? "Searching…" : "Search jobs"}
        </Button>
      </form>

      {/* The filter row: a disclosure, and the active count. */}
      <div className="flex flex-wrap items-center gap-2">
        <button
          type="button"
          onClick={() => setFiltersOpen((open) => !open)}
          aria-expanded={filtersOpen}
          aria-controls={filtersId}
          className={cn(
            "inline-flex h-8 items-center gap-1.5 rounded-lg border border-border-surface px-2.5",
            "text-[13px] font-medium text-foreground transition-colors outline-none",
            "hover:bg-accent focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring"
          )}
        >
          <SlidersHorizontal
            aria-hidden="true"
            className="size-3.5"
            strokeWidth={1.8}
          />
          Filters
          {activeFilterCount > 0 ? (
            <span className="rounded bg-forest px-1.5 text-[11px] font-semibold text-primary-foreground tabular-nums">
              {activeFilterCount}
            </span>
          ) : null}
        </button>

        {/*
          The active filters, as removable chips — the design's own row. A
          chip is a real control: clicking it clears that filter, so a reader
          can undo a narrowing without opening the disclosure.
        */}
        {location.trim() ? (
          <button
            type="button"
            onClick={() => onLocationChange("")}
            className="inline-flex h-8 items-center gap-1.5 rounded-lg bg-forest-soft px-2.5 text-[13px] font-medium text-forest outline-none hover:bg-accent focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring"
          >
            {location.trim()}
            <span aria-hidden="true">×</span>
            <span className="sr-only">Remove the location filter</span>
          </button>
        ) : null}

        {topN !== 50 ? (
          <button
            type="button"
            onClick={() => onTopNChange(50)}
            className="inline-flex h-8 items-center gap-1.5 rounded-lg bg-forest-soft px-2.5 text-[13px] font-medium text-forest outline-none hover:bg-accent focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring"
          >
            Top {topN}
            <span aria-hidden="true">×</span>
            <span className="sr-only">Reset the ranked slice to 50</span>
          </button>
        ) : null}

        <p className="type-caption">
          Ranks the stored corpus — no board is fetched while you search. Widen
          it in{" "}
          <Link
            to="/app/operations"
            className="font-medium text-forest underline underline-offset-4 outline-none focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring"
          >
            Operations
          </Link>
          .
        </p>
      </div>

      {filtersOpen ? (
        <div
          id={filtersId}
          className="surface grid gap-3 p-4 sm:grid-cols-2 lg:max-w-2xl"
        >
          <div className="space-y-1">
            <label
              htmlFor="search-location"
              className="text-[13px] font-medium text-foreground"
            >
              Location
            </label>
            <Input
              id="search-location"
              value={location}
              placeholder="Substring of the location"
              onChange={(event) => onLocationChange(event.target.value)}
            />
            <p className="type-caption">
              A substring match against the stored location, not a geocoder.
            </p>
          </div>
          <div className="space-y-1">
            <label
              htmlFor="search-top-n"
              className="text-[13px] font-medium text-foreground"
            >
              How many to rank
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
            <p className="type-caption">
              The server ranks at most 50 listings per search.
            </p>
          </div>
        </div>
      ) : null}
    </div>
  )
}
