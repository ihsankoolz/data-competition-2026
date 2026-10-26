/**
 * Editable approval rules (Admin & config). Real backend, no stubs.
 *
 * Priya adds a Quality / Regulatory reviewer to the QTG Vietnam customer route and sees the
 * change in the "Who would approve this?" preview. Marcus cannot edit, and his next Vietnam
 * customer request goes to the new reviewer. The demo is reset before and after so no other
 * spec sees the changed rule.
 */
import { expect, test } from "@playwright/test";

import { actAs, openAs, resetClock } from "./workflow-helpers";

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

test("Priya adds a Vietnam reviewer; Marcus's next customer request goes to her", async ({
  page,
}) => {
  await openAs(page, "priya", "/admin");
  const editor = page.getByTestId("rules-editor");
  await expect(editor).toBeVisible();

  // Starts on the standard QTG Vietnam customer route: three reviewers, then MDM publish.
  await expect(page.getByTestId("rule-domain")).toHaveValue("customer");
  await expect(page.getByTestId("rule-entity")).toHaveValue("QTG");
  await expect(page.getByTestId("rule-country")).toHaveValue("VN");
  await expect(page.getByTestId("rule-source")).toHaveText("Standard route");
  await expect(page.getByTestId("rule-step")).toHaveCount(3);
  const preview = page.getByTestId("rule-preview");
  await expect(preview.getByTestId("preview-task")).toHaveCount(4);
  await expect(preview.locator('[data-user="lan"]')).toHaveCount(0);
  await expect(page.getByTestId("rule-applies-note")).toHaveText(
    "Changes apply to new requests only. Requests already in approval keep their approvers.",
  );

  // Add a step: Quality / Regulatory, Nguyen Thi Lan. The preview follows the unsaved draft.
  await page.getByTestId("add-step-role").selectOption("quality_regulatory");
  await page.getByTestId("add-step-person").selectOption("lan");
  await page.getByTestId("add-step").click();
  await expect(page.getByTestId("rule-step")).toHaveCount(4);
  await expect(preview.getByTestId("preview-task")).toHaveCount(5);
  await expect(preview.locator('[data-user="lan"]')).toBeVisible();
  await expect(preview).toContainText("with your unsaved changes");

  await page.getByTestId("rule-save").click();
  await expect(page.getByTestId("rule-saved")).toContainText("New QTG customer requests (Vietnam)");
  await expect(page.getByTestId("rule-source")).toHaveAttribute("data-override", "true");
  const change = page.getByTestId("config-change").first();
  await expect(change).toContainText("Priya changed the approvers for QTG customers (VN)");
  await expect(change).toContainText("Quality / Regulatory: Nguyễn Thị Lan");

  // Marcus can look but not change.
  await actAs(page, "Marcus");
  await expect(page.getByTestId("rule-save")).toBeDisabled();
  await expect(page.getByTestId("rule-save-note")).toHaveText(
    "Only the MDM team can change approval rules. Switch to Priya to edit.",
  );
  await expect(page.getByTestId("rule-step")).toHaveCount(4);

  // His next Vietnam customer request goes to the new reviewer too.
  const stamp = String(Date.now()).slice(-8);
  const headers = { "X-Acting-User": "marcus" };
  const created = await page.request.post("/api/requests", {
    headers,
    data: {
      domain: "customer",
      entity: "QTG",
      country: "VN",
      fields: {
        CardName: `Rules Editor Test Hospital ${stamp}`,
        Country: "VN",
        FederalTaxID: `88${stamp}`,
        Street: "12 Test Street",
        City: "Hanoi",
        EmailAddress: `ap${stamp}@rulestest.example`,
      },
    },
  });
  expect(created.ok(), await created.text()).toBe(true);
  const { req_id } = (await created.json()) as { req_id: string };
  const submitted = await page.request.post(`/api/requests/${req_id}/submit`, { headers });
  expect(submitted.ok(), await submitted.text()).toBe(true);

  await page.goto(`/requests/${req_id}`);
  await expect(page.getByTestId("request-state")).toHaveAttribute("data-state", "IN_APPROVAL");
  const stage1 = page.getByTestId("stage-1");
  await expect(stage1.getByTestId("task")).toHaveCount(4);
  await expect(stage1.locator('[data-testid="task"][data-assignee="lan"]')).toBeVisible();
});
