/**
 * D-020 #2: a vendor may be based anywhere. The vendor form's Country is an
 * enum of all ISO codes with `x-enum-labels`, rendered as a searchable select
 * showing English names, with arrow-key navigation. Real backend schema.
 */
import { expect, test } from "@playwright/test";

import { openAs } from "./workflow-helpers";

test("vendor country is a searchable list of country names", async ({ page }) => {
  await openAs(page, "amy", "/requests/new");
  await page.getByRole("radio", { name: "Vendor" }).click();
  const combo = page.getByTestId("Country-combobox");
  // Defaults to the operating country until the requestor picks another.
  await expect(combo).toHaveText("Singapore");

  await combo.click();
  const search = page.getByLabel("Search the list");
  await search.fill("germ");
  await expect(page.getByRole("option")).toHaveCount(1);
  await page.getByRole("option", { name: "Germany" }).click();
  await expect(combo).toHaveText("Germany");

  // Keyboard: type, move down one, press Enter.
  await combo.click();
  await search.fill("united");
  await expect(page.getByRole("option").first()).toHaveAttribute("data-active", "true");
  await search.press("ArrowDown");
  await expect(search).toHaveAttribute(
    "aria-activedescendant",
    (await page.getByRole("option").nth(1).getAttribute("id")) ?? "",
  );
  await search.press("Enter");
  await expect(combo).toHaveText("United Kingdom");
});
