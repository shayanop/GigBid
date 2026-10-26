import { expect, test } from "@playwright/test";

import { signUp } from "./helpers";

test("the app explains a marketplace outage and refuses new work clearly", async ({ page }) => {
  await signUp(page);
  await page.route("**/api/marketplace", (route) =>
    route.fulfill({ json: { available: false, connects: null } }),
  );
  await page.route("**/api/jobs", (route) =>
    route.request().method() === "POST"
      ? route.fulfill({ status: 503, json: { detail: "marketplace unavailable, try again shortly" } })
      : route.continue(),
  );
  await page.goto("/inbox");

  await expect(page.getByTestId("degraded-banner")).toContainText("Marketplace unavailable");
  await page.getByLabel("Marketplace job id").fill("job_00012");
  await page.getByRole("button", { name: "Analyze job" }).click();
  await expect(page.getByText("marketplace unavailable, try again shortly")).toBeVisible();
});
