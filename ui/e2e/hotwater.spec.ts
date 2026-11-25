import { mkdirSync } from 'node:fs';
import { join } from 'node:path';
import {
  expect,
  test,
  type APIRequestContext,
  type BrowserContext,
  type Page,
} from '@playwright/test';

test.skip(Boolean(process.env['BASE_URL']), 'the hot-water scenarios run on the mock');
test.describe.configure({ mode: 'serial' });

const SHOTS = process.env['HOTWATER_SHOTS'];
const HEADERS = { 'Content-Type': 'application/json', 'X-Ovenbird-Request': '1' };

async function scenario(context: BrowserContext, value: string, baseURL?: string): Promise<void> {
  await context.addCookies([{ name: 'ovenbird_mock', value, url: baseURL ?? 'http://127.0.0.1' }]);
}

async function language(page: Page, lang: 'en' | 'nl'): Promise<void> {
  await page.addInitScript((value) => localStorage.setItem('ovenbird.language', value), lang);
}

/** Put the stored hot_water setting back to its default (auto), as the other specs expect. */
async function resetSetting(request: APIRequestContext): Promise<void> {
  const doc = (await (await request.get('api/v1/config')).json()) as {
    version: number;
    hot_water: { setting: string };
  };
  if (doc.hot_water.setting === 'auto') return;
  await request.put('api/v1/config', {
    headers: HEADERS,
    data: { base_version: doc.version, changes: { hot_water: null }, comment: 'e2e reset' },
  });
}

const strip = (page: Page) => page.getByTestId('day-strip');
const lane = (page: Page) => strip(page).locator('g[data-lane="dhw"]');
const readout = (page: Page) => strip(page).getByTestId('strip-readout');
const drawer = (page: Page) => page.getByTestId('help-drawer');

async function home(page: Page): Promise<void> {
  await page.goto('./#/home');
  await expect(readout(page)).toBeVisible();
}

async function openGlossary(page: Page): Promise<void> {
  await page.getByTestId('help-button').click();
  await expect(drawer(page)).toBeVisible();
  await drawer(page).getByTestId('help-all-topics').click();
  await drawer(page).getByTestId('help-glossary-link').click();
  await expect(drawer(page).getByTestId('help-glossary')).toBeVisible();
}

