import { expect, test } from '@playwright/test';
import { mkdirSync } from 'node:fs';

const PHONE_HEIGHT_BUDGET = 1700;
const SHOTS = 'e2e/shots';
mkdirSync(SHOTS, { recursive: true });

const VIEWPORTS = [
  { label: 'desktop', width: 1400, height: 1000 },
  { label: 'phone', width: 400, height: 860 },
] as const;

const SCENARIOS = [
  { name: 'weather', cookie: null, landmark: 'weather-chart' },
  { name: 'weather-stale', cookie: 'weather:stale', landmark: 'weather-stale' },
  { name: 'weather-off', cookie: 'weather:off', landmark: 'weather-disabled' },
] as const;

for (const viewport of VIEWPORTS) {
  for (const scheme of ['light', 'dark'] as const) {
    test.describe(`weather ${viewport.label} ${scheme}`, () => {
      test.use({
        viewport: { width: viewport.width, height: viewport.height },
        colorScheme: scheme,
      });
      for (const scenario of SCENARIOS) {
        test(scenario.name, async ({ page, context, baseURL }) => {
          const problems: string[] = [];
          page.on('console', (m) => {
            if (m.type() === 'error') problems.push(m.text());
          });
          page.on('pageerror', (e) => problems.push(e.message));
          if (scenario.cookie)
            await context.addCookies([
              { name: 'ovenbird_mock', value: scenario.cookie, url: baseURL ?? '' },
            ]);
          await page.goto('./#/weather');
          await expect(page.getByTestId(scenario.landmark)).toBeVisible();
          if (scenario.name === 'weather') {
            await expect(page.getByTestId('weather-day').first()).toBeVisible();
            if (viewport.label === 'phone')
              await page.getByTestId('forecast-error-details').locator('summary').click();
            await expect(page.getByTestId('forecast-error')).toBeVisible();
            await expect(page.getByTestId('weather-chart').getByTestId('time-chart')).toBeVisible();
          }
          if (scenario.name === 'weather-stale')
            await expect(page.getByTestId('weather-chart')).toBeVisible();
          if (scenario.name === 'weather-off')
            await expect(page.getByTestId('weather-enable-link')).toHaveAttribute(
              'href',
              '#/settings/weather',
            );
          await page.waitForTimeout(400);
          await page.screenshot({
            path: `${SHOTS}/${scenario.name}-${viewport.label}-${scheme}.png`,
            fullPage: true,
          });
          const m = await page.evaluate(() => ({
            scroll: document.documentElement.scrollWidth,
            inner: window.innerWidth,
            height: document.documentElement.scrollHeight,
          }));
          expect(m.scroll).toBeLessThanOrEqual(m.inner);
          if (viewport.label === 'phone') {
            expect(m.height).toBeLessThanOrEqual(PHONE_HEIGHT_BUDGET);
          }
          expect(problems).toEqual([]);
        });
      }
    });
  }
}
