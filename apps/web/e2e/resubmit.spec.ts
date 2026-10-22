/**
 * Edit and resubmit (D-020 #3). Mei Ling asks Amy a question on the real
 * backend; Amy's status page shows that question above her request, she edits a
 * field and presses Resubmit (PATCH changed fields, then POST submit).
 *
 * The question block (`info_request`) and the resubmit answers are stubbed, so
 * the spec runs whether or not the backend has landed them yet.
 */
import { expect, type Page, test } from "@playwright/test";

import { openAs, submittedCustomer, taskFor } from "./workflow-helpers";

const QUESTION = "Please add the billing contact's phone number.";

async function askedForInfo(page: Page, name: string) {
  const detail = await submittedCustomer(page.request, name);
  const task = taskFor(detail, "meiling");
  const res = await page.request.post(`/api/approvals/${task.task_id}/decision`, {
    headers: { "X-Acting-User": "meiling" },
    data: { action: "ask_info", comment: QUESTION },
  });
  expect(res.ok(), await res.text()).toBe(true);
  return { id: detail.req_id, taskId: task.task_id };
}

/** Adds `info_request` to the request detail when the backend does not send it yet. */
async function stubQuestion(page: Page, id: string, taskId: string) {
  await page.route(`**/api/requests/${id}`, async (route) => {
    if (route.request().method() !== "GET") return route.fallback();
    const res = await route.fetch();
    const body = (await res.json()) as Record<string, unknown>;
    body.info_request ??= {
      task_id: taskId,
      asked_by_user_id: "meiling",
      asked_by_name: "Mei Ling",
      role: "business_support",
      question: QUESTION,
      asked_at: "2026-10-05T02:00:00Z",
    };
    // The backend allows the duplicate decision while INFO_REQUESTED (customer / vendor).
    const actions = (body.allowed_actions as string[] | undefined) ?? [];
    if (!actions.includes("decide_duplicate"))
      body.allowed_actions = [...actions, "decide_duplicate"];
    await route.fulfill({ response: res, json: body });
  });
}

test("the requestor sees the question, edits a field and resubmits", async ({ page }) => {
  const { id, taskId } = await askedForInfo(page, "Quillon Resubmit Medical Pte Ltd");
  await stubQuestion(page, id, taskId);

  let patched: unknown = null;
  let submitted = false;
  await page.route(`**/api/requests/${id}`, async (route) => {
    if (route.request().method() !== "PATCH") return route.fallback();
    patched = route.request().postDataJSON();
    await route.fulfill({ json: { req_id: id, state: "INFO_REQUESTED", issues: [] } });
  });
  // Stubbed: the backend's resubmit rules are being built in parallel (D-020 #3).
  await page.route(`**/api/requests/${id}/submit`, async (route) => {
    submitted = true;
    await route.fulfill({ json: { req_id: id, state: "IN_APPROVAL" } });
  });

  await openAs(page, "amy", `/requests/${id}`);
  const form = page.getByTestId("resubmit-form");
  await expect(form.getByTestId("info-question")).toHaveText(QUESTION);
  await expect(form).toContainText("Mei Ling");
  await expect(form.getByTestId("resubmit-dup-panel")).toBeVisible();
  await expect(form.getByTestId("finance-note")).toHaveText(
    "Changing bank details or credit terms sends the request back to Finance.",
  );

  await form.getByLabel("City").fill("Singapore 159836");
  await form.getByTestId("resubmit").click();

  await expect(page.getByText("Sent back to Mei Ling")).toBeVisible();
  expect(patched).toEqual({ fields: { City: "Singapore 159836" } });
  expect(submitted).toBe(true);
});

test("a resubmit the server refuses shows the problem next to the field", async ({ page }) => {
  const { id, taskId } = await askedForInfo(page, "Quillon Refused Resubmit Pte Ltd");
  await stubQuestion(page, id, taskId);
  await page.route(`**/api/requests/${id}/submit`, (route) =>
    route.fulfill({
      status: 422,
      json: {
        detail: "1 field needs attention before this can be submitted.",
        issues: [
          {
            field: "Phone1",
            label: "Phone",
            kind: "missing",
            message: "Add a phone number: the approver asked for it.",
          },
        ],
      },
    }),
  );

  await openAs(page, "amy", `/requests/${id}`);
  const form = page.getByTestId("resubmit-form");
  await expect(form.getByTestId("info-question")).toBeVisible();
  await form.getByTestId("resubmit").click();
  await expect(form.getByTestId("resubmit-error")).toContainText("1 field needs attention");
  await expect(form.getByTestId("field-Phone1").getByTestId("field-issue")).toHaveText(
    "Add a phone number: the approver asked for it.",
  );
});
