/**
 * The current candidate profile.
 *
 * The API has no endpoint that lists the stored profiles (BA-4 in
 * `docs/implementation/13-frontend.md`), so the console keeps the id of the
 * profile the operator is working with **client-side**, in `localStorage`.
 *
 * That is a deliberate, documented limitation: the id is a per-browser
 * convenience, not a source of truth. The server is still the source of
 * truth for the profile itself, and the console always shows which profile
 * is current so the operator can see when it is stale.
 */
import { useSyncExternalStore } from "react"

const STORAGE_KEY = "aja.currentProfileId"

const listeners = new Set<() => void>()

function read(): string | null {
  try {
    const value = window.localStorage.getItem(STORAGE_KEY)
    return value && value.trim() ? value : null
  } catch {
    // A private-mode browser or a storage-disabled environment: the console
    // still works, it just cannot remember the profile between reloads.
    return null
  }
}

let current: string | null = read()

function write(value: string | null): void {
  current = value
  try {
    if (value) {
      window.localStorage.setItem(STORAGE_KEY, value)
    } else {
      window.localStorage.removeItem(STORAGE_KEY)
    }
  } catch {
    // See read(): a storage failure must not break the console.
  }
  for (const listener of listeners) listener()
}

/** The profile the console is working with, or null when none is chosen. */
export function getCurrentProfileId(): string | null {
  return current
}

/** Choose the profile the console works with (null clears it). */
export function setCurrentProfileId(profileId: string | null): void {
  write(profileId)
}

/** Subscribe to changes of the current profile. */
export function subscribeToCurrentProfile(listener: () => void): () => void {
  listeners.add(listener)
  return () => listeners.delete(listener)
}

/** The current profile id, as a reactive value. */
export function useCurrentProfileId(): string | null {
  return useSyncExternalStore(
    subscribeToCurrentProfile,
    getCurrentProfileId,
    () => null
  )
}
