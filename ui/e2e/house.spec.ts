import { expect, test, type BrowserContext, type Page } from '@playwright/test';
import { allowedHeight } from './budget';

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

const TABS: [string, string, string[]][] = [
  ['overview', '#/house', ['house-status', 'house-score', 'house-facts']],
  ['model', '#/house/model', ['house-signature', 'house-quality']],
  ['learning', '#/house/learning', ['house-run', 'house-timeline', 'house-proposal']],
];

for (const width of [1400, 400]) {
  test(`every tab shows its cards without overflow at ${width} px`, async ({
    page,
    context,
    baseURL,
  }) => {
    await page.setViewportSize({ width, height: 900 });
    await scenario(context, tag(), baseURL);
    await language(page, 'en');
    for (const [name, hash, cards] of TABS) {
      await page.goto(`./${hash}`);
      await expect(page.getByTestId('house-page')).toHaveAttribute('data-tab', name);
      for (const id of cards) await expect(page.getByTestId(id)).toBeVisible();
      const dims = await size(page);
      expect(dims.scroll, `overflow on ${name}`).toBeLessThanOrEqual(dims.inner);
    }
    await page.goto('./#/house');
    await expect(page.getByTestId('house-score')).toContainText('240');
    await expect(page.getByTestId('house-band')).toContainText('Band C');
    await expect(page.getByTestId('house-band-limits')).toContainText('45–60');
    await expect(page.getByTestId('house-indicative')).toHaveText(
      'Indicative, not the official energielabel.',
    );
    await expect(page.getByTestId('house-fact-balance')).toContainText('16.5');
    await expect(page.getByTestId('house-status-credible')).toHaveText('Credible');
    await expect(page.getByTestId('house-status-age')).toContainText(
      'became the model in use today',
    );
  });
}

for (const lang of ['en', 'nl'] as const) {
  for (const [name, hash, cards] of TABS) {
    test(`the phone ${name} tab fits the height budget in ${lang}`, async ({
      page,
      context,
      baseURL,
    }) => {
      await page.setViewportSize({ width: 400, height: 900 });
      await scenario(context, tag(), baseURL);
      await language(page, lang);
      await page.goto(`./${hash}`);
      await expect(page.getByTestId(cards[cards.length - 1]!)).toBeVisible();
      const dims = await size(page);
      expect(dims.scroll).toBeLessThanOrEqual(dims.inner);
      expect(dims.height, `phone height ${name} ${lang}`).toBeLessThanOrEqual(
        allowedHeight(PHONE_BUDGET),
      );
    });
  }
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
  await page.goto('./#/house/model');
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
  await expect(page.getByTestId('house-status-credible')).toHaveText('Still learning');
  await page.goto('./#/house/learning');
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
  await page.goto('./#/house/learning');
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
  await expect(page.getByTestId('house-score')).toBeVisible();
  await page.getByTestId('nav-settings').click();
  await expect(page).toHaveURL(/#\/settings$/);
  await expect(page.getByTestId('nav-settings')).toHaveAttribute('aria-current', 'page');
  await expect(page.getByTestId('settings-overview')).toBeVisible();
});

