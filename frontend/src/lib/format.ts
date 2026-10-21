/** Small formatting helpers. Nothing here interprets or alters server data. */

/** An ISO timestamp, as a readable local date and time. */
export function formatDateTime(value: string | null | undefined): string {
  if (!value) return "—"
  const parsed = new Date(value)
  if (Number.isNaN(parsed.getTime())) return value
  return parsed.toLocaleString()
}

/** A score between 0 and 100, with one decimal. */
export function formatScore(value: number | null | undefined): string {
  if (typeof value !== "number" || Number.isNaN(value)) return "—"
  return value.toFixed(1)
}

/** A list, or an honest "none" when it is empty. */
export function formatList(
  items: readonly string[] | null | undefined
): string {
  if (!items || items.length === 0) return "None"
  return items.join(", ")
}

/** A byte count, in the unit a human would use. */
export function formatBytes(bytes: number | null | undefined): string {
  if (typeof bytes !== "number" || Number.isNaN(bytes)) return "—"
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

/** A number of items, with the right word. */
export function pluralize(
  count: number,
  singular: string,
  plural = `${singular}s`
): string {
  return `${count} ${count === 1 ? singular : plural}`
}
