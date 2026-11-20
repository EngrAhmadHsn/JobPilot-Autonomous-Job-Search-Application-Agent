import { useQuery } from "@tanstack/react-query"
import { ChevronDownIcon } from "lucide-react"
import { useState, type ReactNode } from "react"

import {
  Dialog,
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogTitle,
} from "@/components/ui/dialog"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"

import { api } from "@/lib/api/endpoints"
import type { JobSearchWorkplace } from "@/lib/api/types"

import { MAX_TOP_N } from "./search-panel"

/*
  The job-filters dialog (WS-44, `Overlay · Job filters · 480.png`, compact
  at small widths per `· 350.png`).

  The design's filter model replaces the old disclosure's two inputs:
  **Location** (a select fed by the corpus's own locations — a value the
  corpus holds, not a substring guess), **Workplace** (Any / Remote /
  Hybrid / On-site — the axis `POST /api/jobs/search` actually filters on),
  **Skills** (which maps onto the search's `query` field — one text filter,
  two entrances) and **Rank top N** (the ranked slice's size, which must
  not vanish because the honest control that set it moved here).

  The honesty note is verbatim from the design render: these filters narrow
  the **stored** corpus; nothing fetches a job board.

  The dialog edits a **draft**. Nothing applies until "Apply filters"; the
  parent mounts this component only while it is open, so the draft starts
  from the applied filters at open time, and Cancel, Close and Escape (the
  Base-UI primitive's own behaviour) discard every edit.

  The selects are native `<select>` elements — the pattern the profile
  screen's preferences card already uses. A styled popup primitive belongs
  to the Wave-3 primitive rebase, not to this screen, and a native select
  cannot be invented into offering a location the corpus does not carry.
*/

/**
 * The verbatim honesty note from the design's overlay (`Overlay · Job
 * filters · 480.png`). Quoted as a constant so the test can pin it and a
 * rewording has to be deliberate.
 */
export const JOB_FILTERS_NOTE =
  "These filters apply to the stored corpus. They do not fetch job boards."

/** The draft the dialog edits; the parent commits it only on Apply. */
export interface FiltersDraft {
  /** `""` means "any workplace" — the filter is absent from the request. */
  workplace: JobSearchWorkplace | ""
  /** A location the corpus holds, or `""` for any. */
  location: string
  /** The skills filter — the same field the search box fills (`query`). */
  skills: string
  /** The ranked slice's size, clamped to 1..`MAX_TOP_N` on apply. */
  topN: number
}

/** The workplace options, as the design's dialog draws them. */
const WORKPLACE_OPTIONS: {
  value: FiltersDraft["workplace"]
  label: string
}[] = [
  { value: "", label: "Any" },
  { value: "remote", label: "Remote" },
  { value: "hybrid", label: "Hybrid" },
  { value: "onsite", label: "On-site" },
]

/**
 * One select styled to the design's filled field (a muted surface, the
 * control radius, the chevron on its trailing edge). A native `<select>`:
 * the popup is the browser's own, fully keyboard- and screen-reader
 * -addressable, and it can only ever offer values something real supplied.
 */
function FilterSelect({
  id,
  label,
  value,
  onChange,
  children,
}: {
  id: string
  label: string
  value: string
  onChange: (value: string) => void
  children: ReactNode
}) {
  return (
    <div className="space-y-1">
      <label htmlFor={id} className="block text-sm font-semibold text-forest">
        {label}
      </label>
      <div className="relative">
        <select
          id={id}
          value={value}
          onChange={(event) => onChange(event.target.value)}
          className="h-11 w-full cursor-pointer appearance-none rounded-lg border border-transparent bg-muted px-3 pr-9 text-sm text-foreground outline-none focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50"
        >
          {children}
        </select>
        <ChevronDownIcon
          aria-hidden="true"
          className="pointer-events-none absolute top-1/2 right-3 size-4 -translate-y-1/2 text-muted-foreground"
          strokeWidth={1.8}
        />
      </div>
    </div>
  )
}

/** One filled text field of the dialog (the design's Skills / Rank top N). */
function FilterInput({
  id,
  label,
  hint,
  ...props
}: React.ComponentProps<typeof Input> & {
  id: string
  label: string
  hint?: string
}) {
  return (
    <div className="space-y-1">
      <label htmlFor={id} className="block text-sm font-semibold text-forest">
        {label}
      </label>
      <Input
        id={id}
        className="h-11 rounded-lg border-transparent bg-muted"
        {...props}
      />
      {hint ? <p className="type-caption">{hint}</p> : null}
    </div>
  )
}

