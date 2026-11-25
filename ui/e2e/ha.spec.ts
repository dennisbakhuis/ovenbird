import { expect, test, type Page } from '@playwright/test';

test.skip(
  Boolean(process.env['BASE_URL']),
  'the Home Assistant mock answers run against the mock only',
);

test.use({ viewport: { width: 1400, height: 1000 } });

async function openHa(page: Page): Promise<void> {
  await page.addInitScript(() => localStorage.setItem('ovenbird.language', 'en'));
  await page.goto('./#/settings/ha');
  await expect(page.getByTestId('ha-card')).toBeVisible();
}

test('the connection test reports a working Home Assistant', async ({ page }) => {
  await openHa(page);
  await expect(page.getByTestId('ha-url')).toHaveValue('http://homeassistant.local:8123');
  await expect(page.getByTestId('ha-token')).toHaveValue('');
  await expect(page.getByTestId('ha-token-row')).toContainText('A token is stored');
  await page.getByTestId('ha-test').click();
  const result = page.getByTestId('ha-result');
  await expect(result).toHaveAttribute('data-verdict', 'ok');
  await expect(page.getByTestId('ha-verdict')).toContainText('The connection works');
  await expect(page.getByTestId('ha-version')).toHaveText('2026.11.2');
  await expect(result).toContainText('°C (metric)');
  await page.screenshot({ path: 'e2e/shots/ha-test-ok.png' });
});

test('the connection test explains a rejected token and an unreachable host', async ({ page }) => {
  await openHa(page);
  await page.getByTestId('ha-token').fill('wrong-token');
  await page.getByTestId('ha-test').click();
  await expect(page.getByTestId('ha-result')).toHaveAttribute('data-verdict', 'failed');
  await expect(page.getByTestId('ha-error')).toHaveText('Home Assistant rejected the token.');
  await expect(page.getByTestId('ha-result')).toContainText('rejected');

  await page.getByTestId('ha-url').fill('http://unreachable.local:8123');
  await page.getByTestId('ha-token').fill('some-token');
  await page.getByTestId('ha-test').click();
  await expect(page.getByTestId('ha-error')).toHaveText(
    'Home Assistant cannot be reached at this address.',
  );
  await expect(page.getByTestId('ha-result')).toContainText('Details: cannot reach');
  await page.screenshot({ path: 'e2e/shots/ha-test-failed.png' });

  await page.getByTestId('ha-url').fill('http://me:secret@ha.local:8123');
  await expect(page.getByTestId('ha-url-row')).toContainText(
    'Leave the user name and password out',
  );
  await expect(page.getByTestId('ha-test')).toBeDisabled();
  await expect(page.getByTestId('ha-save')).toBeDisabled();
});

test('a new token is saved write-only', async ({ page }) => {
  await openHa(page);
  await expect(page.getByTestId('ha-save')).toBeDisabled();
  await page.getByTestId('ha-token').fill('mock-long-lived-token-2');
  await page.getByTestId('ha-save').click();
  await expect(page.getByTestId('ha-notice')).toContainText('Saved');
  await expect(page.getByTestId('ha-token')).toHaveValue('');
  await expect(page.getByTestId('ha-token-row')).toContainText('A token is stored');
  await page.getByTestId('ha-token').fill('mock-long-lived-token');
  await page.getByTestId('ha-save').click();
  await expect(page.getByTestId('ha-notice')).toContainText('Saved');
});

test('a thermostat can be picked as the room sensor', async ({ page }) => {
  await page.addInitScript(() => localStorage.setItem('ovenbird.language', 'en'));
  await page.goto('./#/settings/room');
  const select = page.locator('#field-control_room_signal');
  await expect(select).toBeVisible();
  const option = select.locator('option[value="ha/climate.living_room#current_temperature"]');
  await expect(option).toHaveText(/Living room thermostat · Living room — 21[.,]6/);
  await select.selectOption('ha/climate.living_room#current_temperature');
  await expect(page.getByTestId('signal-id')).toContainText(
    'ha/climate.living_room#current_temperature',
  );
  await expect(page.getByTestId('draft-review')).toBeVisible();
  await page.screenshot({ path: 'e2e/shots/ha-pick-climate.png' });
  await page.getByTestId('draft-discard').click();
  await expect(select).toHaveValue('room_temperature');
});

test('liveness lists the room sensor device first', async ({ page }) => {
  await page.addInitScript(() => localStorage.setItem('ovenbird.language', 'en'));
  await page.goto('./#/settings/room');
  await page
    .locator('#field-control_room_signal')
    .selectOption('ha/sensor.living_room_temperature');
  await page.getByTestId('room-sensor-behaviour-details').locator('summary').click();
  const list = page.getByTestId('signal-multi');
  await expect(list).toBeVisible();
  const first = list.locator('li').first();
  await expect(first).toContainText('Living room climate humidity');
  await expect(first.getByTestId('signal-same-device')).toHaveText(
    'same device as the room sensor',
  );
  await expect(list).toContainText('Gang beweging battery');
  await page.getByTestId('draft-discard').click();
});
