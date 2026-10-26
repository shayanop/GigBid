import { expect, type Page } from "@playwright/test";

export const PASSWORD = "e2e password 123";

export function uniqueEmail() {
  return `e2e-${Date.now()}-${Math.random().toString(36).slice(2, 7)}@gigbid.test`;
}

/** Signs up through the API; the page shares the session cookie. */
export async function signUp(page: Page, account = "fr_ml") {
  const response = await page.request.post("/api/auth/signup", {
    data: { email: uniqueEmail(), password: PASSWORD, account },
  });
  expect(response.status()).toBe(201);
}

/** Analyzes a job from the inbox and opens its proposal in the studio. */
export async function openDraft(page: Page, jobId = "job_00012") {
  await page.goto("/inbox");
  await page.getByLabel("Marketplace job id").fill(jobId);
  await page.getByRole("button", { name: "Analyze job" }).click();
  const row = page.getByTestId("inbox-row").filter({ hasText: jobId });
  await expect(row.getByText("Needs your approval")).toBeVisible();
  await row.getByRole("link").click();
  await page.getByRole("link", { name: "Review proposal" }).click();
  await expect(page.getByRole("button", { name: /Approve and submit/ })).toBeVisible();
}
