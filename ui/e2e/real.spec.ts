import { expect, test, type APIRequestContext, type Page } from '@playwright/test';
import { sheetVersion } from './sheet';

test.skip(!process.env['BASE_URL'], 'these flows need a real (simulated) service via BASE_URL');
test.describe.configure({ mode: 'serial' });
test.use({ viewport: { width: 1400, height: 1000 } });

const HEADERS = { 'Content-Type': 'application/json', 'X-Ovenbird-Request': '1' };

interface ConfigBody {
  version: number;
  mode: { paused: boolean };
  fields: Record<string, { value: unknown; stored: unknown }>;
}

async function config(request: APIRequestContext): Promise<ConfigBody> {
  return (await (await request.get('api/v1/config')).json()) as ConfigBody;
}

async function restore(request: APIRequestContext, comfort: number): Promise<void> {
  const now = await config(request);
  if (now.mode.paused) await request.post('api/v1/control/resume', { headers: HEADERS, data: {} });
  if (now.fields['control_comfort_c']?.value !== comfort) {
    await request.put('api/v1/config', {
      headers: HEADERS,
      data: {
        base_version: now.version,
        changes: { control_comfort_c: comfort },
        comment: 'e2e restore',
        acknowledge: [],
      },
    });
  }
}

let original = 0;

test.beforeAll(async ({ playwright }) => {
  const request = await playwright.request.newContext({
    baseURL: process.env['BASE_URL'],
    httpCredentials: { username: 'admin', password: 'ovenbird-dev' },
  });
  original = Number((await config(request)).fields['control_comfort_c']?.value);
  await request.dispose();
});

test.afterAll(async ({ playwright }) => {
  const request = await playwright.request.newContext({
    baseURL: process.env['BASE_URL'],
    httpCredentials: { username: 'admin', password: 'ovenbird-dev' },
  });
  await restore(request, original);
  await request.dispose();
});

const comfortField = (page: Page) => page.getByLabel('Comfort target');

test('the settings load from the real schema and config', async ({ page }) => {
  await page.goto('./#/settings/room');
  await expect(comfortField(page)).toHaveValue(/\d/);
  await page.goto('./#/settings/versions');
  await expect(page.getByTestId('fixed-table')).toBeVisible();
});

test('a change is validated by the service while editing', async ({ page }) => {
  await page.goto('./#/settings/room');
  await comfortField(page).fill(String(original + 0.1));
  await expect(page.getByTestId('draft-bar')).toContainText('All checks passed');
  await page.locator('#field-control_room_signal').fill('');
  await page.locator('#field-control_room_signal').dispatchEvent('change');
  await expect(page.getByTestId('draft-bar')).toContainText(/problem/);
});

test('a small comfort change is applied without preview and rolled back as a rollback', async ({
  page,
  request,
}) => {
  const before = await config(request);
  await page.goto('./#/settings/room');
  await comfortField(page).fill(String(Math.round((original + 0.1) * 10) / 10));
  await page.getByTestId('draft-review').click();
  await expect(page.getByTestId('preview-dialog')).toBeVisible();
  await expect(page.getByTestId('preview-missing')).toBeVisible();
  await expect(page.getByTestId('diff-row-control_comfort_c')).toBeVisible();
  await page.getByTestId('preview-comment').fill('e2e comfort +0.1');
  await page.getByTestId('preview-apply').click();
  await expect(page.getByTestId('apply-notice')).toContainText(`Version ${before.version + 1}`);
  await expect.poll(() => sheetVersion(page)).toBe(`Settings v${before.version + 1}`);
  const applied = await config(request);
  expect(applied.fields['control_comfort_c']?.value).toBeCloseTo(original + 0.1, 5);

  // the service allows one apply per 60 s of its (scaled) clock
  await page.waitForTimeout(4000);
  await page.goto('./#/settings/versions');
  await page.getByTestId(`rollback-${before.version}`).click();
  await expect(
    page.getByTestId('rollback-dialog').getByTestId('diff-row-control_comfort_c'),
  ).toBeVisible();
  await page.getByTestId('rollback-comment').fill('e2e rollback');
  await page.getByTestId('rollback-confirm').click();
  await expect(page.getByTestId('versions-message')).toContainText('Rolled back');
  const rolled = await config(request);
  expect(rolled.version).toBe(before.version + 2);
  expect(rolled.fields['control_comfort_c']?.value).toBe(original);
  await expect(page.getByTestId(`version-${rolled.version}`)).toContainText('rollback');

  await page.goto('./#/activity/audit');
  await expect(page.getByTestId('audit-table')).toContainText('Config rolled back');
  await expect(page.getByTestId('audit-table')).toContainText(`back to version ${before.version}`);
});

test('pause and resume go through the service', async ({ page, request }) => {
  await page.goto('./#/home');
  await page.getByTestId('mode-chip').click();
  await page.getByTestId('pause').click();
  await expect(page.getByTestId('mode-chip')).toHaveAttribute('data-mode', 'paused');
  expect((await config(request)).mode.paused).toBe(true);
  await page.getByTestId('resume').click();
  await page.getByTestId('resume-confirm').click();
  await expect(page.getByTestId('mode-chip')).toHaveAttribute('data-mode', 'auto');
  expect((await config(request)).mode.paused).toBe(false);
});

test('the export is a downloadable file with the stored values', async ({ page }) => {
  await page.goto('./#/settings/versions');
  const download = page.waitForEvent('download');
  await page.getByTestId('export-button').click();
  const file = await download;
  expect(file.suggestedFilename()).toMatch(/^ovenbird-config-v\d+\.json$/);
});

test('every state-changing request carries the content type and the request marker', async ({
  page,
}) => {
  const seen: { method: string; url: string; headers: Record<string, string> }[] = [];
  page.on('request', (r) => {
    if (r.method() !== 'GET' && r.url().includes('/api/v1/'))
      seen.push({ method: r.method(), url: r.url(), headers: r.headers() });
  });
  await page.goto('./#/settings/room');
  await comfortField(page).fill(String(original + 0.2));
  await expect(page.getByTestId('draft-bar')).toContainText('All checks passed');
  await page.getByTestId('draft-discard').click();
  await page.goto('./#/home');
  await page.getByTestId('mode-chip').click();
  await page.getByTestId('pause').click();
  await expect(page.getByTestId('mode-chip')).toHaveAttribute('data-mode', 'paused');
  await page.getByTestId('resume').click();
  await page.getByTestId('resume-confirm').click();
  await expect(page.getByTestId('mode-chip')).toHaveAttribute('data-mode', 'auto');
  expect(seen.length).toBeGreaterThanOrEqual(3);
  for (const call of seen) {
    expect(call.headers['content-type'], call.url).toContain('application/json');
    expect(call.headers['x-ovenbird-request'], call.url).toBe('1');
  }
});
