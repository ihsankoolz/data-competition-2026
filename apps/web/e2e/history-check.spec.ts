/**
 * Verify history (PRD M6, S3): "Check history is untampered" on a request page and on
 * Admin & config. After a demo reset the log is intact, and the count shown is the one the API
 * reports. There is no tamper control in the app; `make tamper-demo` does that on a copy.
 */
import { expect, type APIRequestContext, test } from "@playwright/test";

import { openAs, resetClock, submittedCustomer } from "./workflow-helpers";

async function apiCount(request: APIRequestContext): Promise<number> {
  const res = await request.get("/api/audit/verify", { headers: { "X-Acting-User": "amy" } });
  expect(res.ok(), await res.text()).toBe(true);
  const body = (await res.json()) as { ok: boolean; checked: number };
  expect(body.ok).toBe(true);
  return body.checked;
}

test.beforeEach(async ({ request }) => {
  const reset = await request.post("/api/admin/reset-demo");
  expect(reset.ok(), await reset.text()).toBe(true);
  await resetClock(request);
});

test("a request page can check that the whole history log is intact", async ({
  page,
  request,
}) => {
  const detail = await submittedCustomer(request, "History Check Pte Ltd");
  await openAs(page, "amy", `/requests/${detail.req_id}`);

  const history = page.getByTestId("history");
  await expect(history.getByRole("heading", { name: "History" })).toBeVisible();
  const result = history.getByTestId("history-check-result");
  await expect(result).toBeHidden();

  await history.getByRole("button", { name: "Check history is untampered" }).click();

  const n = await apiCount(request);
  await expect(result).toHaveText(
    `Checks the whole history log (all requests): ${n} entries intact.`,
  );
  expect(n).toBeGreaterThan(1);
});

test("Admin & config has the same check", async ({ page, request }) => {
  await openAs(page, "weijie", "/admin");
  await expect(page.getByRole("heading", { name: "Admin & config", level: 1 })).toBeVisible();
  await expect(page.getByRole("heading", { name: "History check" })).toBeVisible();
  await expect(page.getByText("any edit shows up here")).toBeVisible();

  await page.getByRole("button", { name: "Check history is untampered" }).click();

  const n = await apiCount(request);
  await expect(page.getByTestId("history-check-result")).toHaveText(
    `Checks the whole history log (all requests): ${n} entries intact.`,
  );
});
