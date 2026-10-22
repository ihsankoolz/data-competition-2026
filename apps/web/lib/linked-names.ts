/**
 * The name of the existing record a request was linked to, remembered in this
 * browser at the moment of linking. The request API returns only the code
 * (`linked_card_code`), so the status page uses this to say "Linked to
 * Bệnh viện Chợ Rẫy (C00084)". Falls back to the code when not known.
 */
const KEY = "lives-mdm.linked-names";

type Stash = Record<string, { code: string; name: string }>;

function read(): Stash {
  try {
    return JSON.parse(window.localStorage.getItem(KEY) ?? "{}") as Stash;
  } catch {
    return {};
  }
}

export function rememberLinkedName(reqId: string, code: string, name: string) {
  try {
    window.localStorage.setItem(KEY, JSON.stringify({ ...read(), [reqId]: { code, name } }));
  } catch {
    // Blocked storage: the status page shows the code alone.
  }
}

export function linkedLabel(reqId: string, code: string | null | undefined): string {
  if (!code) return "the existing record";
  const hit = typeof window === "undefined" ? undefined : read()[reqId];
  return hit && hit.code === code ? `${hit.name} (${code})` : code;
}
