import { test, expect } from '@playwright/test';

test.describe('AI Chat', () => {
  test('can send message and receive response', async ({ page }) => {
    await page.goto('/');
    await page.waitForSelector('[data-testid="chat-input"]', { timeout: 10000 });

    // Type a message and send
    await page.fill('[data-testid="chat-input"]', 'Hello, what is my portfolio balance?');
    await page.click('[data-testid="chat-send"]');

    // Response appears (mock response) - wait longer for API call
    await page.waitForSelector('[data-testid="chat-message-assistant"]', { timeout: 20000 });
    const response = await page.locator('[data-testid="chat-message-assistant"]').last().textContent();
    expect(response).toBeTruthy();
    expect(response!.length).toBeGreaterThan(10);
  });
});
