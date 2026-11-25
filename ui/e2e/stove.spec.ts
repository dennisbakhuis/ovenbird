import { expect, test, type BrowserContext, type Page } from '@playwright/test';
import { pinCycleMinute } from './clock';

test.skip(Boolean(process.env['BASE_URL']), 'wood-stove mode runs against the mock only');
test.use({ viewport: { width: 1400, height: 1000 } });

const NORMAL_MINUTE = 130;

async function scenario(context: BrowserContext, value: string, baseURL?: string): Promise<void> {
  await context.addCookies([
    { name: 'ovenbird_mock', value: `${value}.hold:none`, url: baseURL ?? 'http://127.0.0.1' },
  ]);
  await pinCycleMinute(context, baseURL, NORMAL_MINUTE);
}

async function english(page: Page): Promise<void> {
  await page.addInitScript(() => localStorage.setItem('ovenbird.language', 'en'));
}

const tag = () => `tag:s${Math.random().toString(36).slice(2, 10)}`;

test('start the stove by hand from the room card and stop it from the banner', async ({
  page,
  context,
  baseURL,
}) => {
  await scenario(context, tag(), baseURL);
  await english(page);
  await page.goto('./#/home');
  await expect(page.getByTestId('stove-banner')).toHaveCount(0);
  const start = page.getByTestId('room-hero').getByTestId('stove-start');
  await expect(start).toHaveText(/Stove on…/);
  await start.click();
  await expect(start).toHaveAttribute('aria-expanded', 'true');
  await page.keyboard.press('Escape');
  await expect(start).toHaveAttribute('aria-expanded', 'false');
  await start.click();
  await page.getByTestId('stove-start-4').click();

  const banner = page.getByTestId('stove-banner');
  await expect(banner).toBeVisible();
  await expect(banner).toHaveAttribute('data-origin', 'manual');
  await expect(page.getByTestId('stove-banner-headline')).toHaveText(
    'Wood stove: heating backed off by 3 K',
  );
  await expect(page.getByTestId('stove-banner-reference')).toHaveAttribute(
    'data-reference',
    'none',
  );
  await expect(page.getByTestId('stove-banner-reference')).toContainText(
    'No other room is watched',
  );
  await expect(banner).toContainText(/Started by hand · since \d\d:\d\d · until/);
  await expect(page.getByTestId('room-hero').getByTestId('stove-start')).toHaveCount(0);
  await page.screenshot({ path: 'e2e/shots/stove-manual.png' });

  await page.getByTestId('stove-banner-stop').click();
  await expect(banner).toHaveCount(0);
  await expect(page.getByTestId('room-hero').getByTestId('stove-start')).toBeVisible();
});

test('an automatic episode shows on Home, in the mode sheet and on the Setpoint page', async ({
  page,
  context,
  baseURL,
}) => {
  await scenario(context, `${tag()}.stove:active`, baseURL);
  await english(page);
  await page.goto('./#/home');
  const banner = page.getByTestId('stove-banner');
  await expect(banner).toHaveAttribute('data-origin', 'auto');
  await expect(banner).toContainText(/Detected automatically · since \d\d:\d\d/);
  await expect(page.getByTestId('room-value')).toContainText('23.6');

  await page.getByTestId('mode-chip').click();
  await expect(page.getByTestId('sheet-stove')).toBeVisible();
  await expect(page.getByTestId('sheet-stove-start')).toHaveCount(0);
  await page.keyboard.press('Escape');

  await page.goto('./#/setpoint');
  await expect(page.getByTestId('decision-facts')).toContainText(
    /Wood-stove mode since \d\d:\d\d \(detected automatically\): the heating curve is lowered by 3 K/,
  );
});

test('in Shadow the stove banner and the verdict say nothing is backed off', async ({
  page,
  context,
  baseURL,
}) => {
  await scenario(context, `${tag()}.mode:shadow.stove:active`, baseURL);
  await english(page);
  await page.goto('./#/home');
  const banner = page.getByTestId('stove-banner');
  await expect(banner).toHaveAttribute('data-control', 'watching');
  await expect(page.getByTestId('stove-banner-headline')).toHaveText(
    'Wood stove: ovenbird would lower the heating by 3 K, but it only watches; nothing is sent',
  );
  await expect(banner).not.toContainText('backed off by');
  await expect(page.getByTestId('home-verdict')).toHaveAttribute('data-verdict', 'stove_idle');
  await expect(page.getByTestId('verdict-text')).toHaveText(
    'Wood stove burning; ovenbird only watches, so nothing is backed off',
  );
  const tonight = page.getByTestId('tonight');
  if ((await tonight.count()) > 0) {
    await expect(tonight).not.toContainText('stays backed off');
    await expect(tonight).toContainText(/the other controller drives the pump|hardly need/);
  }
  await page.screenshot({ path: 'e2e/shots/stove-shadow.png' });

  await scenario(context, `${tag()}.mode:paused.stove:active`, baseURL);
  await page.reload();
  await expect(page.getByTestId('stove-banner-headline')).toContainText('but it is paused');
  await expect(page.getByTestId('home-verdict')).toHaveAttribute('data-verdict', 'stove_idle');
});

test('the reference room is picked from the signal list', async ({ page, context, baseURL }) => {
  await scenario(context, `${tag()}.stove:active`, baseURL);
  await english(page);
  await page.goto('./#/settings/stove');
  const field = page.getByTestId('field-control_stove_reference_signal');
  await expect(field.getByTestId('signal-select')).toBeVisible();
  await expect(field.getByTestId('signal-fallback')).toHaveCount(0);
  await expect(page.getByTestId('stove-reference')).toHaveAttribute('data-reference', 'none');
});

test('the mode sheet offers Stove on… while no episode runs', async ({
  page,
  context,
  baseURL,
}) => {
  await scenario(context, tag(), baseURL);
  await english(page);
  await page.goto('./#/home');
  await page.getByTestId('mode-chip').click();
  const start = page.getByTestId('sheet-stove-start');
  await expect(start).toBeVisible();
  await start.click();
  await expect(page.getByTestId('sheet-stove-start-2')).toBeVisible();
  await expect(page.getByTestId('sheet-stove-start-8')).toBeVisible();
});

test('the wood-stove settings say why the detection waits', async ({ page, context, baseURL }) => {
  await scenario(context, `${tag()}.stove:waiting`, baseURL);
  await english(page);
  await page.goto('./#/settings/stove');
  await expect(page.getByTestId('stove-status')).toBeVisible();
  await expect(page.getByTestId('stove-chip-state')).toContainText('Ready');
  await expect(page.getByTestId('stove-waiting')).toContainText(
    'The last episode lasted as long as allowed',
  );
  await expect(page.getByTestId('field-control_stove_backoff_k')).toBeVisible();

  await page.goto('./#/settings');
  await expect(page.getByTestId('overview-stove')).toBeVisible();
});

test('no stove controls when wood-stove mode is not enabled', async ({
  page,
  context,
  baseURL,
}) => {
  await scenario(context, `${tag()}.stove:disabled`, baseURL);
  await english(page);
  await page.goto('./#/home');
  await expect(page.getByTestId('room-hero')).toBeVisible();
  await expect(page.getByTestId('stove-start')).toHaveCount(0);
  await expect(page.getByTestId('stove-banner')).toHaveCount(0);
});
