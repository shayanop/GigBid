import { expect, test } from "@playwright/test";

import { PASSWORD, uniqueEmail } from "./helpers";

test("a new freelancer sets up an account, a budget and a saved search", async ({ page }) => {
  await page.goto("/onboarding");
  await page.getByLabel("Email").fill(uniqueEmail());
  await page.getByLabel("Password").fill(PASSWORD);
  await page.getByLabel(/Data analyst/).check();
  await page.getByRole("button", { name: "Create account" }).click();

  await page.getByLabel("Lowest hourly rate you accept (USD)").fill("55");
  await page.getByLabel("Connects you will spend per week").fill("40");
  await page.getByRole("button", { name: "Save and continue" }).click();

  await page.getByLabel("Skills, separated by commas").fill("dbt, Snowflake");
  await page.getByRole("button", { name: "Save search and finish" }).click();

  await expect(page).toHaveURL(/\/inbox$/);
  await expect(page.getByText("Your inbox is empty.")).toBeVisible();
  await page.getByRole("link", { name: "Settings" }).click();
  await expect(page.getByText("dbt, Snowflake")).toBeVisible();
  await expect(page.getByLabel("Weekly Connects budget")).toHaveValue("40");
});
