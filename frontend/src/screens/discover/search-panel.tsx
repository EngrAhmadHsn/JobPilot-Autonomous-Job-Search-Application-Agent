import { Search, SlidersHorizontal } from "lucide-react"
import { useEffect, useState } from "react"
import { Link } from "react-router-dom"

import { QueryCombobox } from "@/components/common/query-combobox"
import { Button } from "@/components/ui/button"

import {
  FiltersDialog,
  type FiltersDraft,
} from "@/screens/discover/filters-dialog"
import type { JobSearchWorkplace } from "@/lib/api/types"

/**
 * The largest ranked slice the server will return.
 *
 * Mirrors `MAX_TOP_N` in `src/graph/job_executor.py`; the server clamps
 * again, so this bound only keeps the screen's own "the first N shown"
 * wording true about a request it actually made. The dialog's Rank-top-N
 * field clamps against it too.
 */
export const MAX_TOP_N = 50

/** The workplace axis in words, as the design's dialog and chips draw it. */
export function workplaceLabel(workplace: JobSearchWorkplace | ""): string {
  if (!workplace) return ""
  if (workplace === "onsite") return "On-site"
  return workplace === "remote" ? "Remote" : "Hybrid"
}

/*
  The search area of the Discover screen (WS-36, re-shaped for WS-42, and
  for WS-44 given the design's own filter model).

  The design file (node `16:42`) draws **one wide search field** with the
  search action attached to its right edge, and the filters as a separate
  row of removable chips under it. The query leads; every other filter —
  Location, Workplace, Skills, Rank top N — lives behind the **Filters**
  button, which opens the design's dialog (`Overlay · Job filters · 480`).
  The filters the dialog applied come back as removable chips in this row
  ("Remote · United Kingdom ×", "Python ×"), so a narrowed search can never
  look like a plain one, and a chip's × undoes its narrowing and searches
  again.

  The copy still states the search's truth — it ranks the **stored** corpus,
  no board is fetched while the operator looks at the screen, and the way to
  widen the corpus is Operations, which owns the refresh. The dialog's
  honesty note (`JOB_FILTERS_NOTE`) says the same thing in the design's own
  words.

  Overflow: the query suggestion panel is absolutely positioned from under the
  field and must extend past its container. `overflow-visible` lives here, at
  the one call site, not in the shared card.
*/
export function SearchPanel({
  query,
  onQueryChange,
  workplace,
  location,
  topN,
  onApplyFilters,
  onClearNarrowing,
  onClearSkills,
  onClearTopN,
  onSubmit,
  isPending,
  recentSearches,
  onPickRecent,
  onRemoveRecent,
  onSuggestingChange,
}: {
  query: string
  onQueryChange: (value: string) => void
  /** The applied workplace filter; `""` is "any". */
  workplace: JobSearchWorkplace | ""
  /** The applied location filter — a value the corpus holds. */
  location: string
  /** The ranked slice's size (1..`MAX_TOP_N`; `MAX_TOP_N` is the default). */
  topN: number
  /** Commit the dialog's draft and re-search with it. */
  onApplyFilters: (draft: FiltersDraft) => void
  /** The narrowing chip's ×: clear workplace and location, then re-search. */
  onClearNarrowing: () => void
  /** The skills chip's ×: clear the skills filter, then re-search. */
  onClearSkills: () => void
  /** The top-N chip's ×: reset the slice to 50, then re-search. */
  onClearTopN: () => void
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

  /*
    The Filters button carries the design's `F` keyboard hint (node `16:42`),
    so the hint is real: pressing `F` opens the dialog. Like "/" below, it
    works only when the operator is not already typing in a field, and
    browser combinations (⌘F, Ctrl+F) pass through untouched.
  */
  useEffect(() => {
    function onFilterKey(event: KeyboardEvent) {
      const key = event.key.toLowerCase()
      if (key !== "f" || event.defaultPrevented) return
      if (event.metaKey || event.ctrlKey || event.altKey) return
      const target = event.target as HTMLElement | null
      if (
        target &&
        (target.tagName === "INPUT" ||
          target.tagName === "TEXTAREA" ||
          target.tagName === "SELECT" ||
          target.isContentEditable)
      ) {
        return
      }
      event.preventDefault()
      setFiltersOpen(true)
    }
    window.addEventListener("keydown", onFilterKey)
    return () => window.removeEventListener("keydown", onFilterKey)
  }, [])

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

  /*
    The chips, as the design draws them (node `16:42`): first the workplace
    and location narrowing as one chip ("Remote · United Kingdom ×"), then
    the skills chip ("Python ×"), then the slice-size chip when it is not
    the default. A chip is a real control: clicking its × clears exactly
    what it shows and searches again, so a reader can undo a narrowing
    without opening the dialog.
  */
  const narrowingParts = [workplaceLabel(workplace), location.trim()].filter(
    Boolean
  )
  const skills = query.trim()

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
          (node `49:1524` — 118x37, forest fill).
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

      {/* The filter row: the applied chips, then the Filters control. */}
      <div className="flex flex-wrap items-center gap-2">
        {narrowingParts.length > 0 ? (
          <button
            type="button"
            onClick={onClearNarrowing}
            className="inline-flex h-8 items-center gap-1.5 rounded-lg bg-forest-soft px-2.5 text-[13px] font-medium text-forest outline-none hover:bg-accent focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring"
          >
            {narrowingParts.join(" · ")}
            <span aria-hidden="true">×</span>
            <span className="sr-only">
              Remove the {narrowingParts.join(" and ")} filter
              {narrowingParts.length > 1 ? "s" : ""}
            </span>
          </button>
        ) : null}

        {skills ? (
          <button
            type="button"
            onClick={onClearSkills}
            className="inline-flex h-8 items-center gap-1.5 rounded-lg bg-forest-soft px-2.5 text-[13px] font-medium text-forest outline-none hover:bg-accent focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring"
          >
            {skills}
            <span aria-hidden="true">×</span>
            <span className="sr-only">Remove the skills filter</span>
          </button>
        ) : null}

        {topN !== MAX_TOP_N ? (
          <button
            type="button"
            onClick={onClearTopN}
            className="inline-flex h-8 items-center gap-1.5 rounded-lg bg-forest-soft px-2.5 text-[13px] font-medium text-forest outline-none hover:bg-accent focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring"
          >
            Top {topN}
            <span aria-hidden="true">×</span>
            <span className="sr-only">Reset the ranked slice to 50</span>
          </button>
        ) : null}

        {/*
          The Filters control, with the design's `F` hint. The hint names a
          shortcut that works — pressing `F` opens this dialog, exactly as
          the guide's "/" promise does.
        */}
        <button
          type="button"
          onClick={() => setFiltersOpen(true)}
          aria-haspopup="dialog"
          className="inline-flex h-8 items-center gap-1.5 rounded-lg border border-border-surface bg-card px-2.5 text-[13px] font-medium text-foreground transition-colors outline-none hover:bg-accent focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring"
        >
          <SlidersHorizontal
            aria-hidden="true"
            className="size-3.5"
            strokeWidth={1.8}
          />
          Filters
          <span
            aria-hidden="true"
            className="inline-flex h-[18px] min-w-[18px] items-center justify-center rounded-[5px] bg-forest-soft px-1 text-[11px] font-semibold text-forest"
          >
            F
          </span>
        </button>

        {/*
          The row's standing copy: the search's truth, in the console's own
          words. (The design puts "Stored corpus · refreshed …" beside the
          Filters button; that line belongs to the source registry the
          Operations screen owns, and no workstream wires it here yet.)
        */}
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

      {/*
        The dialog, mounted only while open (so its draft snapshot starts
        from the applied filters each time). Its honesty note —
        "These filters apply to the stored corpus. They do not fetch job
        boards." — is `JOB_FILTERS_NOTE`, the design's own sentence.
      */}
      {filtersOpen ? (
        <FiltersDialog
          filters={{ workplace, location, skills: query, topN }}
          onApply={(draft) => {
            setFiltersOpen(false)
            onApplyFilters(draft)
          }}
          onDismiss={() => setFiltersOpen(false)}
        />
      ) : null}
    </div>
  )
}
