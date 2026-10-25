/**
 * Timed persona walkthrough of the 2:30 demo storyline (PRD section 4, steps 1-7).
 * Rehearsal tool: run by `make rehearse` only, never by `make e2e` (D-021). Records per step:
 * machine time, clicks, keystrokes, 1440x900 screenshots, console errors and failed API
 * responses. A failing step is logged and the walk carries on, so one bug does not hide the rest.
 */
import fs from "node:fs";

import { type APIRequestContext, expect, type Locator, type Page, test } from "@playwright/test";

import { actAs, resetClock } from "./workflow-helpers";

const OUT = process.env.REHEARSE_OUT ?? "test-results/rehearse";
fs.mkdirSync(OUT, { recursive: true });

type Rec = {
  step: string;
  machineMs: number;
  wallMs: number;
  clicks: number;
  keys: number;
  notes: string[];
  errors: string[];
  failed: string[];
  failure?: string;
};
const records: Rec[] = [];
let cur: Rec;
let shotMs = 0;

function begin(step: string) {
  cur = { step, machineMs: 0, wallMs: 0, clicks: 0, keys: 0, notes: [], errors: [], failed: [] };
  shotMs = 0;
  return Date.now();
}
function end(t0: number) {
  cur.wallMs = Date.now() - t0 - shotMs;
  records.push(cur);
  fs.writeFileSync(`${OUT}/log.json`, JSON.stringify(records, null, 2));
}
const note = (s: string) => cur.notes.push(s);

/** Time a wait on the machine (page loads, API round trips), not presenter actions. */
async function machine<T>(fn: () => Promise<T>): Promise<T> {
  const t = Date.now();
  try {
    return await fn();
  } finally {
    cur.machineMs += Date.now() - t;
  }
}
async function click(loc: Locator) {
  cur.clicks += 1;
  await loc.click();
}
async function type(loc: Locator, text: string) {
  cur.clicks += 1;
  cur.keys += text.length;
  await loc.fill(text);
}
/** One simulated hour between approvals, so a reminder and the approval after it show
 * different times on the status page. */
async function clockHour(request: APIRequestContext) {
  const res = await request.post("/api/clock/advance", {
    headers: { "X-Acting-User": "amy" },
    data: { hours: 1 },
  });
  expect(res.ok(), await res.text()).toBe(true);
}

async function shot(page: Page, name: string, full = true) {
  const t = Date.now();
  await page.screenshot({ path: `${OUT}/${name}.png`, fullPage: full });
  shotMs += Date.now() - t;
}
async function persona(page: Page, name: string) {
  cur.clicks += 2;
  await actAs(page, name);
}
async function runStep(name: string, page: Page, fn: () => Promise<void>, shotName: string) {
  const t0 = begin(name);
  try {
    await fn();
  } catch (e) {
    cur.failure = String(e instanceof Error ? e.message : e)
      .split("\n")
      .slice(0, 6)
      .join(" | ");
    try {
      await shot(page, `${shotName}-FAIL`);
    } catch {
      /* ignore */
    }
  }
  end(t0);
}
const txt = async (l: Locator) =>
  ((await l.textContent().catch(() => "(none)")) ?? "").replace(/\s+/g, " ").trim();

