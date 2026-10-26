/**
 * Session 13: the forecast panel shows the equipment plan built from purchase requests (one
 * plain line) and the "Next 3 months plan" table, with Vietnam's growth adjustment in its own
 * labelled column (demo scenario, D-020 fast-growing).
 */
import { expect, type Page, test } from "@playwright/test";

import { openAs } from "./workflow-helpers";

function watchConsole(page: Page): string[] {
  const errors: string[] = [];
  page.on("console", (m) => {
    if (m.type() === "error") errors.push(m.text());
  });
  page.on("pageerror", (e) => errors.push(e.message));
  return errors;
}

test("forecast: next 3 months plan with the pipeline line and a separate VN adjustment", async ({
  page,
}) => {
  const errors = watchConsole(page);
  await openAs(page, "daniel", "/regional");
  const panel = page.getByTestId("forecast-panel");
  const block = panel.getByTestId("plan-block");
  await block.scrollIntoViewIfNeeded();

  // The plain line: the requests-based equipment plan against the averages, with its caveat.
  const line = block.getByTestId("pipeline-note");
  await expect(line).toContainText("Equipment (Product B), whole region");
  await expect(line).toContainText("a pilot must measure the conversion rate on real data");

  // The table: 5 countries x 3 products.
  const table = block.getByTestId("plan-table");
  await expect(table).toBeVisible();
  await expect(table.locator("tbody tr")).toHaveCount(15);
  await expect(table).toContainText("Growth adjustment (separate)");
  await expect(table).toContainText("From requests (equipment)");

  // Only Vietnam carries the adjustment, labelled as its own number with the measured gap.
  await expect(table.getByTestId("plan-adjustment")).toHaveCount(3);
  await expect(block.getByTestId("plan-row-VN-A").getByTestId("plan-adjustment")).toContainText(
    /^\+[\d,]+ \(Excel \d+% low\)$/,
  );
  await expect(block.getByTestId("plan-row-SG-A")).not.toContainText("low");
  await expect(block.getByTestId("plan-adjustment-note")).toContainText(
    /From the backtest: the Excel average planned Vietnam \d+% low/,
  );
  // Equipment rows carry a requests-based plan; test kits do not.
  await expect(block.getByTestId("plan-row-VN-B").locator("td").nth(3)).not.toHaveText("-");
  await expect(block.getByTestId("plan-row-VN-A").locator("td").nth(3)).toHaveText("-");

  // The flat market has no fast-growing country, so no adjustment is shown.
  await panel.getByTestId("scenario-flat_noisy").click();
  await expect(table.getByTestId("plan-adjustment")).toHaveCount(0);
  await expect(block.getByTestId("plan-adjustment-note")).toContainText("No market");
  expect(errors).toEqual([]);
});
