import { expect, test, type BrowserContext, type Page } from '@playwright/test';
import { settled } from './settle';
import { allowedHeight } from './budget';
import { mkdirSync } from 'node:fs';

test.skip(Boolean(process.env['BASE_URL']), 'features run against the mock only');
test.use({ viewport: { width: 1400, height: 1000 } });

const SHOTS = process.env['E2E_FEATURE_SHOTS'] ?? 'e2e/shots';
mkdirSync(SHOTS, { recursive: true });

const IDS = [
  'weather_compensation',
  'room_feedback',
  'slow_start',
  'minimum_run',
  'pump_duty',
  'quiet',
  'stove',
  'dayshift',
  'summer',
  'away',
  'boost',
  'starts_alarm',
  'house_basics',
] as const;

const SWITCH: Record<string, string> = {
  weather_compensation: 'control_weather_compensation',
  room_feedback: 'control_feedback_enabled',
  slow_start: 'control_ramp_enabled',
  minimum_run: 'control_cycling_enabled',
  pump_duty: 'control_pump_duty',
  quiet: 'control_quiet_enabled',
  stove: 'control_stove_enabled',
  summer: 'control_summer_enabled',
  away: 'control_away_enabled',
  boost: 'control_boost_enabled',
  starts_alarm: 'safety_starts_alarm_enabled',
  house_basics: 'house_basics_enabled',
};

const tag = () => `tag:f${Math.random().toString(36).slice(2, 10)}`;

async function scenario(context: BrowserContext, value: string, baseURL?: string): Promise<void> {
  await context.addCookies([
    { name: 'ovenbird_mock', value: `${value}.hold:none`, url: baseURL ?? 'http://127.0.0.1' },
  ]);
}

async function language(page: Page, lang: 'en' | 'nl' = 'en'): Promise<void> {
  await page.addInitScript((l) => localStorage.setItem('ovenbird.language', l), lang);
}

async function applyDraft(page: Page): Promise<void> {
  await page.getByTestId('draft-review').click();
  await expect(page.getByTestId('preview-now')).toBeVisible();
  for (const box of await page.locator('[data-testid^="ack-"]').all())
    await box.check({ force: true });
  await page.getByTestId('preview-apply').click();
  await expect(page.getByTestId('draft-bar')).toBeHidden();
}

test('lists the thirteen features in order, each with a card', async ({
  page,
  context,
  baseURL,
}) => {
  await scenario(context, tag(), baseURL);
  await language(page);
  await page.goto('./#/settings/features');
  await expect(page.getByTestId('settings-features')).toBeVisible();
  const cards = await page.locator('[data-testid^="feature-"][data-testid$="' + '"]').all();
  void cards;
  const order = await page
    .locator('section[data-testid^="feature-"]')
    .evaluateAll((nodes) => nodes.map((n) => n.getAttribute('data-testid')));
  expect(order).toEqual(IDS.map((id) => `feature-${id}`));
  await expect(page.getByTestId('feature-state-stove')).toHaveText('On');
  await expect(page.getByTestId('feature-state-dayshift')).toHaveText('Off');
  await expect(page.getByTestId('feature-state-weather_compensation')).toHaveText('Active now');
});

for (const id of IDS.filter((i) => i !== 'dayshift')) {
  test(`the ${id} switch toggles, saves and the pill follows`, async ({
    page,
    context,
    baseURL,
  }) => {
    await scenario(context, tag(), baseURL);
    await language(page);
    await page.goto('./#/settings/features');
    const card = page.getByTestId(`feature-${id}`);
    const toggle = card.getByRole('switch').first();
    const was = await toggle.isChecked();
    await toggle.locator('xpath=..').click();
    await expect(toggle).toBeChecked({ checked: !was });
    await expect(page.getByTestId('draft-count')).toHaveText('1 change');
    await applyDraft(page);
    await expect(toggle).toBeChecked({ checked: !was });
    const pill = page.getByTestId(`feature-state-${id}`);
    if (was) await expect(pill).toHaveText('Off');
    else await expect(pill).not.toHaveText('Off');
    expect(SWITCH[id]).toBeTruthy();
  });
}

