/**
 * Theme variants (D-022 #5, D-023). Each is a block of CSS variables in app/globals.css, chosen
 * by `data-variant` on <html>:
 *
 *   a  Sage (the original theme), kept as a fallback
 *   b  Light: sage-tinted page, white cards, dark olive sidebar, olive buttons (the default)
 *
 * To switch the whole app, change THEME_VARIANT. For a one-off preview in one browser:
 * localStorage.setItem("lives-mdm.theme-variant", "a") and reload. "Reset demo" clears it.
 */
export type ThemeVariant = "a" | "b";

export const THEME_VARIANT: ThemeVariant = "b";

export const THEME_VARIANT_STORAGE_KEY = "lives-mdm.theme-variant";

/**
 * Drops any stored preview and puts <html> back on THEME_VARIANT at once, so a preview left
 * in this browser cannot slip into a recording. Called by "Reset demo".
 */
export function clearThemePreview(): void {
  try {
    window.localStorage.removeItem(THEME_VARIANT_STORAGE_KEY);
  } catch {
    // Storage blocked (private window): nothing stored, nothing to clear.
  }
  document.documentElement.dataset.variant = THEME_VARIANT;
}

/**
 * Runs before first paint: applies a stored preview variant, if any, so there is no flash.
 * Kept tiny and dependency-free; any storage error leaves the default in place.
 */
export const THEME_PREVIEW_SCRIPT = `(function(){try{var v=localStorage.getItem(${JSON.stringify(
  THEME_VARIANT_STORAGE_KEY,
)});if(v!=="a"&&v!=="b")return;document.documentElement.dataset.variant=v;}catch(e){}})();`;
