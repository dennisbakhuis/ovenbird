import { mkdirSync, readFileSync } from 'node:fs';
import { settled } from './settle';
import { join } from 'node:path';
import { expect, test, type BrowserContext, type Page } from '@playwright/test';

test.skip(Boolean(process.env['BASE_URL']), 'data scenarios run on the mock');

const SHOTS = 'e2e/shots';
const ARCHIVE_SHOTS = process.env['ARCHIVE_SHOTS'];

async function scenario(context: BrowserContext, value: string, baseURL?: string): Promise<void> {
  await context.addCookies([{ name: 'ovenbird_mock', value, url: baseURL ?? 'http://127.0.0.1' }]);
}

async function english(page: Page, lang: 'en' | 'nl' = 'en'): Promise<void> {
  await page.addInitScript((value) => localStorage.setItem('ovenbird.language', value), lang);
}

function monthsAgo(n: number): string {
  const date = new Date();
  date.setUTCDate(1);
  date.setUTCMonth(date.getUTCMonth() - n);
  return date.toISOString().slice(0, 7);
}

const tag = () => `tag:d${Math.random().toString(36).slice(2, 10)}`;

test.describe('System → Data', () => {
  test.use({ viewport: { width: 1400, height: 1000 } });

  test('shows sizes, the projection and frees space on request', async ({
    page,
    context,
    baseURL,
  }) => {
    await scenario(context, tag(), baseURL);
    await english(page);
    await page.goto('./#/system/data');
    const storage = page.getByTestId('storage-card');
    await expect(storage.getByTestId('storage-database')).toContainText('MB');
    await expect(storage.getByTestId('storage-projected')).toContainText('MB');
    await expect(storage.getByTestId('storage-growth')).toContainText('per year');
    const rows = storage.getByTestId('storage-resolutions').locator('tbody tr');
    await expect(rows).toHaveCount(6);
    await expect(rows.filter({ hasText: 'Hourly averages' })).toContainText('forever');
    await expect(rows.filter({ hasText: 'Raw samples' })).toContainText('14 days');
    await expect(storage).toContainText('of free pages');
    await storage.getByTestId('storage-compact').click();
    await expect(storage.getByTestId('storage-compact-message')).toContainText('queued');
    await expect(storage.getByTestId('storage-compact-last')).toContainText('freed');
    await expect(storage).not.toContainText('of free pages');
    await page.screenshot({ path: `${SHOTS}/data-system-desktop.png`, fullPage: true });
  });

  test('estimates and downloads a series for the chosen signals', async ({
    page,
    context,
    baseURL,
  }) => {
    await scenario(context, tag(), baseURL);
    await english(page);
    await page.goto('./#/system/data');
    const card = page.getByTestId('export-card');
    await expect(card.getByTestId('export-privacy')).toContainText('lived in');
    const all = card.getByTestId('export-signal');
    await expect(all.first()).toBeVisible();
    const total = await all.count();
    expect(total).toBeGreaterThan(5);
    await expect(card.getByTestId('export-chosen')).toHaveText(`${total} of ${total} chosen`);
    const allEstimate = await card.getByTestId('export-estimate').textContent();

    await card.getByTestId('export-none').click();
    await expect(card.getByTestId('export-series')).toBeDisabled();
    await expect(card).toContainText('Choose at least one signal.');

    await card.getByTestId('export-filter').fill('outside');
    await expect(all).toHaveCount(1);
    await all.first().check();
    await card.getByTestId('export-filter').fill('');
    await expect(card.getByTestId('export-chosen')).toHaveText(`1 of ${total} chosen`);
    await card.getByTestId('range-1d').click();
    await card.getByTestId('step-3600').click();
    await expect(card.getByTestId('export-estimate')).toContainText(/About 2[34] rows/);
    expect(await card.getByTestId('export-estimate').textContent()).not.toBe(allEstimate);

    const link = card.getByTestId('export-series');
    await expect(link).toHaveAttribute('href', /signals=main%2FOutside_Temp&step=3600/);
    const download = page.waitForEvent('download');
    await link.click();
    const file = await download;
    expect(file.suggestedFilename()).toMatch(/^ovenbird-series-3600-long-.*\.csv$/);
    const lines = readFileSync(await file.path(), 'utf8')
      .trim()
      .split('\n');
    expect(lines[0]).toBe('at,signal,unit,value,min,max');
    expect(lines.length).toBeGreaterThan(20);
    expect(lines[1]).toContain('main/Outside_Temp,°C,');

    await card.getByTestId('layout-wide').click();
    await card.getByTestId('format-ndjson').click();
    await expect(link).toHaveAttribute('href', /layout=wide&format=ndjson/);
  });

  test('a custom range that ends before it starts blocks the downloads', async ({
    page,
    context,
    baseURL,
  }) => {
    await scenario(context, tag(), baseURL);
    await english(page);
    await page.goto('./#/system/data');
    const card = page.getByTestId('export-card');
    await card.getByTestId('range-custom').click();
    await card.getByTestId('export-from').fill('2026-11-10');
    await card.getByTestId('export-to').fill('2026-11-01');
    await expect(card.getByTestId('export-series')).toBeDisabled();
    await expect(card.getByTestId('export-journal-decisions')).toBeDisabled();
    await card.getByTestId('export-to').fill('2026-11-12');
    await expect(card.getByTestId('export-series')).toHaveAttribute(
      'href',
      /from=2026-11-\d\dT\d\d%3A00%3A00\.000Z/,
    );
  });

  test('journals and the archive download; a viewer gets a clear refusal', async ({
    page,
    context,
    baseURL,
  }) => {
    await scenario(context, tag(), baseURL);
    await english(page);
    await page.goto('./#/system/data');
    const card = page.getByTestId('export-card');
    let download = page.waitForEvent('download');
    await card.getByTestId('export-journal-commands').click();
    const commands = await download;
    expect(commands.suggestedFilename()).toMatch(/^ovenbird-commands-.*\.csv$/);
    expect(readFileSync(await commands.path(), 'utf8').split('\n')[0]).toBe(
      'at,kind,value,status,attempt,topic,payload,detail',
    );
    download = page.waitForEvent('download');
    await card.getByTestId('export-archive').click();
    expect((await download).suggestedFilename()).toMatch(/^ovenbird-archive-.*\.zip$/);
    await expect(card.getByTestId('export-archive-error')).toHaveCount(0);

    await scenario(context, `role:viewer.${tag()}`, baseURL);
    await page.reload();
    await card.getByTestId('export-archive').click();
    await expect(card.getByTestId('export-archive-error')).toHaveText(
      'The archive needs the admin login.',
    );
    await page.getByTestId('storage-compact').click();
    await expect(page.getByTestId('storage-compact-message')).toHaveText(
      'Freeing space needs the admin login.',
    );
  });

  test('an older service without the data endpoints gets calm notes', async ({
    page,
    context,
    baseURL,
  }) => {
    await scenario(context, `newapi:missing.${tag()}`, baseURL);
    await english(page);
    await page.goto('./#/system/data');
    await expect(page.getByTestId('storage-missing')).toBeVisible();
    await expect(page.getByTestId('export-missing')).toBeVisible();
    await expect(page.getByTestId('archive-missing')).toBeVisible();
  });
});

