/**
 * Session 13: the item form's duplicate check, against the real API and the 15 demo items.
 * Rules only, no AI: a near-copy of an existing kit is flagged Likely with reasons and pauses
 * submit; a DEMO-02-like malaria kit shows no match; nothing is ever linked without a person.
 */
import { expect, type Page, test } from "@playwright/test";

import { openAs } from "./workflow-helpers";

async function openItemForm(page: Page) {
  await openAs(page, "amy", "/requests/new");
  await page.getByRole("radio", { name: "Item", exact: true }).click();
  await expect(page.getByLabel("Item name")).toBeVisible();
}

function collectErrors(page: Page): string[] {
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));
  page.on("console", (m) => {
    if (m.type() === "error") errors.push(m.text());
  });
  return errors;
}

test("a near-copy of an existing kit is flagged Likely, with reasons, and submit waits", async ({
  page,
}) => {
  const errors = collectErrors(page);
  await openItemForm(page);
  const panel = page.getByTestId("item-dup-panel");
  await page.getByLabel("Item name").fill("Rapid Dengue NS1 Antigen Test Kit, 25 tests");

  await expect(panel.getByTestId("verdict")).toHaveAttribute("data-verdict", "likely");
  const top = panel.getByTestId("candidate").first();
  await expect(top).toContainText("Rapid Dengue NS1 Ag Test Kit");
  await expect(top).toContainText("A-DEN-NS1");
  await expect(top).toContainText("Likely the same");
  await expect(top.getByTestId("reasons")).toContainText("pack size");
  await expect(panel.getByTestId("link-A-DEN-NS1")).toBeVisible();
  await expect(panel.getByTestId("not-duplicate")).toHaveText("Not the same item — explain why");
  // The check only advises (rule 6): nothing is linked, and submit waits for a person.
  await expect(panel.getByTestId("linked")).toHaveCount(0);
  await expect(page.getByTestId("submit")).toBeDisabled();
  await expect(page.getByTestId("submit-hint")).toContainText("decide on the likely duplicate");
  expect(errors).toEqual([]);
});

test("a DEMO-02-like malaria kit shows no match", async ({ page }) => {
  const errors = collectErrors(page);
  await openItemForm(page);
  const panel = page.getByTestId("item-dup-panel");
  await page.getByLabel("Item name").fill("Malaria Pf/Pan Antigen Rapid Test Kit");

  await expect(panel.getByTestId("verdict")).toHaveAttribute("data-verdict", "none");
  await expect(panel.getByTestId("verdict")).toContainText("No existing item matched");
  await expect(panel.getByTestId("candidate")).toHaveCount(0);
  expect(errors).toEqual([]);
});

test("the same (synthetic) catalogue number is Likely even with a vague name", async ({ page }) => {
  await openItemForm(page);
  const panel = page.getByTestId("item-dup-panel");
  await page.getByLabel("Item name").fill("Antigen cassette");
  await page.getByLabel("Manufacturer catalogue no.").fill("REF 51-SCV2-25");

  await expect(panel.getByTestId("verdict")).toHaveAttribute("data-verdict", "likely");
  const top = panel.getByTestId("candidate").first();
  await expect(top).toContainText("A-COV-AG");
  await expect(top.getByTestId("reasons")).toContainText("synthetic");
});
