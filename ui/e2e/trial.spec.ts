import { expect, test, type BrowserContext, type Page } from '@playwright/test';
import { allowedHeight } from './budget';

test.skip(Boolean(process.env['BASE_URL']), 'the trial flows run against the mock only');

async function scenario(context: BrowserContext, value: string, baseURL?: string): Promise<void> {
  await context.addCookies([{ name: 'ovenbird_mock', value, url: baseURL ?? 'http://127.0.0.1' }]);
}

async function language(page: Page, lang: 'en' | 'nl' = 'en'): Promise<void> {
  await page.addInitScript((value) => localStorage.setItem('ovenbird.language', value), lang);
}

const tag = () => `tag:t${Math.random().toString(36).slice(2, 10)}`;

async function open(page: Page): Promise<void> {
  await page.goto('./#/system/trial');
  await expect(page.getByTestId('trial-checklist')).toBeVisible();
  await expect(page.getByTestId('release-rehearse')).toBeVisible();
}

for (const viewport of [
  { label: 'desktop', width: 1400, height: 1000 },
  { label: 'phone', width: 400, height: 860 },
] as const) {
  for (const lang of ['en', 'nl'] as const) {
    test(`${viewport.label} ${lang}: renders every part without overflow`, async ({
      page,
      context,
      baseURL,
    }) => {
      await page.setViewportSize({ width: viewport.width, height: viewport.height });
      await scenario(context, tag(), baseURL);
      await language(page, lang);
      const errors: string[] = [];
      page.on('pageerror', (error) => errors.push(error.message));
      await open(page);
      await expect(page.getByTestId('trial-checklist').locator('li')).toHaveCount(10);
      await expect(page.getByTestId('trial-criteria').locator('tbody tr')).toHaveCount(6);
      await expect(page.getByTestId('runs-count')).toBeVisible();
      await expect(page.getByTestId('trial-snapshot')).toContainText(lang === 'en' ? '32' : '32');
      await page.waitForTimeout(300);
      const size = await page.evaluate(() => ({
        height: document.documentElement.scrollHeight,
        scroll: document.documentElement.scrollWidth,
        inner: window.innerWidth,
      }));
      expect(size.scroll).toBeLessThanOrEqual(size.inner);
      if (viewport.width <= 640) {
        expect(size.height, 'phone height').toBeLessThanOrEqual(allowedHeight(2500));
      }
      expect(errors).toEqual([]);
    });
  }
}

