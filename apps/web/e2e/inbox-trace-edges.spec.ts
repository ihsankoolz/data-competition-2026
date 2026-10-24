/**
 * The live AI trace's edges (D-023 #3, QA notes): keyboard focus, a stream that goes quiet, a
 * stream cut short, a last step without its closing blank line, switching email mid-trace,
 * bank details as the only thing found, reduced motion, and nothing on the page moving when
 * the first read lands.
 */
import { expect, type Page, type Route, test } from "@playwright/test";

import { openEmail, record, samples, waitDone } from "./trace-helpers";
import { openAs } from "./workflow-helpers";

let consoleErrors: string[] = [];

test.beforeEach(({ page }) => {
  consoleErrors = [];
  page.on("console", (m) => {
    if (m.type() === "error") consoleErrors.push(m.text());
  });
  page.on("pageerror", (e) => consoleErrors.push("pageerror: " + e.message));
});

type Frame = { kind: string; [k: string]: unknown };

/** The real trace for an email, all at once, as its list of steps. */
async function realSteps(page: Page, id: string, user: string): Promise<Frame[]> {
  const res = await page.request.post(`/api/emails/${id}/interpret/stream?step_ms=0`, {
    headers: { "X-Acting-User": user },
  });
  expect(res.ok()).toBe(true);
  return (await res.text())
    .split("\n\n")
    .filter((f) => f.trim())
    .map(
      (f) =>
        JSON.parse(
          f
            .split("\n")
            .find((l) => l.startsWith("data: "))!
            .slice(6),
        ) as Frame,
    );
}

const sse = (steps: Frame[]) =>
  steps.map((s) => "event: step\ndata: " + JSON.stringify(s) + "\n\n").join("");

const fulfillWith = (body: string) => (route: Route) =>
  route.fulfill({ status: 200, contentType: "text/event-stream", body });

/** Every plain (unstreamed) read the page asks for. */
function plainReads(page: Page): string[] {
  const seen: string[] = [];
  page.on("request", (r) => {
    if (r.method() === "POST" && /\/interpret$/.test(new URL(r.url()).pathname)) seen.push(r.url());
  });
  return seen;
}

async function shortStall(page: Page, ms: number) {
  await page.addInitScript((n) => {
    (window as unknown as { __traceStallMs: number }).__traceStallMs = n;
  }, ms);
}

test("keyboard: after Read this email and Watch again, focus lands on what the AI read", async ({
  page,
}) => {
  const pane = await openEmail(page, "marcus", "Cho Ray", "DEMO-01", "Benh vien Cho Ray");
  const reading = pane.getByTestId("ai-reading");
  await pane.getByTestId("read-with-ai").focus();
  await page.keyboard.press("Enter");
  await expect(reading).toBeFocused();
  await waitDone(page);
  await expect(reading).toBeFocused();

  await pane.getByTestId("replay-trace").focus();
  await page.keyboard.press("Enter");
  await expect(reading).toHaveAttribute("data-trace-state", "streaming");
  await expect(reading).toBeFocused();
  await waitDone(page);
  await expect(reading).toBeFocused();
  // Tab moves on from the reading into its contents, not back to the top of the page.
  await page.keyboard.press("Tab");
  expect(
    await page.evaluate(
      () =>
        !!document.activeElement?.closest('[data-testid="ai-reading"]') &&
        document.activeElement !== document.body,
    ),
  ).toBe(true);
  expect(consoleErrors).toEqual([]);
});

test("a stream that never sends its first step falls back to the plain read", async ({ page }) => {
  await shortStall(page, 400);
  let release = () => {};
  const held = new Promise<void>((r) => (release = r));
  await page.route("**/interpret/stream**", async (route) => {
    await held; // says nothing until the test ends
    await route.abort().catch(() => {});
  });
  const plain = plainReads(page);
  const pane = await openEmail(page, "marcus", "Cho Ray", "DEMO-01", "Benh vien Cho Ray");
  const t0 = Date.now();
  await pane.getByTestId("read-with-ai").click();
  await waitDone(page);
  const took = Date.now() - t0;
  expect(plain).toHaveLength(1);
  expect(took).toBeGreaterThanOrEqual(400);
  expect(took).toBeLessThan(5_000);
  await expect(pane.getByTestId("category-chip")).toHaveAttribute("data-category", "mdm_request");
  await expect(pane.getByTestId("create-request")).toBeVisible();
  await expect(pane.getByTestId("replay-badge")).toHaveCount(0);
  release();
  expect(consoleErrors).toEqual([]);
});

