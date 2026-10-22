/**
 * The persona the app is acting as. There is no login in this prototype:
 * the header switcher sets it, it is remembered in localStorage, and the
 * API client sends it as the X-Acting-User header on every call.
 */
import { useSyncExternalStore } from "react";

export const DEFAULT_ACTING_USER = "amy";
const STORAGE_KEY = "lives-mdm.acting-user";

let current: string | null = null;
const listeners = new Set<() => void>();

function readStored(): string {
  try {
    return window.localStorage.getItem(STORAGE_KEY) ?? DEFAULT_ACTING_USER;
  } catch {
    return DEFAULT_ACTING_USER;
  }
}

export function getActingUserId(): string {
  if (typeof window === "undefined") return DEFAULT_ACTING_USER;
  current ??= readStored();
  return current;
}

export function setActingUserId(userId: string) {
  current = userId;
  try {
    window.localStorage.setItem(STORAGE_KEY, userId);
  } catch {
    // Private mode or blocked storage: keep the choice for this tab only.
  }
  for (const l of listeners) l();
}

function subscribe(listener: () => void) {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

/** The acting user's id, or null during server render / hydration. */
export function useActingUserId(): string | null {
  return useSyncExternalStore(subscribe, getActingUserId, () => null);
}
