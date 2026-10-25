/**
 * Reset demo while the header reads the clock and polls the bell (D-025): the live finals press
 * Reset, so it must never show the user an error. Root cause was a keep-alive race between the
 * Next proxy and uvicorn ("socket hang up" -> 500); GETs are also retried once in the client.
 */
import { expect, test, type Page } from "@playwright/test";

/** Fails the test even if the offline notice only flickers (it hides again on the next answer). */
async function watchOfflineNotice(page: Page) {
  await page.addInitScript(() => {
    const w = window as unknown as { __sawOffline?: boolean };
    new MutationObserver(() => {
      if (document.querySelector('[data-testid="api-offline"]')) w.__sawOffline = true;
    }).observe(document, { childList: true, subtree: true });
  });
  return async () =>
    page.evaluate(() => !!(window as unknown as { __sawOffline?: boolean }).__sawOffline);
}

function watch(page: Page) {
  const failed: string[] = [];
  page.on("response", (r) => {
    const path = new URL(r.url()).pathname;
    if (path.startsWith("/api/") && r.status() >= 500) failed.push(`${r.status()} ${path}`);
  });
  return failed;
}

test("Reset demo three times after idle gaps: no 5xx, no offline notice, no error toast", async ({
  page,
}) => {
  test.setTimeout(120_000);
  const failed = watch(page);
  const sawOffline = await watchOfflineNotice(page);
  await page.goto("/requests/new");
  await expect(page.getByTestId("sim-clock-day")).toBeVisible();

  for (let i = 0; i < 3; i++) {
    // Idle about as long as the proxy's 5 s socket pool, the window the race needed.
    await page.waitForTimeout(5_000);
    await page.getByTestId("reset-demo").click();
    await page.getByTestId("reset-demo-confirm").click();
    await expect(page.getByText(/Demo reset in/).first()).toBeVisible({ timeout: 30_000 });
    await expect(page.getByRole("dialog")).toBeHidden();
    await expect(page.getByTestId("sim-clock-day")).toContainText("Day 1");
  }
  await page.waitForTimeout(1_000);
  expect(await sawOffline()).toBe(false);
  await expect(page.getByText("Reset did not finish")).toHaveCount(0);
  expect(failed).toEqual([]);
});

test("one dropped clock read is retried silently", async ({ page }) => {
  let dropped = 0;
  const sawOffline = await watchOfflineNotice(page);
  await page.route("**/api/clock", async (route) => {
    if (route.request().method() === "GET" && dropped === 0) {
      dropped += 1;
      // What the Next proxy answers on "socket hang up": a 500 without a JSON body.
      await route.fulfill({
        status: 500,
        contentType: "text/plain",
        body: "Internal Server Error",
      });
      return;
    }
    await route.continue();
  });
  await page.goto("/requests/new");
  await expect(page.getByTestId("sim-clock-day")).toContainText("Day");
  await page.waitForTimeout(500);
  expect(dropped).toBe(1);
  expect(await sawOffline()).toBe(false);
});