test('the day shift offers on once its experimental side is accepted', async ({
  page,
  context,
  baseURL,
}) => {
  await scenario(context, tag(), baseURL);
  await language(page);
  await page.goto('./#/settings/features');
  const card = page.getByTestId('feature-dayshift');
  const ack = page.getByTestId('feature-ack-input-dayshift');
  await expect(page.getByTestId('dayshift-mode-off')).toBeChecked();
  await expect(ack).not.toBeChecked();
  await expect(page.getByTestId('feature-ack-dayshift')).toContainText(
    'large sun-facing windows too warm',
  );
  await expect(page.getByTestId('dayshift-mode-on')).toBeDisabled();
  await expect(page.getByTestId('feature-ack-why-dayshift')).toContainText('Tick the box');
  await expect(page.getByTestId('feature-experimental-dayshift')).toHaveCount(0);
  await ack.check();
  await expect(page.getByTestId('dayshift-mode-on')).toBeEnabled();
  await expect(page.getByTestId('feature-ack-why-dayshift')).toHaveCount(0);
  await page.getByTestId('dayshift-mode-on').click();
  await expect(page.getByTestId('draft-count')).toHaveText('2 changes');
  await expect(page.getByTestId('feature-experimental-dayshift')).toHaveText('Experimental');
  await applyDraft(page);
  await expect(page.getByTestId('dayshift-mode-on')).toBeChecked();
  await expect(page.getByTestId('feature-state-dayshift')).not.toHaveText('Off');
  await expect(card.getByTestId('dayshift-see-now')).toBeVisible();
  await ack.uncheck();
  await expect(card.getByText('Tick that you want to try it')).toBeVisible();
  await page.getByTestId('dayshift-mode-shadow').click();
  await expect(card.getByText('Tick that you want to try it')).toHaveCount(0);
  await expect(page.getByTestId('dayshift-mode-on')).toBeDisabled();
  await applyDraft(page);
  await expect(page.getByTestId('feature-state-dayshift')).toHaveText('Shadow');
  await expect(page.getByTestId('feature-experimental-dayshift')).toHaveCount(0);
});

test('a day shift that is on says it is experimental', async ({ page, context, baseURL }) => {
  await scenario(context, `${tag()}.dayshift:on`, baseURL);
  await language(page);
  await page.goto('./#/settings/features');
  await expect(page.getByTestId('feature-ack-input-dayshift')).toBeChecked();
  await expect(page.getByTestId('dayshift-mode-on')).toBeChecked();
  await expect(page.getByTestId('feature-experimental-dayshift')).toBeVisible();
  await page.goto('./#/setpoint');
  await expect(page.getByTestId('dayshift-card')).toHaveAttribute('data-mode', 'on');
  await expect(page.getByTestId('dayshift-experimental')).toHaveText('Experimental');
  await expect(page.getByTestId('dayshift-offset')).toContainText('applied');
});

for (const lang of ['en', 'nl'] as const) {
  for (const width of [1400, 400] as const) {
    test(`day shift card unticked and on ${lang} ${width}`, async ({ page, context, baseURL }) => {
      await scenario(context, tag(), baseURL);
      await language(page, lang);
      await page.setViewportSize({ width, height: 900 });
      await page.goto('./#/settings/features');
      const card = page.getByTestId('feature-dayshift');
      await expect(page.getByTestId('feature-ack-why-dayshift')).toBeVisible();
      await card.scrollIntoViewIfNeeded();
      await settled(page);
      await card.screenshot({ path: `${SHOTS}/dayshift-unticked-${lang}-${width}.png` });
      await page.getByTestId('feature-ack-input-dayshift').check();
      await page.getByTestId('dayshift-mode-on').click();
      await expect(page.getByTestId('feature-experimental-dayshift')).toBeVisible();
      const overflow = await page.evaluate(
        () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
      );
      expect(overflow).toBeLessThanOrEqual(0);
      await settled(page);
      await card.screenshot({ path: `${SHOTS}/dayshift-ticked-on-${lang}-${width}.png` });
    });
  }
}