test('the tabs switch and keep their deep links', async ({ page, context, baseURL }) => {
  await page.setViewportSize({ width: 1400, height: 900 });
  await scenario(context, tag(), baseURL);
  await language(page, 'en');
  await page.goto('./#/house');
  const tabs = page.getByRole('navigation', { name: 'House sections' });
  await expect(tabs.getByRole('link', { name: 'Overview' })).toHaveAttribute(
    'aria-current',
    'page',
  );
  await tabs.getByRole('link', { name: 'Model' }).click();
  await expect(page).toHaveURL(/#\/house\/model$/);
  await expect(page.getByTestId('house-signature')).toBeVisible();
  await expect(page.getByTestId('house-score')).toHaveCount(0);
  await tabs.getByRole('link', { name: 'Learning' }).click();
  await expect(page).toHaveURL(/#\/house\/learning$/);
  await expect(page.getByTestId('house-run')).toBeVisible();
  await expect(page.getByTestId('house-signature')).toHaveCount(0);
  await page.goto('./#/house/nonsense');
  await expect(page.getByTestId('house-page')).toHaveAttribute('data-tab', 'overview');
  await page.goto('./#/house/learning');
  await expect(page.getByTestId('house-timeline')).toBeVisible();
});

test('the timeline shows the daily error, the left-out periods and what the model was fitted on', async ({
  page,
  context,
  baseURL,
}) => {
  await scenario(context, tag(), baseURL);
  await language(page, 'en');
  await page.goto('./#/house/learning');
  await expect(page.getByTestId('daily-error-plot')).toHaveAttribute(
    'aria-label',
    /14 test days: .* within .* to .* K/,
  );
  await expect(page.getByTestId('daily-error-plot')).toHaveAttribute('data-bars', '14');
  await expect(page.getByTestId('daily-error-table')).toHaveCount(0);
  await page.getByTestId('daily-error-toggle').click();
  await expect(page.getByTestId('daily-error-table').locator('tbody tr')).toHaveCount(14);
  await expect(page.getByTestId('run-errors')).toContainText('0.112 → 0.101 → 0.093');
  await expect(page.getByTestId('left-out')).toContainText('Wood stove');
  await expect(page.getByTestId('left-out')).toContainText('5 h');
  await expect(page.getByTestId('excluded-days')).toContainText('1');
  await expect(page.getByTestId('house-fitted')).toContainText('House only');
  await expect(page.getByTestId('house-fitted')).toContainText('41 days');
});

test('Run now starts the learner, shows it running and reloads when it is done', async ({
  page,
  context,
  baseURL,
}) => {
  await scenario(context, tag(), baseURL);
  await language(page, 'en');
  await page.goto('./#/house/learning');
  const state = page.getByTestId('run-state');
  await expect(state).toHaveAttribute('data-kind', 'scheduled');
  await expect(page.getByTestId('run-outcome')).toContainText('New model in use');
  const reloads: string[] = [];
  page.on('request', (request) => {
    if (/\/api\/v1\/insight\/house$/.test(request.url())) reloads.push(request.url());
  });
  await page.getByTestId('run-now').click();
  await expect(state).toHaveAttribute('data-kind', 'running');
  await expect(page.getByTestId('run-now')).toBeDisabled();
  await expect(state).toHaveAttribute('data-kind', 'scheduled', { timeout: 20_000 });
  await expect(page.getByTestId('run-outcome')).toContainText('Previous model kept');
  await expect(page.getByTestId('run-now')).toBeEnabled();
  expect(reloads.length, 'the house data is loaded again after the run').toBeGreaterThan(0);
});

for (const [value, kind, text] of [
  ['learner:running', 'running', 'A run started'],
  ['learner:unavailable', 'unavailable', 'no built-in learner'],
  ['learner:disabled', 'disabled', 'switched off'],
] as const) {
  test(`${value} says so in plain words`, async ({ page, context, baseURL }) => {
    await scenario(context, `${tag()}.${value}`, baseURL);
    await language(page, 'en');
    await page.goto('./#/house/learning');
    await expect(page.getByTestId('run-state')).toHaveAttribute('data-kind', kind);
    await expect(page.getByTestId('run-state')).toContainText(text);
    if (kind === 'disabled') await expect(page.getByTestId('run-now')).toBeEnabled();
    else await expect(page.getByTestId('run-now')).toBeDisabled();
  });
}

test('learner:failed shows the last failure and its reason', async ({ page, context, baseURL }) => {
  await scenario(context, `${tag()}.learner:failed`, baseURL);
  await language(page, 'en');
  await page.goto('./#/house/learning');
  await expect(page.getByTestId('run-failure')).toContainText('it took too long and was stopped');
  await expect(page.getByTestId('run-failure')).toContainText('stopped after 1800 s');
  await expect(page.getByTestId('run-outcome')).toContainText('Failed');
  await page.getByTestId('run-now').click();
  await expect(page.getByTestId('run-outcome')).toContainText('Previous model kept', {
    timeout: 20_000,
  });
  await expect(page.getByTestId('run-failure')).toHaveCount(0);
});

test('a read-only login is told why Run now does not work', async ({ page, context, baseURL }) => {
  await scenario(context, `${tag()}.role:viewer`, baseURL);
  await language(page, 'en');
  await page.goto('./#/house/learning');
  await page.getByTestId('run-now').click();
  await expect(page.getByTestId('run-error')).toContainText('operate or admin role');
  await expect(page.getByTestId('run-state')).toHaveAttribute('data-kind', 'scheduled');
});

test('an older service without the run endpoint hides the learner card calmly', async ({
  page,
  context,
  baseURL,
}) => {
  await scenario(context, tag(), baseURL);
  await language(page, 'en');
  await page.route('**/api/v1/insight/house/run', (route) =>
    route.fulfill({ status: 404, json: { detail: 'Not Found' } }),
  );
  await page.goto('./#/house/learning');
  await expect(page.getByTestId('house-timeline')).toBeVisible();
  await expect(page.getByTestId('house-run')).toHaveCount(0);
});

for (const [value, expect_] of [
  ['house:learning', 'Not enough data yet'],
  ['house:notrun', null],
] as const) {
  test(`${value} shows the learner card, so a new user sees learning happen`, async ({
    page,
    context,
    baseURL,
  }) => {
    await page.setViewportSize({ width: 400, height: 900 });
    await scenario(context, `${tag()}.${value}`, baseURL);
    await language(page, 'en');
    await page.goto('./#/house');
    await expect(page.getByTestId('house-run')).toBeVisible();
    await expect(page.getByTestId('run-state')).toContainText('Next run');
    await expect(page.getByTestId('run-expect')).toContainText('first model');
    if (expect_) await expect(page.getByTestId('run-outcome')).toContainText(expect_);
    else await expect(page.getByTestId('run-never')).toBeVisible();
    const dims = await size(page);
    expect(dims.scroll).toBeLessThanOrEqual(dims.inner);
    expect(dims.height).toBeLessThanOrEqual(allowedHeight(PHONE_BUDGET));
  });
}

test('the Dutch learning tab speaks Dutch', async ({ page, context, baseURL }) => {
  await scenario(context, tag(), baseURL);
  await language(page, 'nl');
  await page.goto('./#/house/learning');
  await expect(page.getByTestId('house-run')).toContainText('Het leerprogramma');
  await expect(page.getByTestId('run-now')).toHaveText('Nu uitvoeren');
  await expect(page.getByTestId('house-timeline')).toContainText('Kamerfout per dag');
});
