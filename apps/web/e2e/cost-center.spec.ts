/**
 * Session 13: Cost Center on "New request". Amy fills the schema-driven form, submits, and the
 * status page shows the two reviewers (Finance and BU Head) in stage 1 and MDM publish after.
 * Real backend, no stubs. The UI always says "Cost Center", never "Profit Center".
 */
import { expect, test } from "@playwright/test";

import { openAs, resetClock } from "./workflow-helpers";

const RESET = { headers: { "X-Acting-User": "amy" } };

test.beforeEach(async ({ request }) => {
  const res = await request.post("/api/admin/reset-demo", RESET);
  expect(res.ok(), await res.text()).toBe(true);
});

test.afterEach(async ({ request }) => {
  const res = await request.post("/api/admin/reset-demo", RESET);
  expect(res.ok(), await res.text()).toBe(true);
  await resetClock(request);
});

test("Amy requests a Cost Center and Finance plus the BU Head are asked to approve", async ({
  page,
}) => {
  await openAs(page, "amy", "/requests/new");
  await page.getByRole("radio", { name: "Cost Center" }).click();

  // The form renders from config/forms/cost_center.schema.json.
  const form = page.getByRole("form", { name: "New cost center form" });
  await expect(page.getByLabel("Cost center name")).toBeVisible();
  await expect(page.getByTestId("field-CenterName")).toContainText("Required");
  await expect(page.getByTestId("field-EffectiveFrom")).toContainText("Required");
  await expect(page.getByTestId("field-InWhichDimension")).toBeVisible();
  await expect(page.getByTestId("sap-note")).toContainText("distribution rule");
  await expect(form).not.toContainText("Profit Center");
  await expect(page.getByTestId("submit-hint")).toHaveText("2 required fields are still empty.");

  await page.getByLabel("Cost center name").fill("SPD SG Tender Desk");
  await page.getByLabel("Effective from").fill("2026-11-02");
  await expect(page.getByTestId("submit-hint")).toHaveText("Everything required is filled in.");
  await page.getByTestId("submit").click();

  // The status page: Finance and BU Head review together, then MDM publishes.
  await expect(page.getByTestId("request-state")).toHaveAttribute("data-state", "IN_APPROVAL");
  const stage1 = page.getByTestId("stage-1");
  await expect(stage1.getByTestId("task")).toHaveCount(2);
  await expect(stage1).toContainText("Finance");
  await expect(stage1).toContainText("BU Head");
  await expect(stage1).toContainText("Wei Jie");
  await expect(stage1).toContainText("Daniel");
  await expect(page.getByTestId("stage-2")).toContainText("Priya");
  await expect(page.getByTestId("request-fields")).toContainText("SPD SG Tender Desk");
  await expect(page.locator("body")).not.toContainText("Profit Center");
});