test('day shift times use a time input and are validated', async ({ page, context, baseURL }) => {
  await scenario(context, tag(), baseURL);
  await language(page);
  await page.goto('./#/settings/features');
  const start = page.locator('#field-control_dayshift_day_start');
  await expect(start).toHaveAttribute('type', 'time');
  await expect(start).toHaveValue('09:00');
  await start.fill('18:00');
  await expect(page.getByTestId('draft-count')).toHaveText('1 change');
  await expect(page.getByTestId('field-control_dayshift_day_end')).toContainText(
    'The times do not fit',
  );
  await page.getByTestId('draft-discard').click();
});

test('advanced settings sit in a closed block, expert ones are read-only', async ({
  page,
  context,
  baseURL,
}) => {
  await scenario(context, tag(), baseURL);
  await language(page);
  await page.goto('./#/settings/features');
  await expect(page.locator('#field-control_dayshift_min_sun_wm2')).toHaveCount(0);
  await page.getByTestId('feature-more-dayshift').locator('summary').click();
  await expect(page.locator('#field-control_dayshift_min_sun_wm2')).toBeVisible();

  await page.getByTestId('feature-fixed-slow_start').locator('summary').click();
  await expect(page.getByTestId('feature-fixed-hint-slow_start')).toContainText(
    'set when ovenbird is installed',
  );
  const row = page.getByTestId('fixed-control_ramp_dwell_s');
  await expect(row).toContainText('3 min');
  await expect(row.locator('input')).toHaveCount(0);
  await expect(page.getByTestId('draft-bar')).toBeHidden();
  await expect(page.getByTestId('feature-link-slow_start')).toHaveAttribute(
    'href',
    /#\/settings\/behaviour$/,
  );
});

test('the features section fits a phone', async ({ page, context, baseURL }) => {
  await scenario(context, tag(), baseURL);
  await language(page);
  await page.setViewportSize({ width: 400, height: 860 });
  await page.goto('./#/settings/features');
  await expect(page.getByTestId('feature-house_basics')).toBeVisible();
  await settled(page);
  const m = await page.evaluate(() => ({
    h: document.documentElement.scrollHeight,
    w: document.documentElement.scrollWidth,
    iw: window.innerWidth,
  }));
  expect(m.w).toBeLessThanOrEqual(m.iw);
  expect(m.h, `features height at 400 px: ${m.h}`).toBeLessThanOrEqual(allowedHeight(4000));
});

test('start a boost from Home and stop it', async ({ page, context, baseURL }) => {
  await scenario(context, tag(), baseURL);
  await language(page);
  await page.goto('./#/home');
  await expect(page.getByTestId('home-boost')).toBeVisible();
  await page.getByTestId('home-boost-toggle').click();
  await page.getByTestId('home-boost-offset-1.5').click();
  await page.getByTestId('home-boost-hours-4').click();
  await page.getByTestId('home-boost-start').click();
  await expect(page.getByTestId('home-boost-active')).toContainText('+1.5 K');
  await expect(page.getByTestId('home-boost-left')).toContainText(/(4 h|3 h \d+ min) left/);
  await page.getByTestId('home-boost-stop').click();
  await expect(page.getByTestId('home-boost-active')).toHaveCount(0);
  await expect(page.getByTestId('home-boost')).toHaveAttribute('data-active', 'false');
});

test('a boost already running shows its time left', async ({ page, context, baseURL }) => {
  await scenario(context, `${tag()}.boost:active`, baseURL);
  await language(page);
  await page.goto('./#/home');
  await expect(page.getByTestId('home-boost-active')).toContainText('+1 K until');
  await expect(page.getByTestId('home-boost-left')).toContainText('1 h');
});

test('a boost while away says to end away first', async ({ page, context, baseURL }) => {
  await scenario(context, tag(), baseURL);
  await language(page);
  await page.goto('./#/home');
  await page.getByTestId('home-boost-toggle').click();
  await expect(page.getByTestId('home-boost-start')).toBeEnabled();
  const until = new Date(Date.now() + 3 * 86_400_000).toISOString();
  const set = await page.request.put('api/v1/control/away', {
    data: { until },
    headers: { 'X-Ovenbird-Request': '1' },
  });
  expect(set.status()).toBe(200);
  await page.getByTestId('home-boost-start').click({ force: true });
  await expect(page.getByTestId('home-boost').getByText('End away first').first()).toBeVisible();
});

