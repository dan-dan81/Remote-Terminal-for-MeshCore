import { test, expect } from '@playwright/test';
import { ensureFlightlessChannel } from '../helpers/api';

test.describe('Channel messaging in #flightless', () => {
  test.beforeEach(async () => {
    await ensureFlightlessChannel();
  });

  test('send a message and see it appear', async ({ page }) => {
    await page.goto('/');

    // Click #flightless in the sidebar (use exact match to avoid "Flightless🥝" etc.)
    await page.getByText('#flightless', { exact: true }).first().click();

    // Verify conversation is open — the input placeholder includes the channel name
    await expect(page.getByPlaceholder(/message #flightless/i)).toBeVisible();

    // Compose a unique message
    const testMessage = `e2e-test-${Date.now()}`;
    const input = page.getByPlaceholder(/type a message|message #flightless/i);
    await input.fill(testMessage);

    // Send it
    await page.getByRole('button', { name: 'Send' }).click();

    // Verify message appears in the message list
    await expect(page.getByText(testMessage)).toBeVisible({ timeout: 15_000 });
  });

  test('outgoing message shows ack indicator', async ({ page }) => {
    await page.goto('/');

    await page.getByText('#flightless', { exact: true }).first().click();

    const testMessage = `ack-test-${Date.now()}`;
    const input = page.getByPlaceholder(/type a message|message #flightless/i);
    await input.fill(testMessage);
    await page.getByRole('button', { name: 'Send' }).click();

    // Wait for the message to appear
    const messageEl = page.getByText(testMessage);
    await expect(messageEl).toBeVisible({ timeout: 15_000 });

    // Outgoing messages show either "?" (pending) or "✓" (acked)
    // The ack indicator is in the same container as the message text
    const messageContainer = messageEl.locator('..');
    await expect(messageContainer.getByText(/[?✓]/)).toBeVisible();
  });

  test('resend outgoing channel message from message row', async ({ page }) => {
    await page.goto('/');

    await page.getByText('#flightless', { exact: true }).first().click();
    await expect(page.getByPlaceholder(/message #flightless/i)).toBeVisible();

    const testMessage = `resend-test-${Date.now()}`;
    const input = page.getByPlaceholder(/type a message|message #flightless/i);
    await input.fill(testMessage);
    await page.getByRole('button', { name: 'Send' }).click();

    const messageEl = page.getByText(testMessage).first();
    await expect(messageEl).toBeVisible({ timeout: 15_000 });

    const messageContainer = messageEl.locator(
      'xpath=ancestor::div[contains(@class,"break-words")][1]'
    );
    const resendButton = messageContainer.getByTitle('Resend message');
    await expect(resendButton).toBeVisible({ timeout: 15_000 });

    const resendResponsePromise = page.waitForResponse(
      (response) =>
        response.request().method() === 'POST' &&
        /\/api\/messages\/channel\/\d+\/resend$/.test(response.url())
    );

    await resendButton.click();

    const resendResponse = await resendResponsePromise;
    expect(resendResponse.ok()).toBeTruthy();
    await expect(page.getByText('Message resent')).toBeVisible({ timeout: 10_000 });

    // Byte-perfect resend should not create a second visible row in this conversation.
    await expect(page.getByText(testMessage)).toHaveCount(1);
  });
});
