import type { BrowserContext } from '@playwright/test';
import { CLOCK_COOKIE } from '../mock/scenario';

const CYCLE_MIN = 360;

/**
 * Cookie for the mock service clock: `shiftMin` minutes behind the browser.
 */
export function clockCookie(baseURL: string, shiftMin: number) {
  return { name: CLOCK_COOKIE, value: String(shiftMin), url: baseURL };
}

/**
 * Shift the mock service clock so it stands at `minute` of the 6-hour decision cycle now.
 */
export async function pinCycleMinute(
  context: BrowserContext,
  baseURL: string | undefined,
  minute: number,
): Promise<void> {
  const current = Math.floor(Date.now() / 60_000) % CYCLE_MIN;
  const shift = (((current - minute) % CYCLE_MIN) + CYCLE_MIN) % CYCLE_MIN;
  await context.addCookies([clockCookie(baseURL ?? 'http://127.0.0.1', shift)]);
}
