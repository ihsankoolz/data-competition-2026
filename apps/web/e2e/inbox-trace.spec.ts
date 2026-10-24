/**
 * The live AI trace in the messy inbox (Stretch S1, D-023 #3). "Read this email" streams the
 * AI's reading step by step: details appear one by one with their source words lit up in the
 * email, then the type, then what is missing, and an injection warning last. A recorded replay
 * says so. Reduced motion shows the result at once; a broken stream falls back to the plain read.
 *
 * A MutationObserver in the page samples the panel on every change, so the assertions are about
 * what the browser really showed and when, not about how fast Playwright happened to poll.
 */
import { expect, type Page, test } from "@playwright/test";

import { openAs } from "./workflow-helpers";

type Sample = {
  t: number;
  state: string | null;
  fields: number;
  highlights: number;
  status: boolean;
  chip: boolean;
  injection: boolean;
  bank: boolean;
  missing: boolean;
};

const REPLAY_HELP =
  "This answer was recorded from the AI earlier, for this exact email. Replaying it makes the " +
  "demo behave the same every time, even without the internet. Every detail still comes from " +
  "words in the email.";

let consoleErrors: string[] = [];

test.beforeEach(({ page }) => {
  consoleErrors = [];
  page.on("console", (m) => {
    if (m.type() === "error") consoleErrors.push(m.text());
  });
  page.on("pageerror", (e) => consoleErrors.push("pageerror: " + e.message));
});

async function openEmail(page: Page, user: string, search: string, id: string, subject: string) {
  await openAs(page, user, "/inbox");
  await page.getByLabel("Search emails").fill(search);
  await page.getByTestId(`inbox-${id}`).click();
  const pane = page.getByTestId("email-pane");
  await expect(pane).toContainText(subject);
  return pane;
}

/** Starts sampling the email pane on every DOM change. */
async function record(page: Page) {
  await page.evaluate(() => {
    const pane = document.querySelector('[data-testid="email-pane"]')!;
    const w = window as unknown as { __samples: unknown[] };
    w.__samples = [];
    const take = () => {
      const aside = pane.querySelector('[data-testid="ai-reading"]');
      w.__samples.push({
        t: performance.now(),
        state: aside?.getAttribute("data-trace-state") ?? null,
        fields: pane.querySelectorAll('[data-testid="extracted-fields"] > li').length,
        highlights: pane.querySelectorAll('[data-testid="quote-highlight"]').length,
        status: !!pane.querySelector('[data-testid="trace-status"]'),
        chip: !!aside?.querySelector('[data-testid="category-chip"]'),
        injection: !!pane.querySelector('[data-testid="injection-warning"]'),
        bank: !!pane.querySelector('[data-testid="bank-stripped"]'),
        missing: !!pane.querySelector('[data-testid="missing-fields"]'),
      });
    };
    new MutationObserver(take).observe(pane, {
      subtree: true,
      childList: true,
      attributes: true,
      characterData: true,
    });
  });
}

const samples = (page: Page) =>
  page.evaluate(() => (window as unknown as { __samples: Sample[] }).__samples);

async function waitDone(page: Page) {
  await expect(page.getByTestId("ai-reading")).toHaveAttribute("data-trace-state", "done");
}

test("DEMO-01: details appear one by one with their words lit up, then the type", async ({
  page,
}) => {
  const pane = await openEmail(page, "marcus", "Cho Ray", "DEMO-01", "Benh vien Cho Ray");
  await record(page);
  await pane.getByTestId("read-with-ai").click();
  await expect(pane.getByTestId("trace-status")).toHaveText("The AI is reading this email…");
  await expect(pane.getByTestId("ai-reading")).toHaveAttribute("aria-busy", "true");
  await waitDone(page);
  await expect(pane.getByTestId("ai-reading")).not.toHaveAttribute("aria-busy", "true");
  await expect(pane.getByTestId("trace-status")).toHaveCount(0);

  const s = await samples(page);
  const total = s.at(-1)!.fields;
  expect(total).toBeGreaterThanOrEqual(3);
  // A moment mid-stream: the status line showing and only some of the details out.
  const mid = s.filter((x) => x.status && x.fields >= 1 && x.fields <= total - 1);
  expect(mid.length).toBeGreaterThan(0);
  // The type arrives only after every detail is out.
  expect(s.filter((x) => x.chip && x.state === "streaming").every((x) => x.fields === total)).toBe(
    true,
  );
  // Only revealed quotes are lit, so the highlight count grows while streaming and never shrinks.
  const streaming = s.filter((x) => x.state === "streaming");
  const lit = streaming.map((x) => x.highlights);
  expect(Math.max(...lit)).toBeGreaterThan(Math.min(...lit));
  for (let i = 1; i < lit.length; i++) expect(lit[i]).toBeGreaterThanOrEqual(lit[i - 1]!);
  // Streamed, not buffered: the first detail and the end are well apart in the browser.
  const first = s.find((x) => x.fields >= 1)!;
  const done = s.find((x) => x.state === "done")!;
  const spread = done.t - first.t;
  console.log(`DEMO-01 trace: first detail to done ${Math.round(spread)} ms, ${total} details`);
  expect(spread).toBeGreaterThan(800);

  const reading = pane.getByTestId("ai-reading");
  await expect(reading.getByTestId("category-chip")).toHaveAttribute("data-category", "mdm_request");
  await expect(reading.getByTestId("confidence")).toContainText("% sure");
  await expect(pane.getByTestId("email-body").getByTestId("quote-highlight").first()).toBeVisible();
  // The finished read is stored like any other: the list row shows its type too.
  await expect(page.getByTestId("inbox-DEMO-01").getByTestId("category-chip")).toBeVisible();
  await reading.getByTestId("create-request").click();
  await expect(page.getByLabel("Legal name")).toHaveValue("Benh vien Cho Ray");
  expect(consoleErrors).toEqual([]);
});