test("persona walkthrough", async ({ page, request }) => {
  test.setTimeout(900_000);
  await resetClock(request);
  const rs = await request.post("/api/admin/reset-demo", { headers: { "X-Acting-User": "amy" } });
  console.log("pre: reset-demo status " + rs.status());

  page.on("console", (m) => {
    if (m.type() === "error" && cur) cur.errors.push(m.text().slice(0, 300));
  });
  page.on("pageerror", (e) => cur && cur.errors.push("pageerror: " + e.message.slice(0, 300)));
  page.on("response", (r) => {
    if (r.status() >= 400 && cur) {
      cur.failed.push(r.status() + " " + r.request().method() + " " + new URL(r.url()).pathname);
    }
  });

  await page.addInitScript(() => {
    if (window.sessionStorage.getItem("wt-set")) return;
    window.sessionStorage.setItem("wt-set", "1");
    window.localStorage.setItem("lives-mdm.acting-user", "marcus");
  });

  let itemId = "";
  let vendorId = "";

  // ---------------------------------------------------------------- 1. Messy inbox
  await runStep(
    "1 messy inbox",
    page,
    async () => {
      await machine(() => page.goto("/inbox"));
      await machine(() =>
        expect(page.getByTestId("email-list").locator("li").first()).toBeVisible(),
      );
      note("emails listed: " + (await page.getByTestId("email-list").locator("li").count()));
      await shot(page, "01a-inbox-raw");
      const demo01 = page.getByTestId("inbox-DEMO-01");
      const visible = await demo01.isVisible();
      note("DEMO-01 visible without search: " + visible);
      if (!visible) await type(page.getByLabel("Search emails"), "Cho Ray");
      await click(demo01);
      const pane = page.getByTestId("email-pane");
      const reading = pane.getByTestId("ai-reading");
      await machine(() => expect(pane.getByTestId("read-with-ai")).toBeVisible());
      // The live AI trace (D-023 #3): details appear one by one, their words lit in the email.
      await click(pane.getByTestId("read-with-ai"));
      const tRead = Date.now();
      await machine(() =>
        page.waitForFunction(
          () =>
            document
              .querySelector('[data-testid="ai-reading"]')
              ?.getAttribute("data-trace-state") === "streaming" &&
            document.querySelectorAll('[data-testid="extracted-fields"] > li').length >= 3,
        ),
      );
      await shot(page, "01b-inbox-trace-mid", false);
      note(
        "mid-trace: " +
          (await reading.getByTestId("extracted-fields").locator("li").count()) +
          " details shown, still streaming: " +
          ((await reading.getAttribute("data-trace-state")) === "streaming"),
      );
      await machine(() => expect(reading).toHaveAttribute("data-trace-state", "done"));
      note("trace seconds (click to done): " + ((Date.now() - tRead) / 1000).toFixed(1));
      note("replay badge: " + (await reading.getByTestId("replay-badge").isVisible()));
      note("chip: " + (await txt(reading.getByTestId("category-chip"))));
      note("confidence: " + (await txt(pane.getByTestId("confidence"))));
      note(
        "highlights: " +
          (await pane.getByTestId("email-body").getByTestId("quote-highlight").count()),
      );
      await shot(page, "01c-email-read");
      await shot(page, "01c-email-read-viewport", false);
      await click(page.getByTestId("sort-all"));
      const t = Date.now();
      await machine(() =>
        expect(page.getByTestId("sort-all")).toHaveText(/All emails sorted/, { timeout: 60_000 }),
      );
      note("sort-all machine seconds: " + ((Date.now() - t) / 1000).toFixed(1));
      await shot(page, "01d-inbox-sorted");
    },
    "01",
  );

  // ---------------------------------------------------------------- 2. Marcus
  await runStep(
    "2 Marcus Cho Ray",
    page,
    async () => {
      await click(page.getByTestId("create-request"));
      await machine(() => expect(page.getByTestId("prefill-note")).toBeVisible());
      note("legal name: " + (await page.getByLabel("Legal name").inputValue()));
      note("tax id: " + (await page.getByLabel("Tax ID").inputValue()));
      const panel = page.getByTestId("dup-panel");
      await machine(() =>
        expect(panel.getByTestId("verdict")).toHaveAttribute("data-verdict", "likely", {
          timeout: 20_000,
        }),
      );
      note("verdict: " + (await txt(panel.getByTestId("verdict"))).slice(0, 200));
      await shot(page, "02a-form-prefilled-dup");
      await shot(page, "02a-form-prefilled-dup-viewport", false);
      const cand = panel.getByTestId("candidate").filter({ hasText: "C00084" });
      note("candidate: " + (await txt(cand)).slice(0, 400));
      await click(cand.getByTestId("link-C00084"));
      await machine(() => expect(panel.getByTestId("linked")).toBeVisible());
      note("linked: " + (await txt(panel.getByTestId("linked"))).slice(0, 200));
      await shot(page, "02b-linked");
      await click(page.getByRole("link", { name: "See the request" }));
      await machine(() =>
        expect(page.getByTestId("request-state")).toHaveAttribute(
          "data-state",
          "LINKED_TO_EXISTING",
        ),
      );
      note("status: " + (await txt(page.getByTestId("request-status"))).slice(0, 250));
      await shot(page, "02c-status-linked");
    },
    "02",
  );

  // Pre-staged outside the video: a vendor request with bank details waiting on Finance.
  {
    const h = { "X-Acting-User": "amy" };
    const v = await request.post("/api/requests", {
      headers: h,
      data: {
        domain: "vendor",
        entity: "SPD",
        country: "SG",
        fields: {
          CardName: "Precision Diagnostics Asia Pte Ltd",
          Country: "SG",
          FederalTaxID: "201845123K",
          Street: "10 Science Park Road",
          City: "Singapore",
          ZipCode: "117684",
          EmailAddress: "ar@precisiondx.sg.example",
          PayTermsGrpCode: 1,
          BPBankAccounts: [
            {
              BankCode: "DBS",
              AccountNo: "072-123456-7",
              AccountName: "Precision Diagnostics Asia Pte Ltd",
              BICSwiftCode: "DBSSSGSG",
              Country: "SG",
            },
          ],
        },
      },
    });
    const vj = (await v.json()) as { req_id?: string };
    vendorId = vj.req_id ?? "";
    let s = 0;
    if (vendorId) {
      s = (await request.post("/api/requests/" + vendorId + "/submit", { headers: h })).status();
    }
    console.log(
      "prestage vendor: create " +
        v.status() +
        " id=" +
        vendorId +
        " submit " +
        s +
        " " +
        (vendorId ? "" : JSON.stringify(vj).slice(0, 300)),
    );
  }

  // ---------------------------------------------------------------- 3. Amy item
  await runStep(
    "3 Amy malaria kit",
    page,
    async () => {
      await persona(page, "Amy");
      await click(page.getByRole("link", { name: "Messy inbox", exact: true }));
      await machine(() =>
        expect(page.getByTestId("email-list").locator("li").first()).toBeVisible(),
      );
      const demo02 = page.getByTestId("inbox-DEMO-02");
      const vis = await demo02.isVisible();
      note("DEMO-02 visible without search: " + vis);
      if (!vis) await type(page.getByLabel("Search emails"), "Malaria");
      await click(demo02);
      const pane = page.getByTestId("email-pane");
      const read = pane.getByTestId("read-with-ai");
      if (await read.isVisible()) await click(read);
      await machine(() => expect(pane.getByTestId("create-request")).toBeVisible());
      await shot(page, "03a-demo02-read");
      note("extracted: " + (await txt(pane.getByTestId("extracted-fields"))).slice(0, 400));
      note("missing: " + (await txt(pane.getByTestId("missing-fields"))).slice(0, 300));
      await click(pane.getByTestId("create-request"));
      await machine(() => expect(page.getByTestId("prefill-note")).toBeVisible());
      await machine(() => expect(page.getByLabel("Item name")).toBeVisible());
      note("item name: " + (await page.getByLabel("Item name").inputValue()));
      const missing = await page
        .locator('[data-testid^="field-"][data-missing="true"]')
        .evaluateAll((els) => els.map((e) => e.getAttribute("data-testid")));
      note("missing-flagged fields: " + missing.join(", "));
      note("submit hint: " + (await txt(page.getByTestId("submit-hint"))));
      note(
        "suggested: " +
          (
            await page.getByTestId("suggested").evaluateAll((els) => els.map((e) => e.textContent))
          ).join(" || "),
      );
      await shot(page, "03b-item-form-prefilled");
      await shot(page, "03b-item-form-prefilled-viewport", false);

      const regs: [string, string, string][] = [
        ["SG", "DIV-001", "2030-01-10"],
        ["MY", "MDA-002", "2030-02-01"],
        ["VN", "VN-3", "2030-03-01"],
      ];
      for (const [c, no, exp] of regs) {
        const row = page.getByTestId("registration-" + c);
        if ((await row.count()) === 0) {
          note("no registration row for " + c);
          continue;
        }
        await type(row.getByLabel(/Registration number/), no);
        await type(row.getByLabel(/Expiry date/), exp);
      }
      note("submit hint after regs: " + (await txt(page.getByTestId("submit-hint"))));
      await shot(page, "03c-item-form-filled");
      await click(page.getByTestId("submit"));
      await machine(() => expect(page).toHaveURL(/\/requests\/REQ-/, { timeout: 20_000 }));
      itemId = page.url().split("/").pop() ?? "";
      await machine(() => expect(page.getByTestId("pending-with")).toBeVisible());
      note("pending-with: " + (await txt(page.getByTestId("pending-with"))));
      note(
        "stage1 tasks: " +
          (
            await page
              .getByTestId("stage-1")
              .locator('[data-testid="task"]')
              .evaluateAll((els) =>
                els.map(
                  (e) => e.getAttribute("data-assignee") + ":" + e.getAttribute("data-status"),
                ),
              )
          ).join(", "),
      );
      note("qr-reason: " + (await txt(page.getByTestId("qr-reason").first())));
      await shot(page, "03d-item-status");
      await shot(page, "03d-item-status-viewport", false);
    },
    "03",
  );

  // ---------------------------------------------------------------- 4. Wei Jie
  await runStep(
    "4 Wei Jie",
    page,
    async () => {
      // D-021: the Finance beat is the DEMO-07 vendor. Bank details are stripped before the AI
      // reads the email; the vendor request with bank rows is pre-staged above (secure form).
      await click(page.getByRole("link", { name: "Messy inbox", exact: true }));
      const demo07 = page.getByTestId("inbox-DEMO-07");
      await machine(() =>
        expect(page.getByTestId("email-list").locator("li").first()).toBeVisible(),
      );
      if (!(await demo07.isVisible())) await type(page.getByLabel("Search emails"), "Precision");
      await click(demo07);
      const pane07 = page.getByTestId("email-pane");
      const read07 = pane07.getByTestId("read-with-ai");
      if (await read07.isVisible()) await click(read07);
      await machine(() =>
        expect(pane07.getByText(/Bank details in this email were removed/)).toBeVisible(),
      );
      await machine(() =>
        expect(pane07.getByTestId("ai-reading")).toHaveAttribute("data-trace-state", "done"),
      );
      await shot(page, "04-0-demo07-bank-stripped", false);
      await click(page.getByRole("button", { name: "+1 day" }));
      await machine(() => expect(page.getByTestId("sim-clock-day")).toContainText("Day 2"));
      note("clock: " + (await txt(page.getByTestId("sim-clock-time"))));
      await persona(page, "Wei Jie");
      note(
        "Wei Jie tasks on the malaria kit: " +
          (await page.locator('[data-testid="task"][data-assignee="weijie"]').count()),
      );
      const bell = page.getByTestId("notifications-bell");
      await machine(() =>
        expect(bell.getByTestId("notifications-count")).toBeVisible({ timeout: 15_000 }),
      );
      note("bell count: " + (await txt(bell.getByTestId("notifications-count"))));
      await click(bell);
      await machine(() => expect(page.getByTestId("notification").first()).toBeVisible());
      const kinds = await page
        .getByTestId("notification")
        .evaluateAll((els) =>
          els.map(
            (e) =>
              e.getAttribute("data-kind") +
              ": " +
              (e.textContent ?? "").replace(/\s+/g, " ").slice(0, 120),
          ),
        );
      note("notifications: " + kinds.join(" || "));
      await shot(page, "04a-bell-reminder", false);
      const rem = page.locator('[data-testid="notification"][data-kind="reminder"]').first();
      if ((await rem.count()) === 0) {
        throw new Error("no reminder notification for Wei Jie after +1 day");
      }
      await click(rem);
      await machine(() => expect(page).toHaveURL(/\/requests\/REQ-0002$/));
      await machine(() => expect(page.getByTestId("request-status").first()).toBeVisible());
      note("opened: " + (await txt(page.locator("h1").first())));
      await machine(() => expect(page.getByTestId("request-fields").first()).toBeVisible());
      await page.waitForTimeout(500);
      await shot(page, "04b-weijie-sees-bank");
      note("bank as Wei Jie: " + (await txt(page.getByTestId("bank-lines"))).slice(0, 250));
      await persona(page, "Daniel");
      await page.waitForTimeout(800);
      note("bank as Daniel: " + (await txt(page.getByTestId("bank-lines"))).slice(0, 250));
      await shot(page, "04c-daniel-sees-masked");
      await persona(page, "Wei Jie");
      await machine(() => expect(page.getByTestId("your-turn")).toBeVisible());
      await shot(page, "04d-weijie-your-turn", false);
      await clockHour(request);
      await click(page.getByTestId("your-turn").getByTestId("approve"));
      await machine(() =>
        expect(page.locator('[data-testid="task"][data-assignee="weijie"]')).toHaveAttribute(
          "data-status",
          "approved",
        ),
      );
      await shot(page, "04e-weijie-approved");
    },
    "04",
  );

  await runStep(
    "4b other approvers (item) via Act as",
    page,
    async () => {
      await machine(() => page.goto("/requests/" + itemId));
      const stage1 = page.getByTestId("stage-1");
      await machine(() => expect(stage1).toBeVisible());
      for (let guard = 0; guard < 8; guard += 1) {
        const pending = stage1.locator('[data-testid="task"][data-status="pending"]').first();
        if ((await pending.count()) === 0) break;
        const name = (
          (await pending.locator("span.font-medium").first().textContent()) ?? ""
        ).trim();
        const as = pending.getByTestId("act-as");
        if ((await as.count()) > 0) await click(as);
        await machine(() => expect(page.getByTestId("persona-switcher")).toContainText(name));
        await clockHour(request);
        await click(page.getByTestId("your-turn").getByTestId("approve"));
        await machine(() =>
          expect(
            stage1
              .locator('[data-testid="task"][data-status="approved"]')
              .filter({ hasText: name }),
          ).toHaveCount(1),
        );
        note("approved as " + name);
      }
      await machine(() =>
        expect(page.getByTestId("stage-2")).toHaveAttribute("data-status", "open"),
      );
      note("pending-with: " + (await txt(page.getByTestId("pending-with"))));
      await shot(page, "04f-item-all-stage1-approved");
      const audit = await page
        .getByTestId("audit-entry")
        .evaluateAll((els) =>
          els.map((e) => (e.textContent ?? "").replace(/\s+/g, " ").slice(0, 140)),
        );
      note("audit: " + audit.join(" || "));
    },
    "04b",
  );

  {
    const h = (u: string) => ({ "X-Acting-User": u });
    const d = await request.get("/api/requests/" + vendorId, { headers: h("amy") });
    const dj = (await d.json()) as {
      stages?: { tasks: { task_id: string; assignee_user_id: string; status: string }[] }[];
    };
    for (const t of (dj.stages ?? []).flatMap((s) => s.tasks)) {
      if (t.status === "pending") {
        await clockHour(request);
        await request.post("/api/approvals/" + t.task_id + "/decision", {
          headers: h(t.assignee_user_id),
          data: { action: "approve" },
        });
      }
    }
  }

  // ---------------------------------------------------------------- 5. Priya
  await runStep(
    "5 Priya publish",
    page,
    async () => {
      await persona(page, "Priya");
      await click(page.getByRole("link", { name: "Publish to SAP", exact: true }));
      await machine(() => expect(page.getByTestId("publish-item").first()).toBeVisible());
      const items = await page
        .getByTestId("publish-item")
        .evaluateAll((els) => els.map((e) => e.getAttribute("data-req")));
      note("ready to publish: " + items.join(", "));
      await shot(page, "05a-publish-list");
      await click(page.locator('[data-testid="publish-item"][data-req="' + itemId + '"]'));
      const pane = page.getByTestId("publish-pane");
      await machine(() => expect(pane).toBeVisible());
      note("dedup line: " + (await txt(pane.getByTestId("dedup-line"))));
      await shot(page, "05b-publish-pane", false);
      await click(pane.getByTestId("publish"));
      await machine(() =>
        expect(pane.getByTestId("readback-result")).toBeVisible({ timeout: 30_000 }),
      );
      note("readback: " + (await txt(pane.getByTestId("readback-result"))));
      note("sap code: " + (await txt(pane.getByTestId("sap-code"))));
      note("sap active: " + (await txt(pane.getByTestId("sap-active"))));
      await shot(page, "05c-readback");
      await shot(page, "05c-readback-viewport", false);
      // The item's journey once it is in SAP: the pipeline beam lit end to end (D-023 #4).
      await machine(() => page.goto("/requests/" + itemId));
      const beam = page.getByTestId("pipeline-beam");
      await machine(() =>
        expect(beam.locator('[data-testid="beam-node"][data-node="sap"]')).toHaveAttribute(
          "data-state",
          "done",
        ),
      );
      note(
        "beam: " +
          (
            await beam
              .locator('[data-testid="beam-node"]')
              .evaluateAll((els) =>
                els.map((e) => e.getAttribute("data-node") + "=" + e.getAttribute("data-state")),
              )
          ).join(", "),
      );
      await beam.scrollIntoViewIfNeeded();
      await shot(page, "05x-status-beam", false);
    },
    "05",
  );

  // ---------------------------------------------------------------- 6. Regional
  await runStep(
    "6 regional view",
    page,
    async () => {
      await persona(page, "Daniel");
      await click(page.getByRole("link", { name: /Regional/ }));
      for (const i of [1, 2]) {
        const ta = Date.now();
        const r = await page.request.get("/api/analytics/regional?view=before", {
          headers: { "X-Acting-User": "daniel" },
        });
        note(
          "API regional call " +
            i +
            ": " +
            r.status() +
            " in " +
            ((Date.now() - ta) / 1000).toFixed(1) +
            "s",
        );
      }
      const tReg = Date.now();
      await machine(() => expect(page.getByTestId("period")).toBeVisible());
      await machine(() =>
        expect(page.getByTestId("heat-cell").first()).toBeVisible({ timeout: 60_000 }),
      );
      note(
        "regional first load seconds (click to heatmap): " +
          ((Date.now() - tReg) / 1000).toFixed(1),
      );
      note("period: " + (await txt(page.getByTestId("period"))));
      note("headline: " + (await txt(page.getByTestId("merge-headline"))));
      note("customers (before): " + (await txt(page.getByTestId("kpi-customers-value"))));
      note("lost-count (before): " + (await txt(page.getByTestId("lost-count"))));
      await shot(page, "06a-regional-before");
      await shot(page, "06a-regional-before-viewport", false);
      await click(page.getByTestId("view-after"));
      await machine(() =>
        expect(page.getByTestId("lost-customers").getByTestId("duplicate-marker")).toHaveCount(0),
      );
      note("customers (after): " + (await txt(page.getByTestId("kpi-customers-value"))));
      note("lost-count (after): " + (await txt(page.getByTestId("lost-count"))));
      await shot(page, "06b-regional-after");
      await shot(page, "06b-regional-after-viewport", false);
      // Stretch S2: the Southeast Asia map beside the heatmap, scrolled just far enough to show
      // all of it (the merge strip's foot stays in view).
      const map = page.getByTestId("sea-map");
      await machine(() => expect(map).toHaveAttribute("data-drawn", "true"));
      note("map: " + (await map.getAttribute("aria-label")));
      await page.getByTestId("sea-map-panel").scrollIntoViewIfNeeded();
      await shot(page, "06c-regional-map", false);
      const fp = page.getByTestId("forecast-panel");
      await fp.scrollIntoViewIfNeeded();
      cur.clicks += 1;
      note("forecast headline: " + (await txt(fp.getByTestId("data-headline"))));
      await shot(page, "06c-forecast-clean", false);
      await click(fp.getByTestId("data-dirty"));
      await machine(() => expect(fp.getByTestId("honest-note")).toContainText("spreadsheet"));
      note("honest note (dirty): " + (await txt(fp.getByTestId("honest-note"))));
      await shot(page, "06d-forecast-dirty", false);
      await click(fp.getByTestId("scenario-flat_noisy"));
      await machine(() => expect(fp.getByTestId("honest-note")).toContainText("flat"));
      note("honest note (flat): " + (await txt(fp.getByTestId("honest-note"))));
      await shot(page, "06e-forecast-flat", false);
      const bias = page.getByTestId("bias-block");
      note("bias note: " + (await txt(bias.getByTestId("bias-note"))));
      await bias.scrollIntoViewIfNeeded();
      await shot(page, "06f-bias", false);
      const act = page.getByTestId("actions");
      await act.scrollIntoViewIfNeeded();
      note(
        "actions: " +
          (
            await act
              .locator("li")
              .evaluateAll((els) =>
                els.map((e) => (e.textContent ?? "").replace(/\s+/g, " ").slice(0, 160)),
              )
          ).join(" || "),
      );
      await shot(page, "06g-actions", false);
    },
    "06",
  );

  // ---------------------------------------------------------------- 7. Close
  await runStep(
    "7 ops close",
    page,
    async () => {
      await click(page.getByRole("link", { name: /Ops/ }));
      const card = page.getByTestId("ops-card");
      await machine(() => expect(card.getByTestId("ops-amy")).toBeVisible());
      note("amy: " + (await txt(card.getByTestId("ops-amy"))));
      note("amy after: " + (await txt(card.getByTestId("ops-amy-after"))));
      note("ftr: " + (await txt(card.getByTestId("ops-ftr"))));
      note("dupes: " + (await txt(card.getByTestId("ops-dupes-value"))));
      await shot(page, "07-ops");
      await shot(page, "07-ops-viewport", false);
    },
    "07",
  );

  // Screens the storyline does not visit, for the theme review (1440x900 viewport).
  for (const [name, url] of [
    ["08-approvals", "/approvals"],
    ["08-requests", "/requests"],
    ["08-admin", "/admin"],
  ]) {
    await page.goto(url);
    await page.waitForLoadState("networkidle");
    await page.screenshot({ path: `${OUT}/${name}.png` });
  }

  fs.writeFileSync(OUT + "/log.json", JSON.stringify(records, null, 2));
  console.log(
    "WALKTHROUGH_LOG_START\n" + JSON.stringify(records, null, 1) + "\nWALKTHROUGH_LOG_END",
  );
  const total = records.reduce((s, r) => s + r.wallMs, 0);
  console.log(
    "REHEARSE_TIMINGS\n" +
      records
        .map(
          (r) =>
            `${r.step.padEnd(36)} ${(r.wallMs / 1000).toFixed(1)}s` + (r.failure ? "  FAIL" : ""),
        )
        .join("\n") +
      `\nTOTAL machine+scripted ${(total / 1000).toFixed(1)}s vs 150s budget (no narration pauses)`,
  );
});

test("cold regional after reset", async ({ request }) => {
  const h = { "X-Acting-User": "daniel" };
  const t0 = Date.now();
  const rs = await request.post("/api/admin/reset-demo", { headers: h });
  console.log(
    "COLD reset-demo " + rs.status() + " in " + ((Date.now() - t0) / 1000).toFixed(1) + "s",
  );
  for (const [name, url] of [
    ["regional before", "/api/analytics/regional?view=before"],
    ["regional before again", "/api/analytics/regional?view=before"],
    ["regional after", "/api/analytics/regional?view=after"],
    ["forecast", "/api/analytics/forecast"],
    ["ops", "/api/analytics/ops-impact"],
  ]) {
    const t = Date.now();
    const r = await request.get(url, { headers: h });
    console.log(
      "COLD " + name + " " + r.status() + " in " + ((Date.now() - t) / 1000).toFixed(1) + "s",
    );
  }
});