test.describe('release control', () => {
  test.use({ viewport: { width: 1400, height: 1000 } });

  test('the checklist explains items in words, with the service text behind Why', async ({
    page,
    context,
    baseURL,
  }) => {
    await scenario(context, tag(), baseURL);
    await language(page);
    await open(page);
    await expect(page.getByTestId('trial-verdict')).toContainText('4 items to finish');
    const days = page.locator('[data-check="shadow_days"]');
    await expect(days).toContainText('Check');
    await expect(days).toContainText('9.2 of 14 days in Shadow');
    await expect(page.locator('[data-check="divergence"] a')).toHaveAttribute(
      'href',
      '#/system/shadow',
    );
    await expect(page.locator('[data-check="rollback_rehearsal"]')).toContainText('Missing');
  });

  test('a rehearsal runs to the end and is never started by itself', async ({
    page,
    context,
    baseURL,
  }) => {
    await scenario(context, tag(), baseURL);
    await language(page);
    const posts: string[] = [];
    page.on('request', (request) => {
      if (request.method() === 'POST') posts.push(request.url());
    });
    await open(page);
    await page.waitForTimeout(1500);
    expect(posts).toEqual([]);
    await expect(page.getByTestId('release-last')).toContainText('Not rehearsed yet.');

    await page.getByTestId('release-rehearse').click();
    const confirm = page.getByTestId('release-confirm');
    await expect(confirm).toBeVisible();
    await expect(page.getByTestId('release-type')).toHaveCount(0);
    await page.getByTestId('release-reason').fill('drill');
    const request = page.waitForRequest(
      (r) => r.method() === 'POST' && r.url().endsWith('/api/v1/control/release'),
    );
    await page.getByTestId('release-start').click();
    const sent = await request;
    expect(sent.headers()['x-ovenbird-request']).toBe('1');
    expect(sent.postDataJSON()).toEqual({ rehearsal: true, reason: 'drill' });

    const state = page.getByTestId('release-state');
    await expect(state).toHaveAttribute('data-outcome', 'running');
    await expect(page.getByTestId('release-elapsed')).toContainText(/of 5 min/);
    await expect(page.locator('[data-kind="quiet_mode"]')).toContainText('Already right');
    await expect(state).toHaveAttribute('data-outcome', 'ok', { timeout: 20_000 });
    await expect(state).toContainText('Rehearsal done in');
    await expect(page.locator('[data-kind="water_setpoint"]')).toContainText('29 → 32');
    await expect(page.locator('[data-kind="water_setpoint"]')).toContainText('Back');
    const next = page.getByTestId('release-next');
    await expect(next.locator('li')).toHaveCount(4);
    await expect(next).toContainText('Node-RED');
    await expect(next).toContainText('This was a rehearsal');
    await page.screenshot({ path: 'e2e/shots/trial-rehearsal-done.png' });
    await expect(page.locator('[data-check="rollback_rehearsal"]')).toContainText('Done', {
      timeout: 10_000,
    });
  });

  test('before go-live: capture the pump state, plan a hand-back, see the trial state', async ({
    page,
    context,
    baseURL,
  }) => {
    await scenario(context, `mode:shadow.${tag()}`, baseURL);
    await language(page);
    await open(page);
    await expect(page.getByTestId('trial-group-go_live')).toBeVisible();
    await expect(page.getByTestId('trial-group-trial')).toBeVisible();
    await expect(page.getByTestId('trial-criteria-met')).toHaveAttribute('data-state', 'no_trial');
    await expect(page.getByTestId('trial-criteria-met')).toContainText('No trial yet');
    await expect(page.locator('[data-check="release_plan"]')).toContainText('Missing');
    await expect(page.getByTestId('release-dry')).toHaveCount(0);

    await page.getByTestId('trial-capture-button').click();
    await expect(page.getByTestId('trial-snapshot-origin')).toHaveAttribute(
      'data-origin',
      'manual',
    );
    await expect(page.getByTestId('trial-snapshot-origin')).toContainText('Captured by hand');

    const request = page.waitForRequest(
      (r) => r.method() === 'POST' && r.url().endsWith('/api/v1/control/release'),
    );
    await page.getByTestId('release-dry').click();
    expect((await request).postDataJSON()).toEqual({ rehearsal: true, dry: true });
    await expect(page.getByTestId('release-state')).toContainText('Plan ready');
    await expect(page.locator('[data-kind="water_setpoint"]')).toContainText('Would be restored');
    await expect(page.getByTestId('release-next')).toHaveCount(0);
    await expect(page.locator('[data-check="release_plan"]')).toContainText('Done', {
      timeout: 10_000,
    });
    await expect(page.locator('[data-check="pump_snapshot"]')).toContainText('Done');
    await expect(page.getByTestId('trial-criteria-met')).toHaveAttribute('data-state', 'no_trial');
    await expect(page.getByTestId('mode-chip')).not.toHaveAttribute('data-control', 'paused');
    await page.screenshot({ path: 'e2e/shots/trial-dry-plan.png', fullPage: true });
  });

  test('a real release needs the typed word', async ({ page, context, baseURL }) => {
    await scenario(context, tag(), baseURL);
    await language(page);
    await open(page);
    await page.getByTestId('release-now').click();
    const start = page.getByTestId('release-start');
    await expect(page.getByTestId('release-type')).toBeFocused();
    await expect(start).toBeDisabled();
    await page.getByTestId('release-type').fill('RELEAS');
    await expect(start).toBeDisabled();
    await page.getByTestId('release-type').fill('release');
    await expect(start).toBeEnabled();
    await page.getByRole('button', { name: 'Cancel' }).click();
    await expect(page.getByTestId('release-confirm')).toHaveCount(0);
  });

  test('Dutch asks for TERUGGEVEN', async ({ page, context, baseURL }) => {
    await scenario(context, tag(), baseURL);
    await language(page, 'nl');
    await open(page);
    await page.getByTestId('release-now').click();
    await expect(page.getByTestId('release-confirm')).toContainText('Typ TERUGGEVEN');
    await page.getByTestId('release-type').fill('teruggeven');
    await expect(page.getByTestId('release-start')).toBeEnabled();
  });

  test('in Shadow the service refuses and the page says why', async ({
    page,
    context,
    baseURL,
  }) => {
    await scenario(context, `mode:shadow.${tag()}`, baseURL);
    await language(page);
    await open(page);
    await expect(page.getByTestId('release-not-publishing')).toBeVisible();
    await page.getByTestId('release-rehearse').click();
    await page.getByTestId('release-start').click();
    await expect(page.getByTestId('release-error')).toHaveText(
      'ovenbird is not sending now, so it has written nothing to hand back.',
    );
    await expect(page.getByTestId('release-progress')).toHaveCount(0);
  });

  test('without a snapshot the card says when it is recorded', async ({
    page,
    context,
    baseURL,
  }) => {
    await scenario(context, `snapshot:none.${tag()}`, baseURL);
    await language(page);
    await open(page);
    await expect(page.getByTestId('trial-snapshot-none')).toBeVisible();
    await expect(page.locator('[data-check="pump_snapshot"]')).toContainText(
      'Not recorded yet: capture it below, or the go-live records it',
    );
    await page.getByTestId('release-rehearse').click();
    await page.getByTestId('release-start').click();
    await expect(page.getByTestId('release-error')).toContainText('No pump state from go-live');
  });

  test('an older service without these endpoints gets calm lines', async ({
    page,
    context,
    baseURL,
  }) => {
    await scenario(context, `newapi:missing.${tag()}`, baseURL);
    await language(page);
    const errors: string[] = [];
    page.on('pageerror', (error) => errors.push(error.message));
    await page.goto('./#/trial');
    await expect(page.getByTestId('trial-missing')).toHaveText(
      'This service does not offer the trial checklist yet.',
    );
    await expect(page.getByTestId('trial-runs-missing')).toBeVisible();
    await expect(page.getByTestId('trial-release-card')).toContainText(
      'This service does not offer release control yet.',
    );
    await expect(page.getByTestId('release-rehearse')).toHaveCount(0);
    expect(errors).toEqual([]);
  });
});
