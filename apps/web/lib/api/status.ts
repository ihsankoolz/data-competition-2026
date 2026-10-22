/**
 * Tracks whether the API answered the last call. The API client reports
 * into it; the header reads it to show the "server offline" notice.
 */
import { useSyncExternalStore } from "react";

let online = true;
const listeners = new Set<() => void>();

function set(next: boolean) {
  if (next === online) return;
  online = next;
  for (const l of listeners) l();
}

export function reportApiOnline() {
  set(true);
}

export function reportApiOffline() {
  set(false);
}

function subscribe(listener: () => void) {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

/** True until a call fails to reach the server. */
export function useApiOnline(): boolean {
  return useSyncExternalStore(
    subscribe,
    () => online,
    () => true,
  );
}
