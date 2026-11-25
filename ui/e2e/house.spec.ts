import { expect, test, type BrowserContext, type Page } from '@playwright/test';

test.skip(Boolean(process.env['BASE_URL']), 'the House page runs against the mock only');

const PHONE_BUDGET = 2500;

async function scenario(context: BrowserContext, value: string, baseURL?: string): Promise<void> {
  await context.addCookies([{ name: 'ovenbird_mock', value, url: baseURL ?? 'http://127.0.0.1' }]);
}

async function language(page: Page, lang: 'en' | 'nl'): Promise<void> {
  await page.addInitScript((l) => localStorage.setItem('ovenbird.language', l), lang);
}

const tag = () => `tag:h${Math.random().toString(36).slice(2, 10)}`;

async function size(page: Page): Promise<{ height: number; scroll: number; inner: number }> {
  return page.evaluate(() => ({
    height: document.documentElement.scrollHeight,
    scroll: document.documentElement.scrollWidth,
    inner: window.innerWidth,
  }));
}

for (const width of [1400, 400]) {
  test(`the ready page shows every card without overflow at ${width} px`, async ({
    page,
    context,
    baseURL,
  }) => {
    await page.setViewportSize({ width, height: 900 });
    await scenario(context, tag(), baseURL);
    await language(page, 'en');
    await page.goto('./#/house');
    await expect(page.getByTestId('house-page')).toBeVisible();
    for (const id of [
      'house-score',
      'house-facts',
      'house-signature',
      'house-proposal',
      'house-quality',
    ]) {
      await expect(page.getByTestId(id)).toBeVisible();
    }
    await expect(page.getByTestId('house-score')).toContainText('240');
    await expect(page.getByTestId('house-band')).toContainText('Band C');
    await expect(page.getByTestId('house-band-limits')).toContainText('45–60');
    await expect(page.getByTestId('house-indicative')).toHaveText(
      'Indicative, not the official energielabel.',
    );
    await expect(page.getByTestId('house-fact-balance')).toContainText('16.5');
    const dims = await size(page);
    expect(dims.scroll).toBeLessThanOrEqual(dims.inner);
  });
}

for (const lang of ['en', 'nl'] as const) {
  test(`the phone page fits the height budget in ${lang}`, async ({ page, context, baseURL }) => {
    await page.setViewportSize({ width: 400, height: 900 });
    await scenario(context, tag(), baseURL);
    await language(page, lang);
    await page.goto('./#/house');
    await expect(page.getByTestId('house-quality')).toBeVisible();
    const dims = await size(page);
    expect(dims.scroll).toBeLessThanOrEqual(dims.inner);
    expect(dims.height, `phone height ${lang}`).toBeLessThanOrEqual(PHONE_BUDGET);
  });
}

test('the Dutch page uses the Dutch terms', async ({ page, context, baseURL }) => {
  await scenario(context, tag(), baseURL);
  await language(page, 'nl');
  await page.goto('./#/house');
  await expect(page.getByTestId('house-indicative')).toHaveText(
    'Indicatief, niet het officiële energielabel.',
  );
  await expect(page.getByTestId('house-score')).toContainText('warmteverlies');
  await expect(page.getByTestId('house-fact-balance')).toContainText('Stookgrens');
  await expect(page.getByTestId('house-fact-tau')).toContainText('Tijdconstante');
});

test('the signature chart has a text summary and a table', async ({ page, context, baseURL }) => {
  await scenario(context, tag(), baseURL);
  await language(page, 'en');
  await page.goto('./#/house');
  const plot = page.getByTestId('signature-plot');
  await expect(plot).toHaveAttribute('aria-label', /days from .* needed .* kW of heat/);
  await expect(page.getByTestId('signature-table')).toHaveCount(0);
  await page.getByTestId('signature-table-toggle').click();
  await expect(page.getByTestId('signature-table').locator('tbody tr')).toHaveCount(40);
});

