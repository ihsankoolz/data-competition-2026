/**
 * README screenshots of the session-12 screens (1440x900): Start here, the reply draft, the
 * approval-rules editor and the clean-up queue. Not a test of behaviour: `make readme-shots`
 * runs it with README_SHOTS=1; `make e2e` skips it (see playwright.config.ts). Shots go to
 * docs/img/screens/.
 */
import path from "node:path";

import { expect, type Page, test } from "@playwright/test";

const OUT = path.join(__dirname, "..", "..", "..", "docs", "img", "screens");

async function open(page: Page, user: string, url: string) {
  await page.addInitScript((u) => window.localStorage.setItem("lives-mdm.acting-user", u), user);
  await page.goto(url);
}

async function shot(page: Page, name: string) {
  await page.mouse.move(0, 899);
  await page.evaluate(() => document.fonts.ready);
  await page.waitForTimeout(400);
  await page.screenshot({ path: path.join(OUT, `${name}.png`) });
}

test.beforeEach(async ({ request }) => {
  const r = await request.post("/api/admin/reset-demo", { headers: { "X-Acting-User": "amy" } });
  expect(r.ok()).toBeTruthy();
});

test("Start here", async ({ page }) => {
  await open(page, "marcus", "/");
  await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
  await page.waitForLoadState("networkidle");
  await shot(page, "05-start-here");
});

test("Reply to sender (draft)", async ({ page }) => {
  await open(page, "marcus", "/inbox");
  await page.getByTestId("inbox-DEMO-01").click();
  const pane = page.getByTestId("email-pane");
  const read = pane.getByTestId("read-with-ai");
  if (await read.isVisible()) await read.click();
  await expect(pane.getByTestId("reply-draft")).toBeVisible({ timeout: 20_000 });
  // Scroll to the end of the reading panel: the sticky create bar settles below the draft.
  await pane.evaluate((el) =>
    window.scrollTo(0, el.getBoundingClientRect().bottom + window.scrollY - window.innerHeight + 24),
  );
  await shot(page, "06-reply-draft");
});

test("Clean-up queue", async ({ page }) => {
  await open(page, "priya", "/cleanup");
  await expect(page.getByTestId("cleanup-reasons").first()).toBeVisible({ timeout: 20_000 });
  await shot(page, "08-cleanup-queue");
});

test("Approval rules editor", async ({ page }) => {
  await open(page, "priya", "/admin");
  await expect(page.getByTestId("rule-step")).toHaveCount(3, { timeout: 20_000 });
  await page.getByTestId("add-step-role").selectOption("quality_regulatory");
  await page.getByTestId("add-step-person").selectOption("lan");
  await page.getByTestId("add-step").click();
  await expect(page.getByTestId("rule-preview").getByTestId("preview-task")).toHaveCount(5);
  await page.getByTestId("rules-editor").evaluate((el) => {
    const header = document.querySelector("header")?.getBoundingClientRect().height ?? 0;
    window.scrollTo(0, el.getBoundingClientRect().top + window.scrollY - header - 16);
  });
  await shot(page, "07-rules-editor");
});
