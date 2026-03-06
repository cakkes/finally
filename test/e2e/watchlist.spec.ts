import { test, expect } from '@playwright/test';

test.describe('Watchlist Management', () => {
  test('shows 10 default tickers', async ({ page }) => {
    await page.goto('/');
    await page.waitForSelector('[data-testid="watchlist"]', { timeout: 10000 });
    // Wait for rows to load from API
    await page.waitForSelector('[data-testid="watchlist-row"]', { timeout: 10000 });
    const rows = page.locator('[data-testid="watchlist-row"]');
    await expect(rows).toHaveCount(10);
  });

  test('can add a ticker', async ({ page }) => {
    await page.goto('/');
    await page.waitForSelector('[data-testid="add-ticker-input"]', { timeout: 10000 });
    await page.fill('[data-testid="add-ticker-input"]', 'PYPL');
    await page.click('[data-testid="add-ticker-button"]');
    // Wait for the watchlist to refresh
    await page.waitForTimeout(1000);
    await expect(page.getByText('PYPL', { exact: true })).toBeVisible();
  });

  test('can remove a ticker', async ({ page }) => {
    await page.goto('/');
    await page.waitForSelector('[data-testid="watchlist"]', { timeout: 10000 });
    await page.waitForSelector('[data-testid="watchlist-row"]', { timeout: 10000 });
    // Hover over NFLX row to reveal remove button
    const nflxRow = page.locator('[data-testid="watchlist-row"][data-ticker="NFLX"]');
    await nflxRow.hover();
    await page.click('[data-testid="remove-ticker-NFLX"]');
    await page.waitForTimeout(1000);
    await expect(page.locator('[data-testid="watchlist-row"][data-ticker="NFLX"]')).toHaveCount(0);
  });
});