test("a stream that goes quiet between steps falls back to the plain read", async ({ page }) => {
  // The server pauses 500 ms before each step; anything over 300 ms counts as stalled here.
  await shortStall(page, 300);
  await page.route("**/interpret/stream**", (route) => {
    const url = new URL(route.request().url());
    url.searchParams.set("step_ms", "500");
    return route.continue({ url: url.toString() });
  });
  const plain = plainReads(page);
  const pane = await openEmail(page, "marcus", "Cho Ray", "DEMO-01", "Benh vien Cho Ray");
  await record(page);
  await pane.getByTestId("read-with-ai").click();
  await waitDone(page);
  expect(plain).toHaveLength(1);
  const s = await samples(page);
  // The first step did arrive (the line names the recorded replay) before it went quiet.
  expect(
    s.some((x) => x.state === "streaming" && x.statusText === "Showing what the AI read…"),
  ).toBe(true);
  await expect(pane.getByTestId("category-chip")).toHaveAttribute("data-category", "mdm_request");
  await expect(pane.getByTestId("extracted-fields").locator("li").first()).toBeVisible();
  expect(consoleErrors).toEqual([]);
});

test("a stream cut off before the end falls back to the plain read", async ({ page }) => {
  const plain = plainReads(page);
  await openAs(page, "marcus", "/inbox");
  const steps = await realSteps(page, "DEMO-01", "marcus");
  expect(steps.at(-1)!.kind).toBe("done");
  const total = steps.filter((s) => s.kind === "field").length;
  await page.route("**/interpret/stream**", fulfillWith(sse(steps.slice(0, -1))));
  await page.getByLabel("Search emails").fill("Cho Ray");
  await page.getByTestId("inbox-DEMO-01").click();
  const pane = page.getByTestId("email-pane");
  await pane.getByTestId("read-with-ai").click();
  await waitDone(page);
  expect(plain).toHaveLength(1);
  await expect(pane.getByTestId("extracted-fields").locator("li")).toHaveCount(total);
  await expect(pane.getByTestId("create-request")).toBeVisible();
  expect(consoleErrors).toEqual([]);
});

test("a last step without its closing blank line still finishes the read", async ({ page }) => {
  const plain = plainReads(page);
  await openAs(page, "marcus", "/inbox");
  const steps = await realSteps(page, "DEMO-01", "marcus");
  await page.route("**/interpret/stream**", fulfillWith(sse(steps).replace(/\n+$/, "")));
  await page.getByLabel("Search emails").fill("Cho Ray");
  await page.getByTestId("inbox-DEMO-01").click();
  const pane = page.getByTestId("email-pane");
  await pane.getByTestId("read-with-ai").click();
  await waitDone(page);
  expect(plain).toEqual([]);
  // Streamed, so the badge for the recorded replay shows.
  await expect(pane.getByTestId("replay-badge")).toBeVisible();
  await expect(pane.getByTestId("create-request")).toBeVisible();
  expect(consoleErrors).toEqual([]);
});

test("switching email mid-trace: nothing from the first email shows on the second", async ({
  page,
}) => {
  await openAs(page, "marcus", "/inbox");
  await page.getByTestId("inbox-DEMO-01").click();
  const pane = page.getByTestId("email-pane");
  await expect(pane).toContainText("Benh vien Cho Ray");
  await record(page);
  const aborted = page.waitForEvent("requestfailed", (r) => r.url().includes("/interpret/stream"));
  await pane.getByTestId("read-with-ai").click();
  await page.waitForFunction(
    () => document.querySelectorAll('[data-testid="extracted-fields"] > li').length >= 1,
  );
  await page.getByTestId("inbox-DEMO-07").click();
  await expect(pane).toContainText("Precision Diagnostics");
  await aborted; // the first email's stream was stopped, not left running
  // Longer than the rest of DEMO-01's trace would have taken.
  await page.waitForTimeout(2_000);

  const onSecond = (await samples(page)).filter((x) => x.subject.includes("Precision"));
  expect(onSecond.length).toBeGreaterThan(0);
  for (const x of onSecond) {
    expect(x.fields).toBe(0);
    expect(x.highlights).toBe(0);
    expect(x.status).toBe(false);
    expect(x.chip).toBe(false);
    expect(x.state).toBeNull();
  }
  await expect(pane.getByTestId("read-with-ai")).toBeVisible();
  // The stopped read was not kept: DEMO-01 has no type in the list.
  await expect(page.getByTestId("inbox-DEMO-01").getByTestId("category-chip")).toHaveCount(0);

  // The second email reads normally, with only its own details.
  await pane.getByTestId("read-with-ai").click();
  await waitDone(page);
  await expect(pane.getByTestId("extracted-fields")).not.toContainText("Cho Ray");
  await expect(pane.getByTestId("bank-stripped")).toBeVisible();
  expect(consoleErrors).toEqual([]);
});

