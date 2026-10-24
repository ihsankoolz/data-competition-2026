/**
 * Stretch S2 (D-023 #5/#6, D-024 #5): the Southeast Asia map on /regional. Five countries
 * coloured and labelled by 12-month growth; clicking a country filters the page and clicking it
 * again clears the filter; Singapore is a dot; ECharts loads on /regional and nowhere else.
 */
import { expect, type Locator, type Page, test } from "@playwright/test";

import { openAs } from "./workflow-helpers";

/** A string that only ECharts' core contains (its warning for a second init on one element). */
const ECHARTS_MARK = "There is a chart instance already initialized on the dom";

function watchConsole(page: Page): string[] {
  const errors: string[] = [];
  page.on("console", (m) => {
    if (m.type() === "error") errors.push(m.text());
  });
  page.on("pageerror", (e) => errors.push(e.message));
  return errors;
}

/** Collects every script the page downloads that contains ECharts. */
function watchEcharts(page: Page): string[] {
  const hits: string[] = [];
  page.on("response", async (r) => {
    if (r.request().resourceType() !== "script") return;
    const body = await r.text().catch(() => "");
    if (body.includes(ECHARTS_MARK)) hits.push(r.url());
  });
  return hits;
}

async function openMap(page: Page): Promise<Locator> {
  await openAs(page, "daniel", "/regional");
  const map = page.getByTestId("sea-map");
  await expect(map).toHaveAttribute("data-status", "ready", { timeout: 30_000 });
  await expect(map).toHaveAttribute("data-drawn", "true");
  await expect(page.getByTestId("heat-cell")).toHaveCount(15);
  return map;
}

/** Centre-left of a two-line label: the point the label's anchor sits next to. */
async function labelBox(map: Locator, name: string) {
  const top = await map.getByText(name, { exact: true }).boundingBox();
  expect(top).toBeTruthy();
  return top!;
}

test("the map shows all five countries with their 12-month growth", async ({ page }) => {
  const errors = watchConsole(page);
  const map = await openMap(page);

  const res = await page.request.get("/api/analytics/regional?view=after", {
    headers: { "X-Acting-User": "daniel" },
  });
  const growth = (
    (await res.json()) as {
      country_growth: { country: string; growth_12m_pct: number | null }[];
    }
  ).country_growth;
  expect(growth.map((g) => g.country)).toEqual(["SG", "MY", "ID", "VN", "TH"]);
  const names: Record<string, string> = {
    SG: "Singapore",
    MY: "Malaysia",
    ID: "Indonesia",
    VN: "Vietnam",
    TH: "Thailand",
  };
  for (const g of growth) {
    const pct = `${g.growth_12m_pct! > 0 ? "+" : ""}${g.growth_12m_pct!.toFixed(1)}%`;
    await expect(map.getByText(names[g.country], { exact: true })).toBeVisible();
    await expect(map.getByText(pct, { exact: true })).toBeVisible();
    // The text alternative names every country with its growth.
    await expect(map).toHaveAttribute("aria-label", new RegExp(`${names[g.country]} \\${pct}`));
  }
  await expect(map).toHaveAttribute("role", "img");
  await expect(map).toHaveAttribute("aria-label", /Vietnam \+45\.9%/);
  await expect(
    page.getByText("Growth in confirmed-PO value, last 12 full months vs the 12 before."),
  ).toBeVisible();
  expect(errors).toEqual([]);
});

test("clicking Vietnam filters the page; clicking it again shows all five", async ({ page }) => {
  const errors = watchConsole(page);
  const map = await openMap(page);

  await map.getByText("Vietnam", { exact: true }).click();
  await expect(page.getByTestId("country-VN")).toHaveAttribute("data-state", "on");
  await expect(page.getByTestId("heat-cell")).toHaveCount(3);
  for (const cell of await page.getByTestId("heat-cell").all()) {
    await expect(cell).toHaveAttribute("data-cell", /^VN-/);
  }
  await expect(map).toHaveAttribute("data-selected", "VN");
  await expect(map).toHaveAttribute("aria-label", /Showing Vietnam only\./);

  // Click the land itself this time (just west of the label, inside Vietnam): clears it.
  const label = await labelBox(map, "Vietnam");
  await page.mouse.click(label.x - 18, label.y + label.height);
  await expect(page.getByTestId("country-VN")).toHaveAttribute("data-state", "off");
  await expect(map).toHaveAttribute("data-selected", "ALL");
  await expect(page.getByTestId("heat-cell")).toHaveCount(15);

  // The toggle group drives the map too.
  await page.getByTestId("country-TH").click();
  await expect(map).toHaveAttribute("data-selected", "TH");
  await expect(page.getByTestId("heat-cell")).toHaveCount(3);
  expect(errors).toEqual([]);
});

test("the Singapore dot filters to Singapore", async ({ page }) => {
  const errors = watchConsole(page);
  const map = await openMap(page);

  // The dot sits left of its label: label distance 6 px + radius 6 px.
  const label = await labelBox(map, "Singapore");
  const dot = { x: label.x - 12, y: label.y + label.height };
  // Hovering the dot shows its tooltip (ECharts needs a fresh move to pick the target).
  await expect(async () => {
    await page.mouse.move(dot.x + 2, dot.y);
    await page.mouse.move(dot.x, dot.y);
    await expect(map).toContainText("Click to show only Singapore.", { timeout: 1_000 });
  }).toPass();
  await page.mouse.click(dot.x, dot.y);
  await expect(page.getByTestId("country-SG")).toHaveAttribute("data-state", "on");
  await expect(map).toHaveAttribute("data-selected", "SG");
  await expect(page.getByTestId("heat-cell")).toHaveCount(3);
  for (const cell of await page.getByTestId("heat-cell").all()) {
    await expect(cell).toHaveAttribute("data-cell", /^SG-/);
  }
  expect(errors).toEqual([]);
});

test("ECharts loads on the regional page and nowhere else", async ({ page }) => {
  const errors = watchConsole(page);
  const echarts = watchEcharts(page);

  await openAs(page, "daniel", "/inbox");
  await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
  await page.waitForLoadState("networkidle");
  expect(echarts).toEqual([]);

  // Positive control: the same check does see it on /regional, in its own chunk.
  await page.goto("/regional");
  await expect(page.getByTestId("sea-map")).toHaveAttribute("data-status", "ready", {
    timeout: 30_000,
  });
  await expect.poll(() => echarts.length).toBeGreaterThan(0);
  expect(errors).toEqual([]);
});

test("if the map shapes fail to load, a plain message replaces the map", async ({ page }) => {
  const errors = watchConsole(page);
  await page.route("**/geo/sea-5.geojson", (r) => r.fulfill({ status: 404, body: "" }));
  await openAs(page, "daniel", "/regional");
  await expect(page.getByTestId("sea-map-error")).toHaveText(
    "The map could not be loaded. Use the country buttons above to filter.",
  );
  await expect(page.getByTestId("heat-cell")).toHaveCount(15);
  // The browser itself logs the failed request; nothing else may.
  expect(errors.filter((e) => !/Failed to load resource.*404/.test(e))).toEqual([]);
});
