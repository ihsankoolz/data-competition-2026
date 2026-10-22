/**
 * DEMO-01 against the real backend (no stubs): Marcus, QTG Vietnam, asks for
 * "Benh vien Cho Ray". The duplicate check finds SPD's Bệnh viện Chợ Rẫy
 * (C00084, same MST) and he links to it, so no approver ever sees it.
 *
 * Needs /dedup/check, /requests and /requests/{id}/dedup-decision built.
 */
import { expect, type Page, test } from "@playwright/test";

async function openAsMarcus(page: Page) {
  await page.addInitScript(() => window.localStorage.setItem("lives-mdm.acting-user", "marcus"));
  await page.goto("/requests/new");
  await expect(page.getByTestId("persona-switcher")).toContainText("Marcus");
  await expect(page.locator("#ctx-country")).toHaveText(/Vietnam/);
  await expect(page.getByLabel("Legal name")).toBeVisible();
}

async function expectLikelyChoRay(page: Page) {
  const panel = page.getByTestId("dup-panel");
  await expect(panel.getByTestId("verdict")).toHaveAttribute("data-verdict", "likely", {
    timeout: 20_000,
  });
  const candidate = panel.getByTestId("candidate").filter({ hasText: "C00084" });
  await expect(candidate).toContainText("Bệnh viện Chợ Rẫy");
  await expect(
    candidate.getByTestId("comparison").getByRole("row", { name: /Tax ID/ }),
  ).toHaveAttribute("data-match", "true");
  await expect(candidate.getByTestId("reasons")).not.toBeEmpty();
  await expect(page.getByTestId("submit")).toBeDisabled();
  return { panel, candidate };
}

test("DEMO-01: typed request is caught as a likely duplicate and linked", async ({ page }) => {
  await openAsMarcus(page);
  await page.getByLabel("Legal name").fill("Benh vien Cho Ray");
  await page.getByLabel("Tax ID").fill("0301234567");

  const { panel, candidate } = await expectLikelyChoRay(page);
  await candidate.getByTestId("link-C00084").click();

  await expect(panel.getByTestId("linked")).toContainText("Linked to C00084.");
  await expect(panel.getByTestId("linked")).toContainText(
    "the duplicate never reached an approver",
  );

  await page.getByRole("link", { name: "See the request" }).click();
  await expect(page.getByTestId("request-state")).toHaveAttribute(
    "data-state",
    "LINKED_TO_EXISTING",
  );
});

test("DEMO-01 from the email: pre-filled with source quotes, then caught", async ({ page }) => {
  await openAsMarcus(page);
  await page.getByTestId("create-from-email").click();
  await page.getByRole("dialog").getByLabel("Search emails").fill("Cho Ray");
  await page.getByTestId("email-DEMO-01").click();

  await expect(page.getByTestId("prefill-note")).toContainText("New customer - Benh vien Cho Ray");
  await expect(page.getByLabel("Legal name")).toHaveValue("Benh vien Cho Ray");
  await expect(page.getByTestId("field-CardName").getByTestId("quote")).toContainText(
    "Benh vien Cho Ray",
  );
  await expect(page.getByLabel("Tax ID")).toHaveValue("0301234567");

  await expectLikelyChoRay(page);
});
