import { expect, test } from '@playwright/test';
import { sheetVersion } from './sheet';

test.skip(Boolean(process.env['BASE_URL']), 'state-changing flows run against the mock only');

test.use({ viewport: { width: 1400, height: 1000 } });
test.describe.configure({ mode: 'serial' });

test('pause and resume switch between Auto and Paused', async ({ page }) => {
  await page.goto('./#/home');
  const chip = page.getByTestId('mode-chip');
  await expect(chip).toHaveAttribute('data-mode', 'auto');
  await chip.click();
  await page.getByTestId('pause').click();
  await expect(chip).toHaveAttribute('data-mode', 'paused');
  await expect(chip).toHaveAttribute('data-control', 'paused');
  await expect(chip).toContainText('Paused: ovenbird sends nothing until you resume');
  await expect(page.getByTestId('sheet-control')).toHaveText(
    'Paused: ovenbird sends nothing; the pump keeps its last setpoint.',
  );
  await expect(page.getByTestId('control-line')).toHaveAttribute('data-control', 'paused');
  await expect(page.getByTestId('line-pair-would')).toContainText(/would send \d+ °C/);
  await expect(page.getByTestId('line-pair-has')).toContainText(/pump has \d+ °C/);
  await page.getByTestId('resume').click();
  await expect(page.getByTestId('resume-first')).toContainText(
    /First, ovenbird will set the water temperature to \d+ °C \(the pump has \d+ °C\)/,
  );
  await page.getByTestId('resume-confirm').click();
  await expect(chip).toHaveAttribute('data-mode', 'auto');
});

test('an admin can release the hold', async ({ page }) => {
  await page.goto('./#/activity/holds');
  await expect(page.getByTestId('strip-hold')).toBeVisible();
  await page.getByRole('button', { name: 'Release hold' }).click();
  await page.getByLabel('Reason (optional)').fill('checked the remote');
  await page.getByRole('button', { name: 'Release now' }).click();
  await expect(page.getByTestId('no-hold')).toBeVisible();
  await expect(page.getByTestId('strip-hold')).toBeHidden();
});

test('Dutch shows its own wording while paused', async ({ page }) => {
  await page.goto('./#/home');
  await page.getByTestId('settings-menu-button').click();
  await page.getByTestId('language-nl').check();
  await page.keyboard.press('Escape');
  await page.getByTestId('mode-chip').click();
  await page.getByTestId('pause').click();
  await expect(page.getByTestId('mode-chip')).toContainText(
    'Gepauzeerd: ovenbird stuurt niets tot je hervat',
  );
  await page.getByTestId('resume').click();
  await page.getByTestId('resume-confirm').click();
  await expect(page.getByTestId('mode-chip')).toHaveAttribute('data-mode', 'auto');
});

test('edit the curve, review it as a picture and apply', async ({ page }) => {
  await page.goto('./#/settings/curve');
  expect(await sheetVersion(page)).toBe('Settings v12');
  await page.getByTestId('point-water-1-inc').click();
  await expect(page.getByTestId('draft-count')).toHaveText('1 change');
  await expect(page.getByTestId('curve-draft')).toBeVisible();
  await expect(page.getByTestId('curve-draft-now')).toBeVisible();
  await expect(page.getByTestId('strip-draft')).toBeVisible();

  await page.getByTestId('draft-review').click();
  const dialog = page.getByTestId('preview-dialog');
  await expect(dialog).toBeVisible();
  const row = page.getByTestId('diff-row-control_curve');
  await expect(row.locator('svg[role="img"]')).toHaveAttribute('aria-label', /largest change \+1/);
  await expect(page.getByTestId('preview-now')).toBeVisible();
  await expect(page.getByTestId('preview-delta')).toHaveText(/K now|no change now/);
  await expect(page.getByTestId('preview-openloop')).toBeVisible();
  await expect(page.getByTestId('preview-identity')).toHaveAttribute('data-ok', 'true');
  await expect(page.getByTestId('preview-openloop').getByTestId('time-chart')).toBeVisible();
  await page.screenshot({ path: 'e2e/shots/flow-review-curve.png' });
  await page.getByTestId('preview-apply').click();

  await expect(dialog).toBeHidden();
  await expect(page.getByTestId('apply-notice')).toContainText('Version 13');
  await expect.poll(() => sheetVersion(page)).toBe('Settings v13');
  await expect(page.getByTestId('strip-draft')).toBeHidden();
  await expect(page.getByTestId('draft-bar')).toBeHidden();
});

