/**
 * Storyline step 1 in replay mode (no network LLM): open Marcus's email, read
 * it with AI, see the category and each detail's source words highlighted,
 * then create a pre-filled request from it. The injection email is flagged.
 */
import { expect, test } from "@playwright/test";

import { openAs } from "./workflow-helpers";

test("read with AI shows category, highlighted quotes and creates a request", async ({ page }) => {
  await openAs(page, "marcus", "/inbox");
  await page.getByLabel("Search emails").fill("Cho Ray");
  await page.getByTestId("inbox-DEMO-01").click();

  const pane = page.getByTestId("email-pane");
  await expect(pane).toContainText("New customer - Benh vien Cho Ray");
  await pane.getByTestId("read-with-ai").click();

  const reading = pane.getByTestId("ai-reading");
  await expect(reading.getByTestId("category-chip")).toHaveAttribute(
    "data-category",
    "mdm_request",
  );
  await expect(reading.getByTestId("confidence")).toContainText("% sure");
  await expect(reading.getByTestId("extracted-fields")).not.toBeEmpty();
  const highlights = pane.getByTestId("email-body").getByTestId("quote-highlight");
  await expect(highlights.first()).toBeVisible();
  await expect(pane.getByTestId("email-body")).toContainText("Benh vien Cho Ray");

  await reading.getByTestId("create-request").click();
  await expect(page.getByTestId("prefill-note")).toContainText("New customer - Benh vien Cho Ray");
  await expect(page.getByLabel("Legal name")).toHaveValue("Benh vien Cho Ray");
  // The ?email= hand-off is dropped from the address, so a reload cannot create a second draft.
  await expect(page).toHaveURL(/\/requests\/new$/);
  await page.reload();
  await expect(page.getByLabel("Legal name")).toHaveValue("");
  await expect(page.getByTestId("prefill-note")).toHaveCount(0);
});

test("an email that gives the AI orders is flagged for a person", async ({ page }) => {
  await openAs(page, "priya", "/inbox");
  await page.getByLabel("Search emails").fill("bank details update");
  await page.getByTestId("inbox-DEMO-06").click();
  const pane = page.getByTestId("email-pane");
  await pane.getByTestId("read-with-ai").click();
  await expect(pane.getByTestId("injection-warning")).toContainText("Possible hidden instructions");
  await expect(pane.getByTestId("needs-review")).toBeVisible();
});

test("sort all with AI fills in a type for every email", async ({ page }) => {
  await openAs(page, "priya", "/inbox");
  await expect(page.getByTestId("email-list").locator("li").first()).toBeVisible();
  await page.getByTestId("sort-all").click();
  await expect(page.getByTestId("sort-all")).toHaveText(/All emails sorted/, { timeout: 45_000 });
  const filter = page.getByTestId("category-filter");
  await filter.getByRole("radio", { name: /New record request/ }).click();
  await expect(page.getByTestId("inbox-DEMO-01")).toBeVisible();
  await expect(page.getByTestId("inbox-DEMO-03")).toHaveCount(0);
});

test("DEMO-07: the bank-details note sits under 'Details found', on screen without scrolling", async ({
  page,
}) => {
  await openAs(page, "weijie", "/inbox");
  await page.getByLabel("Search emails").fill("Precision");
  await page.getByTestId("inbox-DEMO-07").click();
  const pane = page.getByTestId("email-pane");
  await expect(pane).toContainText("New vendor - Precision Diagnostics Asia");
  await pane.getByTestId("read-with-ai").click();

  const reading = pane.getByTestId("ai-reading");
  const note = reading.getByTestId("bank-stripped");
  await expect(note).toHaveText(
    "Bank details in this email were removed before the AI read it. They are never sent to " +
      "the AI, and only Finance can see them.",
  );
  const heading = reading.getByRole("heading", { name: "Details found" });
  const firstField = reading.getByTestId("extracted-fields").locator("li").first();
  await expect(firstField).toBeVisible();

  // Inside the 1440x900 viewport, with the page not scrolled.
  expect(await page.evaluate(() => window.scrollY)).toBe(0);
  const viewport = page.viewportSize()!;
  const box = (await note.boundingBox())!;
  expect(box.y).toBeGreaterThanOrEqual(0);
  expect(box.y + box.height).toBeLessThanOrEqual(viewport.height);

  // Just below the heading and above the first extracted field.
  const h = (await heading.boundingBox())!;
  const f = (await firstField.boundingBox())!;
  expect(box.y).toBeGreaterThanOrEqual(h.y + h.height - 1);
  expect(box.y + box.height).toBeLessThanOrEqual(f.y + 1);
});
