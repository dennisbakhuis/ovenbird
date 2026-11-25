import { expect, test, type BrowserContext, type Page } from '@playwright/test';

test.skip(Boolean(process.env['BASE_URL']), 'mock scenarios');

async function scenario(context: BrowserContext, value: string, baseURL?: string): Promise<void> {
  await context.addCookies([{ name: 'ovenbird_mock', value, url: baseURL ?? 'http://127.0.0.1' }]);
}

async function english(page: Page): Promise<void> {
  await page.addInitScript(() => localStorage.setItem('ovenbird.language', 'en'));
}

test.describe('who controls the pump', () => {
  test.use({ viewport: { width: 1400, height: 1000 } });

  test('Shadow next to Node-RED: ovenbird only watches and shows both values', async ({
    page,
    context,
    baseURL,
  }) => {
    await scenario(context, 'mode:shadow', baseURL);
    await english(page);
    await page.goto('./#/home');
    const chip = page.getByTestId('mode-chip');
    await expect(chip).toHaveAttribute('data-control', 'watching');
    await expect(chip).toHaveClass(/manual/);
    await expect(page.getByTestId('strip-sentence')).toHaveText(
      'ovenbird only watches; another controller writes',
    );
    const line = page.getByTestId('control-line');
    await expect(line).toContainText('Nothing is sent to the pump');
    const would = await page.getByTestId('line-pair-would').innerText();
    const has = await page.getByTestId('line-pair-has').innerText();
    expect(Number(would.match(/\d+/)?.[0]) + 2).toBe(Number(has.match(/\d+/)?.[0]));
    await expect(page.getByTestId('setpoint-line')).toHaveAttribute('data-sending', 'false');
    await expect(page.getByTestId('setpoint-would')).toContainText('Would send');
    await expect(page.getByTestId('setpoint-has')).toContainText('Pump has');
    await expect(page.getByTestId('setpoint-line')).not.toContainText('Water setpoint');
    await line.getByRole('button').click();
    await expect(page.getByTestId('mode-sheet')).toBeVisible();
    await expect(page.getByTestId('sheet-control')).toContainText('only watches');
    await page.keyboard.press('Escape');
    await page.goto('./#/setpoint');
    await expect(page.getByTestId('waterfall').first()).toHaveAttribute('data-sends', 'false');
    await expect(page.getByTestId('waterfall').first()).toContainText('Would send');
    await expect(page.getByTestId('waterfall').first()).toContainText('Pump has');
    await page.goto('./#/system');
    await expect(page.getByTestId('mode-card')).toContainText('the mode is Shadow');
  });

  test('a latched hold: ovenbird waits until released, in plain words', async ({
    page,
    context,
    baseURL,
  }) => {
    await scenario(context, 'hold:latched', baseURL);
    await english(page);
    await page.goto('./#/activity/holds');
    const hold = page.getByTestId('strip-hold');
    await expect(hold).toContainText(
      'ovenbird is waiting until an administrator releases it: someone else changed the pump; the pump keeps 31 °C',
    );
    await expect(page.getByTestId('mode-chip')).toHaveAttribute('data-control', 'held');
    await expect(page.getByTestId('mode-chip')).toHaveClass(/limited/);
    await expect(page.getByTestId('hold-card')).toContainText('Someone else changed the pump');
    await expect(page.getByTestId('hold-card')).toContainText('3 holds in the last 12 h.');
    await expect(page.getByTestId('control-line')).toHaveAttribute('data-control', 'held');
  });

  test('paused: the line names the pause and the resume names the first write', async ({
    page,
    context,
    baseURL,
  }) => {
    await scenario(context, 'mode:paused', baseURL);
    await english(page);
    await page.goto('./#/home');
    await expect(page.getByTestId('mode-chip')).toHaveAttribute('data-control', 'paused');
    await expect(page.getByTestId('strip-sentence')).toHaveText(
      'Paused: ovenbird sends nothing; the pump keeps its last setpoint',
    );
    await page.getByTestId('mode-chip').click();
    await page.getByTestId('resume').click();
    await expect(page.getByTestId('resume-first')).toContainText(
      /First, ovenbird will set the water temperature to \d+ °C \(the pump has \d+ °C\)\./,
    );
    await page.getByRole('button', { name: 'Cancel' }).click();
  });

  test('a simulation carries a badge and the service time when its clock is off', async ({
    page,
    context,
    baseURL,
  }) => {
    await scenario(context, 'simulation:on.clock:behind', baseURL);
    await english(page);
    await page.goto('./#/home');
    await expect(page.getByTestId('sim-badge')).toHaveText(/Simulation/i);
    await expect(page.getByTestId('service-clock')).toContainText(/Service time \d+ \w+/);
  });

  test('no badge and no service time on a real installation in step with the browser', async ({
    page,
  }) => {
    await english(page);
    await page.goto('./#/home');
    await expect(page.getByTestId('room-value')).toContainText(/\d/);
    await expect(page.getByTestId('sim-badge')).toHaveCount(0);
    await expect(page.getByTestId('service-clock')).toHaveCount(0);
  });

  for (const [value, trust, text] of [
    ['room:old', 'reduced', 'ovenbird trusts it less (45 %)'],
    ['room:untrusted', 'untrusted', 'Room value not trusted'],
  ] as const) {
    test(`the room line follows the controller's trust: ${trust}`, async ({
      page,
      context,
      baseURL,
    }) => {
      await scenario(context, value, baseURL);
      await english(page);
      await page.goto('./#/home');
      const line = page.getByTestId('room-trust');
      await expect(line).toHaveAttribute('data-trust', trust);
      await expect(line).toContainText(text);
      await expect(line).not.toContainText('Sensor ok');
      await expect(line.getByRole('link')).toHaveAttribute('href', '#/setpoint');
    });
  }

  test('Dutch on a phone: the hold chip says "tot", the sentence is plain', async ({
    page,
    context,
    baseURL,
  }) => {
    await scenario(context, 'hold:timed', baseURL);
    await page.addInitScript(() => localStorage.setItem('ovenbird.language', 'nl'));
    await page.setViewportSize({ width: 400, height: 860 });
    await page.goto('./#/home');
    await expect(page.getByTestId('strip-hold').locator('.short')).toHaveText(/^tot \d\d:\d\d$/);
    await expect(page.getByTestId('control-line')).toContainText(
      /ovenbird wacht tot (vandaag|morgen) \d\d:\d\d/,
    );
    await expect(page.getByTestId('control-line')).not.toContainText('iemand anders');
    await expect(page.getByTestId('verdict-text')).toContainText(
      'iemand anders heeft de pomp aangepast',
    );
    await expect(page.getByTestId('line-pair-has')).toContainText('pomp heeft 31 °C');

    await page.goto('./#/pump');
    await expect(page.getByTestId('control-line')).toContainText(
      /ovenbird wacht tot (vandaag|morgen) \d\d:\d\d: iemand anders heeft de pomp aangepast/,
    );
  });

  test('Dutch on a phone: Shadow shows both values in the line', async ({
    page,
    context,
    baseURL,
  }) => {
    await scenario(context, 'mode:shadow', baseURL);
    await page.addInitScript(() => localStorage.setItem('ovenbird.language', 'nl'));
    await page.setViewportSize({ width: 400, height: 860 });
    await page.goto('./#/home');
    await expect(page.getByTestId('control-line')).toContainText(
      'ovenbird kijkt alleen mee; een andere regelaar stuurt de pomp',
    );
    await expect(page.getByTestId('line-pair-would')).toContainText('zou sturen');
    await expect(page.getByTestId('line-pair-has')).toContainText('pomp heeft');
    const strip = await page.getByTestId('topbar').boundingBox();
    expect(strip?.height ?? 0).toBeLessThanOrEqual(60);
  });
});