test('edit the comfort target, review and apply', async ({ page }) => {
  await page.goto('./#/settings/room');
  await expect(page.getByTestId('room-status')).toBeVisible();
  const comfort = page.getByLabel('Comfort target', { exact: true });
  await comfort.fill('22.4');
  await comfort.press('Enter');
  await expect(
    page.getByTestId('field-control_comfort_c').getByTestId('changed-chip'),
  ).toBeVisible();
  await page.getByTestId('comfort-stepper-inc').click();
  await expect(comfort).toHaveValue('22.5');
  await expect(page.getByTestId('draft-count')).toHaveText('1 change');

  await page.getByTestId('draft-review').click();
  await expect(page.getByTestId('preview-comfort')).toContainText(
    'Warmer: comfort temperature 21.5 → 22.5 °C.',
  );
  await expect(page.getByTestId('preview-comfort-water')).toBeVisible();
  await expect(page.getByTestId('diff-row-control_comfort_c')).toHaveCount(0);
  await page.getByTestId('preview-details').locator('summary').first().click();
  await expect(page.getByTestId('diff-row-control_comfort_c')).toContainText('22.5');
  await expect(page.getByTestId('diff-row-control_comfort_c')).toContainText('+1 K');
  await expect(page.getByTestId('preview-now')).toBeVisible();
  await page.getByTestId('preview-details').locator('summary').first().click();
  await page.getByTestId('preview-comment').fill('a bit warmer');
  await page.getByTestId('preview-apply').click();

  await expect(page.getByTestId('preview-dialog')).toBeHidden();
  await expect(page.getByTestId('apply-notice')).toContainText(/Version \d+/);
  await expect(comfort).toHaveValue('22.5');
  await expect(page.getByTestId('field-control_comfort_c').getByTestId('changed-chip')).toHaveCount(
    0,
  );
});

test('the comfort temperature is one tap from Home and goes through the review', async ({
  page,
}) => {
  await page.goto('./#/home');
  const target = page.getByRole('button', { name: /Change the comfort temperature/ });
  await expect(target).toHaveText(/Target \d+\.\d °C/);
  await expect(target).toBeEnabled();
  await target.click();
  const sheet = page.getByTestId('comfort-sheet');
  await expect(sheet).toBeVisible();
  const nowText = page.getByTestId('comfort-sheet-now');
  await expect(nowText).toContainText(/Now \d+\.\d °C/);
  const before = Number(/Now (\d+\.\d) °C/.exec((await nowText.textContent()) ?? '')?.[1]);
  const after = (before - 0.2).toFixed(1);
  await expect(page.getByTestId('comfort-sheet-review')).toBeDisabled();
  await page.getByTestId('comfort-sheet-stepper-dec').click();
  await page.getByTestId('comfort-sheet-stepper-dec').click();
  await page.getByTestId('comfort-sheet-review').click();
  await expect(sheet).toBeHidden();
  const dialog = page.getByTestId('preview-dialog');
  await expect(dialog).toBeVisible();
  await expect(page.getByTestId('preview-comfort')).toContainText(
    `Slightly cooler: comfort temperature ${before.toFixed(1)} → ${after} °C.`,
  );
  await page.screenshot({ path: 'e2e/shots/flow-comfort-home.png' });
  await page.getByTestId('preview-apply').click();
  await expect(dialog).toBeHidden();
  await target.click();
  await expect(page.getByTestId('comfort-sheet-now')).toContainText(`Now ${after} °C`);
  await page.keyboard.press('Escape');
  await expect(sheet).toBeHidden();
});

