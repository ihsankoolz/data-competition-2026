/**
 * Storyline steps 3-4 against the real backend: Amy's request waits on three
 * approvers in parallel; Daniel approves from his inbox; the status page and
 * the audit trail show it. Mei Ling's "ask for info" needs a comment.
 */
import { expect, test } from "@playwright/test";

import { actAs, openAs, submittedCustomer } from "./workflow-helpers";

test("approver approves from the inbox and Amy's status page updates", async ({
  page,
  request,
}) => {
  const detail = await submittedCustomer(request, "Quillon Approve Flow Medical Pte Ltd");
  const id = detail.req_id;

  // Amy sees exactly who is pending, side by side.
  await openAs(page, "amy", `/requests/${id}`);
  await expect(page.getByTestId("request-state")).toHaveAttribute("data-state", "IN_APPROVAL");
  await expect(page.getByTestId("pending-with")).toContainText("Daniel");
  await expect(page.getByTestId("pending-with")).toContainText("Wei Jie");
  const stage1 = page.getByTestId("stage-1");
  await expect(stage1.getByTestId("task")).toHaveCount(3);
  await expect(stage1.locator('[data-testid="task"][data-status="pending"]')).toHaveCount(3);
  await expect(page.getByTestId("stage-2")).toHaveAttribute("data-status", "waiting");
  // Amy is the requestor: no decision buttons for her own request.
  await expect(page.getByTestId("your-turn")).toHaveCount(0);

  // Daniel approves from his inbox.
  await actAs(page, "Daniel");
  await page.goto("/approvals");
  const item = page.locator(`[data-testid="approval-item"][data-req="${id}"]`);
  await item.click();
  const pane = page.getByTestId("approval-pane");
  await expect(pane).toContainText("Quillon Approve Flow Medical Pte Ltd");
  await expect(pane.getByTestId("request-fields")).toContainText("8 Kallang Way");
  await pane.getByTestId("approve").click();
  await expect(page.getByText(/Approved: Quillon Approve Flow/)).toBeVisible();
  await expect(item).toHaveCount(0);

  // The status page shows Daniel's tick and the audit line.
  await page.goto(`/requests/${id}`);
  await expect(page.locator('[data-testid="task"][data-assignee="daniel"]')).toHaveAttribute(
    "data-status",
    "approved",
  );
  await expect(page.getByTestId("pending-with")).not.toContainText("Daniel");
  await expect(page.getByTestId("audit-timeline")).toContainText("Daniel approved (BU Head)");

  // Mei Ling asks for more information: the comment is required.
  await actAs(page, "Mei Ling");
  await expect(page.getByTestId("your-turn")).toBeVisible();
  await page.getByTestId("ask-info").click();
  const confirm = page.getByTestId("decision-confirm");
  await expect(confirm).toBeDisabled();
  await page.getByTestId("decision-comment").fill("Please add the billing contact's phone number.");
  await confirm.click();
  await expect(page.getByTestId("request-state")).toHaveAttribute("data-state", "INFO_REQUESTED");
  await expect(page.getByTestId("audit-timeline")).toContainText("billing contact");
});
