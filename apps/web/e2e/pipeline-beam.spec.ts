/**
 * Stretch S1 pipeline beam (D-023 #4): the strip at the top of the status page
 * (Email -> Read by AI -> Golden record -> Approvals -> In SAP) lights each step
 * from the request's real state. One sweep of at most 400 ms into the current
 * step, never looping, none under reduced motion.
 */
import { expect, type Page, test } from "@playwright/test";

import { approveAs, openAs, submittedCustomer } from "./workflow-helpers";

function node(page: Page, id: string) {
  return page.locator(`[data-testid="beam-node"][data-node="${id}"]`);
}

async function expectStates(page: Page, states: Record<string, string>) {
  for (const [id, state] of Object.entries(states)) {
    await expect(node(page, id), id).toHaveAttribute("data-state", state);
  }
}

function collectErrors(page: Page) {
  const errors: string[] = [];
  page.on("console", (m) => m.type() === "error" && errors.push(m.text()));
  page.on("pageerror", (e) => errors.push(e.message));
  return errors;
}

test("typed customer: mid-approval, then all approved and live in SAP", async ({
  page,
  request,
}) => {
  const errors = collectErrors(page);
  let d = await submittedCustomer(request, "Quillon Beam Medical Pte Ltd");

  await openAs(page, "amy", `/requests/${d.req_id}`);
  const beam = page.getByTestId("pipeline-beam");
  await expect(beam.getByRole("list", { name: "Where this request is" })).toBeVisible();
  await expectStates(page, {
    email: "skipped",
    ai: "skipped",
    golden: "done",
    approvals: "current",
    sap: "waiting",
  });
  await expect(node(page, "email")).toContainText("Typed into the form");
  await expect(node(page, "golden")).toContainText("No duplicate found");
  await expect(node(page, "approvals")).toContainText("0 of 3 approved");
  // Screen readers hear each step's state, not just its colour.
  await expect(node(page, "approvals")).toContainText("Happening now");

  // Exactly one sweep, into the current step, inside the 400 ms budget.
  const sweeps = beam.locator('[data-testid="beam-segment"][data-sweep="true"]');
  await expect(sweeps).toHaveCount(1);
  await expect(sweeps).toHaveAttribute("data-kind", "flow");
  await expect(sweeps.locator("linearGradient")).toHaveCount(1);
  const ms = Number(await sweeps.getAttribute("data-duration-ms"));
  expect(ms).toBeGreaterThan(0);
  expect(ms).toBeLessThanOrEqual(400);

  // Compact: "Waiting on" stays well above the fold at 1440x900.
  const box = await beam.boundingBox();
  expect(box!.height).toBeLessThanOrEqual(115);
  await expect(page.getByTestId("pending-with")).toBeInViewport();

  d = await approveAs(request, d, "daniel");
  await page.reload();
  await expect(node(page, "approvals")).toContainText("1 of 3 approved");
  await page.screenshot({ path: "test-results/beam/status-beam.png" });

  for (const who of ["weijie", "meiling"]) d = await approveAs(request, d, who);
  await page.reload();
  await expectStates(page, { golden: "done", approvals: "done", sap: "current" });
  await expect(node(page, "sap")).toContainText("waiting to be published");

  const pub = await request.post(`/api/requests/${d.req_id}/publish`, {
    headers: { "X-Acting-User": "priya" },
  });
  expect(pub.ok(), await pub.text()).toBe(true);
  await page.reload();
  await expectStates(page, { golden: "done", approvals: "done", sap: "done" });
  await expect(node(page, "approvals")).toContainText("All approved");
  await expect(node(page, "sap")).toContainText(/Live in SAP as C\d+/);
  await expect(beam.locator('[data-testid="beam-segment"][data-sweep="true"]')).toHaveCount(0);

  expect(errors).toEqual([]);
});

test("from the DEMO-01 email, then linked: approvals not needed, already in SAP", async ({
  page,
  request,
}) => {
  const errors = collectErrors(page);
  const headers = { "X-Acting-User": "marcus" };
  const res = await request.post("/api/requests/from-email/DEMO-01", { headers });
  expect(res.ok(), await res.text()).toBe(true);
  const draft = (await res.json()) as { req_id: string; prefill_quotes: Record<string, string> };
  const quotes = Object.keys(draft.prefill_quotes).length;
  expect(quotes).toBeGreaterThan(0);

  await openAs(page, "marcus", `/requests/${draft.req_id}`);
  await expectStates(page, {
    email: "done",
    ai: "done",
    golden: "current",
    approvals: "waiting",
    sap: "waiting",
  });
  await expect(node(page, "email")).toContainText("From an email");
  await expect(node(page, "ai")).toContainText(`${quotes} details pre-filled`);
  await expect(node(page, "golden")).toContainText("Checking for duplicates");

  const link = await request.post(`/api/requests/${draft.req_id}/dedup-decision`, {
    headers,
    data: { action: "link_to_existing", card_code: "C00084" },
  });
  expect(link.ok(), await link.text()).toBe(true);
  await page.reload();
  await expectStates(page, {
    email: "done",
    ai: "done",
    golden: "done",
    approvals: "skipped",
    sap: "done",
  });
  await expect(node(page, "golden")).toContainText("Linked to Bệnh viện Chợ Rẫy");
  await expect(node(page, "approvals")).toContainText("Existing record used");
  await expect(node(page, "sap")).toContainText("Already in SAP as C00084");

  expect(errors).toEqual([]);
});

test("reduced motion: no sweep, static lines only", async ({ page, request }) => {
  await page.emulateMedia({ reducedMotion: "reduce" });
  const d = await submittedCustomer(request, "Quillon Still Beam Medical Pte Ltd");
  await openAs(page, "amy", `/requests/${d.req_id}`);
  const beam = page.getByTestId("pipeline-beam");
  await expect(beam).toHaveAttribute("data-reduced-motion", "true");
  await expect(node(page, "approvals")).toHaveAttribute("data-state", "current");
  await expect(beam.getByTestId("beam-segment")).toHaveCount(4);
  await expect(beam.locator('[data-testid="beam-segment"][data-sweep="true"]')).toHaveCount(0);
  await expect(beam.locator("linearGradient")).toHaveCount(0);
});
