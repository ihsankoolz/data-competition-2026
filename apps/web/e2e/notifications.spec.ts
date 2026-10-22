/**
 * The header bell: a new task shows as an unread count for the approver,
 * opening the list marks it read, and a click goes to the request. Moving
 * the demo clock one working day sends Wei Jie a reminder (storyline step 4).
 */
import { expect, test } from "@playwright/test";

import { openAs, resetClock, submittedCustomer } from "./workflow-helpers";

test("approver's bell counts new tasks and links to the request", async ({ page, request }) => {
  await resetClock(request);
  const detail = await submittedCustomer(request, "Quillon Bell Medical Pte Ltd");

  await openAs(page, "weijie", "/approvals");
  const bell = page.getByTestId("notifications-bell");
  await expect(bell.getByTestId("notifications-count")).toBeVisible();

  await bell.click();
  const mine = page.getByTestId("notification").filter({ hasText: "Quillon Bell Medical" }).first();
  await expect(mine).toBeVisible();
  await page.keyboard.press("Escape");
  // Everything in the list is now read.
  await expect(bell.getByTestId("notifications-count")).toHaveCount(0);

  // One working day later the reminder arrives and the count comes back.
  await page.getByRole("button", { name: "+1 day" }).click();
  await expect(bell.getByTestId("notifications-count")).toBeVisible({ timeout: 15_000 });
  await bell.click();
  await expect(
    page.locator('[data-testid="notification"][data-kind="reminder"]').first(),
  ).toBeVisible();
  await page
    .getByTestId("notification")
    .filter({ hasText: "Quillon Bell Medical" })
    .first()
    .click();
  await expect(page).toHaveURL(new RegExp(`/requests/${detail.req_id}$`));
  await expect(
    page.locator('[data-testid="task"][data-assignee="weijie"] [data-testid="sla-badge"]'),
  ).toHaveAttribute("data-sla", "reminded");

  await resetClock(request);
});
