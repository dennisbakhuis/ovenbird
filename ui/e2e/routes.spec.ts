import { expect, test, type ConsoleMessage, type Page } from '@playwright/test';
import { settled } from './settle';
import { allowedHeight } from './budget';
import { mkdirSync } from 'node:fs';

const SHOTS = 'e2e/shots';

const OPTIONAL_ENDPOINT =
  /\/api\/v1\/(config|audit|weather|pump|insight|decisions\/series|shadow|trial|notifications|system|diagnostics|history|export|replay|control\/(pause|resume|snapshot|release))/;

interface RouteSpec {
  name: string;
  hash: string | ((page: Page) => Promise<string>);
  landmarks: string[];
}

const ROUTES: RouteSpec[] = [
  {
    name: 'home',
    hash: '#/home',
    landmarks: ['home-verdict', 'room-hero', 'why-card', 'home-chart'],
  },
  {
    name: 'setpoint',
    hash: '#/setpoint',
    landmarks: ['setpoint-now', 'setpoint-inputs', 'setpoint-history', 'setpoint-table-card'],
  },
  {
    name: 'setpoint-tick',
    hash: async (page) => {
      const response = await page.request.get('api/v1/decisions?limit=5');
      const body = (await response.json()) as { decisions: { at: string }[] };
      const pick = body.decisions[Math.max(0, body.decisions.length - 3)];
      return `#/setpoint?range=6&at=${encodeURIComponent(pick?.at ?? '')}`;
    },
    landmarks: ['setpoint-now', 'setpoint-history'],
  },
  {
    name: 'activity',
    hash: '#/activity',
    landmarks: ['alarms-active', 'alarms-monitors', 'alarms-journal'],
  },
  {
    name: 'activity-holds',
    hash: '#/activity/holds',
    landmarks: ['holds-current', 'holds-incidents'],
  },
  {
    name: 'activity-commands',
    hash: '#/activity/commands',
    landmarks: ['commands-budget', 'commands-journal'],
  },
  { name: 'activity-audit', hash: '#/activity/audit', landmarks: ['audit-card'] },
  {
    name: 'system',
    hash: '#/system',
    landmarks: ['mode-card', 'notify-card', 'safety-net-card', 'about-card'],
  },
  { name: 'weather', hash: '#/weather', landmarks: ['weather-now', 'weather-chart'] },
  { name: 'settings', hash: '#/settings', landmarks: ['settings-overview'] },
  {
    name: 'settings-features',
    hash: '#/settings/features',
    landmarks: ['settings-features', 'feature-dayshift'],
  },
  { name: 'settings-curve', hash: '#/settings/curve', landmarks: ['curve-editor', 'curve-table'] },
  {
    name: 'settings-room',
    hash: '#/settings/room',
    landmarks: ['room-status', 'field-control_comfort_c'],
  },
  { name: 'settings-pump-duty', hash: '#/settings/pump-duty', landmarks: ['group-pump_duty'] },
  { name: 'settings-behaviour', hash: '#/settings/behaviour', landmarks: ['group-limits'] },
  { name: 'settings-quiet', hash: '#/settings/quiet', landmarks: ['quiet-editor'] },
  { name: 'settings-emitter', hash: '#/settings/emitter', landmarks: ['preset-diff'] },
  { name: 'settings-weather', hash: '#/settings/weather', landmarks: ['weather-location'] },
  {
    name: 'settings-versions',
    hash: '#/settings/versions',
    landmarks: ['export-import', 'locked-table'],
  },
  { name: 'pump', hash: '#/pump', landmarks: ['pump-live', 'pump-stats'] },
  { name: 'more', hash: '#/more', landmarks: ['more-links'] },
  { name: 'system-signals', hash: '#/system/signals', landmarks: ['signals-table'] },
  {
    name: 'system-shadow',
    hash: '#/system/shadow',
    landmarks: ['shadow-page', 'shadow-range', 'shadow-summary', 'shadow-chart', 'shadow-episodes'],
  },
  {
    name: 'system-trial',
    hash: '#/system/trial',
    landmarks: [
      'trial-checklist-card',
      'trial-criteria-card',
      'trial-runs-card',
      'trial-release-card',
    ],
  },
  {
    name: 'house',
    hash: '#/house',
    landmarks: ['house-page', 'house-loss-now', 'house-facts-input'],
  },
  { name: 'settings-house', hash: '#/settings/house', landmarks: ['house-section'] },
  { name: 'settings-ha', hash: '#/settings/ha', landmarks: ['ha-card', 'ha-sensors'] },
  {
    name: 'system-data',
    hash: '#/system/data',
    landmarks: ['storage-card', 'storage-resolutions', 'export-card', 'export-estimate'],
  },
  { name: 'settings-data', hash: '#/settings/data', landmarks: ['data-section'] },
  {
    name: 'system-replay',
    hash: '#/system/replay',
    landmarks: ['replay-page', 'replay-no-claims', 'replay-coverage', 'replay-run'],
  },
];

