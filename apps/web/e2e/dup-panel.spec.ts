/**
 * Duplicate panel with a stubbed duplicate check (DEMO-01 shape). Runs before
 * the backend endpoints exist: only /forms, /personas and /clock are real.
 */
import { expect, type Page, type Route, test } from "@playwright/test";

const LIKELY_CHO_RAY = {
  verdict: "likely",
  message: "This looks like Bệnh viện Chợ Rẫy (C00084), already set up for SPD in Vietnam.",
  block_submit: true,
  grey_zone: false,
  elapsed_ms: 12,
  candidates: [
    {
      CardCode: "C00084",
      CardName: "Bệnh viện Chợ Rẫy",
      CardForeignName: null,
      CardType: "cCustomer",
      entity: "SPD",
      country: "VN",
      city: "Ho Chi Minh City",
      FederalTaxID: "0301234567",
      score: 0.99,
      name_score: 1,
      verdict: "likely",
      tax_id_match: true,
      reasons: [
        { layer: "tax_id", text: "Same tax ID (MST 0301234567) in Vietnam.", weight: 0.6 },
        {
          layer: "normalise",
          text: "Same name once Vietnamese accents are removed: “Benh vien Cho Ray”.",
          weight: 0.3,
        },
      ],
    },
  ],
  related: [
    {
      CardCode: "C00190",
      CardName: "Cho Ray Phnom Penh Hospital",
      CardType: "cCustomer",
      country: "TH",
      rule: "same_group_other_country",
      group_id: "G-CHORAY",
      explanation: "Same hospital group in another country: a separate legal entity, not a duplicate.",
    },
  ],
  judge: { status: "offline", reasons: [], message: "AI offline" },
};

function requestDetail(state: string, extra: Record<string, unknown> = {}) {
  return {
    req_id: "REQ-E2E-1",
    domain: "customer",
    state,
    title: "Benh vien Cho Ray",
    entity: "QTG",
    country: "VN",
    requestor_user_id: "marcus",
    requestor_name: "Marcus",
    created_at: "2026-10-05T09:00:00+08:00",
    updated_at: "2026-10-05T09:00:00+08:00",
    fields: {},
    ...extra,
  };
}

type Captured = { checks: Record<string, unknown>[]; decisions: Record<string, unknown>[] };

async function stubBackend(page: Page): Promise<Captured> {
  const captured: Captured = { checks: [], decisions: [] };
  const json = (route: Route, body: unknown, status = 200) =>
    route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });

  await page.route("**/api/dedup/check", async (route) => {
    captured.checks.push(route.request().postDataJSON());
    await json(route, LIKELY_CHO_RAY);
  });
  await page.route("**/api/requests", async (route) => {
    if (route.request().method() !== "POST") return route.fallback();
    await json(route, requestDetail("DRAFT"), 201);
  });
  await page.route("**/api/requests/REQ-E2E-1", async (route) => {
    await json(route, requestDetail("DRAFT"));
  });
  await page.route("**/api/requests/REQ-E2E-1/dedup-decision", async (route) => {
    const body = route.request().postDataJSON() as Record<string, unknown>;
    captured.decisions.push(body);
    await json(
      route,
      body.action === "link_to_existing"
        ? requestDetail("LINKED_TO_EXISTING", { linked_card_code: body.card_code })
        : requestDetail("DRAFT"),
    );
  });
  return captured;
}

async function openAsMarcus(page: Page) {
  await page.addInitScript(() => window.localStorage.setItem("lives-mdm.acting-user", "marcus"));
  await page.goto("/requests/new");
  await expect(page.getByRole("heading", { name: "New request" })).toBeVisible();
  // Marcus is QTG Vietnam: the form opens for his entity and country.
  await expect(page.locator("#ctx-country")).toHaveText(/Vietnam/);
  await expect(page.locator("#ctx-entity")).toHaveText(/QTG/);
  await expect(page.getByLabel("Legal name")).toBeVisible();
}

async function typeChoRay(page: Page) {
  await page.getByLabel("Legal name").pressSequentially("Benh vien Cho Ray", { delay: 20 });
  await page.getByLabel("Tax ID").fill("0301234567");
}

