// Playwright template for the master prompt's end-to-end journey. Run against STAGING only.
//   STAGING_URL=https://opsi-staging.corp.example E2E_USER=... E2E_PASSWORD=... npx playwright test tests/e2e
// Selectors are placeholders - adapt them to the real Opsi markup (prefer data-testid attributes).
import { expect, test } from "@playwright/test";

const BASE = process.env.STAGING_URL ?? "";
const INCIDENT = process.env.E2E_INCIDENT_ID ?? "P-24102";

async function login(page: import("@playwright/test").Page) {
  await page.goto(`${BASE}/`);
  // Corporate SSO pages differ: replace with your IdP's test flow or a pre-authenticated storageState.
  await page.getByLabel(/user/i).fill(process.env.E2E_USER ?? "");
  await page.getByLabel(/password/i).fill(process.env.E2E_PASSWORD ?? "");
  await page.getByRole("button", { name: /sign in/i }).click();
  await expect(page).toHaveURL(new RegExp(BASE));
}

test("incident -> ask why -> cited answer -> UI action -> persisted after re-login", async ({ page, context }) => {
  test.skip(!BASE, "STAGING_URL not set");
  await login(page);
  await page.goto(`${BASE}/incidents/${INCIDENT}`);

  await page.getByRole("button", { name: /copilot|assistant/i }).click();
  await page.getByPlaceholder(/ask about this incident/i).fill("Why is this incident happening? Check logs and who owns the affected table.");
  await page.keyboard.press("Enter");

  // retrieval used exact logs and catalog ownership, answer carries citations
  await expect(page.getByText(/Searched logs/i)).toBeVisible({ timeout: 60_000 });
  await expect(page.getByText(/Looked up the catalog/i)).toBeVisible({ timeout: 60_000 });
  const answer = page.locator(".copilotKitAssistantMessage, [data-role='assistant']").last();
  await expect(answer).toContainText(/\[c\d+\]/, { timeout: 90_000 });

  // allowed UI action changes the chart filter
  await page.getByPlaceholder(/ask about this incident/i).fill("Filter the dashboard to errors of the affected service.");
  await page.keyboard.press("Enter");
  await expect(page.getByTestId("dashboard-filter-severity")).toHaveText(/ERROR/, { timeout: 60_000 });

  // tag the thread, then log out and back in
  const threadTitle = await page.locator("[aria-current='true'] button").first().innerText();
  await context.clearCookies();
  await page.evaluate(() => { localStorage.clear(); sessionStorage.clear(); });
  await login(page);
  await page.goto(`${BASE}/investigations`);
  await page.getByRole("searchbox", { name: /search history/i }).fill(threadTitle.slice(0, 20));
  await page.getByRole("button", { name: threadTitle }).click();
  await expect(page.getByText(/\[c1\]/).first()).toBeVisible();
  await expect(page.getByRole("complementary", { name: /evidence/i })).toContainText("[c1]");
});
