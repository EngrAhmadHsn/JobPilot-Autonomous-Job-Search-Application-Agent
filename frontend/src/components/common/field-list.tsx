import type { ReactNode } from "react"

/**
 * A label and a value.
 *
 * The value is a `ReactNode` the caller chooses; when the value is server
 * text the caller renders it through `PlainText`, so the console's one
 * rendering rule (untrusted text is text) holds everywhere.
 *
 * The label and the value **stack** on a narrow screen. A two-column table
 * with a wide label column squeezes the value into a few characters — a
 * place name like "San Francisco" ends up broken across three lines — so
 * below `sm` the label sits above its value.
 */
export function Field({
  label,
  children,
}: {
  label: string
  children: ReactNode
}) {
  return (
    <div className="grid grid-cols-1 gap-x-4 gap-y-0.5 py-1.5 text-sm sm:grid-cols-[minmax(7rem,13rem)_minmax(0,1fr)] sm:gap-y-1">
      <dt className="text-muted-foreground sm:pt-0.5">{label}</dt>
      <dd className="min-w-0 break-words">{children}</dd>
    </div>
  )
}

/** A list of label/value pairs. */
export function FieldList({
  items,
}: {
  items: { label: string; value: ReactNode }[]
}) {
  return (
    <dl className="divide-y divide-border/60">
      {items.map((item) => (
        <Field key={item.label} label={item.label}>
          {item.value}
        </Field>
      ))}
    </dl>
  )
}

/** A section title inside a card. */
export function SectionTitle({ children }: { children: ReactNode }) {
  return <h3 className="text-sm font-medium text-foreground">{children}</h3>
}
