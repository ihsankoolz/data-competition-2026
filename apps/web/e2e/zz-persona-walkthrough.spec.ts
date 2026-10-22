import { expect, test, type Page } from "@playwright/test";
import { actAs, openAs } from "./workflow-helpers";

const OUT = "C:/Users/ihsan/.claude/jobs/dbc79bcd/tmp/persona";
const errors: string[] = [];
const timings: string[] = [];
let t0 = Date.now();
function mark(name: string) {
  timings.push(`${name}: ${((Date.now() - t0) / 1000).toFixed(1)}s`);
  t0 = Date.now();
}
async function shot(page: Page, name: string) {
  await page.waitForTimeout(400);
  await page.screenshot({ path: `${OUT}/${name}.png`, fullPage: true });
}

test("persona walkthrough", async ({ page, request }) => {
  test.setTimeout(600_000);
  page.on("console", (m) => {
    if (m.type() === "error" || m.type() === "warning") errors.push(`[console.${m.type()}] ${m.text()} @ ${page.url()}`);
  });
  page.on("pageerror", (e) => errors.push(`[pageerror] ${e.message}`));
  page.on("requestfailed", (r) => errors.push(`[requestfailed] ${r.method()} ${r.url()} ${r.failure()?.errorText}`));
  page.on("response", (r) => {
    if (r.status() >= 400) errors.push(`[http ${r.status()}] ${r.request().method()} ${r.url()} @ ${page.url()}`);
  });

  await request.post("/api/admin/reset-demo", { headers: { "X-Acting-User": "priya" } });

  // Beat 1
  await openAs(page, "marcus", "/inbox");
  await expect(page.getByTestId("email-list").locator("li").first()).toBeVisible();
  await shot(page, "1a-inbox");
  console.log("INBOX TEXT:", (await page.locator("main").innerText()).slice(0, 800));
  await page.getByTestId("sort-all").click();
  await expect(page.getByTestId("sort-all")).toHaveText(/All emails sorted/, { timeout: 60_000 });
  mark("1 sort all");
  await shot(page, "1b-sorted");
  await page.getByLabel("Search emails").fill("Cho Ray");
  await page.getByTestId("inbox-DEMO-01").click();
  await shot(page, "1c-demo01-open");
  await page.getByTestId("read-with-ai").click();
  await expect(page.getByTestId("ai-reading").getByTestId("category-chip")).toBeVisible();
  await shot(page, "1d-demo01-read");
  mark("1 open+read DEMO-01");
  await page.getByLabel("Search emails").fill("bank details update");
  await page.getByTestId("inbox-DEMO-06").click();
  await page.getByTestId("read-with-ai").click();
  await expect(page.getByTestId("injection-warning")).toBeVisible();
  await shot(page, "1e-demo06-flagged");
  mark("1 DEMO-06");

  // Beat 2: Marcus
  await page.getByLabel("Search emails").fill("Cho Ray");
  await page.getByTestId("inbox-DEMO-01").click();
  await page.getByTestId("read-with-ai").click();
  await page.getByTestId("create-request").click();
  await expect(page.getByTestId("prefill-note")).toBeVisible();
  await shot(page, "2a-marcus-prefilled");
  const panel = page.getByTestId("dup-panel");
  await expect(panel.getByTestId("verdict")).toHaveAttribute("data-verdict", "likely", { timeout: 20_000 });
  await shot(page, "2b-marcus-dup-panel");
  console.log("DUP PANEL:", await panel.innerText());
  await panel.getByTestId("link-C00084").click();
  await expect(panel.getByTestId("linked")).toBeVisible();
  await shot(page, "2c-marcus-linked");
  await page.getByRole("link", { name: "See the request" }).click();
  await expect(page.getByTestId("request-state")).toHaveAttribute("data-state", "LINKED_TO_EXISTING");
  await shot(page, "2d-marcus-status-linked");
  console.log("LINKED STATUS:", await page.locator("main").innerText());
  mark("2 Marcus");

  console.log("ERRORS:", JSON.stringify(errors, null, 1));
  console.log("TIMINGS:", timings.join(" | "));
});
