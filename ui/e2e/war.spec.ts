import { expect, test } from '@playwright/test';

test.skip(Boolean(process.env['BASE_URL']), 'draft edits run against the mock only');
test.use({ viewport: { width: 1400, height: 1000 } });

test('weather-dependent control switches off to a fixed water temperature', async ({ page }) => {
  await page.addInitScript(() => localStorage.setItem('ovenbird.language', 'en'));
  await page.goto('./#/settings/curve');
  const card = page.getByTestId('curve-card');
  await expect(card).toHaveAttribute('data-war', 'on');
  await expect(page.getByTestId('curve-editor')).toBeVisible();
  await expect(page.getByTestId('field-control_fixed_water_c')).toHaveCount(0);

  const war = page.getByRole('switch', { name: /^Weather-dependent control \(WAR\)/ });
  await expect(war).toBeChecked();
  await war.locator('xpath=..').click();
  await expect(war).not.toBeChecked();
  await expect(card).toHaveAttribute('data-war', 'off');
  await expect(page.getByTestId('curve-editor')).toHaveCount(0);
  await expect(page.getByTestId('field-control_fixed_water_c')).toBeVisible();
  await expect(page.getByTestId('curve-fixed-note')).toContainText('safety band');
  await expect(page.getByTestId('draft-count')).toHaveText('1 change');
  await page.screenshot({ path: 'e2e/shots/settings-war-off.png' });

  await page.goto('./#/settings');
  await expect(page.getByTestId('overview-fixed')).toContainText('30');
});