const PHONE_BUDGET: Record<string, number> = {
  home: 1900,
  setpoint: 2500,
  weather: 1600,
  pump: 2500,
  'activity-commands': 2000,
  'system-signals': 1600,
  'settings-room': 1600,
  'settings-features': 4000,
  'settings-emitter': 1800,
  'system-data': 3600,
};
const DEFAULT_PHONE_BUDGET = 2500;

const VIEWPORTS = [
  { label: 'desktop', width: 1400, height: 1000 },
  { label: 'phone', width: 400, height: 860 },
] as const;

const SCHEMES = ['light', 'dark'] as const;

function isIgnorable(message: ConsoleMessage): boolean {
  if (message.type() !== 'error') return true;
  const text = message.text();
  const url = message.location().url;
  return /status of (404|405)/.test(text) && OPTIONAL_ENDPOINT.test(url);
}

mkdirSync(SHOTS, { recursive: true });

for (const viewport of VIEWPORTS) {
  for (const scheme of SCHEMES) {
    test.describe(`${viewport.label} ${scheme}`, () => {
      test.use({
        viewport: { width: viewport.width, height: viewport.height },
        colorScheme: scheme,
      });

      for (const route of ROUTES) {
        test(`${route.name}`, async ({ page }) => {
          const problems: string[] = [];
          page.on('console', (message) => {
            if (!isIgnorable(message)) problems.push(`${message.type()}: ${message.text()}`);
          });
          page.on('pageerror', (error) => problems.push(`pageerror: ${error.message}`));

          await page.goto('./');
          const hash = typeof route.hash === 'string' ? route.hash : await route.hash(page);
          await page.evaluate((value) => (window.location.hash = value), hash);

          await expect(page.getByTestId('status-strip')).toBeVisible();
          await expect(page.getByTestId('mode-chip')).toContainText(
            /Auto|Shadow|Paused|Off|Manual/,
          );
          for (const landmark of route.landmarks) {
            const target = page.getByTestId(landmark);
            await expect(
              process.env['BASE_URL'] ? target.or(page.getByTestId('unavailable')).first() : target,
            ).toBeVisible();
          }
          await expect(page.locator('main h1').first()).toBeAttached();

          if (route.name === 'home') {
            await expect(page.getByTestId('room-value')).toContainText(/\d/);
            await expect(page.getByTestId('waterfall')).toBeHidden();
            const why = page.getByTestId('why-card').locator('summary').first();
            await why.click();
            await expect(page.getByTestId('waterfall')).toBeVisible();
            await why.click();
            await expect(page.getByTestId('home-chart').getByTestId('time-chart')).toBeVisible();
          }
          if (route.name.startsWith('setpoint')) {
            await expect(page.getByTestId('reason-sentence')).toBeVisible();
            await expect(page.getByTestId('waterfall').first()).toBeVisible();
            await expect(
              page.getByTestId('setpoint-history').getByTestId('time-chart'),
            ).toBeVisible();
            await expect(page.getByTestId('reason-strip')).toBeVisible();
          }
          if (route.name === 'setpoint') {
            await expect(
              page.getByTestId('decision-table').locator('tbody tr').first(),
            ).toBeVisible();
          }
          if (route.name === 'activity-audit') {
            await expect(
              page
                .getByTestId('audit-table')
                .or(page.getByTestId('audit-missing'))
                .or(page.getByTestId('audit-forbidden')),
            ).toBeVisible();
          }

          const bottom = page.getByTestId('bottom-nav');
          const top = page.getByTestId('top-nav');
          if (viewport.width <= 640) {
            await expect(bottom).toBeVisible();
            await expect(top).toBeHidden();
          } else {
            await expect(bottom).toBeHidden();
            await expect(top).toBeVisible();
          }

          if (viewport.width <= 640) {
            const strip = await page.getByTestId('topbar').boundingBox();
            expect(strip?.height ?? 0, 'status strip is one row').toBeLessThanOrEqual(60);
          }

          await settled(page);
          const overflow = await page.evaluate(() => ({
            scroll: document.documentElement.scrollWidth,
            inner: window.innerWidth,
          }));
          expect(overflow.scroll, 'horizontal overflow').toBeLessThanOrEqual(overflow.inner);

          if (viewport.width <= 640) {
            const budget = PHONE_BUDGET[route.name] ?? DEFAULT_PHONE_BUDGET;
            const height = await page.evaluate(() => document.documentElement.scrollHeight);
            expect(height, `phone page height of ${route.name}`).toBeLessThanOrEqual(
              allowedHeight(budget),
            );
          }

          await page.screenshot({
            path: `${SHOTS}/${route.name}-${viewport.label}-${scheme}.png`,
            fullPage: true,
          });
          expect(problems).toEqual([]);
        });
      }
    });
  }
}

