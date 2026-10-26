import { expect, test } from "@playwright/test";

import { openDraft, signUp } from "./helpers";

test("an approved, evidence-backed draft is submitted", async ({ page }) => {
  await signUp(page);
  await openDraft(page);

  // Every kept claim shows its source on hover; the unsupported one never reached the draft.
  await page.locator(".claim").first().hover();
  await page.getByRole("button", { name: /^(Case study|Code|Past proposal|Client review|Repository|CV):/ }).first().hover();
  await expect(page.getByRole("tooltip")).toBeVisible();
  await expect(page.getByText("1 claim with no evidence was removed")).toBeVisible();
  await expect(page.getByText("15 years of Rust")).toHaveCount(0);

  await page.getByRole("button", { name: /Approve and submit/ }).click();
  await expect(page.getByText("Submitted", { exact: true })).toBeVisible();
});