test.describe('Settings → Data', () => {
  test.use({ viewport: { width: 1400, height: 1000 } });

  test('retention is edited in days or kept forever and goes through the review', async ({
    page,
    context,
    baseURL,
  }) => {
    await scenario(context, tag(), baseURL);
    await english(page);
    await page.goto('./#/settings');
    await expect(page.getByTestId('overview-data')).toHaveText('14 d');
    await page.getByTestId('section-data').click();
    await expect(page).toHaveURL(/#\/settings\/data$/);
    const section = page.getByTestId('data-section');
    await section.getByTestId('retention-advanced').locator('summary').click();
    await expect(section.getByTestId('forever-history_1h_days')).toBeChecked();
    const raw = section.getByTestId('forever-history_raw_days');
    await expect(raw).not.toBeChecked();
    const minute = section.getByLabel('Keep 1-minute history', { exact: true });
    await minute.fill('3');
    await expect(
      section.getByTestId('field-history_1m_days').getByTestId('soft-warning'),
    ).toBeVisible();
    await minute.fill('180');
    await expect(
      section.getByTestId('field-history_1m_days').getByTestId('soft-warning'),
    ).toHaveCount(0);
    await raw.check();
    await expect(
      section.getByTestId('field-history_raw_days').locator('input[type=text]'),
    ).toHaveCount(0);
    await expect(page.getByTestId('draft-count')).toHaveText('2 changes');
    await expect(section.getByTestId('preset-custom')).toBeVisible();
    await page.screenshot({ path: `${SHOTS}/data-settings-desktop.png`, fullPage: true });

    await page.getByTestId('draft-review').click();
    const dialog = page.getByTestId('preview-dialog');
    await expect(dialog).toBeVisible();
    await expect(page.getByTestId('diff-row-history_raw_days')).toContainText('forever');
    await expect(page.getByTestId('diff-row-history_1m_days')).toContainText('180 d');
    await page.keyboard.press('Escape');
    await expect(dialog).toBeHidden();
    await page.getByTestId('draft-discard').click();
    await expect(page.getByTestId('draft-bar')).toBeHidden();

    await page.getByTestId('data-section-link').click();
    await expect(page).toHaveURL(/#\/system\/data$/);
    await page.getByTestId('storage-settings').click();
    await expect(page).toHaveURL(/#\/settings\/data$/);
  });
});

test.describe('Retention presets', () => {
  test.use({ viewport: { width: 1400, height: 1000 } });

  test('a preset sets the five retentions; anything else is custom', async ({
    page,
    context,
    baseURL,
  }) => {
    await scenario(context, tag(), baseURL);
    await english(page);
    await page.goto('./#/settings/data');
    const presets = page.getByTestId('retention-presets');
    await expect(presets.getByRole('radio', { name: /Standard/ })).toBeChecked();
    await expect(presets.getByTestId('preset-standard')).toContainText('in use');
    await expect(presets.getByTestId('preset-size-short')).toContainText('after a year');
    await expect(presets.getByTestId('preset-size-unlimited')).toContainText('per year');
    await expect(presets.getByTestId('preset-custom')).toHaveCount(0);

    await presets.getByTestId('preset-radio-long').check();
    await expect(presets.getByRole('radio', { name: /Long/ })).toBeChecked();
    await expect(page.getByTestId('draft-count')).toHaveText('3 changes');
    await page.getByTestId('retention-advanced').locator('summary').click();
    await expect(page.getByLabel('Keep 1-minute history', { exact: true })).toHaveValue('366');
    await expect(
      page.getByTestId('field-history_decision_days').getByTestId('soft-warning'),
    ).toHaveCount(0);

    await page.getByLabel('Keep raw history', { exact: true }).fill('0.5');
    await expect(page.getByTestId('field-history_raw_days')).toContainText(
      'Keep at least 1 day, or choose Keep forever.',
    );
    await page.getByLabel('Keep raw history', { exact: true }).fill('21');
    await expect(presets.getByTestId('preset-custom')).toBeVisible();
    await expect(presets.getByRole('radio', { name: /Custom/ })).toBeChecked();

    await presets.getByTestId('preset-radio-standard').check();
    await expect(page.getByTestId('draft-bar')).toBeHidden();
    await expect(presets.getByTestId('preset-custom')).toHaveCount(0);
  });
});

test.describe('Yearly archive', () => {
  test.use({ viewport: { width: 1400, height: 1000 } });

  test('lists months, years and seasons and downloads them', async ({ page, context, baseURL }) => {
    await scenario(context, tag(), baseURL);
    await english(page);
    await page.goto('./#/system/data');
    const card = page.getByTestId('archive-card');
    await expect(card.getByTestId('archive-privacy')).toContainText('Share it with care');
    const months = card.getByTestId('archive-month');
    await expect(months).toHaveCount(0);
    await card.getByTestId('archive-months-details').locator('summary').click();
    await expect(months).toHaveCount(15);
    await expect(months.first()).toHaveAttribute('data-state', 'open');
    await expect(months.last()).toContainText('days missing');
    await expect(card.getByTestId('archive-total')).toContainText('MB');

    const years = card.getByTestId('archive-group');
    await expect(years).toHaveCount(2);
    await expect(years.last()).toContainText('Partial:');
    let download = page.waitForEvent('download');
    await years.last().getByTestId('archive-group-download').click();
    expect((await download).suggestedFilename()).toMatch(/^ovenbird-archive-\d{4}\.zip$/);

    await card.getByTestId('archive-by-season').click();
    await expect(card).toContainText('August to July');
    download = page.waitForEvent('download');
    await years.first().getByTestId('archive-group-download').click();
    expect((await download).suggestedFilename()).toMatch(
      /^ovenbird-archive-season-\d{4}-\d{2}\.zip$/,
    );

    download = page.waitForEvent('download');
    await months.first().getByTestId('archive-month-download').click();
    expect((await download).suggestedFilename()).toMatch(/-partial\.zip$/);
    await expect(card.getByTestId('archive-message')).toHaveCount(0);
  });

  test('deletes a month after confirmation; a viewer is refused', async ({
    page,
    context,
    baseURL,
  }) => {
    await scenario(context, tag(), baseURL);
    await english(page);
    await page.goto('./#/system/data');
    const card = page.getByTestId('archive-card');
    const period = monthsAgo(2);
    await card.getByTestId('archive-months-details').locator('summary').click();
    const row = card.locator(`[data-testid="archive-month"][data-period="${period}"]`);
    await row.getByTestId('archive-month-delete').click();
    const dialog = page.getByTestId('archive-delete-dialog');
    await expect(dialog).toContainText('is not archived again');
    await dialog.getByRole('button', { name: 'Cancel' }).click();
    await expect(row).toBeVisible();
    await row.getByTestId('archive-month-delete').click();
    await page.getByTestId('archive-delete-confirm').click();
    await expect(card.getByTestId('archive-message')).toContainText('deleted from the archive');
    await expect(row).toHaveCount(0);
    await expect(card.getByTestId('archive-month')).toHaveCount(14);

    await scenario(context, `role:viewer.${tag()}`, baseURL);
    await page.reload();
    await card.getByTestId('archive-month-download').nth(1).click();
    await expect(card.getByTestId('archive-message')).toHaveText(
      'Downloads from the archive need the admin login.',
    );
    await card.getByTestId('archive-month-delete').first().click();
    await page.getByTestId('archive-delete-confirm').click();
    await expect(card.getByTestId('archive-message')).toHaveText(
      'Deleting from the archive needs the admin login.',
    );
  });

  test('the switch turns the archive off as a configuration change', async ({
    page,
    context,
    baseURL,
  }) => {
    await scenario(context, tag(), baseURL);
    await english(page);
    await page.goto('./#/system/data');
    const card = page.getByTestId('archive-card');
    await card.getByTestId('archive-switch').locator('xpath=..').click();
    await expect(card.getByTestId('archive-off')).toContainText('The archive is off');
    await page.goto('./#/settings/data');
    await expect(
      page.getByTestId('field-history_archive_enabled').locator('input[type=checkbox]'),
    ).not.toBeChecked();
    await page.goto('./#/system/data');
    await card.getByTestId('archive-switch').locator('xpath=..').click();
    await expect(card.getByTestId('archive-off')).toHaveCount(0);
  });

  test('an empty archive and a failed step are named', async ({ page, context, baseURL }) => {
    await scenario(context, `archive:empty.${tag()}`, baseURL);
    await english(page);
    await page.goto('./#/system/data');
    await expect(page.getByTestId('archive-empty')).toBeVisible();
    await scenario(context, `archive:error.${tag()}`, baseURL);
    await page.reload();
    await expect(page.getByTestId('archive-error')).toContainText('disk I/O error');
  });
});

test.describe('archive screenshots', () => {
  test.skip(!ARCHIVE_SHOTS, 'set ARCHIVE_SHOTS=<dir> to capture');

  for (const viewport of [
    { label: 'desktop', width: 1400, height: 1000 },
    { label: 'phone', width: 400, height: 860 },
  ] as const) {
    for (const scheme of ['light', 'dark'] as const) {
      for (const lang of ['en', 'nl'] as const) {
        test(`${viewport.label} ${scheme} ${lang}`, async ({ page, context, baseURL }) => {
          mkdirSync(ARCHIVE_SHOTS!, { recursive: true });
          await scenario(context, tag(), baseURL);
          await page.setViewportSize({ width: viewport.width, height: viewport.height });
          await page.emulateMedia({ colorScheme: scheme });
          await english(page, lang);
          await page.goto('./#/system/data');
          const card = page.getByTestId('archive-card');
          await card.getByTestId('archive-months-details').locator('summary').click();
          await expect(card.getByTestId('archive-month').first()).toBeVisible();
          await settled(page);
          const width = await page.evaluate(() => document.documentElement.scrollWidth);
          expect(width).toBeLessThanOrEqual(viewport.width);
          await card.screenshot({
            path: join(ARCHIVE_SHOTS!, `archive-${viewport.label}-${scheme}-${lang}.png`),
          });
          await page.goto('./#/settings/data');
          await expect(page.getByTestId('preset-size-short')).toContainText(/MB|kB/);
          await settled(page);
          await page.screenshot({
            path: join(ARCHIVE_SHOTS!, `presets-${viewport.label}-${scheme}-${lang}.png`),
            fullPage: true,
          });
        });
      }
    }
  }
});
