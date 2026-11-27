import { expect, test, type BrowserContext, type Page } from '@playwright/test';
import { allowedHeight } from './budget';
import { pinCycleMinute } from './clock';

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
  [
    'overview',
    '#/house',
    ['house-status', 'house-schematic', 'house-score', 'house-facts', 'house-facts-input'],
  ],
  [
    'model',
    '#/house/model',
    ['house-signature', 'house-prediction', 'house-quality', 'house-bounds-card'],
  ],
  ['control', '#/house/control', ['house-control']],
  [
    'learning',
    '#/house/learning',
    ['house-run', 'house-learning-settings', 'house-timeline', 'house-proposal'],
  ],
  ['what-if', '#/house/what-if', ['house-whatif', 'whatif-results']],
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
      await page.screenshot({ path: `e2e/shots/house-${name}-${width}.png`, fullPage: true });
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

async function applyDraft(page: Page): Promise<void> {
  await page.getByTestId('draft-review').click();
  await page.getByTestId('preview-apply').click();
  await expect(page.getByTestId('preview-dialog')).toBeHidden();
  await expect(page.getByTestId('apply-notice')).toContainText(/Version \d+/);
}

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
  await expect(page.getByTestId('field-house_build_period')).toBeVisible();
  await page.locator('select#field-house_build_period').selectOption('1975_1991');
  await expect(page.getByTestId('draft-count')).toHaveText('1 change');
  await expect(page.getByTestId('house-pending')).toHaveAttribute('data-source', 'draft');
  await applyDraft(page);
  await expect(page.getByTestId('draft-bar')).toHaveCount(0);
  await expect(page.getByTestId('house-facts-input-details')).not.toHaveAttribute('open', '');
  await expect(page.getByTestId('house-pending')).toHaveAttribute('data-source', 'stored');
  await page.getByTestId('house-facts-input-details').locator('summary').click();
  await expect(page.locator('select#field-house_build_period')).toHaveValue('1975_1991');
  await page.goto('./#/settings/house');
  await expect(page.locator('select#field-house_build_period')).toHaveValue('1975_1991');
});

test('pinning the heat loss with equal limits applies and shows the pin', async ({
  page,
  context,
  baseURL,
}) => {
  await scenario(context, tag(), baseURL);
  await language(page, 'en');
  await page.goto('./#/house/model');
  const card = page.getByTestId('house-bounds-card');
  await expect(card.getByTestId('bounds-explain')).toContainText('pin the value');
  await card.getByTestId('house-bounds-card-details').locator('summary').click();
  await expect(page.getByTestId('bound-learned-ua')).toContainText('Learned: 240 W/K');
  await expect(page.getByTestId('bound-learned-ua')).toContainText('90 % range 230–251');
  await page.locator('#field-house_ua_min_w_per_k').fill('250');
  await page.locator('#field-house_ua_max_w_per_k').fill('250');
  await expect(page.getByTestId('draft-count')).toHaveText('2 changes');
  await expect(page.getByTestId('bound-pinned-ua')).toBeVisible();
  await applyDraft(page);
  await expect(page.locator('#field-house_ua_min_w_per_k')).toHaveValue('250');
  await expect(page.getByTestId('bound-pinned-ua')).toBeVisible();
});

test('a minimum above its maximum is refused by the service and explained', async ({
  page,
  context,
  baseURL,
}) => {
  await scenario(context, tag(), baseURL);
  await language(page, 'en');
  await page.goto('./#/house/model');
  await page.getByTestId('house-bounds-card-details').locator('summary').click();
  await page.locator('#field-house_ua_min_w_per_k').fill('300');
  await page.locator('#field-house_ua_max_w_per_k').fill('200');
  await expect(page.getByTestId('field-house_ua_max_w_per_k')).toContainText(
    'Heat loss, at least (300 W/K) must not exceed Heat loss, at most (200 W/K).',
  );
  await page.getByTestId('draft-review').click();
  await expect(page.getByTestId('preview-errors')).toContainText('must not exceed');
  await expect(page.getByTestId('preview-apply')).toBeDisabled();
});

