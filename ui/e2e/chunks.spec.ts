import { expect, test } from '@playwright/test';

test.skip(Boolean(process.env['BASE_URL']), 'blocks lazy files of the mock dev server');

test.use({ viewport: { width: 1400, height: 1000 } });

test.beforeEach(async ({ page }) => {
  await page.addInitScript(() => localStorage.setItem('ovenbird.language', 'en'));
});

test('a page that failed to load says so and loads on the next visit', async ({ page }) => {
  let blocked = true;
  await page.route('**/src/pages/Settings.svelte*', (route) =>
    blocked ? route.abort() : route.continue(),
  );
  await page.goto('./#/settings');
  await expect(page.getByTestId('page-load-failed')).toContainText('could not be loaded');
  await expect(page.getByTestId('page-load-failed').getByRole('button')).toHaveText('Reload');
  blocked = false;
  await page.getByTestId('top-nav').getByRole('link', { name: 'Home' }).click();
  await page.getByTestId('nav-settings').click();
  await expect(page.getByTestId('page-load-failed')).toHaveCount(0);
  await expect(
    page.getByTestId('settings-picker').or(page.locator('main h1')).first(),
  ).toBeVisible();
});

test('help opens on the next click after its first load failed', async ({ page }) => {
  let blocked = true;
  await page.route('**/components/help/HelpDrawer.svelte*', (route) =>
    blocked ? route.abort() : route.continue(),
  );
  await page.goto('./#/');
  await page.getByTestId('help-button').click();
  await page.waitForTimeout(500);
  await expect(page.getByTestId('help-drawer')).toHaveCount(0);
  blocked = false;
  await page.getByTestId('help-button').click();
  await expect(page.getByTestId('help-drawer')).toBeVisible();
});

test('a tab still running an older build reloads itself once', async ({ page, baseURL }) => {
  let loads = 0;
  page.on('load', () => (loads += 1));
  await page.goto('./#/');
  await expect(page.getByTestId('help-button')).toBeVisible();
  await page.route('**/src/pages/Weather.svelte*', (route) => route.abort());
  await page.route(`${baseURL}/`, async (route) => {
    if (route.request().resourceType() !== 'fetch') return route.continue();
    const response = await route.fetch();
    const html = (await response.text()).replace('/src/main.ts', '/assets/index-newer.js');
    await route.fulfill({ response, body: html });
  });
  await page.getByTestId('top-nav').getByRole('link', { name: 'Weather' }).click();
  await expect.poll(() => loads).toBe(2);
  await page.waitForTimeout(1500);
  expect(loads).toBe(2);
});