test('set away and end it again', async ({ page, context, baseURL }) => {
  await scenario(context, tag(), baseURL);
  await language(page);
  await page.goto('./#/home');
  await page.getByTestId('home-away-toggle').click();
  await expect(page.getByTestId('home-away-date')).toHaveAttribute('type', 'date');
  await expect(page.getByTestId('home-away-time')).toHaveValue('18:00');
  await page.getByTestId('home-away-time').fill('06:00');
  await page.getByTestId('home-away-set').click();
  await expect(page.getByTestId('home-away-active')).toContainText('Away until');
  await expect(page.getByTestId('home-away-detail')).toContainText('Room target 16 °C');
  await expect(page.getByTestId('home-away-detail')).toContainText('Back to comfort from');
  await page.getByTestId('home-away-end').click();
  await expect(page.getByTestId('home-away')).toHaveAttribute('data-active', 'false');
});

test('an end of away inside the comfort lead is refused before sending', async ({
  page,
  context,
  baseURL,
}) => {
  await scenario(context, tag(), baseURL);
  await language(page);
  await page.goto('./#/home');
  await page.getByTestId('home-away-toggle').click();
  const soon = new Date(Date.now() + 2 * 3_600_000);
  const pad = (n: number) => String(n).padStart(2, '0');
  await page
    .getByTestId('home-away-date')
    .fill(`${soon.getFullYear()}-${pad(soon.getMonth() + 1)}-${pad(soon.getDate())}`);
  await page
    .getByTestId('home-away-time')
    .fill(`${pad(soon.getHours())}:${pad(soon.getMinutes())}`);
  await expect(page.getByTestId('home-away-problem')).toContainText('more than 6 h');
  await expect(page.getByTestId('home-away-set')).toBeDisabled();
});

test('away that is running and the return phase show on Home', async ({
  page,
  context,
  baseURL,
}) => {
  await scenario(context, `${tag()}.away:returning`, baseURL);
  await language(page);
  await page.goto('./#/home');
  await expect(page.getByTestId('home-away')).toHaveAttribute('data-phase', 'returning');
  await expect(page.getByTestId('home-away-active')).toHaveText('Warming up for your return');
});

test('boost and away are hidden when switched off', async ({ page, context, baseURL }) => {
  await scenario(context, tag(), baseURL);
  await language(page);
  await page.goto('./#/settings/features');
  for (const id of ['boost', 'away'])
    await page.getByTestId(`feature-${id}`).getByRole('switch').first().locator('xpath=..').click();
  await applyDraft(page);
  await page.goto('./#/home');
  await expect(page.getByTestId('home-verdict')).toBeVisible();
  await expect(page.getByTestId('home-boost')).toHaveCount(0);
  await expect(page.getByTestId('home-away')).toHaveCount(0);
});

for (const phase of ['boost', 'setback', 'recovery', 'blocked', 'idle'] as const) {
  test(`the day shift card shows the ${phase} phase`, async ({ page, context, baseURL }) => {
    await scenario(context, `${tag()}.dayshift:${phase}`, baseURL);
    await language(page);
    await page.goto('./#/setpoint');
    const card = page.getByTestId('dayshift-card');
    await expect(card).toHaveAttribute('data-phase', phase);
    await expect(card).toHaveAttribute('data-mode', 'shadow');
    await expect(page.getByTestId('dayshift-phase')).toBeVisible();
    await expect(page.getByTestId('dayshift-shadow')).toContainText('In shadow');
    if (phase !== 'blocked') await expect(page.getByTestId('dayshift-reasons')).toBeVisible();
    await expect(page.getByTestId('dayshift-forecast')).toContainText('Sun');
    if (phase === 'blocked') {
      await expect(page.getByTestId('dayshift-guards')).toContainText('forecast is too old');
      await expect(page.getByTestId('dayshift-next')).toContainText('No change planned');
    } else {
      await expect(page.getByTestId('dayshift-next')).toContainText('Next:');
    }
    if (phase === 'boost') await expect(page.getByTestId('dayshift-shadow')).toContainText('raise');
    if (phase === 'setback')
      await expect(page.getByTestId('dayshift-shadow')).toContainText('lower');
  });
}