test.describe('Dutch phone heights', () => {
  test.skip(Boolean(process.env['BASE_URL']), 'budgets are measured on the default mock');
  test.use({ viewport: { width: 400, height: 860 } });

  for (const name of ['home', 'pump'] as const) {
    test(`${name} stays within its budget in Dutch`, async ({ page }) => {
      await page.addInitScript(() => localStorage.setItem('ovenbird.language', 'nl'));
      await page.goto(`./#/${name}`);
      await expect(page.locator('html')).toHaveAttribute('lang', 'nl');
      await expect(
        page.getByTestId(name === 'home' ? 'home-chart' : 'pump-settings'),
      ).toBeVisible();
      await settled(page);
      const height = await page.evaluate(() => document.documentElement.scrollHeight);
      expect(height, `Dutch phone height of ${name}`).toBeLessThanOrEqual(
        allowedHeight(PHONE_BUDGET[name] ?? 0),
      );
    });
  }
});

test.describe('shell', () => {
  test.skip(Boolean(process.env['BASE_URL']), 'shell interactions run against the mock only');

  test('strip pills link to Activity and the mode chip opens its sheet', async ({ page }) => {
    await page.setViewportSize({ width: 1400, height: 1000 });
    await page.goto('./#/home');
    await expect(page.getByTestId('alarm-count')).toHaveAttribute('href', '#/activity');
    await expect(page.getByTestId('strip-hold')).toHaveAttribute('href', '#/activity/holds');
    await expect(page.getByTestId('config-version')).toHaveCount(0);
    await page.getByTestId('mode-chip').click();
    await expect(page.getByTestId('mode-sheet')).toBeVisible();
    await expect(page.getByTestId('config-version')).toHaveAttribute('href', '#/settings/versions');
    await expect(page.getByTestId('pause')).toBeVisible();
    await page.keyboard.press('Escape');
    await expect(page.getByTestId('mode-sheet')).toBeHidden();
    await expect(page.getByTestId('mode-chip')).toBeFocused();
    await page.getByTestId('strip-hold').click();
    await expect(page).toHaveURL(/#\/activity\/holds$/);
  });

  test('the settings menu switches theme and language by keyboard', async ({ page }) => {
    await page.setViewportSize({ width: 1400, height: 1000 });
    await page.emulateMedia({ colorScheme: 'light' });
    await page.goto('./#/home');
    await expect(page.locator('html')).toHaveAttribute('data-theme', 'light');
    await page.getByTestId('settings-menu-button').focus();
    await page.keyboard.press('Enter');
    await expect(page.getByTestId('settings-menu')).toBeVisible();
    await page.getByTestId('theme-dark').focus();
    await page.waitForFunction(() => new Promise((resolve) => requestAnimationFrame(resolve)));
    await expect(page.getByTestId('theme-dark')).toBeFocused();
    await page.keyboard.press('Space');
    await expect(page.locator('html')).toHaveAttribute('data-theme', 'dark');
    await page.getByTestId('language-nl').check();
    await expect(page.getByTestId('top-nav')).toContainText('Thuis');
    await page.keyboard.press('Escape');
    await expect(page.getByTestId('settings-menu')).toBeHidden();
    await expect(page.getByTestId('settings-menu-button')).toBeFocused();
    await page.reload();
    await expect(page.locator('html')).toHaveAttribute('data-theme', 'dark');
    await expect(page.getByTestId('top-nav')).toContainText('Thuis');
    await page.getByTestId('settings-menu-button').click();
    await page.getByTestId('theme-auto').check();
    await page.getByTestId('language-auto').check();
    await expect(page.locator('html')).toHaveAttribute('data-theme', 'light');
  });

  test('a new page starts at the top and a sheet locks the page scroll', async ({ page }) => {
    await page.setViewportSize({ width: 400, height: 860 });
    await page.goto('./#/home');
    await expect(page.getByTestId('home-chart').getByTestId('time-chart')).toBeVisible();
    await expect(page.getByTestId('home-verdict')).toBeVisible();
    await expect
      .poll(() =>
        page.evaluate(() => {
          window.scrollTo(0, document.documentElement.scrollHeight);
          return window.scrollY;
        }),
      )
      .toBeGreaterThan(800);
    await page.getByTestId('bottom-nav').getByRole('link', { name: 'Setpoint' }).click();
    await expect(page.getByTestId('setpoint-now')).toBeVisible();
    expect(await page.evaluate(() => window.scrollY)).toBe(0);
    await page.getByTestId('mode-chip').click();
    await expect(page.getByTestId('mode-sheet')).toHaveAttribute('aria-modal', 'true');
    expect(await page.evaluate(() => document.documentElement.style.overflow)).toBe('hidden');
    await page.keyboard.press('Escape');
    await expect(page.getByTestId('mode-sheet')).toBeHidden();
    await expect.poll(() => page.evaluate(() => document.documentElement.style.overflow)).toBe('');
  });

  test('pages follow the service clock when it runs behind the browser', async ({
    page,
    context,
    baseURL,
  }) => {
    await context.addCookies([
      { name: 'ovenbird_mock', value: 'clock:behind', url: baseURL ?? 'http://127.0.0.1' },
    ]);
    await page.setViewportSize({ width: 1400, height: 1000 });
    await page.goto('./#/home');
    const chart = page.getByTestId('home-chart');
    await expect(chart.getByTestId('time-chart')).toBeVisible();
    await expect(chart.getByTestId('home-chart-empty')).toHaveCount(0);
    await expect(page.getByTestId('home-tiles')).not.toContainText(/Energy today\s*0\s*kWh/);
    await page.goto('./#/pump');
    await expect(page.getByTestId('pump-live')).toBeVisible();
    await expect(page.locator('[data-testid=time-chart]').first()).toBeVisible();
    await expect(page.getByTestId('flow-empty')).toHaveCount(0);
    await page.goto('./#/activity');
    await expect(page.getByTestId('activity-timeline')).toBeVisible();
    await expect(page.getByTestId('strip-hold')).toContainText(/until (today|tomorrow) \d/);
  });

  test('a critical alarm comes with its monitor tripped above the limit', async ({
    page,
    context,
    baseURL,
  }) => {
    test.skip(Boolean(process.env['BASE_URL']), 'mock scenario');
    await context.addCookies([
      { name: 'ovenbird_mock', value: 'alarms:critical', url: baseURL ?? 'http://127.0.0.1' },
    ]);
    await page.setViewportSize({ width: 1400, height: 1000 });
    await page.goto('./#/activity');
    const monitor = page
      .getByTestId('monitor-table')
      .locator('li')
      .filter({ hasText: 'Outlet too hot' });
    await expect(monitor).toHaveAttribute('data-status', 'active');
    await expect(monitor).toContainText('48.2');
    await expect(monitor).toContainText('45');
  });

  test('Home and Pump count the same compressor starts today', async ({ page }) => {
    await page.setViewportSize({ width: 1400, height: 1000 });
    await page.goto('./#/home');
    const homeValue = page.getByTestId('tile-starts').locator('.value');
    await expect(homeValue).toHaveText(/^\d+$/);
    const home = await homeValue.textContent();
    await page.goto('./#/pump');
    await expect(page.getByTestId('pump-stats-title')).toHaveText('Today, since 00:00');
    await expect(page.getByTestId('pump-starts').locator('.value')).toHaveText(home ?? '');
    await expect(page.getByTestId('loop-runs')).toContainText(`${home} starts today`);
  });

  for (const language of ['en', 'nl'] as const) {
    test(`the top navigation fits at tablet widths, ${language}`, async ({ page }) => {
      await page.addInitScript(
        (value) => localStorage.setItem('ovenbird.language', value),
        language,
      );
      for (const width of [641, 700, 780, 860, 1000]) {
        await page.setViewportSize({ width, height: 900 });
        await page.goto('./#/house');
        const nav = page.getByTestId('top-nav');
        await expect(nav).toBeVisible();
        const fit = await nav.evaluate((element) => {
          const list = element.querySelector('ul') as HTMLElement;
          const box = element.getBoundingClientRect();
          const links = [...element.querySelectorAll('a')].map((a) => a.getBoundingClientRect());
          return {
            clipped: list.scrollWidth - list.clientWidth,
            beyond: Math.max(...links.map((r) => r.right)) - box.right,
          };
        });
        expect(fit.clipped, `nav clipped at ${width} px`).toBeLessThanOrEqual(0);
        expect(fit.beyond, `nav link beyond the bar at ${width} px`).toBeLessThanOrEqual(0.5);
        const active = nav.locator('a[aria-current="page"] .nav-label');
        expect((await active.boundingBox())?.width ?? 0, 'active label shown').toBeGreaterThan(20);
        const strip = await page.getByTestId('status-strip').boundingBox();
        expect(strip?.height ?? 0, `status strip is one row at ${width} px`).toBeLessThanOrEqual(
          48,
        );
      }
    });
  }

  for (const viewport of VIEWPORTS) {
    for (const scheme of SCHEMES) {
      test(`framed in Home Assistant, ${viewport.label} ${scheme}`, async ({ page }) => {
        await page.setViewportSize({ width: viewport.width, height: viewport.height });
        await page.emulateMedia({ colorScheme: scheme });
        await page.goto('./__frame?route=home');
        const frame = page.frameLocator('[data-testid=ingress-frame]');
        await expect(frame.getByTestId('room-hero')).toBeVisible();
        await expect(frame.locator('html')).toHaveAttribute('data-framed', '');
        await expect(frame.locator('.brand')).toBeHidden();
        await settled(page);
        await page.screenshot({ path: `${SHOTS}/framed-${viewport.label}-${scheme}.png` });
      });
    }
  }
});