test('the activity range picker sets the window of the timeline and the tabs', async ({ page }) => {
  const windows: string[] = [];
  page.on('request', (request) => {
    const url = new URL(request.url());
    if (url.pathname.endsWith('/api/v1/alarms')) windows.push(url.search);
  });
  await page.goto('./#/activity');
  const range = page.getByTestId('activity-range');
  await expect(range).toBeVisible();
  await expect(page.getByTestId('activity-range-24h')).toHaveAttribute('aria-pressed', 'true');
  await expect.poll(() => windows.at(-1) ?? '').toMatch(/from=.+&to=/);
  const span = (search: string) => {
    const query = new URLSearchParams(search);
    return (Date.parse(query.get('to') ?? '') - Date.parse(query.get('from') ?? '')) / 3_600_000;
  };
  expect(span(windows.at(-1) ?? '')).toBe(24);
  await page.getByTestId('activity-range-7d').click();
  await expect.poll(() => span(windows.at(-1) ?? '')).toBe(168);
  await expect(page.getByTestId('journal-list')).toContainText('Room too cold');
  await page.getByTestId('activity-range-custom').click();
  await page.getByTestId('activity-range-from').fill('2026-11-01T10:00');
  await page.getByTestId('activity-range-to').fill('2026-11-01T09:00');
  await expect(range.getByRole('alert')).toBeVisible();
  await page.getByTestId('activity-range-to').fill('2026-11-02T10:00');
  await expect(range.getByRole('alert')).toBeHidden();
  await expect.poll(() => span(windows.at(-1) ?? '')).toBe(24);

  await page.goto('./#/activity/commands');
  const counters = page.getByTestId('command-counters');
  await expect(page.getByText('Since the service started')).toBeVisible();
  await expect(counters.locator('[data-counter=failed]')).toBeVisible();
  await expect(counters.locator('[data-counter=retried]')).toBeVisible();
});

test('active alarms say what ovenbird does and what you can do', async ({ page }) => {
  await page.goto('./#/activity');
  const advice = page.locator('[data-testid^=alarm-advice-]').first();
  await expect(advice).toContainText('ovenbird now:');
  await expect(advice).toContainText('You:');
});

test('quiet mode picks a time zone from a list and offers the browser zone', async ({ page }) => {
  await page.goto('./#/settings/quiet');
  const select = page.getByTestId('quiet-timezone');
  await expect(select).toBeVisible();
  await expect(page.getByTestId('quiet-now')).toHaveText(/^Now \d\d:\d\d in [A-Za-z_/]+$/);
  const browser = await page.evaluate(() => Intl.DateTimeFormat().resolvedOptions().timeZone);
  const other = browser === 'Asia/Tokyo' ? 'Europe/Lisbon' : 'Asia/Tokyo';
  await select.selectOption(other);
  await expect(page.getByTestId('quiet-now')).toContainText(other);
  await expect(page.getByTestId('quiet-zone-differs')).toContainText(browser);
  await page.getByTestId('quiet-use-browser').click();
  await expect(select).toHaveValue(browser);
  await expect(page.getByTestId('quiet-zone-differs')).toBeHidden();
  await page.getByTestId('draft-discard').click();
});

