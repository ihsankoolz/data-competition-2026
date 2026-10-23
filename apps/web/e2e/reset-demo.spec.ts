/** "Reset demo" in the header: in-app confirmation, then a toast with the duration. */
import { expect, test } from "@playwright/test";

test("reset demo asks first, then reports how long it took", async ({ page }) => {
  let calls = 0;
  await page.route("**/api/admin/reset-demo", async (route) => {
    calls += 1;
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({
        ok: true,
        duration_ms: 1234,
        counts: { requests: 0 },
        clock: {
          now: "2026-10-05T01:00:00Z",
          started_at: "2026-10-05T01:00:00Z",
          elapsed_hours: 0,
        },
        sap_mock_reset: true,
      }),
    });
  });

  await page.goto("/requests/new");
  await page.getByTestId("reset-demo").click();
  const dialog = page.getByRole("dialog");
  await expect(dialog).toContainText("Reset the demo?");

  // Cancel does nothing.
  await dialog.getByRole("button", { name: "Cancel" }).click();
  await expect(dialog).toBeHidden();
  expect(calls).toBe(0);

  await page.getByTestId("reset-demo").click();
  await page.getByTestId("reset-demo-confirm").click();
  const toast = page.getByText("Demo reset in 1.2 seconds");
  await expect(toast).toBeVisible();
  // The toast never sits on top of the notifications bell in the header.
  const bell = await page.getByTestId("notifications-bell").boundingBox();
  const box = await page.locator("[data-sonner-toast]").first().boundingBox();
  expect(bell && box).toBeTruthy();
  const overlaps =
    box!.x < bell!.x + bell!.width &&
    bell!.x < box!.x + box!.width &&
    box!.y < bell!.y + bell!.height &&
    bell!.y < box!.y + box!.height;
  expect(overlaps).toBe(false);
  await expect(page.getByRole("dialog")).toBeHidden();
  expect(calls).toBe(1);
});
