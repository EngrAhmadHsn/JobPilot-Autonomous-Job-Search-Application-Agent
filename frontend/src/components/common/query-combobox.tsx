import { cn } from "cn"
import { useQuery } from "@tanstack/react-query"
import {
  useDeferredValue,
  useEffect,
  useId,
  useRef,
  useState,
  type ReactNode,
} from "react"
import { Search } from "lucide-react"

import { Input } from "@/components/ui/input"
import { api } from "@/lib/api/endpoints"
import { stagger } from "@/lib/stagger"

/*
  The query field, with suggestions drawn from the listings you have (WS-42
  rebuild to the design's autocomplete, node `49:1528`).

  A plain text box asks the operator to guess the words that are in the
  corpus. This one offers the job titles the corpus actually holds, ranked by
  how many listings carry them, and filters as you type — so a search starts
  from a role that exists rather than from a guess.

  The popup card is the design's: a 14px-radius surface with the group label
  ("Job titles in your stored corpus" — node `49:1529`), two-line rows
  (title 15/600 + a subtitle naming what the count is — node `49:1533`),
  and, when this browser has run searches before, the RECENT SEARCHES
  section (node `49:1559`): the operator's own past queries as removable
  chips under a divider. The trailing count line stays as a quiet caption.

  Beside the popup at `lg` — below it on smaller screens, as the design
  stacks them (node `49:1527`) — sits the keyboard guide card (node
  `49:1565`), documenting the four shortcuts the combobox really implements.
  The design's fifth row ("⌘ K — Open workspace search") documents a feature
  this console does not have, so it is not rendered: a shortcut hint for
  something that does not exist would be the exact fabrication this product
  forbids.

  The panel is the console's own, not the browser's: a native datalist cannot
  be styled, cannot show how many listings a suggestion matches, and renders
  outside the page's design. This one opens from under the field and its rows
  arrive in sequence, like every other list here.

  Keyboard behaviour is the standard combobox: Down/Up move through the
  suggestions, Enter takes the highlighted one (and otherwise submits the
  search), Escape closes.
*/

/** One row of the keyboard guide: the keys and what they do — all real. */
const GUIDE_ROWS: { keys: string; label: string }[] = [
  { keys: "/", label: "Focus job search" },
  { keys: "↑ ↓", label: "Move between suggestions" },
  { keys: "Enter", label: "Search the selected title" },
  { keys: "Esc", label: "Dismiss suggestions" },
]

function KeyboardGuide(): ReactNode {
  return (
    <aside className="w-full shrink-0 space-y-3.5 rounded-[var(--radius-surface)] bg-forest-soft p-5 lg:w-[410px]">
      <h2 className="max-w-[24ch] text-[22px] leading-[32px] font-semibold text-forest">
        Find it without leaving the keyboard.
      </h2>
      <ul className="space-y-3.5">
        {GUIDE_ROWS.map(({ keys, label }) => (
          <li key={keys} className="flex items-center gap-3">
            <kbd className="inline-flex h-[39px] min-w-[37px] items-center justify-center rounded-lg border border-border-surface bg-card px-3 text-[13px] leading-[19px] font-semibold text-forest">
              {keys}
            </kbd>
            <span className="text-[13px] leading-[19px] text-muted-foreground">
              {label}
            </span>
          </li>
        ))}
      </ul>
      <div aria-hidden="true" className="h-px bg-border" />
      <p className="max-w-[42ch] text-[13px] leading-[19px] text-muted-foreground">
        Searching never fetches job boards. Refresh the corpus separately in
        Operations.
      </p>
    </aside>
  )
}