test('the day shift card is absent while the day shift is off', async ({
  page,
  context,
  baseURL,
}) => {
  await scenario(context, tag(), baseURL);
  await language(page);
  await page.goto('./#/setpoint');
  await expect(page.getByTestId('setpoint-now')).toBeVisible();
  await expect(page.getByTestId('dayshift-card')).toHaveCount(0);
});

test('the summer switch shows on Home and in the features', async ({ page, context, baseURL }) => {
  await scenario(context, `${tag()}.summer:on`, baseURL);
  await language(page);
  await page.goto('./#/home');
  await expect(page.getByTestId('home-summer')).toContainText('no space heating');
  await expect(page.getByTestId('home-summer')).toContainText('19.4');
  await page.goto('./#/settings/features');
  await expect(page.getByTestId('feature-state-summer')).toHaveText('Active now');
});

test('the summer switch collecting its mean is named', async ({ page, context, baseURL }) => {
  await scenario(context, `${tag()}.summer:warming`, baseURL);
  await language(page);
  await page.goto('./#/home');
  await expect(page.getByTestId('home-summer')).toContainText('collecting');
});

test('the start-count alarm has its own words', async ({ page, context, baseURL }) => {
  await scenario(context, tag(), baseURL);
  await language(page);
  await page.goto('./#/settings/features');
  await page.getByTestId('feature-more-starts_alarm').locator('summary').click();
  await expect(page.getByTestId('field-safety_starts_per_hour_max')).toContainText(
    'Most starts per hour',
  );
});

for (const lang of ['en', 'nl'] as const) {
  for (const [label, width, height] of [
    ['desktop', 1400, 1000],
    ['phone', 400, 860],
  ] as const) {
    test(`screenshots ${lang} ${label}`, async ({ page, context, baseURL }) => {
      await scenario(context, `${tag()}.dayshift:boost.boost:active.summer:on`, baseURL);
      await language(page, lang);
      await page.setViewportSize({ width, height });
      await page.goto('./#/settings/features');
      await expect(page.getByTestId('feature-state-dayshift')).toHaveText(
        lang === 'en' ? 'Shadow' : 'Schaduw',
      );
      await settled(page);
      await page.screenshot({ path: `${SHOTS}/features-${lang}-${width}.png`, fullPage: true });
      await page.goto('./#/home');
      await expect(page.getByTestId('home-boost-active')).toBeVisible();
      await settled(page);
      await page.screenshot({ path: `${SHOTS}/home-boost-${lang}-${width}.png`, fullPage: true });
      await page.getByTestId('home-away-toggle').click();
      await settled(page);
      await page.screenshot({
        path: `${SHOTS}/home-boost-away-${lang}-${width}.png`,
        fullPage: true,
      });
      await page.goto('./#/setpoint');
      await expect(page.getByTestId('dayshift-card')).toBeVisible();
      await settled(page);
      await page
        .getByTestId('dayshift-card')
        .screenshot({ path: `${SHOTS}/dayshift-${lang}-${width}.png` });
    });
  }
}

for (const lang of ['en', 'nl'] as const) {
  for (const width of [1400, 400] as const) {
    test(`home with the away control open ${lang} ${width}`, async ({ page, context, baseURL }) => {
      await scenario(context, tag(), baseURL);
      await language(page, lang);
      await page.setViewportSize({ width, height: 860 });
      await page.goto('./#/home');
      await page.getByTestId('home-away-toggle').click();
      await expect(page.getByTestId('home-away-set')).toBeVisible();
      await settled(page);
      await page.screenshot({ path: `${SHOTS}/home-away-${lang}-${width}.png`, fullPage: true });
      const panel = await page.locator('#home-away-panel').boundingBox();
      const viewport = page.viewportSize()!;
      if (width < 640) expect(panel!.width).toBeGreaterThan(viewport.width * 0.8);
    });
  }
}
