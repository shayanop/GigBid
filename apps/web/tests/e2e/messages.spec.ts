import { expect, test } from "@playwright/test";

import { signUp } from "./helpers";

test("a client's interview request gets times and a reply that is sent only after approval", async ({ page }) => {
  await signUp(page);
  await page.goto("/messages");
  await page.getByRole("button", { name: "Check for new messages" }).click();

  const interview = page.getByTestId("conversation-row").filter({ hasText: "Interview request" });
  await expect(interview.getByText("Needs your approval")).toBeVisible();
  await interview.click();

  await expect(page.getByRole("heading", { name: "Interview times offered" })).toBeVisible();
  await expect(page.getByText("Your drafted reply")).toBeVisible();
  await page.getByRole("button", { name: "Approve and send" }).click();
  await expect(page.getByText("Sent", { exact: true })).toBeVisible();
});
