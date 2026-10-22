/**
 * DEMO-02: the malaria kit waits on Quality/Regulatory reviewers who are not
 * among the eight personas (Joanne Yeo for Singapore, Nguyễn Thị Lan for
 * Vietnam). The presenter acts as each pending approver from the status page,
 * the header shows that person's real name, and Priya's stage opens.
 */
import { expect, test } from "@playwright/test";

import { openAs } from "./workflow-helpers";

function malariaKit(suffix: string) {
  return {
    ItemName: `Malaria Pf/Pan Antigen Rapid Test Kit ${suffix}`,
    U_IVD: "tYES",
    selling_countries: ["SG", "MY", "VN"],
    product_family: "A",
    registrations: [
      { country: "SG", reg_no: "DIV-001", expiry_date: "2030-01-10" },
      { country: "MY", reg_no: "MDA-002", expiry_date: "2030-02-01" },
      { country: "VN", reg_no: "VN-3", expiry_date: "2030-03-01" },
    ],
  };
}

test("acting as each pending approver from the status page opens Priya's stage", async ({
  page,
  request,
}) => {
  const headers = { "X-Acting-User": "amy" };
  const created = await request.post("/api/requests", {
    headers,
    data: {
      domain: "item",
      entity: "SPD",
      country: "SG",
      fields: malariaKit(String(Date.now() % 100_000)),
    },
  });
  expect(created.ok(), await created.text()).toBe(true);
  const { req_id: id } = (await created.json()) as { req_id: string };
  const submitted = await request.post(`/api/requests/${id}/submit`, { headers });
  expect(submitted.ok(), await submitted.text()).toBe(true);

  await openAs(page, "amy", `/requests/${id}`);
  const stage1 = page.getByTestId("stage-1");
  await expect(stage1.locator('[data-testid="task"][data-assignee="joanne"]')).toBeVisible();
  await expect(stage1.locator('[data-testid="task"][data-assignee="lan"]')).toBeVisible();
  await expect(page.getByTestId("qr-reason").first()).toContainText(
    "diagnostic product sold in Singapore, Malaysia and Vietnam",
  );

  // Approve every pending Stage 1 task by acting as its approver.
  for (let guard = 0; guard < 8; guard += 1) {
    const pendingCard = stage1.locator('[data-testid="task"][data-status="pending"]').first();
    if ((await pendingCard.count()) === 0) break;
    const name = (await pendingCard.locator("span.font-medium").first().textContent()) ?? "";
    const actAs = pendingCard.getByTestId("act-as");
    if ((await actAs.count()) > 0) await actAs.click();
    await expect(page.getByTestId("persona-switcher")).toContainText(name);
    if (name === "Joanne Yeo") {
      // A non-persona approver is offered in the switcher while active.
      await page.getByTestId("persona-switcher").click();
      await expect(page.getByTestId("persona-other")).toContainText("Joanne Yeo");
      await page.keyboard.press("Escape");
    }
    const yourTurn = page.getByTestId("your-turn");
    await expect(yourTurn).toBeVisible();
    await yourTurn.getByTestId("approve").click();
    await expect(
      stage1.locator(`[data-testid="task"][data-status="approved"]`).filter({ hasText: name }),
    ).toHaveCount(1);
  }

  await expect(page.getByTestId("stage-1")).toHaveAttribute("data-status", "done");
  await expect(page.getByTestId("stage-2")).toHaveAttribute("data-status", "open");
  await expect(page.getByTestId("pending-with")).toContainText("Priya");
});

test("an unknown stored person falls back visibly to Amy", async ({ page }) => {
  await openAs(page, "nobody-here", "/requests");
  await expect(page.getByTestId("persona-switcher")).toContainText("Amy");
  await expect(page.getByText("Now acting as Amy")).toBeVisible();
});
