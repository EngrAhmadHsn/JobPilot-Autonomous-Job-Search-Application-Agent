import type { ReactNode } from "react"

/**
 * A label and a value.
 *
 * The value is a `ReactNode` the caller chooses; when the value is server
 * text the caller renders it through `PlainText`, so the console's one
 * rendering rule (untrusted text is text) holds everywhere.
 */
export function Field({
  label,
  children,
}: {
  label: string
  children: ReactNode
}) {
  return (
    <div className="grid grid-cols-[minmax(8rem,14rem)_1fr] gap-x-4 gap-y-1 py-1 text-sm">
      <dt className="text-muted-foreground">{label}</dt>
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

/** A section heading inside a card. */
export function SectionTitle({ children }: { children: ReactNode }) {
  return <h3 className="text-sm font-semibold tracking-tight">{children}</h3>
}