test('days left out are added and removed in the editor and the timeline', async ({
  page,
  context,
  baseURL,
}) => {
  await scenario(context, tag(), baseURL);
  await language(page, 'en');
  await page.goto('./#/house/learning');
  await page.getByTestId('house-learning-settings-details').locator('summary').click();
  await page.getByTestId('excluded-day-input').fill('2026-11-02');
  await page.getByTestId('excluded-day-add').click();
  await expect(page.getByTestId('excluded-chip-2026-11-02')).toBeVisible();
  await expect(page.getByTestId('draft-count')).toHaveText('1 change');
  await page.getByRole('button', { name: /Take .* back in/ }).click();
  await expect(page.getByTestId('excluded-days-none')).toBeVisible();
  await expect(page.getByTestId('draft-bar')).toHaveCount(0);

  await expect(page.getByTestId('leave-out-why')).toContainText('holiday');
  const bar = page.locator('[data-testid^="day-bar-"]').first();
  const day = ((await bar.getAttribute('data-testid')) ?? '').replace('day-bar-', '');
  await bar.focus();
  await page.keyboard.press('Enter');
  await expect(bar).toHaveAttribute('aria-pressed', 'true');
  await expect(page.getByTestId('draft-count')).toHaveText('1 change');
  await expect(page.getByTestId(`excluded-chip-${day}`)).toBeVisible();
  await page.keyboard.press('Space');
  await expect(bar).toHaveAttribute('aria-pressed', 'false');
  await expect(page.getByTestId('draft-bar')).toHaveCount(0);

  await page.getByTestId('daily-error-toggle').click();
  const toggle = page.getByTestId(`day-toggle-${day}`);
  await toggle.click();
  await expect(toggle).toHaveAttribute('aria-pressed', 'true');
  await expect(page.getByTestId(`excluded-chip-${day}`)).toBeVisible();
  await applyDraft(page);
  await expect(page.getByTestId(`excluded-chip-${day}`)).toBeVisible();
  await toggle.click();
  await expect(page.getByTestId('draft-count')).toHaveText('1 change');
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
  for (const subset of ['facts', 'bounds', 'learning'])
    await expect(section.getByTestId(`house-subset-${subset}`)).toBeVisible();
  await expect(page.locator('select#field-house_build_period')).toHaveValue('1975_1991');
  await expect(page.locator('#field-house_occupants')).toHaveValue('3');
  await expect(page.locator('#field-house_floor_heating_share')).toHaveValue('60');
  await page.getByTestId('advanced-house_bounds').locator('summary').click();
  await expect(page.locator('#field-house_ua_min_w_per_k')).toHaveValue('200');
  await page.getByTestId('advanced-house_learning').locator('summary').click();
  await expect(page.getByTestId('excluded-days-list').locator('li')).toHaveCount(1);
  await page.screenshot({ path: 'e2e/shots/house-settings-1400.png', fullPage: true });
  await page.goto('./#/house');
  await expect(page.locator('select#field-house_build_period')).toHaveCount(0);
  await page.getByTestId('house-facts-input-details').locator('summary').click();
  await expect(page.locator('select#field-house_build_period')).toHaveValue('1975_1991');
});

test('while the model is still learning the facts card is open and first', async ({
  page,
  context,
  baseURL,
}) => {
  await page.setViewportSize({ width: 400, height: 900 });
  await scenario(context, `${tag()}.house:learning`, baseURL);
  await language(page, 'en');
  await page.goto('./#/house');
  await expect(page.getByTestId('house-facts-intro')).toBeVisible();
  await expect(page.locator('select#field-house_build_period')).toBeVisible();
  await page.locator('#field-house_occupants').fill('3');
  await expect(page.getByTestId('draft-count')).toHaveText('1 change');
  const dims = await size(page);
  expect(dims.scroll).toBeLessThanOrEqual(dims.inner);
  await page.screenshot({ path: 'e2e/shots/house-learning-state-400.png', fullPage: true });
});

