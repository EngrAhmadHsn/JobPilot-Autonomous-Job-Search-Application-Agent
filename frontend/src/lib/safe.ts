/**
 * Safe accessors for loosely-typed server data.
 *
 * Two API routes answer with free-form JSON: the persisted match history
 * (a `scores` dictionary) and the approval evidence. A free-form dictionary
 * has no schema, so the console reads it through these accessors instead of
 * casting it — an unexpected value becomes a sensible default, never a
 * `TypeError` in the middle of a render.
 */

/** A string, or the fallback. */
export function asString(value: unknown, fallback = ""): string {
  return typeof value === "string" ? value : fallback
}

/** A number, or the fallback. */
export function asNumber(value: unknown, fallback = 0): number {
  if (typeof value === "number" && Number.isFinite(value)) return value
  if (typeof value === "string") {
    const parsed = Number(value)
    if (Number.isFinite(parsed)) return parsed
  }
  return fallback
}

/** A list of strings; anything that is not a string is dropped. */
export function asStringArray(value: unknown): string[] {
  if (!Array.isArray(value)) return []
  return value.filter((item): item is string => typeof item === "string")
}

/** A dictionary, or an empty one. */
export function asRecord(value: unknown): Record<string, unknown> {
  if (typeof value !== "object" || value === null || Array.isArray(value))
    return {}
  return value as Record<string, unknown>
}