export function QueryCombobox({
  value,
  onChange,
  inputId,
  className,
  placeholder = "Start typing a role — suggestions come from your listings",
  recentSearches = [],
  onPickRecent,
  onRemoveRecent,
  onSuggestingChange,
}: {
  value: string
  onChange: (value: string) => void
  inputId?: string
  /** Extra classes for the field, so a call site can size it. */
  className?: string
  placeholder?: string
  /** The queries this browser has actually run, newest first (WS-42). */
  recentSearches?: string[]
  /** Run a recent query again — the chip's own action. */
  onPickRecent?: (query: string) => void
  /** Remove a query from the recent list. */
  onRemoveRecent?: (query: string) => void
  /**
   * Whether the suggestions are on screen, reported up so the screen can
   * swap its heading copy the way the design's suggestions state does
   * (node `47:333`).
   */
  onSuggestingChange?: (suggesting: boolean) => void
}) {
  const listId = useId()
  const wrapper = useRef<HTMLDivElement>(null)
  const [open, setOpen] = useState(false)
  const [active, setActive] = useState(-1)

  // Deferred, so typing does not fire a request per keystroke.
  const deferred = useDeferredValue(value)
  const suggestions = useQuery({
    queryKey: ["job-suggestions", deferred],
    queryFn: ({ signal }) => api.suggestJobs(deferred.trim(), signal),
    enabled: deferred.trim().length > 0,
    staleTime: 60_000,
  })
  const items = suggestions.data?.suggestions ?? []
  const visible = open && items.length > 0

  // Report the suggestions state once per change, not per render. The
  // callback ref is refreshed in an effect, never during render (React 19's
  // `react-hooks/refs` rule treats a render-time write as a side effect),
  // and the reporting effect reads the latest callback from it.
  const reportSuggesting = useRef(onSuggestingChange)
  useEffect(() => {
    reportSuggesting.current = onSuggestingChange
  }, [onSuggestingChange])
  useEffect(() => {
    reportSuggesting.current?.(visible)
  }, [visible])

  function choose(index: number) {
    const item = items[index]
    if (!item) return
    onChange(item.value)
    setActive(-1)
    setOpen(false)
  }

  function onKeyDown(event: React.KeyboardEvent<HTMLInputElement>) {
    if (event.key === "ArrowDown") {
      event.preventDefault()
      setOpen(true)
      setActive((current) => Math.min(current + 1, items.length - 1))
    } else if (event.key === "ArrowUp") {
      event.preventDefault()
      setActive((current) => Math.max(current - 1, -1))
    } else if (event.key === "Escape") {
      setOpen(false)
      setActive(-1)
    } else if (event.key === "Enter" && visible && active >= 0) {
      event.preventDefault()
      choose(active)
    }
  }

  return (
    <div ref={wrapper} className="relative">
      <Input
        id={inputId}
        role="combobox"
        aria-expanded={visible}
        aria-controls={listId}
        aria-autocomplete="list"
        aria-activedescendant={active >= 0 ? `${listId}-${active}` : undefined}
        autoComplete="off"
        value={value}
        placeholder={placeholder}
        className={className}
        onChange={(event) => {
          onChange(event.target.value)
          setOpen(true)
          setActive(-1)
        }}
        onFocus={() => setOpen(true)}
        onBlur={() => {
          setOpen(false)
          setActive(-1)
        }}
        onKeyDown={onKeyDown}
      />

      {/*
        The panel is anchored to the field, not to a fixed 320 px.

        `min-w-[20rem]` was a hard 320 px floor regardless of the field's own
        width. Inside the Matches search card the field is ~295 px at 375 px
        and ~272 px at 320 px, so the panel overrode its anchor and — being
        pinned to the trailing edge — threw the surplus off the leading edge,
        past the viewport. `w-full` follows the field at every width; the
        20 rem floor is kept only from `sm` up, where there is room for it.
        `end-0` rather than `right-0` so the panel mirrors with the field
        under RTL.

        The card and the guide are one overlay (node `49:1527` — the design's
        2:1 columns): side by side from `lg`, stacked below it on smaller
        screens, exactly where the design draws them in its suggestions
        state.
      */}
      {visible ? (
        <div className="suggest-panel absolute end-0 top-full z-50 mt-[15px] flex w-full flex-col gap-6 lg:flex-row lg:items-start">
          {/*
            The popup card (node `49:1528`): r14, pad 12, the group label,
            the suggestion rows, the recent searches, and the count caption.
          */}
          <div className="min-w-0 flex-1 rounded-[var(--radius-surface)] border border-border-surface bg-popover p-3 text-popover-foreground shadow-lg">
            <p className="px-1 pb-1 text-[11px] leading-4 font-semibold tracking-wide text-muted-foreground uppercase">
              Job titles in your stored corpus
            </p>
            <ul
              id={listId}
              role="listbox"
              aria-label="Suggested roles from your listings"
              className="max-h-80 overflow-auto"
            >
              {items.map((item, index) => {
                const arrival = stagger(index)
                return (
                  <li
                    key={item.value}
                    // onMouseDown beats the input's blur, so the click lands.
                    onMouseDown={(event) => {
                      event.preventDefault()
                      choose(index)
                    }}
                    role="option"
                    id={`${listId}-${index}`}
                    aria-selected={index === active}
                    className={cn(
                      "suggest-option flex cursor-pointer items-center gap-3 rounded-[var(--radius-surface)] px-3 py-3",
                      arrival.className,
                      index === active ? "bg-forest-soft" : "hover:bg-accent"
                    )}
                    style={arrival.style}
                  >
                    <Search
                      aria-hidden="true"
                      className="size-5 shrink-0 text-muted-foreground"
                      strokeWidth={1.8}
                    />
                    {/*
                      Two lines, as the design draws them (node `49:1533`):
                      the title at 15/600, and a subtitle that says what the
                      count is. The subtitle carries the row's one real
                      number — the corpus' own count, moved out of the way of
                      the title.
                    */}
                    <span className="min-w-0 flex-1">
                      <span className="block truncate text-[15px] leading-[22px] font-semibold text-forest">
                        {item.value}
                      </span>
                      <span className="block text-xs leading-[17px] text-muted-foreground">
                        {item.count} listing{item.count === 1 ? "" : "s"} in
                        the stored corpus
                      </span>
                    </span>
                  </li>
                )
              })}
            </ul>

            {/*
              RECENT SEARCHES (node `49:1559`): the queries this browser
              actually ran, as removable chips under a divider. Clicking a
              chip runs it again; the × removes it from the list. Nothing
              here is invented — an empty history renders nothing.
            */}
            {recentSearches.length > 0 ? (
              <div className="mt-2 border-t border-border px-1 pt-2.5">
                <p className="pb-1.5 text-[11px] leading-4 font-semibold tracking-wide text-muted-foreground uppercase">
                  Recent searches
                </p>
                <div className="flex flex-wrap gap-3 pb-1">
                  {recentSearches.map((term) => (
                    <span
                      key={term}
                      className="inline-flex h-[37px] items-stretch overflow-hidden rounded-lg border border-border-surface bg-card text-[13px] leading-[19px] font-semibold text-forest"
                    >
                      <button
                        type="button"
                        className="px-2.5 transition-colors outline-none hover:bg-accent focus-visible:bg-accent"
                        onMouseDown={(event) => {
                          // onMouseDown beats the input's blur.
                          event.preventDefault()
                          onPickRecent?.(term)
                        }}
                      >
                        {term}
                      </button>
                      <button
                        type="button"
                        className="px-1.5 text-muted-foreground transition-colors outline-none hover:bg-accent focus-visible:bg-accent"
                        onMouseDown={(event) => {
                          event.preventDefault()
                          onRemoveRecent?.(term)
                        }}
                        aria-label={`Remove ${term} from recent searches`}
                      >
                        <span aria-hidden="true">×</span>
                      </button>
                    </span>
                  ))}
                </div>
              </div>
            ) : null}

            <p
              aria-hidden="true"
              className="px-1 pt-2 text-[11px] leading-4 text-muted-foreground"
            >
              {items.length} suggestion{items.length === 1 ? "" : "s"} from
              your saved listings
            </p>
          </div>

          <KeyboardGuide />
        </div>
      ) : null}
    </div>
  )
}