test("bank details as the only thing found: the heading stays and says what is there", async ({
  page,
}) => {
  await openAs(page, "weijie", "/inbox");
  const steps = (await realSteps(page, "DEMO-07", "weijie"))
    .filter((s) => s.kind !== "field" && s.kind !== "line")
    .map((s) =>
      s.kind === "done"
        ? {
            ...s,
            interpretation: {
              ...(s.interpretation as Record<string, unknown>),
              fields: [],
              lines: [],
            },
          }
        : s,
    );
  expect(steps.some((s) => s.kind === "bank_stripped")).toBe(true);
  await page.route("**/interpret/stream**", fulfillWith(sse(steps)));
  await page.getByLabel("Search emails").fill("Precision");
  await page.getByTestId("inbox-DEMO-07").click();
  const pane = page.getByTestId("email-pane");
  await expect(pane).toContainText("Precision Diagnostics");
  await record(page);
  await pane.getByTestId("read-with-ai").click();
  await waitDone(page);

  const reading = pane.getByTestId("ai-reading");
  await expect(reading.getByRole("heading", { name: "Details found" })).toBeVisible();
  await expect(reading.getByTestId("bank-stripped")).toBeVisible();
  await expect(reading.getByTestId("no-other-details")).toHaveText(
    "No other details were found in this email.",
  );
  await expect(reading.getByTestId("extracted-fields").locator("li")).toHaveCount(0);
  // Once the heading is up it never drops out (no jump at the end).
  const s = await samples(page);
  const first = s.findIndex((x) => x.heading);
  expect(first).toBeGreaterThanOrEqual(0);
  expect(s.slice(first).every((x) => x.heading)).toBe(true);
  expect(consoleErrors).toEqual([]);
});

test("reduced motion: no fading highlights and no smooth scrolling", async ({ page }) => {
  await page.emulateMedia({ reducedMotion: "reduce" });
  await page.addInitScript(() => {
    const w = window as unknown as { __scrolls: unknown[] };
    w.__scrolls = [];
    Element.prototype.scrollIntoView = function (arg?: boolean | ScrollIntoViewOptions) {
      w.__scrolls.push(arg);
    };
  });
  const pane = await openEmail(page, "marcus", "Cho Ray", "DEMO-01", "Benh vien Cho Ray");
  await pane.getByTestId("read-with-ai").click();
  await waitDone(page);
  await pane.getByTestId("extracted-fields").locator("li button").first().hover();
  const scrolls = await page.evaluate(
    () => (window as unknown as { __scrolls: { behavior?: string }[] }).__scrolls,
  );
  expect(scrolls.length).toBeGreaterThan(0);
  expect(scrolls.every((a) => a.behavior !== "smooth")).toBe(true);
  const duration = await pane
    .getByTestId("quote-highlight")
    .first()
    .evaluate((el) => getComputedStyle(el).transitionDuration);
  // The global reduced-motion rule shortens every transition to next to nothing.
  expect(parseFloat(duration)).toBeLessThan(0.01);
  expect(consoleErrors).toEqual([]);
});

test("at 1440x900 nothing moves when the first read lands, and the page does not scroll", async ({
  page,
}) => {
  await openAs(page, "marcus", "/inbox");
  const list = page.getByTestId("email-list");
  await expect(list.locator("li").first()).toBeVisible();
  // The list's scroll box, not the list itself (that moves when the list scrolls).
  const box = list.locator("xpath=..");
  const listTop = async () => (await box.boundingBox())!.y;
  // The inbox (title, type filter, search, list) fits the screen, and the page never scrolls
  // by itself while the AI reads. A long reading may run below the fold; the visitor scrolls.
  const fits = async () => {
    const b = (await box.boundingBox())!;
    expect(b.y + b.height).toBeLessThanOrEqual(page.viewportSize()!.height);
    expect(await page.evaluate(() => window.scrollY)).toBe(0);
  };

  const before = await listTop();
  await fits();
  await page.getByTestId("inbox-DEMO-01").click();
  const pane = page.getByTestId("email-pane");
  await pane.getByTestId("read-with-ai").click();
  await page.waitForFunction(
    () => document.querySelectorAll('[data-testid="extracted-fields"] > li').length >= 2,
  );
  expect(await listTop()).toBe(before);
  await fits();
  await waitDone(page);
  await expect(page.getByTestId("category-filter")).toBeVisible();
  expect(await listTop()).toBe(before);
  await fits();
  expect(consoleErrors).toEqual([]);
});
