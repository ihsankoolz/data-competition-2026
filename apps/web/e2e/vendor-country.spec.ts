/**
 * D-020 #2: a vendor may be based anywhere. A long enum (ISO country codes with
 * `x-enum-labels`) renders as a searchable select showing English names. The
 * widened vendor schema is stubbed so the spec runs before the backend lands it.
 */
import { expect, test } from "@playwright/test";

import { openAs } from "./workflow-helpers";

const LABELS: Record<string, string> = {
  SG: "Singapore",
  MY: "Malaysia",
  ID: "Indonesia",
  VN: "Vietnam",
  TH: "Thailand",
  DE: "Germany",
  US: "United States",
  JP: "Japan",
  FR: "France",
  GB: "United Kingdom",
  CH: "Switzerland",
  KR: "South Korea",
  CN: "China",
  IN: "India",
  AU: "Australia",
  NL: "Netherlands",
  SE: "Sweden",
  IT: "Italy",
  ES: "Spain",
  BE: "Belgium",
  IE: "Ireland",
  DK: "Denmark",
  AT: "Austria",
  CA: "Canada",
};

test("vendor country is a searchable list of country names", async ({ page }) => {
  await page.route("**/api/forms/vendor*", async (route) => {
    const res = await route.fetch();
    const spec = (await res.json()) as {
      json_schema: { properties: Record<string, Record<string, unknown>> };
    };
    spec.json_schema.properties.Country = {
      ...spec.json_schema.properties.Country,
      enum: Object.keys(LABELS),
      "x-enum-labels": LABELS,
    };
    await route.fulfill({ response: res, json: spec });
  });

  await openAs(page, "amy", "/requests/new");
  await page.getByRole("radio", { name: "Vendor" }).click();
  const combo = page.getByTestId("Country-combobox");
  // Defaults to the operating country until the requestor picks another.
  await expect(combo).toHaveText("Singapore");
  await combo.click();
  await page.getByLabel("Search the list").fill("germ");
  await expect(page.getByRole("option")).toHaveCount(1);
  await page.getByRole("option", { name: "Germany" }).click();
  await expect(combo).toHaveText("Germany");
});
