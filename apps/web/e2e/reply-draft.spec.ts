/**
 * "Reply to sender (draft)" under the AI reading: a fixed template (no AI) that asks only for the
 * details the read found missing and links to the pre-filled form. Nothing is sent from the app.
 */
import { expect, test } from "@playwright/test";

import { keyLabel } from "../lib/emails";
import { buildReply, firstName, formUrlFor, replyText } from "../lib/reply";
import { openEmail, waitDone } from "./trace-helpers";

test.use({ permissions: ["clipboard-read", "clipboard-write"] });

test("the template lists only what is missing, or asks for a check when nothing is", () => {
  const url = formUrlFor("http://x.test", "DEMO-01");
  expect(url).toBe("http://x.test/requests/new?email=DEMO-01");
  expect(firstName("Grace Teo")).toBe("Grace");
  expect(firstName("  ")).toBeNull();

  const some = buildReply({
    senderName: "Marcus",
    missingLabels: ["Address", "Contact email"],
    formUrl: url,
  });
  expect(replyText(some)).toBe(
    [
      "Hi Marcus,",
      "",
      "Thanks for your email. We have started the request from it, but a few details are missing:",
      "- Address",
      "- Contact email",
      "",
      "Please add them in the form below. Everything else is already filled in.",
      url,
      "",
      "MDM team",
    ].join("\n"),
  );

  const none = replyText(buildReply({ senderName: null, missingLabels: [], formUrl: url }));
  expect(none.startsWith("Hello,\n")).toBe(true);
  expect(none).toContain("Please check the details in the form below");
  expect(none).not.toContain("- ");
  expect(none.endsWith(`${url}\n\nMDM team`)).toBe(true);
});

test("DEMO-01: the draft asks for the read's missing details, copies, and opens the form", async ({
  page,
}) => {
  const res = await page.request.post("/api/emails/DEMO-01/interpret", {
    headers: { "X-Acting-User": "marcus" },
  });
  expect(res.ok()).toBe(true);
  const read = (await res.json()) as { missing_fields: string[] };
  expect(read.missing_fields.length).toBeGreaterThan(0);

  const pane = await openEmail(page, "marcus", "Cho Ray", "DEMO-01", "Benh vien Cho Ray");
  await pane.getByTestId("read-with-ai").click();
  await waitDone(page);
  const reading = pane.getByTestId("ai-reading");

  // The create bar is still on screen at 1440x900 without scrolling.
  const create = reading.getByTestId("create-request");
  expect(await page.evaluate(() => window.scrollY)).toBe(0);
  const box = (await create.boundingBox())!;
  expect(box.y).toBeGreaterThanOrEqual(0);
  expect(box.y + box.height).toBeLessThanOrEqual(page.viewportSize()!.height);
  await create.click({ trial: true });

  const draft = reading.getByTestId("reply-draft");
  await expect(draft).toContainText("Reply to sender (draft)");
  await expect(draft.getByTestId("reply-text")).toContainText("Hi Marcus,");
  await expect(draft.getByTestId("reply-missing-field")).toHaveText(
    read.missing_fields.map(keyLabel),
  );
  await expect(draft.getByTestId("reply-note")).toContainText(
    "In production, Power Automate sends this from the MDM mailbox.",
  );

  const link = draft.getByTestId("reply-form-link");
  const origin = new URL(page.url()).origin;
  await expect(link).toHaveAttribute("href", `${origin}/requests/new?email=DEMO-01`);
  await expect(link).toHaveText(`${origin}/requests/new?email=DEMO-01`);

  await draft.getByTestId("copy-reply").click();
  await expect(draft.getByTestId("copy-reply")).toHaveText("Copied");
  // The Windows clipboard hands text back with CRLF line ends.
  const copied = (await page.evaluate(() => navigator.clipboard.readText())).replace(
    /\r\n/g,
    "\n",
  );
  expect(copied).toBe(
    replyText(
      buildReply({
        senderName: "Marcus",
        missingLabels: read.missing_fields.map(keyLabel),
        formUrl: `${origin}/requests/new?email=DEMO-01`,
      }),
    ),
  );

  await draft.getByTestId("open-form").click();
  await expect(page.getByTestId("prefill-note")).toContainText("New customer - Benh vien Cho Ray");
  await expect(page.getByLabel("Legal name")).toHaveValue("Benh vien Cho Ray");
});

test("an email that is not a new-record request has no reply draft", async ({ page }) => {
  const pane = await openEmail(page, "priya", "RSCM", "DEMO-03", "PO RSCM/2026/118");
  await pane.getByTestId("read-with-ai").click();
  await waitDone(page);
  await expect(pane.getByTestId("category-chip")).not.toHaveAttribute(
    "data-category",
    "mdm_request",
  );
  await expect(pane.getByTestId("reply-draft")).toHaveCount(0);
});

test("the email that gives the AI orders gets no reply draft", async ({ page }) => {
  const pane = await openEmail(
    page,
    "priya",
    "bank details update",
    "DEMO-06",
    "vendor registration and bank details update",
  );
  await pane.getByTestId("read-with-ai").click();
  await waitDone(page);
  await expect(pane.getByTestId("injection-warning")).toBeVisible();
  await expect(pane.getByTestId("reply-draft")).toHaveCount(0);
});
