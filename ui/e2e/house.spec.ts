import { expect, test, type BrowserContext, type Page } from '@playwright/test';
import { allowedHeight } from './budget';

test.skip(Boolean(process.env['BASE_URL']), 'the House page runs against the mock only');

const PHONE_BUDGET = 2600;

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

async function applyDraft(page: Page): Promise<void> {
  await page.getByTestId('draft-review').click();
  await page.getByTestId('preview-apply').click();
  await expect(page.getByTestId('preview-dialog')).toBeHidden();
  await expect(page.getByTestId('apply-notice')).toContainText(/Version \d+/);
}

for (const width of [1400, 400]) {
  test(`the House page shows its cards without overflow at ${width} px`, async ({
    page,
    context,
    baseURL,
  }) => {
    await page.setViewportSize({ width, height: 900 });
    await scenario(context, tag(), baseURL);
    await language(page, 'en');
    await page.goto('./#/house');
    await expect(page.getByTestId('house-page')).toBeVisible();
    await expect(page.getByTestId('house-loss-now')).toBeVisible();
    await expect(page.getByTestId('house-heat-pump')).toBeVisible();
    await expect(page.getByTestId('house-by-weather')).toBeVisible();
    await expect(page.getByTestId('house-facts-input')).toBeVisible();
    const dims = await size(page);
    expect(dims.scroll).toBeLessThanOrEqual(dims.inner);
    await page.screenshot({ path: `e2e/shots/house-${width}.png`, fullPage: true });
  });
}

for (const lang of ['en', 'nl'] as const) {
  for (const [name, value] of [
    ['default', ''],
    ['facts set', 'house:facts'],
  ] as const) {
    test(`the phone House page with ${name} fits the height budget in ${lang}`, async ({
      page,
      context,
      baseURL,
    }) => {
      await page.setViewportSize({ width: 400, height: 900 });
      await scenario(context, value ? `${tag()}.${value}` : tag(), baseURL);
      await language(page, lang);
      await page.goto('./#/house');
      await expect(page.getByTestId('house-facts-input')).toBeVisible();
      await page.getByTestId('house-facts-input-details').locator('summary').click();
      await expect(page.locator('#field-house_occupants')).toBeVisible();
      const dims = await size(page);
      expect(dims.scroll).toBeLessThanOrEqual(dims.inner);
      expect(dims.height, `phone height ${name} ${lang}`).toBeLessThanOrEqual(
        allowedHeight(PHONE_BUDGET),
      );
    });
  }
}

test('the facts card comes last and the heat-loss cards come first', async ({
  page,
  context,
  baseURL,
}) => {
  await page.setViewportSize({ width: 1400, height: 900 });
  await scenario(context, tag(), baseURL);
  await language(page, 'en');
  await page.goto('./#/house');
  await expect(page.getByTestId('house-facts-input')).toBeVisible();
  const top = async (id: string) => (await page.getByTestId(id).boundingBox())?.y ?? 0;
  const facts = await top('house-facts-input');
  for (const id of ['house-loss-now', 'house-heat-pump', 'house-loss-fit', 'house-by-weather'])
    expect(await top(id), id).toBeLessThan(facts);
  await expect(page.getByTestId('house-facts-input-details')).not.toHaveAttribute('open', '');
});

test('the House page asks the service for no model data', async ({ page, context, baseURL }) => {
  await scenario(context, tag(), baseURL);
  await language(page, 'en');
  const asked: string[] = [];
  page.on('request', (request) => {
    const url = request.url();
    if (/\/api\/v1\/insight\/house/.test(url)) asked.push(url);
  });
  await page.goto('./#/house');
  await expect(page.getByTestId('house-loss-now')).toBeVisible();
  await page.goto('about:blank');
  await page.goto('./#/more');
  await expect(page.getByTestId('more-house')).toBeVisible();
  expect(asked).toEqual([]);
});

