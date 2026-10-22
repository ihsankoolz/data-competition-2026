/** Fired on `window` after "Reset demo" succeeds, so open screens can drop stale drafts. */
export const DEMO_RESET_EVENT = "lives:demo-reset";

export function announceDemoReset() {
  window.dispatchEvent(new Event(DEMO_RESET_EVENT));
}
