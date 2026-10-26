/**
 * Session 13: Nguyễn Thị Lan (Quality / Regulatory, Vietnam) sees her due time
 * in Vietnam time next to SGT, and "See it in Teams" on her notification shows
 * the Adaptive Card the reminder would be. The preview's buttons decide
 * nothing: her task is still open afterwards.
 */
import { expect, test } from "@playwright/test";

import { openAs, resetClock } from "./workflow-helpers";

test("Lan's notification opens a Teams card preview with her local due time", async ({
  page,
  request,
}) => {
  await resetClock(request);
  const headers = { "X-Acting-User": "amy" };
  const name = `Teams Preview Malaria Rapid Test ${Date.now() % 100_000}`;
  const created = await request.post("/api/requests", {
    headers,
    data: {
      domain: "item",
      entity: "SPD",
      country: "SG",
      fields: {
        ItemName: name,
        U_IVD: "tYES",
        selling_countries: ["SG", "VN"],
        product_family: "A",
        registrations: [
          { country: "SG", reg_no: "DIV-001", expiry_date: "2030-01-10" },
          { country: "VN", reg_no: "VN-3", expiry_date: "2030-03-01" },
        ],
      },
    },
  });
  expect(created.ok(), await created.text()).toBe(true);
  const { req_id: id } = (await created.json()) as { req_id: string };
  const submitted = await request.post(`/api/requests/${id}/submit`, { headers });
  expect(submitted.ok(), await submitted.text()).toBe(true);

  // Part 1: her inbox card shows SGT and Vietnam time. Lan is not one of the
  // switcher's personas, so act as her from her task card (as a judge would).
  await openAs(page, "amy", `/requests/${id}`);
  await page
    .getByTestId("stage-1")
    .locator('[data-testid="task"][data-assignee="lan"]')
    .getByTestId("act-as")
    .click();
  await expect(page.getByTestId("persona-switcher")).toContainText("Nguyễn Thị Lan");
  await page.getByRole("link", { name: "Approvals" }).first().click();
  await expect(page).toHaveURL(/\/approvals/);
  const item = page.locator(`[data-testid="approval-item"][data-req="${id}"]`);
  await expect(item.getByTestId("approval-due")).toContainText("9:00 am SGT, 8:00 am in Vietnam");

  // Part 2: the bell's "See it in Teams" opens the card preview.
  await page.getByTestId("notifications-bell").click();
  const note = page.getByTestId("notification").filter({ hasText: name }).first();
  await expect(note).toContainText("SGT, 8:00 am in Vietnam");
  await page.locator(`[data-testid="see-in-teams"][data-req="${id}"]`).first().click();

  const preview = page.getByTestId("teams-card-preview");
  await expect(preview).toBeVisible();
  const card = preview.getByTestId("teams-card");
  await expect(card).toContainText(name);
  await expect(card.locator('[data-fact="Decide by"]')).toContainText(
    "9:00 am SGT, 8:00 am in Vietnam",
  );
  await expect(card.getByTestId("teams-card-action")).toHaveText([
    "Approve",
    "Ask for info",
    "Reject",
    "Open",
  ]);
  await expect(preview.getByTestId("teams-card-note")).toContainText(
    "In production, Power Automate sends this card to the approver in Teams. Nothing is sent from here.",
  );

  // The buttons do nothing and say so.
  await card.locator('[data-action="approve"]').click();
  await expect(preview.getByTestId("teams-card-pressed")).toContainText("does nothing");

  // The card JSON downloads as a file.
  const [download] = await Promise.all([
    page.waitForEvent("download"),
    preview.getByTestId("teams-card-download").click(),
  ]);
  expect(download.suggestedFilename()).toBe(`teams-card-${id}.json`);

  await expect(preview.getByTestId("teams-card-download")).toHaveText(
    "Download the card file (JSON)",
  );
  await expect(preview.getByTestId("teams-card-note")).toContainText(
    "The Open link points at this demo",
  );

  await page.keyboard.press("Escape");
  await expect(preview).toHaveCount(0);
  // Nothing was approved from the preview: the task is still in her inbox.
  await expect(item).toBeVisible();
  // The page is usable again: a dialog opened from a menu must not leave the body blocked.
  await expect(page.locator("body")).not.toHaveCSS("pointer-events", "none");
  // A normal header control still takes a click (Playwright refuses one that would not land).
  await page.getByTestId("notifications-bell").click();
  await expect(page.getByTestId("notifications-list")).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(page.getByTestId("notifications-list")).toHaveCount(0);
});
