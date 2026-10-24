/**
 * D-022 #3: the heatmap's growth is the 12-month measure (`growth_12m_pct`), Product B carries
 * the "Lumpy" note, and the NRR / bridge captions say "last 3 months vs the 3 before" so the
 * two periods cannot be confused. The cross-sell tile reads "0% → 29%" on one line (D-021).
 */
import { expect, test } from "@playwright/test";

import { openAs } from "./workflow-helpers";

test("heatmap shows 12-month growth, never the 3-month change", async ({ page }) => {
  // Give every cell a recognisable 12-month figure and an absurd 3-month one.
  await page.route("**/api/analytics/regional**", async (route) => {
    const res = await route.fetch();
    const body = (await res.json()) as {
      heatmap: { growth_pct: number | null; growth_12m_pct: number | null }[];
    };
    for (const cell of body.heatmap) {
      cell.growth_12m_pct = 12.3;
      cell.growth_pct = -99;
    }
    await route.fulfill({ response: res, json: body });
  });
  await openAs(page, "daniel", "/regional");

  const growth = page.getByTestId("heat-growth");
  await expect(growth).toHaveCount(15);
  for (const text of await growth.allTextContents()) expect(text).toBe("+12.3%");
  await expect(page.getByTestId("heatmap")).not.toContainText("-99.0%");
  await expect(page.getByTestId("heat-growth-caption")).toContainText(/growth \(12 months\)/i);
  await expect(page.getByTestId("heat-growth-caption")).toContainText(
    "last 12 months vs the 12 before",
  );

  // Product B, and only Product B, is marked lumpy; the note explains it.
  await expect(page.getByTestId("lumpy-marker")).toHaveCount(5);
  for (const cell of await page.locator('[data-testid="heat-cell"]:has([data-testid="lumpy-marker"])').all()) {
    await expect(cell).toHaveAttribute("data-cell", /-B$/);
  }
  await expect(page.getByTestId("lumpy-note")).toContainText(
    "Lumpy: plan from the enquiry pipeline",
  );
});

test("NRR and the bridge say 3 months; cross-sell reads before → after on one line", async ({
  page,
}) => {
  await openAs(page, "daniel", "/regional");
  await expect(page.getByTestId("kpi-nrr")).toContainText("last 3 months vs the 3 before");
  await expect(page.getByText("Revenue bridge, last 3 months vs the 3 before")).toBeVisible();

  const tile = page.getByTestId("kpi-cross-sell");
  await expect(tile).toContainText("Customers buying 2+ product lines (before vs after merge)");
  const line = tile.locator("dd").first();
  await expect(line).toHaveText(/^\d+%\s*→\s*\d+%$/);
  // One line: the before and after numbers sit on the same baseline.
  const before = await page.getByTestId("kpi-cross-sell-value").boundingBox();
  const after = await page.getByTestId("kpi-cross-sell-after").boundingBox();
  expect(before && after).toBeTruthy();
  expect(Math.abs(before!.y - after!.y)).toBeLessThan(4);
  // Same figures in the after-merge view.
  const text = await line.textContent();
  await page.getByTestId("view-after").click();
  await expect(line).toHaveText(text ?? "");
});
