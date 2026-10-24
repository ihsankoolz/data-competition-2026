/**
 * Toast placement and lifetime (D-022 #5). Toasts sit bottom-left inside the sidebar column,
 * so they never cover the revenue bridge (/regional) or a request's history; they last about
 * 3 seconds and are cleared on page change, except the one that announces the change itself.
 *
 * Saves 1440x900 proof screenshots to apps/web/screenshots/toasts/ (gitignored; outside
 * test-results, which Playwright wipes).
 */
import path from "node:path";

import { expect, type Locator, type Page, test } from "@playwright/test";

import { openAs, submittedCustomer } from "./workflow-helpers";

const SHOTS = path.join(__dirname, "..", "screenshots", "toasts");

type Box = { x: number; y: number; width: number; height: number };

function overlaps(a: Box, b: Box): boolean {
  return a.x < b.x + b.width && b.x < a.x + a.width && a.y < b.y + b.height && b.y < a.y + a.height;
}

/** The front toast lies inside the sidebar column and clear of `target`. */
async function expectClear(page: Page, toastEl: Locator, target: Locator) {
  const toastBox = await toastEl.boundingBox();
  const targetBox = await target.boundingBox();
  const sidebar = await page.getByTestId("sidebar").boundingBox();
  expect(toastBox && targetBox && sidebar).toBeTruthy();
  expect(overlaps(toastBox!, targetBox!)).toBe(false);
  expect(toastBox!.x).toBeGreaterThanOrEqual(sidebar!.x);
  expect(toastBox!.x + toastBox!.width).toBeLessThanOrEqual(sidebar!.x + sidebar!.width);
}

/** "Reset demo" with the API call stubbed: a toast on any page without changing data. */
async function stubbedResetToast(page: Page) {
  await page.route("**/api/admin/reset-demo", (route) =>
    route.fulfill({
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
    }),
  );
  await page.getByTestId("reset-demo").click();
  await page.getByTestId("reset-demo-confirm").click();
  const toastEl = page.locator("[data-sonner-toast]").filter({ hasText: "Demo reset in 1.2" });
  await expect(toastEl).toBeVisible();
  return toastEl;
}

test("a toast never covers the revenue bridge, and goes after about 3 seconds", async ({
  page,
}) => {
  await openAs(page, "daniel", "/regional");
  const bridge = page.getByTestId("bridge-chart");
  await bridge.scrollIntoViewIfNeeded();
  // Put the bridge at the bottom of the screen, where a corner toast would sit.
  await page.evaluate(() => {
    const el = document.querySelector('[data-testid="bridge-chart"]');
    if (!el) return;
    const r = el.getBoundingClientRect();
    window.scrollBy(0, r.bottom - window.innerHeight + 8);
  });

  const toastEl = await stubbedResetToast(page);
  // Let the entry animation finish before measuring.
  await page.waitForTimeout(450);
  await expectClear(page, toastEl, bridge);
  await page.screenshot({ path: path.join(SHOTS, "regional.png") });

  // Still there shortly after, gone well before 5 seconds.
  await page.waitForTimeout(1_000);
  await expect(toastEl).toBeVisible();
  await expect(toastEl).toBeHidden({ timeout: 4_000 });
});

test("a toast never covers a request's history, and is cleared on page change", async ({
  page,
  request,
}) => {
  const detail = await submittedCustomer(request, "Toast Guard Clinic Pte Ltd");
  // Warm the page we navigate to, so the change is quicker than the toast's 3 seconds.
  await openAs(page, "amy", "/approvals");
  await page.goto(`/requests/${detail.req_id}`);
  const history = page.getByTestId("history");
  await expect(page.getByTestId("audit-entry").first()).toBeVisible();
  await history.scrollIntoViewIfNeeded();

  await page.getByTestId("act-as").first().click();
  const toastEl = page.locator("[data-sonner-toast]").filter({ hasText: "Now acting as" });
  await expect(toastEl).toBeVisible();
  await page.waitForTimeout(450);
  await expectClear(page, toastEl, history);
  await expectClear(page, toastEl, page.getByTestId("audit-timeline"));
  await page.screenshot({ path: path.join(SHOTS, "status.png") });

  // Change page with the toast still up: it is gone at once, not after its 3 seconds.
  const shownAt = Date.now();
  await page.getByRole("link", { name: "Approvals", exact: true }).click();
  await expect(page).toHaveURL(/\/approvals$/);
  await expect(toastEl).toBeHidden({ timeout: 1_000 });
  expect(Date.now() - shownAt).toBeLessThan(2_500);
});

test("'Request submitted' stays through the move to the status page", async ({ page }) => {
  await openAs(page, "amy", "/requests/new");
  await expect(page.getByLabel("Legal name")).toBeVisible();
  const n = (Date.now() % 90_000) + 10_000;
  await page.getByLabel("Legal name").fill(`Quillon Toast Medical ${n} Pte Ltd`);
  await page.getByLabel("Tax ID").fill(`2026${String(n).padStart(5, "0")}T`);
  await page.getByLabel("Billing address").fill("8 Kallang Way");
  await page.getByLabel("City").fill("Singapore");
  await page.getByLabel("Contact email").fill("accounts@quillon.example.com");
  await page.getByTestId("submit").click();
  await expect(page).toHaveURL(/\/requests\/REQ-/);
  await expect(page.getByText("Request submitted")).toBeVisible();
});
