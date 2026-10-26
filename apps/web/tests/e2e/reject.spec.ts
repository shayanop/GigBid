import { expect, test } from "@playwright/test";

import { openDraft, signUp } from "./helpers";

test("rejecting a draft requires a reason and sends nothing", async ({ page }) => {
  await signUp(page);
  await openDraft(page);

  await page.getByRole("button", { name: "Reject", exact: true }).click();
  const confirm = page.getByRole("button", { name: "Reject proposal" });
  await expect(confirm).toBeDisabled();
  await page.getByLabel("Why are you rejecting it?").fill("Budget too low for the scope");
  await confirm.click();

  await expect(page.getByText("Rejected by you")).toBeVisible();
});
