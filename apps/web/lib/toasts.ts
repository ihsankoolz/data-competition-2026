/**
 * Toast lifecycle rules (D-022 #5): a toast lasts about 3 seconds and is cleared when the
 * page changes, so an old confirmation never sits over the next screen.
 *
 * A toast that announces the navigation itself ("Request submitted", then the app opens the
 * status page) is kept through that one page change: create it with `toastAcrossNavigation`.
 */
import { toast } from "sonner";

/** How long a toast stays on screen, in ms. */
export const TOAST_DURATION_MS = 3_000;

const keepThroughNextNavigation = new Set<string | number>();

/** Show a toast that survives the next page change (and only that one). */
export function toastAcrossNavigation(show: () => string | number): string | number {
  const id = show();
  keepThroughNextNavigation.add(id);
  return id;
}

/** Dismiss every toast on screen, except those created for this navigation. */
export function dismissToastsOnNavigation(): void {
  for (const t of toast.getToasts()) {
    if (!keepThroughNextNavigation.has(t.id)) toast.dismiss(t.id);
  }
  keepThroughNextNavigation.clear();
}