for (const lang of ['en', 'nl'] as const) {
  for (const [name, hash, cards] of TABS) {
    test(`the phone ${name} tab with facts and bounds set fits the budget in ${lang}`, async ({
      page,
      context,
      baseURL,
    }) => {
      await page.setViewportSize({ width: 400, height: 900 });
      await scenario(context, `${tag()}.house:facts`, baseURL);
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

test('the Dutch House cards use natural Dutch', async ({ page, context, baseURL }) => {
  await scenario(context, `${tag()}.house:facts`, baseURL);
  await language(page, 'nl');
  await page.goto('./#/house/model');
  await expect(page.getByTestId('house-bounds-card')).toContainText(
    'Geleerde waarden vastzetten of begrenzen',
  );
  await expect(page.getByTestId('bound-learned-ua')).toContainText('bereik van 90 %');
  await page.goto('./#/house');
  await expect(page.getByTestId('house-facts-input')).toContainText('Wat je van het huis weet');
});

const shotPath = (tab: string, width: number, scheme = '') =>
  `e2e/shots/house-s3-${tab}-${width}${scheme}.png`;

for (const width of [1400, 400]) {
  test(`session 3 screenshots at ${width} px`, async ({ page, context, baseURL }) => {
    await page.setViewportSize({ width, height: 900 });
    await scenario(context, tag(), baseURL);
    await language(page, 'en');
    for (const [name, hash, cards] of TABS) {
      await page.goto(`./${hash}`);
      for (const id of cards) await expect(page.getByTestId(id)).toBeVisible();
      await page.waitForTimeout(400);
      await page.screenshot({ path: shotPath(name, width), fullPage: true });
    }
    if (width === 1400) {
      await page.emulateMedia({ colorScheme: 'dark' });
      await page.goto('./#/house');
      await expect(page.getByTestId('house-schematic-svg')).toBeVisible();
      await page.waitForTimeout(400);
      await page.screenshot({ path: shotPath('overview', width, '-dark'), fullPage: true });
    }
  });
}

test('the schematic shows the flows of the moment and says them in one sentence', async ({
  page,
  context,
  baseURL,
}) => {
  await page.setViewportSize({ width: 1400, height: 900 });
  await scenario(context, tag(), baseURL);
  await language(page, 'en');
  await page.goto('./#/house');
  const svg = page.getByTestId('house-schematic-svg');
  await expect(svg).toHaveAttribute('data-layout', 'wide');
  await expect(svg).toHaveAttribute('role', 'img');
  const sentence = page.getByTestId('house-balance-sentence');
  await expect(sentence).toContainText(
    /^Right now the house loses about [\d.,]+\s(kW|W) to outside; the heat pump delivers /,
  );
  await expect(svg).toHaveAttribute('aria-label', (await sentence.textContent()) ?? '');
  await expect(page.getByTestId('house-balance-source')).toHaveText('Measured model');
  await expect(svg).toContainText('Heat pump');
  await expect(svg).toContainText('Building mass');
  await page.setViewportSize({ width: 400, height: 900 });
  await expect(svg).toHaveAttribute('data-layout', 'narrow');
  await expect(sentence).toBeVisible();
});

test('the schematic is an estimate while the model is still learning', async ({
  page,
  context,
  baseURL,
}) => {
  await scenario(context, `${tag()}.house:learning`, baseURL);
  await language(page, 'en');
  await page.goto('./#/house');
  await expect(page.getByTestId('house-schematic')).toBeVisible();
  await expect(page.getByTestId('house-balance-source')).toHaveText(
    'Estimate from your answers, not measured',
  );
  await expect(page.getByTestId('house-balance-sentence')).toContainText('Right now the house');
});

test('without a model or facts the schematic asks for the facts', async ({
  page,
  context,
  baseURL,
}) => {
  await scenario(context, `${tag()}.house:learning.balance:missing`, baseURL);
  await language(page, 'en');
  await page.goto('./#/house');
  await expect(page.getByTestId('house-schematic-hint')).toContainText('Fill in a few facts');
  await page.getByTestId('house-schematic-facts').click();
  await expect(page.getByTestId('house-facts-input')).toBeInViewport();
});

test('a burning wood stove makes the storage unknown, never zero', async ({
  page,
  context,
  baseURL,
}) => {
  await scenario(context, `${tag()}.stove:active`, baseURL);
  await language(page, 'en');
  await page.goto('./#/house');
  const svg = page.getByTestId('house-schematic-svg');
  await expect(svg).toHaveAttribute('data-storage', 'unknown');
  await expect(svg).toContainText('Wood stove');
  await expect(page.getByTestId('house-balance-sentence')).toContainText(
    'the wood stove is burning too, so how much heat the building stores is not known',
  );
});

test('an unknown sun is drawn as unknown and not as zero', async ({ page, context, baseURL }) => {
  await scenario(context, `${tag()}.balance:nosun`, baseURL);
  await language(page, 'en');
  await page.goto('./#/house');
  await expect(page.getByTestId('house-schematic-svg')).toHaveAttribute('data-storage', 'unknown');
  await expect(page.getByTestId('house-schematic-svg')).toContainText('unknown');
  await expect(page.getByTestId('house-balance-sentence')).toContainText(
    "the sun's share is not known",
  );
});

test('an older service hides the new parts calmly', async ({ page, context, baseURL }) => {
  await page.setViewportSize({ width: 1400, height: 900 });
  await scenario(context, `${tag()}.balance:absent`, baseURL);
  await language(page, 'en');
  await page.goto('./#/house');
  await expect(page.getByTestId('house-score')).toBeVisible();
  await expect(page.getByTestId('house-schematic')).toHaveCount(0);
  const tabs = page.getByRole('navigation', { name: 'House sections' });
  await expect(tabs.getByRole('link', { name: 'What if' })).toHaveCount(0);
  await page.goto('./#/house/model');
  await expect(page.getByTestId('house-quality')).toBeVisible();
  await expect(page.getByTestId('house-prediction')).toHaveCount(0);
  await page.goto('./#/house/what-if');
  await expect(page.getByTestId('whatif-absent')).toBeVisible();
});

test('the prediction chart compares measured and predicted and switches its range', async ({
  page,
  context,
  baseURL,
}) => {
  await page.setViewportSize({ width: 1400, height: 900 });
  await scenario(context, tag(), baseURL);
  await language(page, 'en');
  await page.goto('./#/house/model');
  const card = page.getByTestId('house-prediction');
  await expect(card).toBeVisible();
  await expect(page.getByTestId('house-pred-summary')).toContainText(
    /last 7 days the prediction was typically [\d.,]+ K off and at most [\d.,]+ K/,
  );
  await expect(card.getByTestId('chart-legend')).toContainText('Measured');
  await expect(card.getByTestId('chart-legend')).toContainText('Predicted 24 h ahead');
  await page.getByTestId('house-pred-range-3').click();
  await expect(page.getByTestId('house-pred-summary')).toContainText('last 3 days');
  await page.getByTestId('house-pred-range-14').click();
  await expect(page.getByTestId('house-pred-summary')).toContainText('last 14 days');
  await expect(card.getByTestId('chart-table')).toHaveCount(0);
  await card.getByTestId('chart-table-toggle').click();
  await expect(card.getByTestId('chart-table')).toBeVisible();
});

test('the heat loss and the time constant of the models are two small charts', async ({
  page,
  context,
  baseURL,
}) => {
  await scenario(context, tag(), baseURL);
  await language(page, 'en');
  await page.goto('./#/house/model');
  await expect(page.getByTestId('house-trend')).toHaveAttribute('aria-label', /3 model runs/);
  await expect(page.getByTestId('house-trend-tau')).toHaveAttribute(
    'aria-label',
    /time constant of 3 models went from 121 to 53 hours/,
  );
});

test('what you told is shown next to what was measured, with a remark when they differ', async ({
  page,
  context,
  baseURL,
}) => {
  await scenario(context, `${tag()}.house:facts`, baseURL);
  await language(page, 'en');
  await page.goto('./#/house');
  await expect(page.getByTestId('house-told-ua')).toContainText(
    'You told us ≈ 340 W/K · measured 240 W/K (90 % range 230–251)',
  );
  await expect(page.getByTestId('house-told-solar')).toHaveAttribute('data-differs', 'true');
  await expect(page.getByTestId('house-told-ua')).toHaveAttribute('data-differs', 'false');
  await expect(page.getByTestId('house-told-differs')).toContainText(
    'the model follows the measurements',
  );
});

test('a model promoted because the settings changed says so in plain words', async ({
  page,
  context,
  baseURL,
}) => {
  await scenario(context, `${tag()}.house:changed`, baseURL);
  await language(page, 'en');
  await page.goto('./#/house/model');
  await expect(page.getByTestId('house-settings-changed')).toContainText(
    'You changed the house settings, so this model took over even though it predicted slightly worse: 0.11 K against 0.1 K',
  );
});

test.describe('what if', () => {
  test('the inputs change the answer and the URL, and survive a reload', async ({
    page,
    context,
    baseURL,
  }) => {
    await page.setViewportSize({ width: 1400, height: 900 });
    await scenario(context, tag(), baseURL);
    await language(page, 'en');
    await page.goto('./#/house/what-if');
    const demand = page.getByTestId('whatif-demand');
    await expect(demand).toContainText('The heat pump has to deliver about');
    const before = (await demand.textContent()) ?? '';
    await page.getByTestId('whatif-outside-dec').click();
    await page.getByTestId('whatif-outside-dec').click();
    await expect(page).toHaveURL(/#\/house\/what-if\?.*outside=-2/);
    await expect(demand).not.toHaveText(before);
    await page.getByTestId('whatif-stove-2000').click();
    await expect(page).toHaveURL(/stove=2000/);
    await page.getByTestId('whatif-sun-150').click();
    await expect(page).toHaveURL(/sun=150/);
    await expect(page.getByTestId('whatif-sun-exact').locator('input')).toHaveValue('150');
    await expect(demand).toContainText(/2\.[34]\skW/);
    const after = (await demand.textContent()) ?? '';
    await page.reload();
    await expect(page.getByTestId('whatif-outside').locator('input')).toHaveValue('−2');
    await expect(page.getByTestId('whatif-stove-2000')).toHaveAttribute('aria-pressed', 'true');
    await expect(demand).toHaveText(after);
    await expect(page.getByTestId('whatif-water')).toContainText('Your heating curve gives');
    await expect(page.getByTestId('whatif-drift')).toHaveAttribute(
      'aria-label',
      /Room temperature over 8 hours with the heating off/,
    );
    await expect(page.getByTestId('whatif-drift-text')).toContainText(
      /With the heating off, the room cools to/,
    );
    await expect(page.getByTestId('house-whatif')).toContainText(
      'Nothing here changes any setting',
    );
  });

  test('a very cold day shows that the maximum supply limits it; a mild sunny one needs no heating', async ({
    page,
    context,
    baseURL,
  }) => {
    await scenario(context, tag(), baseURL);
    await language(page, 'en');
    await page.goto('./#/house/what-if?outside=-20');
    await expect(page.getByTestId('whatif-capped')).toContainText('Your maximum supply of 40 °C');
    await page.goto('./#/house/what-if?outside=20&sun=500');
    await expect(page.getByTestId('whatif-none')).toContainText('No heating is needed at 20');
    await expect(page.getByTestId('whatif-capped')).toHaveCount(0);
  });

  test('an estimate is marked as one', async ({ page, context, baseURL }) => {
    await scenario(context, `${tag()}.balance:estimate`, baseURL);
    await language(page, 'en');
    await page.goto('./#/house/what-if');
    await expect(page.getByTestId('whatif-source')).toHaveText(
      'Estimate from your answers, not measured.',
    );
  });

  test('without facts it points to the Overview tab', async ({ page, context, baseURL }) => {
    await scenario(context, `${tag()}.balance:missing`, baseURL);
    await language(page, 'en');
    await page.goto('./#/house/what-if');
    await expect(page.getByTestId('whatif-no-model')).toBeVisible();
    await page.getByTestId('whatif-facts').click();
    await expect(page).toHaveURL(/#\/house$/);
  });

  test('the Dutch tab and schematic speak Dutch', async ({ page, context, baseURL }) => {
    await scenario(context, tag(), baseURL);
    await language(page, 'nl');
    await page.goto('./#/house');
    await expect(page.getByRole('link', { name: 'Wat als' })).toBeVisible();
    await expect(page.getByTestId('house-balance-sentence')).toContainText(
      /^Op dit moment verliest het huis ongeveer/,
    );
    await expect(page.getByTestId('house-balance-source')).toHaveText('Gemeten model');
    await page.goto('./#/house/what-if');
    await expect(page.getByTestId('whatif-water')).toContainText('Je stooklijn geeft');
  });
});

const CONTROL_SHOTS = [
  ['off', 'modelplan:off'],
  ['shadow', 'modelplan:shadow'],
  ['dead', 'modelplan:dead'],
  ['blocked', 'modelplan:blocked'],
  ['on', 'modelplan:on'],
] as const;

test.describe('how the controller uses the model', () => {
  const card = (page: Page) => page.getByTestId('house-control');

  test('is off by default: says so, offers the switch and shows no chart', async ({
    page,
    context,
    baseURL,
  }) => {
    await scenario(context, tag(), baseURL);
    await language(page, 'en');
    await page.goto('./#/house/control');
    await expect(card(page)).toContainText('How the controller uses the model');
    await expect(page.getByTestId('house-control-pill')).toHaveText('Off');
    await expect(page.getByTestId('house-control-meaning')).toContainText('ignores the model');
    await expect(page.getByTestId('house-control-shift')).toContainText('not running');
    await expect(page.getByTestId('house-control-ready')).toBeVisible();
    await expect(page.getByTestId('house-control-summary')).toContainText('did not evaluate');
    await expect(page.getByTestId('house-control-bounds')).toHaveText(
      'At most 0.5 K down and 0.3 K up, looking 6 hours ahead.',
    );
    await expect(page.getByTestId('house-control-locked')).toContainText('locked');
    await expect(page.getByTestId('house-control-history').getByRole('img')).toHaveCount(0);
  });

  test('shadow with a set-back: would lower, the expected effect and the chart', async ({
    page,
    context,
    baseURL,
  }) => {
    await scenario(context, `modelplan:shadow.${tag()}`, baseURL);
    await language(page, 'en');
    await page.goto('./#/house/control');
    await expect(page.getByTestId('house-control-pill')).toContainText('Shadow: computes only');
    await expect(page.getByTestId('house-control-shift')).toContainText(
      /^Would lower the room target by 0\.3 K until \d\d:\d\d\.$/,
    );
    await expect(page.getByTestId('house-control-effect')).toContainText(
      'the sun is expected to warm the room by about 0.6 °C',
    );
    await expect(page.getByTestId('house-control-at')).toContainText('Last evaluated');
    const history = page.getByTestId('house-control-history');
    const summary = page.getByTestId('house-control-summary');
    await expect(summary).toContainText(
      /^In the last 7 days the model would have lowered the room target on \d days?, by at most 0\.4 K\./,
    );
    const image = history.getByRole('img').first();
    await expect(image).toHaveAttribute('aria-label', /would have lowered the room target/);
    await history.getByRole('button', { name: 'Show as table' }).click();
    await expect(history.getByRole('table')).toBeVisible();
    await expect(history.getByRole('columnheader', { name: /Computed shift/ })).toBeVisible();
  });

  test('a shadow shift is dashed only; an applied stretch is drawn solid too', async ({
    page,
    context,
    baseURL,
  }) => {
    await scenario(context, `modelplan:on.${tag()}`, baseURL);
    await language(page, 'en');
    await page.goto('./#/house/control');
    const history = page.getByTestId('house-control-history');
    await expect(history.getByRole('button', { name: /Computed shift/ })).toBeVisible();
    await expect(history.getByRole('button', { name: /Applied/ })).toBeVisible();
    await expect(history.locator('path[stroke-dasharray]').first()).toBeAttached();
    await expect(
      history.locator('svg path[stroke="var(--series-setpoint)"]').first(),
    ).toBeAttached();
  });

  test('inside the dead zone there is no shift and it says why', async ({
    page,
    context,
    baseURL,
  }) => {
    await scenario(context, `modelplan:dead.${tag()}`, baseURL);
    await language(page, 'en');
    await page.goto('./#/house/control');
    await expect(page.getByTestId('house-control-shift')).toHaveText(
      'No shift now: the expected change stays within the dead zone.',
    );
  });

  test('blocked lists its reasons, most important first', async ({ page, context, baseURL }) => {
    await scenario(context, `modelplan:blocked.${tag()}`, baseURL);
    await language(page, 'en');
    await page.goto('./#/house/control');
    const items = page.getByTestId('house-control-blocks').locator('li');
    await expect(items).toHaveText([
      'The model is not trusted yet.',
      'A wood stove was burning in the last 12 hours.',
    ]);
    await expect(page.getByTestId('house-control-shift')).toContainText('may not act');
    await expect(page.getByTestId('house-control-ready')).toHaveCount(0);
  });

  test('on, applied: says what it does, not what it would do', async ({
    page,
    context,
    baseURL,
  }) => {
    await scenario(context, `modelplan:on.${tag()}`, baseURL);
    await language(page, 'en');
    await page.goto('./#/house/control');
    await expect(page.getByTestId('house-control-pill')).toHaveText('On');
    await expect(page.getByTestId('house-control-shift')).toContainText(
      'Lowers the room target by 0.3 K until',
    );
    await expect(page.getByTestId('house-control-summary')).toContainText(
      'the model lowered the room target',
    );
    await page.goto('./#/house');
    await expect(page.getByTestId('house-status-use')).toContainText('Controller use: On');
  });

  test('an older service hides the card and the status line calmly', async ({
    page,
    context,
    baseURL,
  }) => {
    await scenario(context, `modelplan:missing.${tag()}`, baseURL);
    await language(page, 'en');
    await page.goto('./#/house/control');
    await expect(page.getByTestId('house-control-absent')).toBeVisible();
    await expect(card(page)).toHaveCount(0);
    await page.goto('./#/house');
    await expect(page.getByTestId('house-status')).toBeVisible();
    await expect(page.getByTestId('house-status-use')).toHaveCount(0);
  });

  test('newapi:missing hides it too', async ({ page, context, baseURL }) => {
    await scenario(context, `newapi:missing.${tag()}`, baseURL);
    await page.goto('./#/house/control');
    await expect(page.getByTestId('house-page')).toHaveCount(0);
    await expect(card(page)).toHaveCount(0);
  });

  test('the status line names the use and leads to the card', async ({
    page,
    context,
    baseURL,
  }) => {
    await scenario(context, `modelplan:shadow.${tag()}`, baseURL);
    await language(page, 'en');
    await page.goto('./#/house');
    await expect(page.getByTestId('house-status-use')).toContainText('Controller use: Shadow');
    await page.getByTestId('house-status-use-link').click();
    await expect(page.getByTestId('house-page')).toHaveAttribute('data-tab', 'control');
    await expect(card(page)).toBeVisible();
  });

  test('switching to shadow goes through the draft and applies', async ({
    page,
    context,
    baseURL,
  }) => {
    await scenario(context, tag(), baseURL);
    await language(page, 'en');
    await page.goto('./#/house/control');
    await expect(page.getByTestId('house-control-pill')).toHaveText('Off');
    await page.getByTestId('house-control-use-shadow').click();
    await expect(page.getByTestId('draft-count')).toHaveText('1 change');
    await expect(page.getByTestId('house-control-pill')).toHaveText('Off');
    await applyDraft(page);
    await expect(page.getByTestId('draft-bar')).toHaveCount(0);
    await expect(page.getByTestId('house-control-pill')).toContainText('Shadow', {
      timeout: 15_000,
    });
    await expect(page.getByTestId('house-control-shift')).toContainText('Would lower');
    await page.goto('./#/settings/house');
    await expect(page.getByTestId('field-control_model_use')).toBeVisible();
  });

  for (const lang of ['en', 'nl'] as const) {
    test(`on is refused with the translated message in ${lang}`, async ({
      page,
      context,
      baseURL,
    }) => {
      await scenario(context, tag(), baseURL);
      await language(page, lang);
      await page.goto('./#/house/control');
      await page.getByTestId('house-control-use-on').click();
      await expect(page.getByTestId('draft-errors')).toBeVisible({ timeout: 10_000 });
      await expect(page.getByTestId('house-control-error')).toContainText(
        lang === 'en' ? 'locked for now' : 'voorlopig vergrendeld',
      );
      await expect(page.getByTestId('house-control-error')).not.toContainText(
        'model_use_on_locked',
      );
    });
  }

  test('the advanced numbers sit in a collapsed block and edit through the draft', async ({
    page,
    context,
    baseURL,
  }) => {
    await scenario(context, tag(), baseURL);
    await language(page, 'en');
    await page.goto('./#/house/control');
    const details = page.getByTestId('house-control-advanced');
    await expect(details).not.toHaveAttribute('open', '');
    await details.locator('summary').click();
    await expect(page.getByTestId('field-control_model_max_setback_k')).toBeVisible();
    await expect(page.getByTestId('field-control_model_horizon_h')).toBeVisible();
    await page.locator('input#field-control_model_max_setback_k').fill('0.4');
    await expect(page.getByTestId('draft-count')).toHaveText('1 change');
  });

  test('a decision made with a model plan reads plainly on Home and Setpoint', async ({
    page,
    context,
    baseURL,
  }) => {
    await pinCycleMinute(context, baseURL, 130);
    await scenario(context, `modelplan:on.${tag()}`, baseURL);
    await language(page, 'en');
    await page.setViewportSize({ width: 1400, height: 1000 });
    await page.goto('./#/home');
    await page.getByTestId('why-card').locator('summary').click();
    await expect(page.getByTestId('waterfall-model-plan').first()).toContainText(
      'The house model lowered the room target by 0.3 K',
    );
    await page.goto('./#/setpoint');
    await expect(page.getByTestId('reason-sentence').first()).toContainText(
      'Room target lowered by 0.3 K: the house model expects the room to warm up on its own',
    );
    await expect(page.getByTestId('waterfall-model-plan').first()).toBeVisible();
    await page.screenshot({ path: 'e2e/shots/house-s4-setpoint-plan-1400.png', fullPage: true });
    await page.goto('./#/activity');
    await expect(page.locator('body')).not.toContainText('ladder_model_plan');
  });

  test('the Dutch card speaks natural Dutch', async ({ page, context, baseURL }) => {
    await scenario(context, `modelplan:blocked.${tag()}`, baseURL);
    await language(page, 'nl');
    await page.goto('./#/house/control');
    await expect(card(page)).toContainText('Hoe de regelaar het model gebruikt');
    await expect(page.getByTestId('house-control-pill')).toContainText('Schaduw');
    await expect(page.getByTestId('house-control-block-model_not_credible')).toHaveText(
      'Het model wordt nog niet vertrouwd.',
    );
    await page.goto('./#/house/control');
  });

  for (const lang of ['en', 'nl'] as const) {
    test(`the phone Control tab with a shadow chart fits the height budget in ${lang}`, async ({
      page,
      context,
      baseURL,
    }) => {
      await page.setViewportSize({ width: 400, height: 900 });
      await scenario(context, `modelplan:shadow.${tag()}`, baseURL);
      await language(page, lang);
      await page.goto('./#/house/control');
      await expect(
        page.getByTestId('house-control-history').getByRole('img').first(),
      ).toBeVisible();
      await page.waitForTimeout(400);
      const dims = await size(page);
      expect(dims.scroll).toBeLessThanOrEqual(dims.inner);
      expect(dims.height, `phone height control ${lang}`).toBeLessThanOrEqual(
        allowedHeight(PHONE_BUDGET),
      );
    });
  }

  for (const width of [1400, 400]) {
    test(`session 4 screenshots at ${width} px`, async ({ page, context, baseURL }) => {
      await page.setViewportSize({ width, height: 900 });
      await language(page, 'en');
      for (const [name, value] of CONTROL_SHOTS) {
        await scenario(context, `${value}.${tag()}`, baseURL);
        await page.goto('about:blank');
        await page.goto('./#/house/control');
        await expect(card(page)).toBeVisible();
        await page.waitForTimeout(400);
        await card(page).screenshot({ path: `e2e/shots/house-s4-${name}-${width}.png` });
      }
      await scenario(context, `modelplan:shadow.${tag()}`, baseURL);
      await page.goto('./#/house');
      await expect(page.getByTestId('house-status-use')).toBeVisible();
      await page.screenshot({ path: `e2e/shots/house-s4-status-${width}.png` });
    });
  }
});
