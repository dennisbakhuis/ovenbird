import { mkdirSync } from 'node:fs';
import { settled } from './settle';
import { join } from 'node:path';
import {
  expect,
  test,
  type APIRequestContext,
  type BrowserContext,
  type Locator,
  type Page,
} from '@playwright/test';

test.skip(Boolean(process.env['BASE_URL']), 'the broker scenarios run on the mock');
test.describe.configure({ mode: 'serial' });

const SHOTS = process.env['INTEGRATIONS_SHOTS'];
const HEADERS = { 'Content-Type': 'application/json', 'X-Ovenbird-Request': '1' };
const INPUT_TOPIC = 'garden/temp';
const INPUT_SIGNAL = 'garden_temperature';
const INPUT_NAME = 'Garden temperature';

let tags = 0;

/**
 * Give the browser its own mock broker (the mock keeps it per scenario cookie), with the given
 * scenario options on top.
 */
async function scenario(context: BrowserContext, baseURL?: string, value = ''): Promise<void> {
  tags += 1;
  const tag = `tag:i${tags}${Math.random().toString(36).slice(2, 8)}`;
  await context.addCookies([
    {
      name: 'ovenbird_mock',
      value: value ? `${value}.${tag}` : tag,
      url: baseURL ?? 'http://127.0.0.1',
    },
  ]);
}

async function language(page: Page, lang: 'en' | 'nl'): Promise<void> {
  await page.addInitScript((value) => localStorage.setItem('ovenbird.language', value), lang);
}

interface StoredFields {
  version: number;
  fields: Record<string, { stored: unknown }>;
}

async function stored(request: APIRequestContext): Promise<StoredFields> {
  return (await (await request.get('api/v1/config')).json()) as StoredFields;
}

const SHARED = ['mqtt_inputs', 'control_outside_signal'] as const;
let original: Record<string, unknown> | null = null;

/** Put the shared settings this spec changes back to what they were, as the other specs expect. */
async function resetShared(request: APIRequestContext): Promise<void> {
  if (!original) return;
  const doc = await stored(request);
  const changes = Object.fromEntries(
    SHARED.filter(
      (id) => JSON.stringify(doc.fields[id]?.stored) !== JSON.stringify(original?.[id]),
    ).map((id) => [id, original?.[id] ?? null]),
  );
  if (Object.keys(changes).length === 0) return;
  await request.put('api/v1/config', {
    headers: HEADERS,
    data: { base_version: doc.version, changes, comment: 'e2e reset' },
  });
}

const card = (page: Page) => page.getByTestId('mqtt-card');
const save = (page: Page) => page.getByTestId('mqtt-save');

async function mqttPage(page: Page): Promise<void> {
  await page.goto('./#/settings/mqtt');
  await expect(page.getByTestId('mqtt-now')).toBeVisible();
}

async function runTest(page: Page, host: string): Promise<void> {
  await page.getByTestId('mqtt-host').fill(host);
  await page.getByTestId('mqtt-test').click();
  await expect(page.getByTestId('mqtt-result')).toBeVisible();
}

async function applyDraft(page: Page, count: string): Promise<void> {
  await expect(page.getByTestId('draft-count')).toHaveText(count);
  await page.getByTestId('draft-review').click();
  await page.getByTestId('preview-apply').click();
  await expect(page.getByTestId('preview-dialog')).toBeHidden();
  await expect(page.getByTestId('apply-notice')).toContainText(/Version \d+/);
}

async function noSideScroll(page: Page, width: number): Promise<void> {
  const scroll = await page.evaluate(() => document.documentElement.scrollWidth);
  expect(scroll).toBeLessThanOrEqual(width);
}

