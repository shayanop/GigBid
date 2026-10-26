import { expect, test } from "@playwright/test";

import { openDraft, signUp } from "./helpers";

test("an edited draft goes back through compliance before approval", async ({ page }) => {
  await signUp(page);
  await openDraft(page);

  await page.getByRole("button", { name: "Edit draft" }).click();
  await page.getByLabel("Edit the cover letter").fill(
    "Thanks for the clear brief. Reach me at me@example.com any time. " +
      "I would begin with a short call to confirm scope and data access. ".repeat(5),
  );
  await page.getByRole("button", { name: "Save edit" }).click();

  // Back in review: the edit is kept, but the contact sentence is gone.
  await expect(page.getByText("Thanks for the clear brief.").first()).toBeVisible();
  await expect(page.getByText("me@example.com")).toHaveCount(0);
  await expect(page.getByText("removed contact details")).toBeVisible();
  await expect(page.getByRole("button", { name: /Approve and submit/ })).toBeVisible();

  // The edit is evidence, not yet a preference: one edit of the two needed.
  await page.getByRole("link", { name: "Settings" }).click();
  const learning = page.getByTestId("still-learning");
  await expect(learning).toContainText("Open with the client's problem");
  await expect(learning).toContainText("1 of 2 edits so far");
  await learning.getByRole("listitem").filter({ hasText: "Open with the client's problem" })
    .getByRole("button", { name: "Forget" }).click();
  await expect(page.getByText("Open with the client's problem")).toHaveCount(0);
});
