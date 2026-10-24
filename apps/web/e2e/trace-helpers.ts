/** Shared by the live AI trace specs (D-023 #3): open an email and sample the panel as it changes. */
import { expect, type Page } from "@playwright/test";

import { openAs } from "./workflow-helpers";

export type Sample = {
  t: number;
  state: string | null;
  fields: number;
  highlights: number;
  status: boolean;
  /** The words of the live status line under the reading ("" when it is not showing). */
  statusText: string;
  chip: boolean;
  injection: boolean;
  bank: boolean;
  missing: boolean;
  /** The "Details found" heading is showing. */
  heading: boolean;
  /** The subject of the email in the pane, so a sample can be tied to its email. */
  subject: string;
  /** The extracted details' text, to catch details from one email showing on another. */
  fieldText: string;
};

export async function openEmail(
  page: Page,
  user: string,
  search: string,
  id: string,
  subject: string,
) {
  await openAs(page, user, "/inbox");
  await page.getByLabel("Search emails").fill(search);
  await page.getByTestId(`inbox-${id}`).click();
  const pane = page.getByTestId("email-pane");
  await expect(pane).toContainText(subject);
  return pane;
}

/**
 * Starts sampling the email pane on every DOM change. It looks the pane up afresh each time, so
 * it keeps working when another email is opened (the pane is rebuilt per email).
 */
export async function record(page: Page) {
  await page.evaluate(() => {
    const w = window as unknown as { __samples: unknown[] };
    w.__samples = [];
    const take = () => {
      const pane = document.querySelector('[data-testid="email-pane"]');
      if (!pane) return;
      const aside = pane.querySelector('[data-testid="ai-reading"]');
      w.__samples.push({
        t: performance.now(),
        state: aside?.getAttribute("data-trace-state") ?? null,
        fields: pane.querySelectorAll('[data-testid="extracted-fields"] > li').length,
        highlights: pane.querySelectorAll('[data-testid="quote-highlight"]').length,
        status: !!pane.querySelector('[data-testid="trace-status"]'),
        statusText: pane.querySelector('[data-testid="trace-status"]')?.textContent ?? "",
        chip: !!aside?.querySelector('[data-testid="category-chip"]'),
        injection: !!pane.querySelector('[data-testid="injection-warning"]'),
        bank: !!pane.querySelector('[data-testid="bank-stripped"]'),
        missing: !!pane.querySelector('[data-testid="missing-fields"]'),
        heading: [...pane.querySelectorAll("h3")].some((h) => h.textContent === "Details found"),
        subject: pane.querySelector("h2")?.textContent ?? "",
        fieldText: pane.querySelector('[data-testid="extracted-fields"]')?.textContent ?? "",
      });
    };
    new MutationObserver(take).observe(document.querySelector("main") ?? document.body, {
      subtree: true,
      childList: true,
      attributes: true,
      characterData: true,
    });
  });
}

export const samples = (page: Page) =>
  page.evaluate(() => (window as unknown as { __samples: Sample[] }).__samples);

export async function waitDone(page: Page) {
  await expect(page.getByTestId("ai-reading")).toHaveAttribute("data-trace-state", "done");
}
