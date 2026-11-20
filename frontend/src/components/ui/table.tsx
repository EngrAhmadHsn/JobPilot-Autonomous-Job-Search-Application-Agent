"use client"

import * as React from "react"
import { ArrowDown, ArrowUp, ArrowUpDown } from "lucide-react"
import { cn } from "cn"

function Table({ className, ...props }: React.ComponentProps<"table">) {
  return (
    <div
      data-slot="table-container"
      className="relative w-full overflow-x-auto"
    >
      <table
        data-slot="table"
        className={cn("w-full caption-bottom text-sm", className)}
        {...props}
      />
    </div>
  )
}

function TableHeader({ className, ...props }: React.ComponentProps<"thead">) {
  return (
    <thead
      data-slot="table-header"
      className={cn("[&_tr]:border-b", className)}
      {...props}
    />
  )
}

function TableBody({ className, ...props }: React.ComponentProps<"tbody">) {
  return (
    <tbody
      data-slot="table-body"
      className={cn("[&_tr:last-child]:border-0", className)}
      {...props}
    />
  )
}

function TableFooter({ className, ...props }: React.ComponentProps<"tfoot">) {
  return (
    <tfoot
      data-slot="table-footer"
      className={cn(
        "border-t bg-muted/50 font-medium [&>tr]:last:border-b-0",
        className
      )}
      {...props}
    />
  )
}

function TableRow({ className, ...props }: React.ComponentProps<"tr">) {
  return (
    <tr
      data-slot="table-row"
      className={cn(
        "border-b transition-colors hover:bg-muted/50 has-aria-expanded:bg-muted/50 data-[state=selected]:bg-muted",
        className
      )}
      {...props}
    />
  )
}

function TableHead({ className, ...props }: React.ComponentProps<"th">) {
  return (
    <th
      data-slot="table-head"
      className={cn(
        "h-10 px-2 text-left align-middle font-medium whitespace-nowrap text-foreground [&:has([role=checkbox])]:pr-0",
        className
      )}
      {...props}
    />
  )
}

function TableCell({ className, ...props }: React.ComponentProps<"td">) {
  return (
    <td
      data-slot="table-cell"
      className={cn(
        "p-2 align-middle whitespace-nowrap [&:has([role=checkbox])]:pr-0",
        className
      )}
      {...props}
    />
  )
}

function TableCaption({
  className,
  ...props
}: React.ComponentProps<"caption">) {
  return (
    <caption
      data-slot="table-caption"
      className={cn("mt-4 text-sm text-muted-foreground", className)}
      {...props}
    />
  )
}

export {
  Table,
  TableHeader,
  TableBody,
  TableFooter,
  TableHead,
  TableRow,
  TableCell,
  TableCaption,
}

/**
 * One sortable column header, from the design's interactive-table sets
 * (nodes 49:3196/49:3745/49:5091): a quiet pill — r=8, 9×14 padding,
 * 13/600 — whose glyph reads the current sort (idle ↕, ascending ↑,
 * descending ↓). The `aria-sort` lives on the `th`, where assistive tech
 * reads it; the glyph is the sighted echo, never the only carrier.
 *
 * Clicking cycles idle → ascending → descending → idle, so a reader can
 * always get back to the corpus's own order.
 */
export function TableSortHead({
  label,
  sort,
  onSortChange,
  className,
}: {
  label: string
  /** The column's current sort state; `null` is the unsorted default. */
  sort: "asc" | "desc" | null
  onSortChange: (next: "asc" | "desc" | null) => void
  className?: string
}) {
  const Glyph =
    sort === "asc" ? ArrowUp : sort === "desc" ? ArrowDown : ArrowUpDown
  return (
    <TableHead
      aria-sort={
        sort === "asc"
          ? "ascending"
          : sort === "desc"
            ? "descending"
            : undefined
      }
      className={className}
    >
      <button
        type="button"
        onClick={() =>
          onSortChange(sort === null ? "asc" : sort === "asc" ? "desc" : null)
        }
        className={cn(
          "inline-flex h-[37px] items-center gap-1.5 rounded-lg px-3.5 text-[13px] leading-[19px] font-semibold text-forest",
          "transition-colors outline-none hover:bg-muted/60 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring"
        )}
      >
        {label}
        <Glyph
          aria-hidden="true"
          className="size-3.5 shrink-0 text-muted-foreground"
          strokeWidth={1.8}
        />
      </button>
    </TableHead>
  )
}
