import { cn } from "cn"
import { useQuery } from "@tanstack/react-query"
import { useDeferredValue, useId, useRef, useState } from "react"

import { Input } from "@/components/ui/input"
import { api } from "@/lib/api/endpoints"
import { stagger } from "@/lib/stagger"

/**
 * The query field, with suggestions drawn from the listings you have.
 *
 * A plain text box asks the operator to guess the words that are in the
 * corpus. This one offers the job titles the corpus actually holds, ranked by
 * how many listings carry them, and filters as you type — so a search starts
 * from a role that exists rather than from a guess.
 *
 * The panel is the console's own, not the browser's: a native datalist cannot
 * be styled, cannot show how many listings a suggestion matches, and renders
 * outside the page's design. This one opens from under the field and its rows
 * arrive in sequence, like every other list here.
 *
 * Keyboard behaviour is the standard combobox: Down/Up move through the
 * suggestions, Enter takes the highlighted one (and otherwise submits the
 * search), Escape closes.
 */
export function QueryCombobox({
  value,
  onChange,
  inputId,
}: {
  value: string
  onChange: (value: string) => void
  inputId?: string
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
        placeholder="Start typing a role — suggestions come from your listings"
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

      {visible ? (
        <ul
          id={listId}
          role="listbox"
          aria-label="Suggested roles from your listings"
          className="suggest-panel absolute right-0 top-full z-50 mt-[15px] max-h-80 w-full min-w-[20rem] overflow-auto rounded-xl border border-border bg-popover p-1 text-popover-foreground shadow-lg"
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
                  "suggest-option flex cursor-pointer items-baseline justify-between gap-3 rounded-lg px-3 py-2 text-sm",
                  arrival.className,
                  index === active ? "" : "hover:bg-accent"
                )}
                style={arrival.style}
              >
                <span className="truncate">{item.value}</span>
                <span className="shrink-0 text-xs text-muted-foreground tabular-nums">
                  {item.count} listing{item.count === 1 ? "" : "s"}
                </span>
              </li>
            )
          })}
          <li
            aria-hidden="true"
            className="px-3 pb-1 pt-2 text-[11px] text-muted-foreground"
          >
            {items.length} suggestion{items.length === 1 ? "" : "s"} from your
            saved listings
          </li>
        </ul>
      ) : null}
    </div>
  )
}