/**
 * Shared set-up for the workflow specs: create, submit and approve requests
 * straight through the API (via the web app's /api proxy), so each spec
 * starts from a known state without clicking through the form.
 */
import { expect, type APIRequestContext, type Page } from "@playwright/test";

type Json = Record<string, unknown>;
type Task = { task_id: string; role: string; assignee_user_id: string; stage: number };
type Detail = { req_id: string; state: string; stages: { tasks: Task[] }[] };

let counter = 0;

/** A Singapore UEN-shaped tax ID that no seeded customer has. */
function freshTaxId(): string {
  counter += 1;
  const n = (Date.now() % 90_000) + 10_000 + counter;
  return `2026${String(n).padStart(5, "0")}Z`;
}

async function call(
  request: APIRequestContext,
  method: "get" | "post" | "patch",
  path: string,
  user: string,
  data?: Json,
) {
  const res = await request[method](`/api${path}`, {
    headers: { "X-Acting-User": user },
    data,
  });
  expect(res.ok(), `${method.toUpperCase()} ${path} as ${user}: ${await res.text()}`).toBe(true);
  return (await res.json()) as Detail;
}

/** Amy's customer request, submitted: three approvers decide in parallel (D-007). */
export async function submittedCustomer(request: APIRequestContext, name: string) {
  const created = await call(request, "post", "/requests", "amy", {
    domain: "customer",
    entity: "SPD",
    country: "SG",
    fields: {
      CardName: name,
      Country: "SG",
      FederalTaxID: freshTaxId(),
      Street: "8 Kallang Way",
      City: "Singapore",
      EmailAddress: "ap@example.com",
    },
  });
  return call(request, "post", `/requests/${created.req_id}/submit`, "amy");
}

export function taskFor(detail: Detail, user: string): Task {
  const task = detail.stages.flatMap((s) => s.tasks).find((t) => t.assignee_user_id === user);
  if (!task) throw new Error(`No task for ${user} on ${detail.req_id}`);
  return task;
}

export async function approveAs(request: APIRequestContext, detail: Detail, user: string) {
  return call(request, "post", `/approvals/${taskFor(detail, user).task_id}/decision`, user, {
    action: "approve",
  });
}

export async function resetClock(request: APIRequestContext) {
  const res = await request.post("/api/clock/reset", { headers: { "X-Acting-User": "amy" } });
  expect(res.ok()).toBe(true);
}

/** Switch persona the way a presenter does: through the header menu. */
export async function actAs(page: Page, name: string) {
  await page.getByTestId("persona-switcher").click();
  await page.getByRole("menuitemradio", { name: new RegExp(`^${name}`) }).click();
  await expect(page.getByTestId("persona-switcher")).toContainText(name);
}

/**
 * Start the test as a persona. The choice is written once per tab, so a later
 * switch in the header menu survives reloads and navigation.
 */
export async function openAs(page: Page, user: string, path: string) {
  await page.addInitScript((u) => {
    if (window.sessionStorage.getItem("e2e-persona-set")) return;
    window.sessionStorage.setItem("e2e-persona-set", "1");
    window.localStorage.setItem("lives-mdm.acting-user", u);
  }, user);
  await page.goto(path);
}