test("DEMO-06: the hidden-instructions warning comes last, after the type", async ({ page }) => {
  const pane = await openEmail(page, "priya", "bank details update", "DEMO-06", "");
  await record(page);
  await pane.getByTestId("read-with-ai").click();
  await waitDone(page);
  await expect(pane.getByTestId("injection-warning")).toContainText("Possible hidden instructions");
  await expect(pane.getByTestId("needs-review")).toBeVisible();

  const s = await samples(page);
  const firstChip = s.findIndex((x) => x.chip);
  const firstWarning = s.findIndex((x) => x.injection);
  expect(firstChip).toBeGreaterThanOrEqual(0);
  expect(firstWarning).toBeGreaterThan(firstChip);
  expect(s[firstChip]!.injection).toBe(false);
  expect(consoleErrors).toEqual([]);
});

test("DEMO-07: the bank-details notice shows as soon as the AI starts", async ({ page }) => {
  const pane = await openEmail(page, "weijie", "Precision", "DEMO-07", "Precision Diagnostics");
  await record(page);
  await pane.getByTestId("read-with-ai").click();
  await waitDone(page);
  await expect(pane.getByTestId("bank-stripped")).toContainText(
    "Bank details in this email were removed before the AI read it.",
  );
  const s = await samples(page);
  // Shown while streaming, before the first detail.
  expect(s.some((x) => x.state === "streaming" && x.bank && x.fields === 0)).toBe(true);
  expect(consoleErrors).toEqual([]);
});

test("a recorded answer says so, and can be watched again", async ({ page }) => {
  const pane = await openEmail(page, "marcus", "Cho Ray", "DEMO-01", "Benh vien Cho Ray");
  await pane.getByTestId("read-with-ai").click();
  const badge = pane.getByTestId("replay-badge");
  await expect(badge).toHaveText("Replaying a recorded AI response");
  await waitDone(page);
  await expect(badge).toBeVisible();
  await badge.hover();
  await expect(page.getByRole("tooltip")).toHaveText(REPLAY_HELP);

  await record(page);
  await pane.getByTestId("replay-trace").click();
  await expect(pane.getByTestId("ai-reading")).toHaveAttribute("data-trace-state", "streaming");
  await waitDone(page);
  const s = await samples(page);
  expect(s.some((x) => x.state === "streaming" && x.status)).toBe(true);
  await expect(badge).toBeVisible();
  await expect(pane.getByTestId("create-request")).toBeVisible();

  // The badge stays with the email: open another one and come back.
  await page.getByLabel("Search emails").fill("Precision");
  await page.getByTestId("inbox-DEMO-07").click();
  await expect(pane).toContainText("Precision Diagnostics");
  await expect(pane.getByTestId("replay-badge")).toHaveCount(0);
  await page.getByLabel("Search emails").fill("Cho Ray");
  await page.getByTestId("inbox-DEMO-01").click();
  await expect(pane.getByTestId("replay-badge")).toBeVisible();
  expect(consoleErrors).toEqual([]);
});

test("reduced motion: the whole read shows at once, with no streaming phase", async ({ page }) => {
  await page.emulateMedia({ reducedMotion: "reduce" });
  const pane = await openEmail(page, "marcus", "Cho Ray", "DEMO-01", "Benh vien Cho Ray");
  await record(page);
  const req = page.waitForRequest((r) => r.url().includes("/interpret/stream"));
  await pane.getByTestId("read-with-ai").click();
  expect(new URL((await req).url()).searchParams.get("step_ms")).toBe("0");
  await waitDone(page);
  await expect(pane.getByTestId("category-chip")).toBeVisible();
  await expect(pane.getByTestId("extracted-fields")).not.toBeEmpty();
  const s = await samples(page);
  expect(s.some((x) => x.state === "streaming" || x.status)).toBe(false);
  expect(consoleErrors).toEqual([]);
});

test("if the stream breaks, the plain read still shows the result", async ({ page }) => {
  await page.route("**/interpret/stream**", (route) =>
    route.fulfill({ status: 500, contentType: "text/plain", body: "stream broke" }),
  );
  const pane = await openEmail(page, "marcus", "Cho Ray", "DEMO-01", "Benh vien Cho Ray");
  const plain = page.waitForResponse(
    (r) => r.url().endsWith("/interpret") && r.request().method() === "POST",
  );
  await pane.getByTestId("read-with-ai").click();
  expect((await plain).status()).toBe(200);
  await waitDone(page);
  await expect(pane.getByTestId("category-chip")).toHaveAttribute("data-category", "mdm_request");
  await expect(pane.getByTestId("create-request")).toBeVisible();
  await expect(pane.getByTestId("replay-badge")).toHaveCount(0);
  // The browser itself logs the 500; nothing else may fail.
  expect(consoleErrors.filter((e) => !e.includes("500"))).toEqual([]);
});
