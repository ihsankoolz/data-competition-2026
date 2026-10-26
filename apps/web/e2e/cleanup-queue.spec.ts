/**
 * Clean-up queue: the groups behind the regional "after merge" view. Priya confirms one link and
 * marks another as not the same (with a reason); Marcus sees the queue read-only; the regional
 * view's caption links here. The demo is reset before and after, so no decision leaks into
 * other specs.
 */
import { expect, type APIRequestContext, test } from "@playwright/test";

import { openAs, resetClock } from "./workflow-helpers";

async function resetDemo(request: APIRequestContext) {
  const res = await request.post("/api/admin/reset-demo", {
    headers: { "X-Acting-User": "amy" },
  });
  expect(res.ok(), await res.text()).toBe(true);
  await resetClock(request);
}

test.beforeEach(async ({ request }) => resetDemo(request));
test.afterEach(async ({ request }) => resetDemo(request));

test("Priya confirms one group and marks another as not the same", async ({ page }) => {
  await openAs(page, "priya", "/cleanup");
  await expect(page.getByRole("heading", { name: "Clean-up queue" })).toBeVisible();
  const counter = page.getByTestId("cleanup-counter");
  await expect(counter).toHaveText(/^0 of \d+ reviewed$/);
  const total = Number((await counter.textContent())!.match(/of (\d+)/)![1]);
  expect(total).toBeGreaterThan(100);
  await expect(page.getByTestId("cleanup-readonly")).toHaveCount(0);

  const groups = page.getByTestId("cleanup-group");
  const first = groups.nth(0);
  await expect(first.getByTestId("cleanup-records")).toBeVisible();
  // The most certain group comes first: same tax ID, with the check's reasons listed.
  await expect(first.getByTestId("cleanup-reasons")).toContainText("Same");
  await expect(first.getByTestId("cleanup-reasons").locator("li").first()).toBeVisible();

  await first.getByTestId("cleanup-confirm").click();
  await expect(first.getByTestId("cleanup-decision")).toContainText("Link confirmed");
  await expect(first.getByTestId("cleanup-decision")).toContainText("By Priya");
  await expect(counter).toHaveText(`1 of ${total} reviewed`);

  const second = groups.nth(1);
  await second.getByTestId("cleanup-not-same").click();
  const dialog = page.getByRole("dialog");
  await expect(dialog).toContainText("Why are these different customers?");
  // A reason is required before it can be saved.
  await expect(dialog.getByTestId("cleanup-reason-save")).toBeDisabled();
  await dialog.getByTestId("cleanup-reason").fill("Two separate hospitals with their own accounts");
  await dialog.getByTestId("cleanup-reason-save").click();
  await expect(dialog).toBeHidden();
  await expect(second.getByTestId("cleanup-decision")).toContainText(
    "Marked as not the same customer",
  );
  await expect(second.getByTestId("cleanup-decision")).toContainText(
    "Two separate hospitals with their own accounts",
  );
  await expect(counter).toHaveText(`2 of ${total} reviewed`);

  // Decisions survive a reload.
  await page.reload();
  await expect(counter).toHaveText(`2 of ${total} reviewed`);
  await expect(groups.nth(0)).toHaveAttribute("data-status", "confirmed");
  await expect(groups.nth(1)).toHaveAttribute("data-status", "not_same");
});

test("Marcus sees the queue read-only", async ({ page }) => {
  await openAs(page, "marcus", "/cleanup");
  await expect(page.getByTestId("cleanup-readonly")).toContainText("Priya");
  const first = page.getByTestId("cleanup-group").first();
  await expect(first.getByTestId("cleanup-records")).toBeVisible();
  await expect(first.getByTestId("cleanup-confirm")).toBeDisabled();
  await expect(first.getByTestId("cleanup-not-same")).toBeDisabled();
});

test("the regional view's after-merge caption links to the clean-up queue", async ({ page }) => {
  await openAs(page, "priya", "/regional");
  const caption = page.getByTestId("merge-cleanup-caption");
  await expect(caption).toContainText("After merge uses the links the duplicate check proposes");
  await caption.getByRole("link", { name: "Clean-up queue" }).click();
  await expect(page).toHaveURL(/\/cleanup$/);
  await expect(page.getByTestId("cleanup-counter")).toHaveText(/^0 of \d+ reviewed$/);
});