test.describe('MQTT connection', () => {
  test.use({ viewport: { width: 1400, height: 1000 } });

  test.beforeAll(async ({ request }) => {
    const doc = await stored(request);
    original = Object.fromEntries(SHARED.map((id) => [id, doc.fields[id]?.stored ?? null]));
  });

  test.afterAll(async ({ request }) => {
    await resetShared(request);
  });

  test('test, then save: the change is applied', async ({ page, context, baseURL }) => {
    await scenario(context, baseURL);
    await language(page, 'en');
    await mqttPage(page);
    await expect(page.getByTestId('mqtt-status')).toHaveText('Connected');
    await expect(page.getByTestId('mqtt-now')).toContainText('mosquitto:1883');
    await expect(save(page)).toBeDisabled();
    await expect(page.getByTestId('mqtt-save-why')).toHaveAttribute('data-block', 'unchanged');

    await runTest(page, 'broker.lan');
    await expect(page.getByTestId('mqtt-result')).toHaveAttribute('data-verdict', 'ok');
    await expect(page.getByTestId('mqtt-verdict')).toContainText(
      'The broker works and HeishaMon data arrives',
    );
    await expect(page.getByTestId('mqtt-result-broker')).toHaveText('broker.lan:1883');
    await expect(save(page)).toBeEnabled();
    await save(page).click();
    await expect(page.getByTestId('mqtt-apply')).toHaveAttribute('data-state', 'applying');
    await expect(page.getByTestId('mqtt-apply')).toHaveAttribute('data-state', 'applied', {
      timeout: 15_000,
    });
    await expect(page.getByTestId('mqtt-apply')).toContainText(/Applied at \d\d:\d\d/);
    await expect(page.getByTestId('mqtt-now')).toContainText('broker.lan:1883');
    await expect(page.getByTestId('mqtt-host')).toHaveValue('broker.lan');
  });

  test('a failing test keeps Save disabled', async ({ page, context, baseURL }) => {
    await scenario(context, baseURL);
    await language(page, 'en');
    await mqttPage(page);
    await runTest(page, 'bad.lan');
    await expect(page.getByTestId('mqtt-result')).toHaveAttribute('data-verdict', 'failed');
    await expect(page.getByTestId('mqtt-error')).toContainText(/reach|connect/i);
    await expect(save(page)).toBeDisabled();
    await expect(page.getByTestId('mqtt-save-why')).toHaveAttribute('data-block', 'failed');

    await page.getByTestId('mqtt-host').fill('mosquitto');
    await page.getByTestId('mqtt-username').fill('wrong');
    await page.getByTestId('mqtt-test').click();
    await expect(page.getByTestId('mqtt-result')).toHaveAttribute('data-verdict', 'failed');
    await expect(save(page)).toBeDisabled();

    await page.getByTestId('mqtt-username').fill('');
    await page.getByTestId('mqtt-base').fill('empty');
    await page.getByTestId('mqtt-test').click();
    await expect(page.getByTestId('mqtt-result')).toHaveAttribute('data-verdict', 'no_heishamon');
    await expect(save(page)).toBeDisabled();
  });

  test('changing the form after a test disables Save', async ({ page, context, baseURL }) => {
    await scenario(context, baseURL);
    await language(page, 'en');
    await mqttPage(page);
    await runTest(page, 'broker.lan');
    await expect(save(page)).toBeEnabled();
    await page.getByTestId('mqtt-host').fill('broker2.lan');
    await expect(save(page)).toBeDisabled();
    await expect(page.getByTestId('mqtt-save-why')).toHaveAttribute('data-block', 'changed');
    await page.getByTestId('mqtt-port').fill('70000');
    await expect(card(page).getByRole('alert')).toBeVisible();
    await expect(page.getByTestId('mqtt-test')).toBeDisabled();
  });

  test('a broker without data in time is reverted', async ({ page, context, baseURL }) => {
    await scenario(context, baseURL);
    await language(page, 'en');
    await mqttPage(page);
    await runTest(page, 'flaky.lan');
    await save(page).click();
    await expect(page.getByTestId('mqtt-apply')).toHaveAttribute('data-state', 'reverted', {
      timeout: 15_000,
    });
    await expect(page.getByTestId('mqtt-apply')).toContainText(/Reverted at \d\d:\d\d/);
    await expect(page.getByTestId('mqtt-now')).toContainText('mosquitto:1883');
  });

  test('fields set by the deployment are locked', async ({ page, context, baseURL }) => {
    await scenario(context, baseURL, 'mqtt:env');
    await language(page, 'en');
    await mqttPage(page);
    for (const key of ['host', 'port', 'username', 'password'])
      await expect(page.getByTestId(`mqtt-${key}`)).toBeDisabled();
    await expect(page.getByTestId('mqtt-host-row')).toContainText('Set by the deployment');
    await expect(page.getByTestId('mqtt-base')).toBeEnabled();
    await page.getByTestId('mqtt-base').fill('heishamon');
    await page.getByTestId('mqtt-test').click();
    await expect(page.getByTestId('mqtt-result')).toHaveAttribute('data-verdict', 'ok');
    await expect(save(page)).toBeEnabled();
  });

  test('while commands are on the broker cannot be changed', async ({ page, context, baseURL }) => {
    await scenario(context, baseURL, 'mqtt:commands');
    await language(page, 'en');
    await mqttPage(page);
    await expect(page.getByTestId('mqtt-commands')).toBeVisible();
    await runTest(page, 'broker.lan');
    await expect(page.getByTestId('mqtt-result')).toHaveAttribute('data-verdict', 'ok');
    await expect(save(page)).toBeDisabled();
    await expect(page.getByTestId('mqtt-save-why')).toHaveAttribute('data-block', 'commands');
  });

  test('test, then save in Dutch', async ({ page, context, baseURL }) => {
    await scenario(context, baseURL);
    await language(page, 'nl');
    await mqttPage(page);
    await expect(page.getByTestId('mqtt-card-title')).toContainText('MQTT-broker');
    await expect(page.getByTestId('mqtt-status')).toHaveText('Verbonden');
    await runTest(page, 'bad.lan');
    await expect(page.getByTestId('mqtt-verdict')).toContainText('Geen werkende verbinding');
    await runTest(page, 'broker.lan');
    await expect(page.getByTestId('mqtt-verdict')).toContainText(
      'De broker werkt en er komen HeishaMon-gegevens binnen',
    );
    await save(page).click();
    await expect(page.getByTestId('mqtt-apply')).toContainText(/Toegepast om \d\d:\d\d/, {
      timeout: 15_000,
    });
  });

  test('an MQTT sensor becomes the outside sensor of the curve', async ({
    page,
    context,
    baseURL,
  }) => {
    await scenario(context, baseURL);
    await language(page, 'en');
    await mqttPage(page);
    const before = await page.getByTestId('mqtt-inputs').locator('fieldset').count();
    await page.getByTestId('mqtt-input-add').click();
    const row = page.getByTestId(`mqtt-input-${before}`);
    await expect(row).toBeVisible();
    await expect(row.getByTestId('mqtt-input-caption')).toContainText(/topic/i);
    await row.getByTestId('mqtt-input-topic').fill(INPUT_TOPIC);
    await row.getByTestId('mqtt-input-signal').fill(INPUT_SIGNAL);
    await row.getByTestId('mqtt-input-unit').fill('°C');
    await expect(row.getByTestId('mqtt-input-caption')).toContainText(INPUT_SIGNAL);
    await applyDraft(page, '1 change');

    await page.goto('./#/settings/curve');
    const outside = page.getByTestId('curve-outside');
    await expect(outside).toBeVisible();
    await expect(page.getByTestId('curve-outside-note')).toContainText("pump's");
    const select = page.getByTestId('field-control_outside_signal').getByTestId('signal-select');
    await expect(select.locator(`option[value="${INPUT_SIGNAL}"]`)).toHaveCount(1);
    await select.selectOption(INPUT_SIGNAL);
    await expect(page.getByTestId('curve-outside-note')).toContainText('Only the heating curve');
    await applyDraft(page, '1 change');

    await page.reload();
    await expect(page.getByTestId('curve-outside-using')).toContainText(INPUT_NAME, {
      timeout: 15_000,
    });
    await page.goto('./#/setpoint');
    await expect(page.getByTestId('decision-facts')).toContainText(
      `The curve uses the outside temperature of ${INPUT_NAME}`,
    );
    await page.getByTestId('setpoint-state').locator('summary').click();
    await expect(page.getByTestId('state-outside-source')).toContainText(`from ${INPUT_NAME}`);
    await resetShared(page.request);
  });

  for (const lang of ['en', 'nl'] as const) {
    test(`a stale outside sensor shows the fall-back, ${lang}`, async ({
      page,
      context,
      baseURL,
    }) => {
      await scenario(context, baseURL, 'outside:stale');
      await language(page, lang);
      await page.goto('./#/settings/curve');
      await expect(page.getByTestId('curve-outside-fallback')).toContainText(
        lang === 'en'
          ? "the curve uses the pump's sensor now"
          : 'gebruikt nu de sensor van de pomp',
      );
      await page.goto('./#/setpoint');
      await expect(page.getByTestId('decision-facts')).toContainText(
        lang === 'en'
          ? 'The outside sensor Garden temperature is 42 min old'
          : 'De buitensensor Garden temperature is 42 min oud',
      );
      await page.getByTestId('setpoint-state').locator('summary').click();
      await expect(page.getByTestId('state-outside-source')).toContainText(
        lang === 'en' ? "pump's sensor (fallback)" : 'sensor van de pomp (terugval)',
      );
    });
  }

  test('no horizontal scroll at phone width', async ({ page, context, baseURL }) => {
    await scenario(context, baseURL, 'outside:stale');
    await language(page, 'nl');
    await page.setViewportSize({ width: 390, height: 844 });
    await mqttPage(page);
    await page.getByTestId('mqtt-more').click();
    await runTest(page, 'bad.lan');
    await noSideScroll(page, 390);
    await page.goto('./#/settings/curve');
    await expect(page.getByTestId('curve-outside-fallback')).toBeVisible();
    await noSideScroll(page, 390);
  });
});

