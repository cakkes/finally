import { test, expect } from '@playwright/test';

test.describe('Portfolio Display', () => {
  test('positions table is visible', async ({ page }) => {
    await page.goto('/');
    await page.waitForSelector('[data-testid="positions-table"]', { timeout: 10000 });
    await expect(page.locator('[data-testid="positions-table"]')).toBeVisible();
  });

  test('portfolio heatmap renders', async ({ page }) => {
    await page.goto('/');
    await page.waitForSelector('[data-testid="portfolio-heatmap"]', { timeout: 10000 });
    await expect(page.locator('[data-testid="portfolio-heatmap"]')).toBeVisible();
  });
});
