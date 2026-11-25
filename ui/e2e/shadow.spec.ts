import { expect, test, type BrowserContext, type Page } from '@playwright/test';
import { mkdirSync } from 'node:fs';
import { join } from 'node:path';

test.skip(Boolean(process.env['BASE_URL']), 'the shadow view runs against the mock only');

const SHOTS = process.env['SHADOW_SHOTS'];
const PHONE_BUDGET = 2500;

async function scenario(context: BrowserContext, value: string, baseURL?: string): Promise<void> {
  await context.addCookies([{ name: 'ovenbird_mock', value, url: baseURL ?? 'http://127.0.0.1' }]);
}

async function language(page: Page, lang: 'en' | 'nl'): Promise<void> {
  await page.addInitScript((value) => localStorage.setItem('ovenbird.language', value), lang);
}

async function overflow(page: Page): Promise<number> {
  return page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
}

function watchConsole(page: Page): string[] {
  const problems: string[] = [];
  page.on('console', (message) => {
    if (message.type() !== 'error') return;
    const url = message.location().url;
    if (/status of 404/.test(message.text()) && /\/api\/v1\//.test(url)) return;
    problems.push(message.text());
  });
  page.on('pageerror', (error) => problems.push(error.message));
  return problems;
}

for (const viewport of [
  { label: 'desktop', width: 1400, height: 1000 },
  { label: 'phone', width: 400, height: 860 },
] as const) {
  for (const lang of ['en', 'nl'] as const) {
    test(`renders on ${viewport.label} in ${lang} without overflow`, async ({ page }) => {
      const problems = watchConsole(page);
      await page.setViewportSize({ width: viewport.width, height: viewport.height });
      await language(page, lang);
      await page.goto('./#/system/shadow');
      await expect(page.getByTestId('shadow-summary')).toBeVisible();
      await expect(page.getByTestId('shadow-chart')).toBeVisible();
      await expect(page.getByTestId('shadow-writer-legend')).toContainText(
        /Other controller|Andere regelaar/,
      );
      await expect(page.getByTestId('shadow-days')).toBeVisible();
      await expect(page.getByTestId('shadow-episodes')).toBeVisible();
      await expect(
        page.locator('[aria-current="page"]', { hasText: /Compare|Vergelijken/ }),
      ).toHaveCount(1);
      await page.waitForTimeout(600);
      expect(await overflow(page)).toBeLessThanOrEqual(0);
      if (viewport.label === 'phone') {
        const height = await page.evaluate(() => document.documentElement.scrollHeight);
        expect(height, `phone height in ${lang}`).toBeLessThanOrEqual(PHONE_BUDGET);
      }
      expect(problems).toEqual([]);
    });
  }
}

test.describe('interaction', () => {
  test.use({ viewport: { width: 1400, height: 1000 } });

  test('the #/shadow alias opens the Compare tab', async ({ page }) => {
    await language(page, 'en');
    await page.goto('./#/shadow');
    await expect(page.getByTestId('shadow-page')).toBeVisible();
    await expect(
      page.getByRole('heading', { name: 'Compare with the other controller' }),
    ).toBeVisible();
  });

  test('switches the period, refuses a bad custom window and shows the table', async ({ page }) => {
    await language(page, 'en');
    await page.goto('./#/system/shadow');
    const rows = page.getByTestId('shadow-days').locator('tbody tr');
    await expect(page.getByTestId('shadow-range-24h')).toHaveAttribute('aria-pressed', 'true');
    await expect(rows.first()).toBeVisible();
    const dayRows = await rows.count();
    expect(dayRows).toBeGreaterThanOrEqual(1);
    expect(dayRows).toBeLessThanOrEqual(2);

    const seven = page.waitForResponse(
      (r) => r.url().includes('/shadow/divergence') && r.url().includes('step=900'),
    );
    await page.getByTestId('shadow-range-7d').click();
    expect((await seven).ok()).toBe(true);
    await expect(rows).toHaveCount(8);
    await page.getByTestId('shadow-range-14d').click();
    await expect(rows).toHaveCount(15);

    await page.getByTestId('shadow-range-custom').click();
    const from = page.getByTestId('shadow-range-from');
    const to = page.getByTestId('shadow-range-to');
    await expect(from).not.toHaveValue('');
    await from.fill('2026-01-01T00:00');
    await expect(page.getByTestId('shadow-range-error')).toHaveText(
      'Choose at most 31 days at once.',
    );
    const toValue = await to.inputValue();
    await from.fill(toValue);
    await expect(page.getByTestId('shadow-range-error')).toHaveText(
      'The start must lie before the end.',
    );
    const end = new Date(Date.parse(toValue));
    const start = new Date(end.getTime() - 3 * 86_400_000);
    const pad = (n: number) => String(n).padStart(2, '0');
    const local = (d: Date) =>
      `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
    await from.fill(local(start));
    await expect(page.getByTestId('shadow-range-error')).toHaveCount(0);
    expect(await rows.count()).toBeGreaterThanOrEqual(3);

    await page.getByTestId('shadow-chart').getByTestId('chart-table-toggle').click();
    await expect(page.getByTestId('shadow-chart').getByTestId('chart-table')).toBeVisible();
  });

  test('lists the episodes newest first with the reason, and the older ones behind Show', async ({
    page,
  }) => {
    await language(page, 'en');
    await page.goto('./#/system/shadow');
    await page.getByTestId('shadow-range-14d').click();
    const list = page.getByTestId('shadow-episode-list');
    await expect(list.getByTestId('shadow-episode').first()).toBeVisible();
    await expect(list.getByTestId('shadow-episode')).toHaveCount(3);
    await expect(list.getByTestId('shadow-episode').first()).toContainText(/ovenbird’s reason: /);
    await expect(list.getByTestId('shadow-episode').first()).toContainText(
      /ovenbird would have sent \d+(\.\d)? K (less|more)/,
    );
    const more = page.getByTestId('shadow-episodes-more');
    await expect(more).toBeVisible();
    await more.locator('summary, button').first().click();
    await expect(more.getByTestId('shadow-episode').first()).toBeVisible();
  });

  test('an older service without the endpoint shows a calm not-available state', async ({
    page,
    context,
    baseURL,
  }) => {
    const problems = watchConsole(page);
    await scenario(context, 'newapi:missing', baseURL);
    await language(page, 'en');
    await page.goto('./#/system/shadow');
    await expect(page.getByTestId('shadow-missing')).toContainText(
      'Not available on this service yet',
    );
    await expect(page.getByTestId('shadow-summary')).toHaveCount(0);
    expect(problems).toEqual([]);
  });

  test('in Shadow the control line links to the comparison', async ({ page, context, baseURL }) => {
    await scenario(context, 'mode:shadow', baseURL);
    await language(page, 'en');
    await page.goto('./#/home');
    const link = page.getByTestId('control-compare');
    await expect(link).toBeVisible();
    await link.focus();
    await expect(link).toBeFocused();
    await page.keyboard.press('Enter');
    await expect(page).toHaveURL(/#\/system\/shadow$/);
    await expect(page.getByTestId('shadow-summary')).toBeVisible();
    await expect(page.getByTestId('shadow-lean')).toHaveAttribute('data-direction', 'cooler');
  });

  test('the control line has no Compare link while ovenbird controls', async ({ page }) => {
    await language(page, 'en');
    await page.goto('./#/home');
    await expect(page.getByTestId('status-strip')).toBeVisible();
    await expect(page.getByTestId('control-compare')).toHaveCount(0);
  });
});

test.describe('shadow screenshots', () => {
  test.skip(!SHOTS, 'set SHADOW_SHOTS=<dir> to capture');

  for (const viewport of [
    { label: 'desktop', width: 1400, height: 1000 },
    { label: 'phone', width: 400, height: 860 },
  ] as const) {
    for (const scheme of ['light', 'dark'] as const) {
      for (const lang of ['en', 'nl'] as const) {
        test(`${viewport.label} ${scheme} ${lang}`, async ({ page, context, baseURL }) => {
          mkdirSync(SHOTS!, { recursive: true });
          await scenario(context, 'mode:shadow', baseURL);
          await page.setViewportSize({ width: viewport.width, height: viewport.height });
          await page.emulateMedia({ colorScheme: scheme });
          await language(page, lang);
          await page.goto('./#/system/shadow');
          await expect(page.getByTestId('shadow-chart')).toBeVisible();
          await page.waitForTimeout(800);
          await page.screenshot({
            path: join(SHOTS!, `shadow-${viewport.label}-${scheme}-${lang}.png`),
            fullPage: true,
          });
          if (viewport.label === 'phone' && scheme === 'light') {
            await page.goto('./#/home');
            await expect(page.getByTestId('control-compare')).toBeVisible();
            await page.screenshot({
              path: join(SHOTS!, `shadow-controlline-phone-${lang}.png`),
              clip: { x: 0, y: 0, width: 400, height: 160 },
            });
          }
        });
      }
    }
  }
});

test('an episode can be marked as explained and the mark removed', async ({
  page,
  context,
  baseURL,
}) => {
  await context.addCookies([
    {
      name: 'ovenbird_mock',
      value: `mode:shadow.tag:x${Math.random().toString(36).slice(2, 10)}`,
      url: baseURL ?? 'http://127.0.0.1',
    },
  ]);
  await page.addInitScript(() => localStorage.setItem('ovenbird.language', 'en'));
  await page.setViewportSize({ width: 1400, height: 1000 });
  await page.goto('./#/system/shadow');
  const first = page.getByTestId('shadow-episode').first();
  await first.getByTestId('shadow-explain').click();
  await first.getByTestId('shadow-explain-note').fill('Node-RED boost after the defrost');
  const request = page.waitForRequest((r) => r.url().endsWith('/shadow/episodes/explain'));
  await first.getByTestId('shadow-explain-save').click();
  const body = (await request).postDataJSON();
  expect(body.note).toBe('Node-RED boost after the defrost');
  expect(typeof body.start).toBe('string');
  await expect(first.getByTestId('shadow-episode-explained')).toContainText(
    'Explained: Node-RED boost after the defrost',
  );
  await page.reload();
  await expect(
    page.getByTestId('shadow-episode').first().getByTestId('shadow-episode-explained'),
  ).toBeVisible();
  await page.getByTestId('shadow-episode').first().getByTestId('shadow-explain-remove').click();
  await expect(
    page.getByTestId('shadow-episode').first().getByTestId('shadow-episode-explained'),
  ).toHaveCount(0);
});
