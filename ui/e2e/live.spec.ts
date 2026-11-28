import { expect, test } from '@playwright/test';

test.skip(Boolean(process.env['BASE_URL']), 'mock stream');

test('a healthy page never shows the lost-connection banner while the stream opens', async ({
  page,
}) => {
  await page.addInitScript(() => localStorage.setItem('ovenbird.language', 'en'));
  await page.goto('./#/home');
  await expect(page.getByTestId('top-nav')).toBeVisible();
  await expect(page.getByTestId('banner-disconnected')).toHaveCount(0);
  await page.waitForFunction(
    () =>
      (window as unknown as { __mockSockets?: unknown[] }).__mockSockets?.length === 1 &&
      document.querySelector('[data-testid="status-strip"]') !== null,
  );
  await expect(page.getByTestId('banner-disconnected')).toHaveCount(0);
});

test('the banner appears when the stream drops and clears once it reconnects', async ({ page }) => {
  await page.addInitScript(() => localStorage.setItem('ovenbird.language', 'en'));
  await page.goto('./#/home');
  await expect(page.getByTestId('top-nav')).toBeVisible();
  await page.waitForFunction(
    () => (window as unknown as { __mockSockets?: unknown[] }).__mockSockets?.length === 1,
  );
  await page.evaluate(() => {
    const sockets = (window as unknown as { __mockSockets: { drop(): void }[] }).__mockSockets;
    sockets[0]!.drop();
  });
  await expect(page.getByTestId('banner-disconnected')).toContainText('Live connection lost');
  await expect(page.getByTestId('banner-disconnected')).toHaveCount(0, { timeout: 10_000 });
});