test('an uncredible model says how many cold days it needs and blocks the draft', async ({
  page,
  context,
  baseURL,
}) => {
  await scenario(context, `${tag()}.house:uncredible`, baseURL);
  await language(page, 'en');
  await page.goto('./#/house');
  await expect(page.getByTestId('house-learning-score')).toContainText(
    'Still learning: 4 more cold days (daily mean below 5 °C) needed.',
  );
  await expect(page.getByTestId('house-band')).toHaveCount(0);
  await expect(page.getByTestId('house-proposal-uncredible')).toBeVisible();
  await expect(page.getByTestId('house-open-draft')).toBeDisabled();
});

test('without a floor area the score links to the setting', async ({ page, context, baseURL }) => {
  await scenario(context, `${tag()}.house:noarea`, baseURL);
  await language(page, 'en');
  await page.goto('./#/house');
  await expect(page.getByTestId('house-no-area')).toBeVisible();
  await expect(page.getByTestId('house-band')).toHaveCount(0);
  await page.getByTestId('house-area-link').click();
  await expect(page).toHaveURL(/#\/settings\/house$/);
  await expect(page.locator('#field-house_floor_area_m2')).toBeVisible();
});

for (const [value, testid, text] of [
  ['house:learning', 'house-learning', 'Still learning'],
  ['house:notrun', 'house-not_run', 'has not run yet'],
  ['newapi:missing', 'house-missing', 'does not offer the house model'],
] as const) {
  test(`${value} shows one explaining card`, async ({ page, context, baseURL }) => {
    await page.setViewportSize({ width: 400, height: 900 });
    await scenario(context, `${tag()}.${value}`, baseURL);
    await language(page, 'en');
    await page.goto('./#/house');
    await expect(page.getByTestId(testid)).toContainText(text);
    await expect(page.getByTestId('house-page')).toHaveCount(0);
    const dims = await size(page);
    expect(dims.scroll).toBeLessThanOrEqual(dims.inner);
  });
}

test('Open as draft lands on the curve page with the suggestion as a labelled draft', async ({
  page,
  context,
  baseURL,
}) => {
  await scenario(context, tag(), baseURL);
  await language(page, 'en');
  await page.goto('./#/house');
  const table = page.getByTestId('house-proposal-table');
  await expect(table).toContainText('capped at the maximum supply');
  await page.getByTestId('house-open-draft').click();
  await expect(page).toHaveURL(/#\/settings\/curve$/);
  await expect(page.getByTestId('draft-bar')).toBeVisible();
  await expect(page.getByTestId('draft-origin')).toHaveText('Suggested by the house model');
  await expect(page.getByTestId('draft-count')).toContainText('1');
  await page.getByTestId('draft-review').click();
  await expect(page.getByTestId('preview-comment')).toHaveValue(
    /^Suggested by the house model \(.+\)$/,
  );
  await page.keyboard.press('Escape');
  await page.getByTestId('draft-discard').click();
  await expect(page.getByTestId('draft-origin')).toHaveCount(0);
});

test('Settings has a House section with the floor area', async ({ page, context, baseURL }) => {
  await scenario(context, tag(), baseURL);
  await language(page, 'en');
  await page.goto('./#/settings/house');
  const section = page.getByTestId('house-section');
  await expect(section).toBeVisible();
  await expect(page.locator('#field-house_floor_area_m2')).toHaveValue('150');
  await section.getByTestId('house-section-link').click();
  await expect(page).toHaveURL(/#\/house$/);
});

test('Home and More lead to the House page', async ({ page, context, baseURL }) => {
  await page.setViewportSize({ width: 400, height: 900 });
  await scenario(context, tag(), baseURL);
  await language(page, 'en');
  await page.goto('./#/home');
  const link = page.getByTestId('week-house-link');
  await expect(link).toHaveAttribute('href', '#/house');
  await page.goto('./#/more');
  const more = page.getByTestId('more-house');
  await expect(more).toContainText('Band C · 240 W/K');
  await more.click();
  await expect(page).toHaveURL(/#\/house$/);
});
