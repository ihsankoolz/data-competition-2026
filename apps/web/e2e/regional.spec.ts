/**
 * Storyline step 6 (PRD M8, M10): the regional view. The before/after merge
 * toggle removes the 'lost customers' that were really duplicates; the forecast
 * panel's clean/dirty switch changes the scores; the ops card says "modelled".
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

test("merge toggle removes duplicate 'lost customers' and changes the numbers", async ({
  page,
}) => {
  const errors = watchConsole(page);
  await openAs(page, "daniel", "/regional");

  await expect(page.getByTestId("period")).toContainText("last 12 full months");
  await expect(page.getByTestId("heat-cell")).toHaveCount(15);
  await expect(page.getByTestId("merge-headline")).toContainText(
    /\d+ of \d+ .lost customer. alerts in the region were really duplicates/,
  );

  // Before merge (the default): duplicate alerts are marked.
  const lost = page.getByTestId("lost-customers");
  const before = await lost.getByTestId("lost-row").count();
  const markers = await lost.getByTestId("duplicate-marker").count();
  expect(markers).toBeGreaterThan(0);
  await expect(page.getByTestId("lost-count")).toContainText(
    `${before} alerts, of which ${markers}`,
  );
  const customersBefore = await page.getByTestId("kpi-customers-value").textContent();

  // After merge: fewer alerts, none of them duplicates, fewer customers.
  await page.getByTestId("view-after").click();
  await expect(lost.getByTestId("duplicate-marker")).toHaveCount(0);
  const after = await lost.getByTestId("lost-row").count();
  expect(after).toBeLessThan(before);
  await expect(page.getByTestId("lost-count")).toContainText(`${after} alerts`);
  await expect(page.getByTestId("kpi-customers-value")).not.toHaveText(customersBefore ?? "");

  // The country filter narrows the strip and the heatmap.
  await page.getByTestId("country-VN").click();
  await expect(page.getByTestId("merge-headline")).toContainText("in Vietnam");
  await expect(page.getByTestId("heat-cell")).toHaveCount(3);

  // POs, enquiries, purchase requests and MDM requests stay separate; MDM has no value.
  await expect(page.getByTestId("panel-mdm_request")).toContainText("never counted as demand");
  await expect(page.getByTestId("actions").locator("li")).not.toHaveCount(0);

  expect(errors).toEqual([]);
});

test("forecast: switching to today's spreadsheet data changes the scores", async ({ page }) => {
  const errors = watchConsole(page);
  await openAs(page, "daniel", "/regional");
  const panel = page.getByTestId("forecast-panel");
  await expect(panel.getByTestId("data-headline")).toContainText("Equipment (Product B)");

  const productB = panel.getByTestId("product-row-B");
  await expect(productB).toBeVisible();
  const clean = await productB.textContent();
  await panel.getByTestId("data-dirty").click();
  await expect(productB).not.toHaveText(clean ?? "");
  await expect(panel.getByTestId("honest-note")).toContainText("spreadsheet");

  await panel.getByTestId("scenario-flat_noisy").click();
  await expect(panel.getByTestId("honest-note")).toContainText("flat");
  expect(errors).toEqual([]);
});

test("forecast: bias by country renders when the backtest provides it", async ({ page }) => {
  await page.route("**/api/analytics/forecast", async (route) => {
    const res = await route.fetch();
    const body = (await res.json()) as {
      runs: { bias_by_country: unknown[]; bias_note: string | null }[];
    };
    const score = (method: string, bias: number) => ({
      method,
      label: method,
      wape_pct: 10,
      bias_pct: bias,
    });
    // Shaped like the backtest's payload: 5 country rows (product null) first, then A/B/C each.
    const growth: Record<string, number> = { SG: 2.1, MY: 18.4, ID: 9.7, VN: 45.0, TH: -3.2 };
    const countryRows = Object.entries(growth).map(([country, g]) => ({
      country,
      product: null,
      growth_pct: g,
      scores:
        country === "VN"
          ? [score("excel_6m", -13.0), score("combination", -17.0)]
          : [score("excel_6m", -1.0), score("combination", 0.5)],
    }));
    const productRows = Object.keys(growth).flatMap((country) =>
      ["A", "B", "C"].map((product) => ({
        country,
        product,
        growth_pct: 5.0,
        scores: [score("excel_6m", -2.0), score("combination", -1.0)],
      })),
    );
    for (const run of body.runs) {
      run.bias_by_country = [...countryRows, ...productRows];
      run.bias_note =
        "Stub: in Vietnam, the fastest-growing market, the Excel average planned 13% too low. " +
        "Our method planned 17% too low there, so neither fixes it. " +
        "(Caveat: one synthetic seed; growth measured in units.)";
    }
    await route.fulfill({ response: res, json: body });
  });
  await openAs(page, "daniel", "/regional");
  const block = page.getByTestId("bias-block");
  const note = block.getByTestId("bias-note");
  // Long caption starts collapsed at its first sentence.
  await expect(note).toContainText("planned 13% too low.");
  await expect(note).not.toContainText("neither fixes it");
  await note.getByTestId("bias-note-more").click();
  await expect(note).toContainText("neither fixes it");

  // Countries only by default; each product on request.
  await expect(block.getByTestId("bias-row")).toHaveCount(5);
  await expect(block.getByTestId("bias-table")).toContainText("Vietnam");
  await expect(block.getByTestId("bias-table")).toContainText("+45.0%");
  await expect(block.getByTestId("bias-table")).toContainText("-17.0%");
  await block.getByTestId("bias-by-product").click();
  await expect(block.getByTestId("bias-row")).toHaveCount(20);
});

test("ops impact card shows modelled cycle time and its assumptions", async ({ page }) => {
  const errors = watchConsole(page);
  await openAs(page, "daniel", "/ops");
  const card = page.getByTestId("ops-card");
  await expect(card.getByTestId("modelled-tag")).toHaveText("Modelled, not measured");
  await expect(card.getByTestId("ops-amy")).toContainText("18");
  await expect(card.getByTestId("ops-amy-after")).toHaveText(/~\d+/);
  await expect(card.getByTestId("ops-ftr")).toContainText("%");
  await expect(card.getByTestId("ops-dupes-value")).toHaveText(/\d+/);
  await expect(card.getByTestId("assumptions").locator("tbody tr")).not.toHaveCount(0);
  await expect(card.getByTestId("assumptions")).toContainText("The case brief");
  expect(errors).toEqual([]);
});
