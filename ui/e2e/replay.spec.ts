import { mkdirSync } from 'node:fs';
import { join } from 'node:path';
import { expect, test, type BrowserContext, type Page } from '@playwright/test';

test.skip(Boolean(process.env['BASE_URL']), 'replay scenarios run on the mock');

const SHOTS = process.env['REPLAY_SHOTS'];

async function scenario(context: BrowserContext, value: string, baseURL?: string): Promise<void> {
  await context.addCookies([{ name: 'ovenbird_mock', value, url: baseURL ?? 'http://127.0.0.1' }]);
}

async function language(page: Page, lang: 'en' | 'nl' = 'en'): Promise<void> {
  await page.addInitScript((value) => localStorage.setItem('ovenbird.language', value), lang);
}

async function withDraft(page: Page, changes: Record<string, unknown>): Promise<void> {
  await page.addInitScript(
    (value) =>
      localStorage.setItem(
        'ovenbird.draft',
        JSON.stringify({ base: 12, changes: value, origin: null }),
      ),
    changes,
  );
}

const tag = () => `tag:r${Math.random().toString(36).slice(2, 10)}`;

async function runReplay(page: Page): Promise<void> {
  await page.getByTestId('replay-run').click();
  await expect(page.getByTestId('replay-progress')).toBeVisible();
  await expect(page.getByTestId('replay-result')).toBeVisible({ timeout: 15_000 });
}