test('an old deep link to a removed tab still shows the House page', async ({
  page,
  context,
  baseURL,
}) => {
  await scenario(context, tag(), baseURL);
  await language(page, 'en');
  for (const hash of ['#/house/model', '#/house/learning', '#/house/what-if']) {
    await page.goto('about:blank');
    await page.goto(`./${hash}`);
    await expect(page.getByTestId('house-loss-now')).toBeVisible();
    await expect(page.getByTestId('house-facts-input')).toBeVisible();
  }
});

test('the Dutch page uses the Dutch terms', async ({ page, context, baseURL }) => {
  await scenario(context, tag(), baseURL);
  await language(page, 'nl');
  await page.goto('./#/house');
  await expect(page.getByTestId('house-loss-now')).toContainText('Warmteverlies nu');
  await expect(page.getByTestId('house-heat-pump')).toContainText('aanvoertemperatuur');
  await expect(page.getByTestId('house-loss-night')).toContainText('doorgetrokken');
  await expect(page.getByTestId('house-by-weather')).toContainText('Warmteproductie');
  await expect(page.getByTestId('house-facts-input')).toContainText('Wat je van het huis weet');
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
  await expect(more).toContainText('What you know about the house');
  await more.click();
  await expect(page).toHaveURL(/#\/house$/);
});

test('the desktop navigation reaches House and Settings', async ({ page, context, baseURL }) => {
  await page.setViewportSize({ width: 1400, height: 900 });
  await scenario(context, tag(), baseURL);
  await language(page, 'en');
  await page.goto('./#/home');
  const nav = page.getByTestId('top-nav');
  await expect(nav.getByRole('link', { name: 'Settings' })).toHaveCount(0);
  await nav.getByRole('link', { name: 'House' }).click();
  await expect(page).toHaveURL(/#\/house$/);
  await expect(nav.getByRole('link', { name: 'House' })).toHaveAttribute('aria-current', 'page');
  await expect(page.getByTestId('house-loss-now')).toBeVisible();
  await page.getByTestId('nav-settings').click();
  await expect(page).toHaveURL(/#\/settings$/);
  await expect(page.getByTestId('nav-settings')).toHaveAttribute('aria-current', 'page');
  await expect(page.getByTestId('settings-overview')).toBeVisible();
});

test('a fact edited on the House page goes through the draft bar and applies', async ({
  page,
  context,
  baseURL,
}) => {
  await scenario(context, tag(), baseURL);
  await language(page, 'en');
  await page.goto('./#/house');
  const card = page.getByTestId('house-facts-input');
  await expect(card).toContainText('What you know about the house');
  await expect(page.getByTestId('house-facts-input-details')).not.toHaveAttribute('open', '');
  await expect(card).toContainText('1 set');
  await page.getByTestId('house-facts-input-details').locator('summary').click();
  await expect(page.getByTestId('field-house_build_period')).toBeVisible();
  await page.locator('select#field-house_build_period').selectOption('1975_1991');
  await expect(page.getByTestId('draft-count')).toHaveText('1 change');
  await expect(card).toContainText('1 change');
  await applyDraft(page);
  await expect(page.getByTestId('draft-bar')).toHaveCount(0);
  await expect(card).toContainText('2 set');
  await expect(page.locator('select#field-house_build_period')).toHaveValue('1975_1991');
  await page.goto('./#/settings/house');
  await expect(page.locator('select#field-house_build_period')).toHaveValue('1975_1991');
});

test('Settings → House shows the same fields as the House page', async ({
  page,
  context,
  baseURL,
}) => {
  await scenario(context, `${tag()}.house:facts`, baseURL);
  await language(page, 'en');
  await page.goto('./#/settings/house');
  const section = page.getByTestId('house-section');
  await expect(section.getByTestId('house-subset-facts')).toBeVisible();
  await expect(section.locator('[data-testid^="house-subset-"]')).toHaveCount(1);
  await expect(page.locator('select#field-house_build_period')).toHaveValue('1975_1991');
  await expect(page.locator('#field-house_occupants')).toHaveValue('3');
  await expect(page.locator('#field-house_floor_heating_share')).toHaveCount(0);
  await expect(page.getByText('Share of floor heating')).toHaveCount(0);
  await page.goto('./#/house');
  await expect(page.locator('select#field-house_build_period')).toHaveCount(0);
  await page.getByTestId('house-facts-input-details').locator('summary').click();
  await expect(page.locator('select#field-house_build_period')).toHaveValue('1975_1991');
  await expect(page.locator('#field-house_occupants')).toHaveValue('3');
});

test('the facts card counts the facts that are set, in both languages', async ({
  page,
  context,
  baseURL,
}) => {
  await scenario(context, `${tag()}.house:facts`, baseURL);
  await language(page, 'en');
  await page.goto('./#/house');
  await expect(page.getByTestId('house-facts-input-details')).not.toHaveAttribute('open', '');
  await expect(page.getByTestId('house-facts-input')).toContainText('3 set');
  await language(page, 'nl');
  await page.goto('about:blank');
  await page.goto('./#/house');
  await expect(page.getByTestId('house-facts-input')).toContainText('3 ingevuld');
});

test('no model settings are left on the House page or in Settings', async ({
  page,
  context,
  baseURL,
}) => {
  await scenario(context, tag(), baseURL);
  await language(page, 'en');
  for (const hash of ['#/house', '#/settings/house']) {
    await page.goto('about:blank');
    await page.goto(`./${hash}`);
    await expect(page.locator('#field-house_ua_min_w_per_k')).toHaveCount(0);
    await expect(page.locator('#field-house_learn_fit_days')).toHaveCount(0);
    await expect(page.locator('#field-control_model_use')).toHaveCount(0);
  }
});

test.describe('house basics states', () => {
  test('credible: the loss now, the extrapolations and the heat from the pump', async ({
    page,
    context,
    baseURL,
  }) => {
    await scenario(context, tag(), baseURL);
    await language(page, 'en');
    await page.goto('./#/house');
    await expect(page.getByTestId('house-loss-value')).toContainText('2.8');
    await expect(page.getByTestId('house-loss-provisional')).toHaveCount(0);
    await expect(page.getByTestId('house-loss-basis')).toContainText('2 °C outside');
    await expect(page.getByTestId('house-loss-beyond')).toHaveCount(0);
    await expect(page.getByTestId('house-loss-night')).toContainText('extrapolated');
    await expect(page.getByTestId('house-loss-design')).toContainText('−10 °C');
    await expect(page.getByTestId('house-loss-design')).toContainText('extrapolated');
    await expect(page.getByTestId('house-delivered-now')).toContainText('3.1 kW');
    await expect(page.getByTestId('house-delivered-mean')).toContainText('2.7 kW');
    await expect(page.getByTestId('house-steady-note')).toContainText('Under-floor heating');
    await expect(page.getByTestId('house-by-weather-note')).toContainText('own electricity');
    await expect(page.getByTestId('house-loss-fit')).not.toHaveAttribute('open', '');
  });

  test('the supply slider shows a shortfall, a balance and a surplus', async ({
    page,
    context,
    baseURL,
  }) => {
    await scenario(context, tag(), baseURL);
    await language(page, 'en');
    await page.goto('./#/house');
    const slider = page.getByTestId('house-supply-slider');
    await expect(slider).toBeVisible();
    await expect(page.getByTestId('house-supply-value')).toContainText('30 °C supply');
    await expect(page.getByTestId('house-balance')).toContainText('about 29');
    await slider.focus();
    await page.keyboard.press('Home');
    await expect(page.getByTestId('house-supply-value')).toContainText('25 °C supply');
    await expect(page.getByTestId('house-verdict')).toHaveAttribute('data-verdict', 'shortfall');
    await expect(page.getByTestId('house-verdict')).toContainText('Shortfall of');
    await page.keyboard.press('End');
    await expect(page.getByTestId('house-supply-value')).toContainText('45 °C supply');
    await expect(page.getByTestId('house-verdict')).toHaveAttribute('data-verdict', 'surplus');
    await expect(page.getByTestId('house-verdict')).toContainText('Surplus of');
  });

  test('the fit opens to a scatter with used, outlier and near-balance marks', async ({
    page,
    context,
    baseURL,
  }) => {
    await scenario(context, tag(), baseURL);
    await language(page, 'en');
    await page.goto('./#/house');
    await page.getByTestId('house-loss-fit').locator('summary').click();
    await expect(page.getByTestId('scatter-line')).toBeVisible();
    for (const mark of ['used', 'outlier', 'near_balance'])
      await expect(
        page.locator(`[data-testid="scatter-point"][data-mark="${mark}"]`).first(),
      ).toBeVisible();
    await expect(page.getByTestId('house-fit-h')).toContainText('180 W/K');
    await expect(page.getByTestId('house-fit-days')).toContainText('44');
    await expect(page.getByTestId('house-fit-excluded')).toContainText('Wood stove in use: 4');
    await expect(page.getByTestId('house-fit-limits')).toContainText('sun is not modelled');
  });

  test('provisional: a number with a provisional pill and the reasons', async ({
    page,
    context,
    baseURL,
  }) => {
    await scenario(context, `${tag()}.basics:provisional`, baseURL);
    await language(page, 'en');
    await page.goto('./#/house');
    await expect(page.getByTestId('house-loss-value')).toBeVisible();
    await expect(page.getByTestId('house-loss-provisional')).toHaveText('provisional');
    await expect(page.getByTestId('house-loss-reasons')).toContainText('Fewer than 30 days');
    await expect(page.getByTestId('house-heat-provisional')).toBeVisible();
  });

  test('collecting: no number, the days so far and the reasons in words', async ({
    page,
    context,
    baseURL,
  }) => {
    await scenario(context, `${tag()}.basics:collecting`, baseURL);
    await language(page, 'en');
    await page.goto('./#/house');
    const card = page.getByTestId('house-collecting');
    await expect(card).toContainText('6 of 10 qualifying days');
    await expect(page.getByTestId('house-collecting-reasons')).toContainText(
      'Not enough qualifying days yet',
    );
    await expect(page.getByTestId('house-collecting-excluded')).toContainText(
      'Wood stove in use: 3',
    );
    await expect(page.getByTestId('house-loss-now')).toHaveCount(0);
    await expect(page.getByTestId('house-loss-value')).toHaveCount(0);
    await expect(page.getByTestId('house-loss-fit')).toHaveCount(0);
    await expect(page.getByTestId('house-emitter-collecting')).toBeVisible();
  });

  test('collecting in Dutch uses the Dutch reasons', async ({ page, context, baseURL }) => {
    await scenario(context, `${tag()}.basics:collecting`, baseURL);
    await language(page, 'nl');
    await page.goto('./#/house');
    await expect(page.getByTestId('house-collecting')).toContainText('6 van de 10 bruikbare dagen');
    await expect(page.getByTestId('house-collecting-reasons')).toContainText(
      'Nog te weinig bruikbare dagen',
    );
  });

  test('disabled: one card that says so and links to the setting', async ({
    page,
    context,
    baseURL,
  }) => {
    await scenario(context, `${tag()}.basics:off`, baseURL);
    await language(page, 'en');
    await page.goto('./#/house');
    await expect(page.getByTestId('house-disabled')).toContainText('House basics are off');
    await expect(page.getByTestId('house-loss-now')).toHaveCount(0);
    await expect(page.getByTestId('house-heat-pump')).toHaveCount(0);
    await expect(page.getByTestId('house-facts-input')).toBeVisible();
    await page.getByTestId('house-disabled-link').click();
    await expect(page).toHaveURL(/#\/settings\/house$/);
    await expect(page.locator('#field-house_basics_enabled')).toBeVisible();
  });

  test('a request error says so and the retry loads the figures', async ({
    page,
    context,
    baseURL,
  }) => {
    await scenario(context, `${tag()}.basics:error`, baseURL);
    await language(page, 'en');
    await page.goto('./#/house');
    await expect(page.getByTestId('house-basics-error')).toContainText('could not be loaded');
    await expect(page.getByTestId('house-loss-now')).toHaveCount(0);
    await expect(page.getByTestId('house-facts-input')).toBeVisible();
    const again = page.waitForRequest(/\/api\/v1\/insight\/basics/);
    await page.getByTestId('house-basics-retry').click();
    await again;
  });
});
