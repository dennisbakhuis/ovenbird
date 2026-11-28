import { defineConfig } from '@playwright/test';

const baseURL = process.env['BASE_URL'];
const MOCK_PORT = process.env['E2E_PORT'] ?? '5199';
const MOCK_URL = `http://127.0.0.1:${MOCK_PORT}`;
const CLOCK_SHIFT = process.env['E2E_CLOCK_SHIFT'];

/** Browser and mock service run in one fixed zone, so the suite reads the same on every machine and CI. */
const E2E_TIMEZONE = 'Europe/Amsterdam';

/**
 * E2E_CLOCK_SHIFT=<minutes> runs the mock service clock that far behind, to run the suite at
 * another minute of the mock's 6-hour cycle and another time of day.
 */
const clockState =
  !baseURL && CLOCK_SHIFT
    ? {
        cookies: [
          {
            name: 'ovenbird_clock',
            value: CLOCK_SHIFT,
            domain: '127.0.0.1',
            path: '/',
            expires: -1,
            httpOnly: false,
            secure: false,
            sameSite: 'Lax' as const,
          },
        ],
        origins: [],
      }
    : undefined;

export default defineConfig({
  testDir: 'e2e',
  projects: [
    { name: 'routes', testMatch: 'routes.spec.ts' },
    { name: 'flows', testMatch: 'flows.spec.ts', dependencies: ['routes'] },
    { name: 'real', testMatch: 'real.spec.ts', dependencies: ['routes'] },
    { name: 'weather', testMatch: 'weather-states.spec.ts', dependencies: ['routes'] },
    { name: 'setpoint', testMatch: 'setpoint.spec.ts', dependencies: ['routes'] },
    { name: 'help', testMatch: 'help.spec.ts', dependencies: ['routes'] },
    { name: 'control', testMatch: 'control.spec.ts', dependencies: ['flows'] },
    { name: 'stove', testMatch: 'stove.spec.ts', dependencies: ['routes'] },
    { name: 'shadow', testMatch: 'shadow.spec.ts', dependencies: ['routes'] },
    { name: 'trial', testMatch: 'trial.spec.ts', dependencies: ['routes'] },
    { name: 'house', testMatch: 'house.spec.ts', dependencies: ['routes'] },
    { name: 'ha', testMatch: 'ha.spec.ts', dependencies: ['routes'] },
    { name: 'deice', testMatch: 'deice.spec.ts', dependencies: ['routes'] },
    { name: 'system', testMatch: 'system.spec.ts', dependencies: ['routes'] },
    { name: 'chunks', testMatch: 'chunks.spec.ts', dependencies: ['routes'] },
    { name: 'live', testMatch: 'live.spec.ts', dependencies: ['routes'] },
    { name: 'topbar', testMatch: 'topbar.spec.ts', dependencies: ['routes'] },
    { name: 'features', testMatch: 'features.spec.ts', dependencies: ['routes'] },
    { name: 'war', testMatch: 'war.spec.ts', dependencies: ['routes'] },
    { name: 'data', testMatch: 'data.spec.ts', dependencies: ['routes'] },
    { name: 'replay', testMatch: 'replay.spec.ts', dependencies: ['routes'] },
    { name: 'hotwater', testMatch: 'hotwater.spec.ts', dependencies: ['flows'] },
    { name: 'integrations', testMatch: 'integrations.spec.ts', dependencies: ['hotwater'] },
  ],
  outputDir: 'e2e/results',
  timeout: 45_000,
  retries: 0,
  fullyParallel: true,
  reporter: [['list']],
  use: {
    baseURL: baseURL ?? MOCK_URL,
    timezoneId: E2E_TIMEZONE,
    storageState: clockState,
    httpCredentials: baseURL
      ? {
          username: process.env['E2E_USER'] ?? 'admin',
          password: process.env['E2E_PASSWORD'] ?? 'ovenbird-dev',
        }
      : undefined,
  },
  webServer: baseURL
    ? undefined
    : {
        command: `npx vite --mode mock --port ${MOCK_PORT} --strictPort --host 127.0.0.1`,
        url: MOCK_URL,
        reuseExistingServer: false,
        timeout: 60_000,
        env: { TZ: E2E_TIMEZONE },
      },
});
