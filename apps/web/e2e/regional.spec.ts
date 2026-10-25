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
  // Read the counts from the sentence, then wait for the list to match it:
  // count() does not wait, so counting rows first races the render.
  const lost = page.getByTestId("lost-customers");
  await expect(page.getByTestId("lost-count")).toContainText(/\d+ alerts, of which \d+/);
  const counts = (await page.getByTestId("lost-count").textContent())?.match(
    /(\d+) alerts, of which (\d+)/,
  );
  const before = Number(counts?.[1]);
  const markers = Number(counts?.[2]);
  expect(markers).toBeGreaterThan(0);
  await expect(lost.getByTestId("lost-row")).toHaveCount(before);
  await expect(lost.getByTestId("duplicate-marker")).toHaveCount(markers);
  const customersBefore = await page.getByTestId("kpi-customers-value").textContent();
  const lostNote = page.getByTestId("moving-lost-note");
  await expect(lostNote).toHaveText("false alarms from old or copied records disappear");
  // Before merge cross-sell is meant to be low; the after-merge figure sits beside it.
  await expect(page.getByTestId("cross-sell-note")).toHaveText(
    "Before the golden record, you can't see who your cross-sell customers are.",
  );
  await expect(page.getByTestId("kpi-cross-sell-after")).toHaveText(/\d+%/);
  await expect(page.getByTestId("kpi-cross-sell-after")).not.toHaveText(
    (await page.getByTestId("kpi-cross-sell-value").textContent()) ?? "",
  );
  // Account lists (PRD S1) only make sense once duplicates are linked.
  await expect(page.getByTestId("account-lists-before")).toContainText("Merge duplicates");
  await expect(page.getByTestId("drop-off-list")).toHaveCount(0);

  // After merge: fewer alerts, none of them duplicates, fewer customers.
  await page.getByTestId("view-after").click();
  await expect(lost.getByTestId("duplicate-marker")).toHaveCount(0);
  await expect(page.getByTestId("lost-count")).not.toContainText(`${before} alerts`);
  const after = Number(
    (await page.getByTestId("lost-count").textContent())?.match(/(\d+) alerts/)?.[1],
  );
  expect(after).toBeLessThan(before);
  await expect(lost.getByTestId("lost-row")).toHaveCount(after);
  await expect(page.getByTestId("kpi-customers-value")).not.toHaveText(customersBefore ?? "");
  // The strip's caption says how the count moved, and its numbers add up to the arrow.
  await expect(lostNote).toHaveText(/^\d+ false alarms gone, \d+ newly caught$/);
  const [gone, caught] = ((await lostNote.textContent()) ?? "").match(/\d+/g)!.map(Number);
  expect(before - gone + caught).toBe(after);
  await expect(lostNote.getByRole("button", { name: "What is Newly caught?" })).toBeVisible();
  // After merge: both account lists show real accounts with a US$ value.
  for (const list of ["drop-off-list", "whitespace-list"]) {
    const rows = page.getByTestId(list).getByTestId("account-row");
    await expect(rows.first()).toBeVisible();
    await expect(rows.first()).toContainText("US$");
  }
  // Drop-off is year over year; whitespace rows on under 10 similar customers are marked and
  // left out of the total (D-022 #4).
  await expect(page.getByTestId("drop-off-list").getByTestId("account-row").first()).toContainText(
    "same quarter last year",
  );
  await expect(page.getByTestId("drop-off-list-total")).toContainText("same 3 months last year");
  // Confident rows come first, so the top 10 here has no low-confidence row; the total says
  // how many are listed after them and left out (the marker itself: see the next test).
  await expect(page.getByTestId("whitespace-list").getByRole("heading")).toContainText(
    "Cross-sell gaps",
  );
  await expect(
    page.getByTestId("whitespace-list").getByTestId("account-row").first(),
  ).toContainText("typically spend");
  await expect(page.getByTestId("whitespace-list-total")).toContainText(
    /\d+ low-confidence rows? listed after them/,
  );
  await expect(page.getByTestId("whitespace-list-total")).toContainText(
    /Total excludes the \d+ low-confidence rows?/,
  );
  await expect(page.getByTestId("account-lists-before")).toHaveCount(0);

  // The country filter narrows the strip and the heatmap.
  await page.getByTestId("country-VN").click();
  await expect(page.getByTestId("merge-headline")).toContainText("in Vietnam");
  // Nothing newly caught in Vietnam: only the false alarms, no tooltip.
  await expect(lostNote).toHaveText(/^\d+ false alarms gone$/);
  await expect(lostNote.getByRole("button")).toHaveCount(0);
  await page.getByTestId("view-before").click();
  await expect(lostNote).toHaveText("false alarms from old or copied records disappear");
  await expect(page.getByTestId("heat-cell")).toHaveCount(3);

  // POs, enquiries, purchase requests and MDM requests stay separate; MDM has no value.
  await expect(page.getByTestId("panel-mdm_request")).toContainText("never counted as demand");
  await expect(page.getByTestId("actions").locator("li")).not.toHaveCount(0);

  expect(errors).toEqual([]);
});

test("cross-sell gaps: a low-confidence row is marked and greyed", async ({ page }) => {
  const errors = watchConsole(page);
  const isAfter = (u: URL) =>
    u.pathname.endsWith("/analytics/regional") && u.searchParams.get("view") === "after";
  await page.route(isAfter, async (route) => {
    const res = await route.fetch();
    const body = (await res.json()) as {
      cross_sell_whitespace: { low_confidence: boolean; comparable_customers: number }[];
    };
    const last = body.cross_sell_whitespace.at(-1);
    if (last) {
      last.low_confidence = true;
      last.comparable_customers = 4;
    }
    await route.fulfill({ response: res, json: body });
  });
  await openAs(page, "daniel", "/regional");
  await page.getByTestId("view-after").click();
  const list = page.getByTestId("whitespace-list");
  await expect(list.getByTestId("low-confidence-marker")).toHaveCount(1);
  await expect(list.getByTestId("low-confidence-marker")).toHaveText(
    "Low confidence (fewer than 10 similar customers)",
  );
  await expect(list.getByTestId("account-row").last()).toContainText("Low confidence");
  expect(errors).toEqual([]);
});

test("forecast: switching to today's spreadsheet data changes the scores", async ({ page }) => {
  const errors = watchConsole(page);
  await openAs(page, "daniel", "/regional");
  const panel = page.getByTestId("forecast-panel");
  await expect(panel.getByTestId("data-headline")).toContainText("Equipment (Product B)");

  // Real backtest data: five country rows, the long caption collapsed behind "More".
  await expect(panel.getByTestId("bias-row")).toHaveCount(5);
  await expect(panel.getByTestId("bias-note-more")).toHaveText("More");
  // The technical setup sits behind an expander.
  await expect(panel.getByTestId("forecast-setup")).not.toHaveAttribute("open");

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
  const assumptions = card.getByTestId("assumptions");
  await expect(assumptions).toContainText("The brief");
  await expect(assumptions).toContainText("Our past request history");
  // Judges never see file names or decision numbers.
  await expect(card).not.toContainText(".csv");
  await expect(card).not.toContainText(/\bD-0\d\d\b/);
  // Amy's long explanation starts collapsed.
  await expect(card.getByTestId("amy-explanation-more")).toHaveText("More");
  expect(errors).toEqual([]);
});
