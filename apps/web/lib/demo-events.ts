/** Fired on `window` after "Reset demo" succeeds, so open screens can drop stale drafts. */
export const DEMO_RESET_EVENT = "lives:demo-reset";

export function announceDemoReset() {
  window.dispatchEvent(new Event(DEMO_RESET_EVENT));
}

/** Fired after an approval decision, a submit or a publish, so the bell refreshes at once. */
export const WORKFLOW_CHANGED_EVENT = "lives:workflow-changed";

export function announceWorkflowChange() {
  window.dispatchEvent(new Event(WORKFLOW_CHANGED_EVENT));
}