test.describe('System → Replay', () => {
  test.use({ viewport: { width: 1400, height: 1000 } });

  test('replays the active configuration with figures, chart and episodes', async ({
    page,
    context,
    baseURL,
  }) => {
    await scenario(context, tag(), baseURL);
    await language(page);
    await page.goto('./#/system/replay');
    await expect(page.getByTestId('replay-no-claims')).toContainText(
      'The house followed the recorded control',
    );
    const days = page.getByTestId('replay-day');
    await expect(days.first()).toBeAttached();
    expect(await days.count()).toBeGreaterThanOrEqual(30);
    await expect(
      page.locator('[data-testid="replay-day"][data-level="part"]').first(),
    ).toBeAttached();
    await expect(page.getByTestId('replay-idle')).toBeVisible();
    await page.getByTestId('replay-preset-1d').click();
    await runReplay(page);
    await expect(page.getByTestId('replay-identity')).toContainText('Exact');
    await expect(page.getByTestId('replay-for')).toContainText(
      /Active configuration \(version \d+\)/,
    );
    await expect(page.getByTestId('replay-chip-changes')).toBeVisible();
    await expect(page.getByTestId('replay-chip-writes')).toContainText('of 150');
    await expect(page.getByTestId('replay-chip-binding')).toContainText('Dead band');
    await expect(page.getByTestId('replay-chart').locator('svg').first()).toBeVisible();
    await expect(page.getByTestId('replay-share-reason').locator('li').first()).toBeVisible();
    await expect(page.getByTestId('replay-episodes')).toBeVisible();
    await expect(page.getByTestId('replay-no-claims')).toBeVisible();
    await expect(page.getByTestId('replay-run')).toHaveText('Replay again');

    await page.goto('./#/system/shadow');
    await page.goto('./#/system/replay');
    await expect(page.getByTestId('replay-result')).toBeVisible();
  });

  test('replays the current draft against the pump', async ({ page, context, baseURL }) => {
    await scenario(context, tag(), baseURL);
    await language(page);
    await withDraft(page, { control_comfort_c: 22.5 });
    await page.goto('./#/system/replay');
    await page.getByTestId('replay-config-draft').click();
    await expect(page.getByTestId('replay-config-note')).toContainText('on top of the active');
    await page.getByTestId('replay-preset-7d').click();
    await runReplay(page);
    await expect(page.getByTestId('replay-for')).toContainText('Draft (1 changed)');
    await expect(page.getByTestId('replay-chip-recorded')).not.toContainText('none');
    await expect(page.getByTestId('replay-episode').first()).toContainText('above the pump');
    await expect(page.getByTestId('replay-limitations')).toContainText('open loop');
  });

  test('replays a stored version and a day picked on the strip', async ({
    page,
    context,
    baseURL,
  }) => {
    await scenario(context, tag(), baseURL);
    await language(page);
    await page.goto('./#/system/replay');
    await page.getByTestId('replay-config-version').click();
    const select = page.getByTestId('replay-version');
    await expect(select).toBeVisible();
    await select.selectOption('10');
    const full = page.locator('[data-testid="replay-day"][data-level="full"]');
    await full.nth(1).click();
    await expect(page.getByTestId('replay-from')).toBeVisible();
    await expect(full.nth(1)).toHaveAttribute('aria-pressed', 'true');
    await runReplay(page);
    await expect(page.getByTestId('replay-for')).toContainText('Version 10');
  });

  test('checks a custom period and stops a running replay', async ({ page, context, baseURL }) => {
    await scenario(context, tag(), baseURL);
    await language(page);
    await page.goto('./#/system/replay');
    await page.getByTestId('replay-preset-custom').click();
    await page.getByTestId('replay-from').fill('2026-11-20T10:00');
    await page.getByTestId('replay-to').fill('2026-11-19T10:00');
    await expect(page.getByTestId('replay-period-error')).toContainText('before the end');
    await expect(page.getByTestId('replay-run')).toBeDisabled();
    await page.getByTestId('replay-preset-7d').click();
    await page.getByTestId('replay-run').click();
    await page.getByTestId('replay-cancel').click();
    await expect(page.getByTestId('replay-cancelled')).toBeVisible();
    await expect(page.getByTestId('replay-run')).toBeEnabled();
  });

  test('a viewer sees why it cannot replay', async ({ page, context, baseURL }) => {
    await scenario(context, 'role:viewer', baseURL);
    await language(page);
    await page.goto('./#/system/replay');
    await page.getByTestId('replay-run').click();
    await expect(page.getByTestId('replay-problem')).toContainText('operate or admin role');
  });

  test('an older service says the replay is not there', async ({ page, context, baseURL }) => {
    await scenario(context, 'newapi:missing', baseURL);
    await language(page);
    await page.goto('./#/system/replay');
    await expect(page.getByTestId('replay-missing')).toBeVisible();
    await expect(page.getByTestId('replay-no-claims')).toBeVisible();
  });
});

test.describe('replay screenshots', () => {
  test.skip(!SHOTS, 'set REPLAY_SHOTS=<dir> to capture');

  for (const viewport of [
    { label: 'desktop', width: 1400, height: 1000 },
    { label: 'phone', width: 400, height: 860 },
  ] as const) {
    for (const scheme of ['light', 'dark'] as const) {
      for (const lang of ['en', 'nl'] as const) {
        test(`${viewport.label} ${scheme} ${lang}`, async ({ page, context, baseURL }) => {
          mkdirSync(SHOTS!, { recursive: true });
          await scenario(context, tag(), baseURL);
          await page.setViewportSize({ width: viewport.width, height: viewport.height });
          await page.emulateMedia({ colorScheme: scheme });
          await language(page, lang);
          await withDraft(page, { control_comfort_c: 22.5 });
          await page.goto('./#/system/replay');
          await page.getByTestId('replay-config-draft').click();
          await runReplay(page);
          await expect(page.getByTestId('replay-chart')).toBeVisible();
          await page.waitForTimeout(800);
          const width = await page.evaluate(() => document.documentElement.scrollWidth);
          expect(width).toBeLessThanOrEqual(viewport.width);
          await page.screenshot({
            path: join(SHOTS!, `replay-${viewport.label}-${scheme}-${lang}.png`),
            fullPage: true,
          });
        });
      }
    }
  }
});
