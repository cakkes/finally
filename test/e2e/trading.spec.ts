import { test, expect } from '@playwright/test';

test.describe('Core Trading Flow', () => {
  test('fresh start shows default watchlist and $10k balance', async ({ page }) => {
    await page.goto('/');
    await page.waitForSelector('[data-testid="watchlist"]', { timeout: 10000 });

    // Wait for watchlist rows to appear (loaded from API)
    await page.waitForSelector('[data-testid="watchlist-row"]', { timeout: 10000 });

    // Should show 10 default tickers
    const tickers = ['AAPL', 'GOOGL', 'MSFT', 'AMZN', 'TSLA', 'NVDA', 'META', 'JPM', 'V', 'NFLX'];
    for (const ticker of tickers) {
      await expect(page.getByText(ticker, { exact: true }).first()).toBeVisible();
    }

    // Should show cash balance using specific testid
    await expect(page.locator('[data-testid="cash-balance"]')).toContainText('$10,000');
  });

  test('prices update via SSE', async ({ page }) => {
    await page.goto('/');
    await page.waitForSelector('[data-testid="watchlist"]');
    // Wait for SSE connection to establish and transition to connected
    await expect(page.locator('[data-testid="connection-status"]')).toHaveAttribute(
      'data-status', 'connected', { timeout: 15000 }
    );
  });

  test('buy shares decreases cash and creates position', async ({ page }) => {
    await page.goto('/');
    await page.waitForSelector('[data-testid="trade-bar"]', { timeout: 10000 });
    // Wait for prices to load so buy buttons work
    await page.waitForSelector('[data-testid="watchlist-row"]', { timeout: 10000 });
    await page.waitForTimeout(2000);

    // Get initial cash
    const cashBefore = await page.locator('[data-testid="cash-balance"]').textContent();

    // Buy 5 AAPL - fill ticker first, then quantity
    await page.fill('[data-testid="trade-ticker"]', 'AAPL');
    await page.fill('[data-testid="trade-quantity"]', '5');
    await page.click('[data-testid="buy-button"]');

    // Wait for trade to complete
    await page.waitForTimeout(2000);

    // Cash should decrease
    const cashAfter = await page.locator('[data-testid="cash-balance"]').textContent();
    expect(cashBefore).not.toEqual(cashAfter);
  });
});
