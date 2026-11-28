import { expect, test, type Page } from '@playwright/test';
import { settled } from './settle';
import { pinCycleMinute } from './clock';

const NORMAL_MINUTE = 130;
const HOLD_MINUTE = 301;
const REFUSE_MINUTE = 331;

async function layout(page: Page) {
  const card = await page.getByTestId('setpoint-now').boundingBox();
  const chart = await page
    .getByTestId('setpoint-history')
    .getByRole('slider')
    .first()
    .boundingBox();
  if (!card || !chart) throw new Error('no layout');
  return { card: Math.round(card.height), chartY: Math.round(chart.y) };
}

test.describe('setpoint page', () => {
  test.skip(Boolean(process.env['BASE_URL']), 'setpoint interactions run against the mock only');

  test('fits the phone budget with details collapsed', async ({ page }) => {
    await page.setViewportSize({ width: 400, height: 860 });
    await page.goto('./#/setpoint');
    await expect(page.getByTestId('waterfall')).toBeVisible();
    await expect(page.getByTestId('decision-table').locator('tbody tr').first()).toBeVisible();
    await expect(page.getByTestId('reason-strip')).toBeVisible();
    await settled(page);
    const size = await page.evaluate(() => ({
      height: document.documentElement.scrollHeight,
      scroll: document.documentElement.scrollWidth,
      inner: window.innerWidth,
    }));
    expect(size.height, 'phone page height').toBeLessThanOrEqual(2500);
    expect(size.scroll, 'horizontal overflow').toBeLessThanOrEqual(size.inner);
  });

  test('shows episodes instead of minute rows and can switch to every decision', async ({
    page,
    context,
    baseURL,
  }) => {
    await pinCycleMinute(context, baseURL, NORMAL_MINUTE);
    await page.setViewportSize({ width: 1400, height: 1000 });
    await page.goto('./#/setpoint');
    const table = page.getByTestId('decision-table');
    await expect(table.locator('tbody tr')).toHaveCount(8);
    await expect(table.locator('[data-episode="start"]').first()).toBeVisible();
    await page.getByTestId('episodes-more').click();
    expect(await table.locator('tbody tr').count()).toBeGreaterThan(8);
    await page.getByTestId('view-all').click();
    await expect(table.locator('tbody tr')).toHaveCount(30);
  });

  for (const [name, minute] of [
    ['a normal decision', NORMAL_MINUTE],
    ['a hold', HOLD_MINUTE],
    ['a refusal', REFUSE_MINUTE],
  ] as const) {
    test(`the crosshair preview keeps the layout still when the current decision is ${name}`, async ({
      page,
      context,
      baseURL,
    }) => {
      await pinCycleMinute(context, baseURL, minute);
      await page.setViewportSize({ width: 1400, height: 1600 });
      await page.goto('./#/setpoint');
      const title = page.getByTestId('setpoint-now').locator('h2');
      await expect(title).toHaveText('Now');
      const slider = page.getByTestId('setpoint-history').getByRole('slider').first();
      await expect(slider).toBeInViewport();
      await expect(page.getByTestId('waterfall')).toBeVisible();
      await settled(page);
      const before = await layout(page);
      const box = await slider.boundingBox();
      if (!box) throw new Error('no chart');
      for (const fraction of [0.1, 0.3, 0.5, 0.7, 0.9]) {
        await page.mouse.move(box.x + box.width * fraction, box.y + 40);
        await expect(title).toContainText('crosshair');
        await settled(page);
        expect(await layout(page), `layout at ${fraction}`).toEqual(before);
      }
      await page.mouse.move(2, 2);
      await expect(title).toHaveText('Now');
    });
  }

  test('the crosshair previews a moment in the waterfall and a click opens it', async ({
    page,
    context,
    baseURL,
  }) => {
    await pinCycleMinute(context, baseURL, NORMAL_MINUTE);
    await page.setViewportSize({ width: 1400, height: 1000 });
    await page.goto('./#/setpoint');
    const title = page.getByTestId('setpoint-now').locator('h2');
    await expect(title).toHaveText('Now');
    const slider = page.getByTestId('setpoint-history').getByRole('slider').first();
    await page.setViewportSize({ width: 1400, height: 1600 });
    await expect(slider).toBeInViewport();
    const box = await slider.boundingBox();
    if (!box) throw new Error('no chart');
    await page.mouse.move(box.x + box.width * 0.3, box.y + 40);
    await expect(title).toContainText('crosshair');
    await page.mouse.click(box.x + box.width * 0.3, box.y + 40);
    await expect(page).toHaveURL(/#\/setpoint\?at=/);
    await page.mouse.move(2, 2);
    await expect(title).toHaveText('Selected moment');
    await expect(page.getByTestId('viewing-past')).toContainText('earlier decision');
  });

  test('keyboard: details, the why panel and the chart slider', async ({ page }) => {
    await page.setViewportSize({ width: 1400, height: 1000 });
    await page.goto('./#/setpoint');
    const inputs = page.getByTestId('setpoint-inputs');
    await inputs.locator('summary').focus();
    await page.keyboard.press('Enter');
    await expect(page.getByTestId('inputs-table')).toBeVisible();
    await page.getByTestId('setpoint-state').locator('summary').focus();
    await page.keyboard.press('Enter');
    await expect(page.getByTestId('pipeline')).toBeVisible();
    await expect(page.getByTestId('controller-state')).toBeVisible();

    await page.getByTestId('reason-why-button').focus();
    await page.keyboard.press('Enter');
    await expect(page.getByTestId('reason-why')).toBeVisible();
    await expect(page.getByTestId('note-clauses')).toBeVisible();
    await page.keyboard.press('Escape');
    await expect(page.getByTestId('reason-why')).toBeHidden();
    await expect(page.getByTestId('reason-why-button')).toBeFocused();

    const slider = page.getByTestId('setpoint-history').getByRole('slider').first();
    await slider.focus();
    await page.keyboard.press('End');
    await page.keyboard.press('ArrowLeft');
    await expect(page.getByTestId('setpoint-now').locator('h2')).toContainText('crosshair');
    await page.keyboard.press('Enter');
    await expect(page).toHaveURL(/#\/setpoint\?at=/);
  });
});
