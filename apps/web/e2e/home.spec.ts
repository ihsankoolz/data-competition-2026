/**
 * The "Start here" home page at /: the pitch, the five steps, headline numbers that come from
 * the API, and one link per demo journey that switches to the right person first.
 */
import { expect, test } from "@playwright/test";

import { days, usdShort } from "../lib/analytics";
import { openAs } from "./workflow-helpers";

type Ops = { amy_before_bd: number; amy_after_bd: number };
type Merge = {
  customers_before: number;
  customers_after: number;
  lost_before: number;
  lost_after: number;
  lost_that_were_duplicates: number;
};
type Regional = {
  period: string;
  heatmap: { value_usd: number }[];
  lost_alert_change: { new_after_merge: number };
};

async function getJson<T>(page: import("@playwright/test").Page, path: string): Promise<T> {
  const res = await page.request.get(`/api${path}`, { headers: { "X-Acting-User": "amy" } });
  expect(res.ok(), `GET ${path}`).toBe(true);
  return (await res.json()) as T;
}

test("/ shows Start here (no redirect) with the numbers the API returns", async ({ page }) => {
  await openAs(page, "amy", "/");
  await expect(page).toHaveURL(/\/$/);
  await expect(page.getByRole("heading", { level: 1, name: "Start here" })).toBeVisible();
  await expect(page.getByTestId("home-pitch")).toContainText("SAP Business One");
  await expect(page.getByTestId("home-pipeline").locator("h3")).toHaveText([
    "Email",
    "Read by AI",
    "Golden record",
    "Approvals",
    "In SAP",
  ]);

  const ops = await getJson<Ops>(page, "/analytics/ops-impact");
  const merge = await getJson<Merge>(page, "/analytics/merge-impact");
  const regional = await getJson<Regional>(page, "/analytics/regional?view=after");

  await expect(page.getByTestId("home-stat-amy-before")).toHaveText(days(ops.amy_before_bd));
  await expect(page.getByTestId("home-stat-amy-after")).toHaveText(
    `~${days(Math.round(ops.amy_after_bd))}`,
  );
  await expect(page.getByTestId("home-stat-customers-before")).toHaveText(
    merge.customers_before.toLocaleString("en-US"),
  );
  await expect(page.getByTestId("home-stat-customers-after")).toHaveText(
    merge.customers_after.toLocaleString("en-US"),
  );
  await expect(page.getByTestId("home-stat-lost-before")).toHaveText(String(merge.lost_before));
  await expect(page.getByTestId("home-stat-lost-after")).toHaveText(String(merge.lost_after));
  await expect(page.getByTestId("home-stat-lost")).toContainText(
    `${merge.lost_that_were_duplicates} were false alarms`,
  );
  if (regional.lost_alert_change.new_after_merge > 0)
    await expect(page.getByTestId("home-stat-lost")).toContainText(
      `${regional.lost_alert_change.new_after_merge} more`,
    );
  const total = regional.heatmap.reduce((s, c) => s + c.value_usd, 0);
  await expect(page.getByTestId("home-stat-sales-after")).toHaveText(usdShort(total));
  await expect(page.getByTestId("home-stat-sales")).toContainText(regional.period);
});

test("each journey link switches person and opens its screen", async ({ page }) => {
  const journeys: [string, RegExp, string | null][] = [
    ["marcus", /\/inbox$/, "Marcus"],
    ["amy", /\/inbox$/, "Amy"],
    ["weijie", /\/inbox$/, "Wei Jie"],
    ["priya", /\/publish$/, "Priya"],
    ["regional", /\/regional$/, null],
  ];
  // Start as someone none of the journeys switches to, so every switch is visible.
  await openAs(page, "daniel", "/");
  let actingAs = "Daniel";
  for (const [id, url, person] of journeys) {
    await page.goto("/");
    const journey = page.getByTestId(`journey-${id}`);
    await expect(journey.getByTestId("journey-person")).toHaveText(person ?? "Anyone");
    await journey.getByTestId(`journey-${id}-link`).click();
    await expect(page).toHaveURL(url);
    // The regional view is for anyone: its link keeps whoever was acting.
    actingAs = person ?? actingAs;
    await expect(page.getByTestId("persona-switcher")).toContainText(actingAs);
  }

  // The inbox journeys name an email that is really there.
  await page.goto("/");
  await page.getByTestId("journey-marcus-link").click();
  await page.getByLabel("Search emails").fill("Cho Ray");
  await expect(page.getByTestId("inbox-DEMO-01")).toContainText("New customer - Benh vien Cho Ray");
});

test("the sidebar starts with Start here, then the existing screens in the same order", async ({
  page,
}) => {
  await openAs(page, "amy", "/");
  const links = page.getByRole("navigation", { name: "Screens" }).getByRole("link");
  await expect(links).toHaveText([
    "Start here",
    "Messy inbox",
    "New request",
    "My requests",
    "Approvals",
    "Publish to SAP",
    "Clean-up queue",
    "Regional view",
    "Ops impact",
    "Admin & config",
  ]);
  const nav = page.getByRole("navigation", { name: "Screens" });
  await expect(nav.getByRole("heading")).toHaveText(["Request flow", "Results", "Setup"]);
  // "/" is highlighted only on the home page.
  await expect(nav.getByRole("link", { name: "Start here" })).toHaveAttribute(
    "aria-current",
    "page",
  );
  await nav.getByRole("link", { name: "Messy inbox" }).click();
  await expect(page).toHaveURL(/\/inbox$/);
  await expect(nav.getByRole("link", { name: "Messy inbox" })).toHaveAttribute(
    "aria-current",
    "page",
  );
  await expect(nav.getByRole("link", { name: "Start here" })).not.toHaveAttribute("aria-current");
});
