/**
 * Theme variant screenshots (D-022 #5, D-023): A (sage, the fallback) and B (light with a dark
 * olive sidebar, the default). Not a test of behaviour: `make theme-shots` runs it with
 * THEME_SHOTS=1; `make e2e` skips it (see playwright.config.ts).
 *
 * Each variant is applied the way a presenter would preview it: the stored override in
 * localStorage (lib/theme.ts), set by an init script before the page loads. 1440x900 shots go
 * to apps/web/screenshots/themes/{a,b}/ (gitignored; Playwright wipes test-results).
 */
import path from "node:path";

import { expect, type Page, test } from "@playwright/test";

import { approveAs, submittedCustomer } from "./workflow-helpers";

const VARIANTS = ["a", "b"] as const;
const OUT = path.join(__dirname, "..", "screenshots", "themes");

/** Load `url` as `user`. Init scripts run in order on every load, so the last user set wins. */
async function open(page: Page, user: string, url: string) {
  await page.addInitScript((u) => window.localStorage.setItem("lives-mdm.acting-user", u), user);
  await page.goto(url);
}

async function shot(page: Page, variant: string, name: string) {
  await page.mouse.move(0, 899);
  await page.evaluate(() => document.fonts.ready);
  await page.waitForTimeout(400);
  await page.screenshot({ path: path.join(OUT, variant, `${name}.png`) });
}

for (const variant of VARIANTS) {
  test(`theme ${variant.toUpperCase()}: form, status, regional and ops`, async ({
    page,
    request,
  }) => {
    test.setTimeout(120_000);
    // The preview switch must not cause hydration warnings or any other console error.
    const errors: string[] = [];
    page.on("console", (m) => m.type() === "error" && errors.push(m.text()));
    page.on("pageerror", (e) => errors.push(e.message));
    await page.addInitScript((v) => {
      window.localStorage.setItem("lives-mdm.theme-variant", v);
    }, variant);

    // 1. New-request form with the duplicate panel (DEMO-01: Marcus, QTG Vietnam).
    await open(page, "marcus", "/requests/new");
    await expect(page.locator("html")).toHaveAttribute("data-variant", variant);
    await expect(page.locator("#ctx-country")).toHaveText(/Vietnam/);
    await page.getByLabel("Legal name").fill("Benh vien Cho Ray");
    await page.getByLabel("Tax ID").fill("0301234567");
    const panel = page.getByTestId("dup-panel");
    await expect(panel.getByTestId("verdict")).toHaveAttribute("data-verdict", "likely", {
      timeout: 20_000,
    });
    await page.getByLabel("Legal name").scrollIntoViewIfNeeded();
    await shot(page, variant, "form-dup");

    // 2. Status page: three approvers in parallel, one approved, the history beside it.
    const detail = await submittedCustomer(request, `Theme ${variant.toUpperCase()} Clinic Pte Ltd`);
    await approveAs(request, detail, "daniel");
    await open(page, "amy", `/requests/${detail.req_id}`);
    await expect(page.getByTestId("audit-entry").first()).toBeVisible();
    await expect(page.getByTestId("task").first()).toBeVisible();
    await shot(page, variant, "status");

    // 3. Regional view, scrolled to the heatmap and the revenue bridge.
    await open(page, "daniel", "/regional");
    await expect(page.getByTestId("heat-cell")).toHaveCount(15);
    await expect(page.getByTestId("bridge-chart")).toBeVisible();
    await page.evaluate(() => {
      const h = document.getElementById("heatmap-title");
      if (h) window.scrollBy(0, h.getBoundingClientRect().top - 88);
    });
    await shot(page, variant, "regional");

    // 4. Ops impact card.
    await open(page, "daniel", "/ops");
    await expect(page.getByTestId("ops-card")).toBeVisible();
    await expect(page.getByTestId("ops-dupes-value")).toHaveText(/\d+/);
    await shot(page, variant, "ops");
    expect(errors).toEqual([]);
  });
}
