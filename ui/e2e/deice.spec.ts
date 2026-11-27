import { expect, test, type BrowserContext, type Page } from '@playwright/test';

test.skip(Boolean(process.env['BASE_URL']), 'the defrost scenarios run on the mock');

async function scenario(context: BrowserContext, value: string, baseURL?: string): Promise<void> {
  await context.addCookies([{ name: 'ovenbird_mock', value, url: baseURL ?? 'http://127.0.0.1' }]);
}

async function language(page: Page, lang: 'en' | 'nl'): Promise<void> {
  await page.addInitScript((value) => localStorage.setItem('ovenbird.language', value), lang);
}

const pill = (page: Page) => page.getByTestId('pump-state').locator('.pill');

test('a mode 2 defrost names its mode on Home, the Pump page and System', async ({
  page,
  context,
  baseURL,
}) => {
  await scenario(context, 'pump:defrost.deice:2', baseURL);
  await language(page, 'en');
  await page.goto('./#/');
  await expect(page.getByTestId('pump-state')).toHaveAttribute('data-state', 'defrost');
  await expect(pill(page)).toHaveText('Defrosting · mode 2');
  await expect(pill(page)).toHaveAttribute(
    'title',
    'Defrosting · mode 2 (hot gas, water pump off by design)',
  );
  await expect(page.getByTestId('pump-deice')).toHaveText(
    'Mode 2: hot gas, the water pump is off by design.',
  );
  await page.screenshot({ path: 'e2e/shots/deice-home.png' });

  await page.goto('./#/pump');
  await expect(page.getByTestId('loop-deice')).toHaveText(
    'Defrosting · mode 2 (hot gas, water pump off by design)',
  );

  await page.goto('./#/system');
  await expect(page.getByTestId('about-pump-model')).toHaveText(
    'WH-MXC12J9E8 (defrost facts from the Panasonic service manual)',
  );
});

test('a defrost of an unknown model stays plain and System says so', async ({
  page,
  context,
  baseURL,
}) => {
  await scenario(context, 'pump:defrost', baseURL);
  await language(page, 'en');
  await page.goto('./#/');
  await expect(page.getByTestId('pump-state')).toHaveAttribute('data-state', 'defrost');
  await expect(pill(page)).toHaveText('Defrosting');
  await expect(page.getByTestId('pump-deice')).toHaveCount(0);
  await page.goto('./#/system');
  await expect(page.getByTestId('about-pump-model')).toHaveText(
    'not recognised; generic defrost handling',
  );
});

test.describe('Dutch phone', () => {
  test.use({ viewport: { width: 400, height: 860 } });

  test('names the mode within the phone width', async ({ page, context, baseURL }) => {
    await scenario(context, 'pump:defrost.deice:2', baseURL);
    await language(page, 'nl');
    await page.goto('./#/');
    await expect(pill(page)).toHaveText('Ontdooien · modus 2');
    await expect(page.getByTestId('pump-deice')).toHaveText(
      'Modus 2: heet gas, de waterpomp staat bewust uit.',
    );
    await page.getByTestId('pump-card').screenshot({ path: 'e2e/shots/deice-home-nl-phone.png' });
    const header = await page.getByTestId('pump-state').boundingBox();
    expect(header?.height ?? 0, 'the state chip stays on one line').toBeLessThanOrEqual(40);
    await page.goto('./#/pump');
    await expect(page.getByTestId('loop-state')).toHaveText('Ontdooien · modus 2');
    await expect(page.getByTestId('loop-deice')).toHaveText(
      'Ontdooien · modus 2 (heet gas, waterpomp bewust uit)',
    );
    const overflow = await page.evaluate(
      () => document.documentElement.scrollWidth - window.innerWidth,
    );
    expect(overflow, 'horizontal overflow').toBeLessThanOrEqual(0);
    await page.screenshot({ path: 'e2e/shots/deice-pump-nl-phone.png', fullPage: true });
  });
});