test.describe('hot water', () => {
  test.use({ viewport: { width: 1400, height: 1000 } });

  test.afterAll(async ({ request }) => {
    await resetSetting(request);
  });

  test('shows hot water by default: lane, signals and help', async ({ page }) => {
    await language(page, 'en');
    await home(page);
    await expect(lane(page)).toHaveCount(1);
    await expect(readout(page)).toContainText('Hot water');
    await openGlossary(page);
    await expect(drawer(page).getByTestId('help-glossary')).toContainText('Hot water');

    await page.goto('./#/system/signals');
    await expect(
      page.getByTestId('signal-raw-id').filter({ hasText: 'main/DHW_Temp' }),
    ).toHaveCount(1);
  });

  for (const lang of ['en', 'nl'] as const) {
    test(`hides hot water when the pump has no tank, ${lang}`, async ({
      page,
      context,
      baseURL,
    }) => {
      await scenario(context, 'dhw:none', baseURL);
      await language(page, lang);
      await home(page);
      await expect(lane(page)).toHaveCount(0);
      await expect(readout(page)).toContainText(lang === 'en' ? 'Defrost' : 'Ontdooien');
      await expect(readout(page)).not.toContainText(lang === 'en' ? 'Hot water' : 'Warm water');
      await expect(page.getByTestId('pump-state')).not.toHaveAttribute('data-state', 'dhw');

      await page.getByTestId('help-button').click();
      await expect(drawer(page)).toBeVisible();
      await expect(drawer(page)).toContainText(lang === 'en' ? 'Three lanes' : 'Drie banen');
      await expect(drawer(page).locator('[data-term="dhw"]')).toHaveCount(0);
      await expect(drawer(page)).not.toContainText(
        lang === 'en' ? /hot water/i : /tapwater|Warm water|warm water maakte/,
      );
      await drawer(page).getByTestId('help-all-topics').click();
      await drawer(page).getByTestId('help-glossary-link').click();
      const glossary = drawer(page).getByTestId('help-glossary');
      await expect(glossary).toBeVisible();
      await expect(glossary).not.toContainText(lang === 'en' ? 'Hot water' : 'Warm water');
      await page.keyboard.press('Escape');

      await page.goto('./#/system/signals');
      await expect(page.getByTestId('signal-raw-id').first()).toBeVisible();
      await expect(page.getByTestId('signal-raw-id').filter({ hasText: /DHW/ })).toHaveCount(0);

      await page.goto('./#/settings/pump-duty');
      await expect(page.getByTestId('field-hot_water')).toBeVisible();
      await expect(page.getByTestId('hot-water-tank')).toHaveAttribute('data-installed', 'false');
      await expect(page.getByTestId('hot-water-tank')).toHaveText(
        lang === 'en'
          ? 'The pump reports no hot-water tank.'
          : 'De pomp meldt geen tapwaterboiler.',
      );
    });

    test(`a run while hot water is hidden reads "busy elsewhere", ${lang}`, async ({
      page,
      context,
      baseURL,
    }) => {
      await scenario(context, 'dhw:none.pump:dhw', baseURL);
      await language(page, lang);
      await home(page);
      const state = page.getByTestId('pump-state');
      await expect(state).toHaveAttribute('data-state', 'dhw');
      await expect(state).toContainText(
        lang === 'en' ? 'Pump busy elsewhere' : 'Pomp elders bezig',
      );
      await expect(lane(page)).toHaveCount(1);
      await expect(readout(page)).toContainText(lang === 'en' ? 'Busy elsewhere' : 'Elders bezig');
      await expect(readout(page)).not.toContainText(lang === 'en' ? 'Hot water' : 'Warm water');

      await page.goto('./#/pump');
      await expect(page.getByTestId('loop-diagram')).toContainText(
        lang === 'en' ? 'Busy elsewhere' : 'Elders bezig',
      );
    });
  }

  test('the setting "Show" brings hot water back without a tank', async ({
    page,
    context,
    baseURL,
  }) => {
    await scenario(context, 'dhw:none', baseURL);
    await language(page, 'en');
    await page.goto('./#/settings/pump-duty');
    const field = page.getByTestId('field-hot_water');
    await expect(field).toContainText('Hot water');
    const select = field.locator('select');
    await expect(select.locator('option')).toHaveText([
      'Automatic (as the pump reports)',
      'Show',
      'Hide',
    ]);
    await select.selectOption('on');
    await expect(page.getByTestId('draft-count')).toHaveText('1 change');
    await page.getByTestId('draft-review').click();
    await page.getByTestId('preview-apply').click();
    await expect(page.getByTestId('preview-dialog')).toBeHidden();
    await expect(page.getByTestId('apply-notice')).toContainText(/Version \d+/);

    await home(page);
    await expect(lane(page)).toHaveCount(1);
    await expect(readout(page)).toContainText('Hot water');
    await page.goto('./#/system/signals');
    await expect(
      page.getByTestId('signal-raw-id').filter({ hasText: 'main/DHW_Temp' }),
    ).toHaveCount(1);
  });
});

test.describe('hot water screenshots', () => {
  test.skip(!SHOTS, 'set HOTWATER_SHOTS=<dir> to capture');

  for (const viewport of [
    { label: 'desktop', width: 1400, height: 1000 },
    { label: 'phone', width: 390, height: 844 },
  ] as const) {
    for (const scheme of ['light', 'dark'] as const) {
      for (const lang of ['en', 'nl'] as const) {
        test(`${viewport.label} ${scheme} ${lang}`, async ({ page, context, baseURL }) => {
          mkdirSync(SHOTS!, { recursive: true });
          await scenario(context, 'dhw:none', baseURL);
          await page.setViewportSize({ width: viewport.width, height: viewport.height });
          await page.emulateMedia({ colorScheme: scheme });
          await language(page, lang);
          const name = (screen: string) =>
            join(SHOTS!, `hotwater-${screen}-${viewport.label}-${scheme}-${lang}.png`);

          await page.goto('./#/settings/pump-duty');
          await expect(page.getByTestId('hot-water-tank')).toBeVisible();
          await page.waitForTimeout(600);
          await page.screenshot({ path: name('settings') });

          await home(page);
          await expect(lane(page)).toHaveCount(0);
          await page.waitForTimeout(800);
          const width = await page.evaluate(() => document.documentElement.scrollWidth);
          expect(width).toBeLessThanOrEqual(viewport.width);
          await page.screenshot({ path: name('home'), fullPage: true });
        });
      }
    }
  }
});
