/**
 * The persona the app is acting as. There is no login in this prototype:
 * the header switcher sets it, it is remembered in localStorage, and the
 * API client sends it as the X-Acting-User header on every call.
 *
 * Besides the eight headline personas, the presenter can act as any other
 * seeded person who has a task (for example the Singapore Quality/Regulatory
 * reviewer) from the status page. That person's name and role are stored next
 * to the id, because they are not in the persona list.
 */
import { useSyncExternalStore } from "react";

export const DEFAULT_ACTING_USER = "amy";
const STORAGE_KEY = "lives-mdm.acting-user";
const OTHER_KEY = "lives-mdm.acting-user-other";

/** A seeded person outside the eight personas, as shown on their approval task. */
export type OtherPerson = {
  user_id: string;
  name: string;
  title: string;
  country: string | null;
};

let current: string | null = null;
let other: OtherPerson | null | undefined;
const listeners = new Set<() => void>();

function readStored(): string {
  try {
    return window.localStorage.getItem(STORAGE_KEY) ?? DEFAULT_ACTING_USER;
  } catch {
    return DEFAULT_ACTING_USER;
  }
}

function readOther(): OtherPerson | null {
  try {
    const raw = window.localStorage.getItem(OTHER_KEY);
    if (!raw) return null;
    const p = JSON.parse(raw) as Partial<OtherPerson>;
    if (typeof p.user_id !== "string" || typeof p.name !== "string" || !p.name.trim()) return null;
    return {
      user_id: p.user_id,
      name: p.name,
      title: typeof p.title === "string" ? p.title : "",
      country: typeof p.country === "string" ? p.country : null,
    };
  } catch {
    return null;
  }
}

function emit() {
  for (const l of listeners) l();
}

export function getActingUserId(): string {
  if (typeof window === "undefined") return DEFAULT_ACTING_USER;
  current ??= readStored();
  return current;
}

/** The stored non-persona person, only when it is the one being acted as. */
export function getOtherPerson(): OtherPerson | null {
  if (typeof window === "undefined") return null;
  if (other === undefined) other = readOther();
  return other && other.user_id === getActingUserId() ? other : null;
}

function writeOther(p: OtherPerson | null) {
  other = p;
  try {
    if (p) window.localStorage.setItem(OTHER_KEY, JSON.stringify(p));
    else window.localStorage.removeItem(OTHER_KEY);
  } catch {
    // Blocked storage: keep it for this tab only.
  }
}

function writeId(userId: string) {
  current = userId;
  try {
    window.localStorage.setItem(STORAGE_KEY, userId);
  } catch {
    // Private mode or blocked storage: keep the choice for this tab only.
  }
}

/** Act as one of the eight personas (forgets any other person). */
export function setActingUserId(userId: string) {
  writeId(userId);
  if (other === undefined) other = readOther();
  if (other && other.user_id !== userId) writeOther(null);
  emit();
}

/** Act as a seeded person who is not one of the personas, e.g. a pending approver. */
export function actAsOtherPerson(p: OtherPerson) {
  writeOther(p);
  writeId(p.user_id);
  emit();
}

function subscribe(listener: () => void) {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

/** The acting user's id, or null during server render / hydration. */
export function useActingUserId(): string | null {
  return useSyncExternalStore(subscribe, getActingUserId, () => null);
}

/** The non-persona person being acted as, if any. */
export function useOtherPerson(): OtherPerson | null {
  return useSyncExternalStore(subscribe, getOtherPerson, () => null);
}
