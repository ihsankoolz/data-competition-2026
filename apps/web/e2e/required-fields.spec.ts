/**
 * Session 13: required-field toggles in Admin & config. Real backend, no stubs.
 *
 * Priya makes City required for Singapore customers. Amy's new customer form shows it as
 * required. Locked fields are greyed with a reason. Reset demo puts everything back.
 */
import { expect, test } from "@playwright/test";

import { actAs, openAs, resetClock } from "./workflow-helpers";

const RESET = { headers: { "X-Acting-User": "amy" } };

test.beforeEach(async ({ request }) => {
  const res = await request.post("/api/admin/reset-demo", RESET);
  expect(res.ok(), await res.text()).toBe(true);
});

test.afterEach(async ({ request }) => {
  const res = await request.post("/api/admin/reset-demo", RESET);
  expect(res.ok(), await res.text()).toBe(true);
  await resetClock(request);
});

test("Priya makes City required for Singapore customers; the form shows it; Reset demo clears it", async ({
  page,
}) => {
  await openAs(page, "priya", "/admin");
  const editor = page.getByTestId("required-editor");
  await expect(editor).toBeVisible();
  await expect(page.getByTestId("req-domain")).toHaveValue("customer");
  await expect(page.getByTestId("req-country")).toHaveValue("SG");
  await expect(page.getByTestId("req-applies-note")).toContainText("Applies to new requests only");

  // Locked fields are greyed, always on, with a one-line reason.
  const name = page.getByTestId("req-row-CardName");
  await expect(name).toHaveAttribute("data-locked", "true");
  await expect(page.getByTestId("req-switch-CardName")).toBeDisabled();
  await expect(page.getByTestId("req-locked-CardName")).toContainText("SAP cannot create");
  await expect(page.getByTestId("req-locked-FederalTaxID")).toContainText("duplicate check");

  // City starts optional. Flip it and save.
  const city = page.getByTestId("req-row-City");
  await expect(city).toHaveAttribute("data-required", "false");
  await page.getByTestId("req-switch-City").click();
  await expect(city).toHaveAttribute("data-required", "true");
  await expect(city).toContainText("Unsaved change");
  await page.getByTestId("req-save").click();
  await expect(page.getByTestId("req-saved")).toContainText(
    "New requests for customers in Singapore use these rules.",
  );
  await expect(city).toContainText("Changed from the standard");
  await expect(page.getByTestId("req-change").first()).toContainText(
    "Priya made City required for Singapore customers",
  );

  // Amy's new customer form now asks for the City.
  await actAs(page, "Amy");
  await expect(page.getByTestId("req-save")).toBeDisabled();
  await expect(page.getByTestId("req-save-note")).toContainText("Switch to Priya to edit");
  await page.goto("/requests/new");
  await expect(page.getByTestId("field-City")).toContainText("Required");
  await expect(page.getByTestId("field-Street")).toContainText("Required");

  // Reset demo clears the toggle.
  await page.getByTestId("reset-demo").click();
  await page.getByTestId("reset-demo-confirm").click();
  await expect(page.getByText(/Demo reset in/)).toBeVisible();
  await page.goto("/requests/new");
  await expect(page.getByTestId("field-Street")).toContainText("Required");
  await expect(page.getByTestId("field-City")).not.toContainText("Required");

  await page.goto("/admin");
  await expect(page.getByTestId("req-row-City")).toHaveAttribute("data-required", "false");
  await expect(page.getByTestId("req-changes")).toContainText("No field has been changed yet");
});
