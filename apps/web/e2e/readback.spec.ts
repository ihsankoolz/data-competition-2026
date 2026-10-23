/**
 * Priya's read-back table with stubbed publish responses (SapPublishView):
 * every field matches; one field differs; bank rows arrive masked and stay
 * masked. Also the fallback to GET /sap-readback when the publish response
 * has no `sap_publish`, and the empty state when that answers 404.
 */
import { expect, type Page, test } from "@playwright/test";

const ID = "REQ-STUB-RB";

const SUMMARY = {
  req_id: ID,
  domain: "vendor",
  state: "APPROVED",
  title: "Precision Diagnostics Asia Pte Ltd",
  entity: "SPD",
  country: "SG",
  requestor_user_id: "amy",
  requestor_name: "Amy",
  created_at: "2026-10-05T09:00:00+08:00",
  updated_at: "2026-10-06T09:00:00+08:00",
  pending_with: ["Priya"],
};

const DETAIL = {
  ...SUMMARY,
  fields: {
    CardName: "Precision Diagnostics Asia Pte Ltd",
    FederalTaxID: "201912345K",
    BPBankAccounts: [{ BankCode: "DBS", AccountNo: "••••6789" }],
  },
  allowed_actions: ["publish"],
  stages: [],
  issues: [],
  sap_publish: null,
};

type Row = { field: string; sent: string | null; read_back: string | null; match: boolean };

const ROWS: Row[] = [
  { field: "CardCode", sent: "V00213", read_back: "V00213", match: true },
  {
    field: "CardName",
    sent: "Precision Diagnostics Asia Pte Ltd",
    read_back: "Precision Diagnostics Asia Pte Ltd",
    match: true,
  },
  { field: "CardType", sent: "cSupplier", read_back: "cSupplier", match: true },
  { field: "FederalTaxID", sent: "201912345K", read_back: "201912345K", match: true },
  { field: "BPBankAccounts[0].AccountNo", sent: "••••6789", read_back: "••••6789", match: true },
];

function view(rows: Row[]) {
  return {
    resource: "BusinessPartners",
    sap_code: "V00213",
    published_at: "2026-10-06T10:00:00+08:00",
    published_by: "Priya",
    active: rows.every((r) => r.match),
    all_match: rows.every((r) => r.match),
    rows,
  };
}

async function stub(
  page: Page,
  opts: { inPublish: ReturnType<typeof view> | null; readback: ReturnType<typeof view> | null },
) {
  await page.addInitScript(() => window.localStorage.setItem("lives-mdm.acting-user", "priya"));
  let published = false;
  await page.route(
    (url) => url.pathname === "/api/requests",
    (route) => {
      const state = new URL(route.request().url()).searchParams.get("state");
      const list =
        state === "APPROVED" && !published
          ? [SUMMARY]
          : state === "ACTIVE" && published
            ? [{ ...SUMMARY, state: "ACTIVE" }]
            : [];
      return route.fulfill({ contentType: "application/json", body: JSON.stringify(list) });
    },
  );
  await page.route(`**/api/requests/${ID}`, (route) =>
    route.fulfill({
      contentType: "application/json",
      body: JSON.stringify(
        published ? { ...DETAIL, state: "ACTIVE", sap_publish: opts.inPublish } : DETAIL,
      ),
    }),
  );
  await page.route(`**/api/requests/${ID}/publish`, (route) => {
    published = true;
    return route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({
        ...DETAIL,
        state: "ACTIVE",
        allowed_actions: [],
        sap_publish: opts.inPublish,
      }),
    });
  });
  await page.route(`**/api/requests/${ID}/sap-readback`, (route) =>
    opts.readback
      ? route.fulfill({ contentType: "application/json", body: JSON.stringify(opts.readback) })
      : route.fulfill({
          status: 404,
          contentType: "application/json",
          body: JSON.stringify({ detail: "This request has not been published to SAP yet." }),
        }),
  );
}

async function publish(page: Page) {
  await page.goto("/publish");
  await page.locator(`[data-testid="publish-item"][data-req="${ID}"]`).click();
  await page.getByTestId("publish").click();
  return page.getByTestId("publish-pane");
}

test("all fields match: green result, active in SAP, bank values stay masked", async ({ page }) => {
  await stub(page, { inPublish: view(ROWS), readback: null });
  const pane = await publish(page);

  const result = pane.getByTestId("readback-result");
  await expect(result).toHaveAttribute("data-match", "true");
  await expect(result).toContainText("all 5 fields match");
  await expect(pane.getByTestId("sap-code")).toHaveText("V00213");
  await expect(pane.getByTestId("sap-active")).toHaveText("Active in SAP");
  await expect(pane.getByTestId("readback-row")).toHaveCount(5);

  const bank = pane.getByTestId("readback-row").filter({ hasText: "BPBankAccounts" });
  await expect(bank.getByTestId("masked-value")).toHaveCount(2);
  await expect(bank).toContainText("••••6789");
  await expect(pane).not.toContainText("123456789");
});

test("one field differs: shown as a red row and the record is not switched on", async ({
  page,
}) => {
  const rows = ROWS.map((r) =>
    r.field === "CardName" ? { ...r, read_back: "Precision Diagnostics Asia", match: false } : r,
  );
  await stub(page, { inPublish: view(rows), readback: null });
  const pane = await publish(page);

  const result = pane.getByTestId("readback-result");
  await expect(result).toHaveAttribute("data-match", "false");
  await expect(result).toContainText("1 of 5 fields differ");
  await expect(pane.getByTestId("sap-active")).toHaveText("Inactive until checked");
  const bad = pane.locator('[data-testid="readback-row"][data-match="false"]');
  await expect(bad).toHaveCount(1);
  await expect(bad).toContainText("CardName");
  await expect(bad).toContainText("Differs");
  await expect(pane.locator('[data-testid="readback-row"][data-match="true"]')).toHaveCount(4);
});

test("long values wrap inside their cells: no sideways scrolling at 1440 wide", async ({
  page,
}) => {
  const long =
    "Lot 12, Jalan Tun Razak Medical Precinct, Tower B Level 23 Unit 23-01/23-08, ".repeat(3);
  const rows: Row[] = [
    ...ROWS,
    { field: "BPAddresses[0].Street", sent: long, read_back: long, match: true },
    {
      field: "EmailAddress",
      sent: "x".repeat(120) + "@example.com",
      read_back: "x".repeat(120) + "@example.com",
      match: true,
    },
  ];
  await stub(page, { inPublish: view(rows), readback: null });
  const pane = await publish(page);

  const table = pane.getByTestId("readback-table");
  await expect(table).toBeVisible();
  const fits = await table.evaluate((t) => t.scrollWidth <= t.parentElement!.clientWidth);
  expect(fits).toBe(true);
  const pageScroll = await page.evaluate(
    () => document.documentElement.scrollWidth <= document.documentElement.clientWidth,
  );
  expect(pageScroll).toBe(true);
});

test("no read-back in the publish answer: it is fetched from /sap-readback", async ({ page }) => {
  await stub(page, { inPublish: null, readback: view(ROWS) });
  const pane = await publish(page);
  await expect(pane.getByTestId("readback-result")).toHaveAttribute("data-match", "true");
});

test("no read-back anywhere: a plain empty state, not an error", async ({ page }) => {
  await stub(page, { inPublish: null, readback: null });
  const pane = await publish(page);
  await expect(pane.getByTestId("readback-unavailable")).toContainText(
    "Read-back details are not available for this record.",
  );
});
