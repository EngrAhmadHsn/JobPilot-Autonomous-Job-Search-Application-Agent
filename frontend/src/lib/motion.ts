/**
 * The visitor's motion preference.
 *
 * The OS preference (`prefers-reduced-motion`) is the default, and it is
 * never ignored — a visitor who has asked their machine for less motion gets
 * less motion. But it is also **not the only source of truth**: Windows'
 * "Animation effects" toggle is off on plenty of machines for reasons that
 * have nothing to do with the person using this site (an OEM image, a
 * battery-saving tweak), and a product should not become a static page for
 * that reason alone.
 *
 * So the preference has three values:
 *
 * - `system` (the default) — follow the OS;
 * - `full` — play everything, whatever the OS says;
 * - `reduced` — no movement, whatever the OS says.
 *
 * The **effective** value (`full` | `reduced`) is mirrored onto
 * `<html data-motion="…">`, which is what the CSS keys on. It is set by
 * `initMotion()` from `main.tsx` **before the first render**, so no content
 * is ever painted with the wrong motion setting.
 */
import { useSyncExternalStore } from "react"

export type MotionPreference = "system" | "full" | "reduced"
export type EffectiveMotion = "full" | "reduced"

const STORAGE_KEY = "jobpilot.motion"
const MEDIA_QUERY = "(prefers-reduced-motion: reduce)"

const listeners = new Set<() => void>()

function readPreference(): MotionPreference {
  try {
    const value = window.localStorage.getItem(STORAGE_KEY)
    return value === "full" || value === "reduced" || value === "system"
      ? value
      : "system"
  } catch {
    return "system"
  }
}

function systemPrefersReduced(): boolean {
  if (typeof window === "undefined" || !window.matchMedia) return false
  return window.matchMedia(MEDIA_QUERY).matches
}

let preference: MotionPreference = "system"
let initialised = false

function effective(): EffectiveMotion {
  if (preference === "full") return "full"
  if (preference === "reduced") return "reduced"
  return systemPrefersReduced() ? "reduced" : "full"
}

function publish(): void {
  if (typeof document !== "undefined") {
    document.documentElement.setAttribute("data-motion", effective())
  }
  for (const listener of listeners) listener()
}

/**
 * Read the stored preference, watch the OS, and publish the effective value.
 * Called once from the entry point, before React renders.
 */
export function initMotion(): void {
  if (initialised) return
  initialised = true
  preference = readPreference()
  if (typeof window !== "undefined" && window.matchMedia) {
    // The listener lives for the page's lifetime, which is what we want.
    window.matchMedia(MEDIA_QUERY).addEventListener("change", publish)
  }
  publish()
}

/** The visitor's chosen preference (not the resolved value). */
export function getMotionPreference(): MotionPreference {
  return preference
}

/** Choose a preference; persists and republishes immediately. */
export function setMotionPreference(next: MotionPreference): void {
  preference = next
  try {
    window.localStorage.setItem(STORAGE_KEY, next)
  } catch {
    // A storage failure must not break the page; the choice just will not
    // survive a reload.
  }
  publish()
}

/** Subscribe to preference and OS changes. */
export function subscribeToMotion(listener: () => void): () => void {
  listeners.add(listener)
  return () => listeners.delete(listener)
}

/** The chosen preference, as a reactive value. */
export function useMotionPreference(): MotionPreference {
  return useSyncExternalStore(subscribeToMotion, getMotionPreference, () => "system")
}

/**
 * Whether movement should be suppressed — the single question the animated
 * components ask. Derived from the **effective** value, so choosing "full"
 * turns the light field back on even when the OS says reduce.
 */
export function useEffectiveReducedMotion(): boolean {
  return useSyncExternalStore(
    subscribeToMotion,
    () => effective() === "reduced",
    () => false
  )
}

/** The effective value, for code outside React. */
export function getEffectiveMotion(): EffectiveMotion {
  return effective()
}

/** Exposed for the OS-preference hook (`useReducedMotion`) to share the query. */
export const REDUCED_MOTION_QUERY = MEDIA_QUERY