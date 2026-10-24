/**
 * Theme variants (D-022 #5). Each is a block of CSS variables in app/globals.css, chosen by
 * `data-variant` on <html>:
 *
 *   a  Sage (the original theme)
 *   b  Light: sage-tinted page, white cards, dark olive sidebar, olive buttons
 *   c  Dark, from the tweakcn theme file (also sets the `dark` class)
 *
 * To switch the whole app, change THEME_VARIANT. For a one-off preview in one browser:
 * localStorage.setItem("lives-mdm.theme-variant", "b") and reload. "Reset demo" clears it.
 */
export type ThemeVariant = "a" | "b" | "c";

export const THEME_VARIANT: ThemeVariant = "a";

export const THEME_VARIANT_STORAGE_KEY = "lives-mdm.theme-variant";

/** Class names <html> needs for a variant (C reuses the `.dark` block). */
export function variantClass(v: ThemeVariant): string {
  return v === "c" ? "dark" : "";
}

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
  const html = document.documentElement;
  html.dataset.variant = THEME_VARIANT;
  html.classList.toggle("dark", THEME_VARIANT === "c");
}

/**
 * Runs before first paint: applies a stored preview variant, if any, so there is no flash.
 * Kept tiny and dependency-free; any storage error leaves the default in place.
 */
export const THEME_PREVIEW_SCRIPT = `(function(){try{var v=localStorage.getItem(${JSON.stringify(
  THEME_VARIANT_STORAGE_KEY,
)});if(v!=="a"&&v!=="b"&&v!=="c")return;var h=document.documentElement;h.dataset.variant=v;h.classList.toggle("dark",v==="c");}catch(e){}})();`;