export function FiltersDialog({
  filters,
  onApply,
  onDismiss,
}: {
  /** The applied filters the draft starts from. */
  filters: FiltersDraft
  /** Commit the draft; the parent closes the dialog and re-searches. */
  onApply: (draft: FiltersDraft) => void
  /** Close without applying (Cancel, Close, Escape). */
  onDismiss: () => void
}) {
  /*
    The corpus's own locations, fetched while the dialog is on screen. The
    dialog is mounted only while open, so this query lives exactly as long
    as the choices it feeds.
  */
  const locations = useQuery({
    queryKey: ["job-locations"],
    queryFn: ({ signal }) => api.listJobLocations(500, signal),
    staleTime: 60_000,
  })

  // The draft starts from the applied filters — this component mounts
  // fresh on every open, so `useState`'s initialiser is the snapshot.
  const [draft, setDraft] = useState<FiltersDraft>(() => filters)

  /*
    The location options are the corpus's own values. An applied location
    that the list does not carry (a value from an earlier corpus, or an
    endpoint that could not be read) still renders as the selection — the
    select never silently drops a filter the URL holds.
  */
  const locationOptions = locations.data?.suggestions ?? []
  const locationKnown = locationOptions.some(
    (option) => option.value === draft.location
  )

  function apply() {
    onApply({
      workplace: draft.workplace,
      location: draft.location.trim(),
      skills: draft.skills.trim(),
      topN: Math.min(Math.max(1, Math.floor(draft.topN) || 1), MAX_TOP_N),
    })
  }

  return (
    <Dialog open onOpenChange={(open) => (!open ? onDismiss() : undefined)}>
      {/*
        The design's dialog is 480 px wide (the `480.png` overlay); on a
        phone it is the viewport minus gutters — the `350.png` overlay's
        compact shape. The primitive's own `max-w-[calc(100%-2rem)]` already
        does the phone case; `sm:` raises the width to the design's.
      */}
      <DialogContent
        showCloseButton={false}
        className="gap-4 rounded-surface sm:max-w-[30rem]"
      >
        <div className="space-y-3">
          <DialogTitle className="font-heading text-[24px] leading-[32px] font-semibold text-forest">
            Job filters
          </DialogTitle>
          {/*
            The design's "Close ×" chip beneath the title. It is the
            primitive's own close control (`DialogClose`), so focus return
            and the accessibility wiring stay the primitive's — not a
            second, competing close.
          */}
          <DialogClose
            render={
              <button
                type="button"
                className="inline-flex h-9 items-center gap-1.5 rounded-lg bg-forest-soft px-3 text-[13px] font-medium text-forest transition-colors outline-none hover:bg-accent focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring"
              />
            }
          >
            Close <span aria-hidden="true">×</span>
            <span className="sr-only">the filters dialog</span>
          </DialogClose>
        </div>

        <div className="grid gap-4">
          <FilterSelect
            id="filter-location"
            label="Location"
            value={draft.location}
            onChange={(value) => setDraft({ ...draft, location: value })}
          >
            <option value="">Any location</option>
            {draft.location && !locationKnown ? (
              <option value={draft.location}>{draft.location}</option>
            ) : null}
            {locationOptions.map((option) => (
              <option key={option.value} value={option.value}>
                {option.value}
              </option>
            ))}
          </FilterSelect>

          <FilterSelect
            id="filter-workplace"
            label="Workplace"
            value={draft.workplace}
            onChange={(value) =>
              setDraft({
                ...draft,
                workplace: value as FiltersDraft["workplace"],
              })
            }
          >
            {WORKPLACE_OPTIONS.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </FilterSelect>

          <FilterInput
            id="filter-skills"
            label="Skills"
            placeholder="e.g. Python"
            value={draft.skills}
            onChange={(event) =>
              setDraft({ ...draft, skills: event.target.value })
            }
          />

          <FilterInput
            id="filter-top-n"
            label="Rank top N"
            type="number"
            min={1}
            max={MAX_TOP_N}
            hint={`The server ranks at most ${MAX_TOP_N} listings per search.`}
            value={draft.topN}
            onChange={(event) =>
              setDraft({ ...draft, topN: Number(event.target.value) || 1 })
            }
          />
        </div>

        {/*
          The honesty note, verbatim. As the dialog's description it is
          announced with the dialog itself, so a screen reader hears the
          boundary the dialog works within before it reaches the actions.
        */}
        <DialogDescription className="text-sm leading-relaxed text-muted-foreground">
          {JOB_FILTERS_NOTE}
        </DialogDescription>

        {/*
          The design stacks the actions: Apply, then Cancel beneath it —
          left-aligned, not a right-edge footer band.
        */}
        <div className="flex flex-col items-start gap-2">
          <Button type="button" onClick={apply} className="px-4">
            Apply filters
          </Button>
          <Button
            type="button"
            onClick={onDismiss}
            className="bg-forest-soft px-4 text-forest hover:bg-accent"
          >
            Cancel
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  )
}