/**
 * The element on desktop; the whole page on a phone, with the viewport as tall as the page so the
 * fixed tab bar sits at the bottom instead of over the element.
 */
async function shoot(page: Page, element: Locator, label: string, file: string): Promise<void> {
  const path = join(SHOTS!, file);
  if (label !== 'phone') return element.screenshot({ path }).then(() => undefined);
  const size = page.viewportSize() ?? { width: 390, height: 844 };
  const height = await page.evaluate(() => document.documentElement.scrollHeight);
  await page.setViewportSize({ width: size.width, height: Math.max(height, size.height) });
  await settled(page);
  await page.screenshot({ path });
  await page.setViewportSize(size);
}

test.describe('integration screenshots', () => {
  test.skip(!SHOTS, 'set INTEGRATIONS_SHOTS=<dir> to capture');

  const STATES = ['idle', 'tested', 'failed', 'applied', 'reverted', 'locked'] as const;

  for (const viewport of [
    { label: 'desktop', width: 1400, height: 1000 },
    { label: 'phone', width: 390, height: 844 },
  ] as const) {
    for (const scheme of ['light', 'dark'] as const) {
      for (const lang of ['en', 'nl'] as const) {
        const suffix = `${viewport.label}-${scheme}-${lang}`;
        for (const state of STATES) {
          test(`mqtt ${state} ${suffix}`, async ({ page, context, baseURL }) => {
            mkdirSync(SHOTS!, { recursive: true });
            await scenario(context, baseURL, state === 'locked' ? 'mqtt:env' : '');
            await page.setViewportSize({ width: viewport.width, height: viewport.height });
            await page.emulateMedia({ colorScheme: scheme });
            await language(page, lang);
            await mqttPage(page);
            if (state === 'tested') await runTest(page, 'broker.lan');
            if (state === 'failed') await runTest(page, 'bad.lan');
            if (state === 'applied' || state === 'reverted') {
              await runTest(page, state === 'applied' ? 'broker.lan' : 'flaky.lan');
              await save(page).click();
              await expect(page.getByTestId('mqtt-apply')).toHaveAttribute('data-state', state, {
                timeout: 15_000,
              });
            }
            await settled(page);
            await noSideScroll(page, viewport.width);
            await shoot(page, card(page), viewport.label, `mqtt-${state}-${suffix}.png`);
          });
        }
        test(`outside curve ${suffix}`, async ({ page, context, baseURL }) => {
          mkdirSync(SHOTS!, { recursive: true });
          await scenario(context, baseURL, 'outside:stale');
          await page.setViewportSize({ width: viewport.width, height: viewport.height });
          await page.emulateMedia({ colorScheme: scheme });
          await language(page, lang);
          await page.goto('./#/settings/curve');
          const outside = page.getByTestId('curve-outside');
          await expect(page.getByTestId('curve-outside-fallback')).toBeVisible();
          await settled(page);
          await noSideScroll(page, viewport.width);
          await shoot(page, outside, viewport.label, `outside-curve-${suffix}.png`);
        });
      }
    }
  }
});
