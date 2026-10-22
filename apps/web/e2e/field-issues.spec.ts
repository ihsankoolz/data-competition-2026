/**
 * D-018 #3: submit answers 422 {detail, issues}. The detail stays as the
 * summary under the button; each issue appears next to its field and clears
 * when that field is edited. Stubbed, so it runs before the backend's
 * validator lands; the real 422 has the same shape.
 */
import { expect, test } from "@playwright/test";

const DRAFT = {
  req_id: "REQ-E2E-ISSUES",
  domain: "customer",
  state: "DRAFT",
  title: "Quillon Issues Medical Pte Ltd",
  entity: "SPD",
  country: "SG",
  requestor_user_id: "amy",
  requestor_name: "Amy",
  created_at: "2026-10-05T09:00:00+08:00",
  updated_at: "2026-10-05T09:00:00+08:00",
  fields: {},
  issues: [],
};

test("submit's field issues show next to each field and clear on edit", async ({ page }) => {
  await page.addInitScript(() => window.localStorage.setItem("lives-mdm.acting-user", "amy"));
  await page.route("**/api/dedup/check", (route) =>
    route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({ verdict: "none", message: "No similar record.", block_submit: false }),
    }),
  );
  await page.route("**/api/requests", (route) =>
    route.request().method() === "POST"
      ? route.fulfill({ status: 201, contentType: "application/json", body: JSON.stringify(DRAFT) })
      : route.fallback(),
  );
  await page.route("**/api/requests/REQ-E2E-ISSUES/submit", (route) =>
    route.fulfill({
      status: 422,
      contentType: "application/json",
      body: JSON.stringify({
        detail: "Two fields need fixing before this can go to approvers.",
        issues: [
          {
            field: "FederalTaxID",
            label: "Tax ID (UEN)",
            message: "A Singapore UEN has 9 or 10 characters, like 201912345K.",
            kind: "format",
          },
          {
            field: "EmailAddress",
            label: "Contact email",
            message: "Use a full email address, like accounts@hospital.com.",
            kind: "format",
          },
          {
            field: "Country",
            label: "Country",
            message: "This entity does not trade in that country.",
            kind: "not_allowed",
          },
        ],
      }),
    }),
  );

  await page.goto("/requests/new");
  await expect(page.getByLabel("Legal name")).toBeVisible();
  await page.getByLabel("Legal name").fill("Quillon Issues Medical Pte Ltd");
  await page.getByLabel("Tax ID").fill("12345");
  await page.getByLabel("Billing address").fill("8 Kallang Way");
  await page.getByLabel("City").fill("Singapore");
  await page.getByLabel("Contact email").fill("accounts@quillon");
  await page.getByTestId("submit").click();

  await expect(page.getByTestId("submit-error")).toHaveText(
    "Two fields need fixing before this can go to approvers.",
  );
  const tax = page.getByTestId("field-FederalTaxID");
  await expect(tax).toHaveAttribute("data-issue", "true");
  await expect(tax.getByTestId("field-issue")).toHaveText(
    "A Singapore UEN has 9 or 10 characters, like 201912345K.",
  );
  await expect(page.getByTestId("field-EmailAddress").getByTestId("field-issue")).toBeVisible();
  // A problem with a field that is not on the form is listed under the button.
  await expect(page.getByTestId("other-issues")).toContainText(
    "Country: This entity does not trade in that country.",
  );

  // Editing the field clears its (now out of date) problem; the others stay.
  await page.getByLabel("Tax ID").fill("201912345K");
  await expect(tax).not.toHaveAttribute("data-issue", "true");
  await expect(page.getByTestId("field-EmailAddress")).toHaveAttribute("data-issue", "true");
});
