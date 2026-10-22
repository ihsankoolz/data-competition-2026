/** "Create from email" with stubbed endpoints: pre-filled values, source quotes, missing fields. */
import { expect, test } from "@playwright/test";

const EMAIL = {
  email_id: "DEMO-01",
  received_at: "2026-10-05T08:12:00+08:00",
  from_name: "Marcus",
  from_address: "marcus@qtg.lives.example",
  subject: "New customer - Benh vien Cho Ray",
  snippet: "Pls create new customer Benh vien Cho Ray, HCMC, MST 0301234567",
  has_attachments: false,
};

test("pre-fills the form from an email and shows where each value came from", async ({ page }) => {
  await page.addInitScript(() => window.localStorage.setItem("lives-mdm.acting-user", "marcus"));
  await page.route("**/api/emails", (route) =>
    route.fulfill({ contentType: "application/json", body: JSON.stringify([EMAIL]) }),
  );
  await page.route("**/api/requests/from-email/DEMO-01", (route) =>
    route.fulfill({
      status: 201,
      contentType: "application/json",
      body: JSON.stringify({
        req_id: "REQ-E2E-2",
        domain: "customer",
        state: "DRAFT",
        title: "Benh vien Cho Ray",
        entity: "QTG",
        country: "VN",
        requestor_user_id: "marcus",
        requestor_name: "Marcus",
        created_at: "2026-10-05T09:00:00+08:00",
        updated_at: "2026-10-05T09:00:00+08:00",
        fields: {
          CardName: "Benh vien Cho Ray",
          FederalTaxID: "0301234567",
          City: "HCMC",
          purpose: "service contract (annual analyser service)",
          // Never taken from the server into the form: credit terms, and anything masked.
          CreditLimit: 5000000,
          PayTermsGrpCode: 3,
          Phone1: "••••1849",
        },
        missing_fields: ["Street", "EmailAddress"],
        prefill_quotes: {
          CardName: "new customer Benh vien Cho Ray",
          FederalTaxID: "MST 0301234567",
          City: "HCMC",
        },
        source_email_id: "DEMO-01",
      }),
    }),
  );
  // Keep this spec about pre-filling: the duplicate check answers "none".
  await page.route("**/api/dedup/check", (route) =>
    route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({ verdict: "none", message: "No similar record.", block_submit: false }),
    }),
  );

  await page.goto("/requests/new");
  await page.getByTestId("create-from-email").click();
  await page.getByTestId("email-DEMO-01").click();

  await expect(page.getByTestId("prefill-note")).toContainText("New customer - Benh vien Cho Ray");
  await expect(page.getByLabel("Legal name")).toHaveValue("Benh vien Cho Ray");
  const nameQuote = page.getByTestId("field-CardName").getByTestId("quote");
  await expect(nameQuote).toContainText("From the email:");
  await expect(nameQuote).toContainText("new customer Benh vien Cho Ray");
  await expect(page.getByTestId("field-FederalTaxID").getByTestId("quote")).toContainText(
    "MST 0301234567",
  );
  // Required fields the email did not give are highlighted straight away.
  await expect(page.getByTestId("field-Street")).toHaveAttribute("data-missing", "true");
  await expect(page.getByTestId("field-EmailAddress")).toHaveAttribute("data-missing", "true");
  await expect(page.getByTestId("field-CardName")).not.toHaveAttribute("data-missing", "true");
  await expect(page.getByTestId("verdict")).toHaveAttribute("data-verdict", "none");

  // Credit terms are typed by a person, and a masked value is never shown as real.
  await expect(page.getByLabel("Credit limit (local currency)")).toHaveValue("");
  await expect(page.locator("#PayTermsGrpCode")).toContainText("Choose one");
  await expect(page.getByLabel("Phone")).toHaveValue("");
});
