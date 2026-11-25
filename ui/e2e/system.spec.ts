import { expect, test, type BrowserContext, type Page } from '@playwright/test';

test.skip(
  Boolean(process.env['BASE_URL']),
  'notification, safety-net and export scenarios run on the mock',
);

async function scenario(context: BrowserContext, value: string, baseURL?: string): Promise<void> {
  await context.addCookies([{ name: 'ovenbird_mock', value, url: baseURL ?? 'http://127.0.0.1' }]);
}

async function english(page: Page): Promise<void> {
  await page.addInitScript(() => localStorage.setItem('ovenbird.language', 'en'));
}

const tag = () => `tag:y${Math.random().toString(36).slice(2, 10)}`;

test.describe('System overview tiles', () => {
  test.use({ viewport: { width: 1400, height: 1000 } });

  test('notifications are working and a test can be sent', async ({ page, context, baseURL }) => {
    await scenario(context, tag(), baseURL);
    await english(page);
    await page.goto('./#/system');
    const card = page.getByTestId('notify-card');
    await expect(card.getByTestId('notify-verdict')).toHaveAttribute('data-tone', 'good');
    await expect(card.getByTestId('notify-ntfy')).toContainText('ntfy.sh');
    await expect(card.getByTestId('notify-deadman')).toContainText('healthy');
    await card.getByTestId('notify-test').click();
    await expect(card.getByTestId('notify-test-outcome')).toHaveText(
      'Test sent. Check your phone.',
    );
    await expect(card.getByTestId('notify-last-test')).toContainText('today');
  });

  test('without a channel the tile says alerts only show here and cannot test', async ({
    page,
    context,
    baseURL,
  }) => {
    await scenario(context, `notify:off.${tag()}`, baseURL);
    await english(page);
    await page.goto('./#/system');
    const card = page.getByTestId('notify-card');
    await expect(card.getByTestId('notify-verdict')).toHaveAttribute('data-tone', 'bad');
    await expect(card.getByTestId('notify-verdict')).toContainText('only show on this page');
    await expect(card.getByTestId('notify-test')).toBeDisabled();
  });

  test('a failing channel shows the failed test and the unhealthy watchdog', async ({
    page,
    context,
    baseURL,
  }) => {
    await scenario(context, `notify:failing.${tag()}`, baseURL);
    await english(page);
    await page.goto('./#/system');
    const card = page.getByTestId('notify-card');
    await expect(card.getByTestId('notify-verdict')).toHaveAttribute('data-tone', 'bad');
    await expect(card.getByTestId('notify-deadman')).toContainText('failing');
    await card.getByTestId('notify-test').click();
    await expect(card.getByTestId('notify-test-outcome')).toContainText('HTTP 403');
  });

  test('a failing channel shows on Home, in the strip and in the checklist', async ({
    page,
    context,
    baseURL,
  }) => {
    await scenario(context, `notify:failing.alarms:none.${tag()}`, baseURL);
    await english(page);
    await page.goto('./#/home');
    await expect(page.getByTestId('strip-notify')).toBeVisible();
    await expect(page.getByTestId('strip-notify')).toHaveAttribute('href', '#/system');
    await expect(page.getByTestId('verdict-text')).toContainText('alerts do not reach your phone');
    await page.goto('./#/system/trial');
    const item = page.getByTestId('trial-checklist').locator('[data-check=notifications]');
    await expect(item).not.toHaveAttribute('data-status', 'ok');

    await scenario(context, `alarms:none.${tag()}`, baseURL);
    await page.goto('./#/home');
    await page.reload();
    await expect(page.getByTestId('home-verdict')).not.toContainText('alerts');
    await expect(page.getByTestId('strip-notify')).toHaveCount(0);
  });

  test('the safety net says declared, or proven with its evidence', async ({
    page,
    context,
    baseURL,
  }) => {
    await english(page);
    await page.goto('./#/system');
    const net = page.getByTestId('safety-net-card');
    await expect(net.getByTestId('envelope-rule')).toHaveAttribute('data-state', 'declared');
    await expect(net.getByTestId('envelope-evidence')).toHaveCount(0);
    await expect(net.getByTestId('envelope-band')).toContainText('°C');

    await scenario(context, 'envelope:proven', baseURL);
    await page.reload();
    await expect(net.getByTestId('envelope-rule')).toHaveAttribute('data-state', 'proven');
    await expect(net.getByTestId('envelope-evidence')).toContainText('without ovenbird');

    await scenario(context, 'envelope:none', baseURL);
    await page.reload();
    await expect(net.getByTestId('envelope-rule')).toHaveAttribute('data-state', 'not_declared');
  });

  test('about lists the installation and downloads diagnostics', async ({ page }) => {
    await english(page);
    await page.goto('./#/system');
    const about = page.getByTestId('about-card');
    await expect(about.getByTestId('about-facts')).toContainText('0.4.0');
    await about.getByTestId('about-details').locator('summary').click();
    await expect(about).toContainText('setcurves_target_high');
    const download = page.waitForEvent('download');
    await about.getByTestId('diagnostics-download').click();
    expect((await download).suggestedFilename()).toMatch(/^ovenbird-diagnostics-.*\.json$/);
  });

  test('an older service without these endpoints gets calm notes', async ({
    page,
    context,
    baseURL,
  }) => {
    const problems: string[] = [];
    page.on('pageerror', (error) => problems.push(error.message));
    await scenario(context, 'newapi:missing', baseURL);
    await english(page);
    await page.goto('./#/system');
    await expect(page.getByTestId('notify-missing')).toBeVisible();
    await expect(page.getByTestId('safety-net-missing')).toBeVisible();
    await expect(page.getByTestId('about-missing')).toBeVisible();
    await page.getByTestId('diagnostics-download').click();
    await expect(page.getByTestId('diagnostics-error')).toContainText('does not offer');
    expect(problems).toEqual([]);
  });
});

