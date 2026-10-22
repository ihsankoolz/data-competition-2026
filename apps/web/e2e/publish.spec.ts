/**
 * Storyline step 5: Priya publishes a fully approved request to the SAP B1
 * mock in one click and sees the read-back. Until the backend serves
 * `sap_publish` / `GET /requests/{id}/sap-readback`, the screen shows its
 * "read-back details are not available yet" state; the second test then
 * skips itself and lights up once the endpoint answers.
 */
import { expect, test } from "@playwright/test";

import { approveAs, openAs, submittedCustomer } from "./workflow-helpers";

async function approvedCustomer(request: Parameters<typeof submittedCustomer>[0], name: string) {
  let d = await submittedCustomer(request, name);
  for (const who of ["daniel", "weijie", "meiling"]) d = await approveAs(request, d, who);
  expect(d.state).toBe("APPROVED");
  return d;
}

test("Priya publishes in one click and sees the read-back or its empty state", async ({
  page,
  request,
}) => {
  const d = await approvedCustomer(request, "Quillon Publish Medical Pte Ltd");

  // Someone who is not a master-data analyst is told who can publish.
  await openAs(page, "amy", "/publish");
  await expect(page.getByTestId("not-analyst")).toContainText("Priya");

  await page.evaluate(() => window.localStorage.setItem("lives-mdm.acting-user", "priya"));
  await page.reload();
  await expect(page.getByTestId("persona-switcher")).toContainText("Priya");
  await page.locator(`[data-testid="publish-item"][data-req="${d.req_id}"]`).click();
  const pane = page.getByTestId("publish-pane");
  await expect(pane).toContainText("POST /b1s/v2/BusinessPartners");
  await pane.getByTestId("publish").click();

  await expect(pane.getByTestId("request-state")).toHaveAttribute(
    "data-state",
    /ACTIVE|PUBLISHED_INACTIVE/,
  );
  await expect(
    pane.getByTestId("readback-result").or(pane.getByTestId("readback-unavailable")),
  ).toBeVisible();
  await expect(page.getByText(/Published to SAP: Quillon Publish/)).toBeVisible();
  // It moved from "Ready to publish" to "Published".
  await expect(page.getByTestId("publish-done").locator(`[data-req="${d.req_id}"]`)).toBeVisible();
});

test("read-back table: every field matches and the record is active", async ({ page, request }) => {
  const d = await approvedCustomer(request, "Quillon Readback Medical Pte Ltd");
  const pub = await request.post(`/api/requests/${d.req_id}/publish`, {
    headers: { "X-Acting-User": "priya" },
  });
  expect(pub.ok()).toBe(true);
  const rb = await request.get(`/api/requests/${d.req_id}/sap-readback`, {
    headers: { "X-Acting-User": "priya" },
  });
  test.skip(!rb.ok(), `Waiting on the backend: sap-readback answered ${rb.status()}.`);

  await openAs(page, "priya", "/publish");
  await page.locator(`[data-testid="publish-item"][data-req="${d.req_id}"]`).click();
  const table = page.getByTestId("sap-readback");
  await expect(table.getByTestId("readback-result")).toHaveAttribute("data-match", "true");
  await expect(table.getByTestId("sap-active")).toHaveText("Active in SAP");
  await expect(table.locator('[data-testid="readback-row"][data-match="false"]')).toHaveCount(0);
  await expect(table.getByTestId("readback-row").first()).toBeVisible();
});