test("likely duplicate: side by side, submit blocked, link to existing", async ({ page }) => {
  const captured = await stubBackend(page);
  await openAsMarcus(page);
  await typeChoRay(page);

  const panel = page.getByTestId("dup-panel");
  await expect(panel.getByTestId("verdict")).toHaveAttribute("data-verdict", "likely");
  await expect(panel.getByTestId("verdict")).toContainText("Likely duplicate");

  // Debounced: typing 17 characters does not fire 17 checks.
  expect(captured.checks.length).toBeLessThanOrEqual(3);
  const last = captured.checks.at(-1)!;
  expect(last).toMatchObject({
    domain: "customer",
    entity: "QTG",
    fields: { CardName: "Benh vien Cho Ray", FederalTaxID: "0301234567", Country: "VN" },
  });

  // Side by side: what was typed next to the existing record, matching rows marked.
  const candidate = panel.getByTestId("candidate");
  await expect(candidate).toContainText("Bệnh viện Chợ Rẫy");
  await expect(candidate).toContainText("C00084");
  const table = candidate.getByTestId("comparison");
  const taxRow = table.getByRole("row", { name: /Tax ID/ });
  await expect(taxRow).toHaveAttribute("data-match", "true");
  await expect(taxRow).toContainText("0301234567");
  const nameRow = table.getByRole("row", { name: /Legal name/ });
  await expect(nameRow).toContainText("Benh vien Cho Ray");
  await expect(nameRow).toContainText("Bệnh viện Chợ Rẫy");
  await expect(nameRow).toContainText("Same once accents are ignored");
  await expect(table.getByRole("row", { name: /Entity/ })).toHaveAttribute("data-match", "false");

  // Plain-English reasons, related records and the AI status.
  const reasons = candidate.getByTestId("reasons");
  await expect(reasons).toContainText("Same tax ID (MST 0301234567) in Vietnam.");
  await expect(reasons).toContainText("Same name once Vietnamese accents are removed");
  await expect(panel.getByTestId("related")).toContainText("Same hospital group in another country");
  await expect(panel.getByTestId("judge")).toContainText("AI offline");

  // Submit is blocked until a human decides.
  await expect(page.getByTestId("submit")).toBeDisabled();
  await expect(page.getByTestId("submit-hint")).toContainText("decide on the likely duplicate");

  await panel.getByTestId("link-C00084").click();
  const linked = panel.getByTestId("linked");
  await expect(linked).toContainText("Linked to C00084.");
  await expect(linked).toContainText("No approval needed; the duplicate never reached an approver.");
  expect(captured.decisions).toEqual([{ action: "link_to_existing", card_code: "C00084" }]);
  await expect(page.getByRole("link", { name: "See the request" })).toHaveAttribute(
    "href",
    "/requests/REQ-E2E-1",
  );
});

test("not a duplicate: a reason is required, then submit is allowed", async ({ page }) => {
  const captured = await stubBackend(page);
  await openAsMarcus(page);
  await typeChoRay(page);

  const panel = page.getByTestId("dup-panel");
  await expect(panel.getByTestId("verdict")).toHaveAttribute("data-verdict", "likely");
  await expect(page.getByTestId("submit")).toBeDisabled();

  await panel.getByTestId("not-duplicate").click();
  const dialog = page.getByRole("dialog");
  await expect(dialog).toContainText("Why is this a different customer?");
  const save = dialog.getByRole("button", { name: "Save reason" });
  await dialog.getByLabel("Reason").fill("too short");
  await expect(save).toBeDisabled();
  await dialog.getByLabel("Reason").fill("A different legal entity: the QTG service arm.");
  await save.click();

  await expect(dialog).toBeHidden();
  await expect(panel.getByTestId("override-saved")).toContainText("You can submit now.");
  expect(captured.decisions).toEqual([
    { action: "not_duplicate", reason: "A different legal entity: the QTG service arm." },
  ]);
  await expect(page.getByTestId("submit")).toBeEnabled();
});