test.describe('exports', () => {
  test.use({ viewport: { width: 1400, height: 1000 } });

  test('the activity journals download as CSV for the range on screen', async ({ page }) => {
    await english(page);
    await page.goto('./#/activity');
    let download = page.waitForEvent('download');
    await page.getByTestId('csv-alarms').click();
    expect((await download).suggestedFilename()).toMatch(/^ovenbird-alarms-.*\.csv$/);

    await page.goto('./#/activity/commands');
    download = page.waitForEvent('download');
    await page.getByTestId('csv-commands').click();
    const file = await download;
    expect(file.suggestedFilename()).toMatch(/^ovenbird-commands-.*\.csv$/);
    const path = await file.path();
    const text = (await import('node:fs')).readFileSync(path, 'utf8');
    expect(text.split('\r\n')[0]).toBe('at,kind,value,status,attempt,topic,payload,detail');

    await page.goto('./#/activity/holds');
    download = page.waitForEvent('download');
    await page.getByTestId('csv-holds').click();
    const holds = await download;
    expect(holds.suggestedFilename()).toBe('ovenbird-holds.csv');
    const holdText = (await import('node:fs')).readFileSync(await holds.path(), 'utf8');
    expect(holdText.split('\r\n')[0]).toBe(
      'from,to,duration_s,reason,latched,setting,ovenbird_value,seen_value,message',
    );

    await page.goto('./#/activity/audit');
    download = page.waitForEvent('download');
    await page.getByTestId('csv-audit').click();
    expect((await download).suggestedFilename()).toMatch(/^ovenbird-audit-.*\.csv$/);
  });

  test('a chart table downloads as CSV', async ({ page }) => {
    await english(page);
    await page.goto('./#/pump');
    const toggle = page.getByTestId('chart-table-toggle').first();
    await toggle.click();
    const download = page.waitForEvent('download');
    await page.getByTestId('chart-table-csv').first().click();
    expect((await download).suggestedFilename()).toMatch(/^ovenbird-.*\.csv$/);
  });
});

test.describe('hold forensics', () => {
  test.use({ viewport: { width: 1400, height: 1000 } });

  test('the hold card says what changed, what the pump keeps and what happens next', async ({
    page,
    context,
    baseURL,
  }) => {
    await scenario(context, 'hold:timed', baseURL);
    await english(page);
    await page.goto('./#/activity/holds');
    const facts = page.getByTestId('hold-forensics');
    await expect(facts).toContainText('Water setpoint');
    await expect(facts.getByTestId('hold-ovenbird')).toHaveText('33 °C');
    await expect(facts.getByTestId('hold-seen')).toContainText('31 °C since');
    await expect(facts.getByTestId('hold-keeps')).toHaveText('31 °C');
    await expect(facts.getByTestId('hold-end')).toContainText('writes its own value again');
  });

  test('a latched hold waits for an administrator', async ({ page, context, baseURL }) => {
    await scenario(context, 'hold:latched', baseURL);
    await english(page);
    await page.goto('./#/activity/holds');
    await expect(page.getByTestId('hold-end')).toContainText('administrator releases');
  });
});

test.describe('small comparisons', () => {
  test('Home shows the energy used yesterday by this time', async ({ page }) => {
    await page.setViewportSize({ width: 1400, height: 1000 });
    await english(page);
    await page.goto('./#/home');
    await expect(page.getByTestId('tile-energy-yesterday')).toHaveText(/^yesterday \d/);
    await expect(page.getByTestId('tile-energy')).toHaveAttribute(
      'title',
      /Yesterday at this time/,
    );
    await page.setViewportSize({ width: 400, height: 860 });
    await expect(page.getByTestId('tile-energy-yesterday')).toBeHidden();
  });

  test('Signals shows the raw id on wide screens only', async ({ page }) => {
    await english(page);
    await page.setViewportSize({ width: 1400, height: 1000 });
    await page.goto('./#/system/signals');
    await expect(page.getByTestId('signal-raw-id').first()).toBeVisible();
    await page.setViewportSize({ width: 400, height: 860 });
    await expect(page.getByTestId('signal-raw-id').first()).toBeHidden();
  });
});
