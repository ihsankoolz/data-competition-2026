/**
 * Storyline step 5: Priya publishes a fully approved request to the SAP B1
 * mock in one click and sees the read-back. Until the backend serves
 * `sap_publish` / `GET /requests/{id}/sap-readback`, the screen shows its
 * "read-back details are not available yet" state; the second test then
 * skips itself and lights up once the endpoint answers.
 */
import { expect, test } from "@playwright/test";

import { approveAs, openAs, resetClock, submittedCustomer } from "./workflow-helpers";

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

test("after Publish the pane stays on the published record and shows its read-back", async ({
  page,
  request,
}) => {
  // Two ready records, so a jump to "the next one" would be visible.
  await approvedCustomer(request, "Quillon Stay First Medical Pte Ltd");
  await approvedCustomer(request, "Quillon Stay Second Medical Pte Ltd");

  // Publish whatever the screen selects by default, without clicking the list.
  await openAs(page, "priya", "/publish");
  const current = page.getByTestId("publish-waiting").locator('[aria-current="true"]');
  const reqId = await current.getAttribute("data-req");
  expect(reqId).toBeTruthy();
  const pane = page.getByTestId("publish-pane");
  await pane.getByTestId("publish").click();

  await expect(page.getByTestId("publish-done").locator(`[data-req="${reqId}"]`)).toBeVisible();
  await expect(
    page.getByTestId("publish-waiting").getByTestId("publish-item").first(),
  ).toBeVisible();
  await expect(pane).toContainText(reqId!);
  await expect(pane.getByTestId("sap-readback")).toBeVisible();
  await expect(pane.getByTestId("publish")).toHaveCount(0);
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

test("status cards: Priya's says Published, a reminder at the decision time is hidden", async ({
  page,
  request,
}) => {
  const amy = { "X-Acting-User": "amy" };
  const advance = async (data: { days?: number; hours?: number }) =>
    expect((await request.post("/api/clock/advance", { headers: amy, data })).ok()).toBe(true);
  await resetClock(request);
  try {
    let d = await submittedCustomer(request, "Quillon Status Cards Medical Pte Ltd");
    await advance({ days: 1 }); // every approver gets a reminder now
    d = await approveAs(request, d, "daniel"); // same minute as his reminder
    await advance({ hours: 1 });
    for (const who of ["weijie", "meiling"]) d = await approveAs(request, d, who);
    const pub = await request.post(`/api/requests/${d.req_id}/publish`, {
      headers: { "X-Acting-User": "priya" },
    });
    expect(pub.ok(), await pub.text()).toBe(true);

    await openAs(page, "amy", `/requests/${d.req_id}`);
    const card = (u: string) => page.locator(`[data-testid="task"][data-assignee="${u}"]`);
    await expect(card("priya").getByTestId("task-status-text")).toHaveText("Published");
    await expect(card("daniel").getByTestId("task-status-text")).toHaveText("Approved");
    await expect(card("daniel").getByTestId("task-reminder")).toHaveCount(0);
    await expect(card("weijie").getByTestId("task-reminder")).toContainText("Reminder sent");
  } finally {
    await resetClock(request);
  }
});