test('the section picker replaces the tab row on a phone', async ({ page }) => {
  await page.setViewportSize({ width: 400, height: 860 });
  await page.goto('./#/settings/curve');
  await expect(page.getByTestId('settings-rail')).toBeHidden();
  await page.getByTestId('settings-picker').locator('select').selectOption('quiet');
  await expect(page).toHaveURL(/#\/settings\/quiet$/);
  await expect(page.getByTestId('quiet-editor')).toBeVisible();
});

test('phone page heights stay within budget', async ({ page }) => {
  await page.setViewportSize({ width: 400, height: 860 });
  await page.goto('./#/settings/room');
  await expect(page.getByTestId('room-status')).toBeVisible();
  await page.waitForTimeout(300);
  const room = await page.evaluate(() => document.documentElement.scrollHeight);
  expect(room, 'Room height at 400 px').toBeLessThanOrEqual(1600);

  await page.goto('./#/settings/emitter');
  await page.getByTestId('emitter-radiators').check();
  await expect(page.getByTestId('preset-diff')).toContainText('Radiators');
  await expect(
    page.getByTestId('preset-diff').getByTestId('diff-row-control_max_supply_c'),
  ).toBeVisible();
  await page.waitForTimeout(300);
  await page.screenshot({ path: 'e2e/shots/flow-emitter-switch-phone.png', fullPage: true });
  const emitter = await page.evaluate(() => document.documentElement.scrollHeight);
  expect(emitter, 'Emitter height at 400 px with a preset switch').toBeLessThanOrEqual(1800);
  await page.getByTestId('draft-discard').click();
  await expect(page.getByTestId('draft-bar')).toBeHidden();
});

test('settings work from the keyboard', async ({ page }) => {
  await page.goto('./#/settings/curve');
  const handle = page.getByTestId('curve-handle-1');
  await handle.focus();
  await page.keyboard.press('ArrowUp');
  await expect(page.getByTestId('curve-readout')).toContainText('Point 2');
  await expect(page.getByTestId('draft-count')).toHaveText('1 change');
  await page.keyboard.press('Shift+ArrowDown');
  await expect(handle).toHaveAttribute('aria-valuenow', /34\.5|35\.5/);
  await page.getByTestId('undo-control_curve').focus();
  await page.keyboard.press('Enter');
  await expect(page.getByTestId('draft-bar')).toBeHidden();

  await page.goto('./#/settings/room');
  const comfort = page.getByLabel('Comfort target', { exact: true });
  const before = await comfort.inputValue();
  await comfort.focus();
  await page.keyboard.press('ArrowUp');
  await expect(comfort).not.toHaveValue(before);
  const why = page.getByTestId('why-control_comfort_c-button');
  await why.focus();
  await page.keyboard.press('Enter');
  await expect(page.getByTestId('why-control_comfort_c')).toBeVisible();
  await page.keyboard.press('Escape');
  await expect(page.getByTestId('why-control_comfort_c')).toBeHidden();
  await expect(why).toBeFocused();
  await page.getByTestId('draft-review').focus();
  await page.keyboard.press('Enter');
  await expect(page.getByTestId('preview-dialog')).toBeVisible();
  await page.keyboard.press('Escape');
  await expect(page.getByTestId('preview-dialog')).toBeHidden();
  await page.getByTestId('draft-discard').click();
});

test('a locked field is not editable and names its variable', async ({ page }) => {
  await page.goto('./#/settings/behaviour');
  const field = page.getByTestId('field-control_min_setpoint_c');
  await expect(field.getByLabel('Minimum water setpoint', { exact: true })).toBeDisabled();
  await expect(field.getByTestId('locked-note')).toContainText('OVENBIRD_CONTROL_MIN_SETPOINT_C');
});

test('the geolocation button is hidden in a non-secure context', async ({ page }) => {
  await page.addInitScript(() =>
    Object.defineProperty(window, 'isSecureContext', { value: false }),
  );
  await page.goto('./#/settings/weather');
  await expect(page.getByTestId('weather-location')).toBeVisible();
  await expect(page.getByTestId('use-location')).toHaveCount(0);
});

test.describe('secure context with a mocked position', () => {
  test.use({ geolocation: { latitude: 52.0949, longitude: 5.1234 }, permissions: ['geolocation'] });

  test('"Use my location" fills rounded coordinates and shows the source', async ({ page }) => {
    await page.goto('./#/settings/weather');
    await page.getByTestId('use-location').click();
    await expect(page.getByLabel('Latitude', { exact: true })).toHaveValue('52.09');
    await expect(page.getByLabel('Longitude', { exact: true })).toHaveValue('5.12');
    await expect(page.getByTestId('weather-source')).toContainText('this browser');
  });
});

test('a pump setting is written with confirmation and verified', async ({ page }) => {
  await page.goto('./#/pump');
  await page.getByTestId('pump-edit-heat_delta').click();
  await page.getByTestId('pump-input').fill('4');
  await page.getByTestId('pump-confirm-input').fill('4');
  await page.getByTestId('pump-confirm').click();
  await expect(page.getByTestId('command-progress')).toBeVisible();
  await expect(page.getByTestId('command-progress')).toHaveAttribute('data-status', 'verified', {
    timeout: 15_000,
  });
  await expect(page.getByTestId('pump-value-heat_delta')).toContainText('4');
});

test('without a preview endpoint the dialog validates only and still applies', async ({ page }) => {
  await page.route('**/api/v1/config/preview', (route) =>
    route.fulfill({ status: 404, contentType: 'application/json', body: '{"detail":"nf"}' }),
  );
  await page.goto('./#/settings/room');
  await page.getByLabel('Comfort target', { exact: true }).fill('22.1');
  await page.getByLabel('Comfort target', { exact: true }).press('Enter');
  await page.getByTestId('draft-review').click();
  await expect(page.getByTestId('preview-missing')).toBeVisible();
  await page.screenshot({ path: 'e2e/shots/flow-preview-missing.png' });
  await expect(page.getByTestId('preview-now')).toHaveCount(0);
  await expect(page.getByTestId('preview-comfort')).toContainText('comfort temperature');
  await expect(page.getByTestId('preview-apply')).toBeEnabled();
  await page.getByTestId('preview-apply').click();
  await expect(page.getByTestId('apply-notice')).toContainText('Version');
});

test('a rollback goes through the rollback endpoint and is recorded as one', async ({ page }) => {
  await page.goto('./#/settings/versions');
  await expect(page.getByTestId('rollback-11')).toBeVisible();
  const before = await sheetVersion(page);
  await page.getByTestId('rollback-11').click();
  await expect(page.getByTestId('rollback-dialog')).toBeVisible();
  await expect(page.getByTestId('rollback-dialog').getByTestId('diff-table')).toBeVisible();
  await expect(
    page.getByTestId('rollback-dialog').getByTestId('diff-table').locator('li').first(),
  ).toBeVisible();
  await page.screenshot({ path: 'e2e/shots/flow-rollback-dialog.png' });
  await page.getByTestId('rollback-comment').fill('back to 11');
  await page.getByTestId('rollback-confirm').click();
  await expect(page.getByTestId('rollback-dialog')).toBeHidden();
  await expect(page.getByTestId('versions-message')).toContainText('Rolled back');
  await expect.poll(() => sheetVersion(page)).not.toBe(before);
  const newest = Number(before.replace(/\D/g, '')) + 1;
  await expect(page.getByTestId(`version-${newest}`)).toContainText('rollback');
  await expect(page.getByTestId(`version-${newest}`)).toContainText('back to 11');
});

test('a validation error from the server blocks applying and is explained', async ({ page }) => {
  await page.goto('./#/settings/room');
  const room = page.locator('select#field-control_room_signal');
  await expect(room).toBeVisible();
  await room.selectOption('');
  await page.getByTestId('draft-review').click();
  await expect(page.getByTestId('preview-errors')).toContainText('room sensor');
  await page.screenshot({ path: 'e2e/shots/flow-preview-errors.png' });
  await expect(page.getByTestId('preview-apply')).toBeDisabled();
});

test('a change applied while paused says that nothing is sent', async ({
  page,
  context,
  baseURL,
}) => {
  await context.addCookies([
    { name: 'ovenbird_mock', value: 'mode:paused', url: baseURL ?? 'http://127.0.0.1' },
  ]);
  await page.goto('./#/settings/room');
  const comfort = page.getByLabel('Comfort target', { exact: true });
  await comfort.fill('21.6');
  await comfort.press('Enter');
  await page.getByTestId('draft-review').click();
  await page.getByTestId('preview-apply').click();
  await expect(page.getByTestId('apply-notice')).toContainText(
    'But ovenbird sends nothing to the pump while paused.',
  );
});
